from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, Mention, Prospect
from app.services.lead_quality import evaluate_lead_quality


@dataclass(frozen=True)
class P3QualityAudit:
    reviewed_mentions: int
    rejected_mentions: int
    a_tier_mentions: int
    b_tier_mentions: int
    high_quality_mentions: int
    reviewed_prospects: int
    rejected_prospects: int
    high_quality_prospects: int
    reviewed_companies: int
    rejected_companies: int
    high_quality_companies: int
    top_reject_reasons: list[tuple[str, int]]
    top_customer_types: list[tuple[str, int]]
    samples: list[dict[str, object]]


def run_p3_quality_audit(db: Session, limit: int = 500) -> dict[str, object]:
    audit = build_p3_quality_audit(db, limit=limit)
    return {
        "reviewed_mentions": audit.reviewed_mentions,
        "rejected_mentions": audit.rejected_mentions,
        "a_tier_mentions": audit.a_tier_mentions,
        "b_tier_mentions": audit.b_tier_mentions,
        "high_quality_mentions": audit.high_quality_mentions,
        "reviewed_prospects": audit.reviewed_prospects,
        "rejected_prospects": audit.rejected_prospects,
        "high_quality_prospects": audit.high_quality_prospects,
        "reviewed_companies": audit.reviewed_companies,
        "rejected_companies": audit.rejected_companies,
        "high_quality_companies": audit.high_quality_companies,
        "top_reject_reasons": audit.top_reject_reasons,
        "top_customer_types": audit.top_customer_types,
        "samples": audit.samples,
    }


def build_p3_quality_audit(db: Session, limit: int = 500) -> P3QualityAudit:
    reject_reasons: Counter[str] = Counter()
    customer_types: Counter[str] = Counter()
    samples: list[dict[str, object]] = []

    reviewed_mentions = rejected_mentions = a_tier_mentions = b_tier_mentions = 0
    high_quality_mentions = 0
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.priority_score), desc(Mention.score), desc(Mention.discovered_at))
            .limit(limit)
        )
    )
    for mention in mentions:
        reviewed_mentions += 1
        quality = evaluate_lead_quality(
            title=mention.title,
            content=f"{mention.content}\n{mention.author}\n{mention.matched_keywords}",
            url=mention.canonical_url,
            source_name=mention.source_name,
        )
        collect_quality_stats(quality, reject_reasons, customer_types)
        if quality.reject:
            rejected_mentions += 1
        if quality.tier == "A":
            a_tier_mentions += 1
        if quality.tier == "B":
            b_tier_mentions += 1
        if quality.tier in {"A", "B"} and not quality.reject:
            high_quality_mentions += 1
            if len(samples) < 20:
                samples.append(
                    {
                        "type": "mention",
                        "id": mention.id,
                        "title": mention.title,
                        "score": mention.score,
                        "quality": quality.quality_score,
                        "tier": quality.tier,
                        "customer_types": quality.customer_types,
                        "source": mention.source_name,
                    }
                )

    reviewed_prospects = rejected_prospects = high_quality_prospects = 0
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.status != "invalid")
            .order_by(desc(Prospect.priority_score), desc(Prospect.lead_score))
            .limit(limit)
        )
    )
    for prospect in prospects:
        reviewed_prospects += 1
        quality = evaluate_lead_quality(
            title=prospect.display_name,
            content="\n".join(
                [
                    prospect.company_name or "",
                    prospect.platform or "",
                    prospect.profile_url or "",
                    prospect.website or "",
                    prospect.customer_type or "",
                    prospect.keywords or "",
                    prospect.evidence or "",
                    prospect.next_action or "",
                ]
            ),
            url=prospect.profile_url,
            source_name=prospect.platform,
        )
        collect_quality_stats(quality, reject_reasons, customer_types)
        if quality.reject:
            rejected_prospects += 1
        elif quality.tier in {"A", "B"}:
            high_quality_prospects += 1

    reviewed_companies = rejected_companies = high_quality_companies = 0
    companies = list(
        db.scalars(
            select(CompanyProfile)
            .where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
            .order_by(desc(CompanyProfile.priority_score))
            .limit(limit)
        )
    )
    for company in companies:
        reviewed_companies += 1
        quality = evaluate_lead_quality(
            title=company.company_name or company.domain,
            content="\n".join(
                [
                    company.customer_type or "",
                    company.business_scenario or "",
                    company.evidence_summary or "",
                    company.need_reason or "",
                    company.next_action or "",
                ]
            ),
            url=company.website,
            source_name=company.domain,
        )
        collect_quality_stats(quality, reject_reasons, customer_types)
        if quality.reject:
            rejected_companies += 1
        elif quality.tier in {"A", "B"}:
            high_quality_companies += 1

    return P3QualityAudit(
        reviewed_mentions=reviewed_mentions,
        rejected_mentions=rejected_mentions,
        a_tier_mentions=a_tier_mentions,
        b_tier_mentions=b_tier_mentions,
        high_quality_mentions=high_quality_mentions,
        reviewed_prospects=reviewed_prospects,
        rejected_prospects=rejected_prospects,
        high_quality_prospects=high_quality_prospects,
        reviewed_companies=reviewed_companies,
        rejected_companies=rejected_companies,
        high_quality_companies=high_quality_companies,
        top_reject_reasons=reject_reasons.most_common(8),
        top_customer_types=customer_types.most_common(8),
        samples=samples,
    )


def collect_quality_stats(quality, reject_reasons: Counter[str], customer_types: Counter[str]) -> None:
    for customer_type in quality.customer_types:
        customer_types[customer_type] += 1
    if quality.reject:
        reject_reasons[reject_reason(quality)] += 1


def reject_reason(quality) -> str:
    if quality.illegal_risk:
        return "违规/高风险用途"
    if quality.supplier_ad:
        return "疑似供应商广告或同行官网"
    if quality.low_fit:
        return "静态/固定/机房/VPN 等低匹配需求"
    if quality.tutorial_noise:
        return "教程/测评/新闻/招聘等低价值内容"
    if quality.generic_page:
        return "搜索页/标签页/列表页"
    if quality.reasons:
        return quality.reasons[-1]
    return "unknown"
