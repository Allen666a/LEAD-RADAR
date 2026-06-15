from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectEvent
from app.services.analytics import KeywordAttribution, SourceAttribution, build_keyword_attribution, build_source_attribution
from app.services.cadence import CadenceTask, apply_cadence_action, load_cadence_tasks
from app.services.contact_status import has_real_contact
from app.services.feedback import FeedbackBoard, build_feedback_board, record_prospect_event
from app.services.learning import run_feedback_learning
from app.services.prospects import CUSTOMER_TYPE_LABELS
from app.services.session_collector import SessionPlatformDiagnostic, build_session_platform_diagnostics


P5_PLATFORM_HEALTH_RANK = {
    "healthy": 0,
    "no_output": 1,
    "quality_filtered": 2,
    "blocked": 3,
    "needs_login": 4,
    "not_ready": 5,
}

P5_PRIMARY_DOMESTIC_PLATFORMS = {
    "zhihu",
    "tieba",
    "xiaohongshu",
    "douyin",
    "bilibili",
    "weibo",
    "wearesellers",
    "amazon_seller_cn",
    "fobshanghai",
}

P5_PLATFORM_LABELS = {
    "zhihu": "知乎",
    "tieba": "百度贴吧",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "bilibili": "B站",
    "weibo": "微博",
    "wearesellers": "卖家论坛",
    "amazon_seller_cn": "亚马逊卖家论坛",
    "fobshanghai": "福步外贸",
    "v2ex": "V2EX",
    "segmentfault": "SegmentFault",
    "learnku": "LearnKu",
    "gitee": "Gitee",
    "github": "GitHub",
}

P5_ACTION_LABELS = {
    "contacted": "已触达",
    "wechat_added": "已加微信",
    "trial_sent": "已发测试",
    "schedule_1": "明天复访",
    "schedule_3": "3天后复访",
    "schedule_7": "7天后复查",
    "reviewed": "已人工审核",
    "no_contact": "暂无联系方式",
    "invalid": "无效",
    "won": "成交",
}

P5_TITLE = "今天该联系谁"
P5_SUBTITLE = "系统已经筛过一遍，只把今天最值得看的客户放在这里。"


def p5_prospect_display_name(prospect: Prospect) -> str:
    name = (prospect.display_name or "").strip()
    if name and not is_url_like_name(name):
        return name
    platform = (prospect.platform or "未知平台").strip()
    platform_label = P5_PLATFORM_LABELS.get(platform, platform)
    customer_type = CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type or "需求线索")
    return f"{platform_label} {customer_type} #{prospect.id}"


def is_url_like_name(name: str) -> bool:
    compact = name.strip().lower()
    if not compact:
        return False
    if compact.startswith(("http://", "https://", "www.")):
        return True
    first_token = compact.split()[0]
    if "/" in first_token and "." in first_token:
        return True
    parsed = urlparse("https://" + first_token if "://" not in first_token else first_token)
    return bool(parsed.netloc and "." in parsed.netloc and (parsed.path not in {"", "/"}))


@dataclass(frozen=True)
class P5Summary:
    active_prospects: int
    today_tasks: int
    hot_tasks: int
    missing_contact_tasks: int
    due_followups: int
    trial_pending: int
    feedback_events: int
    feedback_coverage: float
    session_blockers: int
    won: int
    invalid: int


@dataclass(frozen=True)
class P14Action:
    priority: int
    title: str
    reason: str
    next_step: str
    url: str
    kind: str
    count: int


@dataclass(frozen=True)
class P5Workbench:
    summary: P5Summary
    tasks: list[CadenceTask]
    p14_actions: list[P14Action]
    high_keywords: list[KeywordAttribution]
    pause_keywords: list[KeywordAttribution]
    source_warnings: list[SourceAttribution]
    feedback: FeedbackBoard
    platform_issues: list[SessionPlatformDiagnostic]
    recent_events: list[ProspectEvent]
    generated_at: datetime
    mode: str
    platform: str
    min_score: int


