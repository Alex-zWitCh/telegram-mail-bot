# 📧 MailBot — Telegram Email Manager

> **🇬🇧** A Telegram bot for managing email mailboxes on your own domain via Dovecot + Postfix.
> **🇷🇺** Telegram-бот для управления почтовыми ящиками на собственном домене через Dovecot + Postfix.

Create mailboxes, read incoming emails, send replies, check quota usage — all from Telegram.
Создавай ящики, читай входящие, отвечай на письма, следи за заполнением — прямо в Telegram.

---

## ✨ Features / Возможности

| Command | 🇬🇧 Description | 🇷🇺 Описание |
|---------|----------------|--------------|
| `/start` | Main menu | Главное меню |
| `/register` | Create a new mailbox | Создать новый почтовый ящик |
| `/login` | Log into an existing mailbox | Войти в существующий ящик |
| `/inbox` | View inbox (last 5 messages) | Просмотреть входящие |
| `/send` | Compose a new email | Написать новое письмо |
| `/mybox` | Mailbox info + disk usage | Информация о ящике + заполненность |
| `/logout` | Log out, remove password from bot | Выйти, удалить пароль из бота |
| `/cancel` or `/exit` | Cancel current operation | Отменить текущее действие |

---

### 🔑 Registration / Регистрация

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| Pick a name → availability check | Выбор имени → проверка на занятость |
| Provide a backup email → receive 6-digit code | Запрос резервного email → код подтверждения |
| **3 password storage options** | **3 варианта хранения пароля** |
| ① **Auto-generate** — bot creates and stores the password | ① **Автогенерация** — бот создаёт и сохраняет пароль |
| ② **Custom password** — ⚠️ visible to server admin | ② **Свой пароль** — ⚠️ виден администратору |
| ③ **No storage** — password via email only, use `/login` each time | ③ **Не сохранять** — пароль только в письме |
| Password auto-deleted from chat after 10 min | Пароль удаляется из чата через 10 минут |
| 3 invitation codes issued | 3 инвайт-кода для приглашения других |

---

### 📥 Mail / Почта

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| Read inbox (last 5 emails) | Чтение входящих (5 последних писем) |
| View subject, sender, date, body | Просмотр темы, отправителя, даты, тела |
| Reply to messages | Ответ на письмо |
| Compose new emails (To → Subject → Body) | Отправка новых писем (Кому → Тема → Текст) |

---

### 👤 Profile / Профиль

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| Email, creation date | Email, дата создания |
| **Usage progress bar** 🟩🟩⬜⬜⬜ (default: 300 MB) | **Прогресс-бар заполнения** 🟩🟩⬜⬜⬜ |
| IMAP/SMTP connection settings | IMAP/SMTP настройки для клиентов |

---

### 🚪 Logout / Выход

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| Removes password from bot memory | Удаляет пароль из памяти бота |
| Email stays linked (1 Telegram = 1 email) | Email остаётся привязанным |
| Re-enter via `/login` | Можно заново войти через /login |

---

### 🔐 Security / Безопасность

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| Emails encrypted on disk (Dovecot mail_crypt) | Письма шифруются на диске |
| Logging disabled | Логи отключены |
| Password auto-removed after 10 minutes | Пароль удаляется через 10 минут |
| `/cancel` aborts any input flow | `/cancel` прерывает любой ввод |

---

