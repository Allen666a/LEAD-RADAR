from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import CandidateItem, Mention, Prospect, Source
from app.services.lead_finder import build_lead_finder_board
from app.services.prospects import CUSTOMER_TYPE_LABELS


FRESH_CUTOFF = datetime(2026, 1, 1)


@dataclass(frozen=True)
class Metric:
    label: str
    value: int | str
    note: str


@dataclass(frozen=True)
class SourceHealthRow:
    name: str
    kind: str
    quality: str
    score: int
    fetched: int
    inserted: int
    success: int
    failed: int
    last_error: str


@dataclass(frozen=True)
class BucketRow:
    label: str
    count: int


@dataclass(frozen=True)
class ProductionLeadRow:
    id: int
    title: str
    source: str
    platform: str
    score: int
    status: str
    published_at: datetime | None
    url: str
    why: str
    next_step: str


@dataclass(frozen=True)
class ProductionReport:
    readiness: str
    readiness_class: str
    summary: list[Metric]
    funnel: list[Metric]
    source_rows: list[SourceHealthRow]
    weak_source_rows: list[SourceHealthRow]
    failure_rows: list[BucketRow]
    customer_rows: list[BucketRow]
    top_leads: list[ProductionLeadRow]
    actions: list[str]


def build_production_report(db: Session, sample_limit: int = 50) -> ProductionReport:
    total_sources = int(db.scalar(select(func.count(Source.id))) or 0)
    enabled_sources = int(db.scalar(select(func.count(Source.id)).where(Source.enabled.is_(True))) or 0)
    hq_sources = int(db.scalar(select(func.count(Source.id)).where(Source.name.startswith("HQ "))) or 0)
    candidates = int(db.scalar(select(func.count(CandidateItem.id))) or 0)
    fresh_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.published_at >= FRESH_CUTOFF)) or 0
    )
    lead_board = build_lead_finder_board(db, segment="all", scope="all", pool="usable", min_score=0)
    usable_mentions = int(lead_board.stats.get("results", 0))
    review_mentions = sum(1 for row in lead_board.rows if row.status == "review")
    high_mentions = int(lead_board.stats.get("high", 0))
    active_prospects = int(
        db.scalar(
            select(func.count(Prospect.id))
            .where(Prospect.status.notin_(["won", "invalid"]))
            .where(Prospect.lead_score >= 50)
            .where(Prospect.last_seen_at >= FRESH_CUTOFF)
        )
        or 0
    )

    conversion = round(usable_mentions * 100 / candidates) if candidates else 0
    freshness = round(fresh_candidates * 100 / candidates) if candidates else 0
    readiness, readiness_class = readiness_level(
        candidates=candidates,
        usable_mentions=usable_mentions,
        high_mentions=high_mentions,
        active_prospects=active_prospects,
    )

    summary = [
        Metric("启用来源", f"{enabled_sources}/{total_sources}", f"HQ 高产来源 {hq_sources} 个"),
        Metric("候选池", candidates, "原始入口，越大越利于筛选"),
        Metric("可用线索", usable_mentions, f"候选到线索转化约 {conversion}%"),
        Metric("高分线索", high_mentions, "优先补联系方式和跟进"),
        Metric("可跟进客户", active_prospects, "已合并成客户画像的目标"),
    ]
    funnel = [
        Metric("全部候选", candidates, "所有来源抓到的原始入口"),
        Metric("2026 候选", fresh_candidates, f"时效占比 {freshness}%"),
        Metric("线索池", usable_mentions, "排除明显无效后可人工处理"),
        Metric("待复核", review_mentions, "疑似真客户但证据不足"),
        Metric("高分", high_mentions, "最接近生产动作"),
    ]

    source_rows = load_top_sources(db, strongest=True, limit=12)
    weak_source_rows = load_top_sources(db, strongest=False, limit=12)
    failure_rows = [
        BucketRow(label=key or "unknown", count=int(count))
        for key, count in db.execute(
            select(CandidateItem.failure_type, func.count(CandidateItem.id))
            .where(CandidateItem.failure_type != "")
            .group_by(CandidateItem.failure_type)
            .order_by(desc(func.count(CandidateItem.id)))
            .limit(12)
        )
    ]
    customer_rows = [
        BucketRow(label=CUSTOMER_TYPE_LABELS.get(key or "unknown", key or "unknown"), count=int(count))
        for key, count in db.execute(
            select(Prospect.customer_type, func.count(Prospect.id))
            .group_by(Prospect.customer_type)
            .order_by(desc(func.count(Prospect.id)))
            .limit(12)
        )
    ]
    top_leads = lead_rows_to_production(lead_board.rows[: max(10, min(100, sample_limit))])
    actions = build_actions(
        candidates=candidates,
        fresh_candidates=fresh_candidates,
        usable_mentions=usable_mentions,
        high_mentions=high_mentions,
        review_mentions=review_mentions,
        weak_sources=weak_source_rows,
        top_leads=top_leads,
    )

    return ProductionReport(
        readiness=readiness,
        readiness_class=readiness_class,
        summary=summary,
        funnel=funnel,
        source_rows=source_rows,
        weak_source_rows=weak_source_rows,
        failure_rows=failure_rows,
        customer_rows=customer_rows,
        top_leads=top_leads,
        actions=actions,
    )


