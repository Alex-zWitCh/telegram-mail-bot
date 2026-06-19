# 📧 MailBot — Telegram Email Manager

A Telegram bot for managing email mailboxes on your own domain via **Dovecot + Postfix**.

Create mailboxes, read incoming emails, send replies, check quota usage — all from Telegram.

## ✨ Features

| Command | Description |
|---------|-------------|
| `/start` | Main menu |
| `/register` | Create a new mailbox |
| `/login` | Log into an existing mailbox |
| `/inbox` | View inbox (last 5 messages) |
| `/send` | Compose a new email |
| `/mybox` | Mailbox info + disk usage |
| `/logout` | Log out, remove password from bot |
| `/cancel` or `/exit` | Cancel current operation |

### 🔑 Registration
- Pick a name → availability check
- Provide a backup email → receive a 6-digit verification code
- **3 password storage options:**
  1. **Auto-generate** — bot creates and stores the password
  2. **Custom password** — ⚠️ visible to the server administrator
  3. **No storage** — password sent via email only, use `/login` each time
- Password shown once; after 10 minutes the message is replaced with a privacy notice
- 3 invitation codes issued for inviting others

### 📥 Mail
- Read inbox (last 5 emails)
- View subject, sender, date, body
- Reply to messages
- Compose new emails (To → Subject → Body)

### 👤 Profile
- Email address, creation date
- **Usage progress bar** 🟩🟩⬜⬜⬜ (default quota: 300 MB)
- IMAP/SMTP connection settings

### 🚪 Logout
- Removes the password from the bot's memory
- Email stays linked (1 Telegram account = 1 email)
- Re-enter via `/login`

### 🔐 Security
- Emails encrypted on disk (Dovecot mail_crypt)
- Logging disabled
- Password automatically removed from message after 10 minutes
- `/cancel` aborts any input flow

## 🧱 Requirements

- **OS:** Linux (Ubuntu 22.04+ / Debian 12+)
- **Python:** 3.10+
- **Mail server:** Dovecot (IMAP) + Postfix (SMTP) running on the same host
- **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)

### Recommended Mail Server Setup

- Dovecot: IMAP on 127.0.0.1:143 (STARTTLS) or 993 (SSL)
- Postfix: Submission on 127.0.0.1:587 (STARTTLS)
- Dovecot users file: `/etc/dovecot/users` (format: `email:{BLF-CRYPT}hash:uid:gid::/maildir::`)
- Maildir: `/var/mail/vhosts/{domain}/{user}/`
- Quota: 300 MB (configurable)

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USER/telegram-mail-bot.git /opt/mailbot
cd /opt/mailbot

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cat > .env << 'EOF'
MAILBOT_TOKEN=your_telegram_bot_token
MAIL_DOMAIN=your-domain.com
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=your_smtp_password
MAIL_QUOTA=300
EOF

# 5. Run
python3 bot.py
```

### 🐳 Systemd Service

```ini
# /etc/systemd/system/mailbot.service
[Unit]
Description=MailBot Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mailbot
EnvironmentFile=/opt/mailbot/.env
ExecStart=/opt/mailbot/venv/bin/python3 /opt/mailbot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now mailbot
```

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAILBOT_TOKEN` | — | **Telegram Bot token (required)** |
| `MAIL_DOMAIN` | `example.com` | Email domain |
| `SMTP_USER` | `noreply@{DOMAIN}` | SMTP user for sending notifications |
| `SMTP_PASSWORD` | `""` | SMTP password for notifications |
| `IMAP_HOST` | `127.0.0.1` | IMAP server |
| `IMAP_PORT` | `143` | IMAP port |
| `SMTP_HOST` | `127.0.0.1` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `MAIL_QUOTA` | `300` | Mailbox quota in MB |
| `DOVECOT_USER_FILE` | `/etc/dovecot/users` | Dovecot users file |
| `DOVECOT_EXTRA_FILE` | `/etc/dovecot/user-extra.conf` | Backup email mapping file |
| `MAIL_DIR` | `/var/mail/vhosts` | Maildir parent directory |
| `DATA_FILE` | `/opt/mailbot/data.json` | Bot data storage file |
| `INVITES_FILE` | `/etc/dovecot/invites.json` | Invitation codes file |

## 📁 Project Structure

```
mailbot/
├── bot.py              # Main bot code
├── reserved_names.py   # Reserved/resricted mailbox names
├── requirements.txt    # Python dependencies
├── .env.example        # Sample configuration
├── .gitignore
├── LICENSE
└── README.md
```

## 🔒 Security Notes

- The SMTP account used for sending notifications should have **restricted permissions** (send only)
- User passwords are stored in `data.json` — **restrict file access** (`chmod 600`)
- Dovecot should use `BLF-CRYPT` or a stronger hash algorithm
- Enable `mail_crypt` in production for at-rest email encryption
- Keep aiogram and all dependencies up to date

## 🧪 Testing

```bash
# Syntax check
python3 -m py_compile bot.py

# Run in debug mode
MAILBOT_TOKEN=test:token python3 bot.py
```

## 📄 License

MIT