def build_p5_workbench(
    db: Session,
    mode: str = "today",
    platform: str = "domestic",
    min_score: int = 60,
    limit: int = 80,
) -> P5Workbench:
    tasks = load_cadence_tasks(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=limit,
    )
    if platform == "domestic":
        tasks = sorted(tasks, key=p5_task_rank, reverse=True)
    feedback = build_feedback_board(db)
    diagnostics = build_session_platform_diagnostics(db)
    platform_issues = sorted(
        [
            row
            for row in diagnostics
            if row.health not in {"healthy"} or row.failure_code or row.paused or row.inserted == 0
        ],
        key=lambda row: (
            P5_PLATFORM_HEALTH_RANK.get(row.health, 9),
            -row.high_quality_session,
            -row.inserted,
        ),
        reverse=True,
    )[:8]
    recent_events = list(
        db.scalars(
            select(ProspectEvent)
            .order_by(desc(ProspectEvent.created_at), desc(ProspectEvent.id))
            .limit(20)
        )
    )
    keyword_rows = build_keyword_attribution(db)
    source_rows = build_source_attribution(db)
    high_keywords = [
        row
        for row in keyword_rows
        if row.strategy_score >= 55 or row.high_value_mentions >= 2 or row.trial_sent or row.won
    ][:8]
    pause_keywords = [
        row
        for row in keyword_rows
        if row.mentions >= 3 and row.high_value_mentions == 0 and row.prospects == 0 and row.trial_sent == 0 and row.won == 0
    ][:8]
    source_warnings = [
        row
        for row in source_rows
        if (row.quality_status in {"blocked", "unstable", "low_yield"} or row.quality_score < 45)
    ][:8]
    today_end = datetime.combine(datetime.now().date(), time.max)
    active_query = (
        db.query(Prospect)
        .filter(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .filter(Prospect.status.notin_(["won", "invalid"]))
    )
    summary = P5Summary(
        active_prospects=active_query.count(),
        today_tasks=len(tasks),
        hot_tasks=sum(1 for task in tasks if task.priority >= 85 or task.prospect.lead_score >= 85),
        missing_contact_tasks=sum(1 for task in tasks if not has_real_contact(task.prospect)),
        due_followups=active_query.filter(Prospect.next_follow_up_at.is_not(None))
        .filter(Prospect.next_follow_up_at <= today_end)
        .count(),
        trial_pending=active_query.filter(Prospect.status == "trial_sent").count(),
        feedback_events=feedback.summary.events,
        feedback_coverage=feedback.summary.event_coverage,
        session_blockers=sum(1 for row in diagnostics if row.health not in {"healthy"}),
        won=db.query(Prospect).filter(Prospect.status == "won").count(),
        invalid=db.query(Prospect).filter(Prospect.status == "invalid").count(),
    )
    return P5Workbench(
        summary=summary,
        tasks=tasks,
        p14_actions=build_p14_actions(tasks, platform_issues, high_keywords, pause_keywords, source_warnings),
        high_keywords=high_keywords,
        pause_keywords=pause_keywords,
        source_warnings=source_warnings,
        feedback=feedback,
        platform_issues=platform_issues,
        recent_events=recent_events,
        generated_at=datetime.now(),
        mode=mode,
        platform=platform,
        min_score=min_score,
    )


def build_p14_actions(
    tasks: list[CadenceTask],
    platform_issues: list[SessionPlatformDiagnostic],
    high_keywords: list[KeywordAttribution],
    pause_keywords: list[KeywordAttribution],
    source_warnings: list[SourceAttribution],
) -> list[P14Action]:
    by_type: dict[str, list[CadenceTask]] = {}
    for task in tasks:
        by_type.setdefault(task.task_type, []).append(task)

    actions: list[P14Action] = []
    due = by_type.get("follow_up_due", [])
    first_touch = by_type.get("first_touch", [])
    contact_enrich = by_type.get("contact_enrich", [])
    trial_follow = by_type.get("trial_follow_up", [])
    send_trial = by_type.get("send_trial", [])
    compliance = by_type.get("compliance_review", [])
    blockers = [
        row
        for row in platform_issues
        if row.failure_code or row.health not in {"healthy", "可采集", "待试跑"}
    ]

    if due:
        actions.append(
            P14Action(
                100,
                "先处理到期复访",
                f"有 {len(due)} 个客户今天已经到复访时间，越拖越容易冷掉。",
                "打开今日复访队列，按上次上下文继续问测试结果、目标国家和当前痛点。",
                "/?mode=follow_up_due&platform=domestic&min_score=50",
                "follow_up_due",
                len(due),
            )
        )
    if first_touch:
        actions.append(
            P14Action(
                94,
                "联系已有触达入口的高分客户",
                f"有 {len(first_touch)} 个客户已经具备联系方式或可触达入口。",
                "先轻触达，不硬卖，确认平台、国家、账号量、并发量和现在的 IP 痛点。",
                "/?mode=first_touch&platform=domestic&min_score=50",
                "first_touch",
                len(first_touch),
            )
        )
    if contact_enrich:
        actions.append(
            P14Action(
                88,
                "补齐高价值线索联系方式",
                f"有 {len(contact_enrich)} 个高相关客户缺微信、QQ、Telegram、邮箱或手机号。",
                "进入补联系方式工作台，只查公开主页和公开搜索，补到后再进入今日跟进。",
                "/contact-workbench?mode=missing&platform=domestic&min_score=50",
                "contact_enrich",
                len(contact_enrich),
            )
        )
    if send_trial or trial_follow:
        actions.append(
            P14Action(
                84,
                "推进测试包和测试后复访",
                f"有 {len(send_trial) + len(trial_follow)} 个客户处于测试推进阶段。",
                "确认国家命中、连通率、稳定性、验证码/风控触发，再推进套餐或继续测试。",
                "/?mode=send_trial&platform=domestic&min_score=50",
                "trial",
                len(send_trial) + len(trial_follow),
            )
        )
    if compliance:
        actions.append(
            P14Action(
                80,
                "人工审核风险线索",
                f"有 {len(compliance)} 条线索需要先确认合法用途。",
                "不清楚用途前不要触达；只保留跨境运营、公开数据采集和环境测试等合规场景。",
                "/?mode=compliance_review&platform=domestic&min_score=50",
                "compliance",
                len(compliance),
            )
        )
    if blockers:
        actions.append(
            P14Action(
                72,
                "处理受阻平台",
                f"有 {len(blockers)} 个平台登录、风控或产出状态异常。",
                "去平台采集页检查登录态、验证码、频控和最近失败原因；不要反复高频重试。",
                "/session-collector",
                "platform_blocker",
                len(blockers),
            )
        )
    if source_warnings:
        actions.append(
            P14Action(
                64,
                "暂停低质或受阻来源",
                f"有 {len(source_warnings)} 个来源质量变差或失败较多。",
                "去来源管理看原因，低产出来源先降频或暂停，把精力放到高质量来源。",
                "/sources",
                "source_warning",
                len(source_warnings),
            )
        )
    if high_keywords:
        actions.append(
            P14Action(
                58,
                "放大高质量关键词",
                f"有 {len(high_keywords)} 个关键词带来高质量线索或客户。",
                "保留这些词，围绕同一客户场景扩展痛点词，而不是泛泛加词。",
                "/keywords",
                "keyword_scale",
                len(high_keywords),
            )
        )
    if pause_keywords:
        actions.append(
            P14Action(
                52,
                "暂停无产出关键词",
                f"有 {len(pause_keywords)} 个关键词只带来噪音，没有形成客户。",
                "暂停或改写这些词，避免继续抓教程、广告、旧内容和同行文章。",
                "/strategy",
                "keyword_pause",
                len(pause_keywords),
            )
        )
    if not actions:
        actions.append(
            P14Action(
                50,
                "先补国内平台新鲜线索",
                "当前没有足够明确的今日任务。",
                "先检查平台登录状态，跑小批量国内会话采集，再进入国内质检和补联系方式。",
                "/session-collector",
                "seed_pipeline",
                0,
            )
        )
    return sorted(actions, key=lambda row: row.priority, reverse=True)[:6]


def p5_task_rank(task: CadenceTask) -> tuple[int, int, int, int]:
    prospect = task.prospect
    primary_platform = 1 if prospect.platform in P5_PRIMARY_DOMESTIC_PLATFORMS else 0
    real_contact = 1 if has_real_contact(prospect) else 0
    high_value = 1 if prospect.high_value_count > 0 or prospect.lead_score >= 70 else 0
    return (
        primary_platform,
        real_contact,
        high_value,
        task.priority + prospect.lead_score,
    )


def apply_p5_action(db: Session, prospect_id: int, action: str, note: str = "") -> bool:
    ok = apply_cadence_action(db, prospect_id, action)
    if not ok:
        return False
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None and note.strip():
        record_prospect_event(db, prospect, "note_saved", action, note.strip(), commit=True)
    run_feedback_learning(db, apply=True)
    return True


def p5_csv_rows(workbench: P5Workbench) -> list[list[str | int]]:
    rows: list[list[str | int]] = [
        [
            "priority",
            "task_type",
            "display_name",
            "platform",
            "lead_score",
            "studio_persona",
            "status",
            "has_contact",
            "due",
            "next_action",
            "message",
            "evidence",
            "profile_url",
        ]
    ]
    for task in workbench.tasks:
        prospect = task.prospect
        rows.append(
            [
                task.priority,
                task.task_type,
                p5_prospect_display_name(prospect),
                prospect.platform,
                prospect.lead_score,
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type),
                prospect.status,
                "yes" if has_real_contact(prospect) else "no",
                task.due_label,
                task.primary_action_label,
                task.message,
                prospect.evidence or task.brief.account_summary,
                prospect.profile_url,
            ]
        )
    return rows
