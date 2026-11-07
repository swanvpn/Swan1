import asyncio
import html
import logging
import os
from datetime import datetime, timedelta, timezone

import jdatetime
from aiohttp import web

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Integer,
    String,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReactionTypeEmoji,
    ReplyKeyboardMarkup,
)

# ---------------------------------------------------------------------------
# تنظیمات اولیه (همه با متغیر محیطی قابل تغییرند)
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "98695770"))

# مقادیر پیش‌فرض؛ ادمین می‌تواند از داخل ربات آن‌ها را تغییر دهد
DEFAULT_CARD_NUMBER = os.environ.get("CARD_NUMBER", "6219861493813108")
DEFAULT_CARD_HOLDER = os.environ.get("CARD_HOLDER", "باقرزاده")
DEFAULT_SUPPORT = os.environ.get("SUPPORT_INFO", "@Swanvpnnn")

database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if database_url:
    engine = create_engine(database_url, pool_pre_ping=True)
else:
    engine = create_engine("sqlite:///bot_data.db")

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)
dp = Dispatcher(storage=MemoryStorage())

esc = html.escape

# متن دکمه‌های منوی کاربر
BTN_BUY = "🛒 خرید سرویس"
BTN_MY = "📦 سرویس‌های من"
BTN_TARIFFS = "📈 تعرفه سرویس‌ها"
BTN_WALLET = "💳 شارژ کیف پول"
BTN_ACCOUNT = "👤 حساب کاربری"
BTN_SUPPORT = "🎧 پشتیبانی"

CATEGORY_LABELS = {
    "economic": "اقتصادی",
    "vip": "VIP",
    "gaming": "گیمینگ",
}


# ---------------------------------------------------------------------------
# مدل‌های دیتابیس
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    # آیدی تلگرام می‌تواند از ۲ میلیارد بیشتر باشد، پس BigInteger
    user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    balance = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    is_new_user = Column(Boolean, default=True)
    purchase_count_current_month = Column(Integer, default=0)
    last_purchase_month = Column(String, default="None")
    has_monthly_discount = Column(Boolean, default=False)


class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String)
    name = Column(String)
    price = Column(Integer)


class UserConfig(Base):
    __tablename__ = "user_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger)
    config_name = Column(String)
    config_details = Column(String)


class Request(Base):
    __tablename__ = "requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger)
    req_type = Column(String)
    plan_name = Column(String)
    status = Column(String, default="unanswered")
    created_at = Column(String)
    answered_at = Column(String)
    receipt_file_id = Column(String)
    price = Column(Integer, default=0)
    paid_wallet = Column(Boolean, default=False)


class BotSetting(Base):
    __tablename__ = "bot_settings"
    id = Column(Integer, primary_key=True, autoincrement=False)
    discount_percent = Column(Integer, default=0)
    card_number = Column(String)
    card_holder = Column(String)
    support_info = Column(String)


DEFAULT_PLANS = [
    ("economic", "100 گیگ - ۲ کاربر", 298000),
    ("economic", "100 گیگ - نامحدود", 398000),
    ("vip", "10 گیگ", 190000),
    ("vip", "20 گیگ", 320000),
    ("vip", "30 گیگ", 490000),
    ("vip", "50 گیگ", 790000),
    ("vip", "100 گیگ", 1330000),
    ("gaming", "10 گیگ", 220000),
    ("gaming", "20 گیگ", 360000),
    ("gaming", "30 گیگ", 530000),
    ("gaming", "50 گیگ", 850000),
]


