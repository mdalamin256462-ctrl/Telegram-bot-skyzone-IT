import os
import logging
import json 
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import db 

# Logging সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ====================================================================
# A. কনফিগারেশন ভ্যারিয়েবল লোড ও Firebase ইনিশিয়ালাইজেশন 
# ====================================================================

# 1. টেলিগ্রাম কনফিগারেশন (আপনার টোকেন সরাসরি বসানো হয়েছে)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8406630077:AAEx91ea3QBjF1b1HufHmYkk72t6xtypRd0") # ✅ আপনার টোকেন
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "7870088579")) 
ADMIN_GROUP_CHAT_ID = os.environ.get("ADMIN_GROUP_CHAT_ID", "-5054092329") 

# 2. Firebase কনফিগারেশন (সুরক্ষিত পদ্ধতি: JSON স্ট্রিং Environment Variable থেকে নেবে)
FIREBASE_CONFIG_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT") 
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com"

db = None # Firestore ক্লায়েন্ট
rtdb = None # Realtime DB ক্লায়েন্ট

if FIREBASE_CONFIG_JSON:
    try:
        # JSON স্ট্রিং লোড করে প্রমাণীকরণ
        cred_dict = json.loads(FIREBASE_CONFIG_JSON)
        cred = credentials.Certificate(cred_dict)
        
        # Realtime Database URL যোগ করে Firebase Initialize করা
        firebase_admin.initialize_app(cred, {
            'databaseURL': REALTIME_DATABASE_URL
        })
        
        db = firestore.client() # Firestore ক্লায়েন্ট
        rtdb = firebase_admin.db.reference() # Realtime DB ক্লায়েন্ট

        logging.info("Firebase Successfully Initialized with both DBs.")
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        db = None
        rtdb = None
else:
    logging.error("FIREBASE_SERVICE_ACCOUNT environment variable not found. Check hosting settings.")
    db = None
    rtdb = None

# 3. হোস্টিং কনফিগারেশন (Render/Railway এর জন্য Webhook)
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'YOUR_RENDER_APP_URL')

# 4. লিঙ্ক কনফিগারেশন (আপনার দেওয়া লিঙ্কগুলো)
LINKS = {
    "REVIEW_GEN": "https://sites.google.com/view/review-generator/home",
    "FB_GROUP": "https://www.facebook.com/groups/1853319645292519/?ref=share&mibextid=NSMWBT",
    "TG_CHANNEL_PAYMENT": "https://t.me/brotheritltd",
    "ADMIN_USERNAME": "@AfMdshakil",
    # বাকি লিঙ্কগুলো এখানে যোগ হবে
}

# 5. প্রাথমিক সেটিংস
INITIAL_REFERRAL_BONUS = 50 
COLLECTION_USERS = "users"
COLLECTION_SUBMISSIONS = "submissions"

# ====================================================================
# B. Firebase ডেটাবেস ফাংশন (Core Logic)
# ====================================================================

# ইউজার অ্যাকাউন্টের স্ট্যাটাস চেক/তৈরি
async def get_or_create_user(user_id, username, first_name):
    if db is None:
        return None
    
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
            'balance': 0,
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
    
    user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
    user_ref.update({'balance': firestore.Increment(amount)})
    return True

# ====================================================================
# C. ইউজার কমান্ড ও হ্যান্ডেলার (User Handlers)
# ====================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username if user.username else 'N/A'
    first_name = user.first_name

    # 1. ইউজার ডেটা চেক ও তৈরি
    result = await get_or_create_user(user_id, username, first_name)
    
    if result and result.get("status") == "blocked":
        await update.message.reply_text("দুঃখিত! আপনাকে বট ব্যবহার থেকে ব্লক করা হয়েছে।")
        return

    # 2. ইসলামিক সালাম ও স্বাগত বার্তা
    if result and result.get("status") == "created":
        welcome_message = f"আসসালামু আলাইকুম, **{first_name}**! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম। আপনি স্বয়ংক্রিয়ভাবে নিবন্ধিত হয়েছেন।"
    else:
        welcome_message = f"আসসালামু আলাইকুম, **{first_name}**! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"

    # 3. মূল মেনু বাটন তৈরি
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
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "submit_work":
        await query.edit_message_text(text="কাজ জমা দেওয়ার প্রক্রিয়া শুরু হয়েছে।\n\nপ্রথমে আপনার **স্ক্রিনশট লিংকটি** দিন।")
    
    elif query.data == "show_account":
        user_id = query.from_user.id
        await query.edit_message_text(text=f"👤 **আপনার অ্যাকাউন্ট**\n\nবর্তমান ব্যালেন্স: 0 BDT (ডেটাবেস থেকে আসবে)\nরেফারেল লিংক: <আপনার রেফারেল লিংক>")
    
    elif query.data == "show_links":
        links_text = f"🌐 **গুরুত্বপূর্ণ লিংক সমূহ:**\n\n"
        links_text += f"১. ফেসবুক গ্রুপ: {LINKS['FB_GROUP']}\n"
        links_text += f"২. পেমেন্ট প্রমাণ চ্যানেল: {LINKS['TG_CHANNEL_PAYMENT']}\n"
        links_text += f"৩. অ্যাডমিনের সাথে যোগাযোগ: {LINKS['ADMIN_USERNAME']}\n"
        
        await query.edit_message_text(text=links_text)

# ====================================================================
# D. অ্যাডমিন কমান্ড (Admin Handlers)
# ====================================================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("🚫 আপনি অ্যাডমিন নন। এই কমান্ডটি আপনার জন্য নয়।")
        return
    
    # অ্যাডমিন প্যানেল মেনু তৈরি
    keyboard = [
        [InlineKeyboardButton("👥 ইউজার সংখ্যা দেখুন", callback_data="admin_user_count"),
         InlineKeyboardButton("📢 গণবার্তা পাঠান", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💰 রেফারেল বোনাস সেট করুন", callback_data="admin_set_referral")],
        [InlineKeyboardButton("🗑️ ইউজার ব্লক/ডিলিট", callback_data="admin_manage_user")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("👑 **অ্যাডমিন প্যানেল**\n\nদয়া করে অপশন নির্বাচন করুন:", reply_markup=reply_markup)

# ====================================================================
# E. প্রধান রান ফাংশন (Main Function)
# ====================================================================

def main() -> None:
    """বট অ্যাপ্লিকেশন শুরু করে"""
    application = Application.builder().token(BOT_TOKEN).build()

    # ইউজার কমান্ড
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # অ্যাডমিন কমান্ড
    application.add_handler(CommandHandler("admin", admin_command))
    
    # ⚠️ Webhook সেটআপ (24/7 লাইভ রাখার জন্য)
    if WEBHOOK_URL and WEBHOOK_URL != 'YOUR_RENDER_APP_URL':
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
        logging.info(f"Webhook set on port {PORT}")
    else:
        # Polling মোড (টেস্টিং এর জন্য)
        logging.warning("WEBHOOK_URL not set. Running in Polling mode (Not suitable for 24/7 Free hosting).")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
