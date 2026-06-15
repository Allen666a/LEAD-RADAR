from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha1

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateItem, Source
from app.schemas import RawItem


BLOCKING_FAILURES = {
    "forbidden_403",
    "rate_limited_429",
    "captcha_required",
    "login_required",
}


@dataclass(frozen=True)
class SourceRunDecision:
    allowed: bool
    reason: str


def source_run_decision(source: Source, now: datetime | None = None) -> SourceRunDecision:
    now = now or datetime.now()
    if not source.enabled:
        return SourceRunDecision(False, "source disabled")
    if source.cooldown_until and source.cooldown_until > now:
        return SourceRunDecision(False, f"cooldown until {source.cooldown_until:%Y-%m-%d %H:%M}")
    if source.next_collect_at and source.next_collect_at > now:
        return SourceRunDecision(False, f"next collect at {source.next_collect_at:%Y-%m-%d %H:%M}")
    return SourceRunDecision(True, "due")


def known_candidate(db: Session, url: str) -> CandidateItem | None:
    canonical = canonical_fingerprint_url(url)
    return db.scalar(select(CandidateItem).where(CandidateItem.canonical_url == canonical))


def should_skip_known_candidate(candidate: CandidateItem | None) -> bool:
    if candidate is None:
        return False
    if candidate.status in {"accepted", "duplicate", "rejected", "review"}:
        return True
    if candidate.detail_status in {"ok", "not_detail", "blocked", "failed"}:
        return True
    return False


def source_cursor_from_items(items: list[RawItem]) -> str:
    dated = [item.published_at for item in items if item.published_at is not None]
    if dated:
        return max(dated).isoformat(timespec="seconds")
    keys = sorted({canonical_fingerprint_url(item.url) for item in items if item.url})
    if not keys:
        return ""
    digest = sha1("\n".join(keys[:100]).encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def apply_source_success_schedule(source: Source, fetched: int, inserted: int, cursor: str = "") -> None:
    source.crawl_backoff_level = max(0, (source.crawl_backoff_level or 0) - 1)
    delay_minutes = success_delay_minutes(source, fetched, inserted)
    now = datetime.now()
    source.next_collect_at = now + timedelta(minutes=delay_minutes)
    source.cooldown_until = None
    if cursor:
        source.last_cursor = cursor[:260]
    source.last_run_reason = f"success: fetched={fetched}, inserted={inserted}, next={delay_minutes}m"


def apply_source_failure_schedule(source: Source, failure_type: str, message: str = "") -> None:
    level = min(7, (source.crawl_backoff_level or 0) + 1)
    source.crawl_backoff_level = level
    delay_minutes = failure_delay_minutes(failure_type, level)
    now = datetime.now()
    source.next_collect_at = now + timedelta(minutes=delay_minutes)
    if failure_type in BLOCKING_FAILURES:
        source.cooldown_until = source.next_collect_at
    source.last_run_reason = f"{failure_type}: retry in {delay_minutes}m; {message[:180]}"


def success_delay_minutes(source: Source, fetched: int, inserted: int) -> int:
    quality = source.quality_status or "unchecked"
    if inserted > 0 and quality in {"excellent", "good"}:
        return 25
    if inserted > 0:
        return 45
    if fetched == 0:
        return 180
    if quality == "low_yield":
        return 240
    if quality in {"blocked", "unstable"}:
        return 720
    return 90


def failure_delay_minutes(failure_type: str, level: int) -> int:
    if failure_type == "rate_limited_429":
        base = 720
    elif failure_type in {"captcha_required", "login_required"}:
        base = 1440
    elif failure_type == "forbidden_403":
        base = 720
    elif failure_type == "collector_timeout":
        base = 60
    else:
        base = 30
    return min(1440, base * max(1, min(level, 4)))


def canonical_fingerprint_url(url: str) -> str:
    # Keep this deliberately conservative; ingestion owns full canonicalization.
    return (url or "").strip().split("#", 1)[0]
