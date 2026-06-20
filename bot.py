#!/usr/bin/env python3
"""
MailBot — Telegram bot for email management on custom domains.

Connects to a Dovecot + Postfix mail server via IMAP/SMTP.
Features: create mailboxes, read inbox, send replies, quota display,
auto-delete of password messages, logout.

Env vars:
  MAILBOT_TOKEN     — Telegram Bot token (REQUIRED)
  MAIL_DOMAIN       — Email domain (default: example.com)
  SMTP_USER         — SMTP auth user for sending verification codes
  SMTP_PASSWORD     — SMTP auth password for sending verification codes
  IMAP_HOST         — IMAP server (default: 127.0.0.1)
  SMTP_HOST         — SMTP server (default: 127.0.0.1)
  DOVECOT_USER_FILE — Path to dovecot users file (default: /etc/dovecot/users)
  DOVECOT_EXTRA_FILE— Path to backup email mapping (default: /etc/dovecot/user-extra.conf)
  MAIL_DIR          — Maildir parent (default: /var/mail/vhosts)
  DATA_FILE         — Bot data storage (default: /opt/mailbot/data.json)
  MAIL_QUOTA        — Mailbox quota in MB (default: 300)
"""

import asyncio, logging, os, sys, json, imaplib, smtplib, re, random, subprocess, binascii, email as eml
from datetime import datetime
from email.header import decode_header
from email.mime.text import MIMEText
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reserved_names import is_reserved

# ─── Configuration ──────────────────────────────────────────────

TOKEN = os.environ.get("MAILBOT_TOKEN", "")
if not TOKEN:
    print("ERROR: MAILBOT_TOKEN environment variable not set")
    sys.exit(1)

DOMAIN = os.environ.get("MAIL_DOMAIN", "example.com")
MAIL_QUOTA_MB = int(os.environ.get("MAIL_QUOTA", "300"))
MAIL_QUOTA_BYTES = MAIL_QUOTA_MB * 1024 * 1024

USER_FILE = os.environ.get("DOVECOT_USER_FILE", "/etc/dovecot/users")
EXTRA_FILE = os.environ.get("DOVECOT_EXTRA_FILE", "/etc/dovecot/user-extra.conf")
MAIL_DIR = os.environ.get("MAIL_DIR", "/var/mail/vhosts")
IMAP_HOST = os.environ.get("IMAP_HOST", "127.0.0.1")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "143"))
SMTP_HOST = os.environ.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
DATA_FILE = os.environ.get("DATA_FILE", "/opt/mailbot/data.json")

SMTP_USER = os.environ.get("SMTP_USER", f"noreply@{DOMAIN}")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
INVITES_FILE = os.environ.get("INVITES_FILE", "/etc/dovecot/invites.json")

WEBMAIL_URL = f"https://mail.{DOMAIN}/"

# ─── Logging ────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Bot init ───────────────────────────────────────────────────

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── States ─────────────────────────────────────────────────────

class RegisterStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_backup = State()
    waiting_for_code = State()
    waiting_for_password_choice = State()
    waiting_password = State()

class LoginStates(StatesGroup):
    waiting_credentials = State()

class MailStates(StatesGroup):
    waiting_reply_text = State()
    waiting_send_to = State()
    waiting_send_subject = State()
    waiting_send_body = State()

# ─── Data helpers ───────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            d = json.load(f)
            return d if "users" in d else {"users": {}}
    return {"users": {}}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(tg_id):
    return load_data()["users"].get(str(tg_id))

def set_user(tg_id, info):
    d = load_data()
    d["users"][str(tg_id)] = info
    save_data(d)

# ─── Password helpers ───────────────────────────────────────────

