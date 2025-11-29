import os
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import db as rtdb_admin_module # Realtime DB এর জন্য

# ==========================================
# ১. কনফিগারেশন এবং সেটআপ
# ==========================================

# লগিং সেটআপ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভেরিয়েবল থেকে তথ্য নেওয়া
BOT_TOKEN = os.getenv("BOT_TOKEN")  
ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID") 
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT") 

# হোস্টিং কনফিগারেশন
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com" # আপনার Realtime DB URL

# ফায়ারবেস ইনিশিয়ালাইজেশন (নিরাপদ ব্লক)
db = None # Firestore ক্লায়েন্ট
rtdb = None # Realtime DB ক্লায়েন্ট

try:
    if FIREBASE_JSON:
        # JSON লোড করার সময় এরর হ্যান্ডেল করা
        try:
            cred_info = json.loads(FIREBASE_JSON)
            cred = credentials.Certificate(cred_info)
            
            # Realtime Database URL যোগ করে Firebase Initialize করা
            firebase_admin.initialize_app(cred, {
                'databaseURL': REALTIME_DATABASE_URL
            })
            
            db = firestore.client() # Firestore ক্লায়েন্ট
            rtdb = rtdb_admin_module.reference() # Realtime DB ক্লায়েন্ট

            logger.info("✅ Firebase Connected Successfully!")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Firebase JSON Decode Error: Check FIREBASE_SERVICE_ACCOUNT string. Error: {e}")
        except Exception as e:
            logger.error(f"❌ Firebase Initialization Failed: {e}")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT not found! Running without database.")
except Exception as e:
    # অন্যান্য মারাত্মক এরর হ্যান্ডেল করা
    logger.error(f"❌ A critical error occurred during global setup: {e}")

# লিংক কনফিগারেশন
LINKS = {
    "REVIEW_GEN": "https://sites.google.com/view/review-generator/home",
    "FB_GROUP": "https://www.facebook.com/groups/YOUR_GROUP_ID",
    "SUPPORT": "@AfMdshakil",
    "TG_CHANNEL_PAYMENT": "https://t.me/brotheritltd",
}

# প্রাথমিক সেটিংস
COLLECTION_USERS = "users"
COLLECTION_SUBMISSIONS = "submissions"

# ==========================================
# ২. ডাটাবেস ফাংশন (Core Logic)
# ==========================================

# ইউজার অ্যাকাউন্টের স্ট্যাটাস চেক/তৈরি
async def get_or_create_user(user_id, username, first_name):
    if db is None:
        return {"status": "NO_DB"}
    
    user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
    user_data = user_ref.get().to_dict()
    
    if user_data:
        if user_data.get('is_blocked', False):
            return {"status": "blocked"}
        return {"status": "exists", "data": user_data}
    else:
        new_user = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'balance': 0.0,
            'referred_by': None,
            'joined_at': firestore.SERVER_TIMESTAMP,
            'is_blocked': False
        }
        user_ref.set(new_user)
        return {"status": "created", "data": new_user}

# ব্যালেন্স আপডেট
async def update_balance(user_id, amount):
    if db is None:
        return False
    
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_ref.update({'balance': firestore.Increment(amount)})
        return True
    except Exception as e:
        logger.error(f"Error updating balance for {user_id}: {e}")
        return False

