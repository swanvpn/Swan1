import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
import jdatetime
from aiohttp import web
async def health_check(request):
    return web.Response(text='OK')
    async def run_web_server(app, port):
        runner = web.AppRunner(app)
        await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
        from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# تنظیمات اولیه و اتصال به دیتابیس
TOKEN = "9090743881:AAEX78oy_ZWi8E9RX4kGWn4YtHdsNTaHipA"
CARD_NUMBER = "6219861493813108"
CARD_HOLDER = "باقرزاده"
ADMIN_ID = 98695770

database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if database_url:
    engine = create_engine(database_url)
else:
    engine = create_engine("sqlite:///bot_data.db")

Base = declarative_base()

# مدل‌های دیتابیس
class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    balance = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    configs = relationship("UserConfig", backref="user")

class Service(Base):
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String)
    name = Column(String)
    price = Column(Integer)

class UserConfig(Base):
    __tablename__ = 'user_configs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    config_name = Column(String)
    config_details = Column(String)

class Request(Base):
    __tablename__ = 'requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    req_type = Column(String)
    plan_name = Column(String)
    status = Column(String, default='unanswered')
    created_at = Column(String)
    answered_at = Column(String)
    receipt_file_id = Column(String)

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# وضعیت‌های ماشین حالت (FSM)
class PaymentState(StatesGroup):
    waiting_for_receipt = State()
    waiting_for_charge_receipt = State()
    broadcasting = State()
    adjusting_balance = State()
    waiting_for_admin_config = State()
    direct_messaging = State()
    renaming_service = State()
    changing_price = State()

# مدیریت زمان
iran_timezone = timezone(timedelta(hours=3, minutes=30))

def get_current_jalali():
    now_gregorian = datetime.now(iran_timezone)
    shamsi_date = jdatetime.date.fromgregorian(date=now_gregorian.date()).strftime('%Y/%m/%d')
    shamsi_time = now_gregorian.strftime('%H:%M:%S')
    return f"{shamsi_date} - {shamsi_time}"

def get_jalali_date(gregorian_date):
    return jdatetime.date.fromgregorian(date=gregorian_date).strftime('%Y/%m/%d')

# پر کردن داده‌های اولیه سرویس‌ها
def init_services_db():
    session = SessionLocal()
    if session.query(Service).count() == 0:
        plans = [
            Service(category='economic', name='۱00 گیگ - ۲ کاربر', price=298000),
            Service(category='economic', name='۱00 گیگ - نامحدود', price=398000),
            Service(category='vip', name='10 گیگ', price=190000),
            Service(category='vip', name='20 گیگ', price=320000),
            Service(category='vip', name='30 گیگ', price=490000),
            Service(category='vip', name='50 گیگ', price=790000),
            Service(category='vip', name='100 گیگ', price=1330000),
            Service(category='gaming', name='10 گیگ', price=220000),
            Service(category='gaming', name='20 گیگ', price=360000),
            Service(category='gaming', name='30 گیگ', price=530000),
            Service(category='gaming', name='50 گیگ', price=850000)
        ]
        session.add_all(plans)
        session.commit()
    session.close()

init_services_db()
# توابع کمکی کیبوردها
def get_main_keyboard():
    btn_buy = KeyboardButton(text="🛒 خرید سرویس")
    btn_services = KeyboardButton(text="📦 سرویس‌های من")
    btn_tariffs = KeyboardButton(text="📈 تعرفه سرویس‌ها")
    btn_wallet = KeyboardButton(text="💳 شارژ کیف پول")
    btn_account = KeyboardButton(text="👤 حساب کاربری")
    btn_support = KeyboardButton(text="🎧 پشتیبانی")
    
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [btn_buy, btn_services],
            [btn_tariffs, btn_wallet],
            [btn_account, btn_support]
        ],
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="منوی اصلی ربات"
    )
    return markup

def get_admin_main_keyboard():
    btn_unanswered = InlineKeyboardButton(text="🔴 پاسخ داده نشده", callback_data="admin_unanswered")
    btn_answered = InlineKeyboardButton(text="🟢 پاسخ داده شده", callback_data="admin_answered")
    btn_users = InlineKeyboardButton(text="👥 مدیریت کاربران", callback_data="admin_users_list_page_1")
    btn_stats = InlineKeyboardButton(text="📈 آمار کلی فروش", callback_data="admin_sales_stats")
    btn_broadcast = InlineKeyboardButton(text="📢 ارسال پیام همگانی", callback_data="admin_broadcast_start")
    btn_home = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_unanswered, btn_answered],
        [btn_users],
        [btn_stats],
        [btn_broadcast],
        [btn_home]
    ])

def build_pagination_keyboard(current_page, total_pages, prefix, item_id=None):
    keyboard = []
    nav_buttons = []
    
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"{prefix}_page_{current_page - 1}{f'_{item_id}' if item_id else ''}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="ignore"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"{prefix}_page_{current_page + 1}{f'_{item_id}' if item_id else ''}"))
        
    keyword_buttons = [nav_buttons]
    return InlineKeyboardMarkup(inline_keyboard=keyword_buttons)

# بررسی وضعیت مسدود بودن کاربر
async def check_ban(message: types.Message):
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == message.from_user.id).first()
    session.close()
    return user and user.is_banned

# هندلر شروع و منوی اصلی
async def show_main_menu(message: types.Message):
    if await check_ban(message):
        return
    user_id = message.from_user.id
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, balance=0, is_banned=False)
        session.add(user)
        session.commit()
    session.close()
    
    markup = get_main_keyboard()
    await message.answer("سلام! به پنل Swan VPN خوش آمدید.\n/start", reply_markup=markup)

async def main_menu_handler_call(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    await state.clear()
    markup = get_main_keyboard()
    await call.message.answer("سلام! به پنل Swan VPN خوش آمدید.\n/start", reply_markup=markup)
    try:
        await call.message.delete()
    except Exception:
        pass
# هندلر نمایش تعرفه‌ها
async def tariffs_handler(message: types.Message):
    if await check_ban(message):
        return
    session = SessionLocal()
    services = session.query(Service).order_by(Service.category).all()
    session.close()
    
    current_cat = ""
    text = "📊 **لیست تعرفه و قیمت سرویس‌ها:**\n\n"
    for s in services:
        if s.category != current_cat:
            current_cat = s.category
            text += f"\n📂 **دسته‌بندی {current_cat.upper()}:**\n"
        text += f"🔹 {s.name}: {s.price:,} تومان\n"
        
    btn_back = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_back]])
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

