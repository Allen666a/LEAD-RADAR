from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import CandidateItem, Mention
from app.services.lead_finder import (
    has_dynamic_ip_context,
    is_chinese_lead_source,
    looks_like_ad_or_noise,
    usable_display_mention,
)


CORE_NEED_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "家宽",
    "代理ip",
    "代理 ip",
    "指纹浏览器",
    "防关联",
    "账号关联",
    "店铺关联",
    "网络环境",
    "登录环境",
    "环境异常",
    "ip 被封",
    "ip被封",
    "cloudflare",
    "403",
    "429",
    "验证码",
    "爬虫",
)

BUYER_LANGUAGE_TERMS = (
    "求推荐",
    "有没有",
    "哪里",
    "哪家",
    "怎么解决",
    "如何解决",
    "需要",
    "采购",
    "购买",
    "替换",
    "稳定",
    "不稳定",
    "被封",
    "封号",
    "关联",
    "风控",
    "which",
    "what is the best",
    "best way",
    "how to",
    "why",
    "looking for",
    "recommend",
    "need",
    "necessary",
    "suspended",
    "blocked",
    "failed",
    "unstable",
)

NOISE_TERMS = (
    "代运营",
    "招商",
    "加盟",
    "培训",
    "课程",
    "排行榜",
    "测评",
    "评测",
    "官网",
    "优惠",
    "免费测试",
    "内附福利",
)

DIRECT_PROXY_NEED_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "家宽",
    "原生ip",
    "原生 ip",
    "代理ip",
    "代理 ip",
    "指纹浏览器",
    "防关联",
    "账号关联",
    "店铺关联",
    "网络环境",
    "登录环境",
    "环境异常",
    "ip 被封",
    "ip被封",
    "cloudflare",
    "403",
    "429",
    "验证码",
    "residential proxy",
    "residential proxies",
    "rotating proxy",
    "rotating proxies",
    "proxy pool",
    "anti detect",
    "anti-detect",
)

WEAK_CONTEXT_TERMS = (
    "爬虫",
    "数据采集",
    "采集",
    "scrapy",
    "playwright",
    "puppeteer",
)

SUPPLIER_OR_PROMO_TERMS = (
    "kookeey",
    "novproxy",
    "922s5",
    "iproyal",
    "bright data",
    "oxylabs",
    "smartproxy",
    "soax",
    "mango proxy",
    "ipfighter",
    "scraperapi",
    "proxy-seller",
    "proxy seller",
    "luna proxy",
    "webshare",
    "免费测试",
    "免费试用",
    "优惠",
    "福利",
    "官网",
    "排行榜",
    "测评",
    "评测",
    "十大",
    "解决方案",
    "代运营",
    "招商",
    "加盟",
    "培训",
    "课程",
    "read the rules",
    "rules clarification",
    "read the full",
    "试试我这个项目",
    "大幅提升",
)

ENGINEERING_CHANGE_TERMS = (
    "unit coverage",
    "test suite",
    "split scraper",
    "handler.py",
    "p0:",
    "p1 ",
    "p2 ",
    "fix(",
    "bug",
    "release",
    "changelog",
    "firewall auth mutation",
    "browser-originated requests",
    "github action",
)


@dataclass(frozen=True)
class AuditRow:
    id: int
    kind: str
    title: str
    url: str
    source: str
    platform: str
    status: str
    score: int
    published_at: datetime | None
    discovered_at: datetime | None
    reason: str
    verdict: str
    risk: str


@dataclass(frozen=True)
class LeadQualityAuditBoard:
    stats: dict[str, int]
    failure_counts: dict[str, int]
    source_counts: dict[str, int]
    possible_false_negatives: list[AuditRow]
    questionable_passed: list[AuditRow]
    top_usable: list[AuditRow]
    recommendations: list[str]