def _migrate_columns():
    """ستون‌های جدید را به جدول‌های قدیمی اضافه می‌کند (SQLite و PostgreSQL)."""
    wanted = {
        "users": {
            "is_new_user": "BOOLEAN DEFAULT TRUE",
            "purchase_count_current_month": "INTEGER DEFAULT 0",
            "last_purchase_month": "VARCHAR",
            "has_monthly_discount": "BOOLEAN DEFAULT FALSE",
        },
        "requests": {
            "receipt_file_id": "VARCHAR",
            "price": "INTEGER DEFAULT 0",
            "paid_wallet": "BOOLEAN DEFAULT FALSE",
        },
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            existing = {c["name"].lower() for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    # در PostgreSQL ستون‌های آیدی کاربر باید BigInteger باشند
    if engine.dialect.name == "postgresql":
        for table in ("users", "requests", "user_configs"):
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(f"ALTER TABLE {table} ALTER COLUMN user_id TYPE BIGINT")
                    )
            except Exception as e:  # noqa: BLE001
                logging.warning("BIGINT migration skipped for %s: %s", table, e)


def init_db():
    Base.metadata.create_all(engine)
    _migrate_columns()
    with SessionLocal() as s:
        if s.query(Service).count() == 0:
            s.add_all(
                [Service(category=c, name=n, price=p) for c, n, p in DEFAULT_PLANS]
            )
        if s.get(BotSetting, 1) is None:
            s.add(
                BotSetting(
                    id=1,
                    discount_percent=0,
                    card_number=DEFAULT_CARD_NUMBER,
                    card_holder=DEFAULT_CARD_HOLDER,
                    support_info=DEFAULT_SUPPORT,
                )
            )
        s.commit()


# ---------------------------------------------------------------------------
# وضعیت‌های FSM
# ---------------------------------------------------------------------------
class PaymentState(StatesGroup):
    waiting_for_receipt = State()
    replying_to_user = State()
    waiting_for_charge_receipt = State()
    broadcasting = State()
    adjusting_balance = State()
    waiting_for_admin_config = State()
    editing_card = State()
    editing_support = State()
    editing_discount = State()


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------
iran_timezone = timezone(timedelta(hours=3, minutes=30))


def now_iran():
    return datetime.now(iran_timezone)


def jalali_today():
    return jdatetime.date.fromgregorian(date=now_iran().date())


def get_current_jalali():
    shamsi_date = jalali_today().strftime("%Y/%m/%d")
    shamsi_time = now_iran().strftime("%H:%M:%S")
    return f"{shamsi_date} - {shamsi_time}"


def get_jalali_date(gregorian_date):
    return jdatetime.date.fromgregorian(date=gregorian_date).strftime("%Y/%m/%d")


def get_settings():
    with SessionLocal() as s:
        row = s.get(BotSetting, 1)
        return {
            "discount": row.discount_percent or 0,
            "card_number": row.card_number or "تنظیم نشده",
            "card_holder": row.card_holder or "",
            "support": row.support_info or "",
        }


def calculating_dynamic_price(base_price, is_new_user, has_monthly_discount):
    final_price = base_price
    if is_new_user or has_monthly_discount:
        final_price = base_price * 0.9

    discount = get_settings().get("discount", 0)
    if discount > 0:
        final_price = final_price * (1 - discount / 100)
    return int(final_price)


def get_or_create_user(session, user_id):
    user = session.get(User, user_id)
    if user is None:
        user = User(
            user_id=user_id,
            balance=0,
            is_banned=False,
            is_new_user=True,
            purchase_count_current_month=0,
            last_purchase_month="None",
            has_monthly_discount=False,
        )
        session.add(user)
        session.flush()
    return user


def is_banned(user_id):
    with SessionLocal() as s:
        user = s.get(User, user_id)
        return bool(user and user.is_banned)


def user_flags(user_id):
    """(is_new_user, has_monthly_discount) برای کاربر."""
    with SessionLocal() as s:
        user = s.get(User, user_id)
        if user is None:
            return True, False
        return bool(user.is_new_user), bool(user.has_monthly_discount)


def user_label(tg_user):
    if tg_user.username:
        return f"@{esc(tg_user.username)}"
    return f"آیدی: {tg_user.id}"


async def edit_or_send(call: types.CallbackQuery, text_, markup=None):
    try:
        await call.message.edit_text(text_, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        await call.message.answer(text_, reply_markup=markup)


async def append_status(call: types.CallbackQuery, line, markup=None):
    """یک خط وضعیت به پیام (متنی یا عکس‌دار) ادمین اضافه می‌کند."""
    if call.message.caption is not None:
        base = call.message.caption
    else:
        base = call.message.text or ""
    new_text = f"{base}\n\n{line}"
    try:
        if call.message.photo:
            await call.message.edit_caption(
                caption=new_text, reply_markup=markup, parse_mode=None
            )
        else:
            await call.message.edit_text(
                new_text, reply_markup=markup, parse_mode=None
            )
    except TelegramBadRequest as e:
        logging.warning("append_status failed: %s", e)


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def get_user_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_TARIFFS), KeyboardButton(text=BTN_WALLET)],
            [KeyboardButton(text=BTN_ACCOUNT), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def get_admin_main_keyboard():
    b = InlineKeyboardButton
    keyboard = [
        [
            b(text="🟢 پاسخ داده نشده", callback_data="admin_unanswered"),
            b(text="🔴 پاسخ داده شده", callback_data="admin_answered"),
        ],
        [b(text="👥 مدیریت کاربران", callback_data="admin_users")],
        [b(text="📊 آمار کلی فروش", callback_data="admin_sales_stats")],
        [b(text="📢 ارسال پیام همگانی", callback_data="admin_broadcast_start")],
        [
            b(text="💳 تغییر شماره کارت", callback_data="admin_edit_card"),
            b(text="📞 اطلاعات پشتیبانی", callback_data="admin_edit_support"),
        ],
        [b(text="⚙️ تنظیمات ربات", callback_data="admin_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


WELCOME_TEXT = (
    "سلام! به پنل Swan VPN خوش آمدید.\n\n"
    "✨ <b>آفر ویژه:</b> ۱۰٪ تخفیف برای اولین خرید شما!\n\n"
    "🎁 <b>آفر این ماه:</b> ۱۰٪ تخفیف برای این ماه به مناسبت عضویت در ربات Swan VPN.\n\n"
    "💎 <b>طرح وفاداری:</b> در صورت ثبت ۲ خرید در طول هر ماه، ۱۰٪ تخفیف روی "
    "تمام سرویس‌ها برای ماه آینده برایتان لحاظ خواهد شد."
)


def back_home_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")]
        ]
    )


# ---------------------------------------------------------------------------
# میدل‌ور مسدودسازی کاربران
# ---------------------------------------------------------------------------
class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and user.id != ADMIN_ID and is_banned(user.id):
            if isinstance(event, types.CallbackQuery):
                await event.answer("دسترسی شما مسدود شده است.", show_alert=True)
            return None
        return await handler(event, data)


dp.message.outer_middleware(BanMiddleware())
dp.callback_query.outer_middleware(BanMiddleware())


# ---------------------------------------------------------------------------
# بخش کاربران: منو
# ---------------------------------------------------------------------------
@dp.message(Command("start"))
async def show_main_menu(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as s:
        get_or_create_user(s, message.from_user.id)
        s.commit()
    await message.answer(WELCOME_TEXT, reply_markup=get_user_keyboard())


@dp.callback_query(F.data == "main_menu")
async def main_menu_handler_call(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await edit_or_send(call, WELCOME_TEXT)


@dp.message(F.text == BTN_TARIFFS)
async def tariffs_handler(message: types.Message, state: FSMContext):
    await state.clear()
    is_new, has_monthly = user_flags(message.from_user.id)
    with SessionLocal() as s:
        rows = [
            (r.category, r.name, r.price)
            for r in s.query(Service).order_by(Service.category, Service.id).all()
        ]

    current_cat = None
    out = (
        "📊 <b>لیست تعرفه و قیمت‌های ویژه شما:</b>\n\n"
        "💡 ۱۰٪ تخفیف خرید اول و ۱۰٪ تخفیف وفاداری (در صورت داشتن) اعمال شده است.\n"
    )
    for cat, name, price in rows:
        if cat != current_cat:
            current_cat = cat
            out += f"\n📂 <b>دسته‌بندی {esc(CATEGORY_LABELS.get(cat, cat))}:</b>\n"
        dyn = calculating_dynamic_price(price, is_new, has_monthly)
        if dyn != price:
            out += f"🔹 <s>{price:,}</s> ➡️ <b>{dyn:,}</b> تومان ({esc(name)})\n"
        else:
            out += f"🔹 {price:,} تومان ({esc(name)})\n"
    await message.answer(out, reply_markup=back_home_markup())


@dp.message(F.text == BTN_SUPPORT)
async def support_handler(message: types.Message, state: FSMContext):
    await state.clear()
    support = get_settings()["support"]
    await message.reply(
        "🎧 <b>پشتیبانی Swan VPN</b>\n\n"
        "برای ارتباط با ادمین و رفع مشکلات، به آیدی زیر پیام دهید:\n"
        f"👉 {esc(support)}"
    )


# ---------------------------------------------------------------------------
# بخش کاربران: خرید
# ---------------------------------------------------------------------------
def buy_menu_markup():
    b = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="🌱 سرویس اقتصادی", callback_data="cat_economic")],
            [b(text="💎 سرویس وی‌آی‌پی", callback_data="cat_vip")],
            [b(text="🎮 سرویس گیمینگ", callback_data="cat_gaming")],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )


@dp.message(F.text == BTN_BUY)
async def message_buy_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "لطفاً دسته‌بندی مورد نظر را انتخاب کنید:", reply_markup=buy_menu_markup()
    )


@dp.callback_query(F.data == "main_buy")
async def main_buy_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await edit_or_send(
        call, "لطفاً دسته‌بندی مورد نظر را انتخاب کنید:", buy_menu_markup()
    )