## 🧱 Requirements / Требования

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| **OS:** Linux (Ubuntu 22.04+ / Debian 12+) | **ОС:** Linux |
| **Python:** 3.10+ | **Python:** 3.10+ |
| **Mail server:** Dovecot (IMAP) + Postfix (SMTP) on same host | **Почтовый сервер:** Dovecot + Postfix на том же хосте |
| **Telegram Bot Token** from [@BotFather](https://t.me/BotFather) | **Токен бота** от [@BotFather](https://t.me/BotFather) |

### Recommended Mail Server Setup / Рекомендуемая конфигурация

| Параметр | Значение |
|----------|----------|
| Dovecot IMAP | 127.0.0.1:143 (STARTTLS) or 993 (SSL) |
| Postfix Submission | 127.0.0.1:587 (STARTTLS) |
| Users file | `/etc/dovecot/users` (`email:{BLF-CRYPT}hash:uid:gid::/maildir::`) |
| Maildir | `/var/mail/vhosts/{domain}/{user}/` |
| Quota | 300 MB (configurable / настраивается) |

---

## 🚀 Quick Start / Быстрая установка

```bash
# 1. Clone / Клонировать
git clone https://github.com/YOUR_USER/telegram-mail-bot.git /opt/mailbot
cd /opt/mailbot

# 2. Virtual environment / Виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies / Установить зависимости
pip install -r requirements.txt

# 4. Configure / Настроить
cat > .env << 'EOF'
MAILBOT_TOKEN=your_telegram_bot_token
MAIL_DOMAIN=your-domain.com
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=your_smtp_password
MAIL_QUOTA=300
EOF

# 5. Run / Запустить
python3 bot.py
```

### 🐳 Systemd Service / Сервис

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

---

## 🔧 Environment Variables / Переменные окружения

| Variable | Default | 🇬🇧 Description | 🇷🇺 Описание |
|----------|---------|----------------|--------------|
| `MAILBOT_TOKEN` | — | **Telegram Bot token (required)** | **Токен Telegram бота (обязательно)** |
| `MAIL_DOMAIN` | `example.com` | Email domain | Домен email |
| `SMTP_USER` | `noreply@{DOMAIN}` | SMTP user for notifications | Юзер для отправки уведомлений |
| `SMTP_PASSWORD` | `""` | SMTP password for notifications | Пароль для отправки уведомлений |
| `IMAP_HOST` | `127.0.0.1` | IMAP server | IMAP сервер |
| `IMAP_PORT` | `143` | IMAP port | IMAP порт |
| `SMTP_HOST` | `127.0.0.1` | SMTP server | SMTP сервер |
| `SMTP_PORT` | `587` | SMTP port | SMTP порт |
| `MAIL_QUOTA` | `300` | Mailbox quota in MB | Квота ящика в MB |
| `DOVECOT_USER_FILE` | `/etc/dovecot/users` | Dovecot users file | Файл пользователей Dovecot |
| `DOVECOT_EXTRA_FILE` | `/etc/dovecot/user-extra.conf` | Backup email mapping | Файл backup-email |
| `MAIL_DIR` | `/var/mail/vhosts` | Maildir parent directory | Maildir родительская папка |
| `DATA_FILE` | `/opt/mailbot/data.json` | Bot data storage file | Файл данных бота |
| `INVITES_FILE` | `/etc/dovecot/invites.json` | Invitation codes file | Файл инвайт-кодов |

---

## 📁 Project Structure / Структура проекта

```
mailbot/
├── bot.py              # 🇬🇧 Main bot code         🇷🇺 Основной код бота
├── reserved_names.py   # 🇬🇧 Reserved names list   🇷🇺 Список запрещённых имён
├── requirements.txt    # 🇬🇧 Python dependencies   🇷🇺 Зависимости
├── .env.example        # 🇬🇧 Sample config         🇷🇺 Пример конфига
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔒 Security Notes / Замечания по безопасности

| 🇬🇧 | 🇷🇺 |
|-----|-----|
| SMTP account should have **send-only** permissions | SMTP-учётка должна иметь права только на отправку |
| Restrict access to `data.json` (`chmod 600`) | Ограничьте доступ к `data.json` |
| Dovecot should use `BLF-CRYPT` or stronger | Dovecot должен использовать `BLF-CRYPT` |
| Enable `mail_crypt` in production | Включите `mail_crypt` в продакшене |
| Keep aiogram and dependencies updated | Обновляйте aiogram и зависимости |

---

## 🧪 Testing / Тестирование

```bash
# Syntax check / Проверка синтаксиса
python3 -m py_compile bot.py

# Debug mode / Режим отладки
MAILBOT_TOKEN=test:token python3 bot.py
```

---

## 📄 License / Лицензия

MIT