def build_lead_quality_audit(db: Session, limit: int = 40) -> LeadQualityAuditBoard:
    total_mentions = int(db.scalar(select(func.count(Mention.id))) or 0)
    invalid_mentions = int(db.scalar(select(func.count(Mention.id)).where(Mention.status == "invalid")) or 0)
    total_candidates = int(db.scalar(select(func.count(CandidateItem.id))) or 0)
    accepted_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "accepted")) or 0
    )
    review_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "review")) or 0
    )
    rejected_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "rejected")) or 0
    )
    duplicate_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "duplicate")) or 0
    )

    failure_counts = {
        key or "unknown": int(count)
        for key, count in db.execute(
            select(CandidateItem.failure_type, func.count(CandidateItem.id))
            .where(CandidateItem.failure_type != "")
            .group_by(CandidateItem.failure_type)
        )
    }
    source_counts = {
        key or "unknown": int(count)
        for key, count in db.execute(
            select(CandidateItem.platform, func.count(CandidateItem.id))
            .group_by(CandidateItem.platform)
            .order_by(desc(func.count(CandidateItem.id)))
            .limit(12)
        )
    }

    rejected_pool = list(
        db.scalars(
            select(CandidateItem)
            .where(CandidateItem.status.in_(["rejected", "review"]))
            .order_by(desc(CandidateItem.score), desc(CandidateItem.fetched_at))
            .limit(1500)
        )
    )
    possible_false_negatives = sorted(
        [candidate_to_audit_row(row) for row in rejected_pool if looks_like_possible_false_negative(row)],
        key=lambda row: (-row.score, row.published_at or datetime.min),
        reverse=False,
    )[:limit]

    passed_mentions = list(
        row
        for row in db.scalars(
            select(Mention)
            .where(Mention.status != "invalid")
            .where(Mention.published_at.is_not(None))
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(1500)
        )
        if usable_display_mention(row, "usable")
    )
    usable_mentions = len(passed_mentions)
    questionable_passed = [
        mention_to_audit_row(row, verdict="建议复核", risk=questionable_pass_reason(row))
        for row in passed_mentions
        if questionable_pass_reason(row)
    ][:limit]
    top_usable = [
        mention_to_audit_row(row, verdict="优先看", risk="中文/2026/动态住宅 IP 或明确痛点优先")
        for row in passed_mentions
        if not questionable_pass_reason(row)
    ][:limit]

    stats = {
        "mentions": total_mentions,
        "usable_mentions": usable_mentions,
        "invalid_mentions": invalid_mentions,
        "candidates": total_candidates,
        "accepted_candidates": accepted_candidates,
        "review_candidates": review_candidates,
        "rejected_candidates": rejected_candidates,
        "duplicate_candidates": duplicate_candidates,
        "possible_false_negatives": len(possible_false_negatives),
        "questionable_passed": len(questionable_passed),
    }

    recommendations = build_recommendations(stats, failure_counts, possible_false_negatives, questionable_passed)
    return LeadQualityAuditBoard(
        stats=stats,
        failure_counts=failure_counts,
        source_counts=source_counts,
        possible_false_negatives=possible_false_negatives,
        questionable_passed=questionable_passed,
        top_usable=top_usable,
        recommendations=recommendations,
    )


def looks_like_possible_false_negative(row: CandidateItem) -> bool:
    text = candidate_text(row)
    title = (row.title or "").lower()
    if is_hard_noise_text(text, title):
        return False
    if (row.score or 0) < 40:
        return False
    has_need = contains_direct_proxy_need(text)
    weak_only = contains_any(text, WEAK_CONTEXT_TERMS) and not has_need
    has_buyer = contains_any(text, BUYER_LANGUAGE_TERMS)
    fresh = row.published_at is not None and row.published_at.year >= 2026
    detail_ok = row.detail_status in {"ok", "skipped", "deferred", "not_checked", ""}
    if weak_only:
        return False
    return fresh and detail_ok and has_need and has_buyer


def questionable_pass_reason(row: Mention) -> str:
    if row.published_at and row.published_at.year < 2026:
        return "旧内容进入可用池"
    if looks_like_ad_or_noise(row):
        return "疑似广告/软文进入可用池"
    if is_chinese_lead_source(row) and not has_dynamic_ip_context(row):
        return "中文来源但原文缺少动态住宅/IP/防关联证据"
    text = mention_raw_text(row)
    if not contains_core_need(text) and (row.score or 0) < 80:
        return "核心动态住宅 IP 证据偏弱"
    return ""


def candidate_to_audit_row(row: CandidateItem) -> AuditRow:
    return AuditRow(
        id=row.id,
        kind="candidate",
        title=row.title or "-",
        url=row.canonical_url or "",
        source=row.source_name or "",
        platform=row.platform or row.source_kind or "",
        status=row.status or "",
        score=row.score or 0,
        published_at=row.published_at,
        discovered_at=row.fetched_at,
        reason=row.gate_reason or row.detail_reason or row.failure_type or "-",
        verdict="疑似误杀",
        risk=false_negative_reason(row),
    )


