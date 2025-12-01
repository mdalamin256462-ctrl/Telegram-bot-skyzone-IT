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
PORT = int(os.environ.get('PORT', 8080))
REALTIME_DATABASE_URL = "https://telegram-bot-skyzone-it-default-rtdb.firebaseio.com" # আপনার RTDB লিংক দিন অথবা env তে রাখুন

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

# ডিফল্ট কনফিগারেশন (UI এবং টেক্সট)
# নতুন বাটন বা টেক্সট যোগ করতে চাইলে এখানে ডিফল্ট ভ্যালু দিন
DEFAULT_UI_CONFIG = {
    # Main Menu Buttons
    "btn_review_gen": {"text": "🌐 রিভিউ জেনারেটর", "url": "https://sites.google.com/view/review-generator/home", "show": True},
    "btn_submit_work": {"text": "💰 কাজ জমা দিন", "show": True},
    "btn_balance": {"text": "📈 ব্যালেন্স", "show": True},
    "btn_withdraw": {"text": "💸 উত্তোলন (Withdraw)", "show": True},
    "btn_info": {"text": "ℹ️ তথ্য দেখুন", "show": True},
    "btn_refer": {"text": "👥 রেফার করুন", "show": True},
    "btn_guide": {"text": "📚 কাজের বিবরণ", "show": True},
    
    # Submit Work Sub-Menu Buttons (NEW)
    "btn_sub_review": {"text": "📋 রিভিউ তথ্য জমা", "show": True},
    "btn_sub_market": {"text": "🔗 মার্কেটিং লিংক জমা", "show": True},

    # Info Menu Links
    "link_fb_group": {"text": "ফেসবুক গ্রুপ", "url": "https://www.facebook.com/groups/1853319645292519/?ref=share&mibextid=NSMWBT", "show": True},
    "link_fb_page": {"text": "ফেসবুক পেজ", "url": "https://www.facebook.com/share/1BX4LQfrq9/", "show": True},
    "link_yt": {"text": "ইউটিউব চ্যানেল", "url": "https://youtube.com/@af.mdshakil?si=QoHvBxpnY4-laCQi", "show": True},
    "link_tg_channel": {"text": "টেলিগ্রাম চ্যানেল", "url": "https://t.me/Skyzone_IT", "show": True},
    "link_tg_group": {"text": "টেলিগ্রাম গ্রুপ", "url": "https://t.me/Skyzone_IT_chat", "show": True},
    "link_tg_payment": {"text": "পেমেন্ট চ্যানেল", "url": "https://t.me/brotheritltd", "show": True},
    "link_website": {"text": "🌐 ওয়েবসাইট", "url": "https://brotheritltd.com", "show": True},
    "link_support": {"text": "👨‍💻 সাপোর্ট (অ্যাডমিন)", "url": "https://t.me/AfMdshakil", "show": True},

    # Dynamic Texts (NEW)
    "text_guide_content": {"text": "📚 <b>কাজের নিয়মাবলী:</b>\n\n১. লিংক থেকে কাজ সম্পন্ন করুন।\n২. সঠিক প্রমাণ জমা দিন।\n৩. অ্যাডমিন চেক করে পেমেন্ট করবে।", "show": True}
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
STATE_ADMIN_REMOVE_ADMIN_ID = 71 # (NEW)
STATE_ADMIN_USER_ACTION_ID = 80
STATE_ADMIN_EDIT_UI_TEXT = 90
STATE_ADMIN_EDIT_UI_URL = 91
STATE_ADMIN_EDIT_GUIDE_TEXT = 92 # (NEW)

# ==========================================
# ২. ডাটাবেস এবং হেল্পার ফাংশন
# ==========================================

async def get_system_config():
    """সিস্টেম কনফিগারেশন আনা (রেট, টগলস)"""
    if db is None: return {}
    try:
        doc = db.collection("system").document(DOC_SYSTEM_CONFIG).get()
        return doc.to_dict() if doc.exists else {}
    except:
        return {}

async def get_ui_config():
    """UI বাটন এবং লিংক কনফিগারেশন আনা"""
    if db is None: return DEFAULT_UI_CONFIG
    try:
        doc = db.collection("system").document(DOC_UI_CONFIG).get()
        if doc.exists:
            saved_config = doc.to_dict()
            # ডিফল্ট কনফিগের সাথে মার্জ করা যাতে নতুন কী মিস না হয়
            final_config = DEFAULT_UI_CONFIG.copy()
            # রিকার্সিভ আপডেট বা সাধারণ আপডেট
            for k, v in saved_config.items():
                if k in final_config and isinstance(final_config[k], dict) and isinstance(v, dict):
                    final_config[k].update(v)
                else:
                    final_config[k] = v
            return final_config
        else:
            db.collection("system").document(DOC_UI_CONFIG).set(DEFAULT_UI_CONFIG)
            return DEFAULT_UI_CONFIG
    except Exception as e:
        logger.error(f"UI Config Error: {e}")
        return DEFAULT_UI_CONFIG

async def update_ui_element(key, field, value):
    """UI এর নির্দিষ্ট এলিমেন্ট আপডেট করা"""
    if db is None: return False
    try:
        db.collection("system").document(DOC_UI_CONFIG).update({
            f"{key}.{field}": value
        })
        return True
    except:
        full_config = await get_ui_config()
        if key in full_config:
            full_config[key][field] = value
        else:
            # যদি নতুন কী হয়
            full_config[key] = {field: value, "show": True}
        
        db.collection("system").document(DOC_UI_CONFIG).set(full_config)
        return True

async def update_system_config(key, value):
    if db is None: return False
    try:
        db.collection("system").document(DOC_SYSTEM_CONFIG).update({key: value})
        return True
    except:
        db.collection("system").document(DOC_SYSTEM_CONFIG).set({key: value}, merge=True)
        return True

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
            # নিজের রেফার কোড ব্যবহার রোধ
            if referred_by and str(user_id) != str(referred_by):
                bonus_amount = await get_refer_bonus()
                await update_balance(referred_by, bonus_amount)
                # অপশনাল: রেফারকারীকে নোটিফাই করা
                logger.info(f"Referral bonus {bonus_amount} given to {referred_by}")
            
            new_user = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'balance': referral_bonus, # জয়েনিং বোনাস চাইলে এখানে দিতে পারেন
                'referred_by': referred_by,
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
    # Firestore থেকে কনফিগ চেক
    sys_conf = await get_system_config()
    if 'refer_bonus' in sys_conf:
        return float(sys_conf['refer_bonus'])
    return 3.00  # ডিফল্ট

async def set_refer_bonus(amount):
    await update_system_config('refer_bonus', amount)
    return True

async def get_all_user_ids():
    if db is None: return []
    try:
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        return [doc.get('user_id') for doc in users]
    except:
        return []

async def get_total_users_count():
    if db is None: return 0
    try:
        # কাউন্ট কোয়েরি ব্যবহার করলে ভালো, তবে ছোট স্কেলে এটি কাজ করবে
        users = db.collection(COLLECTION_USERS).select(['user_id']).stream()
        return len(list(users))
    except:
        return 0

async def delete_user(user_id):
    if db is None: return False
    try:
        db.collection(COLLECTION_USERS).document(str(user_id)).delete()
        return True
    except:
        return False

async def toggle_block_user(user_id, block_status):
    if db is None: return False
    try:
        db.collection(COLLECTION_USERS).document(str(user_id)).update({'is_blocked': block_status})
        return True
    except:
        return False

async def remove_admin(admin_id):
    if db is None: return False
    try:
        # সুপার এডমিনকে রিমুভ করা যাবে না
        if str(admin_id) == str(ADMIN_USER_ID_STR):
            return False
        db.collection(COLLECTION_ADMINS).document(str(admin_id)).delete()
        return True
    except:
        return False

# ==========================================
# ৩. ইউজার হ্যান্ডেলার (User Handlers)
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    
    referred_by = None
    if context.args and context.args[0].isdigit():
        referred_by = int(context.args[0])
    
    result = await get_or_create_user(user_id, user.username or 'N/A', user.first_name, referred_by)
    
    if result.get("status") == "blocked":
        text = "🚫 দুঃখিত! আপনাকে ব্লক করা হয়েছে।"
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    await update_user_state(user_id, STATE_IDLE)
    
    # ডায়নামিক কনফিগারেশন লোড
    ui_config = await get_ui_config()
    keyboard = []
    
    # ১. রিভিউ জেনারেটর
    if ui_config.get("btn_review_gen", {}).get("show", True):
        cfg = ui_config["btn_review_gen"]
        keyboard.append([InlineKeyboardButton(cfg.get("text", "🌐 রিভিউ জেনারেটর"), url=cfg.get("url"))])
    
    # ২. কাজ এবং ব্যালেন্স
    row2 = []
    if ui_config.get("btn_submit_work", {}).get("show", True):
        row2.append(InlineKeyboardButton(ui_config["btn_submit_work"].get("text", "💰 কাজ জমা দিন"), callback_data="submit_work"))
    if ui_config.get("btn_balance", {}).get("show", True):
        row2.append(InlineKeyboardButton(ui_config["btn_balance"].get("text", "📈 ব্যালেন্স"), callback_data="show_account"))
    if row2:
        keyboard.append(row2)
        
    # ৩. উইথড্র এবং ইনফো
    row3 = []
    if ui_config.get("btn_withdraw", {}).get("show", True):
        row3.append(InlineKeyboardButton(ui_config["btn_withdraw"].get("text", "💸 উত্তোলন"), callback_data="start_withdraw"))
    if ui_config.get("btn_info", {}).get("show", True):
        row3.append(InlineKeyboardButton(ui_config["btn_info"].get("text", "ℹ️ তথ্য দেখুন"), callback_data="info_links_menu"))
    if row3:
        keyboard.append(row3)
        
    # ৪. রেফার
    if ui_config.get("btn_refer", {}).get("show", True):
        keyboard.append([InlineKeyboardButton(ui_config["btn_refer"].get("text", "👥 রেফার করুন"), callback_data="show_referral_link")])
        
    # ৫. গাইড
    if ui_config.get("btn_guide", {}).get("show", True):
        keyboard.append([InlineKeyboardButton(ui_config["btn_guide"].get("text", "📚 কাজের বিবরণ"), callback_data="show_guide")])
    
    # অ্যাডমিন
    if await is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 অ্যাডমিন প্যানেল", callback_data="open_admin_panel")])
    
    welcome_text = f"আসসালামু আলাইকুম, <b>{user.first_name}</b>! 👋\n\nSkyzone IT বট-এ আপনাকে স্বাগতম।"
    if result.get("status") == "created" and result['data'].get('referred_by'):
        welcome_text += f"\n🎉 রেফারেল বোনাস যোগ করা হয়েছে।"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except:
            await context.bot.send_message(chat_id=user_id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
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

    # ডায়নামিক ইনফো মেনু
    if data == "info_links_menu":
        ui_config = await get_ui_config()
        link_keyboard = []
        
        def get_link_btn(key):
            cfg = ui_config.get(key, {})
            if cfg.get("show", True):
                return InlineKeyboardButton(cfg.get("text", "Link"), url=cfg.get("url"))
            return None

        # Row 1
        r1 = []
        b1 = get_link_btn("link_fb_group")
        b2 = get_link_btn("link_fb_page")
        if b1: r1.append(b1)
        if b2: r1.append(b2)
        if r1: link_keyboard.append(r1)
        
        # Row 2
        r2 = []
        b3 = get_link_btn("link_yt")
        b4 = get_link_btn("link_tg_channel")
        if b3: r2.append(b3)
        if b4: r2.append(b4)
        if r2: link_keyboard.append(r2)

        # Row 3
        r3 = []
        b5 = get_link_btn("link_tg_group")
        b6 = get_link_btn("link_tg_payment")
        if b5: r3.append(b5)
        if b6: r3.append(b6)
        if r3: link_keyboard.append(r3)

        # Website & Support
        b7 = get_link_btn("link_website")
        if b7: link_keyboard.append([b7])
        b8 = get_link_btn("link_support")
        if b8: link_keyboard.append([b8])
        
        link_keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")])
        await query.edit_message_text(
            "ℹ️ <b>সকল তথ্য ও লিংকসমূহ:</b>\n\nনিচের বাটনগুলো ব্যবহার করে আমাদের সাথে যুক্ত হন।",
            reply_markup=InlineKeyboardMarkup(link_keyboard), parse_mode='HTML'
        )
        return

    # কাজ জমা দেওয়া (Dynamic Sub-buttons)
    if data == "submit_work":
        await update_user_state(user_id, STATE_SUB_SELECT_TYPE)
        ui_config = await get_ui_config()
        keyboard = []
        
        if ui_config.get("btn_sub_review", {}).get("show", True):
            keyboard.append([InlineKeyboardButton(ui_config["btn_sub_review"].get("text", "📋 রিভিউ তথ্য জমা"), callback_data="sub_review_data")])
        
        if ui_config.get("btn_sub_market", {}).get("show", True):
            keyboard.append([InlineKeyboardButton(ui_config["btn_sub_market"].get("text", "🔗 মার্কেটিং লিংক জমা"), callback_data="sub_market_link")])
            
        keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="back_to_main")])
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

    # গাইড (Dynamic Content)
    elif data == "show_guide":
        ui_config = await get_ui_config()
        content = ui_config.get("text_guide_content", {}).get("text", "No guide available.")
        await query.edit_message_text(
            content,
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
            else:
                await update.message.reply_text("❌ পরিমাণ সঠিক নয় বা অপর্যাপ্ত ব্যালেন্স।")
        except:
            await update.message.reply_text("❌ সংখ্যা লিখুন।")
            
    elif state == STATE_WITHDRAW_AWAITING_NUMBER:
        temp_data['target'] = text
        await save_withdrawal(update, context, user_id, temp_data)

    # --- অ্যাডমিন ফ্লো (ব্যালেন্স) ---
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
                try:
                    await context.bot.send_message(target, f"🔔 আপনার ব্যালেন্স আপডেট হয়েছে: {text} BDT")
                except: pass
            else:
                await update.message.reply_text("❌ ব্যর্থ হয়েছে।")
        except:
            await update.message.reply_text("❌ ফরম্যাট: +10 বা -10")

    # --- অ্যাডমিন ফ্লো (রেফার বোনাস) ---
    elif state == STATE_ADMIN_AWAITING_REFER_BONUS:
        try:
            val = float(text)
            await set_refer_bonus(val)
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text(f"✅ রেফার বোনাস আপডেট হয়েছে: {val} TK")
        except:
            await update.message.reply_text("❌ সংখ্যা দিন।")

    # --- অ্যাডমিন ফ্লো (টাস্ক রিওয়ার্ড) ---
    elif state == STATE_ADMIN_AWAITING_TASK_REWARD:
        try:
            await update_system_config('task_reward', float(text))
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ কাজের রেট আপডেট হয়েছে।")
        except:
            await update.message.reply_text("❌ সংখ্যা দিন।")

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

    # --- অ্যাডমিন ফ্লো (অ্যাডমিন অ্যাড/রিমুভ) ---
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
        else:
            await update.message.reply_text("❌ সঠিক ইউজার আইডি দিন।")

    elif state == STATE_ADMIN_REMOVE_ADMIN_ID:
        if text.isdigit():
            target_id = text
            if await remove_admin(target_id):
                await update.message.reply_text(f"✅ অ্যাডমিন {target_id} রিমুভ করা হয়েছে।")
            else:
                await update.message.reply_text("❌ ব্যর্থ! হয়তো আইডি ভুল বা সুপার অ্যাডমিনকে রিমুভ করার চেষ্টা করছেন।")
            await update_user_state(user_id, STATE_IDLE)
        else:
            await update.message.reply_text("❌ সঠিক আইডি দিন।")

    # --- অ্যাডমিন ফ্লো (ইউজার অ্যাকশন - ব্লক/ডিলিট) ---
    elif state == STATE_ADMIN_USER_ACTION_ID:
        if text.isdigit():
            target_uid = text
            action = temp_data.get('action')
            
            if action == 'delete':
                if await delete_user(target_uid):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} ডিলিট করা হয়েছে।")
                else:
                    await update.message.reply_text("❌ ইউজার পাওয়া যায়নি।")
            elif action == 'block':
                if await toggle_block_user(target_uid, True):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} ব্লক করা হয়েছে।")
                else:
                    await update.message.reply_text("❌ ব্যর্থ।")
            elif action == 'unblock':
                if await toggle_block_user(target_uid, False):
                    await update.message.reply_text(f"✅ ইউজার {target_uid} আনব্লক করা হয়েছে।")
                else:
                    await update.message.reply_text("❌ ব্যর্থ।")
            
            await update_user_state(user_id, STATE_IDLE)
        else:
            await update.message.reply_text("❌ সঠিক আইডি দিন।")

    # --- UI এডিট ফ্লো ---
    elif state == STATE_ADMIN_EDIT_UI_TEXT:
        target_key = temp_data.get('target_key')
        await update_ui_element(target_key, 'text', text)
        await update_user_state(user_id, STATE_IDLE)
        await update.message.reply_text("✅ টেক্সট পরিবর্তন হয়েছে।")

    elif state == STATE_ADMIN_EDIT_UI_URL:
        target_key = temp_data.get('target_key')
        if 'http' in text:
            await update_ui_element(target_key, 'url', text)
            await update_user_state(user_id, STATE_IDLE)
            await update.message.reply_text("✅ লিংক পরিবর্তন হয়েছে।")
        else:
            await update.message.reply_text("❌ সঠিক লিংক দিন (https://...)")
            
    elif state == STATE_ADMIN_EDIT_GUIDE_TEXT: # (NEW)
        # এখানে text_guide_content আপডেট হবে
        await update_ui_element('text_guide_content', 'text', text)
        await update_user_state(user_id, STATE_IDLE)
        await update.message.reply_text("✅ গাইড কন্টেন্ট আপডেট হয়েছে!")

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
    
    # সাবমিশন ডিটেইলস তৈরি করা (অ্যাডমিন নোটিফিকেশনের জন্য)
    details_str = ""
    
    if link:
        sub_data['link'] = link
        details_str += f"🔗 Link: {link}\n"
        
    if data:
        sub_data['data'] = data
        if 'link' in data: details_str += f"📸 SS: {data['link']}\n"
        if 'email' in data: details_str += f"📧 Email: {data['email']}\n"
        if 'review_name' in data: details_str += f"👤 Name: {data['review_name']}\n"
        if 'device_name' in data: details_str += f"📱 Device: {data['device_name']}\n"

    ref = db.collection(COLLECTION_SUBMISSIONS).add(sub_data)
    await update_user_state(user_id, STATE_IDLE)
    await update.message.reply_text("✅ কাজ জমা হয়েছে! অ্যাডমিন চেক করবে।")
    
    # অ্যাডমিন নোটিফিকেশন (সংশোধিত)
    msg = f"🔔 <b>নতুন কাজ জমা!</b>\n\n🆔 User ID: <code>{user_id}</code>\n📂 Type: {s_type}\n\n📝 <b>Details:</b>\n{details_str}"
    
    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{ref[1].id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{ref[1].id}")]]
    
    if ADMIN_USER_ID_STR:
        try:
            await context.bot.send_message(ADMIN_USER_ID_STR, msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
        except:
            pass

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
    
    msg = f"💸 <b>উইথড্র!</b>\nID: <code>{user_id}</code>\nAmount: {temp_data['amount']}\nTo: {temp_data['target']} ({temp_data['method']})"
    kb = [[InlineKeyboardButton("✅ Paid", callback_data=f"adm_pay_{ref[1].id}")]]
    if ADMIN_USER_ID_STR:
        try:
            await context.bot.send_message(ADMIN_USER_ID_STR, msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
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
    total_users = await get_total_users_count()
    
    text = f"👑 <b>অ্যাডমিন প্যানেল</b>\n\n📊 মোট ইউজার: {total_users} জন\nআপনার রোল: {'🔥 সুপার অ্যাডমিন' if is_super else '👮 অ্যাডমিন'}"
    
    keyboard = [
        [InlineKeyboardButton("💰 ব্যালেন্স অ্যাড/রিমুভ", callback_data="admin_manage_balance")],
        [InlineKeyboardButton("📢 ব্রডকাস্ট মেসেজ", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🛑 ইউজার কন্ট্রোল (ব্লক/ডিলিট)", callback_data="admin_user_control")]
    ]
    
    if is_super:
        keyboard.append([InlineKeyboardButton("🎨 UI এবং বাটন ম্যানেজমেন্ট", callback_data="admin_ui_menu")])
        keyboard.append([InlineKeyboardButton("⚙️ সেটিংস ও বোনাস", callback_data="admin_settings_menu")])
        keyboard.append([InlineKeyboardButton("👮 অ্যাডমিন ম্যানেজ করুন", callback_data="admin_manage_admins")])
        keyboard.append([InlineKeyboardButton("📝 গাইড এডিট করুন", callback_data="admin_edit_guide")]) # (NEW)
    
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

    # --- সুপার অ্যাডমিন সেটিংস ---
    elif data == "admin_settings_menu":
        if not is_super: return
        config = await get_system_config()
        ref_bonus = await get_refer_bonus()
        
        kb = [
            [InlineKeyboardButton(f"💰 টাস্ক রেট: {config.get('task_reward', 5)} TK", callback_data="set_task_reward")],
            [InlineKeyboardButton(f"🎁 রেফার বোনাস: {ref_bonus} TK", callback_data="set_refer_bonus")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("⚙️ **সিস্টেম সেটিংস:**\n(পরিবর্তন করতে বাটনে ক্লিক করুন)", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "set_task_reward":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_AWAITING_TASK_REWARD)
        await query.edit_message_text("💰 কাজের রেট (টাকা) কত হবে? (সংখ্যা লিখুন):")

    elif data == "set_refer_bonus":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_AWAITING_REFER_BONUS)
        await query.edit_message_text(f"🎁 নতুন বোনাস কত দিতে চান? (সংখ্যা লিখুন):")
        
    elif data == "admin_edit_guide":
        if not is_super: return
        await update_user_state(user_id, STATE_ADMIN_EDIT_GUIDE_TEXT)
        curr_text = (await get_ui_config()).get('text_guide_content', {}).get('text', 'N/A')
        await query.edit_message_text(f"📚 **নতুন গাইড কন্টেন্ট লিখুন:**\n\nবর্তমান:\n{curr_text[:50]}...", parse_mode='HTML')

    # --- UI ম্যানেজমেন্ট মেনু (Dynamic & Full Control) ---
    elif data == "admin_ui_menu":
        if not is_super: return
        kb = [
            [InlineKeyboardButton("মেনু বাটন (Home)", callback_data="aui_cat_home")],
            [InlineKeyboardButton("সাব-মেনু বাটন (Work)", callback_data="aui_cat_sub")], # (NEW)
            [InlineKeyboardButton("ইনফো লিংক (Info)", callback_data="aui_cat_info")],
            [InlineKeyboardButton("অন্যান্য (Misc)", callback_data="aui_cat_misc")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="open_admin_panel")]
        ]
        await query.edit_message_text("🎨 **কোন অংশের বাটন এডিট করবেন?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("aui_cat_"):
        if not is_super: return
        cat = data.split('_')[-1]
        ui_config = await get_ui_config()
        kb = []
        
        for key, val in ui_config.items():
            # Filter keys based on category to keep UI clean
            is_match = False
            if cat == "home" and key.startswith("btn_") and not key.startswith("btn_sub_"): is_match = True
            elif cat == "sub" and key.startswith("btn_sub_"): is_match = True
            elif cat == "info" and key.startswith("link_"): is_match = True
            elif cat == "misc" and not (key.startswith("btn_") or key.startswith("link_")): is_match = True
            
            if is_match:
                status = "👁️" if val.get("show", True) else "🚫"
                btn_name = val.get('text', key)[:25]
                kb.append([InlineKeyboardButton(f"{status} {btn_name}", callback_data=f"aui_sel_{key}")])
        
        kb.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="admin_ui_menu")])
        await query.edit_message_text(f"🔘 **{cat.upper()} সেকশন বাটন:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("aui_sel_"):
        if not is_super: return
        key = data.replace("aui_sel_", "")
        ui_config = await get_ui_config()
        item = ui_config.get(key, {})
        
        status_text = "Visible" if item.get("show", True) else "Hidden"
        toggle_action = "Hide" if item.get("show", True) else "Show"
        
        text = f"🔧 **Edit Item:** `{key}`\n\n📝 Text: {item.get('text')}\n🔗 Link: {item.get('url', 'N/A')}\n👀 Status: {status_text}"
        
        kb = [
            [InlineKeyboardButton("✏️ নাম পরিবর্তন (Text)", callback_data=f"aui_ren_{key}")],
            [InlineKeyboardButton(f"👁️ {toggle_action}", callback_data=f"aui_tog_{key}")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="admin_ui_menu")]
        ]
        
        # URL অপশন যোগ করা যদি URL ফিল্ড থাকে অথবা রিভিউ জেনারেটর হয়
        if "url" in item or key.startswith("link_") or key == "btn_review_gen":
            kb.insert(1, [InlineKeyboardButton("🔗 লিংক পরিবর্তন", callback_data=f"aui_url_{key}")])
            
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("aui_ren_"):
        key = data.replace("aui_ren_", "")
        await update_user_state(user_id, STATE_ADMIN_EDIT_UI_TEXT, temp_data={'target_key': key})
        await query.edit_message_text(f"📝 `{key}` এর জন্য নতুন নাম লিখুন:", parse_mode='Markdown')

    elif data.startswith("aui_url_"):
        key = data.replace("aui_url_", "")
        await update_user_state(user_id, STATE_ADMIN_EDIT_UI_URL, temp_data={'target_key': key})
        await query.edit_message_text(f"🔗 `{key}` এর জন্য নতুন লিংক লিখুন:", parse_mode='Markdown')

    elif data.startswith("aui_tog_"):
        key = data.replace("aui_tog_", "")
        ui_config = await get_ui_config()
        curr_show = ui_config.get(key, {}).get("show", True)
        await update_ui_element(key, 'show', not curr_show)
        
        # Simple confirmation and back
        new_status = "Hidden" if curr_show else "Visible"
        await query.edit_message_text(f"✅ Status updated to {new_status}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 লিস্টে ফিরে যান", callback_data="admin_ui_menu")]]))

    # --- অ্যাডমিন ম্যানেজমেন্ট ---
    elif data == "admin_manage_admins":
        if not is_super: return
        kb = [
            [InlineKeyboardButton("➕ নতুন অ্যাডমিন যোগ করুন", callback_data="adm_add_new")],
            [InlineKeyboardButton("🗑️ অ্যাডমিন রিমুভ করুন", callback_data="adm_rem_exist")], # (NEW)
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

    # Callback Handlers
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^adm'))   # Admin Actions
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^set_'))  # Settings
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))# Navigation
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^aui_'))  # Admin UI Control
    
    app.add_handler(CallbackQueryHandler(withdraw_method_handler, pattern='^wd_method_'))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