def hash_password(p):
    r = subprocess.run(["doveadm", "pw", "-s", "BLF-CRYPT", "-p", p],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else f"{{PLAIN}}{p}"

def gen_password(l=10):
    chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ2345679'
    return ''.join(random.choice(chars) for _ in range(l))

# ─── Account helpers ────────────────────────────────────────────

def account_exists(email):
    if not os.path.exists(USER_FILE):
        return False
    with open(USER_FILE) as f:
        for line in f:
            if line.startswith(f"{email}:"):
                return True
    return False

def create_account(email, password, backup=None):
    local = email.split("@")[0]
    domain = email.split("@")[1]
    home = f"{MAIL_DIR}/{domain}/{local}"
    if account_exists(email):
        return False, "Exists"

    hashed = hash_password(password)

    # Create Maildir folders
    folders = ["cur", "new", "tmp",
               ".Drafts/cur", ".Drafts/new", ".Drafts/tmp",
               ".Sent/cur", ".Sent/new", ".Sent/tmp",
               ".Junk/cur", ".Junk/new", ".Junk/tmp",
               ".Trash/cur", ".Trash/new", ".Trash/tmp"]
    for s in folders:
        os.makedirs(f"{home}/{s}", exist_ok=True, mode=0o700)
    os.chown(home, 1000, 1000)
    for root, dirs, files in os.walk(home):
        for d in dirs:
            os.chown(os.path.join(root, d), 1000, 1000)

    # Write to dovecot users file
    with open(USER_FILE, "a") as f:
        f.write(f"{email}:{hashed}:1000:1000::{home}::userdb_mail=maildir:{home}\n")

    if backup:
        with open(EXTRA_FILE, "a") as f:
            f.write(f"{email}:{backup}\n")

    return True, password

# ─── Email sending ──────────────────────────────────────────────

def send_email(to, subject, body):
    """Send notification email (e.g., verification codes, welcome)."""
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = f"noreply@{DOMAIN}"
        msg["To"] = to
        msg["Subject"] = subject
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        s.starttls()
        if SMTP_PASSWORD:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
        s.quit()
        return True
    except Exception as e:
        logger.error(f"send_email failed: {e}")
        return False

# ─── Quota / usage ──────────────────────────────────────────────

def get_mailbox_usage(email):
    """
    Return (used_bytes, used_human, quota_bytes, quota_human, percent) or None.
    """
    try:
        local, domain = email.split("@")
        path = f"{MAIL_DIR}/{domain}/{local}"
        if not os.path.exists(path):
            return None
        result = subprocess.run(["du", "-sb", path],
                                capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        used = int(result.stdout.split()[0])
        pct = round(used / MAIL_QUOTA_BYTES * 100, 1)

        def fmt(b):
            if b < 1024:
                return f"{b} B"
            elif b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            elif b < 1024 * 1024 * 1024:
                return f"{b / 1024 / 1024:.1f} MB"
            else:
                return f"{b / 1024 / 1024 / 1024:.2f} GB"

        return (used, fmt(used), MAIL_QUOTA_BYTES, fmt(MAIL_QUOTA_BYTES), pct)
    except Exception as e:
        logger.warning(f"get_mailbox_usage failed for {email}: {e}")
        return None

# ─── Keyboards ──────────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Входящие", callback_data="inbox")],
        [InlineKeyboardButton(text="📧 Написать письмо", callback_data="compose")],
        [InlineKeyboardButton(text="👤 Мой ящик", callback_data="mybox")],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")]])

def noacc_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Создать ящик", callback_data="register")],
        [InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])

def inbox_kb(emails):
    kb = []
    for e in emails:
        if "error" in e:
            kb.append([InlineKeyboardButton(text=f"⚠️ {e['error'][:40]}", callback_data="refresh")])
            continue
        kb.append([InlineKeyboardButton(
            text=f"✉️ {e.get('subject','')[:28]} — {e.get('from','?')[:18]}",
            callback_data=f"read_{e.get('uid','')}")])
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="inbox")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ─── IMAP ───────────────────────────────────────────────────────

def fetch_mails(email, password, count=5):
    try:
        m = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        m.starttls()
        m.login(email, password)
        m.select("INBOX")
        r, d = m.search(None, "ALL")
        if r != "OK":
            m.logout()
            return []
        ids = d[0].split()[-count:]
        msgs = []
        for i in ids:
            r2, d2 = m.fetch(i, "(RFC822)")
            if r2 != "OK":
                continue
            msg = eml.message_from_bytes(d2[0][1])
            s = msg.get("Subject", "")
            try:
                s = "".join(
                    p.decode(ch or "utf-8", "replace") if isinstance(p, bytes) else p
                    for p, ch in decode_header(s))
            except Exception:
                pass
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", "replace")[:500]
                        except Exception:
                            body = "(decode err)"
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode(
                        msg.get_content_charset() or "utf-8", "replace")[:500]
                except Exception:
                    body = "(decode err)"
            msgs.append({
                "uid": i.decode() if isinstance(i, bytes) else i,
                "subject": str(s)[:100],
                "from": str(msg.get("From", "?"))[:100],
                "date": str(msg.get("Date", ""))[:30],
                "body": body,
            })
        m.logout()
        return msgs[::-1]
    except Exception as e:
        return [{"error": str(e)}]