@dp.callback_query(F.data.startswith("cat_"))
async def category_handler(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.bot.set_message_reaction(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reaction=[ReactionTypeEmoji(emoji="👍")],
        )
    except Exception:  # noqa: BLE001
        pass

    category = call.data.split("_", 1)[1]
    is_new, has_monthly = user_flags(call.from_user.id)
    with SessionLocal() as s:
        services = [
            (r.id, r.name, r.price)
            for r in s.query(Service)
            .filter(Service.category == category)
            .order_by(Service.id)
            .all()
        ]

    keyboard = []
    out = f"📊 لیست پلن‌های {esc(CATEGORY_LABELS.get(category, category))}:\n\n"
    for sid, name, price in services:
        dyn = calculating_dynamic_price(price, is_new, has_monthly)
        if dyn != price:
            out += f"🔹 <s>{price:,}</s> ➡️ <b>{dyn:,}</b> تومان ({esc(name)})\n"
        else:
            out += f"🔹 {price:,} تومان ({esc(name)})\n"
        keyboard.append(
            [InlineKeyboardButton(text=f"خرید {name}", callback_data=f"buy_{sid}")]
        )
    keyboard.append(
        [InlineKeyboardButton(text="⬅️ برگشت به منوی خرید", callback_data="main_buy")]
    )
    await edit_or_send(call, out, InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data.startswith("buy_"))
async def buy_plan_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        service_id = int(call.data.split("_", 1)[1])
    except ValueError:
        return

    with SessionLocal() as s:
        svc = s.get(Service, service_id)
        if svc is None:
            await call.message.answer("خطایی در یافتن سرویس رخ داد.")
            return
        plan_label = f"{CATEGORY_LABELS.get(svc.category, svc.category)} - {svc.name}"
        base_price = svc.price

    is_new, has_monthly = user_flags(call.from_user.id)
    final_price = calculating_dynamic_price(base_price, is_new, has_monthly)

    await state.set_state(PaymentState.waiting_for_receipt)
    await state.update_data(plan_name=plan_label, plan_price=final_price)

    if final_price != base_price:
        price_display = f"<s>{base_price:,}</s> ➡️ <b>{final_price:,}</b> تومان"
    else:
        price_display = f"{base_price:,} تومان"

    st = get_settings()
    out = (
        f"🛒 سفارش شما: {esc(plan_label)}\n"
        f"💰 قیمت محاسبه شده: {price_display}\n\n"
        "شما می‌توانید از طریق کارت یا موجودی کیف پول پرداخت کنید.\n\n"
        f"💳 شماره کارت جهت واریز:\n<code>{esc(st['card_number'])}</code>\n"
        f"به نام: {esc(st['card_holder'])}\n\n"
        "پس از واریز فیش را ارسال کنید یا در صورت داشتن موجودی کافی از دکمه زیر استفاده کنید."
    )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="✅ ارسال رسید واریز", callback_data="confirm_payment")],
            [b(text="💳 پرداخت از کیف پول", callback_data="pay_with_wallet")],
            [b(text="⬅️ انصراف و بازگشت", callback_data="main_buy")],
        ]
    )
    await edit_or_send(call, out, markup)


def admin_request_markup(req_id):
    b = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                b(text="✅ تایید و ارسال کانفیگ", callback_data=f"admin_confirm_{req_id}"),
                b(text="❌ رد درخواست", callback_data=f"admin_reject_{req_id}"),
            ],
            [b(text="⚙️ پنل مدیریت", callback_data="admin_home")],
        ]
    )


@dp.callback_query(F.data == "pay_with_wallet")
async def pay_with_wallet_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    plan_name = data.get("plan_name")
    price = data.get("plan_price")
    if not plan_name or not price:
        await call.answer(
            "این سفارش منقضی شده است. لطفاً دوباره از منوی خرید شروع کنید.",
            show_alert=True,
        )
        return

    user_id = call.from_user.id
    created_at = get_current_jalali()
    with SessionLocal() as s:
        user = get_or_create_user(s, user_id)
        balance = user.balance or 0
        if balance < price:
            await call.answer(
                f"موجودی شما ({balance:,} تومان) برای پرداخت این سرویس کافی نیست.",
                show_alert=True,
            )
            return
        user.balance = balance - price
        req = Request(
            user_id=user_id,
            req_type="buy",
            plan_name=plan_name,
            status="unanswered",
            created_at=created_at,
            receipt_file_id="None",
            price=price,
            paid_wallet=True,
        )
        s.add(req)
        s.flush()
        req_id = req.id
        s.commit()

    await call.answer()
    await state.clear()
    await edit_or_send(
        call, "✅ پرداخت با موفقیت از کیف پول انجام شد. لطفاً منتظر بررسی ادمین باشید. 🙏"
    )

    try:
        caption = (
            f"🚨 درخواست جدید با کیف پول (کد #{req_id})\n"
            f"👤 کاربر: {user_label(call.from_user)} ({user_id})\n"
            f"📦 پلن: {esc(plan_name)}\n"
            f"💰 مبلغ: {price:,} تومان\n"
            f"⏱ زمان ثبت: {created_at}"
        )
        await call.bot.send_message(
            chat_id=ADMIN_ID, text=caption, reply_markup=admin_request_markup(req_id)
        )
    except Exception as e:  # noqa: BLE001
        logging.error("Error sending wallet purchase to admin: %s", e)


@dp.callback_query(F.data == "confirm_payment")
async def confirm_payment_handler(call: types.CallbackQuery):
    await call.answer()
    await edit_or_send(
        call, "لطفاً اسکرین‌شات یا عکس رسید واریزی خود را در چت بفرستید تا بررسی شود."
    )


@dp.message(PaymentState.waiting_for_receipt, F.photo)
async def receipt_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    plan_name = data.get("plan_name")
    price = data.get("plan_price", 0)
    if not plan_name:
        await state.clear()
        await message.answer("این سفارش منقضی شده است. لطفاً دوباره از منوی خرید شروع کنید.")
        return

    created_at = get_current_jalali()
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id

    with SessionLocal() as s:
        get_or_create_user(s, user_id)
        req = Request(
            user_id=user_id,
            req_type="buy",
            plan_name=plan_name,
            status="unanswered",
            created_at=created_at,
            receipt_file_id=photo_id,
            price=price,
            paid_wallet=False,
        )
        s.add(req)
        s.flush()
        req_id = req.id
        s.commit()

    await state.clear()
    await message.answer(
        f"رسید شما در تاریخ {created_at} دریافت شد و به زودی بررسی می‌شود. "
        "با تشکر از خرید شما! 🙏"
    )

    try:
        caption = (
            f"🚨 رسید جدید (کد #{req_id})\n"
            f"👤 کاربر: {user_label(message.from_user)} ({user_id})\n"
            f"📦 پلن: {esc(plan_name)}\n"
            f"💰 مبلغ: {price:,} تومان\n"
            f"⏱ زمان ارسال: {created_at}"
        )
        await message.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=caption,
            reply_markup=admin_request_markup(req_id),
        )
    except Exception as e:  # noqa: BLE001
        logging.error("Error sending receipt to admin: %s", e)


@dp.message(PaymentState.waiting_for_receipt)
@dp.message(PaymentState.waiting_for_charge_receipt)
async def receipt_not_photo(message: types.Message):
    await message.answer("لطفاً رسید را به صورت عکس (اسکرین‌شات) ارسال کنید.")


