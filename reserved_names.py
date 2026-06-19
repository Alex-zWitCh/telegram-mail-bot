# Зарезервированные имена почтовых ящиков
# Нельзя зарегистрировать: < 3 символов, стандартные служебные имена

RESERVED_NAMES = {
    # Системные
    "root", "admin", "administrator", "system", "master", "operator",
    "postmaster", "mailer-daemon", "mailer", "daemon", "nobody",
    "hostmaster", "webmaster", "noc", "security", "ssl", "cert",
    
    # Почтовые службы
    "abuse", "spam", "mail", "email", "post", "letter", "message",
    "inbox", "sent", "draft", "trash", "junk", "spam", "archive",
    "quarantine", "newsletter", "mailing", "mailer", "mailman",
    "noreply", "no-reply", "reply", "forward", "redirect", "bounce",
    
    # Служебные
    "support", "info", "help", "contact", "feedback", "service",
    "office", "manager", "moderator", "team", "staff", "sales",
    "marketing", "privacy", "legal", "dmca", "complaint",
    
    # Сеть/Домен
    "www", "ftp", "api", "dns", "mx", "smtp", "imap", "pop3",
    "pop", "vps", "vpn", "proxy", "relay", "server", "host",
    "ns1", "ns2", "ns3", "ns4", "domain", "registrar",
    
    # Разное
    "test", "demo", "trial", "fake", "guest", "temp", "tmp", "null",
    "none", "undefined", "empty", "delete", "remove", "stop",
    "unsubscribe", "user", "bot", "robot", "auto", "automatic",
    "blog", "forum", "chat", "shop", "store", "payment", "billing",
    "invoice", "receipt", "fraud", "survey",
    
    # Статистика/мониторинг
    "stats", "stat", "monitor", "monitoring", "alert", "alerts",
    "status", "uptime", "health", "ping",
    
    # Русские
    "админ", "администратор", "инфо", "почта", "письмо",
    "спам", "поддержка", "support1", "info1", "abuse1",
}

def is_reserved(name: str) -> bool:
    """Проверяет, зарезервировано ли имя."""
    name_lower = name.lower().strip()
    
    # Короче 3 символов
    if len(name_lower) < 3:
        return True
    
    # В списке зарезервированных
    if name_lower in RESERVED_NAMES:
        return True
    
    return False
