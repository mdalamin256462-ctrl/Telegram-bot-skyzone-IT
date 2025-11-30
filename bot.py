import os
import logging
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# ContextTypes ইমপোর্ট নিশ্চিত করা হয়েছে
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

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
# রিয়েলটাইম ডাটাবেস ইউআরএল আপনার প্রজেক্ট অনুযায়ী পরিবর্তন করুন
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com" 

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

# ফ্লো স্টেটস (কাজ জমা দেওয়ার জন্য)
STATE_AWAITING_LINK = 1

# ==========================================
# ২. ডাটাবেস ফাংশন (Core Logic)
# ==========================================

# ইউজার অ্যাকাউন্টের স্ট্যাটাস চেক/তৈরি
async def get_or_create_user(user_id, username, first_name):
    """ইউজার ডাটাবেসে আছে কিনা চেক করে, না থাকলে তৈরি করে"""
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
            'is_blocked': False,
            'state': 0 # স্টেট যোগ করা হলো
        }
        user_ref.set(new_user)
        return {"status": "created", "data": new_user}

# ব্যালেন্স আপডেট
async def update_balance(user_id, amount):
    """ইউজারের ব্যালেন্স আপডেট করা"""
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
    """ইউজারের বর্তমান ব্যালেন্স চেক করা"""
    if db is None: return 0.0
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict().get("balance", 0.0)
    return 0.0

# ইউজার স্টেট আপডেট
async def update_user_state(user_id, state):
    """ইউজারের কনভারসেশন স্টেট আপডেট করে"""
    if db is None: return
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_ref.update({'state': state})
    except Exception as e:
        logger.error(f"Error updating state for {user_id}: {e}")

