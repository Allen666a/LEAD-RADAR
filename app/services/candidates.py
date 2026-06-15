from __future__ import annotations

from collections import Counter
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import CandidateItem
from app.schemas import RawItem
from app.services.detail_fetcher import classify_page_type


FAILURE_LABELS = {
    "duplicate": "重复线索",
    "old_content": "旧内容",
    "missing_time": "缺少原文时间",
    "invalid_path": "无效页面",
    "not_detail": "非详情页",
    "low_intent": "低意向",
    "quality_rejected": "质检未通过",
    "review_required": "待人工复核",
    "collector_timeout": "采集超时",
    "login_required": "需要登录",
    "captcha_required": "需要验证码",
    "forbidden_403": "403/无权限",
    "rate_limited_429": "频率受限",
    "network_error": "网络错误",
    "unknown": "未知原因",
}


def canonicalize_candidate_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    clean = parsed._replace(fragment="")
    return urlunparse(clean)


def platform_from_item(item: RawItem) -> str:
    parsed = urlparse(item.url or "")
    host = (parsed.netloc or "").lower()
    if "github.com" in host:
        return "github"
    if "gitee.com" in host:
        return "gitee"
    if "v2ex.com" in host:
        return "v2ex"
    if "segmentfault.com" in host:
        return "segmentfault"
    if "zhihu.com" in host:
        return "zhihu"
    if "wearesellers.com" in host:
        return "wearesellers"
    if "amazon" in host:
        return "amazon_seller"
    if host:
        return host.removeprefix("www.")
    return item.source_kind


def upsert_candidate(db: Session, item: RawItem, canonical_url: str | None = None) -> CandidateItem:
    canonical = canonical_url or canonicalize_candidate_url(item.url)
    row = db.scalar(select(CandidateItem).where(CandidateItem.canonical_url == canonical))
    now = datetime.now()
    if row is None:
        row = CandidateItem(
            source_name=item.source_name[:160],
            source_kind=item.source_kind[:80],
            platform=platform_from_item(item)[:80],
            title=item.title,
            canonical_url=canonical,
            author=item.author[:160],
            content=item.content or "",
            published_at=item.published_at,
            status="candidate",
            fetched_at=now,
            updated_at=now,
        )
        db.add(row)
        try:
            db.flush()
        except Exception:
            db.rollback()
            existing = db.scalar(select(CandidateItem).where(CandidateItem.canonical_url == canonical))
            if existing is not None:
                return existing
            raise
        return row

    row.source_name = item.source_name[:160]
    row.source_kind = item.source_kind[:80]
    row.platform = platform_from_item(item)[:80]
    row.title = item.title
    row.author = item.author[:160]
    row.content = item.content or ""
    row.published_at = item.published_at or row.published_at
    row.updated_at = now
    return row


def mark_candidate(
    candidate: CandidateItem | None,
    status: str,
    reason: str = "",
    *,
    mention_id: int | None = None,
    score: int = 0,
    signal_type: str = "",
    failure_type: str = "",
) -> None:
    if candidate is None:
        return
    candidate.status = status
    candidate.gate_reason = reason[:1000]
    candidate.mention_id = mention_id
    candidate.score = score
    candidate.signal_type = signal_type[:60]
    candidate.failure_type = failure_type[:60]
    candidate.updated_at = datetime.now()


def mark_candidate_detail(
    candidate: CandidateItem | None,
    status: str,
    reason: str = "",
    *,
    excerpt: str = "",
) -> None:
    if candidate is None:
        return
    candidate.detail_status = status[:40]
    candidate.detail_reason = reason[:1000]
    candidate.detail_excerpt = excerpt[:2000]
    candidate.updated_at = datetime.now()


def classify_collector_failure(exc: Exception) -> str:
    text = (str(exc) or exc.__class__.__name__).lower()
    if "login" in text or "signin" in text or "sign in" in text:
        return "login_required"
    if "captcha" in text or "verify" in text or "验证" in text:
        return "captcha_required"
    if "403" in text or "forbidden" in text:
        return "forbidden_403"
    if "429" in text or "rate limit" in text or "too many" in text:
        return "rate_limited_429"
    if "timeout" in text or "timed out" in text:
        return "collector_timeout"
    if "network" in text or "connection" in text or "connect" in text:
        return "network_error"
    return "unknown"


def build_candidate_board(db: Session, status: str = "all", limit: int = 80) -> dict[str, object]:
    query = select(CandidateItem)
    if status != "all":
        query = query.where(CandidateItem.status == status)
    rows = list(db.scalars(query.order_by(desc(CandidateItem.fetched_at)).limit(max(1, min(300, limit)))))

    status_counts = dict(
        db.execute(select(CandidateItem.status, func.count(CandidateItem.id)).group_by(CandidateItem.status)).all()
    )
    platform_counts = dict(
        db.execute(select(CandidateItem.platform, func.count(CandidateItem.id)).group_by(CandidateItem.platform)).all()
    )
    failure_counts = Counter()
    for key, count in db.execute(
        select(CandidateItem.failure_type, func.count(CandidateItem.id))
        .where(CandidateItem.failure_type != "")
        .group_by(CandidateItem.failure_type)
    ):
        failure_counts[key or "unknown"] = count

    detail_counts = dict(
        db.execute(
            select(CandidateItem.detail_status, func.count(CandidateItem.id)).group_by(CandidateItem.detail_status)
        ).all()
    )

    return {
        "rows": rows,
        "status": status,
        "limit": limit,
        "total": sum(status_counts.values()),
        "accepted": status_counts.get("accepted", 0),
        "review": status_counts.get("review", 0),
        "rejected": status_counts.get("rejected", 0),
        "duplicate": status_counts.get("duplicate", 0),
        "status_counts": status_counts,
        "platform_counts": platform_counts,
        "failure_counts": dict(failure_counts),
        "failure_labels": FAILURE_LABELS,
        "detail_counts": detail_counts,
    }


def reclassify_candidate_page_types(db: Session, limit: int = 500) -> dict[str, int]:
    rows = list(
        db.scalars(
            select(CandidateItem)
            .where(CandidateItem.source_kind == "html_links")
            .order_by(desc(CandidateItem.updated_at))
            .limit(max(1, min(2000, limit)))
        )
    )
    checked = changed = rejected = 0
    for row in rows:
        checked += 1
        page_type, reason = classify_page_type(row.canonical_url, row.title, row.content)
        if page_type == "detail":
            continue
        row.detail_status = "not_detail"
        row.detail_reason = reason
        row.failure_type = "not_detail"
        row.gate_reason = reason
        if row.status not in {"accepted", "duplicate"}:
            row.status = "rejected"
            rejected += 1
        row.updated_at = datetime.now()
        changed += 1
    if changed:
        db.commit()
    return {"checked": checked, "changed": changed, "rejected": rejected}
