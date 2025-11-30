import os
import logging
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Firebase Imports
import firebase_admin
from firebase_admin import credentials, firestore, db as realtime_db
from firebase_admin._messaging_utils import messaging_error

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

# আপনার Firebase Realtime Database URL
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com"

# ফায়ারবেস ইনিশিয়ালাইজেশন
db = None  # Firestore ক্লায়েন্ট
rtdb = None  # Realtime DB ক্লায়েন্ট

try:
    if FIREBASE_JSON:
        try:
            cred_info = json.loads(FIREBASE_JSON)
            cred = credentials.Certificate(cred_info)

            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {
                    'databaseURL': REALTIME_DATABASE_URL
                })

            db = firestore.client()
            rtdb = realtime_db.reference()
            # রেফার বোনাস ডিফল্ট সেট করা (যদি না থাকে)
            rtdb.child("ReferBonus").transaction(lambda current: current if current is not None else 3.00)
            logger.info("✅ Firebase Connected Successfully!")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Firebase JSON Decode Error: {e}")
        except Exception as e:
            logger.error(f"❌ Firebase Initialization Failed: {e}")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT not found! Running without database.")
except Exception as e:
    logger.error(f"❌ Critical setup error: {e}")

# লিংক কনফিগারেশন (আপনার নতুন ডেটা)
LINKS = {
    "REVIEW_GEN": "https://sites.google.com/view/review-generator/home",
    "FB_GROUP": "https://www.facebook.com/groups/1853319645292519/?ref=share&mibextid=NSMWBT",
    "FB_PAGE": "https://www.facebook.com/share/1BX4LQfrq9/",
    "YT_CHANNEL": "https://youtube.com/@af.mdshakil?si=QoHvBxpnY4-laCQi",
    "TG_GROUP": "https://t.me/Skyzone_IT_chat", 
    "TG_CHANNEL": "https://t.me/Skyzone_IT",
    "TG_CHANNEL_PAYMENT": "https://t.me/brotheritltd",
    "SUPPORT": "@AfMdshakil",
    "WEBSITE": "brotheritltd.com",
    "EMAIL": "raihan@brotheritltd.com",
}

# কালেকশন নাম
COLLECTION_USERS = "users"
COLLECTION_SUBMISSIONS = "submissions"
COLLECTION_WITHDRAWALS = "withdrawals"

# ফ্লো স্টেটস
STATE_IDLE = 0
STATE_SUB_SELECT_TYPE = 10 # কাজ জমার প্রকারভেদ নির্বাচন
STATE_SUB_MARKET_LINK = 11 # মার্কেটিং লিংক জমার জন্য (নতুন)
STATE_SUB_AWAITING_REVIEW_DATA = 12 # রিভিউ তথ্য জমার ধাপ শুরু
STATE_SUB_AWAITING_LINK = 13 # স্ক্রিনশট লিংক
STATE_SUB_AWAITING_EMAIL = 14 # রিভিউ ইমেইল
STATE_SUB_AWAITING_NAME = 15 # রিভিউ নাম
STATE_SUB_AWAITING_DEVICE = 16 # ডিভাইস নাম
STATE_WITHDRAW_AWAITING_AMOUNT = 20
STATE_WITHDRAW_AWAITING_METHOD = 21
STATE_WITHDRAW_AWAITING_NUMBER = 22

# অ্যাডমিন স্টেটস
STATE_ADMIN_AWAITING_BALANCE_USER_ID = 30
STATE_ADMIN_AWAITING_BALANCE_AMOUNT = 31
STATE_ADMIN_AWAITING_REFER_BONUS = 40
STATE_ADMIN_AWAITING_BROADCAST_MESSAGE = 50

# ==========================================
# ২. ডাটাবেস ফাংশন
# ==========================================

async def get_or_create_user(user_id, username, first_name, referred_by=None):
    if db is None: return {"status": "NO_DB"}
    
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_doc = user_ref.get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data.get('is_blocked', False):
                return {"status": "blocked"}
            return {"status": "exists", "data": user_data}
        else:
            # রেফারেল বোনাস যোগ করা
            referral_bonus = 0.0
            if referred_by and str(user_id) != str(referred_by):
                referral_bonus = await get_refer_bonus()
                await update_balance(referred_by, referral_bonus) # রেফারকারীকে বোনাস দেওয়া
                logger.info(f"Referral bonus {referral_bonus} given to {referred_by} by {user_id}")


            new_user = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'balance': referral_bonus, # নতুন ইউজারের ব্যালেন্সে বোনাস যোগ করা
                'referred_by': referred_by,
                'joined_at': firestore.SERVER_TIMESTAMP,
                'is_blocked': False,
                'state': STATE_IDLE,
                'temp_data': {} # মাল্টি-স্টেপ ফ্লোর জন্য
            }
            user_ref.set(new_user)
            return {"status": "created", "data": new_user}
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return {"status": "NO_DB"}

async def update_balance(user_id, amount):
    """ইউজারের ব্যালেন্স যোগ/বিয়োগ করা"""
    if db is None: return False
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_ref.update({'balance': firestore.Increment(amount)})
        return True
    except Exception as e:
        logger.error(f"Error updating balance for {user_id}: {e}")
        return False

async def get_user_data(user_id):
    """ইউজারের সম্পূর্ণ ডাটা পাওয়া"""
    if db is None: return None
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict()
    return None