# ─── Handlers ───────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = get_user(message.from_user.id)
    if user:
        extra = "\n🔑 Пароль **не сохранён** — используй /login" if not user.get("password") else ""
        k = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Входящие", callback_data="inbox")],
            [InlineKeyboardButton(text="📧 Написать письмо", callback_data="compose")],
            [InlineKeyboardButton(text="👤 Мой ящик", callback_data="mybox")],
            [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")]])
        await message.answer(
            f"👋 С возвращением, `{user['email']}`!\n\n📥 /inbox\n📧 /send\n👤 /mybox{extra}",
            parse_mode="Markdown", reply_markup=k)
    else:
        await message.answer(
            f"📧 **MailBot** — почта @{DOMAIN} в Telegram\n\n"
            "▸ Создай ящик за 10 секунд\n▸ Читай и отвечай на письма\n▸ Отправляй новые\n"
            "▸ Файлы зашифрованы на сервере\n▸ Логи отключены\n\n"
            f"🔗 {WEBMAIL_URL}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Создать ящик", callback_data="register")],
                [InlineKeyboardButton(text="🔐 Войти", callback_data="login")],
                [InlineKeyboardButton(text="🌐 Webmail", url=WEBMAIL_URL)]]))

@dp.message(Command("cancel"))
@dp.message(Command("exit"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Cancel any active operation and clear FSM state."""
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("✅ **Действие отменено.**\n\n/start — меню",
                             parse_mode="Markdown", reply_markup=main_kb())
    else:
        await message.answer("ℹ️ **Нет активного действия.**", parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    user = get_user(message.from_user.id)
    base = "📖 **Помощь**\n\n"
    cmds = (
        "/start — меню\n"
        "/register — создать ящик\n"
        "/login — войти (если пароль не сохранён)\n"
        "/inbox — входящие\n"
        "/send — написать письмо\n"
        "/mybox — мой ящик\n"
        "/logout — выйти (удалить пароль из бота)\n"
        "/cancel — отменить текущее действие\n"
        "/exit — то же, что /cancel\n"
        "\n"
        f"🔗 {WEBMAIL_URL}"
    )
    if user:
        status = f"✅ `{user['email']}`" if user.get("password") else f"⚠️ `{user['email']}` (без пароля)"
        await message.answer(base + "Вы залогинены как: " + status + "\n\n" + cmds,
                             parse_mode="Markdown")
    else:
        await message.answer(base + cmds, parse_mode="Markdown")

@dp.message(Command("mybox"))
async def cmd_mybox(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ **Ящик не подключён.**\n🔑 /register — создать\n🔐 /login — войти",
                             parse_mode="Markdown", reply_markup=noacc_kb())
        return
    usage = get_mailbox_usage(user["email"])
    extra = ""
    if usage:
        filled = max(0, min(10, int(usage[4] / 10)))
        empty = 10 - filled
        bar = "🟩" * filled + "⬜" * empty
        extra = f"\n📦 **{usage[3]}**\n{bar} `{usage[4]}%` (**{usage[1]}**)"
    await message.answer(
        f"👤 **Мой ящик**\n\n📧 `{user['email']}`\n📅 {user.get('created_at', '?')}{extra}\n\n"
        f"🔗 {WEBMAIL_URL}\n📌 IMAP: 993 (SSL) or 143 (STARTTLS)\n📌 SMTP: 587 (STARTTLS)",
        parse_mode="Markdown", reply_markup=main_kb())

@dp.message(Command("inbox"))
async def cmd_inbox(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ **Ящик не подключён.**\n🔑 /register — создать\n🔐 /login — войти",
                             parse_mode="Markdown", reply_markup=noacc_kb())
        return
    if not user.get("password"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])
        await message.answer("🔐 **Пароль не сохранён.**\n/login — войти",
                             parse_mode="Markdown", reply_markup=kb)
        return
    await message.answer("📥 Загружаю...")
    msgs = fetch_mails(user["email"], user["password"])
    if not msgs or "error" in msgs[0]:
        await message.answer("📭 Пусто." if not msgs else f"❌ {msgs[0]['error']}",
                             reply_markup=main_kb())
        return
    user["last_emails"] = msgs
    user["seen_uids"] = list(set(user.get("seen_uids", []) + [str(e.get("uid","")) for e in msgs]))
    set_user(message.from_user.id, user)
    await message.answer(f"📥 **Входящие** ({len(msgs)}):",
                         parse_mode="Markdown", reply_markup=inbox_kb(msgs))

# ─── Registration ───────────────────────────────────────────────

@dp.callback_query(lambda c: c.data in ("register", "login"))
async def cb_reg_or_login(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "login":
        await callback.message.edit_text(
            "🔐 **Вход**\n\nВведи email и пароль через пробел:\n"
            f"`ivan@{DOMAIN} пароль`\n\n/cancel — отмена",
            parse_mode="Markdown")
        await state.set_state(LoginStates.waiting_credentials)
        await callback.answer()
        return

    if get_user(callback.from_user.id):
        u = get_user(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Один Telegram = один ящик.\nТвой: `{u['email']}`\n\n📥 /inbox — входящие",
            parse_mode="Markdown", reply_markup=main_kb())
        await callback.answer()
        return

    await callback.message.edit_text(
        f"🔑 **Создание ящика**\n\nВведи желаемое имя:\n`john` → `john@{DOMAIN}`\n\n"
        "• > 2 символов\n• a-z, 0-9, точка, дефис",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_name)
    await callback.answer()

@dp.message(RegisterStates.waiting_for_name)
async def reg_name(m: types.Message, state: FSMContext):
    name = m.text.strip().lower()
    if not re.match(r"^[a-z0-9._-]+$", name):
        await m.answer("❌ Только a-z, 0-9, . и -")
        return
    if is_reserved(name):
        await m.answer("❌ Имя занято или < 3 символов")
        return
    email = f"{name}@{DOMAIN}"
    if account_exists(email):
        await m.answer("❌ Уже существует")
        return
    await state.update_data(email=email, name=name)
    await m.answer(
        f"✅ `{name}` свободен!\n\n📧 Ящик: `{email}`\n\n"
        "Укажи **резервную почту** (туда придёт код):\n/cancel — отмена",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_backup)

@dp.message(RegisterStates.waiting_for_backup)
async def reg_backup(m: types.Message, state: FSMContext):
    bk = m.text.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", bk):
        await m.answer("❌ Непохоже на email")
        return
    if f"@{DOMAIN}" in bk:
        await m.answer(f"❌ Резервная не может быть на @{DOMAIN}")
        return
    code = str(random.randint(0, 999999)).zfill(6)
    await state.update_data(backup=bk, verify_code=code)
    if not send_email(bk, f"Verification code for @{DOMAIN}", f"Your code: {code}"):
        await m.answer("❌ Не удалось отправить код. Проверь адрес:")
        return
    await m.answer(
        f"✅ Код отправлен на `{bk}`\n\nВведи 6-значный код из письма:\n/cancel — отмена",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_code)

@dp.message(RegisterStates.waiting_for_code)
async def reg_code(m: types.Message, state: FSMContext):
    d = await state.get_data()
    if m.text.strip() != d.get("verify_code", ""):
        await m.answer("❌ Неверный код. Попробуй ещё раз:")
        return
    await m.answer(
        "🔑 **Пароль**\n\n"
        "Выбери способ:\n\n"
        "1️⃣ **Сгенерировать** — бот создаст пароль и сохранит его\n"
        "2️⃣ **Ввести свой** — ⚠️ пароль будет виден администратору сервера\n"
        "3️⃣ **Не сохранять** — бот будет спрашивать пароль при каждом входе\n\n"
        "Отправь **1**, **2** или **3**:",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_password_choice)

# ─── Login ──────────────────────────────────────────────────────

@dp.message(LoginStates.waiting_credentials)
async def login_cred(m: types.Message, state: FSMContext):
    parts = m.text.strip().split(None, 1)
    if len(parts) != 2:
        await m.answer("❌ Введи email и пароль через пробел")
        return
    email, pw = parts[0].strip(), parts[1].strip()
    if f"@{DOMAIN}" not in email:
        await m.answer(f"❌ Только @{DOMAIN}")
        return
    st = await m.answer("🔄 Проверяю...")
    try:
        im = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        im.starttls()
        im.login(email, pw)
        im.logout()
    except Exception as e:
        await st.edit_text(f"❌ {str(e)[:80]}")
        await state.clear()
        return
    set_user(m.from_user.id, {
        "email": email,
        "password": pw,
        "backup": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tg_username": m.from_user.username or "",
        "seen_uids": [],
    })
    await st.edit_text(f"✅ **Вошёл!**\n📧 `{email}`\n\n📥 /inbox",
                       parse_mode="Markdown", reply_markup=main_kb())
    await state.clear()

# ─── Inline: inbox, read, reply ─────────────────────────────────

@dp.callback_query(lambda c: c.data == "inbox")
async def cb_inbox(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    if not u:
        await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb())
        await cb.answer()
        return
    if not u.get("password"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])
        await cb.message.edit_text("🔐 **Пароль не сохранён.**\n/login — войти",
                                   parse_mode="Markdown", reply_markup=kb)
        await cb.answer()
        return
    msgs = fetch_mails(u["email"], u["password"])
    u["last_emails"] = msgs
    u["seen_uids"] = list(set(u.get("seen_uids", []) + [str(e.get("uid","")) for e in msgs]))
    set_user(cb.from_user.id, u)
    if not msgs or "error" in msgs[0]:
        await cb.message.edit_text("📭 Пусто.", reply_markup=main_kb())
        await cb.answer()
        return
    await cb.message.edit_text(f"📥 **Входящие** ({len(msgs)}):",
                               parse_mode="Markdown", reply_markup=inbox_kb(msgs))
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("read_"))
async def cb_read(cb: types.CallbackQuery):
    uid = cb.data.split("_", 1)[1]
    u = get_user(cb.from_user.id)
    if not u:
        await cb.answer("Нет доступа")
        return
    ed = next((e for e in u.get("last_emails", []) if str(e.get("uid")) == uid), None)
    if not ed:
        await cb.message.edit_text("❌ Не найдено")
        await cb.answer()
        return
    t = (f"✉️ **{ed.get('subject', '')}**\n\n"
         f"👤 {ed.get('from', '?')}\n📅 {ed.get('date', '')[:25]}\n\n"
         f"{ed.get('body', '')[:1000]}")
    k = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Ответить", callback_data=f"reply_{uid}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{uid}")],
        [InlineKeyboardButton(text="◀️", callback_data="inbox")]])
    await cb.message.edit_text(t, parse_mode="Markdown", reply_markup=k)
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("delete_"))
async def cb_delete(cb: types.CallbackQuery):
    """Delete an email via IMAP (mark as deleted then expunge)."""
    uid = cb.data.split("_", 1)[1]
    u = get_user(cb.from_user.id)
    if not u:
        await cb.answer("Нет доступа")
        return
    st = await cb.message.edit_text("🗑 Удаляю...")
    try:
        m = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        m.starttls()
        m.login(u["email"], u["password"])
        m.select("INBOX")
        m.store(uid, "+FLAGS", "\\Deleted")
        m.expunge()
        m.logout()
        await st.edit_text("✅ **Письмо удалено**", parse_mode="Markdown", reply_markup=main_kb())
    except Exception as e:
        await st.edit_text(f"❌ Ошибка удаления: {str(e)[:60]}", reply_markup=main_kb())


@dp.callback_query(lambda c: c.data.startswith("reply_"))
async def cb_reply(cb: types.CallbackQuery, state: FSMContext):
    uid = cb.data.split("_", 1)[1]
    u = get_user(cb.from_user.id)
    if not u:
        await cb.answer("Нет доступа")
        return
    ed = next((e for e in u.get("last_emails", []) if str(e.get("uid")) == uid), None)
    if not ed:
        await cb.answer("Не найдено")
        return
    await state.update_data(reply_to=ed)
    await cb.message.edit_text(
        f"📝 **Ответ:** {ed.get('subject', '')[:40]}\n\nТекст:\n/cancel — отмена",
        parse_mode="Markdown")
    await state.set_state(MailStates.waiting_reply_text)
    await cb.answer()

@dp.message(MailStates.waiting_reply_text)
async def reply_txt(m: types.Message, state: FSMContext):
    d = await state.get_data()
    rt = d.get("reply_to", {})
    u = get_user(m.from_user.id)
    if not u or not rt:
        await m.answer("❌ Ошибка")
        await state.clear()
        return
    st = await m.answer("📤 Отправляю...")
    try:
        msg = MIMEText(m.text, "plain", "utf-8")
        msg["From"] = u["email"]
        msg["To"] = rt.get("from", "")
        msg["Subject"] = f"Re: {rt.get('subject', '')}"
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        s.starttls()
        s.login(u["email"], u["password"])
        s.send_message(msg)
        s.quit()
        await st.edit_text("✅ Отправлено!", reply_markup=main_kb())
    except Exception as e:
        await st.edit_text(f"❌ {str(e)[:80]}", reply_markup=main_kb())
    await state.clear()

# ─── Compose ────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "compose")
async def cb_compose(cb: types.CallbackQuery, state: FSMContext):
    u = get_user(cb.from_user.id)
    if not u:
        await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb())
        await cb.answer()
        return
    if not u.get("password"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])
        await cb.message.edit_text("🔐 **Пароль не сохранён.**\n/login — войди",
                                   parse_mode="Markdown", reply_markup=kb)
        await cb.answer()
        return
    await cb.message.edit_text("📧 **Новое письмо**\n\nEmail получателя:\n/cancel — отмена",
                               parse_mode="Markdown")
    await state.set_state(MailStates.waiting_send_to)
    await cb.answer()

@dp.message(MailStates.waiting_send_to)
async def snd_to(m: types.Message, state: FSMContext):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", m.text.strip()):
        await m.answer("❌ Непохоже на email")
        return
    await state.update_data(send_to=m.text.strip())
    await m.answer("📝 Тема письма:\n/cancel — отмена")
    await state.set_state(MailStates.waiting_send_subject)

@dp.message(MailStates.waiting_send_subject)
async def snd_subj(m: types.Message, state: FSMContext):
    await state.update_data(send_subject=m.text.strip())
    await m.answer("✏️ Текст:\n/cancel — отмена")
    await state.set_state(MailStates.waiting_send_body)

@dp.message(MailStates.waiting_send_body)
async def snd_body(m: types.Message, state: FSMContext):
    d = await state.get_data()
    u = get_user(m.from_user.id)
    if not u:
        await m.answer("❌ Нет доступа")
        await state.clear()
        return
    st = await m.answer("📤 Отправляю...")
    try:
        msg = MIMEText(m.text, "plain", "utf-8")
        msg["From"] = u["email"]
        msg["To"] = d.get("send_to", "")
        msg["Subject"] = d.get("send_subject", "")
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        s.starttls()
        s.login(u["email"], u["password"])
        s.send_message(msg)
        s.quit()
        await st.edit_text(f"✅ Отправлено на `{d.get('send_to', '')}`!",
                           parse_mode="Markdown", reply_markup=main_kb())
    except Exception as e:
        await st.edit_text(f"❌ {str(e)[:80]}", reply_markup=main_kb())
    await state.clear()

# ─── Menu / Mybox callbacks ─────────────────────────────────────

@dp.callback_query(lambda c: c.data == "menu")
async def cb_menu(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    t = f"👋 **Меню**\n`{u['email']}`" if u else "👋 **Меню**"
    await cb.message.edit_text(t, parse_mode="Markdown", reply_markup=main_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "mybox")
async def cb_mybox(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    if not u:
        await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb())
        await cb.answer()
        return
    usage = get_mailbox_usage(u["email"])
    extra = ""
    if usage:
        filled = max(0, min(10, int(usage[4] / 10)))
        empty = 10 - filled
        bar = "🟩" * filled + "⬜" * empty
        extra = f"\n📦 **{usage[3]}**\n{bar} `{usage[4]}%` (**{usage[1]}**)"
    await cb.message.edit_text(
        f"👤 **Мой ящик**\n\n📧 `{u['email']}`\n📅 {u.get('created_at', '?')}{extra}\n\n🔗 {WEBMAIL_URL}",
        parse_mode="Markdown", reply_markup=main_kb())
    await cb.answer()

# ─── Delete message after 10 min ────────────────────────────────

async def delete_msg_later(msg, text):
    """Edit message to privacy notice after 10 minutes."""
    await asyncio.sleep(600)
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        pass

# ─── Create account ─────────────────────────────────────────────

async def do_create_account(msg, state, email, name, backup, password, store_password=True):
    """Create mail account, send welcome emails, generate invite codes."""
    ok, res = create_account(email, password, backup)
    if not ok:
        await msg.answer(f"❌ {res}")
        await state.clear()
        return

    # Generate invitation codes
    codes = [binascii.hexlify(os.urandom(16)).decode() for _ in range(3)]
    try:
        inv = {}
        if os.path.exists(INVITES_FILE):
            with open(INVITES_FILE) as f:
                inv = json.load(f)
        for code in codes:
            inv[code] = {
                "email": email,
                "created_by": email,
                "used": False,
                "used_by": None,
                "created_at": datetime.now().isoformat(),
                "used_at": None,
            }
        with open(INVITES_FILE, "w") as f:
            json.dump(inv, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Invite codes not saved: {e}")

    # Save to bot data
    user_data = {
        "email": email,
        "backup": backup,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tg_username": msg.from_user.username or "",
        "seen_uids": [],
    }
    if store_password:
        user_data["password"] = password
    else:
        user_data["password"] = ""
        user_data["store_password"] = False
    set_user(msg.from_user.id, user_data)

    # Send notification emails
    full = (
        f"Mailbox {email} created!\n\nEmail: {email}\nPassword: {password}\n\n"
        f"Webmail: {WEBMAIL_URL}\n\n=== CLIENTS ===\n"
        f"Server: mail.{DOMAIN}\nIMAP: 993 (SSL) or 143 (STARTTLS)\n"
        f"POP3: 995 (SSL) or 110 (STARTTLS)\nSMTP: 587 (STARTTLS)\nUser: Full email\n\n"
        f"=== LIMITS ===\n{MAIL_QUOTA_MB} MB\n\n=== PRIVACY ===\nLogs: OFF\nEncryption: ON\n\n"
        f"=== INVITATION CODES ===\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(codes))
        + "\n\n-- mail.ramadoit.ru"
    )
    short = (
        f"Mailbox {email} created!\n\nEmail: {email}\nPassword: {password}\n\n"
        f"Web: {WEBMAIL_URL}\nLimit: {MAIL_QUOTA_MB} MB\nLogs: OFF\nEncryption: ON\n\n"
        f"Invitation codes:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(codes))
    )
    send_email(email, f"Your mailbox {email} created", full)
    send_email(backup, f"Mailbox {email} on {DOMAIN} created", short)

    pw_notice = "\n🔑 Пароль сохранён в боте." if store_password else "\n🔑 Пароль НЕ сохранён. Используй /login при каждом входе."

    sent_msg = await msg.answer(
        f"✅ **Ящик создан!**\n\n📧 `{email}`\n🔑 `{password}`\n\n🔗 {WEBMAIL_URL}\n\n"
        f"**Настройки клиентов:**\nIMAP: `993 (SSL)`\nSMTP: `587 (STARTTLS)`\nUser: полный email\n\n"
        f"**3 кода приглашения:**\n" + "\n".join(f"`{c}`" for c in codes)
        + f"\n\n⚠️ Пароль показан один раз. Он будет удалён через 10 минут." + pw_notice
        + "\n📥 /inbox — проверить почту",
        parse_mode="Markdown", reply_markup=main_kb())

    # Auto-delete password after 10 minutes
    asyncio.create_task(delete_msg_later(
        sent_msg,
        "⌛️ **Сообщение удалено для конфиденциальности**\n\n"
        "Пароль был показан выше. Если не сохранил — используй /mybox или проверь почту."))
    await state.clear()

# ─── Password choice ────────────────────────────────────────────

@dp.message(RegisterStates.waiting_for_password_choice)
async def reg_password_choice(m: types.Message, state: FSMContext):
    d = await state.get_data()
    choice = m.text.strip()
    email, name, backup = d["email"], d["name"], d["backup"]

    if choice == "1":
        password = gen_password()
        await do_create_account(m, state, email, name, backup, password, store_password=True)
    elif choice == "2":
        await m.answer(
            "🔑 **Введи свой пароль**\n\n"
            "⚠️ **Внимание:** пароль хранится на сервере в открытом виде.\n"
            "Администратор сервера технически может его прочитать.\n\n"
            "Если это не устраивает — используй вариант **1** (автогенерация).\n\n"
            "Введи пароль (минимум 6 символов):\n/cancel — отмена",
            parse_mode="Markdown")
        await state.update_data(password_choice="user")
        await state.set_state(RegisterStates.waiting_password)
    elif choice == "3":
        await m.answer(
            "🔑 **Без сохранения пароля**\n\n"
            "Пароль не будет сохранён в боте.\n"
            "При каждом действии бот будет запрашивать пароль.\n\n"
            "Пароль будет отправлен на твою почту.\n"
            "Сохрани его!\n\n"
            "Нажми **Создать ящик**, чтобы продолжить:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Создать ящик", callback_data="do_create_nopass")]]))
        await state.update_data(password_choice="none")
    else:
        await m.answer("❌ Отправь **1**, **2** или **3**:")

@dp.callback_query(lambda c: c.data == "do_create_nopass")
async def cb_create_nopass(cb: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    password = gen_password()
    await do_create_account(cb.message, state, d["email"], d["name"], d["backup"],
                            password, store_password=False)
    await cb.answer()

@dp.message(RegisterStates.waiting_password)
async def reg_user_password(m: types.Message, state: FSMContext):
    d = await state.get_data()
    pw = m.text.strip()
    if len(pw) < 6:
        await m.answer("❌ Минимум 6 символов. Введи ещё раз:")
        return
    await do_create_account(m, state, d["email"], d["name"], d["backup"], pw, store_password=True)

# ─── Logout ─────────────────────────────────────────────────────

@dp.message(Command("logout"))
async def cmd_logout(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer(
            "❌ **Ты не залогинен.**\n\n🔑 /register — создать ящик\n🔐 /login — войти",
            parse_mode="Markdown")
        return
    email = user["email"]
    user["password"] = ""
    user["logged_out"] = True
    set_user(message.from_user.id, user)
    await state.clear()
    await message.answer(
        f"✅ **Вышел из ящика**\n\n📧 `{email}` — запомнен\n🔑 Пароль удалён из бота\n\n"
        f"Повторно зарегистрироваться нельзя — 1 Telegram = 1 почта.\n"
        f"\n🔐 /login — войти снова\n"
        f"🔑 /register — если хочешь сменить ящик (удалит старый)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="login")],
            [InlineKeyboardButton(text="🔑 Новый ящик", callback_data="force_register")]]))

@dp.callback_query(lambda c: c.data == "logout")
async def cb_logout(cb: types.CallbackQuery, state: FSMContext):
    user = get_user(cb.from_user.id)
    if not user:
        await cb.message.edit_text("❌ Не залогинен", reply_markup=noacc_kb())
        await cb.answer()
        return
    email = user["email"]
    user["password"] = ""
    user["logged_out"] = True
    set_user(cb.from_user.id, user)
    await state.clear()
    await cb.message.edit_text(
        f"✅ **Вышел из ящика**\n\n📧 `{email}` — запомнен\n🔑 Пароль удалён\n\n"
        f"1 Telegram = 1 почта — повторно создать нельзя.\n"
        f"🔐 /login — войти снова",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="login")]]))
    await cb.answer()

# ─── Force re-register ──────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "force_register")
async def cb_force_register(cb: types.CallbackQuery, state: FSMContext):
    user = get_user(cb.from_user.id)
    if not user:
        await cb_reg_or_login(cb, state)
        return
    await cb.message.edit_text(
        "⚠️ **Смена ящика**\n\n"
        f"Сейчас привязан: `{user['email']}`\n\n"
        "Если создашь новый ящик, старый останется на сервере, "
        "но привязка к Telegram сменится.\n\n"
        "Продолжить?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, создать новый", callback_data="confirm_force_reg")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")]]))
    await cb.answer()

@dp.callback_query(lambda c: c.data == "confirm_force_reg")
async def cb_confirm_force_reg(cb: types.CallbackQuery, state: FSMContext):
    tg_id = str(cb.from_user.id)
    d = load_data()
    if tg_id in d["users"]:
        del d["users"][tg_id]
        save_data(d)
    await cb.message.edit_text(
        f"🔑 **Создание нового ящика**\n\n"
        f"Введи желаемое имя:\n`john` → `john@{DOMAIN}`\n\n"
        "• > 2 символов\n• a-z, 0-9, точка, дефис",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_name)
    await cb.answer()

# ─── Start ──────────────────────────────────────────────────────

async def check_new_mails_loop():
    """Background task: check for new emails every 60 seconds and notify."""
    await asyncio.sleep(10)
    while True:
        try:
            d = load_data()
            for tg_id_str, user in d.get("users", {}).items():
                if not user.get("password"):
                    continue
                tg_id = int(tg_id_str)
                try:
                    m = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
                    m.starttls()
                    m.login(user["email"], user["password"])
                    m.select("INBOX")
                    r, data = m.search(None, "ALL")
                    if r != "OK":
                        m.logout()
                        continue
                    all_ids = [i.decode() if isinstance(i, bytes) else i for i in data[0].split()]
                    if not all_ids:
                        m.logout()
                        continue
                    recent_ids = all_ids[-5:]
                    seen = set(user.get("seen_uids", []))
                    new_ids = [uid for uid in recent_ids if uid not in seen]
                    if new_ids:
                        for uid in new_ids:
                            r2, d2 = m.fetch(uid, "(RFC822)")
                            if r2 != "OK":
                                continue
                            msg = eml.message_from_bytes(d2[0][1])
                            subject = str(msg.get("Subject", "(No subject)"))[:80]
                            from_ = str(msg.get("From", "?"))[:60]
                            try:
                                from email.header import decode_header
                                subject = "".join(
                                    p.decode(ch or "utf-8", "replace") if isinstance(p, bytes) else p
                                    for p, ch in decode_header(subject))
                            except:
                                pass
                            notif = f"\U0001f4e8 **\u041d\u043e\u0432\u043e\u0435 \u043f\u0438\u0441\u044c\u043c\u043e**\n\n\U0001f464 {from_}\n\U0001f4dd {subject}"
                            try:
                                await bot.send_message(tg_id, notif, parse_mode="Markdown")
                            except:
                                pass
                        user["seen_uids"] = list(set(seen | set(new_ids)))
                        d["users"][tg_id_str] = user
                    m.logout()
                except Exception as e:
                    logger.warning(f"Notification check failed for {user['email']}: {e}")
            if d:
                save_data(d)
        except Exception as e:
            logger.error(f"check_new_mails_loop error: {e}")
        await asyncio.sleep(60)


async def main():
    logger.info(f"Starting MailBot... IMAP: {IMAP_HOST}:{IMAP_PORT} Domain: {DOMAIN}")
    asyncio.create_task(check_new_mails_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