# ইউজার স্টেট পাওয়া
async def get_user_state(user_id):
    """ইউজারের কনভারসেশন স্টেট পায়"""
    if db is None: return 0
    try:
        doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict().get("state", 0)
    except Exception as e:
        logger.error(f"Error getting state for {user_id}: {e}")
    return 0

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start কমান্ড হ্যান্ডেল করে এবং প্রাথমিক মেনু দেখায়"""
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

    # স্টেট রিসেট করা
    await update_user_state(user_id, 0) 

    # ২. ইসলামিক সালাম ও স্বাগত বার্তা
    if is_created:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম। আপনি স্বয়ংক্রিয়ভাবে নিবন্ধিত হয়েছেন।"
    else:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"

    # ৩. ডাটাবেস এরর মেসেজ (যদি থাকে)
    if result.get("status") == "NO_DB":
        welcome_message += "\n\n⚠️ <b>সতর্কতা:</b> ডাটাবেস কানেকশন ব্যর্থ হয়েছে। অ্যাকাউন্ট ব্যালেন্স ও অন্যান্য ফিচার কাজ করবে না।"

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
    """ইনলাইন বাটন ক্লিক হ্যান্ডেল করে"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # মেইন মেনুতে ফিরে যাওয়া (স্টেট রিসেট)
    if data == "back_to_main":
        await update_user_state(user_id, 0) 
        first_name = query.from_user.first_name
        
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"
        
        keyboard = [
            [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work")],
            [InlineKeyboardButton("👤 আমার অ্যাকাউন্ট", callback_data="show_account"),
             InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")],
            [InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
            [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return

    if data == "submit_work":
        # ১. স্টেট আপডেট
        await update_user_state(user_id, STATE_AWAITING_LINK)
        
        # ২. ইউজারকে লিংক দিতে বলা
        await query.edit_message_text(
            text="কাজ জমা দেওয়ার প্রক্রিয়া শুরু হয়েছে।\n\nপ্রথমে আপনার <b>স্ক্রিনশট লিংকটি</b> দিন।\n\nবাতিল করতে /start লিখুন।",
            parse_mode='HTML'
        )
    
    elif data == "show_account":
        balance = await get_balance(user_id)
        db_status_text = "অনলাইন (🟢)" if db else "অফলাইন (🔴)"
        
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
        # কাজের বিবরণ
        guide_text = (
            f"📚 <b>কাজের বিবরণ ও নির্দেশিকা</b>\n\n"
            f"আমাদের কাজগুলো হলো মূলত বিভিন্ন সাইটে রিভিউ বা রেটিং দেওয়া।\n\n"
            f"১. 'কাজ জমা দিন' অপশন ব্যবহার করে আপনার কাজের স্ক্রিনশট লিংক দিন।\n"
            f"২. অ্যাডমিন যাচাই করার পর আপনার অ্যাকাউন্টে টাকা যোগ হবে।\n"
            f"৩. পেমেন্টের প্রমাণ দেখতে পেমেন্ট চ্যানেলে চোখ রাখুন।"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাধারণ মেসেজগুলি হ্যান্ডেল করে, বিশেষ করে যখন ইউজার একটি স্টেটে থাকে"""
    user_id = update.effective_user.id
    
    if not db:
        await update.message.reply_text("⚠️ ডাটাবেস কানেকশন নেই। কাজ জমা দেওয়া যাবে না।")
        return
    
    current_state = await get_user_state(user_id)
    text = update.message.text
    
    if current_state == STATE_AWAITING_LINK:
        # এখানে লিংক যাচাই করার সহজ কোড দেওয়া হলো
        if text.startswith('http'):
            # ১. সাবমিশন ডাটাবেসে সেভ করা
            submission_data = {
                'user_id': user_id,
                'username': update.effective_user.username,
                'link': text,
                'status': 'pending',
                'submitted_at': firestore.SERVER_TIMESTAMP
            }
            db.collection(COLLECTION_SUBMISSIONS).add(submission_data)
            
            # ২. স্টেট রিসেট করা
            await update_user_state(user_id, 0)
            
            # ৩. ইউজারকে নিশ্চিত বার্তা দেওয়া
            await update.message.reply_text(
                "✅ <b>কাজ সফলভাবে জমা দেওয়া হয়েছে!</b>\n\n"
                "অ্যাডমিন শীঘ্রই আপনার কাজটি যাচাই করবেন। যাচাই শেষ হলে আপনার অ্যাকাউন্টে টাকা যোগ হবে।",
                parse_mode='HTML'
            )
            
            # ৪. অ্যাডমিনকে নোটিফিকেশন পাঠানো (ঐচ্ছিক)
            if ADMIN_USER_ID_STR:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID_STR,
                        text=f"🔔 <b>নতুন কাজ জমা পড়েছে!</b>\n"
                             f"ইউজার ID: <code>{user_id}</code>\n"
                             f"ইউজার: @{update.effective_user.username or update.effective_user.first_name}\n"
                             f"লিংক: <a href='{text}'>{text}</a>",
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Error sending admin notification: {e}")
        else:
            await update.message.reply_text("❌ এটি বৈধ লিংক নয়। দয়া করে স্ক্রিনশটের সম্পূর্ণ লিংক দিন। বাতিল করতে /start লিখুন।")
    
    elif current_state == 0:
        # যদি কোনো স্টেট না থাকে এবং ইউজার কোনো টেক্সট মেসেজ দেয়
        await update.message.reply_text("আমি এই মেসেজটি বুঝতে পারিনি। দয়া করে মেনু থেকে অপশন নির্বাচন করুন বা /start টাইপ করে প্রধান মেনুতে যান।")

# ==========================================
# ৪. অ্যাডমিন কমান্ড (Admin Handlers)
# ==========================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin কমান্ড হ্যান্ডেল করে"""
    user_id = str(update.effective_user.id)
    
    # শুধু অ্যাডমিন এক্সেস পাবে
    if ADMIN_USER_ID_STR is None or ADMIN_USER_ID_STR != user_id: 
        await update.message.reply_text("🚫 আপনি অ্যাডমিন নন। এই কমান্ডটি আপনার জন্য নয়।")
        return
    
    if db is None:
        await update.message.reply_text("⚠️ <b>অ্যাডমিন প্যানেল:</b> ডাটাবেস কানেকশন নেই, কোনো ফিচার কাজ করবে না।", parse_mode='HTML')
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
        return 

    # >>> V20 ফিক্স: ContextTypes কনফিগারেশন ত্রুটিমুক্ত করা হলো <<<
    # ContextTypes.DEFAULT_TYPE() ক্লাসটিকে ইনস্ট্যান্টটিট করা
    defaults = ContextTypes.DEFAULT_TYPE()
    # allowed_updates আলাদাভাবে সেট করা হয়েছে, যাতে TypeError না আসে
    defaults.allowed_updates = Update.ALL_TYPES 
    
    # application.builder() ব্যবহার করে অ্যাপ্লিকেশন তৈরি
    application = Application.builder().token(BOT_TOKEN).context_types(defaults).build()

    # হ্যান্ডেলার যোগ করা
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # সকল টেক্সট মেসেজ হ্যান্ডেল করার জন্য MessageHandler যোগ করা
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Webhook সেটআপ
    if WEBHOOK_URL:
        logger.info(f"🚀 Starting Webhook on Port {PORT}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        # Polling মোড
        logger.warning("⚠️ WEBHOOK_URL not set. Running in Polling mode.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