# هندلرهای منوی خرید
async def message_buy_handler(message: types.Message, state: FSMContext):
    if await check_ban(message):
        return
    await state.clear()
    btn_econ = InlineKeyboardButton(text="🌱 سرویس اقتصادی", callback_data="cat_economic")
    btn_vip = InlineKeyboardButton(text="💎 سرویس وی‌آی‌پی", callback_data="cat_vip")
    btn_gaming = InlineKeyboardButton(text="🎮 سرویس گیمینگ", callback_data="cat_gaming")
    btn_back_main = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_econ], [btn_vip], [btn_gaming], [btn_back_main]])
    await message.answer("لطفاً دسته‌بندی مورد نظر را انتخاب کنید:", reply_markup=markup)

async def main_buy_handler(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    await state.clear()
    btn_econ = InlineKeyboardButton(text="🌱 سرویس اقتصادی", callback_data="cat_economic")
    btn_vip = InlineKeyboardButton(text="💎 سرویس وی‌آی‌پی", callback_data="cat_vip")
    btn_gaming = InlineKeyboardButton(text="🎮 سرویس گیمینگ", callback_data="cat_gaming")
    btn_back_main = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_econ], [btn_vip], [btn_gaming], [btn_back_main]])
    try:
        await call.message.edit_text("لطفاً دسته‌بندی مورد نظر را انتخاب کنید:", reply_markup=markup)
    except Exception:
        await call.message.answer("لطفاً دسته‌بندی مورد نظر را انتخاب کنید:", reply_markup=markup)

# نمایش داینامیک دکمه‌های خرید بر اساس دیتابیس
async def category_handler(call: types.CallbackQuery):
    if await check_ban(call.message):
        return
    try:
        await call.bot.set_message_reaction(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reaction=[ReactionTypeEmoji(emoji="👍")]
        )
    except Exception:
        pass
        
    category = call.data.split("_")[1]
    session = SessionLocal()
    services = session.query(Service).filter(Service.category == category).all()
    session.close()
    
    keyboard = []
    text = f"لیست پلن‌های {category.upper()}:\n\n"
    for s in services:
        text += f"🔹 {s.name}: {s.price:,} تومان\n"
        keyboard.append([InlineKeyboardButton(text=f"خرید {s.name}", callback_data=f"buy_{s.id}")])
        
    btn_back = InlineKeyboardButton(text="⬅️ برگشت به منوی خرید", callback_data="main_buy")
    keyboard.append([btn_back])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await call.message.edit_text(text, reply_markup=markup)

# شروع فرآیند خرید پلن انتخاب شده
async def buy_plan_handler(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    service_id = int(call.data.replace("buy_", ""))
    session = SessionLocal()
    service = session.query(Service).filter(Service.id == service_id).first()
    
    if not service:
        session.close()
        await call.message.answer("خطایی در یافتن سرویس رخ داد.")
        return
        
    plan_name = service.name
    price = service.price
    session.close()
    
    await state.set_state(PaymentState.waiting_for_receipt)
    await state.update_data(plan_name=plan_name, plan_price=price)
    
    text = (f"🛒 سفارش شما: {plan_name}\n"
            f"💰 مبلغ قابل پرداخت: {price:,} تومان\n\n"
            f"شما می‌توانید از طریق کارت یا موجودی کیف پول پرداخت کنید.\n\n"
            f"💳 شماره کارت جهت واریز:\n`{CARD_NUMBER}`\n"
            f"به نام: {CARD_HOLDER}\n\n"
            f"پس از واریز فیش را ارسال کنید یا در صورت داشتن موجودی کافی از دکمه زیر استفاده کنید.")
            
    btn_confirm = InlineKeyboardButton(text="✅ ارسال رسید واریز", callback_data="confirm_payment")
    btn_wallet = InlineKeyboardButton(text="💳 پرداخت از کیف پول", callback_data="pay_with_wallet")
    btn_back = InlineKeyboardButton(text="⬅️ انصراف و بازگشت", callback_data="main_buy")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_confirm], [btn_wallet], [btn_back]])
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
# پردازش پرداخت از طریق کیف پول
async def pay_with_wallet_handler(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    user_id = call.from_user.id
    data = await state.get_data()
    plan_name = data.get("plan_name", "سرویس")
    price = data.get("plan_price", 0)
    
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    
    if not user or user.balance < price:
        session.close()
        await call.answer(f"موجودی شما ({user.balance if user else 0:,} تومان) برای پرداخت این سرویس کافی نیست.", show_alert=True)
        return
        
    user.balance -= price
    created_at = get_current_jalali()
    
    new_request = Request(
        user_id=user_id,
        req_type='buy',
        plan_name=plan_name,
        status='unanswered',
        created_at=created_at,
        receipt_file_id='None'
    )
    session.add(new_request)
    session.commit()
    req_id = new_request.id
    session.close()
    
    await state.clear()
    await call.message.edit_text("✅ پرداخت با موفقیت از کیف پول انجام شد. لطفاً منتظر بررسی ادمین باشید. 🙏")
    
    try:
        user_info = f"@{call.from_user.username}" if call.from_user.username else f"آیدی: {call.from_user.id}"
        caption = (f"🚨 درخواست جدید با کیف پول (کد #{req_id})\n"
                   f"👤 کاربر: {user_info} ({user_id})\n"
                   f"📦 پلن: {plan_name}\n"
                   f"💰 مبلغ: {price:,} تومان\n"
                   f"⏱ زمان ثبت: {created_at}")
                   
        btn_confirm = InlineKeyboardButton(text="✅ تایید و ارسال کانفیگ", callback_data=f"admin_confirm_{req_id}")
        btn_reject = InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"admin_reject_{req_id}")
        btn_admin = InlineKeyboardButton(text="⚙️ پنل مدیریت", callback_data="admin_home")
        markup = InlineKeyboardMarkup(inline_keyboard=[[btn_confirm, btn_reject], [btn_admin]])
        await call.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=markup)
    except Exception as e:
        print(f"Error sending wallet purchase to admin: {e}")

# دریافت رسید واریز کارت به کارت
async def confirm_payment_handler(call: types.CallbackQuery):
    if await check_ban(call.message):
        return
    await call.message.edit_text("لطفاً اسکرین‌شات یا عکس رسید واریزی خود را در چت بفرستید تا بررسی شود.")

