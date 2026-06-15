from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


EMAIL_RE = re.compile(r"(?<![\w.-])[\w.+-]{2,64}@[\w.-]{2,120}\.[A-Za-z]{2,12}(?![\w.-])")
QQ_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:QQ|qq|企鹅|扣扣|q号|Q号)[ \t]*(?:[:：])?[ \t]*([1-9]\d{4,11})"
)
WECHAT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:微信号?|微\s*信|加微|加v|加V|vx|VX|v信|V信|wechat|WeChat|wx|WX)"
    r"[ \t]*(?:[:：])?[ \t]*([A-Za-z][A-Za-z0-9_-]{5,19})"
)
TELEGRAM_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:telegram|Telegram|TG|tg|电报)[ \t]*(?:[:：@])?[ \t]*@?([A-Za-z0-9_]{5,32})"
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
URL_RE = re.compile(r"https?://[^\s，。；;、)）\]]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(
    r"(?<![@\w.-])((?:[A-Za-z0-9][A-Za-z0-9-]{0,62}\.)+(?:com|cn|net|io|ai|co|org|me|dev|app|xyz))(?![\w.-])",
    re.IGNORECASE,
)
COMPANY_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,40}"
    r"(?:公司|工作室|团队|科技|网络|贸易|电商|传媒|数据|运营|出海))"
)

LOW_CONFIDENCE_TOKENS = {
    "example",
    "test",
    "admin",
    "root",
    "none",
    "null",
    "unknown",
    "wechat",
    "weixin",
    "telegram",
    "contact",
    "username",
    "abcdef",
    "abc123",
    "music",
    "resql",
}
IGNORED_EMAIL_DOMAINS = {"example.com", "test.com", "localhost"}
EMAIL_CREDENTIAL_LOCAL_PARTS = {
    "user",
    "username",
    "pass",
    "password",
    "proxy",
    "login",
    "account",
    "token",
    "apikey",
    "api_key",
    "maintainers",
    "maintainer",
    "security",
    "abuse",
    "postmaster",
}
EMAIL_CREDENTIAL_DOMAINS = {
    "gw.dataimpulse.com",
    "geo.iproyal.com",
}
URL_USERINFO_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@:]+(?::[^\s/@]+)?@[^\s，。；;、)）\]]+", re.IGNORECASE)
IGNORED_HOSTS = (
    "github.com",
    "gitee.com",
    "zhihu.com",
    "xiaohongshu.com",
    "douyin.com",
    "tieba.baidu.com",
    "v2ex.com",
    "segmentfault.com",
    "learnku.com",
    "csdn.net",
    "cnblogs.com",
    "oschina.net",
    "claude.ai",
    "xbox.com",
    "sohu.com",
)


@dataclass(frozen=True)
class ContactSignals:
    emails: list[str]
    wechats: list[str]
    telegrams: list[str]
    qqs: list[str]
    phones: list[str]
    websites: list[str]
    companies: list[str]

    @property
    def has_contact(self) -> bool:
        return bool(self.emails or self.wechats or self.telegrams or self.qqs or self.phones)

    @property
    def has_any_signal(self) -> bool:
        return bool(self.has_contact or self.websites or self.companies)

    @property
    def confidence_score(self) -> int:
        score = 0
        if self.wechats:
            score += 35
        if self.phones:
            score += 30
        if self.emails:
            score += 24
        if self.telegrams:
            score += 22
        if self.qqs:
            score += 18
        if self.websites:
            score += 10
        if self.companies:
            score += 8
        score += min(max(0, self.signal_count - 1) * 4, 12)
        return min(100, score)

    @property
    def signal_count(self) -> int:
        return (
            len(self.emails)
            + len(self.wechats)
            + len(self.telegrams)
            + len(self.qqs)
            + len(self.phones)
            + len(self.websites)
            + len(self.companies)
        )

    @property
    def score_bonus(self) -> int:
        if self.confidence_score >= 70:
            return 16
        if self.wechats or self.phones:
            return 12
        if self.emails or self.telegrams or self.qqs:
            return 8
        if self.websites or self.companies:
            return 3
        return 0

    @property
    def quality_label(self) -> str:
        if self.confidence_score >= 70:
            return "high_confidence"
        if self.confidence_score >= 35:
            return "usable"
        if self.has_any_signal:
            return "weak"
        return "missing"

    def primary_key(self) -> str:
        if self.wechats:
            return f"wechat:{self.wechats[0].lower()}"
        if self.emails:
            return f"email:{self.emails[0].lower()}"
        if self.telegrams:
            return f"telegram:{self.telegrams[0].lower().lstrip('@')}"
        if self.qqs:
            return f"qq:{self.qqs[0]}"
        if self.phones:
            return f"phone:{self.phones[0]}"
        return ""

    def note(self) -> str:
        parts: list[str] = []
        if self.wechats:
            parts.append("微信: " + ", ".join(self.wechats[:3]))
        if self.qqs:
            parts.append("QQ: " + ", ".join(self.qqs[:3]))
        if self.telegrams:
            parts.append("Telegram: " + ", ".join(self.telegrams[:3]))
        if self.phones:
            parts.append("手机: " + ", ".join(self.phones[:2]))
        if self.emails:
            parts.append("邮箱: " + ", ".join(self.emails[:3]))
        if self.companies:
            parts.append("公司/团队: " + ", ".join(self.companies[:3]))
        if self.websites:
            parts.append("链接: " + ", ".join(self.websites[:3]))
        if parts:
            parts.append(f"联系可信度: {self.confidence_score}/100 ({self.quality_label})")
        return "\n".join(parts)