# ---------------------------------------------------------------------------
# بخش کاربران: کیف پول
# ---------------------------------------------------------------------------
async def _render_wallet(event):
    with SessionLocal() as s:
        user = s.get(User, event.from_user.id)
        balance = (user.balance if user else 0) or 0

    out = (
        "💳 <b>شارژ کیف پول Swan VPN</b>\n\n"
        f"💰 موجودی فعلی: {balance:,} تومان\n\n"
        "لطفاً مبلغ مورد نظر خود را انتخاب کنید:"
    )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                b(text="200,000 تومان", callback_data="charge_200000"),
                b(text="400,000 تومان", callback_data="charge_400000"),
            ],
            [
                b(text="600,000 تومان", callback_data="charge_600000"),
                b(text="800,000 تومان", callback_data="charge_800000"),
            ],
            [
                b(text="1,000,000 تومان", callback_data="charge_1000000"),
                b(text="1,500,000 تومان", callback_data="charge_1500000"),
            ],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )
    if isinstance(event, types.CallbackQuery):
        await edit_or_send(event, out, markup)
    else:
        await event.answer(out, reply_markup=markup)


@dp.message(F.text == BTN_WALLET)
async def wallet_menu_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await _render_wallet(message)


@dp.callback_query(F.data == "wallet_menu")
async def wallet_menu_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await _render_wallet(call)


@dp.callback_query(F.data.startswith("charge_"))
async def select_charge_amount_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        amount = int(call.data.replace("charge_", ""))
    except ValueError:
        return
    await state.update_data(charge_amount=amount)

    st = get_settings()
    out = (
        "💳 <b>درخواست شارژ کیف پول</b>\n"
        f"💰 مبلغ انتخاب شده: {amount:,} تومان\n\n"
        "لطفاً مبلغ را به شماره کارت زیر واریز نمایید:\n"
        f"💳 <code>{esc(st['card_number'])}</code>\n"
        f"به نام: {esc(st['card_holder'])}\n\n"
        "پس از واریز، روی دکمه زیر کلیک کرده و رسید خود را ارسال کنید."
    )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="📤 ارسال رسید واریز", callback_data="send_charge_receipt")],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )
    await edit_or_send(call, out, markup)


@dp.callback_query(F.data == "send_charge_receipt")
async def prompt_charge_receipt_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    if not data.get("charge_amount"):
        await edit_or_send(call, "لطفاً ابتدا مبلغ شارژ را انتخاب کنید.", back_home_markup())
        return
    await state.set_state(PaymentState.waiting_for_charge_receipt)
    await edit_or_send(call, "لطفاً اسکرین‌شات یا عکس رسید واریزی خود را در چت ارسال کنید:")


@dp.message(PaymentState.waiting_for_charge_receipt, F.photo)
async def process_charge_receipt_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("charge_amount", 0)
    if not amount:
        await state.clear()
        await message.answer("درخواست منقضی شده است. لطفاً دوباره مبلغ شارژ را انتخاب کنید.")
        return

    created_at = get_current_jalali()
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id

    await state.clear()
    await message.answer(
        "🙏 رسید شما دریافت شد و در انتظار بررسی و تایید ادمین است. از صبر شما سپاسگزاریم."
    )

    try:
        caption = (
            "🚨 <b>درخواست جدید شارژ کیف پول</b>\n"
            f"👤 کاربر: {user_label(message.from_user)} ({user_id})\n"
            f"💰 مبلغ: {amount:,} تومان\n"
            f"⏱ زمان ارسال: {created_at}"
        )
        b = InlineKeyboardButton
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    b(
                        text="✅ تایید و شارژ موجودی",
                        callback_data=f"confirm_charge_{user_id}_{amount}",
                    ),
                    b(text="❌ رد واریز", callback_data=f"reject_charge_{user_id}"),
                ],
                [b(text="⚙️ پنل مدیریت", callback_data="admin_home")],
            ]
        )
        await message.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo_id, caption=caption, reply_markup=markup
        )
    except Exception as e:  # noqa: BLE001
        logging.error("Error forwarding charge receipt to admin: %s", e)


@dp.callback_query(F.data.startswith("confirm_charge_"), F.from_user.id == ADMIN_ID)
async def confirm_charge_action(call: types.CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[2])
    amount = int(parts[3])

    with SessionLocal() as s:
        user = get_or_create_user(s, user_id)
        user.balance = (user.balance or 0) + amount
        s.commit()

    await call.answer("شارژ انجام شد.")
    await append_status(
        call,
        "✅ وضعیت: واریز تایید شد و حساب کاربر شارژ گردید.",
        get_admin_main_keyboard(),
    )
    try:
        await call.bot.send_message(
            chat_id=user_id,
            text=f"🎉 تبریک!\n\nمبلغ {amount:,} تومان با موفقیت به موجودی کیف پول شما اضافه شد.",
        )
    except Exception as e:  # noqa: BLE001
        logging.error("Error notifying user about wallet top-up: %s", e)


@dp.callback_query(F.data.startswith("reject_charge_"), F.from_user.id == ADMIN_ID)
async def reject_charge_action(call: types.CallbackQuery):
    await call.answer("رد شد.")
    await append_status(call, "❌ وضعیت: واریز رد شد.", get_admin_main_keyboard())
    try:
        user_id = int(call.data.split("_")[2])
        await call.bot.send_message(
            chat_id=user_id, text="⚠️ متأسفانه واریز شما توسط ادمین تایید نشد."
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# بخش کاربران: سرویس‌های من و حساب کاربری
# ---------------------------------------------------------------------------
def _my_services_view(user_id):
    with SessionLocal() as s:
        configs = [
            (c.id, c.config_name)
            for c in s.query(UserConfig).filter(UserConfig.user_id == user_id).all()
        ]
    if not configs:
        return "❌ شما در حال حاضر سرویس فعالی ندارید.", None

    buttons = [
        InlineKeyboardButton(text=f"🌐 {name}", callback_data=f"view_cfg_{cfg_id}")
        for cfg_id, name in configs
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append(
        [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")]
    )
    return (
        "📦 <b>سرویس‌های فعال شما (برای مشاهده جزئیات انتخاب کنید):</b>",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(F.text == BTN_MY)
async def my_services_handler(message: types.Message, state: FSMContext):
    await state.clear()
    out, markup = _my_services_view(message.from_user.id)
    await message.answer(out, reply_markup=markup)


@dp.callback_query(F.data == "my_services_callback")
async def my_services_callback_handler(call: types.CallbackQuery):
    await call.answer()
    out, markup = _my_services_view(call.from_user.id)
    await edit_or_send(call, out, markup)


@dp.callback_query(F.data.startswith("view_cfg_"))
async def view_config_detail_handler(call: types.CallbackQuery):
    cfg_id = int(call.data.split("_")[2])
    with SessionLocal() as s:
        cfg = s.get(UserConfig, cfg_id)
        # هر کاربر فقط کانفیگ خودش را می‌بیند
        if cfg is None or cfg.user_id != call.from_user.id:
            await call.answer("سرویس یافت نشد.", show_alert=True)
            return
        name, details = cfg.config_name, cfg.config_details

    await call.answer()
    out = f"📋 <b>جزئیات سرویس {esc(name)}:</b>\n\n<code>{esc(details)}</code>"
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="⬅️ بازگشت به لیست سرویس‌ها", callback_data="my_services_callback")],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )
    await edit_or_send(call, out, markup)


def _account_view(user_id):
    with SessionLocal() as s:
        user = s.get(User, user_id)
        balance = (user.balance if user else 0) or 0
        count = (user.purchase_count_current_month if user else 0) or 0
        has_monthly = bool(user and user.has_monthly_discount)
        active_count = (
            s.query(func.count(UserConfig.id)).filter(UserConfig.user_id == user_id).scalar()
        )

    if has_monthly:
        status_text = "✅ فعال (۱۰٪ تخفیف ماه آینده)"
    else:
        status_text = f"⏳ در حال حاضر {count} خرید در این ماه (نیاز به ۲ خرید)"

    out = (
        "👤 <b>حساب کاربری</b>\n\n"
        f"🆔 آیدی عددی: <code>{user_id}</code>\n"
        f"💳 موجودی کیف پول: {balance:,} تومان\n"
        f"🟢 تعداد سرویس‌های فعال: {active_count}\n"
        f"🎁 وضعیت آفر وفاداری: {status_text}"
    )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="📜 تاریخچه تراکنش‌ها", callback_data="tx_history")],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )
    return out, markup