async def get_balance(user_id):
    """ইউজারের বর্তমান ব্যালেন্স চেক করা"""
    data = await get_user_data(user_id)
    return data.get("balance", 0.0) if data else 0.0

async def update_user_state(user_id, state, temp_data=None):
    """ইউজারের স্টেট এবং টেম্পোরারি ডেটা আপডেট করা"""
    if db is None: return
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        update_fields = {'state': state}
        if temp_data is not None:
            update_fields['temp_data'] = temp_data
        
        user_ref.update(update_fields)
    except Exception as e:
        logger.error(f"Error updating state/temp_data for {user_id}: {e}")

async def get_user_state_and_data(user_id):
    """ইউজারের স্টেট এবং টেম্পোরারি ডেটা একসাথে পাওয়া"""
    data = await get_user_data(user_id)
    return data.get("state", STATE_IDLE) if data else STATE_IDLE, data.get("temp_data", {}) if data else {}

async def get_refer_bonus():
    """Realtime DB থেকে রেফার বোনাস পাওয়া"""
    if rtdb is None: return 3.00 # ডিফল্ট মান
    try:
        bonus = rtdb.child("ReferBonus").get()
        return float(bonus) if bonus else 3.00
    except Exception as e:
        logger.error(f"Error getting ReferBonus: {e}")
        return 3.00
        
async def set_refer_bonus(amount):
    """Realtime DB তে রেফার বোনাস সেট করা"""
    if rtdb is None: return False
    try:
        rtdb.child("ReferBonus").set(amount)
        return True
    except Exception as e:
        logger.error(f"Error setting ReferBonus: {e}")
        return False

async def get_all_user_ids():
    """Firestore থেকে সকল ইউজারের ID (ইনটেজার) এর তালিকা পাওয়া"""
    if db is None: return []
    try:
        # শুধুমাত্র user_id ফিল্ডটি সিলেক্ট করা হয়েছে
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        # এখানে user_id গুলোকে int-এ কনভার্ট করে একটি list-এ রাখা হচ্ছে
        return [doc.get('user_id') for doc in users if doc.get('user_id') is not None]
    except Exception as e:
        logger.error(f"Error getting all user IDs: {e}")
        return []

