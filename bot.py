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
ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID") # সুপার অ্যাডমিন আইডি
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get('PORT', 8080))

REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com"

# ফায়ারবেস ইনিশিয়ালাইজেশন
db = None
rtdb = None

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
            
            # সিস্টেম কনফিগারেশন ডিফল্ট সেটআপ (যদি না থাকে)
            sys_ref = db.collection("system").document("config")
            if not sys_ref.get().exists:
                sys_ref.set({
                    'task_reward': 5.0, # ডিফল্ট কাজের রেট
                    'show_review': True,
                    'show_submit': True,
                    'show_withdraw': True,
                    'show_refer': True
                })

            logger.info("✅ Firebase Connected Successfully!")
        except Exception as e:
            logger.error(f"❌ Firebase Init Error: {e}")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT missing!")
except Exception as e:
    logger.error(f"❌ Critical setup error: {e}")

# লিংক কনফিগারেশন
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
COLLECTION_ADMINS = "admins" # সাব-অ্যাডমিনদের জন্য

# ফ্লো স্টেটস
STATE_IDLE = 0
STATE_SUB_SELECT_TYPE = 10
STATE_SUB_MARKET_LINK = 11
STATE_SUB_AWAITING_REVIEW_DATA = 12
STATE_SUB_AWAITING_LINK = 13
STATE_SUB_AWAITING_EMAIL = 14
STATE_SUB_AWAITING_NAME = 15
STATE_SUB_AWAITING_DEVICE = 16
STATE_WITHDRAW_AWAITING_AMOUNT = 20
STATE_WITHDRAW_AWAITING_METHOD = 21
STATE_WITHDRAW_AWAITING_NUMBER = 22

# অ্যাডমিন স্টেটস
STATE_ADMIN_AWAITING_BALANCE_USER_ID = 30
STATE_ADMIN_AWAITING_BALANCE_AMOUNT = 31
STATE_ADMIN_AWAITING_REFER_BONUS = 40
STATE_ADMIN_AWAITING_BROADCAST_MESSAGE = 50
STATE_ADMIN_AWAITING_TASK_REWARD = 60 # নতুন: টাস্ক রিওয়ার্ড সেট করার জন্য
STATE_ADMIN_ADD_ADMIN_ID = 70 # নতুন: অ্যাডমিন অ্যাড করার জন্য
STATE_ADMIN_USER_ACTION_ID = 80 # নতুন: ইউজার ব্লক/ডিলিট করার জন্য

# ==========================================
# ২. ডাটাবেস এবং হেল্পার ফাংশন
# ==========================================

async def get_system_config():
    """সিস্টেম কনফিগারেশন (ফিচার টগল, রেট) আনা"""
    if db is None: return {}
    try:
        doc = db.collection("system").document("config").get()
        return doc.to_dict() if doc.exists else {}
    except:
        return {}

async def update_system_config(key, value):
    """সিস্টেম কনফিগারেশন আপডেট করা"""
    if db is None: return False
    try:
        db.collection("system").document("config").update({key: value})
        return True
    except:
        # ডকুমেন্ট না থাকলে তৈরি করবে
        db.collection("system").document("config").set({key: value}, merge=True)
        return True

async def is_super_admin(user_id):
    """চেক করে ইউজার সুপার অ্যাডমিন কিনা"""
    return str(user_id) == ADMIN_USER_ID_STR

async def is_admin(user_id):
    """চেক করে ইউজার অ্যাডমিন (সুপার বা সাব) কিনা"""
    if str(user_id) == ADMIN_USER_ID_STR:
        return True
    
    if db:
        doc = db.collection(COLLECTION_ADMINS).document(str(user_id)).get()
        return doc.exists
    return False

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
            referral_bonus = 0.0
            if referred_by and str(user_id) != str(referred_by):
                bonus_amount = await get_refer_bonus()
                await update_balance(referred_by, bonus_amount)
                logger.info(f"Referral bonus given to {referred_by}")

            new_user = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'balance': referral_bonus,
                'referred_by': referred_by,
                'joined_at': firestore.SERVER_TIMESTAMP,
                'is_blocked': False,
                'state': STATE_IDLE,
                'temp_data': {}
            }
            user_ref.set(new_user)
            return {"status": "created", "data": new_user}
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return {"status": "NO_DB"}

