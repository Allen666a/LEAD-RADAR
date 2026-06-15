from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, Mention, Prospect
from app.services.contact_status import has_real_contact
from app.services.contact_workbench import DOMESTIC_PLATFORMS, load_top_mention
from app.services.icp_audit import build_icp_quality_audit
from app.services.icp_quality import evaluate_icp
from app.services.platforms import build_platform_statuses
from app.services.session_collector import build_session_platform_diagnostics


@dataclass(frozen=True)
class OpsStats:
    runnable_platforms: int
    blocked_platforms: int
    demand_signals: int
    b2b_accounts: int
    b2b_missing_contact: int
    a_leads: int
    b_leads: int
    risk_leads: int
    contactable_leads: int


@dataclass(frozen=True)
class PlatformOpsRow:
    platform: str
    label: str
    state: str
    login_state: str
    health: str
    qualified: int
    contactable: int
    missing_contact: int
    action: str
    next_url: str
    reason: str


@dataclass(frozen=True)
class FunnelRow:
    prospect: Prospect
    mention: Mention | None
    tier: str
    label: str
    score: int
    route: str
    reason: str
    next_action: str


@dataclass(frozen=True)
class AcquisitionOpsBoard:
    stats: OpsStats
    platform_rows: list[PlatformOpsRow]
    funnel_rows: list[FunnelRow]
    recommendations: list[str]
    generated_at: str


def build_acquisition_ops_board(db: Session) -> AcquisitionOpsBoard:
    session_rows = {row.platform: row for row in build_session_platform_diagnostics(db)}
    platform_statuses = {row.key: row for row in build_platform_statuses(db)}
    icp_audit = build_icp_quality_audit(db)
    icp_platforms = {row["platform"]: row for row in icp_audit["platforms"]}

    platform_rows = build_platform_rows(session_rows, platform_statuses, icp_platforms)
    funnel_rows = build_funnel_rows(db)
    demand_signals = db.scalar(
        select(func.count(Mention.id)).where(Mention.mode == "demand_radar", Mention.priority_score >= 60)
    ) or 0
    b2b_accounts = db.scalar(select(func.count(CompanyProfile.id))) or 0
    b2b_missing = db.scalar(
        select(func.count(CompanyProfile.id)).where(CompanyProfile.contact_status != "contactable")
    ) or 0
    stats = OpsStats(
        runnable_platforms=sum(1 for row in platform_rows if row.state == "可运行"),
        blocked_platforms=sum(1 for row in platform_rows if row.state in {"需处理", "未就绪"}),
        demand_signals=int(demand_signals),
        b2b_accounts=int(b2b_accounts),
        b2b_missing_contact=int(b2b_missing),
        a_leads=sum(1 for row in funnel_rows if row.tier == "A"),
        b_leads=sum(1 for row in funnel_rows if row.tier == "B"),
        risk_leads=sum(1 for row in funnel_rows if row.tier == "风险"),
        contactable_leads=sum(1 for row in funnel_rows if has_real_contact(row.prospect)),
    )
    return AcquisitionOpsBoard(
        stats=stats,
        platform_rows=platform_rows,
        funnel_rows=funnel_rows,
        recommendations=build_board_recommendations(
            platform_rows,
            funnel_rows,
            icp_audit.get("recommendations", []),
            int(demand_signals),
            int(b2b_accounts),
            int(b2b_missing),
        ),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def build_platform_rows(session_rows, platform_statuses, icp_platforms) -> list[PlatformOpsRow]:
    keys = [
        "zhihu",
        "tieba",
        "xiaohongshu",
        "douyin",
        "bilibili",
        "weibo",
        "v2ex",
        "segmentfault",
        "wearesellers",
        "amazon_seller_cn",
        "csdn",
        "oschina",
        "cnblogs",
        "gitee",
    ]
    rows: list[PlatformOpsRow] = []
    for key in keys:
        session = session_rows.get(key)
        status = platform_statuses.get(key)
        icp = icp_platforms.get(key, {})
        qualified = int(icp.get("qualified", 0) or 0)
        contactable = int(icp.get("contactable", 0) or 0)
        missing_contact = int(icp.get("enrich", 0) or 0)
        state, action, next_url, reason = platform_action(key, session, status, qualified, missing_contact)
        rows.append(
            PlatformOpsRow(
                platform=key,
                label=(session.label if session else status.name if status else key),
                state=state,
                login_state=session.login_label if session else "-",
                health=session.health if session else (status.status if status else "观察"),
                qualified=qualified,
                contactable=contactable,
                missing_contact=missing_contact,
                action=action,
                next_url=next_url,
                reason=reason,
            )
        )
    return sorted(rows, key=platform_sort_key)


def platform_action(key: str, session, status, qualified: int, missing_contact: int) -> tuple[str, str, str, str]:
    if session:
        if session.login_state == "logged_in":
            if session.health in {"可采集", "待试跑", "低产"}:
                return "可运行", "跑低频会话采集", "/session-collector", session.action
            return "需处理", "检查状态", "/session-collector", session.action
        if session.login_state in {"blocked", "profile_open", "error"}:
            return "需处理", "处理登录/验证", "/session-collector", session.action
        return "未就绪", "登录账号", f"/session-collector", session.action

    if qualified or missing_contact:
        return "可运行", "去补联系方式", f"/contact-workbench?platform={key}&mode=missing&min_score=50", "已有高匹配线索，优先补触达信息。"
    if status and status.status in {"有效", "有数据"}:
        return "观察", "看平台效果", "/performance", status.recommended_action
    if key == "gitee":
        return "暂停", "暂缓或配 Token", "/platforms", "当前低产且易受限，先不要作为国内获客主源。"
    return "观察", "小批量观察", "/platforms", status.recommended_action if status else "先观察来源质量。"


def platform_sort_key(row: PlatformOpsRow) -> tuple[int, int, int, str]:
    state_rank = {"可运行": 0, "需处理": 1, "未就绪": 2, "观察": 3, "暂停": 4}
    return (state_rank.get(row.state, 9), -row.qualified, -row.missing_contact, row.platform)


def build_funnel_rows(db: Session, limit: int = 120) -> list[FunnelRow]:
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.status.notin_(["won", "invalid"]))
            .where(Prospect.platform.in_(DOMESTIC_PLATFORMS))
            .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(limit * 3)
        )
    )
    rows: list[FunnelRow] = []
    for prospect in prospects:
        mention = load_top_mention(db, prospect.id)
        decision = evaluate_icp(prospect, mention)
        tier, label, next_action = classify_funnel(prospect, decision)
        if tier == "C":
            continue
        rows.append(
            FunnelRow(
                prospect=prospect,
                mention=mention,
                tier=tier,
                label=label,
                score=decision.score,
                route=decision.route,
                reason=decision.reason,
                next_action=next_action,
            )
        )
        if len(rows) >= limit:
            break
    return sorted(rows, key=funnel_sort_key)


