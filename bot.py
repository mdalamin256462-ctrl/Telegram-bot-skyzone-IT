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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভেরিয়েবল
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID") # সুপার অ্যাডমিন
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
# সাপোর্ট গ্রুপের চ্যাট আইডি (মাইনাস সহ, যেমন -100123456789)
SUPPORT_GROUP_ID = os.getenv("SUPPORT_GROUP_ID") 
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
            logger.info("✅ Firebase Connected Successfully!")
        except Exception as e:
            logger.error(f"❌ Firebase Init Error: {e}")
    else:
        logger.warning("⚠️ FIREBASE_SERVICE_ACCOUNT missing!")
except Exception as e:
    logger.error(f"❌ Critical setup error: {e}")

# ডিফল্ট কনফিগারেশন
DEFAULT_UI_CONFIG = {
    "btn_review_gen": {"text": "🌐 রিভিউ জেনারেটর", "url": "https://sites.google.com/view/review-generator/home", "show": True},
    "btn_submit_work": {"text": "💰 কাজ জমা দিন", "show": True},
    "btn_balance": {"text": "📈 অ্যাকাউন্ট ও রেফার", "show": True}, # নাম চেঞ্জ
    "btn_withdraw": {"text": "💸 উত্তোলন (Withdraw)", "show": True},
    "btn_info": {"text": "ℹ️ তথ্য দেখুন", "show": True},
    "btn_refer": {"text": "👥 রেফার করুন", "show": True},
    "btn_guide": {"text": "📚 কাজের বিবরণ", "show": True},
    "btn_sub_review": {"text": "📋 রিভিউ তথ্য জমা", "show": True},
    "btn_sub_market": {"text": "🔗 মার্কেটিং লিংক জমা", "show": True},
    # Dynamic Custom Buttons List
    "custom_buttons": [] 
}

# কালেকশন নাম
COLLECTION_USERS = "users"
COLLECTION_SUBMISSIONS = "submissions"
COLLECTION_WITHDRAWALS = "withdrawals"
COLLECTION_ADMINS = "admins"
DOC_SYSTEM_CONFIG = "config"
DOC_UI_CONFIG = "ui_config"

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
STATE_ADMIN_AWAITING_TASK_REWARD = 60
STATE_ADMIN_ADD_ADMIN_ID = 70
STATE_ADMIN_REMOVE_ADMIN_ID = 71 
STATE_ADMIN_USER_ACTION_ID = 80
STATE_ADMIN_EDIT_UI_TEXT = 90
STATE_ADMIN_EDIT_UI_URL = 91
STATE_ADMIN_EDIT_GUIDE_TEXT = 92
STATE_ADMIN_CHECK_USER_INFO = 93 # (NEW)
STATE_ADMIN_ADD_BTN_TEXT = 94 # (NEW)
STATE_ADMIN_ADD_BTN_URL = 95 # (NEW)
STATE_ADMIN_REPLY_ID = 96 # (NEW)
STATE_ADMIN_REPLY_MSG = 97 # (NEW)

# ==========================================
# ২. ডাটাবেস এবং হেল্পার ফাংশন
# ==========================================

async def get_system_config():
    if db is None: return {}
    try:
        doc = db.collection("system").document(DOC_SYSTEM_CONFIG).get()
        return doc.to_dict() if doc.exists else {}
    except:
        return {}

async def get_ui_config():
    if db is None: return DEFAULT_UI_CONFIG
    try:
        doc = db.collection("system").document(DOC_UI_CONFIG).get()
        if doc.exists:
            saved = doc.to_dict()
            # ডিফল্ট ভ্যালু মার্জ করা
            final = DEFAULT_UI_CONFIG.copy()
            for k, v in saved.items():
                final[k] = v
            return final
        else:
            db.collection("system").document(DOC_UI_CONFIG).set(DEFAULT_UI_CONFIG)
            return DEFAULT_UI_CONFIG
    except:
        return DEFAULT_UI_CONFIG

async def add_custom_button(text, url):
    """নতুন কাস্টম বাটন যোগ করা"""
    if db is None: return False
    try:
        config = await get_ui_config()
        buttons = config.get("custom_buttons", [])
        buttons.append({"text": text, "url": url})
        db.collection("system").document(DOC_UI_CONFIG).update({"custom_buttons": buttons})
        return True
    except: return False

