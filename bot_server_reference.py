#!/usr/bin/env python3
"""MailBot — Telegram bot for mail.ramadoit.ru"""

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

TOKEN = os.environ.get("MAILBOT_TOKEN", "")
if not TOKEN: print("ERROR: MAILBOT_TOKEN not set"); sys.exit(1)

DOMAIN = "ramadoit.ru"
USER_FILE = "/etc/dovecot/users"
EXTRA_FILE = "/etc/dovecot/user-extra.conf"
MAIL_DIR = "/var/mail/vhosts"
IMAP_HOST = "127.0.0.1"; IMAP_PORT = 143
SMTP_HOST = "127.0.0.1"; SMTP_PORT = 587
DATA_FILE = "/opt/mailbot/data.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

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

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            d = json.load(f)
            return d if "users" in d else {"users": {}}
    return {"users": {}}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f: json.dump(data, f, indent=2)

def get_user(tg_id):
    return load_data()["users"].get(str(tg_id))

def set_user(tg_id, info):
    d = load_data(); d["users"][str(tg_id)] = info; save_data(d)

def hash_password(p):
    r = subprocess.run(["doveadm","pw","-s","BLF-CRYPT","-p",p], capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else f"{{PLAIN}}{p}"

def gen_password(l=10):
    c = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ2345679'
    return ''.join(random.choice(c) for _ in range(l))

def account_exists(email):
    if not os.path.exists(USER_FILE): return False
    with open(USER_FILE) as f:
        for l in f:
            if l.startswith(f"{email}:"): return True
    return False

def create_account(email, password, backup=None):
    local = email.split("@")[0]; domain = email.split("@")[1]
    home = f"{MAIL_DIR}/{domain}/{local}"
    if account_exists(email): return False, "Exists"
    hashed = hash_password(password)
    for s in ["cur","new","tmp",".Drafts/cur",".Drafts/new",".Drafts/tmp",
              ".Sent/cur",".Sent/new",".Sent/tmp",".Junk/cur",".Junk/new",".Junk/tmp",
              ".Trash/cur",".Trash/new",".Trash/tmp"]:
        os.makedirs(f"{home}/{s}", exist_ok=True, mode=0o700)
    os.chown(home, 1000, 1000)
    for root, dirs, files in os.walk(home):
        for d in dirs: os.chown(os.path.join(root,d), 1000, 1000)
    with open(USER_FILE, "a") as f:
        f.write(f"{email}:{hashed}:1000:1000::{home}::userdb_mail=maildir:{home}\n")
    if backup:
        with open(EXTRA_FILE, "a") as f: f.write(f"{email}:{backup}\n")
    return True, password

def send_email(to, subj, body):
    try:
        m = MIMEText(body, "plain", "utf-8")
        m["From"] = f"noreply@{DOMAIN}"; m["To"] = to; m["Subject"] = subj
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        s.starttls()
        s.login(f"zwitch@{DOMAIN}", "CMMrvJB2EH")
        s.send_message(m); s.quit(); return True
    except: return False

def get_mailbox_usage(email):
    """Return (used_bytes, used_human, quota_bytes, quota_human, percent) or None"""
    try:
        local, domain = email.split("@")
        path = f"/var/mail/vhosts/{domain}/{local}"
        if not os.path.exists(path):
            return None
        result = subprocess.run(["du", "-sb", path], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        used = int(result.stdout.split()[0])
        quota = 300 * 1024 * 1024  # 300 MB
        pct = round(used / quota * 100, 1)
        def fmt(b):
            if b < 1024: return f"{b} B"
            elif b < 1024*1024: return f"{b/1024:.1f} KB"
            elif b < 1024*1024*1024: return f"{b/1024/1024:.1f} MB"
            else: return f"{b/1024/1024/1024:.2f} GB"
        return (used, fmt(used), quota, fmt(quota), pct)
    except:
        return None

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
        if "error" in e: kb.append([InlineKeyboardButton(text=f"⚠️ {e['error'][:40]}", callback_data="refresh")]); continue
        kb.append([InlineKeyboardButton(text=f"✉️ {e.get('subject','')[:28]} — {e.get('from','?')[:18]}", callback_data=f"read_{e.get('uid','')}")])
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="inbox")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def fetch_mails(email, password, count=5):
    try:
        m = imaplib.IMAP4(IMAP_HOST, IMAP_PORT); m.starttls(); m.login(email, password)
        m.select("INBOX")
        r, d = m.search(None, "ALL")
        if r != "OK": m.logout(); return []
        ids = d[0].split()[-count:]
        msgs = []
        for i in ids:
            r2, d2 = m.fetch(i, "(RFC822)")
            if r2 != "OK": continue
            msg = eml.message_from_bytes(d2[0][1])
            s = msg.get("Subject","")
            try: s = "".join(p.decode(ch or "utf-8","replace") if isinstance(p,bytes) else p for p,ch in decode_header(s))
            except: pass
            body = ""
            if msg.is_multipart():
                for p in msg.walk():
                    if p.get_content_type() == "text/plain":
                        try: body = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8","replace")[:500]
                        except: body = "(decode err)"
                        break
            else:
                try: body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8","replace")[:500]
                except: body = "(decode err)"
            msgs.append({"uid": i.decode() if isinstance(i,bytes) else i, "subject": str(s)[:100], "from": str(msg.get("From","?"))[:100], "date": str(msg.get("Date",""))[:30], "body": body})
        m.logout()
        return msgs[::-1]
    except Exception as e: return [{"error": str(e)}]

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
        await message.answer(f"👋 С возвращением, `{user['email']}`!\n\n📥 /inbox\n📧 /send\n👤 /mybox{extra}", parse_mode="Markdown", reply_markup=k)
    else:
        await message.answer(
            "📧 **RamaDoItMail** — почта @ramadoit.ru в Telegram\n\n"
            "▸ Создай ящик за 10 секунд\n▸ Читай и отвечай на письма\n▸ Отправляй новые\n"
            "▸ Файлы зашифрованы на сервере\n▸ Логи отключены\n\n"
            "🔗 Webmail: https://mail.ramadoit.ru/",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Создать ящик", callback_data="register")],
                [InlineKeyboardButton(text="🔐 Войти", callback_data="login")],
                [InlineKeyboardButton(text="🌐 Webmail", url="https://mail.ramadoit.ru/")]]))