async def get_user_by_id(user_id):
    """ইউজার আইডি দিয়ে ইউজার ডাটা পাওয়া (ব্যালেন্স আপডেটের জন্য চেক)"""
    if db is None: return None
    try:
        doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start কমান্ড হ্যান্ডেল করে এবং প্রাথমিক মেনু দেখায়"""
    user = update.effective_user
    user_id = user.id
    username = user.username if user.username else 'N/A'
    first_name = user.first_name

    # রেফারেল আইডি হ্যান্ডেল করা
    referred_by = None
    if context.args and context.args[0].isdigit():
        referred_by = int(context.args[0])

    # ১. ইউজার ডেটা চেক ও তৈরি
    result = await get_or_create_user(user_id, username, first_name, referred_by)
    
    if result.get("status") == "blocked":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে বট ব্যবহার থেকে ব্লক করা হয়েছে।")
        return
    
    is_created = (result.get("status") == "created")

    # স্টেট রিসেট করা
    await update_user_state(user_id, STATE_IDLE) 

    # ২. স্বাগত বার্তা
    if is_created:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম। আপনি স্বয়ংক্রিয়ভাবে নিবন্ধিত হয়েছেন।"
        if result['data'].get('referred_by'):
             welcome_message += f"\n🎉 আপনি রেফারেল লিংক ব্যবহার করে এসেছেন! আপনার অ্যাকাউন্টে {result['data']['balance']:.2f} BDT যোগ করা হয়েছে।"
    else:
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"

    if result.get("status") == "NO_DB":
        welcome_message += "\n\n⚠️ <b>সতর্কতা:</b> ডাটাবেস অফলাইন।"

    # ৩. মূল মেনু বাটন তৈরি
    keyboard = [
        [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])], # ১. রিভিউ জেনারেটর (উপরে)
        [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work"), # ২. কাজ জমা দিন
         InlineKeyboardButton("📈 ব্যালেন্স", callback_data="show_account")], # ৩. ব্যালেন্স
        [InlineKeyboardButton("💸 উত্তোলন (Withdraw)", callback_data="start_withdraw"),
         InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
        [InlineKeyboardButton("👥 রেফার করুন", callback_data="show_referral_link")],
        [InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")], # কাজের বিবরণ নিচে
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
        await update_user_state(user_id, STATE_IDLE) 
        first_name = query.from_user.first_name
        
        welcome_message = f"আসসালামু আলাইকুম, <b>{first_name}</b>! 👋\n\nপ্রধান মেনু থেকে কাজ শুরু করুন।"
        
        keyboard = [
            [InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])],
            [InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work"),
             InlineKeyboardButton("📈 ব্যালেন্স", callback_data="show_account")],
            [InlineKeyboardButton("💸 উত্তোলন (Withdraw)", callback_data="start_withdraw"),
             InlineKeyboardButton("🔗 সব লিংক", callback_data="show_links")],
            [InlineKeyboardButton("👥 রেফার করুন", callback_data="show_referral_link")],
            [InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return

    # কাজ জমা দেওয়ার প্রকারভেদ
    if data == "submit_work":
        await update_user_state(user_id, STATE_SUB_SELECT_TYPE)
        keyboard = [
            [InlineKeyboardButton("📋 রিভিউ দেওয়ার তথ্য জমা দিন", callback_data="sub_review_data")],
            [InlineKeyboardButton("🔗 মার্কেটিং করা গুগল সিট লিংক জমা দিন", callback_data="sub_market_link")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]
        ]
        await query.edit_message_text("কাজ জমা দেওয়ার ধরন নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    # মার্কেটিং লিংক জমার ধাপ
    elif data == "sub_market_link":
        await update_user_state(user_id, STATE_SUB_MARKET_LINK)
        await query.edit_message_text(
            text="মার্কেটিং করা গুগল সিট লিংক দিন।\n\nবাতিল করতে /start লিখুন।",
            parse_mode='HTML'
        )

    # রিভিউ তথ্য জমার প্রথম ধাপ
    elif data == "sub_review_data":
        await update_user_state(user_id, STATE_SUB_AWAITING_LINK, temp_data={}) # টেম্প ডেটা রিসেট
        await query.edit_message_text(
            text="কাজ জমা দেওয়ার প্রক্রিয়া শুরু হয়েছে।\n\n১/৪: প্রথমে আপনার **স্ক্রিনশট লিংকটি** দিন।\n\nবাতিল করতে /start লিখুন।",
            parse_mode='HTML'
        )

    # অ্যাকাউন্ট তথ্য
    elif data == "show_account":
        balance = await get_balance(user_id)
        db_status_text = "অনলাইন (🟢)" if db else "অফলাইন (🔴)"
        user_data = await get_user_data(user_id)
        
        text = (
            f"👤 <b>আপনার অ্যাকাউন্ট</b>\n\n"
            f"নাম: <b>{query.from_user.first_name}</b>\n"
            f"ইউজারনেম: @{query.from_user.username or 'N/A'}\n"
            f"🆔 আইডি: <code>{user_id}</code>\n"
            f"💰 বর্তমান ব্যালেন্স: {balance:.2f} BDT\n"
            f"🔗 ডাটাবেস স্ট্যাটাস: {db_status_text}"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # উত্তোলন শুরু
    elif data == "start_withdraw":
        balance = await get_balance(user_id)
        min_withdraw = 20.0
        
        if balance < min_withdraw:
            await query.edit_message_text(f"❌ দুঃখিত! উইথড্র করার জন্য আপনার সর্বনিম্ন {min_withdraw:.2f} BDT ব্যালেন্স থাকতে হবে। আপনার বর্তমান ব্যালেন্স: {balance:.2f} BDT।")
            keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
            await query.edit_message_text(f"❌ দুঃখিত! উইথড্র করার জন্য আপনার সর্বনিম্ন {min_withdraw:.2f} BDT ব্যালেন্স থাকতে হবে। আপনার বর্তমান ব্যালেন্স: {balance:.2f} BDT।", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        # উত্তোলন ধাপ ১: অ্যামাউন্ট
        await update_user_state(user_id, STATE_WITHDRAW_AWAITING_AMOUNT)
        await query.edit_message_text(
            f"💸 **উত্তোলন প্রক্রিয়া**\n\nআপনার বর্তমান ব্যালেন্স: {balance:.2f} BDT।\nসর্বনিম্ন উত্তোলন: {min_withdraw:.2f} BDT।\n\nকত টাকা উত্তোলন করতে চান, সংখ্যায় লিখুন:",
            parse_mode='HTML'
        )

    # সব লিংক
    elif data == "show_links":
        links_text = (
            f"🌐 <b>গুরুত্বপূর্ণ লিংক সমূহ:</b>\n\n"
            f"১. ফেসবুক গ্রুপ: <a href='{LINKS['FB_GROUP']}'>এখানে ক্লিক করুন</a>\n"
            f"২. ফেসবুক পেজ: <a href='{LINKS['FB_PAGE']}'>এখানে ক্লিক করুন</a>\n"
            f"৩. ইউটিউব চ্যানেল: <a href='{LINKS['YT_CHANNEL']}'>এখানে ক্লিক করুন</a>\n"
            f"৪. টেলিগ্রাম গ্রুপ (চ্যাট): <a href='{LINKS['TG_GROUP']}'>এখানে ক্লিক করুন</a>\n"
            f"৫. টেলিগ্রাম চ্যানেল: <a href='{LINKS['TG_CHANNEL']}'>এখানে ক্লিক করুন</a>\n"
            f"৬. পেমেন্ট প্রমাণ চ্যানেল: <a href='{LINKS['TG_CHANNEL_PAYMENT']}'>এখানে ক্লিক করুন</a>\n"
            f"৭. ওয়েবসাইট: <a href='https://{LINKS['WEBSITE']}'>{LINKS['WEBSITE']}</a>\n"
            f"৮. সাপোর্ট (এডমিন): {LINKS['SUPPORT']}\n"
            f"৯. ইমেইল: {LINKS['EMAIL']}"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(links_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML', disable_web_page_preview=True)
        
    # কাজের বিবরণ
    elif data == "show_guide":
        guide_text = (
            f"📚 <b>কাজের বিবরণ ও নির্দেশিকা</b>\n\n"
            f"আমাদের কাজগুলো হলো মূলত বিভিন্ন সাইটে রিভিউ বা রেটিং দেওয়া এবং মার্কেটিং করা।\n\n"
            f"১. 'কাজ জমা দিন' অপশন ব্যবহার করে আপনার কাজের তথ্য বা লিংক দিন।\n"
            f"২. অ্যাডমিন যাচাই করার পর আপনার অ্যাকাউন্টে টাকা যোগ হবে।\n"
            f"৩. পেমেন্টের প্রমাণ দেখতে পেমেন্ট চ্যানেলে চোখ রাখুন।"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    # রেফারেল লিংক
    elif data == "show_referral_link":
        refer_link = f"https://t.me/{context.bot.username}?start={user_id}"
        refer_bonus = await get_refer_bonus()
        
        text = (
            f"👥 **আপনার রেফারেল লিংক**\n\n"
            f"এই লিংকটি ব্যবহার করে কেউ জয়েন করলে আপনি **{refer_bonus:.2f} BDT** বোনাস পাবেন।\n\n"
            f"🔗 <code>{refer_link}</code>\n\n"
            f"উপরে দেওয়া লিংকে ক্লিক করে কপি করুন এবং আপনার বন্ধুদের সাথে শেয়ার করুন।"
        )
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাধারণ মেসেজগুলি হ্যান্ডেল করে, বিশেষ করে যখন ইউজার একটি স্টেটে থাকে"""
    user_id = update.effective_user.id
    
    if not db:
        await update.message.reply_text("⚠️ ডাটাবেস কানেকশন নেই। কোনো ফিচার কাজ করবে না।")
        return
    
    current_state, temp_data = await get_user_state_and_data(user_id)
    text = update.message.text
    
    # --- কাজ জমা দেওয়ার ফ্লো ---
    if current_state == STATE_SUB_MARKET_LINK:
        if text.startswith('http'):
            # মার্কেটিং কাজ জমা দেওয়া
            submission_data = {
                'user_id': user_id,
                'username': update.effective_user.username,
                'type': 'marketing_sheet',
                'link': text,
                'status': 'pending',
                'submitted_at': firestore.SERVER_TIMESTAMP
            }
            submission_ref = db.collection(COLLECTION_SUBMISSIONS).add(submission_data)
            
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ মার্কেটিং গুগল সিট লিংক সফলভাবে জমা দেওয়া হয়েছে!")
            
            # অ্যাডমিন নোটিফিকেশন (গ্রুপ এবং অ্যাডমিন)
            await send_submission_notification(context, submission_ref[1].id, submission_data)

        else:
            await update.message.reply_text("❌ এটি বৈধ লিংক নয়। দয়া করে মার্কেটিং গুগল সিট লিংক দিন। বাতিল করতে /start লিখুন।")
            
    elif current_state == STATE_SUB_AWAITING_LINK:
        if text.startswith('http'):
            temp_data['link'] = text
            await update_user_state(user_id, STATE_SUB_AWAITING_EMAIL, temp_data)
            await update.message.reply_text("২/৪: ধন্যবাদ। এবার আপনার **রিভিউ দেওয়া ইমেইল**টি লিখুন:")
        else:
            await update.message.reply_text("❌ এটি বৈধ স্ক্রিনশট লিংক নয়। বাতিল করতে /start লিখুন।")

    elif current_state == STATE_SUB_AWAITING_EMAIL:
        if '@' in text and '.' in text:
            temp_data['email'] = text
            await update_user_state(user_id, STATE_SUB_AWAITING_NAME, temp_data)
            await update.message.reply_text("৩/৪: আপনার **রিভিউ নাম (যে নামে রিভিউ দিয়েছেন)** সেটি লিখুন:")
        else:
            await update.message.reply_text("❌ এটি বৈধ ইমেইল ফরম্যাট নয়। আবার চেষ্টা করুন বা বাতিল করতে /start লিখুন।")

    elif current_state == STATE_SUB_AWAITING_NAME:
        if len(text) > 2:
            temp_data['review_name'] = text
            await update_user_state(user_id, STATE_SUB_AWAITING_DEVICE, temp_data)
            await update.message.reply_text("৪/৪: **ডিভাইস নাম (যেমন: Samsung S20, iPhone 13, PC)** লিখুন:")
        else:
            await update.message.reply_text("❌ রিভিউ নাম কমপক্ষে ৩ অক্ষরের হতে হবে। আবার চেষ্টা করুন।")

    elif current_state == STATE_SUB_AWAITING_DEVICE:
        temp_data['device_name'] = text
        
        # চূড়ান্ত জমা
        submission_data = {
            'user_id': user_id,
            'username': update.effective_user.username,
            'first_name': update.effective_user.first_name,
            'type': 'review_data',
            'data': temp_data,
            'status': 'pending',
            'submitted_at': firestore.SERVER_TIMESTAMP
        }
        submission_ref = db.collection(COLLECTION_SUBMISSIONS).add(submission_data)
        
        await update_user_state(user_id, STATE_IDLE)
        await update.message.reply_text(
            "✅ <b>কাজ সফলভাবে জমা দেওয়া হয়েছে!</b>\n\nঅ্যাডমিন শীঘ্রই যাচাই করবেন।",
            parse_mode='HTML'
        )
        
        # অ্যাডমিন নোটিফিকেশন (গ্রুপ এবং অ্যাডমিন)
        await send_submission_notification(context, submission_ref[1].id, submission_data)

    # --- উত্তোলন (Withdraw) ফ্লো ---
    elif current_state == STATE_WITHDRAW_AWAITING_AMOUNT:
        try:
            amount = float(text)
            balance = await get_balance(user_id)
            min_withdraw = 20.0

            if amount < min_withdraw:
                await update.message.reply_text(f"❌ সর্বনিম্ন উত্তোলনের পরিমাণ ২০ টাকা। আবার লিখুন।")
                return
            if amount > balance:
                await update.message.reply_text(f"❌ আপনার অ্যাকাউন্টে যথেষ্ট ব্যালেন্স নেই ({balance:.2f} BDT)। আবার লিখুন।")
                return
            
            temp_data['amount'] = amount
            await update_user_state(user_id, STATE_WITHDRAW_AWAITING_METHOD, temp_data)
            
            keyboard = [
                [InlineKeyboardButton("💳 বিকাশ", callback_data="wd_method_bkash"),
                 InlineKeyboardButton("💳 নগদ", callback_data="wd_method_nagad")],
                [InlineKeyboardButton("₿ বাইনান্স (Binance)", callback_data="wd_method_binance")]
            ]
            await update.message.reply_text(f"২/৩: উত্তোলন মাধ্যম নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
            
        except ValueError:
            await update.message.reply_text("❌ টাকার পরিমাণ শুধুমাত্র সংখ্যায় লিখুন। বাতিল করতে /start লিখুন।")
            
    elif current_state == STATE_WITHDRAW_AWAITING_METHOD:
        # এই স্টেট শুধু CallbackQueryHandler দিয়ে হ্যান্ডেল হয়
        await update.message.reply_text("❌ উত্তোলন মাধ্যম নির্বাচন করতে বাটন ব্যবহার করুন। বাতিল করতে /start লিখুন।")

    elif current_state == STATE_WITHDRAW_AWAITING_NUMBER:
        method = temp_data.get('method')
        
        if len(text) < 5: # সিম্পল ভ্যালিডেশন
            await update.message.reply_text("❌ প্রদত্ত তথ্যটি খুবই ছোট। সঠিক নাম্বার/আইডি দিন।")
            return

        temp_data['target'] = text

        # চূড়ান্ত উইথড্র জমা
        withdraw_data = {
            'user_id': user_id,
            'username': update.effective_user.username,
            'amount': temp_data['amount'],
            'method': temp_data['method'],
            'target': temp_data['target'],
            'status': 'pending',
            'submitted_at': firestore.SERVER_TIMESTAMP
        }
        withdraw_ref = db.collection(COLLECTION_WITHDRAWALS).add(withdraw_data)

        # ১. ইউজারের ব্যালেন্স থেকে টাকা কাটা
        await update_balance(user_id, -temp_data['amount'])
        
        await update_user_state(user_id, STATE_IDLE)
        await update.message.reply_text(
            f"✅ **উত্তোলন রিকোয়েস্ট সফলভাবে জমা হয়েছে!**\n\n"
            f"টাকা: {temp_data['amount']:.2f} BDT\nমাধ্যম: {method}\nটার্গেট: {text}\n\n"
            f"অ্যাডমিন শীঘ্রই আপনার পেমেন্ট প্রক্রিয়া করবেন।"
        )
        
        # ২. অ্যাডমিন নোটিফিকেশন
        await send_withdraw_notification(context, withdraw_ref[1].id, withdraw_data)
        
    # --- অ্যাডমিন ব্যালেন্স ম্যানেজমেন্ট ফ্লো ---
    elif current_state == STATE_ADMIN_AWAITING_BALANCE_USER_ID:
        if text.isdigit() and len(text) > 5:
            target_user_id = int(text)
            target_user_data = await get_user_by_id(target_user_id)

            if not target_user_data:
                await update.message.reply_text("❌ ইউজার ID টি ডাটাবেসে পাওয়া যায়নি। সঠিক ID দিন বা বাতিল করতে /start লিখুন।")
                return

            temp_data['target_user_id'] = target_user_id
            
            await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_AMOUNT, temp_data)
            await update.message.reply_text(
                f"✅ ইউজার: <b>{target_user_data.get('first_name', 'N/A')}</b> (ID: <code>{target_user_id}</code>)\n"
                f"বর্তমান ব্যালেন্স: <b>{target_user_data.get('balance', 0.0):.2f} BDT</b>\n\n"
                f"কত টাকা যোগ বা বিয়োগ করতে চান? (যেমন: +10 বা -5)\n\n"
                f"বাতিল করতে /start লিখুন।",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ এটি সঠিক ইউজার ID নয়। অনুগ্রহ করে শুধুমাত্র সংখ্যায় ইউজার ID দিন।")

    elif current_state == STATE_ADMIN_AWAITING_BALANCE_AMOUNT:
        try:
            # +10, -5, +5.5, -2.5 ইত্যাদি হ্যান্ডেল করা
            operation = text[0]
            amount = float(text[1:])
            
            if operation == '+':
                final_amount = amount
                action = "যোগ"
            elif operation == '-':
                final_amount = -amount
                action = "বিয়োগ"
            else:
                raise ValueError("অপারেশন ভুল")

            target_user_id = temp_data['target_user_id']
            
            # ব্যালেন্স আপডেট করা
            success = await update_balance(target_user_id, final_amount)
            
            if success:
                current_balance = await get_balance(target_user_id)
                await update_user_state(user_id, STATE_IDLE)

                # অ্যাডমিনকে নিশ্চিত করা
                await update.message.reply_text(
                    f"✅ সফল! ইউজার <code>{target_user_id}</code> এর অ্যাকাউন্টে {amount:.2f} BDT {action} করা হয়েছে।\n"
                    f"নতুন ব্যালেন্স: {current_balance:.2f} BDT।",
                    parse_mode='HTML'
                )
                # টার্গেট ইউজারকে নোটিফাই করা
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🔔 <b>আপনার ব্যালেন্স আপডেট হয়েছে!</b>\n"
                    f"অ্যাডমিন আপনার অ্যাকাউন্টে {amount:.2f} BDT {action} করেছেন।\n"
                    f"বর্তমান ব্যালেন্স: {current_balance:.2f} BDT।",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("❌ ব্যালেন্স আপডেটে ব্যর্থ।")

        except (ValueError, IndexError):
            await update.message.reply_text("❌ ফরম্যাট ভুল। '+[সংখ্যা]' বা '-[সংখ্যা]' ফরম্যাটে লিখুন (যেমন: +10 বা -5)।")

    # --- অ্যাডমিন রেফার বোনাস ফ্লো ---
    elif current_state == STATE_ADMIN_AWAITING_REFER_BONUS:
        try:
            new_bonus = float(text)
            if new_bonus < 0:
                await update.message.reply_text("❌ রেফার বোনাস ঋণাত্মক হতে পারে না। সঠিক সংখ্যা দিন।")
                return

            success = await set_refer_bonus(new_bonus)
            if success:
                await update_user_state(user_id, STATE_IDLE)
                await update.message.reply_text(f"✅ সফল! নতুন রেফারেল বোনাস সেট করা হয়েছে: **{new_bonus:.2f} BDT**।")
            else:
                await update.message.reply_text("❌ রেফারেল বোনাস আপডেটে ব্যর্থ (ডাটাবেস ত্রুটি)।")
        except ValueError:
            await update.message.reply_text("❌ অনুগ্রহ করে রেফার বোনাসের পরিমাণ শুধুমাত্র সংখ্যায় লিখুন। বাতিল করতে /start লিখুন।")

    # --- অ্যাডমিন ব্রডকাস্ট ফ্লো ---
    elif current_state == STATE_ADMIN_AWAITING_BROADCAST_MESSAGE:
        if len(text) < 5:
            await update.message.reply_text("❌ মেসেজটি খুব ছোট। অনুগ্রহ করে আরো বিস্তারিত মেসেজ লিখুন।")
            return
            
        await update.message.reply_text("📢 ব্রডকাস্ট মেসেজ পাঠানো শুরু হয়েছে...")
        await update_user_state(user_id, STATE_IDLE)
        
        # সকল ইউজারের আইডি পাওয়া
        all_user_ids = await get_all_user_ids()
        sent_count = 0
        
        # মেসেজ পাঠানোর প্রক্রিয়া
        for target_id in all_user_ids:
            try:
                await context.bot.send_message(chat_id=target_id, text=f"📢 **অ্যাডমিনের গুরুত্বপূর্ণ বার্তা:**\n\n{text}", parse_mode='HTML')
                sent_count += 1
                await asyncio.sleep(0.05) # ফ্লাডিং এড়াতে ছোট বিরতি
            except Exception as e:
                # যদি ইউজার বট ব্লক করে দেয় বা অন্য কোনো সমস্যা হয়
                logger.warning(f"Failed to send broadcast to user {target_id}: {e}")
                
        await update.message.reply_text(f"✅ ব্রডকাস্ট সফলভাবে সম্পন্ন হয়েছে। মোট {len(all_user_ids)} ইউজারের মধ্যে {sent_count} জনের কাছে বার্তা পাঠানো হয়েছে।")
        

    # --- অন্য কোনো মেসেজ ---
    elif current_state == STATE_IDLE:
        await update.message.reply_text("আমি এই মেসেজটি বুঝতে পারিনি। দয়া করে মেনু থেকে অপশন নির্বাচন করুন বা /start টাইপ করে প্রধান মেনুতে যান।")

# উইথড্র মেথড কলব্যাক হ্যান্ডেলার
async def withdraw_method_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_state, temp_data = await get_user_state_and_data(user_id)
    
    if current_state != STATE_WITHDRAW_AWAITING_METHOD:
        await query.edit_message_text("❌ ভুল ধাপ। /start লিখুন।")
        return

    method_map = {
        "wd_method_bkash": "বিকাশ",
        "wd_method_nagad": "নগদ",
        "wd_method_binance": "বাইনান্স (Binance ID)"
    }
    
    selected_method = method_map.get(query.data)
    if selected_method:
        temp_data['method'] = selected_method
        await update_user_state(user_id, STATE_WITHDRAW_AWAITING_NUMBER, temp_data)

        # প্রম্পট সেট করা
        prompt = ""
        if 'বিকাশ' in selected_method or 'নগদ' in selected_method:
            prompt = "আপনার **পেমেন্ট নাম্বারটি** (যেমন: 01xxxxxxxxx) লিখুন:"
        elif 'বাইনান্স' in selected_method:
            prompt = "আপনার **Binance ID/Email** লিখুন:"
        
        await query.edit_message_text(f"৩/৩: আপনি {selected_method} নির্বাচন করেছেন।\n\n{prompt}")

# ==========================================
# ৪. নোটিফিকেশন ফাংশন
# ==========================================

async def send_submission_notification(context, submission_id, submission_data):
    """কাজ জমা দেওয়ার নোটিফিকেশন অ্যাডমিন এবং গ্রুপে পাঠানো"""
    user_id = submission_data['user_id']
    username = submission_data.get('username') or submission_data.get('first_name')
    s_type = "মার্কেটিং সিট" if submission_data.get('type') == 'marketing_sheet' else "রিভিউ তথ্য"
    link = submission_data.get('link')

    text = f"🔔 <b>নতুন কাজ ({s_type}) জমা পড়েছে!</b>\n\n"
    text += f"ইউজার ID: <code>{user_id}</code> (@{username})\n"
    text += f"সাবমিশন ID: <code>{submission_id}</code>\n"
    if link:
        text += f"লিংক: <a href='{link}'>{link}</a>\n"
    if submission_data.get('data'):
        data = submission_data['data']
        text += f"রিভিউ ইমেইল: {data.get('email')}\n"
        text += f"রিভিউ নাম: {data.get('review_name')}\n"
        text += f"ডিভাইস: {data.get('device_name')}\n"
        text += f"স্ক্রিনশট: <a href='{data.get('link')}'>স্ক্রিনশট লিংক</a>\n"
    
    keyboard = [[InlineKeyboardButton("✅ অ্যাপ্রুভ করুন", callback_data=f"admin_approve_sub_{submission_id}"),
                 InlineKeyboardButton("❌ রিজেক্ট করুন", callback_data=f"admin_reject_sub_{submission_id}")]]

    # অ্যাডমিনকে নোটিফিকেশন
    if ADMIN_USER_ID_STR:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID_STR, text=text, parse_mode='HTML', disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending admin submission notification: {e}")
            
    # এই নোটিফিকেশনটি চ্যাট গ্রুপে পাঠানোর জন্য, আপনাকে Render-এ TG_GROUP এর এনভায়রনমেন্ট ভেরিয়েবল সেট করতে হবে (যেমন, -10012345678)
    # যেহেতু আপনি শুধু লিংক দিয়েছেন, আমি ধরে নিচ্ছি আপনার লক্ষ্য শুধু অ্যাডমিনকেই জানানো।
    
async def send_withdraw_notification(context, withdrawal_id, withdraw_data):
    """উত্তোলন রিকোয়েস্ট অ্যাডমিন এবং গ্রুপে পাঠানো"""
    user_id = withdraw_data['user_id']
    username = withdraw_data.get('username') or "N/A"
    
    text = f"💸 <b>নতুন উত্তোলন রিকোয়েস্ট!</b>\n\n"
    text += f"ইউজার ID: <code>{user_id}</code> (@{username})\n"
    text += f"উত্তোলন ID: <code>{withdrawal_id}</code>\n"
    text += f"টাকা: <b>{withdraw_data['amount']:.2f} BDT</b>\n"
    text += f"মাধ্যম: {withdraw_data['method']}\n"
    text += f"টার্গেট: <code>{withdraw_data['target']}</code>"
    
    keyboard = [[InlineKeyboardButton("✅ সম্পন্ন (Mark Paid)", callback_data=f"admin_mark_paid_{withdrawal_id}")]]

    if ADMIN_USER_ID_STR:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID_STR, text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending admin withdrawal notification: {e}")

# ==========================================
# ৫. অ্যাডমিন কমান্ড ও হ্যান্ডেলার
# ==========================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if not ADMIN_USER_ID_STR or ADMIN_USER_ID_STR != user_id:
        await update.message.reply_text("🚫 আপনি অ্যাডমিন নন।")
        return
    
    if db is None:
        await update.message.reply_text("⚠️ <b>অ্যাডমিন প্যানেল:</b> ডাটাবেস কানেকশন নেই।", parse_mode='HTML')
        return

    # স্টেট রিসেট করা
    await update_user_state(user_id, STATE_IDLE) 

    # অ্যাডমিন প্যানেল মেনু তৈরি
    keyboard = [
        [InlineKeyboardButton("💰 ব্যালেন্স অ্যাড/রিমুভ", callback_data="admin_manage_balance")],
        [InlineKeyboardButton("⚙️ রেফার বোনাস সেট করুন", callback_data="admin_set_referral_bonus"),
         InlineKeyboardButton("📢 গণবার্তা পাঠান", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 প্রধান মেনু", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("👑 <b>অ্যাডমিন প্যানেল</b>\n\nদয়া করে অপশন নির্বাচন করুন:", reply_markup=reply_markup, parse_mode='HTML')

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """অ্যাডমিন ইনলাইন বাটন হ্যান্ডেল করে (কাজ অ্যাপ্রুভ/রিজেক্ট/উত্তোলন সম্পন্ন এবং ম্যানেজমেন্ট টুলস)"""
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    if not ADMIN_USER_ID_STR or ADMIN_USER_ID_STR != user_id:
        await query.edit_message_text("🚫 আপনার এই অ্যাকশন নেওয়ার অনুমতি নেই।")
        return

    data = query.data
    
    # --- অ্যাডমিন ম্যানেজমেন্ট টুলস ---
    if data == "admin_manage_balance":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_USER_ID)
        await query.edit_message_text("💰 **ব্যালেন্স ম্যানেজমেন্ট**\n\nঅনুগ্রহ করে টার্গেট **ইউজার ID** দিন:\n\nবাতিল করতে /start লিখুন।")
        return
    
    elif data == "admin_set_referral_bonus":
        current_bonus = await get_refer_bonus()
        await update_user_state(user_id, STATE_ADMIN_AWAITING_REFER_BONUS)
        await query.edit_message_text(f"⚙️ **রেফারেল বোনাস সেট করুন**\n\nবর্তমান বোনাস: **{current_bonus:.2f} BDT**\n\nনতুন বোনাস কত সেট করতে চান, শুধুমাত্র সংখ্যায় লিখুন (যেমন: 5.00 বা 3):")
        return

    elif data == "admin_broadcast":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BROADCAST_MESSAGE)
        await query.edit_message_text("📢 **গণবার্তা (Broadcast) পাঠান**\n\nযে মেসেজটি সকল ইউজারকে পাঠাতে চান, সেটি লিখুন (HTML ফরম্যাট ব্যবহার করতে পারবেন):\n\nবাতিল করতে /start লিখুন।")
        return


    # --- কাজ অ্যাপ্রুভ/রিজেক্ট ---
    if data.startswith("admin_approve_sub_") or data.startswith("admin_reject_sub_"):
        is_approve = data.startswith("admin_approve_sub_")
        submission_id = data.split('_')[-1]
        
        try:
            submission_ref = db.collection(COLLECTION_SUBMISSIONS).document(submission_id)
            submission_doc = submission_ref.get()
            
            if not submission_doc.exists:
                await query.edit_message_text("❌ এই সাবমিশনটি পাওয়া যায়নি।")
                return

            submission_data = submission_doc.to_dict()
            submitter_id = submission_data['user_id']
            
            if submission_data['status'] != 'pending':
                await query.edit_message_text(f"❌ এই সাবমিশনটি ইতিমধ্যেই {submission_data['status']} স্ট্যাটাসে আছে।")
                return
            
            new_status = 'approved' if is_approve else 'rejected'
            
            # Firestore আপডেট
            submission_ref.update({'status': new_status, 'processed_by': user_id, 'processed_at': firestore.SERVER_TIMESTAMP})
            
            # ইউজারকে নোটিফিকেশন
            if is_approve:
                # কাজের নির্দিষ্ট মূল্য যোগ করা (ডিফল্ট: 5 BDT)
                amount = 5.0 
                await update_balance(submitter_id, amount)
                
                await context.bot.send_message(
                    chat_id=submitter_id,
                    text=f"✅ <b>অভিনন্দন!</b> আপনার জমা দেওয়া কাজটি **অ্যাপ্রুভ** হয়েছে। আপনার ব্যালেন্সে **{amount:.2f} BDT** যোগ করা হয়েছে।",
                    parse_mode='HTML'
                )
            else:
                await context.bot.send_message(
                    chat_id=submitter_id,
                    text=f"❌ দুঃখিত! আপনার জমা দেওয়া কাজটি **রিজেক্ট** হয়েছে। কোনো প্রশ্ন থাকলে অ্যাডমিনের সাথে যোগাযোগ করুন: {LINKS['SUPPORT']}",
                    parse_mode='HTML'
                )
            
            await query.edit_message_text(query.message.text + f"\n\n--- \n✅ স্ট্যাটাস: <b>{new_status.upper()}</b> | অ্যাডমিন: {query.from_user.first_name}", parse_mode='HTML')
            
        except Exception as e:
            await query.edit_message_text(f"❌ এরর: কাজ প্রক্রিয়া করতে ব্যর্থ। {e}")

    # --- উত্তোলন সম্পন্ন (Mark Paid) ---
    elif data.startswith("admin_mark_paid_"):
        withdrawal_id = data.split('_')[-1]
        
        try:
            withdraw_ref = db.collection(COLLECTION_WITHDRAWALS).document(withdrawal_id)
            withdraw_doc = withdraw_ref.get()

            if not withdraw_doc.exists:
                await query.edit_message_text("❌ এই উইথড্র রিকোয়েস্টটি পাওয়া যায়নি।")
                return
            
            withdraw_data = withdraw_doc.to_dict()
            if withdraw_data['status'] != 'pending':
                await query.edit_message_text(f"❌ এই রিকোয়েস্টটি ইতিমধ্যেই {withdraw_data['status']} স্ট্যাটাসে আছে।")
                return
            
            # Firestore আপডেট
            withdraw_ref.update({'status': 'paid', 'processed_by': user_id, 'processed_at': firestore.SERVER_TIMESTAMP})
            
            # ইউজারকে নোটিফিকেশন
            await context.bot.send_message(
                chat_id=withdraw_data['user_id'],
                text=f"💸 <b>পেমেন্ট সফল!</b>\n\nআপনার **{withdraw_data['amount']:.2f} BDT** উত্তোলন সফলভাবে সম্পন্ন হয়েছে। অনুগ্রহ করে আপনার অ্যাকাউন্ট চেক করুন। ধন্যবাদ!",
                parse_mode='HTML'
            )

            await query.edit_message_text(query.message.text + f"\n\n--- \n✅ স্ট্যাটাস: <b>PAID</b> | অ্যাডমিন: {query.from_user.first_name}", parse_mode='HTML')

        except Exception as e:
            await query.edit_message_text(f"❌ এরর: পেমেন্ট সম্পন্ন করতে ব্যর্থ। {e}")


# ==========================================
# ৬. প্রধান রান ফাংশন
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
    
    # কলব্যাক হ্যান্ডেলার
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(withdraw_method_handler, pattern='^wd_method_'))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # সকল টেক্সট মেসেজ হ্যান্ডেল করার জন্য MessageHandler যোগ করা
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