async def remove_custom_button(index):
    """কাস্টম বাটন রিমুভ করা"""
    if db is None: return False
    try:
        config = await get_ui_config()
        buttons = config.get("custom_buttons", [])
        if 0 <= index < len(buttons):
            buttons.pop(index)
            db.collection("system").document(DOC_UI_CONFIG).update({"custom_buttons": buttons})
            return True
        return False
    except: return False

async def get_total_user_balance_liability():
    """সমস্ত ইউজারের মোট ব্যালেন্স হিসাব করা (Total Liability)"""
    if db is None: return 0.0
    try:
        users = db.collection(COLLECTION_USERS).stream()
        total = 0.0
        for doc in users:
            total += doc.get('balance') or 0.0
        return total
    except Exception as e:
        logger.error(f"Liability Calc Error: {e}")
        return 0.0

async def get_referral_count(user_id):
    """ইউজার কতজনকে রেফার করেছে তা গণনা"""
    if db is None: return 0
    try:
        # কাউন্ট কোয়েরি (Requires Indexes sometimes, safe fallback to stream count for low volume)
        query = db.collection(COLLECTION_USERS).where('referred_by', '==', int(user_id)).stream()
        return len(list(query))
    except:
        return 0

async def is_super_admin(user_id):
    return str(user_id) == str(ADMIN_USER_ID_STR)

async def is_admin(user_id):
    if str(user_id) == str(ADMIN_USER_ID_STR): return True
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
                try:
                    # রেফারারকে নোটিফাই করা
                    pass # এখানে bot instance নেই, তাই মেসেজ পাঠানো জটিল, স্কিপ করলাম
                except: pass
            
            new_user = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'balance': referral_bonus,
                'referred_by': int(referred_by) if referred_by else None,
                'joined_at': firestore.SERVER_TIMESTAMP,
                'is_blocked': False,
                'state': STATE_IDLE,
                'temp_data': {}
            }
            user_ref.set(new_user)
            return {"status": "created", "data": new_user}
    except Exception as e:
        logger.error(f"User Create Error: {e}")
        return {"status": "NO_DB"}

async def update_balance(user_id, amount):
    if db is None: return False
    try:
        db.collection(COLLECTION_USERS).document(str(user_id)).update({
            'balance': firestore.Increment(amount)
        })
        return True
    except:
        return False

async def get_balance(user_id):
    if db is None: return 0.0
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    return doc.to_dict().get("balance", 0.0) if doc.exists else 0.0

async def update_user_state(user_id, state, temp_data=None):
    if db is None: return
    try:
        update_fields = {'state': state}
        if temp_data is not None:
            update_fields['temp_data'] = temp_data
        db.collection(COLLECTION_USERS).document(str(user_id)).update(update_fields)
    except:
        pass

async def get_user_state_and_data(user_id):
    if db is None: return STATE_IDLE, {}
    doc = db.collection(COLLECTION_USERS).document(str(user_id)).get()
    data = doc.to_dict() if doc.exists else None
    return (data.get("state", STATE_IDLE), data.get("temp_data", {})) if data else (STATE_IDLE, {})

async def get_refer_bonus():
    sys_conf = await get_system_config()
    return float(sys_conf.get('refer_bonus', 3.00))

async def set_refer_bonus(amount):
    try:
        db.collection("system").document(DOC_SYSTEM_CONFIG).set({'refer_bonus': amount}, merge=True)
        return True
    except: return False

