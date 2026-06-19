# 📧 MailBot — Telegram Email Manager

Telegram-бот для управления почтовыми ящиками на собственном домене через **Dovecot + Postfix**.

## ✨ Возможности

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/register` | Создать новый почтовый ящик |
| `/login` | Войти в существующий ящик |
| `/inbox` | Просмотреть входящие (последние 5) |
| `/send` | Написать новое письмо |
| `/mybox` | Информация о ящике + заполненность |
| `/logout` | Выйти, удалить пароль из бота |
| `/cancel` or `/exit` | Отменить текущее действие |

### 🔑 Регистрация
- Выбор имени → проверка на занятость
- Запрос резервного email → отправка 6-значного кода
- **3 варианта хранения пароля:**
  1. **Автогенерация** — бот создаёт и сохраняет пароль
  2. **Свой пароль** — ⚠️ виден администратору сервера
  3. **Не сохранять** — пароль только в письме, /login при каждом входе
- Пароль показывается 1 раз, через 10 минут сообщение заменяется на уведомление о конфиденциальности
- Выдаются 3 инвайт-кода для приглашения других

### 📥 Почта
- Чтение входящих (5 последних писем)
- Просмотр темы, отправителя, даты, тела
- Ответ на письмо
- Отправка новых писем (To → Subject → Body)

### 👤 Профиль
- Email, дата создания
- **Прогресс-бар заполнения** 🟩🟩⬜⬜⬜ (квота: 300 MB по умолчанию)
- IMAP/SMTP настройки

### 🚪 Logout
- Удаляет пароль из памяти бота
- Email остаётся привязанным (1 Telegram = 1 email)
- Можно заново войти через /login

### 🔐 Безопасность
- Письма шифруются на диске (Dovecot mail_crypt)
- Логи отключены
- Пароль автоматически удаляется из сообщения через 10 минут
- /cancel прерывает любой ввод

## 🧱 Требования

- **OS:** Linux (Ubuntu 22.04+/Debian 12+)
- **Python:** 3.10+
- **Mail server:** Dovecot (IMAP) + Postfix (SMTP) — работающие на том же хосте
- **Telegram Bot Token** — от [@BotFather](https://t.me/BotFather)

### Рекомендуемая конфигурация почтового сервера

- Dovecot: IMAP на 127.0.0.1:143 (STARTTLS) или 993 (SSL)
- Postfix: Submission на 127.0.0.1:587 (STARTTLS)
- Dovecot users file: `/etc/dovecot/users` (формат: `email:{BLF-CRYPT}hash:uid:gid::/maildir::`)
- Maildir: `/var/mail/vhosts/{domain}/{user}/`
- Dovecot quota: 300 MB (настраивается)

## 🚀 Быстрая установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/YOUR_USER/mailbot.git /opt/mailbot
cd /opt/mailbot

# 2. Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить .env
cat > .env << 'EOF'
MAILBOT_TOKEN=your_telegram_bot_token
MAIL_DOMAIN=your-domain.com
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=your_smtp_password
MAIL_QUOTA=300
EOF

# 5. Запустить
python3 bot.py
```

### 🐳 Systemd service

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

## 🔧 Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `MAILBOT_TOKEN` | — | **Токен Telegram бота (обязательно)** |
| `MAIL_DOMAIN` | `example.com` | Домен email |
| `SMTP_USER` | `noreply@{DOMAIN}` | Юзер для отправки уведомлений |
| `SMTP_PASSWORD` | `""` | Пароль для отправки уведомлений |
| `IMAP_HOST` | `127.0.0.1` | IMAP сервер |
| `IMAP_PORT` | `143` | IMAP порт |
| `SMTP_HOST` | `127.0.0.1` | SMTP сервер |
| `SMTP_PORT` | `587` | SMTP порт |
| `MAIL_QUOTA` | `300` | Квота ящика в MB |
| `DOVECOT_USER_FILE` | `/etc/dovecot/users` | Файл пользователей Dovecot |
| `DOVECOT_EXTRA_FILE` | `/etc/dovecot/user-extra.conf` | Файл backup-email |
| `MAIL_DIR` | `/var/mail/vhosts` | Maildir родительская папка |
| `DATA_FILE` | `/opt/mailbot/data.json` | Файл данных бота |
| `INVITES_FILE` | `/etc/dovecot/invites.json` | Файл инвайт-кодов |

## 📁 Структура проекта

```
mailbot/
├── bot.py              # Основной код бота
├── reserved_names.py   # Список запрещённых имён
├── requirements.txt    # Зависимости
├── .env.example        # Пример конфига
├── .gitignore
├── LICENSE
└── README.md
```

## 🔒 Примечания по безопасности

- SMTP-учётка для отправки уведомлений должна иметь **ограниченные права** (только send)
- Пароли пользователей хранятся в `data.json` — **ограничьте доступ** к файлу (`chmod 600`)
- Dovecot должен использовать `BLF-CRYPT` или более сильный хеш
- Для продакшена включите `mail_crypt` для шифрования писем на диске
- Регулярно обновляйте aiogram и зависимости

## 🧪 Тестирование

```bash
# Проверка синтаксиса
python3 -m py_compile bot.py

# Запуск в режиме отладки
MAILBOT_TOKEN=test:token python3 bot.py
```

## 📄 Лицензия

MIT