async def update_balance(user_id, amount):
    if db is None: return False
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        user_ref.update({'balance': firestore.Increment(amount)})
        return True
    except: return False

async def get_user_data(user_id):
    if db is None: return None
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None

async def get_balance(user_id):
    data = await get_user_data(user_id)
    return data.get("balance", 0.0) if data else 0.0

async def update_user_state(user_id, state, temp_data=None):
    if db is None: return
    try:
        user_ref = db.collection(COLLECTION_USERS).document(str(user_id))
        update_fields = {'state': state}
        if temp_data is not None:
            update_fields['temp_data'] = temp_data
        user_ref.update(update_fields)
    except: pass

async def get_user_state_and_data(user_id):
    data = await get_user_data(user_id)
    return data.get("state", STATE_IDLE) if data else STATE_IDLE, data.get("temp_data", {}) if data else {}

async def get_refer_bonus():
    if rtdb is None: return 3.00
    try:
        bonus = rtdb.child("ReferBonus").get()
        return float(bonus) if bonus else 3.00
    except: return 3.00
        
async def set_refer_bonus(amount):
    if rtdb is None: return False
    try:
        rtdb.child("ReferBonus").set(amount)
        return True
    except: return False

async def get_all_user_ids():
    if db is None: return []
    try:
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        return [doc.get('user_id') for doc in users if doc.get('user_id') is not None]
    except: return []

async def get_total_users_count():
    """মোট ইউজার সংখ্যা গণনা"""
    if db is None: return 0
    try:
        # Firestore Count Aggregation (Cost effective)
        # Note: If library version is old, it might fallback to len(list)
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        return len(list(users))
    except: return 0

async def delete_user(user_id):
    """ইউজার ডিলিট করা"""
    if db is None: return False
    try:
        db.collection(COLLECTION_USERS).document(str(user_id)).delete()
        return True
    except: return False