def classify_funnel(prospect: Prospect, decision) -> tuple[str, str, str]:
    contactable = has_real_contact(prospect)
    if decision.status == "risk":
        return "风险", "人工合规审核", "先确认业务用途，风险不清楚前不要触达。"
    if contactable and decision.score >= 60:
        return "A", "今天可触达", "进入今日跟进，先确认平台、国家、账号量和当前 IP 痛点。"
    if decision.route == "contact_enrich" and decision.score >= 60:
        return "A", "优先补联系方式", "查作者主页、同名账号、私域记录；补到联系方式后进入今日跟进。"
    if decision.route == "observe" or decision.score >= 45:
        return "B", "观察/补证据", "等新动态或补充上下文，暂不占用销售精力。"
    return "C", "低价值", "自动过滤或留存观察。"


def funnel_sort_key(row: FunnelRow) -> tuple[int, int, int]:
    rank = {"A": 0, "风险": 1, "B": 2, "C": 3}
    return (rank.get(row.tier, 9), -row.score, -row.prospect.lead_score)


def build_board_recommendations(
    platform_rows: list[PlatformOpsRow],
    funnel_rows: list[FunnelRow],
    audit_recommendations: list[str],
    demand_signals: int = 0,
    b2b_accounts: int = 0,
    b2b_missing: int = 0,
) -> list[str]:
    recs: list[str] = []
    runnable = [row for row in platform_rows if row.state == "可运行"]
    blocked = [row for row in platform_rows if row.state == "需处理"]
    a_rows = [row for row in funnel_rows if row.tier == "A"]
    if blocked:
        recs.append("先处理受阻平台：" + "、".join(row.label for row in blocked[:3]))
    if runnable:
        recs.append("今天可跑：" + "、".join(row.label for row in runnable[:4]))
    if demand_signals:
        recs.append(f"需求雷达有 {demand_signals} 条中高分痛点信号，先筛风险和噪音。")
    if b2b_accounts:
        recs.append(f"B2B 客户库已有 {b2b_accounts} 个公司级客户，其中 {b2b_missing} 个待补联系方式。")
    else:
        recs.append("B2B 客户库为空：先运行公司回填，把线索升级为公司级客户。")
    if a_rows:
        recs.append(f"今天先处理 {len(a_rows)} 条 A 类线索，优先补联系方式和首触达。")
    if not runnable:
        recs.append("当前没有可运行会话平台：先登录 1-2 个国内平台并检查状态。")
    for item in audit_recommendations:
        if item not in recs:
            recs.append(item)
    return recs[:6]
