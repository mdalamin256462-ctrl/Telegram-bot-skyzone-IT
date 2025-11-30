import os
import logging
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Firebase Imports
import firebase_admin
from firebase_admin import credentials, firestore, db as realtime_db

# ==========================================
# ১. কনফিগারেশন এবং সেটআপ
# ==========================================

# লগিং সেটআপ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভেরিয়েবল
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID")
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get('PORT', 8080))

# রিয়েলটাইম ডাটাবেস ইউআরএল (আপনার প্রজেক্ট অনুযায়ী এটি নিশ্চিত করুন)
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com"

# ফায়ারবেস ইনিশিয়ালাইজেশন
db = None  # Firestore ক্লায়েন্ট
rtdb = None  # Realtime DB ক্লায়েন্ট

try:
    if FIREBASE_JSON:
        try:
            cred_info = json.loads(FIREBASE_JSON)
            cred = credentials.Certificate(cred_info)
            
            # Firebase অ্যাপ চেক করে ইনিশিয়ালাইজ করা
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {
                    'databaseURL': REALTIME_DATABASE_URL
                })
            
            db = firestore.client()
            rtdb = realtime_db.reference()
            logger.info("✅ Firebase Connected Successfully!")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Firebase JSON Decode Error: {e}")
        except Exception as e:
            logger.error(f"❌ Firebase Initialization Failed: {e}")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT not found! Running without database.")
except Exception as e:
    logger.error(f"❌ Critical setup error: {e}")

# লিংক কনফিগারেশন
LINKS = {
    "REVIEW_GEN": "https://sites.google.com/view/review-generator/home",
    "FB_GROUP": "https://www.facebook.com/groups/YOUR_GROUP_ID",
    "SUPPORT": "@AfMdshakil",
    "TG_CHANNEL_PAYMENT": "https://t.me/brotheritltd",
}

# কালেকশন নাম
COLLECTION_USERS = "users"
COLLECTION_SUBMISSIONS = "submissions"

# ফ্লো স্টেটস
STATE_AWAITING_LINK = 1

# ==========================================
# ২. ডাটাবেস ফাংশন
# ==========================================

async def get_or_create_user(user_id, username, first_name):
    if db is None:
        return {"status": "NO_DB"}
    
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_doc = user_ref.get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
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
                'state': 0
            }
            user_ref.set(new_user)
            return {"status": "created", "data": new_user}
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return {"status": "NO_DB"}

async def get_balance(user_id):
    if db is None: return 0.0
    try:
        doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict().get("balance", 0.0)
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
    return 0.0

async def update_user_state(user_id, state):
    if db is None: return
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_ref.update({'state': state})
    except Exception as e:
        logger.error(f"Error updating state for {user_id}: {e}")

async def get_user_state(user_id):
    if db is None: return 0
    try:
        doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict().get("state", 0)
    except Exception as e:
        logger.error(f"Error getting state for {user_id}: {e}")
    return 0

# ==========================================
# ৩. ইউজার হ্যান্ডেলার
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username if user.username else 'N/A'
    first_name = user.first_name

    result = await get_or_create_user(user_id, username, first_name)
    
    if result.get("status") == "blocked":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে ব্লক করা হয়েছে।")
        return
    
    is_created = (result.get("status") == "created")
    await update_user_state(user_id, 0) 

    if is_created:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম।"
    else:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"

    if result.get("status") == "NO_DB":
        welcome_message += "\n\n⚠️ <b>সতর্কতা:</b> ডাটাবেস অফলাইন।"

    keyboard = [
        [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work")],
        [InlineKeyboardButton("👤 আমার অ্যাকাউন্ট", callback_data="show_account"),
         InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")],
        [InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
        [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "back_to_main":
        await update_user_state(user_id, 0) 
        first_name = query.from_user.first_name
        
        keyboard = [
            [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work")],
            [InlineKeyboardButton("👤 আমার অ্যাকাউন্ট", callback_data="show_account"),
             InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")],
            [InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
            [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"আসসালামু আলাইকুম, <b>{first_name}</b>!", reply_markup=reply_markup, parse_mode='HTML')
        return

    if data == "submit_work":
        await update_user_state(user_id, STATE_AWAITING_LINK)
        await query.edit_message_text(
            "কাজ জমা দেওয়ার জন্য আপনার <b>স্ক্রিনশট লিংকটি</b> দিন।\n\nবাতিল করতে /start লিখুন।",
            parse_mode='HTML'
        )
    
    elif data == "show_account":
        balance = await get_balance(user_id)
        db_status = "অনলাইন (🟢)" if db else "অফলাইন (🔴)"
        text = f"👤 <b>অ্যাকাউন্ট</b>\nID: <code>{user_id}</code>\nBalance: {balance:.2f} BDT\nDB: {db_status}"
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data == "show_links":
        text = f"🌐 <b>লিংক সমূহ:</b>\n1. <a href='{LINKS['FB_GROUP']}'>ফেসবুক গ্রুপ</a>\n2. <a href='{LINKS['TG_CHANNEL_PAYMENT']}'>পেমেন্ট চ্যানেল</a>\n3. সাপোর্ট: {LINKS['SUPPORT']}"
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML', disable_web_page_preview=True)
        
    elif data == "show_guide":
        text = "📚 <b>নির্দেশিকা</b>\nকাজের স্ক্রিনশট লিংক জমা দিন। অ্যাডমিন চেক করে পেমেন্ট দিবে।"
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not db:
        await update.message.reply_text("⚠️ ডাটাবেস নেই।")
        return
    
    current_state = await get_user_state(user_id)
    text = update.message.text
    
    if current_state == STATE_AWAITING_LINK:
        if text.startswith('http'):
            submission = {
                'user_id': user_id,
                'username': update.effective_user.username,
                'link': text,
                'status': 'pending',
                'submitted_at': firestore.SERVER_TIMESTAMP
            }
            db.collection(COLLECTION_SUBMISSIONS).add(submission)
            await update_user_state(user_id, 0)
            
            await update.message.reply_text("✅ কাজ জমা হয়েছে! অ্যাডমিন চেক করবে।")
            
            # অ্যাডমিন নোটিফিকেশন
            if ADMIN_USER_ID_STR:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID_STR,
                        text=f"🔔 <b>নতুন কাজ!</b>\nUser: {user_id}\nLink: {text}",
                        parse_mode='HTML'
                    )
                except:
                    pass
        else:
            await update.message.reply_text("❌ বৈধ লিংক দিন।")
    
    elif current_state == 0:
        await update.message.reply_text("দয়া করে মেনু ব্যবহার করুন। /start")

# ==========================================
# ৪. অ্যাডমিন কমান্ড
# ==========================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if not ADMIN_USER_ID_STR or ADMIN_USER_ID_STR != user_id:
        await update.message.reply_text("🚫 এক্সেস নেই।")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 ইউজার", callback_data="admin_user_count"),
         InlineKeyboardButton("📢 ব্রডকাস্ট", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💰 ব্যালেন্স", callback_data="admin_add_balance")]
    ]
    await update.message.reply_text("👑 <b>অ্যাডমিন প্যানেল</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# ==========================================
# ৫. মেইন ফাংশন
# ==========================================

def main() -> None:
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN missing! Check Environment Variables.")
        return 

    # Application তৈরি
    application = Application.builder().token(BOT_TOKEN).build()

    # হ্যান্ডেলার যোগ করা
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # সার্ভার রান করা
    if WEBHOOK_URL:
        logger.info(f"🚀 Starting Webhook on Port {PORT}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES
        )
    else:
        logger.warning("⚠️ Running in Polling mode.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