async def receipt_handler(message: types.Message, state: FSMContext):
    if await check_ban(message):
        return
    data = await state.get_data()
    plan_name = data.get("plan_name", "سرویس نامشخص")
    created_at = get_current_jalali()
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id
    
    session = SessionLocal()
    new_request = Request(
        user_id=user_id,
        req_type='buy',
        plan_name=plan_name,
        status='unanswered',
        created_at=created_at,
        receipt_file_id=photo_id
    )
    session.add(new_request)
    session.commit()
    req_id = new_request.id
    session.close()
    
    await state.clear()
    await message.answer(f"رسید شما در تاریخ {created_at} دریافت شد و به زودی بررسی می‌شود. با تشکر از خرید شما! 🙏")
    
    try:
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"آیدی: {message.from_user.id}"
        caption = (f"🚨 رسید جدید (کد #{req_id})\n"
                   f"👤 کاربر: {user_info} ({user_id})\n"
                   f"📦 پلن: {plan_name}\n"
                   f"⏱ زمان ارسال: {created_at}")
            
        btn_confirm = InlineKeyboardButton(text="✅ تایید و ارسال کانفیگ", callback_data=f"admin_confirm_{req_id}")
        btn_reject = InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"admin_reject_{req_id}")
        btn_admin = InlineKeyboardButton(text="⚙️ پنل مدیریت", callback_data="admin_home")
        markup = InlineKeyboardMarkup(inline_keyboard=[[btn_confirm, btn_reject], [btn_admin]])
        await message.bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=caption, reply_markup=markup)
    except Exception as e:
        print(f"Error sending receipt to admin: {e}")

# مدیریت و شارژ کیف پول
async def wallet_menu_handler(message: types.Message):
    if await check_ban(message):
        return
    user_id = message.from_user.id
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    balance = user.balance if user else 0
    session.close()

    text = (f"💳 **شارژ کیف پول Swan VPN**\n\n"
            f"💰 موجودی فعلی: {balance:,} تومان\n\n"
            f"لطفاً مبلغ مورد نظر خود را انتخاب کنید:")

    buttons = [
        [InlineKeyboardButton(text="200,000 تومان", callback_data="charge_200000"),
         InlineKeyboardButton(text="400,000 تومان", callback_data="charge_400000")],
        [InlineKeyboardButton(text="600,000 تومان", callback_data="charge_600000"),
         InlineKeyboardButton(text="800,000 تومان", callback_data="charge_800000")],
        [InlineKeyboardButton(text="1,000,000 تومان", callback_data="charge_1000000"),
         InlineKeyboardButton(text="1,500,000 تومان", callback_data="charge_1500000")],
        [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

async def select_charge_amount_handler(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    amount = int(call.data.replace("charge_", ""))
    await state.update_data(charge_amount=amount)
    
    text = (f"💳 **درخواست شارژ کیف پول**\n"
            f"💰 مبلغ انتخاب شده: {amount:,} تومان\n\n"
            f"لطفاً مبلغ را به شماره کارت زیر واریز نمایید:\n"
            f"💳 `{CARD_NUMBER}`\n"
            f"به نام: {CARD_HOLDER}\n\n"
            f"پس از واریز، روی دکمه زیر کلیک کرده و رسید خود را ارسال کنید.")
            
    btn_send_receipt = InlineKeyboardButton(text="📤 ارسال رسید واریز", callback_data="send_charge_receipt")
    btn_back = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_send_receipt], [btn_back]])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

async def prompt_charge_receipt_handler(call: types.CallbackQuery, state: FSMContext):
    if await check_ban(call.message):
        return
    await state.set_state(PaymentState.waiting_for_charge_receipt)
    await call.message.edit_text("لطفاً اسکرین‌شات یا عکس رسید واریزی خود را در چت ارسال کنید:")

async def process_charge_receipt_handler(message: types.Message, state: FSMContext):
    if await check_ban(message):
        return
    data = await state.get_data()
    amount = data.get("charge_amount", 0)
    created_at = get_current_jalali()
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id
    
    await state.clear()
    await message.answer("🙏 رسید شما دریافت شد و در انتظار بررسی و تایید ادمین است. از صبر شما سپاسگزاریم.")
    
    try:
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"آیدی: {message.from_user.id}"
        caption = (f"🚨 **درخواست جدید شارژ کیف پول**\n"
                   f"👤 کاربر: {user_info} ({user_id})\n"
                   f"💰 مبلغ: {amount:,} تومان\n"
                   f"⏱ زمان ارسال: {created_at}")
                   
        btn_confirm = InlineKeyboardButton(text="✅ تایید و شارژ موجودی", callback_data=f"confirm_charge_{user_id}_{amount}")
        btn_reject = InlineKeyboardButton(text="❌ رد واریز", callback_data=f"reject_charge_{user_id}")
        btn_admin = InlineKeyboardButton(text="⚙️ پنل مدیریت", callback_data="admin_home")
        markup = InlineKeyboardMarkup(inline_keyboard=[[btn_confirm, btn_reject], [btn_admin]])
        
        await message.bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=caption, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error forwarding charge receipt to admin: {e}")

async def confirm_charge_action(call: types.CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[2])
    amount = int(parts[3])
    
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, balance=amount, is_banned=False)
        session.add(user)
    else:
        user.balance += amount
    session.commit()
    session.close()
    
    admin_markup = get_admin_main_keyboard()
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ وضعیت: واریز تایید شد و حساب کاربر شارژ گردید.", reply_markup=admin_markup)
    try:
        await call.bot.send_message(chat_id=user_id, text=f"🎉 تبریک!\n\nمبلغ {amount:,} تومان با موفقیت به موجودی کیف پول شما اضافه شد.")
    except Exception as e:
        print(f"Error notifying user about wallet top-up: {e}")

async def reject_charge_action(call: types.CallbackQuery):
    admin_markup = get_admin_main_keyboard()
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ واریز تایید نشد و رد شد.", reply_markup=admin_markup)

