from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contact_status import has_real_contact
from app.services.contact_workbench import DOMESTIC_PLATFORMS, is_rejected_session_candidate, load_contact_workbench_rows
from app.services.icp_quality import evaluate_icp


@dataclass(frozen=True)
class PlatformICPAudit:
    platform: str
    prospects: int
    qualified: int
    enrich: int
    observe: int
    invalid: int
    contactable: int
    avg_icp_score: int


def build_icp_quality_audit(db: Session, min_score: int = 50) -> dict[str, Any]:
    prospects = list(db.scalars(select(Prospect).where(Prospect.status != "invalid")))
    top_mentions = load_top_mentions(db)
    platform_rows = build_platform_rows(prospects, top_mentions)
    missing_rows = load_contact_workbench_rows(db, mode="missing", platform="domestic", min_score=min_score, limit=50)
    contactable_rows = load_contact_workbench_rows(db, mode="contactable", platform="domestic", min_score=min_score, limit=50)

    decisions = [evaluate_icp(prospect, top_mentions.get(prospect.id)) for prospect in prospects]
    route_counts = Counter(decision.route for decision in decisions)
    status_counts = Counter(decision.status for decision in decisions)

    result = {
        "prospects": len(prospects),
        "domestic_prospects": sum(1 for prospect in prospects if prospect.platform in DOMESTIC_PLATFORMS),
        "routes": dict(route_counts),
        "statuses": dict(status_counts),
        "contactable": sum(1 for prospect in prospects if has_real_contact(prospect)),
        "missing_contact_queue": len(missing_rows),
        "contactable_queue": len(contactable_rows),
        "platforms": [asdict(row) for row in platform_rows],
        "top_missing_contacts": [
            {
                "id": row.prospect.id,
                "platform": row.prospect.platform,
                "name": row.display_label,
                "icp_score": row.icp_score,
                "priority_score": row.priority_score,
                "route": row.icp_route,
                "reason": row.icp_reason,
                "source": row.top_mention.source_name if row.top_mention else row.prospect.platform,
                "url": row.top_mention.canonical_url if row.top_mention else row.prospect.profile_url,
            }
            for row in missing_rows[:20]
        ],
        "recommendations": build_recommendations(platform_rows, route_counts, missing_rows, contactable_rows),
    }
    return result


def load_top_mentions(db: Session) -> dict[int, Mention]:
    rows = list(
        db.scalars(
            select(Mention)
            .where(Mention.status != "invalid")
            .order_by(Mention.prospect_id, desc(Mention.score), desc(Mention.discovered_at))
        )
    )
    top: dict[int, Mention] = {}
    for mention in rows:
        if is_rejected_session_candidate(mention):
            continue
        if mention.prospect_id not in top:
            top[mention.prospect_id] = mention
    return top


def build_platform_rows(prospects: list[Prospect], top_mentions: dict[int, Mention]) -> list[PlatformICPAudit]:
    buckets: dict[str, list[Prospect]] = defaultdict(list)
    for prospect in prospects:
        buckets[prospect.platform or "unknown"].append(prospect)

    rows: list[PlatformICPAudit] = []
    for platform, items in buckets.items():
        decisions = [evaluate_icp(prospect, top_mentions.get(prospect.id)) for prospect in items]
        routes = Counter(decision.route for decision in decisions)
        avg_score = int(sum(decision.score for decision in decisions) / max(1, len(decisions)))
        rows.append(
            PlatformICPAudit(
                platform=platform,
                prospects=len(items),
                qualified=sum(1 for decision in decisions if decision.status == "qualified"),
                enrich=routes.get("contact_enrich", 0),
                observe=routes.get("observe", 0),
                invalid=routes.get("invalid", 0),
                contactable=sum(1 for prospect in items if has_real_contact(prospect)),
                avg_icp_score=avg_score,
            )
        )
    return sorted(rows, key=lambda row: (row.qualified, row.enrich, row.contactable, row.avg_icp_score), reverse=True)


def build_recommendations(
    platforms: list[PlatformICPAudit],
    route_counts: Counter,
    missing_rows: list[Any],
    contactable_rows: list[Any],
) -> list[str]:
    recommendations: list[str] = []
    if not missing_rows:
        recommendations.append("待补联系方式队列为空：先扩大知乎、卖家论坛、贴吧和会话采集的高意图关键词。")
    if route_counts.get("contact_enrich", 0) > len(missing_rows):
        recommendations.append("ICP 高匹配但补全池偏少：检查是否被旧噪音规则或来源去重挡掉。")
    if not contactable_rows:
        recommendations.append("可触达队列为空：优先处理登录会话采集，并补知乎/V2EX/卖家社区作者主页或私域导入。")
    domestic_platforms = [row for row in platforms if row.platform in DOMESTIC_PLATFORMS]
    weak_platforms = [
        row.platform for row in domestic_platforms if row.prospects >= 10 and row.qualified + row.enrich == 0
    ]
    if weak_platforms:
        recommendations.append("低产平台建议降权或暂停：" + "、".join(weak_platforms[:6]))
    strong_platforms = [row.platform for row in domestic_platforms if row.qualified + row.enrich > 0]
    if strong_platforms:
        recommendations.append("优先加码平台：" + "、".join(strong_platforms[:6]))
    if not strong_platforms:
        recommendations.append("国内平台暂未形成稳定产出：先处理会话登录态，再跑知乎、V2EX、贴吧、小红书低频采集。")
    return recommendations[:6]