@dp.message(F.text == BTN_ACCOUNT)
async def account_handler(message: types.Message, state: FSMContext):
    await state.clear()
    out, markup = _account_view(message.from_user.id)
    await message.answer(out, reply_markup=markup)


@dp.callback_query(F.data == "back_to_account")
async def back_to_account_handler(call: types.CallbackQuery):
    await call.answer()
    out, markup = _account_view(call.from_user.id)
    await edit_or_send(call, out, markup)


@dp.callback_query(F.data == "tx_history")
async def transaction_history_handler(call: types.CallbackQuery):
    with SessionLocal() as s:
        reqs = [
            (r.id, r.plan_name, r.status, r.created_at)
            for r in s.query(Request)
            .filter(Request.user_id == call.from_user.id)
            .order_by(Request.id.desc())
            .limit(20)
            .all()
        ]
    if not reqs:
        await call.answer("هیچ فاکتور یا درخواستی ثبت نشده است.", show_alert=True)
        return

    await call.answer()
    out = "📜 <b>تاریخچه تراکنش‌ها و درخواست‌های شما:</b>\n\n"
    for req_id, plan, status, date in reqs:
        emoji = {"answered": "✅", "rejected": "❌"}.get(status, "⏳")
        out += (
            f"🔹 فاکتور #{req_id} | {esc(plan or '')} | وضعیت: {emoji}\n"
            f"⏱ تاریخ: {date}\n-----------------------------------\n"
        )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="⬅️ برگشت به حساب کاربری", callback_data="back_to_account")],
            [b(text="🏠 بازگشت به منوی اصلی", callback_data="main_menu")],
        ]
    )
    await edit_or_send(call, out, markup)


# ---------------------------------------------------------------------------
# پنل ادمین: ورود و صف درخواست‌ها
# ---------------------------------------------------------------------------
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚙️ <b>پنل مدیریت ادمین:</b>", reply_markup=get_admin_main_keyboard()
    )


@dp.callback_query(F.data == "admin_home", F.from_user.id == ADMIN_ID)
async def admin_home_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        await call.message.edit_text(
            "⚙️ <b>پنل مدیریت ادمین:</b>", reply_markup=get_admin_main_keyboard()
        )
    except TelegramBadRequest:
        await call.message.answer(
            "⚙️ <b>پنل مدیریت ادمین:</b>", reply_markup=get_admin_main_keyboard()
        )