# ব্যালেন্স চেক
async def get_balance(user_id):
    if db is None: return 0.0
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict().get("balance", 0.0)
    return 0.0

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username if user.username else 'N/A'
    first_name = user.first_name

    # ১. ইউজার ডেটা চেক ও তৈরি
    result = await get_or_create_user(user_id, username, first_name)
    
    if result.get("status") == "blocked":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে বট ব্যবহার থেকে ব্লক করা হয়েছে।")
        return
    
    is_created = (result.get("status") == "created")

    # ২. ইসলামিক সালাম ও স্বাগত বার্তা
    if is_created:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম। আপনি স্বয়ংক্রিয়ভাবে নিবন্ধিত হয়েছেন।"
    else:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"

    # ৩. ডাটাবেস এরর মেসেজ (যদি থাকে)
    if result.get("status") == "NO_DB":
        welcome_message += "\n\n⚠️ **সতর্কতা:** ডাটাবেস কানেকশন ব্যর্থ হয়েছে। অ্যাকাউন্ট ব্যালেন্স ও অন্যান্য ফিচার কাজ করবে না।"

    # ৪. মূল মেনু বাটন তৈরি
    keyboard = [
        [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work")],
        [InlineKeyboardButton("👤 আমার অ্যাকাউন্ট", callback_data="show_account"),
         InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")],
        [InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
        [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # মেইন মেনুতে ফিরে যাওয়া
    if data == "back_to_main":
        await start_command(update, context)
        return

    if data == "submit_work":
        await query.edit_message_text(text="কাজ জমা দেওয়ার প্রক্রিয়া শুরু হয়েছে।\n\nপ্রথমে আপনার **স্ক্রিনশট লিংকটি** দিন।")
    
    elif data == "show_account":
        balance = await get_balance(user_id)
        db_status_text = "অনলাইন" if db else "অফলাইন"
        
        text = (
            f"👤 <b>আপনার অ্যাকাউন্ট</b>\n\n"
            f"🆔 আইডি: <code>{user_id}</code>\n"
            f"💰 বর্তমান ব্যালেন্স: {balance:.2f} BDT\n"
            f"🔗 ডাটাবেস স্ট্যাটাস: {db_status_text}"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data == "show_links":
        links_text = (
            f"🌐 <b>গুরুত্বপূর্ণ লিংক সমূহ:</b>\n\n"
            f"১. ফেসবুক গ্রুপ: <a href='{LINKS['FB_GROUP']}'>এখানে ক্লিক করুন</a>\n"
            f"২. পেমেন্ট প্রমাণ চ্যানেল: <a href='{LINKS['TG_CHANNEL_PAYMENT']}'>এখানে ক্লিক করুন</a>\n"
            f"৩. অ্যাডমিনের সাথে যোগাযোগ: {LINKS['SUPPORT']}"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(links_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML', disable_web_page_preview=True)
        
    elif data == "show_guide":
        # কাজের বিবরণ একটি হার্ডকোড করা টেক্সট
        guide_text = (
            f"📚 <b>কাজের বিবরণ ও নির্দেশিকা</b>\n\n"
            f"আমাদের কাজগুলো হলো মূলত বিভিন্ন সাইটে রিভিউ বা রেটিং দেওয়া।\n\n"
            f"১. 'কাজ জমা দিন' অপশন ব্যবহার করে আপনার কাজের স্ক্রিনশট লিংক দিন।\n"
            f"২. অ্যাডমিন যাচাই করার পর আপনার অ্যাকাউন্টে টাকা যোগ হবে।\n"
            f"৩. পেমেন্টের প্রমাণ দেখতে পেমেন্ট চ্যানেলে চোখ রাখুন।"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


# ==========================================
# ৪. অ্যাডমিন কমান্ড (Admin Handlers)
# ==========================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    
    # শুধু অ্যাডমিন এক্সেস পাবে
    if ADMIN_USER_ID_STR is None or ADMIN_USER_ID_STR != user_id: 
        await update.message.reply_text("🚫 আপনি অ্যাডমিন নন। এই কমান্ডটি আপনার জন্য নয়।")
        return
    
    if db is None:
        await update.message.reply_text("⚠️ **অ্যাডমিন প্যানেল:** ডাটাবেস কানেকশন নেই, কোনো ফিচার কাজ করবে না।")
        return

    # অ্যাডমিন প্যানেল মেনু তৈরি
    keyboard = [
        [InlineKeyboardButton("👥 ইউজার সংখ্যা দেখুন", callback_data="admin_user_count"),
         InlineKeyboardButton("📢 গণবার্তা পাঠান", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💰 ব্যালেন্স অ্যাড করুন", callback_data="admin_add_balance")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("👑 <b>অ্যাডমিন প্যানেল</b>\n\nদয়া করে অপশন নির্বাচন করুন:", reply_markup=reply_markup, parse_mode='HTML')

# ==========================================
# ৫. প্রধান রান ফাংশন (Main Function)
# ==========================================

def main() -> None:
    """বট অ্যাপ্লিকেশন শুরু করে"""
    if not BOT_TOKEN:
        logger.error("❌ Error: BOT_TOKEN is missing! Please set the environment variable.")
        return # টোকেন না থাকলে প্রোগ্রাম বন্ধ হবে

    application = Application.builder().token(BOT_TOKEN).build()

    # ইউজার কমান্ড
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # অ্যাডমিন কমান্ড
    application.add_handler(CommandHandler("admin", admin_command))
    
    # Webhook সেটআপ (24/7 লাইভ রাখার জন্য)
    if WEBHOOK_URL:
        logger.info(f"🚀 Starting Webhook on Port {PORT}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        # Polling মোড (টেস্টিং এর জন্য)
        logger.warning("⚠️ WEBHOOK_URL not set. Running in Polling mode.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
