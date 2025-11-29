import os
import logging
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# ১. কনফিগারেশন এবং সেটআপ
# ==========================================

# লগিং সেটআপ (ত্রুটি দেখার জন্য)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভেরিয়েবল থেকে তথ্য নেওয়া
BOT_TOKEN = os.getenv("BOT_TOKEN")  # আপনার বটের টোকেন
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")  # আপনার টেলিগ্রাম আইডি
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT") # ফায়ারবেস JSON টেক্সট
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # রেন্ডার বা হোস্টিং সাইটের লিঙ্ক

# ফায়ারবেস ইনিশিয়ালাইজেশন
db = None
try:
    if FIREBASE_JSON:
        cred_info = json.loads(FIREBASE_JSON)
        cred = credentials.Certificate(cred_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("✅ Firebase Connected Successfully!")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT not found! Database features won't work.")
except Exception as e:
    logger.error(f"❌ Firebase Error: {e}")

# লিংক এবং টেক্সট কনফিগারেশন
LINKS = {
    "REVIEW_GEN": "https://sites.google.com/view/review-generator/home",
    "FB_GROUP": "https://www.facebook.com/groups/YOUR_GROUP_ID",
    "SUPPORT": "@AfMdshakil",
}

# ==========================================
# ২. ডাটাবেস ফাংশন
# ==========================================

async def check_user_db(user):
    """ইউজার ডাটাবেসে আছে কিনা চেক করে, না থাকলে তৈরি করে"""
    if db is None:
        return None
    
    user_ref = db.collection("users").document(str(user.id))
    doc = user_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        if data.get("is_blocked", False):
            return "BLOCKED"
        return "EXISTS"
    else:
        # নতুন ইউজার তৈরি
        new_user = {
            "user_id": user.id,
            "first_name": user.first_name,
            "username": user.username,
            "balance": 0.0,
            "joined_at": firestore.SERVER_TIMESTAMP,
            "is_blocked": False
        }
        user_ref.set(new_user)
        return "CREATED"

async def get_balance(user_id):
    """ইউজারের ব্যালেন্স চেক করা"""
    if db is None: return 0.0
    doc = db.collection("users").document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict().get("balance", 0.0)
    return 0.0

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (কমান্ড)
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # ডাটাবেস চেক
    status = await check_user_db(user)
    
    if status == "BLOCKED":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে ব্যান করা হয়েছে।")
        return

    welcome_text = (
        f"আসসালামু আলাইকুম, <b>{user.first_name}</b>! 👋\n\n"
        "Skyzone IT বটে আপনাকে স্বাগতম। নিচের মেনু থেকে অপশন সিলেক্ট করুন:"
    )

    # বাটন মেনু
    keyboard = [
        [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work")],
        [InlineKeyboardButton("👤 প্রোফাইল", callback_data="my_profile"),
         InlineKeyboardButton("📚 হেল্প", callback_data="help_guide")],
        [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS["REVIEW_GEN"])]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # লোডিং আইকন বন্ধ করার জন্য
    
    data = query.data
    user_id = query.from_user.id

    if data == "submit_work":
        await query.edit_message_text("📸 অনুগ্রহ করে আপনার কাজের স্ক্রিনশট বা লিংক এখানে পেস্ট করুন।")
        # এখানে আপনি পরবর্তীতে MessageHandler যুক্ত করতে পারেন ইনপুট নেওয়ার জন্য।

    elif data == "my_profile":
        bal = await get_balance(user_id)
        text = (
            f"👤 <b>আপনার প্রোফাইল</b>\n\n"
            f"🆔 আইডি: <code>{user_id}</code>\n"
            f"💰 ব্যালেন্স: {bal} BDT\n"
            f"🔗 স্ট্যাটাস: একটিভ"
        )
        # ব্যাক বাটন
        back_btn = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode='HTML')

    elif data == "help_guide":
        text = (
            f"❓ <b>সাহায্য কেন্দ্র</b>\n\n"
            f"যে কোনো সমস্যার জন্য যোগাযোগ করুন:\n"
            f"👨‍💻 অ্যাডমিন: {LINKS['SUPPORT']}\n"
            f"ফেসবুক গ্রুপ: <a href='{LINKS['FB_GROUP']}'>এখানে ক্লিক করুন</a>"
        )
        back_btn = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode='HTML', disable_web_page_preview=True)

    elif data == "back_to_main":
        # আবার মেইন মেনু দেখানো
        await start(update, context)

# ==========================================
# ৪. অ্যাডমিন হ্যান্ডেলার
# ==========================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # শুধু অ্যাডমিন এক্সেস পাবে
    if str(ADMIN_USER_ID) != user_id:
        return # চুপচাপ ইগনোর করবে অথবা এরর মেসেজ দিতে পারেন

    keyboard = [
        [InlineKeyboardButton("📊 ইউজার লিস্ট", callback_data="admin_users")],
        [InlineKeyboardButton("📢 ব্রডকাস্টিং", callback_data="admin_broadcast")]
    ]
    await update.message.reply_text("👑 <b>অ্যাডমিন প্যানেল</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# ==========================================
# ৫. মেইন রানার
# ==========================================

def main():
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN is missing!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # হ্যান্ডেলার যোগ করা
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(button_click))

    # সার্ভার কনফিগারেশন (Webhook vs Polling)
    if WEBHOOK_URL:
        # সার্ভারে (যেমন Render/Railway) চলার জন্য
        print(f"🚀 Starting Webhook on Port {PORT}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        # নিজের পিসিতে টেস্ট করার জন্য
        print("🤖 Starting Polling (Local Mode)...")
        application.run_polling()

if __name__ == "__main__":
    main()