@dp.callback_query(F.data == "admin_unanswered", F.from_user.id == ADMIN_ID)
async def admin_unanswered_handler(call: types.CallbackQuery):
    with SessionLocal() as s:
        reqs = [
            (r.id, r.user_id, r.plan_name, r.created_at)
            for r in s.query(Request).filter(Request.status == "unanswered").all()
        ]
    if not reqs:
        await call.answer("درخواست پاسخ‌داده‌نشده‌ای وجود ندارد.", show_alert=True)
        return

    await call.answer()
    out = "🔴 <b>درخواست‌های در انتظار پاسخ:</b>\n\n"
    keyboard = []
    for req_id, u_id, plan, date in reqs:
        out += (
            f"🆔 کد درخواست: #{req_id} | کاربر: {u_id}\n"
            f"📦 پلن: {esc(plan or '')} | تاریخ: {date}\n"
            "-----------------------------------\n"
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"💬 بررسی جزئیات درخواست #{req_id}",
                    callback_data=f"admin_detail_{req_id}",
                )
            ]
        )
    keyboard.append(
        [InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")]
    )
    await edit_or_send(call, out, InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data == "admin_answered", F.from_user.id == ADMIN_ID)
async def admin_answered_handler(call: types.CallbackQuery):
    with SessionLocal() as s:
        reqs = [
            (r.id, r.user_id, r.plan_name, r.created_at, r.answered_at)
            for r in s.query(Request)
            .filter(Request.status != "unanswered")
            .order_by(Request.id.desc())
            .limit(10)
            .all()
        ]
    if not reqs:
        await call.answer("درخواست پاسخ‌داده‌شده‌ای یافت نشد.", show_alert=True)
        return

    await call.answer()
    out = "🟢 <b>آخرین درخواست‌های بررسی‌شده:</b>\n\n"
    for req_id, u_id, plan, created, answered in reqs:
        out += (
            f"🆔 کد: #{req_id} | کاربر: {u_id}\n"
            f"📦 پلن: {esc(plan or '')}\n"
            f"⏱ ثبت: {created}\n"
            f"✅ پاسخ/وضعیت: {answered}\n"
            "-----------------------------------\n"
        )
    buttons = [
        InlineKeyboardButton(text=f"💬 #{r[0]}", callback_data=f"admin_detail_{r[0]}")
        for r in reqs
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")]
    )
    await edit_or_send(call, out, InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("admin_detail_"), F.from_user.id == ADMIN_ID)
async def admin_detail_handler(call: types.CallbackQuery):
    req_id = int(call.data.split("_")[2])
    with SessionLocal() as s:
        r = s.get(Request, req_id)
        if r is None:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        u_id, r_type, plan = r.user_id, r.req_type, r.plan_name
        status, created, answered = r.status, r.created_at, r.answered_at
        receipt_id, price = r.receipt_file_id, r.price or 0

    await call.answer()
    status_text = {
        "answered": "پاسخ داده شده 🟢",
        "rejected": "رد شده ❌",
    }.get(status, "در انتظار بررسی 🔴")

    out = (
        f"📋 <b>جزئیات کامل درخواست #{req_id}</b>\n\n"
        f"👤 آیدی کاربر: <code>{u_id}</code>\n"
        f"📦 نوع و پلن: {esc((r_type or '').upper())} - {esc(plan or '')}\n"
        f"💰 مبلغ: {price:,} تومان\n"
        f"📌 وضعیت: {status_text}\n"
        f"⏱ زمان ثبت: {created}\n"
    )
    if answered:
        out += f"✅ وضعیت/پاسخ: {answered}\n"

    b = InlineKeyboardButton
    back_cb = "admin_unanswered" if status == "unanswered" else "admin_answered"
    keyboard = [
        [b(text="⬅️ بازگشت به لیست", callback_data=back_cb)],
        [b(text="🏠 پنل اصلی مدیریت", callback_data="admin_home")],
    ]
    if status == "unanswered":
        keyboard.insert(
            0,
            [
                b(text="✅ تایید و ارسال کانفیگ", callback_data=f"admin_confirm_{req_id}"),
                b(text="❌ رد درخواست", callback_data=f"admin_reject_{req_id}"),
            ],
        )
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        if receipt_id and receipt_id != "None":
            try:
                await call.message.delete()
            except Exception:  # noqa: BLE001
                pass
            await call.bot.send_photo(
                chat_id=call.message.chat.id,
                photo=receipt_id,
                caption=out,
                reply_markup=markup,
            )
        else:
            await edit_or_send(call, out, markup)
    except Exception as e:  # noqa: BLE001
        logging.error("Error showing request details: %s", e)


@dp.callback_query(F.data.startswith("admin_confirm_"), F.from_user.id == ADMIN_ID)
async def admin_confirm_action(call: types.CallbackQuery, state: FSMContext):
    req_id = int(call.data.split("_")[2])
    with SessionLocal() as s:
        r = s.get(Request, req_id)
        if r is None:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        if r.status != "unanswered":
            await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
            return
        target_user_id, plan_name = r.user_id, r.plan_name

    await call.answer()
    await state.update_data(
        target_user_id=target_user_id, plan_name=plan_name, req_id=req_id
    )
    await state.set_state(PaymentState.waiting_for_admin_config)
    await append_status(
        call,
        "✅ درخواست تایید شد. لطفاً متن کانفیگ یا ساب‌لینک را برای ارسال به کاربر وارد کنید:",
        get_admin_main_keyboard(),
    )


@dp.callback_query(F.data.startswith("admin_reject_"), F.from_user.id == ADMIN_ID)
async def admin_reject_action(call: types.CallbackQuery):
    req_id = int(call.data.split("_")[2])
    refunded = 0
    with SessionLocal() as s:
        r = s.get(Request, req_id)
        if r is None:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        if r.status != "unanswered":
            await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
            return
        r.status = "rejected"
        r.answered_at = get_current_jalali()
        target_user = r.user_id
        # اگر با کیف پول پرداخت شده بود، مبلغ برگردانده می‌شود
        if r.paid_wallet and (r.price or 0) > 0:
            user = get_or_create_user(s, target_user)
            user.balance = (user.balance or 0) + r.price
            refunded = r.price
        s.commit()

    await call.answer("درخواست رد شد.")
    await append_status(call, "❌ وضعیت: درخواست رد شد.", get_admin_main_keyboard())

    msg = "⚠️ متأسفانه پرداخت/درخواست شما توسط ادمین تایید نشد."
    if refunded:
        msg += f"\n💰 مبلغ {refunded:,} تومان به کیف پول شما برگشت داده شد."
    try:
        await call.bot.send_message(chat_id=target_user, text=msg)
    except Exception:  # noqa: BLE001
        pass


@dp.message(PaymentState.waiting_for_admin_config, F.from_user.id == ADMIN_ID)
async def process_admin_config(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("لطفاً کانفیگ را به صورت متن ارسال کنید.")
        return

    data = await state.get_data()
    req_id = data.get("req_id")
    target_user_id = data.get("target_user_id")
    plan_name = data.get("plan_name")

    now_g = now_iran().replace(tzinfo=None)
    start_jalali = get_jalali_date(now_g)
    end_jalali = get_jalali_date(now_g + timedelta(days=30))
    current_month = jalali_today().strftime("%Y/%m")

    with SessionLocal() as s:
        r = s.get(Request, req_id) if req_id else None
        if r is not None:
            r.status = "answered"
            r.answered_at = get_current_jalali()

        s.add(
            UserConfig(
                user_id=target_user_id, config_name=plan_name, config_details=message.text
            )
        )

        user = get_or_create_user(s, target_user_id)
        prev_has_monthly = bool(user.has_monthly_discount)
        count = user.purchase_count_current_month or 0
        new_count = (count + 1) if user.last_purchase_month == current_month else 1
        user.is_new_user = False
        user.purchase_count_current_month = new_count
        user.last_purchase_month = current_month
        user.has_monthly_discount = new_count >= 2
        has_monthly_notif = user.has_monthly_discount and not prev_has_monthly
        s.commit()

    await state.clear()
    await message.answer(
        f"✅ کانفیگ با موفقیت برای کاربر {target_user_id} ارسال و ثبت شد.",
        reply_markup=get_admin_main_keyboard(),
    )

    try:
        notify = (
            "🎉 <b>سفارش شما تایید و آماده شد!</b>\n\n"
            f"📦 سرویس: {esc(plan_name or '')}\n"
            f"📅 تاریخ شروع: {start_jalali}\n"
            f"📅 تاریخ پایان: {end_jalali} (۳۰ روزه)\n\n"
            f"📋 جزئیات/کانفیگ:\n\n<code>{esc(message.text)}</code>\n\n"
        )
        if has_monthly_notif:
            notify += (
                "🔥 <b>تبریک! شما در این ماه ۲ خرید ثبت کردید و ۱۰٪ تخفیف وفاداری "
                "برای تمام سرویس‌های ماه آینده برای شما فعال شد.</b>\n\n"
            )
        notify += (
            "لطفاً ساب‌لینک خود را طبق آموزش داخل کانال وارد برنامه V2Box کنید.\n"
            "با تشکر از خرید شما. 🙏"
        )
        await message.bot.send_message(chat_id=target_user_id, text=notify)
    except Exception as e:  # noqa: BLE001
        logging.error("Error notifying user about config delivery: %s", e)


# ---------------------------------------------------------------------------
# پنل ادمین: مدیریت کاربران
# ---------------------------------------------------------------------------
USERS_PER_PAGE = 10


@dp.callback_query(F.data == "admin_users", F.from_user.id == ADMIN_ID)
@dp.callback_query(F.data.startswith("admin_users_page_"), F.from_user.id == ADMIN_ID)
async def admin_users_list_handler(call: types.CallbackQuery):
    await call.answer()
    page = 1
    if call.data.startswith("admin_users_page_"):
        page = max(1, int(call.data.split("_")[3]))
    offset = (page - 1) * USERS_PER_PAGE

    with SessionLocal() as s:
        total = s.query(func.count(User.user_id)).scalar()
        users = [
            (u.user_id, u.balance or 0, bool(u.is_banned))
            for u in s.query(User)
            .order_by(User.user_id)
            .offset(offset)
            .limit(USERS_PER_PAGE)
            .all()
        ]

    out = f"👥 <b>لیست کاربران ربات (مجموعاً {total} نفر) - صفحه {page}:</b>\n\nID | موجودی | وضعیت\n"
    keyboard = []
    for u_id, bal, banned in users:
        icon = "🛑 بن شده" if banned else "🟢 فعال"
        out += f"<code>{u_id}</code> | {bal:,} | {icon}\n"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"👤 مدیریت کاربر {u_id}", callback_data=f"manage_user_{u_id}"
                )
            ]
        )

    nav = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"admin_users_page_{page - 1}")
        )
    if offset + USERS_PER_PAGE < total:
        nav.append(
            InlineKeyboardButton(text="بعدی ➡️", callback_data=f"admin_users_page_{page + 1}")
        )
    if nav:
        keyboard.append(nav)
    keyboard.append(
        [InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")]
    )
    await edit_or_send(call, out, InlineKeyboardMarkup(inline_keyboard=keyboard))


async def _render_user_management(call: types.CallbackQuery, user_id: int):
    with SessionLocal() as s:
        user = s.get(User, user_id)
        balance = (user.balance if user else 0) or 0
        banned = bool(user and user.is_banned)
        count = (user.purchase_count_current_month if user else 0) or 0
        has_monthly = bool(user and user.has_monthly_discount)
        configs = [
            (c.id, c.config_name)
            for c in s.query(UserConfig).filter(UserConfig.user_id == user_id).all()
        ]

    status_text = "✅ فعال (۱۰٪ تخفیف)" if has_monthly else f"⏳ {count} خرید این ماه"
    out = (
        f"⚙️ <b>مدیریت کاربر <code>{user_id}</code></b>\n\n"
        f"💳 موجودی فعلی: {balance:,} تومان\n"
        f"📋 وضعیت دسترسی: {'🔴 مسدود (بن)' if banned else '🟢 باز'}\n"
        f"🎁 آفر وفاداری: {status_text}\n\n"
        "📦 <b>کانفیگ‌های فعال کاربر:</b>\n"
    )
    keyboard = []
    for cfg_id, cfg_name in configs:
        out += f"🔹 {esc(cfg_name or '')} (ID: {cfg_id})\n"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 حذف کانفیگ #{cfg_id}",
                    callback_data=f"del_cfg_user_{cfg_id}_{user_id}",
                )
            ]
        )
    if not configs:
        out += "هیچ کانفیگ فعالی ندارد.\n"

    b = InlineKeyboardButton
    keyboard.extend(
        [
            [b(text="💵 تغییر موجودی کیف پول", callback_data=f"adjust_bal_menu_{user_id}")],
            [
                b(
                    text="🔓 آزاد سازی کاربر" if banned else "🚫 مسدود کردن (بن) کاربر",
                    callback_data=f"toggle_ban_{user_id}",
                )
            ],
            [b(text="🔙 بازگشت به لیست کاربران", callback_data="admin_users")],
        ]
    )
    await edit_or_send(call, out, InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data.startswith("manage_user_"), F.from_user.id == ADMIN_ID)