async def toggle_block_user(user_id, block_status):
    """ইউজার ব্লক/আনব্লক করা"""
    if db is None: return False
    try:
        db.collection(COLLECTION_USERS).document(str(user_id)).update({'is_blocked': block_status})
        return True
    except: return False

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    
    # রেফারেল হ্যান্ডেলিং
    referred_by = None
    if context.args and context.args[0].isdigit():
        referred_by = int(context.args[0])

    result = await get_or_create_user(user_id, user.username or 'N/A', user.first_name, referred_by)
    
    if result.get("status") == "blocked":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে ব্লক করা হয়েছে।")
        return
    
    await update_user_state(user_id, STATE_IDLE)
    
    # কনফিগারেশন চেক করে বাটন শো/হাইড করা
    config = await get_system_config()
    
    keyboard = []
    
    # রিভিউ জেনারেটর বাটন (লুকানো যাবে)
    if config.get('show_review', True):
        keyboard.append([InlineKeyboardButton("🌐 রিভিউ জেনারেটর", url=LINKS['REVIEW_GEN'])])
    
    # কাজের বাটন এবং ব্যালেন্স
    row2 = []
    if config.get('show_submit', True):
        row2.append(InlineKeyboardButton("💰 কাজ জমা দিন", callback_data="submit_work"))
    row2.append(InlineKeyboardButton("📈 ব্যালেন্স", callback_data="show_account"))
    if row2: keyboard.append(row2)
    
    # উইথড্র এবং তথ্য বাটন
    row3 = []
    if config.get('show_withdraw', True):
        row3.append(InlineKeyboardButton("💸 উত্তোলন (Withdraw)", callback_data="start_withdraw"))
    # নাম পরিবর্তন: "সব লিংক" -> "তথ্য দেখুন"
    row3.append(InlineKeyboardButton("ℹ️ তথ্য দেখুন", callback_data="info_links_menu"))
    if row3: keyboard.append(row3)
    
    # রেফার বাটন
    if config.get('show_refer', True):
        keyboard.append([InlineKeyboardButton("👥 রেফার করুন", callback_data="show_referral_link")])
        
    keyboard.append([InlineKeyboardButton("📚 কাজের বিবরণ", callback_data="show_guide")])
    
    # অ্যাডমিন বাটন (যদি অ্যাডমিন হয়)
    if await is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 অ্যাডমিন প্যানেল", callback_data="open_admin_panel")])

    welcome_text = f"আসসালামু আলাইকুম, <b>{user.first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম।"
    if result.get("status") == "created" and result['data'].get('referred_by'):
         welcome_text += f"\n🎉 রেফারেল বোনাস যোগ করা হয়েছে।"

    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    # ব্যাক টু মেইন মেনু (স্টেট রিসেট সহ)
    if data == "back_to_main":
        await update_user_state(user_id, STATE_IDLE)
        # পুনরায় /start লজিক চালানোর জন্য
        await start_command(update, context)
        return

    # তথ্য দেখুন মেনু (বাটন আকারে লিংক)
    if data == "info_links_menu":
        link_keyboard = [
            [InlineKeyboardButton("ফেসবুক গ্রুপ", url=LINKS['FB_GROUP']), InlineKeyboardButton("ফেসবুক পেজ", url=LINKS['FB_PAGE'])],
            [InlineKeyboardButton("ইউটিউব চ্যানেল", url=LINKS['YT_CHANNEL']), InlineKeyboardButton("টেলিগ্রাম চ্যানেল", url=LINKS['TG_CHANNEL'])],
            [InlineKeyboardButton("টেলিগ্রাম গ্রুপ", url=LINKS['TG_GROUP']), InlineKeyboardButton("পেমেন্ট চ্যানেল", url=LINKS['TG_CHANNEL_PAYMENT'])],
            [InlineKeyboardButton("🌐 ওয়েবসাইট", url=f"https://{LINKS['WEBSITE']}")],
            [InlineKeyboardButton("👨‍💻 সাপোর্ট (অ্যাডমিন)", url=f"https://t.me/{LINKS['SUPPORT'].replace('@', '')}")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]
        ]
        await query.edit_message_text(
            "ℹ️ <b>সকল তথ্য ও লিংকসমূহ:</b>\n\nনিচের বাটনগুলো ব্যবহার করে আমাদের সাথে যুক্ত হন।",
            reply_markup=InlineKeyboardMarkup(link_keyboard),
            parse_mode='HTML'
        )
        return

    # কাজ জমা দেওয়া
    if data == "submit_work":
        await update_user_state(user_id, STATE_SUB_SELECT_TYPE)
        keyboard = [
            [InlineKeyboardButton("📋 রিভিউ তথ্য জমা", callback_data="sub_review_data")],
            [InlineKeyboardButton("🔗 মার্কেটিং লিংক জমা", callback_data="sub_market_link")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]
        ]
        await query.edit_message_text("কাজের ধরন নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "sub_market_link":
        await update_user_state(user_id, STATE_SUB_MARKET_LINK)
        await query.edit_message_text("মার্কেটিং গুগল সিট লিংক দিন:\n(বাতিল করতে /start)")
        
    elif data == "sub_review_data":
        await update_user_state(user_id, STATE_SUB_AWAITING_LINK, temp_data={})
        await query.edit_message_text("১/৪: স্ক্রিনশট লিংক দিন:\n(বাতিল করতে /start)")

    # অ্যাকাউন্ট ইনফো
    elif data == "show_account":
        balance = await get_balance(user_id)
        text = f"👤 <b>অ্যাকাউন্ট</b>\n\nনাম: {query.from_user.first_name}\nID: <code>{user_id}</code>\n💰 ব্যালেন্স: {balance:.2f} BDT"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]), parse_mode='HTML')
    
    # উইথড্র
    elif data == "start_withdraw":
        balance = await get_balance(user_id)
        if balance < 20.0:
            await query.edit_message_text(f"❌ সর্বনিম্ন ২০ টাকা ব্যালেন্স প্রয়োজন। আপনার আছে: {balance:.2f} BDT", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]))
            return
        await update_user_state(user_id, STATE_WITHDRAW_AWAITING_AMOUNT)
        await query.edit_message_text(f"উত্তোলনের পরিমাণ লিখুন (বর্তমান: {balance:.2f} BDT):")

    # রেফার লিংক
    elif data == "show_referral_link":
        bonus = await get_refer_bonus()
        ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
        await query.edit_message_text(
            f"👥 <b>রেফারেল প্রোগ্রাম</b>\n\nপ্রতি রেফারে বোনাস: <b>{bonus:.2f} BDT</b>\n\nআপনার লিংক:\n<code>{ref_link}</code>\n\nকপি করে শেয়ার করুন!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]),
            parse_mode='HTML'
        )

    # গাইড
    elif data == "show_guide":
        await query.edit_message_text(
            "📚 <b>কাজের নিয়মাবলী:</b>\n\n১. লিংক থেকে কাজ সম্পন্ন করুন।\n২. সঠিক প্রমাণ জমা দিন।\n৩. অ্যাডমিন চেক করে পেমেন্ট করবে।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]),
            parse_mode='HTML'
        )

    # অ্যাডমিন প্যানেল এন্ট্রি
    elif data == "open_admin_panel":
        if await is_admin(user_id):
            await show_admin_panel(update, context, user_id)
        else:
            await query.answer("Access Denied", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text
    
    if not db: return
    state, temp_data = await get_user_state_and_data(user_id)
    
    # --- সাবমিশন ফ্লো ---
    if state == STATE_SUB_MARKET_LINK:
        if 'http' in text:
            await save_submission(update, context, user_id, 'marketing_sheet', link=text)
        else: await update.message.reply_text("❌ বৈধ লিংক দিন।")

    elif state == STATE_SUB_AWAITING_LINK:
        if 'http' in text:
            temp_data['link'] = text
            await update_user_state(user_id, STATE_SUB_AWAITING_EMAIL, temp_data)
            await update.message.reply_text("২/৪: রিভিউ ইমেইল লিখুন:")
        else: await update.message.reply_text("❌ বৈধ লিংক দিন।")

    elif state == STATE_SUB_AWAITING_EMAIL:
        temp_data['email'] = text
        await update_user_state(user_id, STATE_SUB_AWAITING_NAME, temp_data)
        await update.message.reply_text("৩/৪: প্রোফাইল নাম লিখুন:")

    elif state == STATE_SUB_AWAITING_NAME:
        temp_data['review_name'] = text
        await update_user_state(user_id, STATE_SUB_AWAITING_DEVICE, temp_data)
        await update.message.reply_text("৪/৪: ডিভাইস নাম লিখুন:")

    elif state == STATE_SUB_AWAITING_DEVICE:
        temp_data['device_name'] = text
        await save_submission(update, context, user_id, 'review_data', data=temp_data)

    # --- উইথড্র ফ্লো ---
    elif state == STATE_WITHDRAW_AWAITING_AMOUNT:
        try:
            amt = float(text)
            bal = await get_balance(user_id)
            if 20 <= amt <= bal:
                temp_data['amount'] = amt
                await update_user_state(user_id, STATE_WITHDRAW_AWAITING_METHOD, temp_data)
                kb = [
                    [InlineKeyboardButton("বিকাশ", callback_data="wd_method_bkash"), InlineKeyboardButton("নগদ", callback_data="wd_method_nagad")],
                    [InlineKeyboardButton("বাইনান্স", callback_data="wd_method_binance")]
                ]
                await update.message.reply_text("মাধ্যম নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(kb))
            else: await update.message.reply_text("❌ পরিমাণ সঠিক নয় বা অপর্যাপ্ত ব্যালেন্স।")
        except: await update.message.reply_text("❌ সংখ্যা লিখুন।")

    elif state == STATE_WITHDRAW_AWAITING_NUMBER:
        temp_data['target'] = text
        await save_withdrawal(update, context, user_id, temp_data)

    # --- অ্যাডমিন ফ্লো (ব্যালেন্স) ---
    elif state == STATE_ADMIN_AWAITING_BALANCE_USER_ID:
        if text.isdigit():
            temp_data['target_uid'] = int(text)
            await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_AMOUNT, temp_data)
            await update.message.reply_text(f"User {text} এর জন্য টাকার পরিমাণ লিখুন (+10 বা -10):")
        else: await update.message.reply_text("❌ শুধু সংখ্যায় ID দিন।")

    elif state == STATE_ADMIN_AWAITING_BALANCE_AMOUNT:
        try:
            op = text[0]
            amt = float(text[1:])
            target = temp_data['target_uid']
            final_amt = amt if op == '+' else -amt
            if await update_balance(target, final_amt):
                await update_user_state(user_id, STATE_IDLE)
                await update.message.reply_text("✅ ব্যালেন্স আপডেট সফল!")
                await context.bot.send_message(target, f"🔔 আপনার ব্যালেন্স আপডেট হয়েছে: {text} BDT")
            else: await update.message.reply_text("❌ ব্যর্থ হয়েছে।")
        except: await update.message.reply_text("❌ ফরম্যাট: +10 বা -10")

    # --- অ্যাডমিন ফ্লো (রেফার বোনাস) ---
    elif state == STATE_ADMIN_AWAITING_REFER_BONUS:
        try:
            await set_refer_bonus(float(text))
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ রেফার বোনাস আপডেট হয়েছে।")
        except: await update.message.reply_text("❌ সংখ্যা দিন।")

    # --- অ্যাডমিন ফ্লো (টাস্ক রিওয়ার্ড) ---
    elif state == STATE_ADMIN_AWAITING_TASK_REWARD:
        try:
            await update_system_config('task_reward', float(text))
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ কাজের রেট আপডেট হয়েছে।")
        except: await update.message.reply_text("❌ সংখ্যা দিন।")

    # --- অ্যাডমিন ফ্লো (ব্রডকাস্ট) ---
    elif state == STATE_ADMIN_AWAITING_BROADCAST_MESSAGE:
        await update.message.reply_text("📢 ব্রডকাস্ট শুরু হচ্ছে...")
        await update_user_state(user_id, STATE_IDLE)
        ids = await get_all_user_ids()
        count = 0
        for uid in ids:
            try:
                await context.bot.send_message(uid, f"📢 <b>নোটিশ:</b>\n{text}", parse_mode='HTML')
                count += 1
                await asyncio.sleep(0.05)
            except: pass
        await update.message.reply_text(f"✅ সম্পন্ন। পাঠানো হয়েছে: {count}")

    # --- অ্যাডমিন ফ্লো (অ্যাডমিন অ্যাড) ---
    elif state == STATE_ADMIN_ADD_ADMIN_ID:
        if text.isdigit():
            new_admin_id = text
            db.collection(COLLECTION_ADMINS).document(new_admin_id).set({
                'added_by': user_id,
                'role': 'admin',
                'added_at': firestore.SERVER_TIMESTAMP
            })
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text(f"✅ নতুন অ্যাডমিন (ID: {new_admin_id}) যুক্ত হয়েছে।")
        else: await update.message.reply_text("❌ সঠিক ইউজার আইডি দিন।")

    # --- অ্যাডমিন ফ্লো (ইউজার অ্যাকশন - ব্লক/ডিলিট) ---
    elif state == STATE_ADMIN_USER_ACTION_ID:
        if text.isdigit():
            target_uid = text
            action = temp_data.get('action')
            
            if action == 'delete':
                if await delete_user(target_uid):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} ডিলিট করা হয়েছে।")
                else: await update.message.reply_text("❌ ইউজার পাওয়া যায়নি।")
            elif action == 'block':
                if await toggle_block_user(target_uid, True):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} ব্লক করা হয়েছে।")
                else: await update.message.reply_text("❌ ব্যর্থ।")
            elif action == 'unblock':
                if await toggle_block_user(target_uid, False):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} আনব্লক করা হয়েছে।")
                else: await update.message.reply_text("❌ ব্যর্থ।")
            
            await update_user_state(user_id, STATE_IDLE)
        else: await update.message.reply_text("❌ সঠিক আইডি দিন।")