def mention_to_audit_row(row: Mention, *, verdict: str, risk: str) -> AuditRow:
    return AuditRow(
        id=row.id,
        kind="mention",
        title=row.title or "-",
        url=row.canonical_url or "",
        source=row.source_name or "",
        platform=row.source_kind or "",
        status=row.status or "",
        score=max(row.score or 0, row.priority_score or 0),
        published_at=row.published_at,
        discovered_at=row.discovered_at,
        reason=row.recommendation or row.score_reasons or "-",
        verdict=verdict,
        risk=risk,
    )


def false_negative_reason(row: CandidateItem) -> str:
    parts = []
    text = candidate_text(row)
    if contains_direct_proxy_need(text):
        parts.append("命中动态住宅/IP/防关联/爬虫痛点")
    if contains_any(text, BUYER_LANGUAGE_TERMS):
        parts.append("有求助或购买语言")
    if row.published_at and row.published_at.year >= 2026:
        parts.append("2026 新内容")
    if row.failure_type:
        parts.append(f"当前过滤原因: {row.failure_type}")
    return "；".join(parts) or "需要人工复核"


def build_recommendations(
    stats: dict[str, int],
    failure_counts: dict[str, int],
    possible_false_negatives: list[AuditRow],
    questionable_passed: list[AuditRow],
) -> list[str]:
    recs: list[str] = []
    if possible_false_negatives:
        recs.append(f"先人工抽查 {min(20, len(possible_false_negatives))} 条疑似误杀，确认过滤规则是否过严。")
    if questionable_passed:
        recs.append(f"先清理 {len(questionable_passed)} 条疑似误入线索池的广告/弱证据线索。")
    if failure_counts.get("old_content", 0):
        recs.append("旧内容过滤有效，但需要保留少量人工复核，避免平台时间解析错误。")
    if failure_counts.get("not_detail", 0):
        recs.append("详情页判断是最大过滤口之一，优先检查被判 not_detail 但内容像真实求助的记录。")
    if stats["accepted_candidates"] == 0 and stats["review_candidates"] > 0:
        recs.append("当前偏保守，建议先把待复核池作为人工获客入口，不要只看主池。")
    if not recs:
        recs.append("当前没有明显质量异常，下一步应人工抽样验证成交可能性。")
    return recs


def candidate_text(row: CandidateItem) -> str:
    return "\n".join([row.title or "", row.content or "", row.detail_excerpt or ""]).lower()


def mention_raw_text(row: Mention) -> str:
    return "\n".join([row.title or "", row.content or ""]).lower()


def is_hard_noise_text(text: str, title: str) -> bool:
    text_lower = text.lower()
    title_lower = title.lower()
    if contains_any(title_lower, SUPPLIER_OR_PROMO_TERMS):
        return True
    if contains_any(title_lower, ENGINEERING_CHANGE_TERMS):
        return True
    if title_lower.startswith("[") and contains_any(title_lower, SUPPLIER_OR_PROMO_TERMS):
        return True
    supplier_mentions = sum(1 for term in SUPPLIER_OR_PROMO_TERMS if term.lower() in text_lower)
    has_buyer_language = contains_any(text_lower, BUYER_LANGUAGE_TERMS)
    if supplier_mentions >= 2 and not has_buyer_language:
        return True
    return False


def contains_direct_proxy_need(text: str) -> bool:
    text_lower = text.lower()
    for term in DIRECT_PROXY_NEED_TERMS:
        needle = term.lower()
        if needle == "ip":
            if re.search(r"(?<![a-z])ip(?![a-z])", text_lower):
                return True
            continue
        if needle in text_lower:
            return True
    return False


def contains_core_need(text: str) -> bool:
    text_lower = text.lower()
    for term in CORE_NEED_TERMS:
        needle = term.lower()
        if needle in {"ip", "代理ip", "代理 ip"}:
            if re.search(r"(?<![a-z])ip(?![a-z])", text_lower):
                return True
        if needle in text_lower:
            return True
    return False


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    text_lower = text.lower()
    return any(term.lower() in text_lower for term in terms)