def extract_contacts(text: str) -> ContactSignals:
    normalized = normalize_text(text or "")
    return ContactSignals(
        emails=clean_emails(unique(EMAIL_RE.findall(normalized)), normalized),
        wechats=clean_handles(unique(WECHAT_RE.findall(normalized))),
        telegrams=clean_handles(unique(TELEGRAM_RE.findall(normalized))),
        qqs=clean_numeric_ids(unique(QQ_RE.findall(normalized))),
        phones=clean_phones(unique(PHONE_RE.findall(normalized))),
        websites=clean_urls(unique(URL_RE.findall(normalized) + [f"https://{item}" for item in BARE_DOMAIN_RE.findall(normalized)])),
        companies=clean_companies(unique(COMPANY_RE.findall(normalized))),
    )


def normalize_text(text: str) -> str:
    return (
        text.replace("ＱＱ", "QQ")
        .replace("ＴＧ", "TG")
        .replace("ＶＸ", "VX")
        .replace("ＷＸ", "WX")
        .replace("＠", "@")
        .replace("：", ":")
    )


def merge_contact_notes(*notes: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for note in notes:
        for line in (note or "").splitlines():
            item = line.strip()
            if item and item not in seen:
                seen.add(item)
                lines.append(item)
    return "\n".join(lines[:30])


def contact_identity_from_fields(
    wechat: str = "",
    email: str = "",
    telegram: str = "",
    qq: str = "",
    phone: str = "",
    note: str = "",
) -> str:
    signals = extract_contacts("\n".join([wechat, email, telegram, qq, phone, note]))
    return signals.primary_key()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip().strip(".,;，。；、）)]")
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def clean_emails(values: list[str], context: str = "") -> list[str]:
    result: list[str] = []
    for value in values:
        lower = value.lower()
        domain = lower.rsplit("@", 1)[-1]
        if domain in IGNORED_EMAIL_DOMAINS:
            continue
        if domain.startswith("mastodon.") or ".mastodon." in domain:
            continue
        if any(token in lower for token in ("noreply", "no-reply", "example")):
            continue
        if is_credential_email(value, context):
            continue
        result.append(value[:260])
    return result[:8]


def is_credential_email(value: str, context: str = "") -> bool:
    lower = (value or "").strip().lower()
    if "@" not in lower:
        return True
    local, domain = lower.rsplit("@", 1)
    if local in EMAIL_CREDENTIAL_LOCAL_PARTS:
        return True
    if domain in EMAIL_CREDENTIAL_DOMAINS:
        return True
    if local in {"user", "username", "pass", "password"} and any(
        token in domain for token in ("proxy", "gateway", "gw.", "geo.")
    ):
        return True
    normalized = normalize_text(context or "").lower()
    for match in URL_USERINFO_RE.findall(normalized):
        if lower in match:
            return True
        if f"//{local}:" in match or f":{local}@" in match:
            return True
    return False


def clean_handles(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = value.strip().lstrip("@")
        lower = value.lower()
        if lower in LOW_CONFIDENCE_TOKENS:
            continue
        if len(set(lower)) <= 2:
            continue
        if lower.isdigit():
            continue
        result.append(value[:80])
    return result[:8]


def clean_numeric_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        digits = re.sub(r"\D+", "", value)
        if len(digits) < 5:
            continue
        if len(set(digits)) <= 2:
            continue
        result.append(digits)
    return result[:8]


def clean_phones(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        digits = re.sub(r"\D+", "", value)
        if digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        if len(digits) == 11 and len(set(digits)) > 3:
            result.append(digits)
    return result[:5]


def clean_urls(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if parsed.username or parsed.password:
            continue
        if not host or any(ignored in host for ignored in IGNORED_HOSTS):
            continue
        result.append(value[:500])
    return result[:8]


def clean_companies(values: list[str]) -> list[str]:
    noise = ("这家公司", "哪个公司", "对方公司", "我们公司", "这个团队", "很多公司")
    noisy_fragments = (
        "lastly",
        "repliedby",
        "有没有",
        "请问",
        "怎么",
        "什么",
        "链接",
        "https",
        "http",
        "views",
        "reply",
    )
    result: list[str] = []
    for value in values:
        value = re.sub(r"\s+", "", value.strip())
        lowered = value.lower()
        if value and value not in noise and len(value) <= 40 and not any(item in lowered for item in noisy_fragments):
            result.append(value)
    return unique(result)[:8]