async def admin_user_management_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await _render_user_management(call, int(call.data.split("_")[2]))


@dp.callback_query(F.data.startswith("toggle_ban_"), F.from_user.id == ADMIN_ID)
async def toggle_ban_action(call: types.CallbackQuery):
    user_id = int(call.data.split("_")[2])
    with SessionLocal() as s:
        user = get_or_create_user(s, user_id)
        user.is_banned = not bool(user.is_banned)
        s.commit()
    await call.answer("وضعیت کاربر تغییر یافت.", show_alert=True)
    await _render_user_management(call, user_id)


@dp.callback_query(F.data.startswith("del_cfg_user_"), F.from_user.id == ADMIN_ID)
async def delete_config_user_action(call: types.CallbackQuery):
    parts = call.data.split("_")
    cfg_id = int(parts[3])
    target_user_id = int(parts[4])
    with SessionLocal() as s:
        cfg = s.get(UserConfig, cfg_id)
        if cfg is not None:
            s.delete(cfg)
            s.commit()
    await call.answer("کانفیگ کاربر حذف شد.", show_alert=True)
    try:
        await call.bot.send_message(
            chat_id=target_user_id, text="⚠️ یکی از سرویس‌های شما توسط ادمین حذف شد."
        )
    except Exception:  # noqa: BLE001
        pass
    await _render_user_management(call, target_user_id)


@dp.callback_query(F.data.startswith("adjust_bal_menu_"), F.from_user.id == ADMIN_ID)
async def adjust_balance_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user_id = int(call.data.split("_")[3])
    await state.update_data(target_adjust_user=user_id)
    await state.set_state(PaymentState.adjusting_balance)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="انصراف", callback_data=f"manage_user_{user_id}")]
        ]
    )
    await edit_or_send(
        call,
        f"💵 لطفاً مبلغ جدید موجودی را برای کاربر <code>{user_id}</code> به عدد وارد کنید (مثلا 500000):",
        markup,
    )


@dp.message(PaymentState.adjusting_balance, F.from_user.id == ADMIN_ID)
async def process_balance_adjustment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("target_adjust_user")
    if not target_user_id or not message.text or not message.text.strip().isdigit():
        await message.answer("مقدار وارد شده نامعتبر است. لطفاً فقط عدد وارد کنید.")
        return

    new_balance = int(message.text.strip())
    with SessionLocal() as s:
        user = get_or_create_user(s, target_user_id)
        user.balance = new_balance
        s.commit()

    await state.clear()
    await message.answer(
        f"✅ موجودی کاربر <code>{target_user_id}</code> با موفقیت به {new_balance:,} تغییر یافت.",
        reply_markup=get_admin_main_keyboard(),
    )


