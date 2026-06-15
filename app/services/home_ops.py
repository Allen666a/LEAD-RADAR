from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import CandidateItem, Mention, Prospect
from app.services.acquisition_hub import SourceCoverage, build_source_coverage
from app.services.contact_status import has_real_contact
from app.services.contact_workbench import DOMESTIC_PLATFORMS
from app.services.feedback_ops import build_feedback_ops_board
from app.services.p5_workbench import build_p5_workbench, p5_prospect_display_name


FRESH_CUTOFF = datetime(2026, 1, 1)


@dataclass(frozen=True)
class HomeStep:
    number: int
    title: str
    description: str
    metric: int
    metric_label: str
    href: str
    button: str
    state: str
    icon: str
    note: str


@dataclass(frozen=True)
class HomeLead:
    id: int
    title: str
    platform: str
    score: int
    customer_type: str
    href: str
    time_label: str
    next_step: str


@dataclass(frozen=True)
class HomeGuidance:
    title: str
    description: str
    href: str
    button: str
    tone: str
    icon: str


@dataclass(frozen=True)
class HomePlatformAlert:
    platform: str
    label: str
    problem: str
    next_step: str
    href: str


@dataclass(frozen=True)
class HomeFunnelStats:
    candidates: int
    fresh_candidates: int
    review_candidates: int
    rejected_candidates: int
    usable_mentions: int
    high_score_mentions: int


@dataclass(frozen=True)
class HomeOpsBoard:
    steps: list[HomeStep]
    top_leads: list[HomeLead]
    today_count: int
    missing_contact_count: int
    feedback_count: int
    fresh_leads: int
    high_score_leads: int
    due_followups: int
    blocked_platforms: int
    primary_action: HomeStep
    guidance: list[HomeGuidance]
    platform_alerts: list[HomePlatformAlert]
    source_coverage: list[SourceCoverage]
    funnel: HomeFunnelStats


def build_home_ops_board(db: Session) -> HomeOpsBoard:
    p5 = build_p5_workbench(db, mode="today", platform="domestic", min_score=50, limit=40)
    feedback_ops = build_feedback_ops_board(db, limit=8)
    missing_contact_count = count_missing_contacts(db)
    fresh_leads = count_fresh_mentions(db)
    high_score_leads = count_high_score_mentions(db)

    steps = [
        HomeStep(
            number=1,
            title="采集线索",
            description="先确认平台登录和采集状态，再跑国内平台里的 2026 年真实需求。",
            metric=fresh_leads,
            metric_label="条可筛选",
            href="/session-collector",
            button="检查采集",
            state="ready" if fresh_leads or p5.summary.session_blockers <= 0 else "empty",
            icon="ti ti-login-2",
            note="国内平台优先，遇到验证、频控或低质输出先停下来处理。",
        ),
        HomeStep(
            number=2,
            title="筛选线索",
            description="只看动态住宅 IP 场景匹配、时间在 2026 年后的高相关需求。",
            metric=high_score_leads,
            metric_label="条高分",
            href="/leads?segment=all&scope=all&pool=usable&min_score=0",
            button="去筛线索",
            state="ready" if high_score_leads else "empty",
            icon="ti ti-search",
            note="先排除旧帖、教程、同行文章和泛技术讨论，再进入补联系方式。",
        ),
        HomeStep(
            number=3,
            title="补联系方式",
            description="只处理高相关但缺微信、QQ、Telegram、邮箱的目标。",
            metric=missing_contact_count,
            metric_label="个待补",
            href="/contact-workbench?mode=missing&platform=domestic&min_score=50",
            button="去补联系方式",
            state="ready" if missing_contact_count else "empty",
            icon="ti ti-address-book",
            note="不是公司销售流程，优先找个人、小团队和工作室可触达入口。",
        ),
        HomeStep(
            number=4,
            title="跟进和复盘",
            description="把可联系目标推进到私域，并记录成交、测试、无效原因。",
            metric=p5.summary.due_followups or feedback_ops.missing_feedback,
            metric_label="个待处理",
            href="/pipeline",
            button="去跟进",
            state="ready" if p5.summary.due_followups or feedback_ops.missing_feedback else "empty",
            icon="ti ti-list-check",
            note="不要只堆线索，必须把触达结果记回来，系统才会越筛越准。",
        ),
    ]
    primary_action = choose_primary_action(steps, blocked_platforms=p5.summary.session_blockers)
    return HomeOpsBoard(
        steps=steps,
        top_leads=build_top_leads(p5),
        today_count=p5.summary.today_tasks,
        missing_contact_count=missing_contact_count,
        feedback_count=feedback_ops.missing_feedback,
        fresh_leads=fresh_leads,
        high_score_leads=high_score_leads,
        due_followups=p5.summary.due_followups,
        blocked_platforms=p5.summary.session_blockers,
        primary_action=primary_action,
        guidance=build_guidance(
            fresh_leads=fresh_leads,
            missing_contact_count=missing_contact_count,
            feedback_count=feedback_ops.missing_feedback,
            today_count=p5.summary.today_tasks,
            blocked_platforms=p5.summary.session_blockers,
        ),
        platform_alerts=build_platform_alerts(p5),
        source_coverage=build_source_coverage(db),
        funnel=build_funnel_stats(db),
    )