@dp.message(Command("cancel"))
@dp.message(Command("exit"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Cancel any active operation and clear FSM state"""
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("✅ **Действие отменено.**\n\n/start — меню", parse_mode="Markdown", reply_markup=main_kb())
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
        "🔗 https://mail.ramadoit.ru/"
    )
    if user:
        status = "✅ `" + user["email"] + "`" if user.get("password") else "⚠️ `" + user["email"] + "` (без пароля)"
        await message.answer(base + "Вы залогинены как: " + status + "\n\n" + cmds, parse_mode="Markdown")
    else:
        await message.answer(base + cmds, parse_mode="Markdown")

@dp.message(Command("mybox"))
async def cmd_mybox(message: types.Message):
    user = get_user(message.from_user.id)
    if not user: await message.answer("❌ **Ящик не подключён.**\n🔑 /register — создать\n🔐 /login — войти", parse_mode="Markdown", reply_markup=noacc_kb()); return
    usage = get_mailbox_usage(user["email"])
    extra = ""
    if usage:
        bar = "🟩" * max(0, min(10, int(usage[4] / 10))) + "⬜" * max(0, 10 - min(10, int(usage[4] / 10)))
        extra = f"\n📦 **{usage[3]}**\n{bar} `{usage[4]}%` (**{usage[1]}**)"
    await message.answer(f"👤 **Мой ящик**\n\n📧 `{user['email']}`\n📅 {user.get('created_at','?')}{extra}\n\n🔗 https://mail.ramadoit.ru/\n📌 IMAP: 993 (SSL) or 143 (STARTTLS)\n📌 SMTP: 587 (STARTTLS)", parse_mode="Markdown", reply_markup=main_kb())

@dp.message(Command("inbox"))
async def cmd_inbox(message: types.Message):
    user = get_user(message.from_user.id)
    if not user: await message.answer("❌ **Ящик не подключён.**\n🔑 /register — создать\n🔐 /login — войти", parse_mode="Markdown", reply_markup=noacc_kb()); return
    if not user.get("password"): await message.answer("🔐 **Пароль не сохранён.**\n/login — войти", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])); return
    await message.answer("📥 Загружаю...")
    msgs = fetch_mails(user["email"], user["password"])
    if not msgs or "error" in msgs[0]:
        await message.answer("📭 Пусто." if not msgs else f"❌ {msgs[0]['error']}", reply_markup=main_kb()); return
    user["last_emails"] = msgs; set_user(message.from_user.id, user)
    await message.answer(f"📥 **Входящие** ({len(msgs)}):", parse_mode="Markdown", reply_markup=inbox_kb(msgs))

# Registration

@dp.callback_query(lambda c: c.data in ("register","login"))
async def cb_reg_or_login(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "login":
        await callback.message.edit_text("🔐 **Вход**\n\nВведи email и пароль через пробел:\n`ivan@ramadoit.ru пароль`\n\n/cancel — отмена", parse_mode="Markdown")
        await state.set_state(LoginStates.waiting_credentials); await callback.answer(); return
    if get_user(callback.from_user.id):
        u = get_user(callback.from_user.id)
        await callback.message.edit_text(f"❌ Один Telegram = один ящик.\nТвой: `{u['email']}`\n\n📥 /inbox — входящие", parse_mode="Markdown", reply_markup=main_kb())
        await callback.answer(); return
    await callback.message.edit_text("🔑 **Создание ящика**\n\nВведи желаемое имя:\n`john` → `john@ramadoit.ru`\n\n• > 2 символов\n• a-z, 0-9, точка, дефис", parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_name); await callback.answer()

@dp.message(RegisterStates.waiting_for_name)
async def reg_name(m: types.Message, state: FSMContext):
    name = m.text.strip().lower()
    if not re.match(r"^[a-z0-9._-]+$", name): await m.answer("❌ Только a-z, 0-9, . и -"); return
    if is_reserved(name): await m.answer("❌ Имя занято или < 3 символов"); return
    email = f"{name}@{DOMAIN}"
    if account_exists(email): await m.answer("❌ Уже существует"); return
    await state.update_data(email=email, name=name)
    await m.answer(f"✅ `{name}` свободен!\n\n📧 Ящик: `{email}`\n\nУкажи **резервную почту** (туда придёт код):\n/cancel — отмена", parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_backup)

@dp.message(RegisterStates.waiting_for_backup)
async def reg_backup(m: types.Message, state: FSMContext):
    bk = m.text.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", bk): await m.answer("❌ Непохоже на email"); return
    if f"@{DOMAIN}" in bk: await m.answer(f"❌ Резервная не может быть на @{DOMAIN}"); return
    code = str(random.randint(0,999999)).zfill(6)
    await state.update_data(backup=bk, verify_code=code)
    if not send_email(bk, f"Verification code for @{DOMAIN}", f"Your code: {code}"):
        await m.answer("❌ Не удалось отправить код. Проверь адрес:"); return
    await m.answer(f"✅ Код отправлен на `{bk}`\n\nВведи 6-значный код из письма:\n/cancel — отмена", parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_code)

@dp.message(RegisterStates.waiting_for_code)
async def reg_code(m: types.Message, state: FSMContext):
    d = await state.get_data()
    if m.text.strip() != d.get("verify_code",""): await m.answer("❌ Неверный код. Попробуй ещё раз:"); return
    await m.answer(
        "🔑 **Пароль**\n\n"
        "Выбери способ:\n\n"
        "1️⃣ **Сгенерировать** — бот создаст пароль и сохранит его\n"
        "2️⃣ **Ввести свой** — ⚠️ пароль будет виден администратору сервера\n"
        "3️⃣ **Не сохранять** — бот будет спрашивать пароль при каждом входе\n\n"
        "Отправь **1**, **2** или **3**:",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_password_choice)
@dp.message(LoginStates.waiting_credentials)
async def login_cred(m: types.Message, state: FSMContext):
    p = m.text.strip().split(None, 1)
    if len(p) != 2: await m.answer("❌ Введи email и пароль через пробел"); return
    email, pw = p[0].strip(), p[1].strip()
    if f"@{DOMAIN}" not in email: await m.answer(f"❌ Только @{DOMAIN}"); return
    st = await m.answer("🔄 Проверяю...")
    try:
        im = imaplib.IMAP4(IMAP_HOST, IMAP_PORT); im.starttls(); im.login(email, pw); im.logout()
    except Exception as e:
        await st.edit_text(f"❌ {str(e)[:80]}"); await state.clear(); return
    set_user(m.from_user.id, {"email":email,"password":pw,"backup":"","created_at":datetime.now().strftime("%Y-%m-%d %H:%M"),"tg_username":m.from_user.username or ""})
    await st.edit_text(f"✅ **Вошёл!**\n📧 `{email}`\n\n📥 /inbox", parse_mode="Markdown", reply_markup=main_kb())
    await state.clear()

# Inline

@dp.callback_query(lambda c: c.data == "inbox")
async def cb_inbox(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    if not u: await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb()); await cb.answer(); return
    if not u.get("password"): await cb.message.edit_text("🔐 **Пароль не сохранён.**\n/login — войти", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])); await cb.answer(); return
    msgs = fetch_mails(u["email"], u["password"])
    u["last_emails"] = msgs; set_user(cb.from_user.id, u)
    if not msgs or "error" in msgs[0]: await cb.message.edit_text("📭 Пусто.", reply_markup=main_kb()); await cb.answer(); return
    await cb.message.edit_text(f"📥 **Входящие** ({len(msgs)}):", parse_mode="Markdown", reply_markup=inbox_kb(msgs))
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("read_"))
async def cb_read(cb: types.CallbackQuery):
    uid = cb.data.split("_",1)[1]; u = get_user(cb.from_user.id)
    if not u: await cb.answer("Нет доступа"); return
    ed = next((e for e in u.get("last_emails",[]) if str(e.get("uid"))==uid), None)
    if not ed: await cb.message.edit_text("❌ Не найдено"); await cb.answer(); return
    t = f"✉️ **{ed.get('subject','')}**\n\n👤 {ed.get('from','?')}\n📅 {ed.get('date','')[:25]}\n\n{ed.get('body','')[:1000]}"
    k = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Ответить", callback_data=f"reply_{uid}")],[InlineKeyboardButton(text="◀️", callback_data="inbox")]])
    await cb.message.edit_text(t, parse_mode="Markdown", reply_markup=k); await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("reply_"))
async def cb_reply(cb: types.CallbackQuery, state: FSMContext):
    uid = cb.data.split("_",1)[1]; u = get_user(cb.from_user.id)
    if not u: await cb.answer("Нет доступа"); return
    ed = next((e for e in u.get("last_emails",[]) if str(e.get("uid"))==uid), None)
    if not ed: await cb.answer("Не найдено"); return
    await state.update_data(reply_to=ed)
    await cb.message.edit_text(f"📝 **Ответ:** {ed.get('subject','')[:40]}\n\nТекст:\n/cancel — отмена", parse_mode="Markdown")
    await state.set_state(MailStates.waiting_reply_text); await cb.answer()

@dp.message(MailStates.waiting_reply_text)
async def reply_txt(m: types.Message, state: FSMContext):
    d = await state.get_data(); rt = d.get("reply_to",{}); u = get_user(m.from_user.id)
    if not u or not rt: await m.answer("❌ Ошибка"); await state.clear(); return
    st = await m.answer("📤 Отправляю...")
    try:
        msg = MIMEText(m.text, "plain", "utf-8")
        msg["From"], msg["To"], msg["Subject"] = u["email"], rt.get("from",""), f"Re: {rt.get('subject','')}"
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT); s.starttls(); s.login(u["email"], u["password"]); s.send_message(msg); s.quit()
        await st.edit_text("✅ Отправлено!", reply_markup=main_kb())
    except Exception as e: await st.edit_text(f"❌ {str(e)[:80]}", reply_markup=main_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "compose")
async def cb_compose(cb: types.CallbackQuery, state: FSMContext):
    u = get_user(cb.from_user.id)
    if not u: await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb()); await cb.answer(); return
    if not u.get("password"): await cb.message.edit_text("🔐 **Пароль не сохранён.**\n/login — войди", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Войти", callback_data="login")]])); await cb.answer(); return
    await cb.message.edit_text("📧 **Новое письмо**\n\nEmail получателя:\n/cancel — отмена", parse_mode="Markdown")
    await state.set_state(MailStates.waiting_send_to); await cb.answer()

@dp.message(MailStates.waiting_send_to)
async def snd_to(m: types.Message, state: FSMContext):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", m.text.strip()): await m.answer("❌ Непохоже на email"); return
    await state.update_data(send_to=m.text.strip()); await m.answer("📝 Тема письма:\n/cancel — отмена")
    await state.set_state(MailStates.waiting_send_subject)

@dp.message(MailStates.waiting_send_subject)
async def snd_subj(m: types.Message, state: FSMContext):
    await state.update_data(send_subject=m.text.strip()); await m.answer("✏️ Текст:\n/cancel — отмена")
    await state.set_state(MailStates.waiting_send_body)

@dp.message(MailStates.waiting_send_body)
async def snd_body(m: types.Message, state: FSMContext):
    d = await state.get_data(); u = get_user(m.from_user.id)
    if not u: await m.answer("❌ Нет доступа"); await state.clear(); return
    st = await m.answer("📤 Отправляю...")
    try:
        msg = MIMEText(m.text, "plain", "utf-8")
        msg["From"], msg["To"], msg["Subject"] = u["email"], d.get("send_to",""), d.get("send_subject","")
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT); s.starttls(); s.login(u["email"], u["password"]); s.send_message(msg); s.quit()
        await st.edit_text(f"✅ Отправлено на `{d.get('send_to','')}`!", parse_mode="Markdown", reply_markup=main_kb())
    except Exception as e: await st.edit_text(f"❌ {str(e)[:80]}", reply_markup=main_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu")
async def cb_menu(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    t = f"👋 **Меню**\n`{u['email']}`" if u else "👋 **Меню**"
    await cb.message.edit_text(t, parse_mode="Markdown", reply_markup=main_kb()); await cb.answer()

@dp.callback_query(lambda c: c.data == "mybox")
async def cb_mybox(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    if not u: await cb.message.edit_text("❌ Нет доступа", reply_markup=noacc_kb()); await cb.answer(); return
    usage = get_mailbox_usage(u["email"])
    extra = ""
    if usage:
        bar = "🟩" * max(0, min(10, int(usage[4] / 10))) + "⬜" * max(0, 10 - min(10, int(usage[4] / 10)))
        extra = f"\n📦 **{usage[3]}**\n{bar} `{usage[4]}%` (**{usage[1]}**)"
    await cb.message.edit_text(f"👤 **Мой ящик**\n\n📧 `{u['email']}`\n📅 {u.get('created_at','?')}{extra}\n\n🔗 https://mail.ramadoit.ru/", parse_mode="Markdown", reply_markup=main_kb())
    await cb.answer()

async def delete_msg_later(msg, text):
    await asyncio.sleep(600)
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except:
        pass


async def do_create_account(msg, state, email, name, backup, password, store_password=True):
    ok, res = create_account(email, password, backup)
    if not ok:
        await msg.answer(f"\u274c {res}")
        await state.clear()
        return
    codes = [binascii.hexlify(os.urandom(16)).decode() for _ in range(3)]
    try:
        inv_path = "/etc/dovecot/invites.json"
        if os.path.exists(inv_path):
            with open(inv_path) as f:
                inv = json.load(f)
        else:
            inv = {}
        for code in codes:
            inv[code] = {"email": email, "created_by": email, "used": False, "used_by": None,
                         "created_at": datetime.now().isoformat(), "used_at": None}
        with open(inv_path, "w") as f:
            json.dump(inv, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: invite codes not saved: {e}")
    if store_password:
        set_user(msg.from_user.id, {"email": email, "password": password, "backup": backup,
                                     "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                     "tg_username": msg.from_user.username or ""})
    else:
        set_user(msg.from_user.id, {"email": email, "password": "", "backup": backup,
                                     "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                     "tg_username": msg.from_user.username or "",
                                     "store_password": False})
    full = (f"Mailbox {email} created!\n\nEmail: {email}\nPassword: {password}\n\n"
            f"Webmail: https://mail.ramadoit.ru/\n\n=== CLIENTS ===\n"
            f"Server: mail.ramadoit.ru\nIMAP: 993 (SSL) or 143 (STARTTLS)\n"
            f"POP3: 995 (SSL) or 110 (STARTTLS)\nSMTP: 587 (STARTTLS)\nUser: Full email\n\n"
            f"=== LIMITS ===\n300 MB\n\n=== PRIVACY ===\nLogs: OFF\nEncryption: ON\n\n"
            f"=== INVITATION CODES ===\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(codes))
            + "\n\n-- mail.ramadoit.ru")
    short = (f"Mailbox {email} created!\n\nEmail: {email}\nPassword: {password}\n\n"
             f"Web: https://mail.ramadoit.ru/\nLimit: 300 MB\nLogs: OFF\nEncryption: ON\n\n"
             f"Invitation codes:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(codes)))
    send_email(email, f"Your mailbox {email} created", full)
    send_email(backup, f"Mailbox {email} on ramadoit.ru created", short)
    pw_notice = "\n\U0001f511 \u041f\u0430\u0440\u043e\u043b\u044c \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d \u0432 \u0431\u043e\u0442\u0435." if store_password else "\n\U0001f511 \u041f\u0430\u0440\u043e\u043b\u044c \u041d\u0415 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 /login \u043f\u0440\u0438 \u043a\u0430\u0436\u0434\u043e\u043c \u0432\u0445\u043e\u0434\u0435."
    sent_msg = await msg.answer(
        f"\u2705 **\u042f\u0449\u0438\u043a \u0441\u043e\u0437\u0434\u0430\u043d!**\n\n\U0001f4e7 `{email}`\n\U0001f511 `{password}`\n\n\U0001f517 https://mail.ramadoit.ru/\n\n"
        f"**\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u043a\u043b\u0438\u0435\u043d\u0442\u043e\u0432:**\nIMAP: `993 (SSL)`\nSMTP: `587 (STARTTLS)`\nUser: \u043f\u043e\u043b\u043d\u044b\u0439 email\n\n"
        f"**3 \u043a\u043e\u0434\u0430 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u044f:**\n" + "\n".join(f"`{c}`" for c in codes)
        + f"\n\n\u26a0\ufe0f \u041f\u0430\u0440\u043e\u043b\u044c \u043f\u043e\u043a\u0430\u0437\u0430\u043d \u043e\u0434\u0438\u043d \u0440\u0430\u0437. \u041e\u043d \u0431\u0443\u0434\u0435\u0442 \u0443\u0434\u0430\u043b\u0451\u043d \u0447\u0435\u0440\u0435\u0437 10 \u043c\u0438\u043d\u0443\u0442." + pw_notice
        + "\n\U0001f4e5 /inbox \u2014 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043f\u043e\u0447\u0442\u0443",
        parse_mode="Markdown", reply_markup=main_kb())
    asyncio.create_task(delete_msg_later(sent_msg,
        "\u231b\ufe0f **\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u043e \u0434\u043b\u044f \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438**\n\n\u041f\u0430\u0440\u043e\u043b\u044c \u0431\u044b\u043b \u043f\u043e\u043a\u0430\u0437\u0430\u043d \u0432\u044b\u0448\u0435. \u0415\u0441\u043b\u0438 \u043d\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u2014 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 /mybox \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c \u043f\u043e\u0447\u0442\u0443."))
    await state.clear()


@dp.message(Command("logout"))
async def cmd_logout(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("\u274c **\u0422\u044b \u043d\u0435 \u0437\u0430\u043b\u043e\u0433\u0438\u043d\u0435\u043d.**\n\n\U0001f511 /register \u2014 \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u044f\u0449\u0438\u043a\n\U0001f510 /login \u2014 \u0432\u043e\u0439\u0442\u0438", parse_mode="Markdown")
        return
    email = user["email"]
    user["password"] = ""
    user["logged_out"] = True
    set_user(message.from_user.id, user)
    await state.clear()
    await message.answer(
        f"\u2705 **\u0412\u044b\u0448\u0435\u043b \u0438\u0437 \u044f\u0449\u0438\u043a\u0430**\n\n\U0001f4e7 `{email}` \u2014 \u0437\u0430\u043f\u043e\u043c\u043d\u0435\u043d\n\U0001f511 \u041f\u0430\u0440\u043e\u043b\u044c \u0443\u0434\u0430\u043b\u0451\u043d \u0438\u0437 \u0431\u043e\u0442\u0430\n\n"
        f"\u041f\u043e\u0432\u0442\u043e\u0440\u043d\u043e \u0437\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u043e\u0432\u0430\u0442\u044c\u0441\u044f \u043d\u0435\u043b\u044c\u0437\u044f \u2014 1 Telegram = 1 \u043f\u043e\u0447\u0442\u0430.\n"
        f"\n\U0001f510 /login \u2014 \u0432\u043e\u0439\u0442\u0438 \u0441\u043d\u043e\u0432\u0430\n\U0001f511 /register \u2014 \u0435\u0441\u043b\u0438 \u0445\u043e\u0447\u0435\u0448\u044c \u0441\u043c\u0435\u043d\u0438\u0442\u044c \u044f\u0449\u0438\u043a (\u0443\u0434\u0430\u043b\u0438\u0442 \u0441\u0442\u0430\u0440\u044b\u0439)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\U0001f510 \u0412\u043e\u0439\u0442\u0438", callback_data="login")],
            [InlineKeyboardButton(text="\U0001f511 \u041d\u043e\u0432\u044b\u0439 \u044f\u0449\u0438\u043a", callback_data="force_register")]]))


@dp.callback_query(lambda c: c.data == "logout")
async def cb_logout(cb: types.CallbackQuery, state: FSMContext):
    user = get_user(cb.from_user.id)
    if not user:
        await cb.message.edit_text("\u274c \u041d\u0435 \u0437\u0430\u043b\u043e\u0433\u0438\u043d\u0435\u043d", reply_markup=noacc_kb())
        await cb.answer()
        return
    email = user["email"]
    user["password"] = ""
    user["logged_out"] = True
    set_user(cb.from_user.id, user)
    await state.clear()
    await cb.message.edit_text(
        f"\u2705 **\u0412\u044b\u0448\u0435\u043b \u0438\u0437 \u044f\u0449\u0438\u043a\u0430**\n\n\U0001f4e7 `{email}` \u2014 \u0437\u0430\u043f\u043e\u043c\u043d\u0435\u043d\n\U0001f511 \u041f\u0430\u0440\u043e\u043b\u044c \u0443\u0434\u0430\u043b\u0451\u043d\n\n"
        f"1 Telegram = 1 \u043f\u043e\u0447\u0442\u0430 \u2014 \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u043e \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f.\n"
        f"\U0001f510 /login \u2014 \u0432\u043e\u0439\u0442\u0438 \u0441\u043d\u043e\u0432\u0430",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\U0001f510 \u0412\u043e\u0439\u0442\u0438", callback_data="login")]]))
    await cb.answer()


@dp.callback_query(lambda c: c.data == "force_register")
async def cb_force_register(cb: types.CallbackQuery, state: FSMContext):
    user = get_user(cb.from_user.id)
    if not user:
        await cb_reg_or_login(cb, state)
        return
    await cb.message.edit_text(
        "\u26a0\ufe0f **\u0421\u043c\u0435\u043d\u0430 \u044f\u0449\u0438\u043a\u0430**\n\n"
        f"\u0421\u0435\u0439\u0447\u0430\u0441 \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d: `{user['email']}`\n\n"
        "\u0415\u0441\u043b\u0438 \u0441\u043e\u0437\u0434\u0430\u0448\u044c \u043d\u043e\u0432\u044b\u0439 \u044f\u0449\u0438\u043a, \u0441\u0442\u0430\u0440\u044b\u0439 \u043e\u0441\u0442\u0430\u043d\u0435\u0442\u0441\u044f \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435, "
        "\u043d\u043e \u043f\u0440\u0438\u0432\u044f\u0437\u043a\u0430 \u043a Telegram \u0441\u043c\u0435\u043d\u0438\u0442\u0441\u044f.\n\n"
        "\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u2705 \u0414\u0430, \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u043d\u043e\u0432\u044b\u0439", callback_data="confirm_force_reg")],
            [InlineKeyboardButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0430", callback_data="menu")]]))
    await cb.answer()


@dp.callback_query(lambda c: c.data == "confirm_force_reg")
async def cb_confirm_force_reg(cb: types.CallbackQuery, state: FSMContext):
    tg_id = str(cb.from_user.id)
    d = load_data()
    if tg_id in d["users"]:
        del d["users"][tg_id]
        save_data(d)
    await cb.message.edit_text(
        "\U0001f511 **\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043d\u043e\u0432\u043e\u0433\u043e \u044f\u0449\u0438\u043a\u0430**\n\n"
        "\u0412\u0432\u0435\u0434\u0438 \u0436\u0435\u043b\u0430\u0435\u043c\u043e\u0435 \u0438\u043c\u044f:\n`john` \u2192 `john@ramadoit.ru`\n\n"
        "\u2022 > 2 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432\n\u2022 a-z, 0-9, \u0442\u043e\u0447\u043a\u0430, \u0434\u0435\u0444\u0438\u0441",
        parse_mode="Markdown")
    await state.set_state(RegisterStates.waiting_for_name)
    await cb.answer()



async def main():
    logger.info(f"Starting MailBot... IMAP: {IMAP_HOST}:{IMAP_PORT} Domain: {DOMAIN}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())