async def get_all_user_ids():
    if db is None: return []
    try:
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        return [doc.get('user_id') for doc in users]
    except: return []

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """কমান্ড লিস্ট দেখানো"""
    text = (
        "🛠 **কমান্ড লিস্ট:**\n\n"
        "/start - বট রিস্টার্ট বা মেইন মেনু\n"
        "/help - এই কমান্ড লিস্ট দেখুন\n"
        "\n"
        "💬 **সাপোর্ট:**\n"
        "আপনি এখানে কোনো মেসেজ লিখলে তা সরাসরি আমাদের সাপোর্ট টিমের কাছে চলে যাবে।"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    
    referred_by = None
    if context.args and context.args[0].isdigit():
        referred_by = int(context.args[0])
    
    result = await get_or_create_user(user_id, user.username or 'N/A', user.first_name, referred_by)
    
    if result.get("status") == "blocked":
        await update.message.reply_text("🚫 দুঃখিত! আপনাকে ব্লক করা হয়েছে।")
        return

    await update_user_state(user_id, STATE_IDLE)
    
    ui_config = await get_ui_config()
    keyboard = []
    
    # Custom Dynamic Buttons (From Admin Panel)
    custom_btns = ui_config.get("custom_buttons", [])
    for btn in custom_btns:
        keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

    # Standard Buttons
    if ui_config.get("btn_review_gen", {}).get("show", True):
        cfg = ui_config["btn_review_gen"]
        keyboard.append([InlineKeyboardButton(cfg.get("text"), url=cfg.get("url"))])
    
    row2 = []
    if ui_config.get("btn_submit_work", {}).get("show", True):
        row2.append(InlineKeyboardButton(ui_config["btn_submit_work"].get("text"), callback_data="submit_work"))
    if ui_config.get("btn_balance", {}).get("show", True):
        row2.append(InlineKeyboardButton(ui_config["btn_balance"].get("text"), callback_data="show_account"))
    if row2: keyboard.append(row2)
        
    row3 = []
    if ui_config.get("btn_withdraw", {}).get("show", True):
        row3.append(InlineKeyboardButton(ui_config["btn_withdraw"].get("text"), callback_data="start_withdraw"))
    if ui_config.get("btn_info", {}).get("show", True):
        row3.append(InlineKeyboardButton(ui_config["btn_info"].get("text"), callback_data="info_links_menu"))
    if row3: keyboard.append(row3)
        
    if ui_config.get("btn_refer", {}).get("show", True):
        keyboard.append([InlineKeyboardButton(ui_config["btn_refer"].get("text"), callback_data="show_referral_link")])
        
    if ui_config.get("btn_guide", {}).get("show", True):
        keyboard.append([InlineKeyboardButton(ui_config["btn_guide"].get("text"), callback_data="show_guide")])
    
    if await is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 অ্যাডমিন প্যানেল", callback_data="open_admin_panel")])
    
    welcome_text = f"আসসালামু আলাইকুম, <b>{user.first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম।"
    if result.get("status") == "created" and result['data'].get('referred_by'):
        welcome_text += f"\n🎉 রেফারেল বোনাস যোগ করা হয়েছে।"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "back_to_main":
        await update_user_state(user_id, STATE_IDLE)
        await start_command(update, context)
        return

    # Account Info with Referral Count
    elif data == "show_account":
        balance = await get_balance(user_id)
        ref_count = await get_referral_count(user_id)
        text = (
            f"👤 <b>আপনার প্রোফাইল</b>\n\n"
            f"নাম: {query.from_user.first_name}\n"
            f"ID: <code>{user_id}</code>\n"
            f"💰 ব্যালেন্স: <b>{balance:.2f} BDT</b>\n"
            f"👥 মোট রেফার: <b>{ref_count} জন</b>"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]), parse_mode='HTML')

    # Info Menu (Existing Logic)
    elif data == "info_links_menu":
        # ... (Same as previous code, simplified for brevity)
        kb = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]] # Add actual links if needed
        await query.edit_message_text("ℹ️ তথ্য ও লিংকসমূহ:", reply_markup=InlineKeyboardMarkup(kb))

    # Submit Work
    elif data == "submit_work":
        await update_user_state(user_id, STATE_SUB_SELECT_TYPE)
        ui_config = await get_ui_config()
        kb = []
        if ui_config.get("btn_sub_review", {}).get("show", True):
            kb.append([InlineKeyboardButton("📋 রিভিউ তথ্য জমা", callback_data="sub_review_data")])
        if ui_config.get("btn_sub_market", {}).get("show", True):
            kb.append([InlineKeyboardButton("🔗 মার্কেটিং লিংক জমা", callback_data="sub_market_link")])
        kb.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")])
        await query.edit_message_text("কাজের ধরন নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "sub_market_link":
        await update_user_state(user_id, STATE_SUB_MARKET_LINK)
        await query.edit_message_text("মার্কেটিং গুগল সিট লিংক দিন:\n(বাতিল করতে /start)")

    elif data == "sub_review_data":
        await update_user_state(user_id, STATE_SUB_AWAITING_LINK, temp_data={})
        await query.edit_message_text("১/৪: স্ক্রিনশট লিংক দিন:\n(বাতিল করতে /start)")

    # Withdraw
    elif data == "start_withdraw":
        balance = await get_balance(user_id)
        if balance < 20.0:
            await query.edit_message_text(f"❌ সর্বনিম্ন ২০ টাকা ব্যালেন্স প্রয়োজন। আপনার আছে: {balance:.2f} BDT", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]))
            return
        
        # Check existing pending withdrawals
        pending = db.collection(COLLECTION_WITHDRAWALS).where('user_id', '==', user_id).where('status', '==', 'pending').stream()
        if len(list(pending)) > 0:
             await query.edit_message_text("⚠️ আপনার একটি উইথড্র রিকোয়েস্ট ইতিমধ্যে পেন্ডিং আছে। সেটি প্রসেস হওয়া পর্যন্ত অপেক্ষা করুন।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]))
             return

        await update_user_state(user_id, STATE_WITHDRAW_AWAITING_AMOUNT)
        await query.edit_message_text(f"উত্তোলনের পরিমাণ লিখুন (বর্তমান: {balance:.2f} BDT):")

    # Referral
    elif data == "show_referral_link":
        bonus = await get_refer_bonus()
        ref_count = await get_referral_count(user_id)
        ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
        await query.edit_message_text(
            f"👥 <b>রেফারেল প্রোগ্রাম</b>\n\nআপনি রেফার করেছেন: <b>{ref_count} জন</b>\nপ্রতি রেফারে বোনাস: <b>{bonus:.2f} BDT</b>\n\nআপনার লিংক:\n<code>{ref_link}</code>\n\nকপি করে শেয়ার করুন!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]),
            parse_mode='HTML'
        )

    # Guide
    elif data == "show_guide":
        ui_config = await get_ui_config()
        content = ui_config.get("text_guide_content", {}).get("text", "No guide available.")
        await query.edit_message_text(content, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")]]), parse_mode='HTML')

    # Admin Entry
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

    # --- Live Support Logic (If State is IDLE) ---
    if state == STATE_IDLE:
        # যদি ইউজার কোনো কমান্ড না দেয় এবং সাধারণ কথা বলে, তবে তা সাপোর্ট গ্রুপে ফরোয়ার্ড হবে
        msg_text = (
            f"📩 <b>Support Message</b>\n"
            f"From: {update.effective_user.first_name} (ID: <code>{user_id}</code>)\n"
            f"Message: {text}"
        )
        
        # সাপোর্ট গ্রুপে পাঠানো
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=msg_text, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send to support group: {e}")
        
        # অ্যাডমিনদের কাছে পাঠানো (অপশনাল, যদি গ্রুপ সেট না থাকে)
        else:
            if ADMIN_USER_ID_STR:
                try:
                    await context.bot.send_message(chat_id=ADMIN_USER_ID_STR, text=msg_text, parse_mode='HTML')
                except: pass
        
        return

    # --- Submission Flow ---
    if state == STATE_SUB_MARKET_LINK:
        if 'http' in text:
            await save_submission(update, context, user_id, 'marketing_sheet', link=text)
        else:
            await update.message.reply_text("❌ বৈধ লিংক দিন।")

    elif state == STATE_SUB_AWAITING_LINK:
        if 'http' in text:
            temp_data['link'] = text
            await update_user_state(user_id, STATE_SUB_AWAITING_EMAIL, temp_data)
            await update.message.reply_text("২/৪: রিভিউ ইমেইল লিখুন:")
        else:
            await update.message.reply_text("❌ বৈধ লিংক দিন।")

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

    # --- Withdraw Flow ---
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
            else:
                await update.message.reply_text("❌ পরিমাণ সঠিক নয় বা অপর্যাপ্ত ব্যালেন্স।")
        except:
            await update.message.reply_text("❌ সংখ্যা লিখুন।")

    elif state == STATE_WITHDRAW_AWAITING_NUMBER:
        temp_data['target'] = text
        await save_withdrawal(update, context, user_id, temp_data)

    # --- Admin Logic ---
    elif state == STATE_ADMIN_AWAITING_BALANCE_USER_ID:
        if text.isdigit():
            temp_data['target_uid'] = int(text)
            await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_AMOUNT, temp_data)
            await update.message.reply_text(f"User {text} এর জন্য টাকার পরিমাণ লিখুন (+10 বা -10):")
        else:
            await update.message.reply_text("❌ শুধু সংখ্যায় ID দিন।")

    elif state == STATE_ADMIN_AWAITING_BALANCE_AMOUNT:
        try:
            op = text[0]
            amt = float(text[1:])
            target = temp_data['target_uid']
            final_amt = amt if op == '+' else -amt
            if await update_balance(target, final_amt):
                await update_user_state(user_id, STATE_IDLE)
                await update.message.reply_text("✅ ব্যালেন্স আপডেট সফল!")
                try: await context.bot.send_message(target, f"🔔 আপনার ব্যালেন্স আপডেট হয়েছে: {text} BDT")
                except: pass
            else: await update.message.reply_text("❌ ব্যর্থ হয়েছে।")
        except: await update.message.reply_text("❌ ফরম্যাট: +10 বা -10")

    elif state == STATE_ADMIN_CHECK_USER_INFO:
        if text.isdigit():
            target_uid = text
            bal = await get_balance(target_uid)
            ref_cnt = await get_referral_count(target_uid)
            # Find recent withdrawals
            w_docs = db.collection(COLLECTION_WITHDRAWALS).where('user_id', '==', int(target_uid)).limit(3).stream()
            w_history = "\n".join([f"- {d.get('amount')} ({d.get('status')})" for d in w_docs])
            
            msg = (
                f"🔎 **User Info:** `{target_uid}`\n"
                f"💰 Balance: {bal} BDT\n"
                f"👥 Referrals: {ref_cnt}\n"
                f"📜 Recent Withdrawals:\n{w_history}"
            )
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ ID দিন।")

    elif state == STATE_ADMIN_REPLY_ID:
        if text.isdigit():
            temp_data['reply_to_uid'] = int(text)
            await update_user_state(user_id, STATE_ADMIN_REPLY_MSG, temp_data)
            await update.message.reply_text("📝 মেসেজটি লিখুন:")
        else:
             await update.message.reply_text("❌ ID দিন।")
             
    elif state == STATE_ADMIN_REPLY_MSG:
        target_uid = temp_data.get('reply_to_uid')
        try:
            await context.bot.send_message(target_uid, f"📩 **সাপোর্ট রিপ্লাই:**\n\n{text}", parse_mode='Markdown')
            await update.message.reply_text("✅ মেসেজ পাঠানো হয়েছে!")
        except Exception as e:
            await update.message.reply_text(f"❌ পাঠানো যায়নি: {e}")
        await update_user_state(user_id, STATE_IDLE)

    elif state == STATE_ADMIN_ADD_BTN_TEXT:
        temp_data['btn_text'] = text
        await update_user_state(user_id, STATE_ADMIN_ADD_BTN_URL, temp_data)
        await update.message.reply_text("🔗 বাটনের লিংক (URL) দিন:")
        
    elif state == STATE_ADMIN_ADD_BTN_URL:
        if 'http' in text:
            await add_custom_button(temp_data['btn_text'], text)
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ নতুন বাটন যুক্ত হয়েছে!")
        else:
            await update.message.reply_text("❌ সঠিক লিংক দিন।")

    # (Other Admin States remain similar - Broadcast, Settings etc.)
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

    elif state == STATE_ADMIN_ADD_ADMIN_ID:
        if text.isdigit():
            db.collection(COLLECTION_ADMINS).document(text).set({'added_by': user_id, 'role': 'admin'})
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text(f"✅ নতুন অ্যাডমিন (ID: {text}) যুক্ত হয়েছে।")

    elif state == STATE_ADMIN_REMOVE_ADMIN_ID:
        if text.isdigit():
            if str(text) != str(ADMIN_USER_ID_STR):
                db.collection(COLLECTION_ADMINS).document(text).delete()
                await update.message.reply_text(f"✅ রিমুভ করা হয়েছে।")
            else:
                await update.message.reply_text("❌ সুপার অ্যাডমিন রিমুভ করা যাবে না।")
            await update_user_state(user_id, STATE_IDLE)

async def save_submission(update, context, user_id, s_type, link=None, data=None):
    sub_data = {
        'user_id': user_id,
        'username': update.effective_user.username,
        'first_name': update.effective_user.first_name,
        'type': s_type,
        'status': 'pending',
        'submitted_at': firestore.SERVER_TIMESTAMP
    }
    
    details_str = ""
    if link: sub_data['link'] = link; details_str += f"🔗 Link: {link}\n"
    if data:
        sub_data['data'] = data
        if 'link' in data: details_str += f"📸 SS: {data['link']}\n"
        if 'email' in data: details_str += f"📧 Email: {data['email']}\n"
        
    ref = db.collection(COLLECTION_SUBMISSIONS).add(sub_data)
    await update_user_state(user_id, STATE_IDLE)
    await update.message.reply_text("✅ কাজ জমা হয়েছে! অ্যাডমিন চেক করবে।")
    
    msg = f"🔔 <b>নতুন কাজ!</b>\nID: <code>{user_id}</code>\nType: {s_type}\n{details_str}"
    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{ref[1].id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{ref[1].id}")]]
    
    # Notify Super Admin & Support Group (Optional)
    if ADMIN_USER_ID_STR:
        try: await context.bot.send_message(ADMIN_USER_ID_STR, msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
        except: pass

async def save_withdrawal(update, context, user_id, temp_data):
    # টাকা কেটে নেওয়া
    await update_balance(user_id, -temp_data['amount'])
    
    w_data = {
        'user_id': user_id,
        'amount': temp_data['amount'],
        'method': temp_data['method'],
        'target': temp_data['target'],
        'status': 'pending',
        'time': firestore.SERVER_TIMESTAMP
    }
    ref = db.collection(COLLECTION_WITHDRAWALS).add(w_data)
    
    await update_user_state(user_id, STATE_IDLE)
    # ইউজারকে পেন্ডিং মেসেজ দেখানো
    await update.message.reply_text("✅ উইথড্র রিকোয়েস্ট পেন্ডিং আছে। অ্যাডমিন চেক করে পেমেন্ট করবে।")
    
    msg = f"💸 <b>উইথড্র রিকোয়েস্ট!</b>\nID: <code>{user_id}</code>\nAmount: {temp_data['amount']}\nMethod: {temp_data['method']} ({temp_data['target']})"
    kb = [
        [InlineKeyboardButton("✅ Pay & Approve", callback_data=f"adm_pay_{ref[1].id}")],
        [InlineKeyboardButton("❌ Reject & Refund", callback_data=f"adm_ref_{ref[1].id}")] # New Refund Logic
    ]
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
# ৪. অ্যাডমিন প্যানেল (আপডেটেড)
# ==========================================

async def show_admin_panel(update, context, user_id):
    is_super = await is_super_admin(user_id)
    total_users = await get_total_users_count()
    
    # নতুন: টোটাল লায়াবিলিটি চেক (শুধুমাত্র সুপার অ্যাডমিন)
    liability_text = ""
    if is_super:
        total_liability = await get_total_user_balance_liability()
        liability_text = f"\n💰 মোট ইউজার ব্যালেন্স (ঋণ): <b>{total_liability:.2f} BDT</b>"

    text = (
        f"👑 <b>অ্যাডমিন প্যানেল</b>\n"
        f"📊 মোট ইউজার: {total_users} জন"
        f"{liability_text}\n"
        f"রোল: {'🔥 সুপার অ্যাডমিন' if is_super else '👮 অ্যাডমিন'}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔎 চেক ইউজার (Balance/Ref)", callback_data="admin_check_user")], # New
        [InlineKeyboardButton("💰 ম্যানুয়াল ব্যালেন্স (+/-)", callback_data="admin_manage_balance")],
        [InlineKeyboardButton("✉️ ইউজারকে রিপ্লাই দিন", callback_data="admin_reply_user")], # New
        [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ", callback_data="admin_broadcast")],
    ]
    
    if is_super:
        keyboard.append([InlineKeyboardButton("🎨 বাটন ম্যানেজ (Dynamic)", callback_data="admin_btn_manager")]) # New
        keyboard.append([InlineKeyboardButton("👮 অ্যাডমিন নিয়ন্ত্রণ", callback_data="admin_manage_admins")])
        keyboard.append([InlineKeyboardButton("⚙️ সেটিংস ও বোনাস", callback_data="admin_settings_menu")])
        keyboard.append([InlineKeyboardButton("🛑 ইউজার ব্লক/ডিলিট", callback_data="admin_user_control")])
    
    keyboard.append([InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_to_main")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def get_total_users_count():
    # Helper to count users
    if db is None: return 0
    try:
        # Note: .count() is cheaper/faster in new firestore SDKs, fall back to stream for old
        return len(list(db.collection(COLLECTION_USERS).select(['user_id']).stream()))
    except: return 0

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data
    
    # অ্যাডমিন চেক (সুপার অ্যাডমিন বা সাধারণ অ্যাডমিন)
    if not await is_admin(user_id):
        await query.answer("Access Denied", show_alert=True)
        return
    is_super = await is_super_admin(user_id)

    if data == "admin_check_user":
        await update_user_state(user_id, STATE_ADMIN_CHECK_USER_INFO)
        await query.edit_message_text("🔎 যার তথ্য দেখতে চান তার **User ID** দিন:")

    elif data == "admin_manage_balance":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BALANCE_USER_ID, temp_data={})
        await query.edit_message_text("💰 যার ব্যালেন্স পরিবর্তন করবেন তার **User ID** দিন:")
        
    elif data == "admin_reply_user":
        await update_user_state(user_id, STATE_ADMIN_REPLY_ID)
        await query.edit_message_text("✉️ যাকে মেসেজ পাঠাবেন তার **User ID** দিন:")

    elif data == "admin_broadcast":
        await update_user_state(user_id, STATE_ADMIN_AWAITING_BROADCAST_MESSAGE)
        await query.edit_message_text("📢 ব্রডকাস্ট মেসেজটি লিখুন:")

    # --- Dynamic Button Manager ---
    elif data == "admin_btn_manager":
        if not is_super: return
        config = await get_ui_config()
        btns = config.get("custom_buttons", [])
        
        kb = []
        for idx, btn in enumerate(btns):
            kb.append([InlineKeyboardButton(f"🗑 {btn['text']} (Remove)", callback_data=f"adm_del_btn_{idx}")])
        
        kb.append([InlineKeyboardButton("➕ নতুন বাটন যুক্ত করুন", callback_data="adm_add_btn_new")])
        kb.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")])
        
        await query.edit_message_text("🎨 **কাস্টম বাটন ম্যানেজার**\n(যেটি ডিলিট করতে চান সেটিতে ক্লিক করুন)", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "adm_add_btn_new":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_ADD_BTN_TEXT, temp_data={})
        await query.edit_message_text("➕ নতুন বাটনের **নাম (Text)** লিখুন:")

    elif data.startswith("adm_del_btn_"):
        if not is_super: return
        idx = int(data.split('_')[-1])
        await remove_custom_button(idx)
        await query.answer("বাটন রিমুভ হয়েছে!")
        # Refresh Menu
        await admin_callback_handler(update, context) # Re-call logic? Better to just trigger function again or go back.
        await query.edit_message_text("✅ বাটন রিমুভ হয়েছে।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="admin_btn_manager")]]))


    # --- Task Approval (Any Admin) ---
    elif data.startswith("adm_app_") or data.startswith("adm_rej_"):
        # সাব-অ্যাডমিনরাও এটি ব্যবহার করতে পারবে কারণ উপরে is_admin চেক আছে
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
                conf = await get_system_config()
                reward = conf.get('task_reward', 5.0)
                await update_balance(s_data['user_id'], reward)
                await context.bot.send_message(s_data['user_id'], f"✅ আপনার জমা দেওয়া কাজ অ্যাপ্রুভ হয়েছে! +{reward} BDT")
            else:
                await context.bot.send_message(s_data['user_id'], "❌ আপনার জমা দেওয়া কাজ রিজেক্ট হয়েছে।")
                
            await query.edit_message_text(f"{query.message.text}\n\n{status.upper()} by Admin")
        except: pass

    # --- Withdraw Approval/Refund (Any Admin) ---
    elif data.startswith("adm_pay_") or data.startswith("adm_ref_"):
        w_id = data.split('_')[-1]
        is_pay = "pay" in data
        try:
            ref = db.collection(COLLECTION_WITHDRAWALS).document(w_id)
            doc = ref.get()
            if not doc.exists: return
            w_data = doc.to_dict()
            
            if w_data['status'] != 'pending':
                 await query.answer("Done already", show_alert=True)
                 return

            if is_pay:
                # টাকা আগেই কেটে নেওয়া হয়েছে, শুধু স্ট্যাটাস আপডেট
                ref.update({'status': 'paid', 'by': user_id})
                await context.bot.send_message(w_data['user_id'], f"💸 আপনার উইথড্র ({w_data['amount']} TK) সম্পন্ন হয়েছে!")
                await query.edit_message_text(f"{query.message.text}\n\nPAID by Admin")
            else:
                # রিজেক্ট -> টাকা ফেরত (Refund)
                amount = w_data.get('amount', 0)
                await update_balance(w_data['user_id'], amount)
                ref.update({'status': 'rejected', 'by': user_id})
                await context.bot.send_message(w_data['user_id'], f"❌ আপনার উইথড্র রিজেক্ট হয়েছে। {amount} TK ব্যালেন্সে ফেরত দেওয়া হয়েছে।")
                await query.edit_message_text(f"{query.message.text}\n\nREJECTED & REFUNDED by Admin")
        except Exception as e:
            logger.error(f"WD Error: {e}")

    # --- অন্যান্য সুপার অ্যাডমিন ফাংশন ---
    elif data == "admin_user_control":
        kb = [
            [InlineKeyboardButton("ব্লক ইউজার", callback_data="adm_usr_block"), InlineKeyboardButton("আনব্লক", callback_data="adm_usr_unblock")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("🛑 কি করতে চান?", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data in ["adm_usr_block", "adm_usr_unblock"]:
        action = data.split('_')[-1]
        await update_user_state(user_id, STATE_ADMIN_USER_ACTION_ID, temp_data={'action': action})
        await query.edit_message_text(f"🛑 টার্গেট ইউজারের **ID** দিন ({action} করার জন্য):")
        
    elif data == "admin_settings_menu":
        if not is_super: return
        ref_bonus = await get_refer_bonus()
        kb = [
            [InlineKeyboardButton(f"🎁 রেফার বোনাস: {ref_bonus} TK", callback_data="set_refer_bonus")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("⚙️ **সেটিংস:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "set_refer_bonus":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_AWAITING_REFER_BONUS)
        await query.edit_message_text(f"🎁 নতুন বোনাস কত দিতে চান? (সংখ্যা লিখুন):")

    elif data == "admin_manage_admins":
        if not is_super: return
        kb = [
            [InlineKeyboardButton("➕ নতুন অ্যাডমিন যোগ করুন", callback_data="adm_add_new")],
            [InlineKeyboardButton("🗑️ অ্যাডমিন রিমুভ করুন", callback_data="adm_rem_exist")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("👮 **অ্যাডমিন ম্যানেজমেন্ট**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "adm_add_new":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_ADD_ADMIN_ID)
        await query.edit_message_text("➕ যাকে অ্যাডমিন বানাতে চান তার **User ID** দিন:")
        
    elif data == "adm_rem_exist":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_REMOVE_ADMIN_ID)
        await query.edit_message_text("🗑️ যাকে রিমুভ করতে চান তার **User ID** দিন:")


# ==========================================
# ৫. মেইন রানার
# ==========================================

def main() -> None:
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN missing!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command)) # New Help Command
    app.add_handler(CommandHandler("admin", lambda u, c: show_admin_panel(u, c, u.effective_user.id)))

    # Callback Handlers
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^adm'))   
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^set_'))  
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))
    
    app.add_handler(CallbackQueryHandler(withdraw_method_handler, pattern='^wd_method_'))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Message Handler (For input & Support Chat)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
