from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention
from app.services.lead_finder import (
    has_dynamic_ip_context,
    is_chinese_lead_source,
    looks_like_ad_or_noise,
    sort_key_for_lead,
)


def load_demand_signals(
    db: Session,
    status: str = "all",
    risk: str = "all",
    min_score: int = 0,
    limit: int = 150,
) -> list[Mention]:
    query = select(Mention).where(
        Mention.mode == "demand_radar",
        Mention.priority_score >= min_score,
    )
    if status != "all":
        query = query.where(Mention.status == status)
    if risk == "high":
        query = query.where(Mention.risk_score >= 60)
    elif risk == "normal":
        query = query.where(Mention.risk_score < 60)
    rows = list(
        db.scalars(
            query.order_by(desc(Mention.priority_score), desc(Mention.discovered_at)).limit(max(limit * 4, 500))
        ).all()
    )
    if status not in {"invalid", "noise"}:
        rows = [row for row in rows if not looks_like_ad_or_noise(row)]
        rows = [
            row
            for row in rows
            if not is_chinese_lead_source(row) or has_dynamic_ip_context(row)
        ]
    rows.sort(key=lambda row: sort_key_for_lead(row, None))
    return rows[:limit]


def build_demand_stats(rows: list[Mention]) -> dict[str, int]:
    return {
        "signals": len(rows),
        "a_signals": sum(1 for row in rows if row.priority_score >= 80),
        "risk": sum(1 for row in rows if row.risk_score >= 60),
        "converted": sum(1 for row in rows if row.company_id or row.prospect_id),
    }


def demand_action_labels() -> dict[str, str]:
    return {
        "new": "新信号",
        "review": "需审核",
        "qualified": "已合格",
        "invalid": "无效",
        "noise": "噪音",
    }