# مشاهده و مدیریت سرویس‌های فعال کاربر
async def my_services_handler(message: types.Message):
    if await check_ban(message):
        return
    user_id = message.from_user.id
    session = SessionLocal()
    configs = session.query(UserConfig).filter(UserConfig.user_id == user_id).all()
    session.close()
    
    if not configs:
        await message.answer("❌ شما در حال حاضر سرویس فعالی ندارید.")
        return
        
    keyword_buttons = [InlineKeyboardButton(text=f"🌐 {c.config_name}", callback_data=f"view_cfg_{c.id}") for c in configs]
    compact_keyboard = [keyword_buttons[i:i+2] for i in range(0, len(keyword_buttons), 2)]
    compact_keyboard.append([InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")])
    markup = InlineKeyboardMarkup(inline_keyboard=compact_keyboard)
    await message.answer("📦 **سرویس‌های فعال شما (برای مشاهده جزئیات انتخاب کنید):**", reply_markup=markup, parse_mode="Markdown")

async def view_config_detail_handler(call: types.CallbackQuery):
    if await check_ban(call.message):
        return
    cfg_id = int(call.data.split("_")[2])
    session = SessionLocal()
    config = session.query(UserConfig).filter(UserConfig.id == cfg_id).first()
    session.close()
    
    if not config:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
        
    text = f"📋 **جزئیات سرویس {config.config_name}:**\n\n`{config.config_details}`"
    keyboard = [
        [InlineKeyboardButton(text="⬅️ بازگشت به لیست سرویس‌ها", callback_data="my_services_callback")],
        [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

async def my_services_callback_handler(call: types.CallbackQuery):
    if await check_ban(call.message):
        return
    user_id = call.from_user.id
    session = SessionLocal()
    configs = session.query(UserConfig).filter(UserConfig.user_id == user_id).all()
    session.close()
    
    if not configs:
        await call.message.edit_text("❌ سرویس فعالی ندارید.")
        return
        
    keyword_buttons = [InlineKeyboardButton(text=f"🌐 {c.config_name}", callback_data=f"view_cfg_{c.id}") for c in configs]
    compact_keyboard = [keyword_buttons[i:i+2] for i in range(0, len(keyword_buttons), 2)]
    compact_keyboard.append([InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")])
    markup = InlineKeyboardMarkup(inline_keyboard=compact_keyboard)
    await message.answer("📦 **سرویس‌های فعال شما (برای مشاهده جزئیات انتخاب کنید):**", reply_markup=markup, parse_mode="Markdown")
# مدیریت درخواست‌های ادمین
async def admin_unanswered_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    session = SessionLocal()
    reqs = session.query(Request).filter(Request.status == 'unanswered').all()
    session.close()
    
    if not reqs:
        await call.answer("درخواست پاسخ‌داده‌نشده‌ای وجود ندارد.", show_alert=True)
        return
        
    text = "🔴 **درخواست‌های در انتظار پاسخ:**\n\n"
    keyboard = []
    for r in reqs:
        text += f"🆔 کد درخواست: #{r.id} | کاربر: {r.user_id}\n📦 پلن: {r.plan_name} | تاریخ: {r.created_at}\n-----------------------------------\n"
        keyboard.append([InlineKeyboardButton(text=f"💬 بررسی جزئیات درخواست #{r.id}", callback_data=f"admin_detail_{r.id}")])
    
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    try:
        await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await call.answer("محتوا تغییری نکرده است.", show_alert=False)
        else:
            raise e

async def admin_answered_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    session = SessionLocal()
    reqs = session.query(Request).filter(Request.status != 'unanswered').order_by(Request.id.desc()).limit(10).all()
    session.close()
    
    if not reqs:
        await call.answer("درخواست پاسخ‌داده‌شده‌ای یافت نشد.", show_alert=True)
        return
        
    text = "🟢 **آخرین درخواست‌های بررسی‌شده:**\n\n"
    for r in reqs:
        text += f"🆔 کد: #{r.id} | کاربر: {r.user_id}\n📦 پلن: {r.plan_name}\n⏱ ثبت: {r.created_at}\n✅ پاسخ/وضعیت: {r.answered_at}\n-----------------------------------\n"

    keyword_buttons = [InlineKeyboardButton(text=f"💬 #{r.id}", callback_data=f"admin_detail_{r.id}") for r in reqs]
    compact_keyboard = [keyword_buttons[i:i+3] for i in range(0, len(keyword_buttons), 3)]
    compact_keyboard.append([InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=compact_keyboard)
    
    try:
        await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await call.answer("محتوا تغییری نکرده است.", show_alert=False)
        else:
            raise e

async def admin_detail_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    req_id = int(call.data.split("_")[2])
    
    session = SessionLocal()
    r = session.query(Request).filter(Request.id == req_id).first()
    session.close()
    
    if not r:
        await call.answer("درخواست یافت نشد.", show_alert=True)
        return
        
    status_text = "پاسخ داده شده 🟢" if r.status == "answered" else ("رد شده ❌" if r.status == "rejected" else "در انتظار بررسی 🔴")
    
    text = (f"📋 **جزئیات کامل درخواست #{req_id}**\n\n"
            f"👤 آیدی کاربر: `{r.user_id}`\n"
            f"📦 نوع و پلن: {r.req_type.upper()} - {r.plan_name}\n"
            f"📌 وضعیت: {status_text}\n"
            f"⏱ زمان ثبت: {r.created_at}\n")
    if r.answered_at:
        text += f"✅ وضعیت/پاسخ: {r.answered_at}\n"
        
    btn_back_list = InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="admin_unanswered" if r.status == "unanswered" else "admin_answered")
    btn_home = InlineKeyboardButton(text="🏠 پنل اصلی مدیریت", callback_data="admin_home")
    keyboard = [[btn_back_list], [btn_home]]
    
    if r.status == "unanswered":
        btn_confirm = InlineKeyboardButton(text="✅ تایید و ارسال کانفیگ", callback_data=f"admin_confirm_{req_id}")
        btn_reject = InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"admin_reject_{req_id}")
        keyboard.insert(0, [btn_confirm, btn_reject])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    try:
        if r.receipt_file_id and r.receipt_file_id != "None":
            try:
                await call.message.delete()
            except:
                pass
            await call.bot.send_photo(chat_id=call.message.chat.id, photo=r.receipt_file_id, caption=text, reply_markup=markup, parse_mode="Markdown")
        else:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error showing request details: {e}")

async def admin_confirm_action(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    req_id = int(call.data.split("_")[2])
    
    session = SessionLocal()
    r = session.query(Request).filter(Request.id == req_id).first()
    if not r:
        session.close()
        await call.answer("درخواست یافت نشد.", show_alert=True)
        return
        
    now_jalali = get_current_jalali()
    r.status = 'answered'
    r.answered_at = now_jalali
    session.commit()
    session.close()
    
    await state.update_data(target_user_id=r.user_id, plan_name=r.plan_name, req_id=req_id)
    await state.set_state(PaymentState.waiting_for_admin_config)
    
    admin_markup = get_admin_main_keyboard()
    try:
        await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ وضعیت: درخواست تایید شد. لطفاً کانفیگ را ارسال کنید.", reply_markup=admin_markup)
    except:
        await call.message.answer("درخواست تایید شد. لطفاً متن کانفیگ یا ساب‌لینک را برای ارسال به کاربر وارد کنید:")

async def admin_reject_action(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    req_id = int(call.data.split("_")[2])
    now_jalali = get_current_jalali()
    
    session = SessionLocal()
    r = session.query(Request).filter(Request.id == req_id).first()
    if r:
        r.status = 'rejected'
        r.answered_at = now_jalali
        session.commit()
    target_user_id = r.user_id if r else None
    session.close()
    
    admin_markup = get_admin_main_keyboard()
    try:
        await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ درخواست رد شد.", reply_markup=admin_markup)
    except:
        await call.message.answer("درخواست رد شد و از لیست ادمین حذف گردید.")
        
    if target_user_id:
        try:
            await call.bot.send_message(chat_id=target_user_id, text="⚠️ متأسفانه پرداخت/درخواست شما توسط ادمین تایید نشد.")
        except:
            pass

async def process_admin_config(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    plan_name = data.get("plan_name")
    
    start_date_gregorian = datetime.now()
    end_date_gregorian = start_date_gregorian + timedelta(days=30)
    
    start_jalali = get_jalali_date(start_date_gregorian)
    end_jalali = get_jalali_date(end_date_gregorian)
    
    session = SessionLocal()
    new_config = UserConfig(
        user_id=target_user_id,
        config_name=plan_name,
        config_details=message.text
    )
    session.add(new_config)
    session.commit()
    session.close()
    
    await state.clear()
    admin_markup = get_admin_main_keyboard()
    await message.answer(f"✅ کانفیگ با موفقیت برای کاربر {target_user_id} ارسال و ثبت شد.", reply_markup=admin_markup)
    
    try:
        notify_text = (f"🎉 **سفارش شما تایید و آماده شد!**\n\n"
                       f"📦 سرویس: {plan_name}\n"
                       f"📅 تاریخ شروع: {start_jalali}\n"
                       f"📅 تاریخ پایان: {end_jalali} (۳۰ روزه)\n\n"
                       f"📋 جزئیات/کانفیگ:\n\n`{message.text}`\n\n"
                       f"طبق ساب‌لینک خود را طبق آموزش داخل کانال وارد برنامه V2Box کنید.\n"
                       f"با تشکر از خرید شما. 🙏")
        await message.bot.send_message(chat_id=target_user_id, text=notify_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error notifying user about config delivery: {e}")
# مدیریت کاربران با صفحه‌بندی
async def admin_users_list_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    page = int(call.data.split("_")[4])
    per_page = 10
    
    session = SessionLocal()
    total_users = session.query(User).count()
    total_pages = (total_users + per_page - 1) // per_page
    users = session.query(User).offset((page - 1) * per_page).limit(per_page).all()
    session.close()
    
    text = f"👥 **لیست کاربران ربات (مجموعاً {total_users} نفر - صفحه {page}/{total_pages}):**\n\nID | موجودی | وضعیت\n"
    keyboard = []
    
    for u in users:
        status_icon = "🛑 بن شده" if u.is_banned else "🟢 فعال"
        text += f"`{u.user_id}` | {u.balance:,} | {status_icon}\n"
        keyboard.append([InlineKeyboardButton(text=f"👤 مدیریت کاربر {u.user_id}", callback_data=f"manage_user_{u.user_id}")])
        
    pagination_kb = build_pagination_keyboard(page, total_pages, "admin_users_list")
    keyboard.append(pagination_kb.inline_keyboard[0])
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error showing users list: {e}")

async def admin_user_management_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    user_id = int(call.data.split("_")[2])
    
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    balance = user.balance if user else 0
    is_banned = user.is_banned if user else False
    
    configs = session.query(UserConfig).filter(UserConfig.user_id == user_id).all()
    session.close()
    
    text = f"⚙️ **مدیریت کاربر `{user_id}`**\n\n💳 موجودی فعلی: {balance:,} تومان\n📋 وضعیت دسترسی: {'🔴 مسدود (بن)' if is_banned else '🟢 باز'}\n\n📦 **کانفیگ‌های فعال کاربر:**\n"
    cfg_keyboard = []
    for c in configs:
        text += f"🔹 {c.config_name} (ID: {c.id})\n"
        cfg_keyboard.append([InlineKeyboardButton(text=f"🗑 حذف کانفیگ #{c.id}", callback_data=f"del_cfg_user_{c.id}_{user_id}")])
    
    if not configs:
        text += "هیچ کانفیگ فعالی ندارد.\n"
        
    btn_adjust_balance = InlineKeyboardButton(text="💵 تغییر موجودی کیف پول", callback_data=f"adjust_bal_menu_{user_id}")
    btn_toggle_ban = InlineKeyboardButton(text="🔓 آزاد سازی کاربر" if is_banned else "🚫 مسدود کردن (بن) کاربر", callback_data=f"toggle_ban_{user_id}_{int(is_banned)}")
    btn_back = InlineKeyboardButton(text="🔙 بازگشت به لیست کاربران", callback_data="admin_users_list_page_1")
    
    cfg_keyboard.extend([[btn_adjust_balance], [btn_toggle_ban], [btn_back]])
    markup = InlineKeyboardMarkup(inline_keyboard=cfg_keyboard)
    
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in user management menu: {e}")

async def toggle_ban_action(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    current_ban = int(parts[3])
    new_ban = not bool(current_ban)
    
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    if user:
        user.is_banned = new_ban
        session.commit()
    session.close()
    
    await call.answer("وضعیت کاربر تغییر یافت.", show_alert=True)
    call.data = f"manage_user_{user_id}"
    await admin_user_management_handler(call)

async def delete_config_user_action(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    cfg_id = int(parts[3])
    target_user_id = int(parts[4])
    
    session = SessionLocal()
    session.query(UserConfig).filter(UserConfig.id == cfg_id).delete()
    session.commit()
    session.close()
    
    await call.answer("کانفیگ کاربر حذف شد.", show_alert=True)
    try:
        await call.bot.send_message(chat_id=target_user_id, text="⚠️ یکی از سرویس‌های شما توسط ادمین حذف شد.")
    except:
        pass
    call.data = f"manage_user_{target_user_id}"
    await admin_user_management_handler(call)

async def adjust_balance_menu_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    user_id = int(call.data.split("_")[3])
    await state.update_data(target_adjust_user=user_id)
    await state.set_state(PaymentState.adjusting_balance)
    
    text = f"💵 لطفاً مبلغ جدید موجودی را برای کاربر `{user_id}` به عدد وارد کنید (مثلا 500000):"
    btn_cancel = InlineKeyboardButton(text="انصراف", callback_data=f"manage_user_{user_id}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_cancel]])
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

async def process_balance_adjustment(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_user_id = data.get("target_adjust_user")
    if not target_user_id or not message.text.isdigit():
        await message.answer("مقدار وارد شده نامعتبر است. لطفاً فقط عدد وارد کنید.")
        return
        
    new_balance = int(message.text)
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == target_user_id).first()
    if not user:
        user = User(user_id=target_user_id, balance=new_balance, is_banned=False)
        session.add(user)
    else:
        user.balance = new_balance
    session.commit()
    session.close()
    
    await state.clear()
    admin_markup = get_admin_main_keyboard()
    await message.answer(f"✅ موجودی کاربر `{target_user_id}` با موفقیت به {new_balance:,} تغییر یافت.", reply_markup=admin_markup, parse_mode="Markdown")

# آمار و ارقام فروش
async def admin_sales_stats_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    
    session = SessionLocal()
    config_count = session.query(UserConfig).count()
    total_users = session.query(User).count()
    answered_requests = session.query(Request.plan_name).filter(Request.status == 'answered').all()
    
    services = session.query(Service).all()
    plan_prices = {s.name: s.price for s in services}
        
    total_revenue = sum(plan_prices.get(p[0], 0) for p in answered_requests)
    
    today_jalali = jdatetime.date.today().strftime('%Y/%m/%d')
    today_requests = session.query(Request.plan_name).filter(Request.status == 'answered', Request.answered_at.like(f"{today_jalali}%")).all()
    daily_revenue = sum(plan_prices.get(p[0], 0) for p in today_requests)
    
    current_year_month = jdatetime.date.today().strftime('%Y/%m')
    monthly_requests = session.query(Request.plan_name).filter(Request.status == 'answered', Request.answered_at.like(f"{current_year_month}%")).all()
    monthly_revenue = sum(plan_prices.get(p[0], 0) for p in monthly_requests)
    
    unanswered_count = session.query(Request).filter(Request.status == 'unanswered').count()
    processed_count = session.query(Request).filter(Request.status != 'unanswered').count()
    session.close()
    
    text = (f"📊 **آمار جامع و وضعیت درخواست‌ها:**\n\n"
            f"👥 کل کاربران عضو شده: {total_users}\n"
            f"📦 کل سرویس‌های فعال: {config_count}\n"
            f"💰 درآمد کل Swan VPN: {total_revenue:,} تومان\n\n"
            f"📅 **آمار ماه جاری ({current_year_month}):**\n"
            f"💵 درآمد ماهانه: {monthly_revenue:,} تومان\n\n"
            f"☀️ **آمار امروز ({today_jalali}):**\n"
            f"🪙 درآمد روزانه: {daily_revenue:,} تومان\n\n"
            f"📝 **وضعیت درخواست‌های خرید:**\n"
            f"🔴 در انتظار پاسخ: {unanswered_count}\n"
            f"🟢 پاسخ داده شده/بررسی شده: {processed_count}")
            
    btn_back = InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_back]])
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await call.answer("محتوا تغییری نکرده است.", show_alert=False)
        else:
            raise e
# ارسال پیام همگانی توسط ادمین
async def admin_broadcast_start_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(PaymentState.broadcasting)
    text = "📢 لطفاً پیام، متن یا رسانه مورد نظر خود را برای ارسال همگانی به تمام کاربران ربات بفرستید:"
    btn_cancel = InlineKeyboardButton(text="انصراف", callback_data="admin_home")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_cancel]])
    await call.message.edit_text(text, reply_markup=markup)

async def process_broadcast_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    
    session = SessionLocal()
    users = session.query(User.user_id).all()
    session.close()
    
    sent_count = 0
    blocked_count = 0
    
    admin_markup = get_admin_main_keyboard()
    await message.answer("⏳ عملیات ارسال پیام همگانی آغاز شد... لطفاً منتظر بمانید.")

    for u in users:
        u_id = u[0]
        try:
            if message.text:
                await message.bot.send_message(chat_id=u_id, text=message.text)
            elif message.photo:
                await message.bot.send_photo(chat_id=u_id, photo=message.photo[-1].file_id, caption=message.caption or "")
            elif message.video:
                await message.bot.send_video(chat_id=u_id, video=message.video.file_id, caption=message.caption or "")
            sent_count += 1
        except TelegramForbiddenError:
            blocked_count += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
        
    await message.answer(f"✅ پیام همگانی با موفقیت ارسال شد!\n\n📨 ارسال‌شده به: {sent_count} کاربر\n🚫 مسدود شده توسط کاربر: {blocked_count}", reply_markup=admin_markup)

# قابلیت ارسال پیام مستقیم ادمین به یک کاربر خاص
async def direct_message_prompt_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    target_user_id = int(call.data.split("_")[2])
    await state.update_data(dm_target_user=target_user_id)
    await state.set_state(PaymentState.direct_messaging)
    
    text = f"✉️ لطفاً پیام خود را برای ارسال مستقیم به کاربر `{target_user_id}` وارد کنید:"
    btn_cancel = InlineKeyboardButton(text="انصراف", callback_data=f"manage_user_{target_user_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_cancel]])
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

async def process_direct_message_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_user_id = data.get("dm_target_user")
    await state.clear()
    
    if not target_user_id:
        await message.answer("خطا در شناسایی کاربر هدف.")
        return

    try:
        if message.text:
            await message.bot.send_message(chat_id=target_user_id, text=f"📩 **پیام مستقیم از طرف مدیریت:**\n\n{message.text}", parse_mode="Markdown")
        elif message.photo:
            await message.bot.send_photo(chat_id=target_user_id, photo=message.photo[-1].file_id, caption=message.caption, parse_mode="Markdown")
        elif message.video:
            await message.bot.send_video(chat_id=target_user_id, video=message.video.file_id, caption=message.caption, parse_mode="Markdown")
        await message.answer(f"✅ پیام با موفقیت برای کاربر {target_user_id} ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال پیام به کاربر: {e}")

# منوهای مدیریت داینامیک سرویس‌ها (افزودن/ویرایش/حذف)
async def dynamic_services_menu_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    
    session = SessionLocal()
    categories = session.query(Service.category).distinct().all()
    session.close()
    
    keyboard = []
    for cat in categories:
        cat_name = cat[0]
        keyboard.append([InlineKeyboardButton(text=f"📂 مدیریت دسته‌بندی {cat_name.upper()}", callback_data=f"manage_cat_{cat_name}")])
    
    keyboard.append([InlineKeyboardButton(text="➕ افزودن سرویس جدید", callback_data="add_service_prompt")])
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await call.message.edit_text("⚙️ **مدیریت داینامیک سرویس‌ها و قیمت‌ها:**\n\nیکی از بخش‌های زیر را انتخاب کنید:", reply_markup=markup, parse_mode="Markdown")

async def manage_category_services_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    category = call.data.split("_")[2]
    
    session = SessionLocal()
    services = session.query(Service).filter(Service.category == category).all()
    session.close()
    
    keyboard = []
    text = f"📋 **سرویس‌های موجود در دسته‌بندی {category.upper()}:**\n\n"
    for s in services:
        text += f"🔹 {s.name} | قیمت: {s.price:,} تومان\n"
        keyboard.append([
            InlineKeyboardButton(text=f"✏️ ویرایش قیمت {s.name}", callback_data=f"edit_price_{s.id}"),
            InlineKeyboardButton(text="🗑 حذف", callback_data=f"delete_service_{s.id}")
        ])
        
    keyword_buttons = [InlineKeyboardButton(text="⬅️ بازگشت به مدیریت سرویس‌ها", callback_data="dynamic_services_menu")]
    keyboard.append(keyword_buttons)
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
# عملیات ویرایش و حذف سرویس‌ها
async def edit_price_prompt_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    service_id = int(call.data.split("_")[2])
    await state.update_data(editing_service_id=service_id)
    await state.set_state(PaymentState.changing_price)
    
    session = SessionLocal()
    s = session.query(Service).filter(Service.id == service_id).first()
    plan_name = s.name if s else "سرویس"
    session.close()
    
    text = f"✏️ لطفاً قیمت جدید را برای سرویس **{plan_name}** به عدد و به تومان وارد کنید:"
    btn_cancel = InlineKeyboardButton(text="انصراف", callback_data="dynamic_services_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_cancel]])
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

async def process_price_change_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    service_id = data.get("editing_service_id")
    await state.clear()
    
    if not message.text.isdigit():
        await message.answer("مقدار وارد شده نامعتبر است. لطفاً فقط عدد وارد کنید.")
        return
        
    new_price = int(message.text)
    session = SessionLocal()
    s = session.query(Service).filter(Service.id == service_id).first()
    if s:
        s.price = new_price
        session.commit()
    session.close()
    
    admin_markup = get_admin_main_keyboard()
    await message.answer(f"✅ قیمت سرویس با موفقیت به {new_price:,} تومان به‌روزرسانی شد.", reply_markup=admin_markup)

async def delete_service_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    service_id = int(call.data.split("_")[2])
    
    session = SessionLocal()
    session.query(Service).filter(Service.id == service_id).delete()
    session.commit()
    session.close()
    
    await call.answer("سرویس با موفقیت حذف شد.", show_alert=True)
    call.data = "dynamic_services_menu"
    await dynamic_services_menu_handler(call)

async def add_service_category_prompt(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(PaymentState.renaming_service)
    text = "➕ لطفاً نام و دسته‌بندی سرویس جدید را با فرمت زیر وارد کنید:\n\nدسته‌بندی (economic/vip/gaming) | نام سرویس | قیمت\n\nمثال:\nvip | 200 گیگ | 2500000"
    btn_cancel = InlineKeyboardButton(text="انصراف", callback_data="dynamic_services_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_cancel]])
    await call.message.edit_text(text, reply_markup=markup)

async def process_add_service_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    parts = message.text.split("|")
    if len(parts) != 3:
        await message.answer("فرمت وارد شده اشتباه است. لطفاً دقیقاً طبق دستورالعمل پیام قبلی وارد کنید.")
        return
        
    cat = parts[0].strip().lower()
    name = parts[1].strip()
    price_str = parts[2].strip()
    
    if cat not in ['economic', 'vip', 'gaming'] or not price_str.isdigit():
        await message.answer("اطلاعات وارد شده نامعتبر است. دسته‌بندی باید یکی از موارد مجاز و قیمت باید عدد باشد.")
        return
        
    session = SessionLocal()
    new_s = Service(category=cat, name=name, price=int(price_str))
    session.add(new_s)
    session.commit()
    session.close()
    
    admin_markup = get_admin_main_keyboard()
    await message.answer("🎉 سرویس جدید با موفقیت به دیتابیس اضافه شد و در منوی خرید در دسترس قرار گرفت.", reply_markup=admin_markup)

# راه‌اندازی سرور وب برای پلتفرم‌های ابری مثل Render
async def health_check(request):
    return web.Response(text="Bot is running", status=200)

async def run_web_server(app, port):
    runner = web.AppRunner(app)
    try:
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        await asyncio.Future()
    finally:
        await runner.cleanup()

# ثبت و مدیریت وقایع ربات
async def log_event(event_type, details):
    print(f"[{get_current_jalali()}] {event_type}: {details}")

# توابع هندلر برای مدیریت درخواست‌های نامعتبر
async def unknown_command_handler(update: types.Update):
    if update.message:
        await update.message.answer("دستور نامعتبر است. لطفاً از منوی اصلی استفاده کنید.")

# تنظیمات واکنش به پیام‌های متنی بدون هندلر مشخص
async def unknown_message_handler(message: types.Message):
    await message.answer("Swan VPN Swan VPN در خدمت شماست. لطفاً از دکمه‌های زیر استفاده کنید.")

# توابع کمکی برای تمیز کردن متون
def sanitize_text(text):
    if not text:
        return ""
    return text.strip().replace("`", "")

# سیستم بررسی دوره‌ای و پاکسازی کش کانفیگ‌ها
async def periodic_cleanup_task():
    while True:
        try:
            session = SessionLocal()
            # می‌توان تسک‌های پاکسازی دوره‌ای را اینجا اضافه کرد
            session.close()
        except Exception as e:
            await log_event("Cleanup Error", str(e))
        await asyncio.sleep(3600)  # اجرا هر یک ساعت یکبار

# هندلر مدیریت خطاهای سراسری ربات
async def error_logger_middleware(handler, event, data):
    try:
        return await handler(event, data)
    except Exception as e:
        await log_event("Global Error", f"Exception occurred: {str(e)}")
        raise e
async def update_bot_commands(bot: Bot):
    user_commands = [
        BotCommand(command="start", description="شروع به کار با ربات")
    ]
    admin_commands = [
        BotCommand(command="start", description="شروع به کار با ربات"),
        BotCommand(command="admin", description="پنل مدیریت")
    ]
    await bot.set_my_commands(user_commands)
    try:
        await bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(chat_id=ADMIN_ID))
    except Exception as e:
        logging.error(f"Failed to set admin commands: {e}")

async def account_handler(message: types.Message):
    if await check_ban(message):
        return
    user_id = message.from_user.id
    session = SessionLocal()
    user = session.query(User).filter(User.user_id == user_id).first()
    configs = session.query(UserConfig).filter(UserConfig.user_id == user_id).all()
    session.close()
    
    balance = user.balance if user else 0
    config_count = len(configs)
    
    text = (f"👤 **حساب کاربری شما:**\n\n"
            f"🆔 آیدی: `{user_id}`\n"
            f"💰 موجودی کیف پول: {balance:,} تومان\n"
            f"📦 تعداد سرویس‌های فعال: {config_count}")
            
    btn_back = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_back]])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

async def support_handler(message: types.Message):
    if await check_ban(message):
        return
    text = (f"🎧 **پشتیبانی Swan VPN**\n\n"
            f"در صورت بروز هرگونه مشکل یا سوال، لطفاً به آیدی زیر پیام دهید:\n\n"
            f"🆔 پشتیبانی: @Swanvpnnn"
            f"با ما در ارتباط باشید. 🙏")
    btn_back = InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn_back]])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

# ثبت تمام هندلرها و راه‌اندازی ربات
async def main():
    init_services_db()
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    await update_bot_commands(bot)
    
    # ثبت هندلرهای پیام متنی
    dp.message.register(show_main_menu, Command(commands=["start"]))
    dp.message.register(admin_panel_cmd, Command(commands=["admin"]))
    dp.message.register(message_buy_handler, F.text == "🛒 خرید سرویس")
    dp.message.register(my_services_handler, F.text == "📦 سرویس‌های من")
    dp.message.register(tariffs_handler, F.text == "📈 تعرفه سرویس‌ها")
    dp.message.register(wallet_menu_handler, F.text == "💳 شارژ کیف پول")
    dp.message.register(account_handler, F.text == "👤 حساب کاربری")
    dp.message.register(support_handler, F.text == "🎧 پشتیبانی")
 
async def admin_panel_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    markup = get_admin_main_keyboard()
    await message.answer("به پنل مدیریت خوش آمدید:", reply_markup=markup)
   
    # ثبت هندلرهای دکمه‌های شیشه‌ای
    dp.callback_query.register(main_menu_handler_call, F.data == "main_menu")
    dp.callback_query.register(main_buy_handler, F.data == "main_buy")
    dp.callback_query.register(category_handler, F.data.startswith("cat_"))
    dp.callback_query.register(buy_plan_handler, F.data.startswith("buy_"))
    dp.callback_query.register(confirm_payment_handler, F.data == "confirm_payment")
    dp.callback_query.register(pay_with_wallet_handler, F.data == "pay_with_wallet")
    dp.message.register(receipt_handler, PaymentState.waiting_for_receipt, F.photo)
    
    dp.callback_query.register(wallet_menu_handler, F.data == "wallet_menu")
    dp.callback_query.register(select_charge_amount_handler, F.data.startswith("charge_"))
    dp.callback_query.register(prompt_charge_receipt_handler, F.data == "send_charge_receipt")
    dp.message.register(process_charge_receipt_handler, PaymentState.waiting_for_charge_receipt, F.photo)
    dp.callback_query.register(confirm_charge_action, F.data.startswith("confirm_charge_"))
    dp.callback_query.register(reject_charge_action, F.data.startswith("reject_charge_"))
    
    dp.callback_query.register(view_config_detail_handler, F.data.startswith("view_cfg_"))
    dp.callback_query.register(my_services_callback_handler, F.data == "my_services_callback")
    dp.callback_query.register(transaction_history_handler, F.data == "tx_history")
    dp.callback_query.register(back_to_account_handler, F.data == "back_to_account")
    
    # هندلرهای پنل مدیریت و عملیات ادمین
    dp.callback_query.register(admin_home_callback, F.data == "admin_home")
    dp.callback_query.register(admin_unanswered_handler, F.data == "admin_unanswered")
    dp.callback_query.register(admin_answered_handler, F.data == "admin_answered")
    dp.callback_query.register(admin_detail_handler, F.data.startswith("admin_detail_"))
    dp.callback_query.register(admin_confirm_action, F.data.startswith("admin_confirm_"))
    dp.callback_query.register(admin_reject_action, F.data.startswith("admin_reject_"))
    dp.message.register(process_admin_config, PaymentState.waiting_for_admin_config)
    
    dp.callback_query.register(admin_users_list_handler, F.data.startswith("admin_users_list_page_"))
    dp.callback_query.register(admin_user_management_handler, F.data.startswith("manage_user_"))
    dp.callback_query.register(toggle_ban_action, F.data.startswith("toggle_ban_"))
    dp.callback_query.register(delete_config_user_action, F.data.startswith("del_cfg_user_"))
    dp.callback_query.register(adjust_balance_menu_handler, F.data.startswith("adjust_bal_menu_"))
    dp.message.register(process_balance_adjustment, PaymentState.adjusting_balance)
    
    dp.callback_query.register(admin_sales_stats_handler, F.data == "admin_sales_stats")
    dp.callback_query.register(admin_broadcast_start_handler, F.data == "admin_broadcast_start")
    dp.message.register(process_broadcast_handler, PaymentState.broadcasting)
    
    dp.callback_query.register(direct_message_prompt_handler, F.data.startswith("dm_user_"))
    dp.message.register(process_direct_message_handler, PaymentState.direct_messaging)
    
    dp.callback_query.register(dynamic_services_menu_handler, F.data == "dynamic_services_menu")
    dp.callback_query.register(manage_category_services_handler, F.data.startswith("manage_cat_"))
    dp.callback_query.register(edit_price_prompt_handler, F.data.startswith("edit_price_"))
    dp.message.register(process_price_change_handler, PaymentState.changing_price)
    dp.callback_query.register(delete_service_handler, F.data.startswith("delete_service_"))
    dp.callback_query.register(add_service_category_prompt, F.data == "add_service_prompt")
    dp.message.register(process_add_service_handler, PaymentState.renaming_service)
    
    # شروع تسک‌های پس‌زمینه و سرور
    app = web.Application()
    app.router.add_get('/', health_check)
    port = int(os.environ.get("PORT", 8080))
    await run_web_server(app, port)
    
    asyncio.create_task(periodic_cleanup_task())
    
    print(f"✅ Bot is running and web server started on port {port}...")
    try:
        polling_task = asyncio.create_task(dp.start_polling(bot))
        await asyncio.Future()
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