def readiness_level(*, candidates: int, usable_mentions: int, high_mentions: int, active_prospects: int) -> tuple[str, str]:
    if candidates >= 5000 and usable_mentions >= 300 and high_mentions >= 40 and active_prospects >= 80:
        return "可以进入稳定生产试运行", "good"
    if candidates >= 1500 and usable_mentions >= 80 and high_mentions >= 10:
        return "可以小规模生产试用", "warn"
    return "还需要扩量和抽样验收", "bad"


def load_top_sources(db: Session, *, strongest: bool, limit: int) -> list[SourceHealthRow]:
    order = (
        (desc(Source.last_inserted_count), desc(Source.last_fetched_count), desc(Source.quality_score))
        if strongest
        else (Source.last_inserted_count, Source.last_fetched_count, Source.quality_score)
    )
    rows = db.scalars(select(Source).where(Source.enabled.is_(True)).order_by(*order).limit(limit)).all()
    return [
        SourceHealthRow(
            name=row.name,
            kind=row.kind,
            quality=row.quality_status or "unchecked",
            score=row.quality_score or 0,
            fetched=row.last_fetched_count or 0,
            inserted=row.last_inserted_count or 0,
            success=row.success_count or 0,
            failed=row.failure_count or 0,
            last_error=(row.last_error or "")[:120],
        )
        for row in rows
    ]


def load_top_leads(db: Session, limit: int) -> list[ProductionLeadRow]:
    board = build_lead_finder_board(db, segment="all", scope="all", pool="usable", min_score=0)
    return lead_rows_to_production(board.rows[:limit])


def lead_rows_to_production(rows_in: list) -> list[ProductionLeadRow]:
    rows: list[ProductionLeadRow] = []
    for row in rows_in:
        rows.append(
            ProductionLeadRow(
                id=row.id,
                title=row.title,
                source=row.source,
                platform=row.platform,
                score=row.score,
                status=row.status,
                published_at=row.published_at,
                url=row.url,
                why=row.why,
                next_step=row.next_step,
            )
        )
    return rows


def build_actions(
    *,
    candidates: int,
    fresh_candidates: int,
    usable_mentions: int,
    high_mentions: int,
    review_mentions: int,
    weak_sources: list[SourceHealthRow],
    top_leads: list[ProductionLeadRow],
) -> list[str]:
    actions: list[str] = []
    if candidates < 5000:
        actions.append("继续跑全源自动采集，候选池先冲到 5000 条以上，再判断各来源真实产能。")
    if fresh_candidates < candidates * 0.5:
        actions.append("时效占比偏低，优先保留能产出 2026 内容的来源，旧内容源降权。")
    if usable_mentions < 300:
        actions.append("线索池还不够厚，先把待复核池作为人工获客入口一起处理。")
    if high_mentions < 40:
        actions.append("高分线索偏少，下一轮要继续强化中文跨境卖家、指纹浏览器和爬虫痛点词。")
    if review_mentions:
        actions.append(f"今天先人工抽检 {min(30, review_mentions)} 条待复核线索，确认是否有真实客户被挡住。")
    if weak_sources:
        actions.append("低产来源不要马上删除，先让它们跑满 2-3 轮；连续低产再降权。")
    if top_leads:
        actions.append(f"先处理前 {min(20, len(top_leads))} 条优先线索：打开原文、确认场景、补微信/QQ/TG/邮箱。")
    return actions[:7]
