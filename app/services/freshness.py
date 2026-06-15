from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


MIN_LEAD_YEAR = 2026

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"),
    re.compile(r"(20\d{2})[-/.年](\d{1,2})"),
    re.compile(r"(?:发布于|发表于|创建于|更新于|时间[:：]?\s*)(20\d{2})"),
]
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
RELATIVE_DAY_RE = re.compile(r"(?<!\d)(\d{1,3})\s*天前")
MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
EN_RELATIVE_DAY_RE = re.compile(r"(?<!\d)(\d{1,3})\s+days?\s+ago", re.IGNORECASE)
NUMERIC_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")
EN_MONTH_DAY_RE = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})\b",
    re.IGNORECASE,
)
EN_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class FreshnessDecision:
    allowed: bool
    published_at: datetime | None
    reason: str


def parse_text_date(text: str) -> datetime | None:
    if not text:
        return None
    explicit_date = parse_explicit_date(text)
    if explicit_date is not None:
        return explicit_date
    lowered = text.lower()
    if any(term in text for term in ("刚刚", "分钟前", "小时前", "今天")) or any(
        term in lowered for term in ("just now", "minutes ago", "minute ago", "hours ago", "hour ago", "today")
    ):
        return datetime.now()
    if "昨天" in text or "yesterday" in lowered:
        return datetime.now() - timedelta(days=1)
    relative_day = RELATIVE_DAY_RE.search(text)
    if relative_day:
        return datetime.now() - timedelta(days=int(relative_day.group(1)))
    en_relative_day = EN_RELATIVE_DAY_RE.search(text)
    if en_relative_day:
        return datetime.now() - timedelta(days=int(en_relative_day.group(1)))
    return parse_partial_date(text)


def parse_explicit_date(text: str) -> datetime | None:
    normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
    for pattern in DATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2)) if len(match.groups()) >= 2 and match.group(2) else 1
        day = int(match.group(3)) if len(match.groups()) >= 3 and match.group(3) else 1
        try:
            return datetime(year, month, day)
        except ValueError:
            continue
    return None


def parse_partial_date(text: str) -> datetime | None:
    month_day = MONTH_DAY_RE.search(text)
    numeric_month_day = NUMERIC_MONTH_DAY_RE.search(text)
    en_month_day = EN_MONTH_DAY_RE.search(text)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        return infer_month_day(month, day)
    if numeric_month_day:
        month = int(numeric_month_day.group(1))
        day = int(numeric_month_day.group(2))
        return infer_month_day(month, day)
    if en_month_day:
        month = EN_MONTHS[en_month_day.group(1).lower()]
        day = int(en_month_day.group(2))
        return infer_month_day(month, day)
    return None


def infer_month_day(month: int, day: int) -> datetime | None:
    now = datetime.now()
    try:
        inferred = datetime(now.year, month, day)
    except ValueError:
        return None
    if inferred.date() > (now + timedelta(days=7)).date():
        try:
            return datetime(now.year - 1, month, day)
        except ValueError:
            return None
    return inferred


def freshness_decision(
    *,
    published_at: datetime | None,
    title: str = "",
    content: str = "",
    url: str = "",
    min_year: int = MIN_LEAD_YEAR,
    require_known: bool = False,
) -> FreshnessDecision:
    text = f"{title}\n{content}"
    parsed_text_time = parse_text_date(text)
    explicit_text_time = parse_explicit_date(text)
    source_time = explicit_text_time or published_at or parsed_text_time
    if require_known and source_time is None:
        return FreshnessDecision(False, None, f"未解析到原文时间，无法确认是否为 {min_year} 年线索")
    if source_time and source_time.year < min_year:
        return FreshnessDecision(False, source_time, f"原文时间 {source_time:%Y-%m-%d} 早于 {min_year} 年")

    years = [int(item) for item in YEAR_RE.findall(f"{title}\n{content}\n{url}")]
    if years and max(years) < min_year:
        newest = max(years)
        return FreshnessDecision(False, source_time, f"文本中最新年份 {newest} 早于 {min_year} 年")

    return FreshnessDecision(True, source_time, "时间合格或未发现早于阈值的原文时间")


def is_fresh_enough(
    *,
    published_at: datetime | None,
    title: str = "",
    content: str = "",
    url: str = "",
    min_year: int = MIN_LEAD_YEAR,
    require_known: bool = False,
) -> bool:
    return freshness_decision(
        published_at=published_at,
        title=title,
        content=content,
        url=url,
        min_year=min_year,
        require_known=require_known,
    ).allowed