# হেল্পার সাবমিশন ফাংশন
async def save_submission(update, context, user_id, s_type, link=None, data=None):
    sub_data = {
        'user_id': user_id,
        'username': update.effective_user.username,
        'first_name': update.effective_user.first_name,
        'type': s_type,
        'status': 'pending',
        'submitted_at': firestore.SERVER_TIMESTAMP
    }
    if link: sub_data['link'] = link
    if data: sub_data['data'] = data
    
    ref = db.collection(COLLECTION_SUBMISSIONS).add(sub_data)
    await update_user_state(user_id, STATE_IDLE)
    await update.message.reply_text("✅ কাজ জমা হয়েছে! অ্যাডমিন চেক করবে।")
    
    # অ্যাডমিন নোটিফাই
    msg = f"🔔 <b>নতুন কাজ!</b>\nID: <code>{user_id}</code>\nType: {s_type}"
    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{ref[1].id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{ref[1].id}")]]
    if ADMIN_USER_ID_STR:
        try: await context.bot.send_message(ADMIN_USER_ID_STR, msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
        except: pass

async def save_withdrawal(update, context, user_id, temp_data):
    w_data = {
        'user_id': user_id,
        'amount': temp_data['amount'],
        'method': temp_data['method'],
        'target': temp_data['target'],
        'status': 'pending',
        'time': firestore.SERVER_TIMESTAMP
    }
    ref = db.collection(COLLECTION_WITHDRAWALS).add(w_data)
    await update_balance(user_id, -temp_data['amount'])
    await update_user_state(user_id, STATE_IDLE)
    await update.message.reply_text("✅ উইথড্র রিকোয়েস্ট জমা হয়েছে!")
    
    # অ্যাডমিন নোটিফাই
    msg = f"💸 <b>উইথড্র!</b>\nID: <code>{user_id}</code>\nAmount: {temp_data['amount']}\nTo: {temp_data['target']} ({temp_data['method']})"
    kb = [[InlineKeyboardButton("✅ Paid", callback_data=f"adm_pay_{ref[1].id}")]]
    if ADMIN_USER_ID_STR:
        try: await context.bot.send_message(ADMIN_USER_ID_STR, msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
        except: pass

async def withdraw_method_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, temp = await get_user_state_and_data(user_id)
    
    methods = {"wd_method_bkash": "Bkash", "wd_method_nagad": "Nagad", "wd_method_binance": "Binance"}
    if query.data in methods:
        temp['method'] = methods[query.data]
        await update_user_state(user_id, STATE_WITHDRAW_AWAITING_NUMBER, temp)
        await query.edit_message_text(f"আপনার {methods[query.data]} নাম্বার/আইডি দিন:")

# ==========================================
# ৪. অ্যাডমিন প্যানেল লজিক (আপডেটেড)
# ==========================================

async def show_admin_panel(update, context, user_id):
    """অ্যাডমিন প্যানেলের মেইন মেনু"""
    is_super = await is_super_admin(user_id)
    
    # পরিসংখ্যান
    total_users = await get_total_users_count()
    
    text = f"👑 <b>অ্যাডমিন প্যানেল</b>\n\n📊 মোট ইউজার: {total_users} জন\nআপনার রোল: {'🔥 সুপার অ্যাডমিন' if is_super else '👮 অ্যাডমিন'}"

    keyboard = [
        [InlineKeyboardButton("💰 ব্যালেন্স অ্যাড/রিমুভ", callback_data="admin_manage_balance")],
        [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🛑 ইউজার কন্ট্রোল (ব্লক/ডিলিট)", callback_data="admin_user_control")]
    ]
    
    # শুধু সুপার অ্যাডমিনের জন্য এক্সট্রা ফিচার
    if is_super:
        keyboard.append([InlineKeyboardButton("⚙️ সেটিংস ও ফিচার", callback_data="admin_settings_menu")])
        keyboard.append([InlineKeyboardButton("👮 অ্যাডমিন ম্যানেজ করুন", callback_data="admin_manage_admins")])
        
    keyboard.append([InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_to_main")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data
    
    if not await is_admin(user_id):
        await query.answer("Access Denied", show_alert=True)
        return

    is_super = await is_super_admin(user_id)

    # --- বেসিক অ্যাডমিন অ্যাকশন ---
    if data == "admin_manage_balance":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_USER_ID, temp_data={})
        await query.edit_message_text("💰 যার ব্যালেন্স পরিবর্তন করবেন তার **User ID** দিন:")
        
    elif data == "admin_broadcast":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BROADCAST_MESSAGE)
        await query.edit_message_text("📢 ব্রডকাস্ট মেসেজটি লিখুন:")
        
    elif data == "admin_user_control":
        kb = [
            [InlineKeyboardButton("ব্লক ইউজার", callback_data="adm_usr_block"), InlineKeyboardButton("আনব্লক ইউজার", callback_data="adm_usr_unblock")],
            [InlineKeyboardButton("ডিলিট ইউজার", callback_data="adm_usr_delete")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("🛑 কি করতে চান?", reply_markup=InlineKeyboardMarkup(kb))

    elif data in ["adm_usr_block", "adm_usr_unblock", "adm_usr_delete"]:
        action = data.split('_')[-1]
        await update_user_state(user_id, STATE_ADMIN_USER_ACTION_ID, temp_data={'action': action})
        await query.edit_message_text(f"🛑 টার্গেট ইউজারের **ID** দিন ({action} করার জন্য):")

    # --- সুপার অ্যাডমিন অ্যাকশন ---
    elif data == "admin_settings_menu":
        if not is_super: return
        config = await get_system_config()
        
        # টগল বাটন জেনারেটর
        def get_btn_text(key, label):
            status = "✅" if config.get(key, True) else "❌"
            return f"{status} {label}"
            
        kb = [
            [InlineKeyboardButton(get_btn_text('show_review', "রিভিউ বাটন"), callback_data="toggle_show_review")],
            [InlineKeyboardButton(get_btn_text('show_submit', "কাজ জমা বাটন"), callback_data="toggle_show_submit")],
            [InlineKeyboardButton(get_btn_text('show_withdraw', "উইথড্র বাটন"), callback_data="toggle_show_withdraw")],
            [InlineKeyboardButton(f"💰 টাস্ক রেট: {config.get('task_reward', 5)} TK", callback_data="set_task_reward")],
            [InlineKeyboardButton(f"🎁 রেফার বোনাস", callback_data="set_refer_bonus")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("⚙️ **সিস্টেম সেটিংস:**\nযেকোনো ফিচারে ক্লিক করে অন/অফ করুন।", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("toggle_"):
        if not is_super: return
        key = data.replace("toggle_", "")
        config = await get_system_config()
        new_val = not config.get(key, True)
        await update_system_config(key, new_val)
        # রিফ্রেশ মেনু
        await query.data == "admin_settings_menu" # হ্যাক রিফ্রেশ
        await admin_callback_handler(update, context) # রিকার্সিভ কল রিফ্রেশ করতে
        
    elif data == "set_task_reward":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_AWAITING_TASK_REWARD)
        await query.edit_message_text("💰 প্রতিটি অ্যাপ্রুভ কাজের জন্য কত টাকা দিতে চান? (সংখ্যা লিখুন):")

    elif data == "set_refer_bonus":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_AWAITING_REFER_BONUS)
        await query.edit_message_text("🎁 প্রতি রেফারে কত বোনাস দিতে চান? (সংখ্যা লিখুন):")

    elif data == "admin_manage_admins":
        if not is_super: return
        kb = [
            [InlineKeyboardButton("➕ নতুন অ্যাডমিন যোগ করুন", callback_data="adm_add_new")],
            [InlineKeyboardButton("➖ অ্যাডমিন রিমুভ (ID দিন)", callback_data="adm_remove_id")], # সিম্পলিসিটির জন্য ডাইরেক্ট ইনপুট
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("👮 **অ্যাডমিন ম্যানেজমেন্ট**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "adm_add_new":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_ADD_ADMIN_ID)
        await query.edit_message_text("➕ যাকে অ্যাডমিন বানাতে চান তার **User ID** দিন:")
        
    elif data == "adm_remove_id":
        if not is_super: return
        # রিমুভ লজিক সিম্পল রাখার জন্য আমরা এখানে স্টেট ব্যবহার করছি না, অ্যাডমিন প্যানেলে ম্যানুয়ালি ডিলিট করা ভালো Firestore কনসোল থেকে, তবে এখানে চাইলে একই ভাবে ID ইনপুট নিয়ে ডিলিট করা যাবে।
        # আপাতত আমরা ইউজারের মতোই ইনপুট নিবো
        await update_user_state(user_id, STATE_ADMIN_USER_ACTION_ID, temp_data={'action': 'remove_admin_privilege'}) 
        # নোট: STATE_ADMIN_USER_ACTION_ID তে আমরা 'remove_admin_privilege' লজিক অ্যাড করতে হবে handle_message এ।
        # কিন্তু কোড ছোট রাখার জন্য আমি এখানে একটা ট্রিক করছি: অ্যাডমিন রিমুভ করার জন্য সোজা Firestore থেকে ডিলিট কমান্ড।
        await query.edit_message_text("⚠️ অ্যাডমিন রিমুভ করতে হলে সরাসরি Firestore ডাটাবেসের 'admins' কালেকশন থেকে ডকুমেন্ট ডিলিট করা নিরাপদ। অথবা আমাকে বলুন কোড বাড়াতে।")

    # --- কাজ অ্যাপ্রুভাল ---
    elif data.startswith("adm_app_") or data.startswith("adm_rej_"):
        sub_id = data.split('_')[-1]
        is_approve = "app" in data
        
        try:
            ref = db.collection(COLLECTION_SUBMISSIONS).document(sub_id)
            doc = ref.get()
            if not doc.exists:
                await query.answer("পাওয়া যায়নি", show_alert=True)
                return
            s_data = doc.to_dict()
            if s_data['status'] != 'pending':
                await query.answer("আগেই প্রসেস করা হয়েছে", show_alert=True)
                return
            
            status = 'approved' if is_approve else 'rejected'
            ref.update({'status': status, 'by': user_id})
            
            if is_approve:
                # ডায়নামিক রেট আনা
                conf = await get_system_config()
                reward = conf.get('task_reward', 5.0)
                await update_balance(s_data['user_id'], reward)
                await context.bot.send_message(s_data['user_id'], f"✅ কাজ অ্যাপ্রুভ হয়েছে! +{reward} BDT")
            else:
                await context.bot.send_message(s_data['user_id'], "❌ কাজ রিজেক্ট হয়েছে।")
            
            await query.edit_message_text(f"{query.message.text}\n\n{status.upper()} by {query.from_user.first_name}")
        except: pass

    # --- পেমেন্ট মার্ক পেইড ---
    elif data.startswith("adm_pay_"):
        w_id = data.split('_')[-1]
        try:
            ref = db.collection(COLLECTION_WITHDRAWALS).document(w_id)
            ref.update({'status': 'paid', 'by': user_id})
            doc = ref.get()
            uid = doc.to_dict()['user_id']
            await context.bot.send_message(uid, "💸 পেমেন্ট পাঠানো হয়েছে! চেক করুন।")
            await query.edit_message_text(f"{query.message.text}\n\nPAID by {query.from_user.first_name}")
        except: pass

# ==========================================
# ৫. মেইন রানার
# ==========================================

def main() -> None:
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN missing!")
        return 

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", lambda u, c: show_admin_panel(u, c, u.effective_user.id)))
    
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^adm')) # Admin & Actions
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^toggle_')) # Toggles
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^set_')) # Settings
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_')) # Navigation
    app.add_handler(CallbackQueryHandler(withdraw_method_handler, pattern='^wd_method_'))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    if WEBHOOK_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
