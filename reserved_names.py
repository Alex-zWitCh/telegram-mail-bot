# Reserved mailbox names
# Cannot register: < 3 chars, standard service names, etc.

RESERVED_NAMES = {
    # System
    "root", "admin", "administrator", "system", "master", "operator",
    "postmaster", "mailer-daemon", "mailer", "daemon", "nobody",
    "hostmaster", "webmaster", "noc", "security", "ssl", "cert",
    
    # Mail services
    "abuse", "spam", "mail", "email", "post", "letter", "message",
    "inbox", "sent", "draft", "trash", "junk", "spam", "archive",
    "quarantine", "newsletter", "mailing", "mailer", "mailman",
    "noreply", "no-reply", "reply", "forward", "redirect", "bounce",
    
    # Service
    "support", "info", "help", "contact", "feedback", "service",
    "office", "manager", "moderator", "team", "staff", "sales",
    "marketing", "privacy", "legal", "dmca", "complaint",
    
    # Network/Domain
    "www", "ftp", "api", "dns", "mx", "smtp", "imap", "pop3",
    "pop", "vps", "vpn", "proxy", "relay", "server", "host",
    "ns1", "ns2", "ns3", "ns4", "domain", "registrar",
    
    # Misc
    "test", "demo", "trial", "fake", "guest", "temp", "tmp", "null",
    "none", "undefined", "empty", "delete", "remove", "stop",
    "unsubscribe", "user", "bot", "robot", "auto", "automatic",
    "blog", "forum", "chat", "shop", "store", "payment", "billing",
    "invoice", "receipt", "fraud", "survey",
    
    # Stats/Monitoring
    "stats", "stat", "monitor", "monitoring", "alert", "alerts",
    "status", "uptime", "health", "ping",
}

def is_reserved(name: str) -> bool:
    """Check if a name is reserved."""
    name_lower = name.lower().strip()
    
    # Shorter than 3 characters
    if len(name_lower) < 3:
        return True
    
    # In the reserved list
    if name_lower in RESERVED_NAMES:
        return True
    
    return False