def build_funnel_stats(db: Session) -> HomeFunnelStats:
    candidates = int(db.scalar(select(func.count(CandidateItem.id))) or 0)
    fresh_candidates = int(
        db.scalar(
            select(func.count(CandidateItem.id)).where(CandidateItem.published_at >= FRESH_CUTOFF)
        )
        or 0
    )
    review_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "review")) or 0
    )
    rejected_candidates = int(
        db.scalar(select(func.count(CandidateItem.id)).where(CandidateItem.status == "rejected")) or 0
    )
    usable_mentions = int(
        db.scalar(select(func.count(Mention.id)).where(Mention.status != "invalid")) or 0
    )
    high_score_mentions = int(
        db.scalar(
            select(func.count(Mention.id))
            .where(Mention.status != "invalid")
            .where(Mention.score >= 80)
            .where(Mention.published_at >= FRESH_CUTOFF)
        )
        or 0
    )
    return HomeFunnelStats(
        candidates=candidates,
        fresh_candidates=fresh_candidates,
        review_candidates=review_candidates,
        rejected_candidates=rejected_candidates,
        usable_mentions=usable_mentions,
        high_score_mentions=high_score_mentions,
    )


def choose_primary_action(steps: list[HomeStep], *, blocked_platforms: int) -> HomeStep:
    if blocked_platforms > 0:
        return steps[0]
    for step in steps:
        if step.number != 1 and step.metric > 0:
            return step
    return steps[0]


def count_fresh_mentions(db: Session) -> int:
    return (
        db.query(Mention)
        .filter(Mention.status != "invalid")
        .filter(Mention.score >= 50)
        .filter(Mention.published_at >= FRESH_CUTOFF)
        .count()
    )


def count_high_score_mentions(db: Session) -> int:
    return (
        db.query(Mention)
        .filter(Mention.status != "invalid")
        .filter(Mention.score >= 80)
        .filter(Mention.published_at >= FRESH_CUTOFF)
        .count()
    )


def count_missing_contacts(db: Session) -> int:
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.status.notin_(["won", "invalid"]))
            .where(Prospect.lead_score >= 50)
            .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
            .where(Prospect.platform.in_(DOMESTIC_PLATFORMS))
            .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(800)
        )
    )
    return sum(1 for prospect in prospects if not has_real_contact(prospect))


def build_top_leads(p5) -> list[HomeLead]:
    rows: list[HomeLead] = []
    for task in p5.tasks[:5]:
        prospect = task.prospect
        rows.append(
            HomeLead(
                id=prospect.id,
                title=p5_prospect_display_name(prospect),
                platform=prospect.platform or "unknown",
                score=max(task.priority, prospect.lead_score or 0),
                customer_type=prospect.customer_type or "unknown",
                href=f"/prospects/{prospect.id}",
                time_label=task.due_label,
                next_step=task.label,
            )
        )
    return rows


def build_guidance(
    *,
    fresh_leads: int,
    missing_contact_count: int,
    feedback_count: int,
    today_count: int,
    blocked_platforms: int,
) -> list[HomeGuidance]:
    rows: list[HomeGuidance] = []
    if fresh_leads <= 0:
        rows.append(
            HomeGuidance(
                title="还没有合格新线索",
                description="先跑国内公开源；如果要采知乎、小红书、抖音，先确认平台登录状态。",
                href="/leads?segment=all&scope=all&pool=usable&min_score=0",
                button="去找线索",
                tone="warn",
                icon="ti ti-search",
            )
        )
    if blocked_platforms > 0:
        rows.append(
            HomeGuidance(
                title="有平台需要处理",
                description="出现登录、验证、频控或低质过滤时，不要连续重试，先看平台状态。",
                href="/session-collector",
                button="查看平台状态",
                tone="warn",
                icon="ti ti-alert-triangle",
            )
        )
    if fresh_leads > 0 and missing_contact_count > 0:
        rows.append(
            HomeGuidance(
                title="优先补联系方式",
                description="线索没有微信、QQ、Telegram 或邮箱，就还不能进入真正跟进。",
                href="/contact-workbench?mode=missing&platform=domestic&min_score=50",
                button="去补联系方式",
                tone="good",
                icon="ti ti-address-book",
            )
        )
    if feedback_count > 0:
        rows.append(
            HomeGuidance(
                title="补上真实结果",
                description="已触达或已测试的线索需要记录成交、无效和原因，系统才会越筛越准。",
                href="/feedback",
                button="记录结果",
                tone="good",
                icon="ti ti-refresh-dot",
            )
        )
    if today_count <= 0 and fresh_leads > 0 and missing_contact_count <= 0 and feedback_count <= 0:
        rows.append(
            HomeGuidance(
                title="降低门槛再看一轮",
                description="当前没有今日任务，可以先降低最低分，或者换 TikTok、亚马逊、爬虫场景查看。",
                href="/leads?segment=all&scope=all&pool=usable&min_score=0",
                button="放宽条件",
                tone="neutral",
                icon="ti ti-adjustments",
            )
        )
    return rows[:4] or [
        HomeGuidance(
            title="今天从找线索开始",
            description="先看是否有 2026 年后的动态住宅 IP 场景，再进入补联系方式和反馈闭环。",
            href="/leads?segment=all&scope=all&pool=usable&min_score=0",
            button="去找线索",
            tone="neutral",
            icon="ti ti-search",
        )
    ]


def build_platform_alerts(p5) -> list[HomePlatformAlert]:
    alerts: list[HomePlatformAlert] = []
    for row in p5.platform_issues[:4]:
        problem = row.diagnostic_label or row.health or row.failure_code or row.login_label
        next_step = row.next_step or row.action or "先查看该平台状态，再决定是否登录、试跑或暂停。"
        alerts.append(
            HomePlatformAlert(
                platform=row.platform,
                label=row.label,
                problem=problem,
                next_step=next_step,
                href=f"/session-collector#platform-{row.platform}",
            )
        )
    return alerts