# ---------------------------------------------------------------------------
# پنل ادمین: آمار
# ---------------------------------------------------------------------------
@dp.callback_query(F.data == "admin_sales_stats", F.from_user.id == ADMIN_ID)
async def admin_sales_stats_handler(call: types.CallbackQuery):
    await call.answer()
    today = jalali_today().strftime("%Y/%m/%d")
    month = jalali_today().strftime("%Y/%m")

    with SessionLocal() as s:
        config_count = s.query(func.count(UserConfig.id)).scalar()
        total_users = s.query(func.count(User.user_id)).scalar()

        def revenue(*extra):
            q = s.query(func.coalesce(func.sum(Request.price), 0)).filter(
                Request.status == "answered", *extra
            )
            return int(q.scalar() or 0)

        total_revenue = revenue()
        daily_revenue = revenue(Request.answered_at.like(f"{today}%"))
        monthly_revenue = revenue(Request.answered_at.like(f"{month}%"))
        unanswered = s.query(func.count(Request.id)).filter(
            Request.status == "unanswered"
        ).scalar()
        processed = s.query(func.count(Request.id)).filter(
            Request.status != "unanswered"
        ).scalar()

    out = (
        "📊 <b>آمار جامع و وضعیت درخواست‌ها:</b>\n\n"
        f"👥 کل کاربران عضو شده: {total_users}\n"
        f"📦 کل سرویس‌های فعال: {config_count}\n"
        f"💰 درآمد کل Swan VPN: {total_revenue:,} تومان\n\n"
        f"📅 <b>آمار ماه جاری ({month}):</b>\n"
        f"💵 درآمد ماهانه: {monthly_revenue:,} تومان\n\n"
        f"☀️ <b>آمار امروز ({today}):</b>\n"
        f"🪙 درآمد روزانه: {daily_revenue:,} تومان\n\n"
        "📝 <b>وضعیت درخواست‌های خرید:</b>\n"
        f"🔴 در انتظار پاسخ: {unanswered}\n"
        f"🟢 پاسخ داده شده/بررسی شده: {processed}"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")]
        ]
    )
    await edit_or_send(call, out, markup)


# ---------------------------------------------------------------------------
# پنل ادمین: پیام همگانی
# ---------------------------------------------------------------------------
@dp.callback_query(F.data == "admin_broadcast_start", F.from_user.id == ADMIN_ID)
async def admin_broadcast_start_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(PaymentState.broadcasting)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="انصراف", callback_data="admin_home")]]
    )
    await edit_or_send(
        call,
        "📢 لطفاً پیام، متن یا رسانه مورد نظر خود را برای ارسال همگانی به تمام کاربران ربات بفرستید:",
        markup,
    )


@dp.message(PaymentState.broadcasting, F.from_user.id == ADMIN_ID)
async def process_broadcast_handler(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as s:
        user_ids = [u[0] for u in s.query(User.user_id).all()]

    await message.answer("⏳ عملیات ارسال پیام همگانی آغاز شد... لطفاً منتظر بمانید.")

    sent = blocked = failed = 0
    for u_id in user_ids:
        try:
            await message.copy_to(chat_id=u_id)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(
        "✅ پیام همگانی با موفقیت ارسال شد!\n\n"
        f"📨 ارسال‌شده به: {sent} کاربر\n"
        f"🚫 مسدود شده توسط کاربر: {blocked}\n"
        f"⚠️ ناموفق: {failed}",
        reply_markup=get_admin_main_keyboard(),
    )


# ---------------------------------------------------------------------------
# پنل ادمین: تنظیمات (کارت، پشتیبانی، تخفیف)
# ---------------------------------------------------------------------------
def _cancel_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="انصراف", callback_data="admin_home")]]
    )


@dp.callback_query(F.data == "admin_edit_card", F.from_user.id == ADMIN_ID)
async def start_edit_card(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(PaymentState.editing_card)
    await edit_or_send(
        call,
        "شماره کارت جدید را بفرستید.\n"
        "(در صورت نیاز به تغییر نام صاحب کارت، آن را در خط بعد بنویسید.)",
        _cancel_markup(),
    )


@dp.message(PaymentState.editing_card, F.from_user.id == ADMIN_ID)
async def save_card(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("لطفاً متن ارسال کنید.")
        return
    lines = [ln.strip() for ln in message.text.strip().splitlines() if ln.strip()]
    card = lines[0]
    holder = lines[1] if len(lines) > 1 else None
    with SessionLocal() as s:
        row = s.get(BotSetting, 1)
        row.card_number = card
        if holder:
            row.card_holder = holder
        s.commit()
    await state.clear()
    await message.answer("✅ اطلاعات کارت ذخیره شد.", reply_markup=get_admin_main_keyboard())


@dp.callback_query(F.data == "admin_edit_support", F.from_user.id == ADMIN_ID)
async def start_edit_support(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(PaymentState.editing_support)
    await edit_or_send(call, "متن پشتیبانی جدید را بفرستید (مثلاً آیدی تلگرام):", _cancel_markup())


@dp.message(PaymentState.editing_support, F.from_user.id == ADMIN_ID)
async def save_support(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("لطفاً متن ارسال کنید.")
        return
    with SessionLocal() as s:
        s.get(BotSetting, 1).support_info = message.text.strip()
        s.commit()
    await state.clear()
    await message.answer(
        "✅ اطلاعات پشتیبانی ذخیره شد.", reply_markup=get_admin_main_keyboard()
    )


@dp.callback_query(F.data == "admin_settings", F.from_user.id == ADMIN_ID)
async def show_bot_settings(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    st = get_settings()
    out = (
        "⚙️ <b>تنظیمات فعلی:</b>\n\n"
        f"🏷 درصد تخفیف عمومی: {st['discount']}%\n"
        f"💳 شماره کارت: <code>{esc(st['card_number'])}</code>\n"
        f"👤 صاحب کارت: {esc(st['card_holder'])}\n"
        f"📞 پشتیبانی: {esc(st['support'])}"
    )
    b = InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [b(text="🏷 تغییر تخفیف عمومی", callback_data="admin_edit_discount")],
            [b(text="🔙 بازگشت به پنل ادمین", callback_data="admin_home")],
        ]
    )
    await edit_or_send(call, out, markup)


@dp.callback_query(F.data == "admin_edit_discount", F.from_user.id == ADMIN_ID)
async def start_edit_discount(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(PaymentState.editing_discount)
    await edit_or_send(
        call, "درصد تخفیف عمومی جدید را به عدد (۰ تا ۹۰) بفرستید. برای خاموش کردن، ۰ بفرستید:", _cancel_markup()
    )


@dp.message(PaymentState.editing_discount, F.from_user.id == ADMIN_ID)
async def save_discount(message: types.Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value.isdigit() or not (0 <= int(value) <= 90):
        await message.answer("مقدار نامعتبر است. یک عدد بین ۰ تا ۹۰ بفرستید.")
        return
    with SessionLocal() as s:
        s.get(BotSetting, 1).discount_percent = int(value)
        s.commit()
    await state.clear()
    await message.answer(
        f"✅ تخفیف عمومی روی {value}٪ تنظیم شد.", reply_markup=get_admin_main_keyboard()
    )


# ---------------------------------------------------------------------------
# وب‌سرور سلامت و اجرای ربات
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Bot is running", status=200)


async def update_bot_commands(bot):
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="منوی اصلی"),
            BotCommand(command="admin", description="پنل ادمین"),
        ]
    )


async def run_web_server(app, port):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is not set.")

    init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    await update_bot_commands(bot)

    app = web.Application()
    app.router.add_get("/", health_check)
    port = int(os.environ.get("PORT", 8080))
    await run_web_server(app, port)

    logging.info("Bot is running and web server started on port %s...", port)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
