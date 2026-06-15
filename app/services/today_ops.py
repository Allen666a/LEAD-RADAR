from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Prospect
from app.services.cadence import CadenceTask
from app.services.contact_status import has_real_contact
from app.services.p5_workbench import P5Workbench, build_p5_workbench, p5_prospect_display_name


TASK_ORDER = {
    "follow_up_due": 0,
    "trial_follow_up": 1,
    "send_trial": 2,
    "first_touch": 3,
    "contact_enrich": 4,
    "compliance_review": 5,
    "nurture": 6,
}

QUOTAS = {
    "follow_up_due": 2,
    "trial_follow_up": 2,
    "send_trial": 2,
    "first_touch": 2,
    "contact_enrich": 1,
    "compliance_review": 1,
}


@dataclass(frozen=True)
class TodayStats:
    focus_count: int
    contactable_count: int
    missing_contact_count: int
    due_count: int
    hot_count: int
    feedback_coverage: float


@dataclass(frozen=True)
class TodayFocusTask:
    task: CadenceTask
    display_name: str
    task_label: str
    stage_label: str
    contact_label: str
    primary_url: str
    secondary_url: str
    why: str
    outcome_hint: str


@dataclass(frozen=True)
class TodayBoard:
    workbench: P5Workbench
    focus_tasks: list[TodayFocusTask]
    backlog_count: int
    stats: TodayStats
    generated_at: datetime
    filters: dict[str, str | int]


def build_today_board(
    db: Session,
    mode: str = "today",
    platform: str = "domestic",
    min_score: int = 50,
    daily_limit: int = 5,
) -> TodayBoard:
    workbench = build_p5_workbench(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=80,
    )
    selected = select_focus_tasks(workbench.tasks, daily_limit=max(1, min(8, daily_limit)))
    focus = [build_focus_task(task) for task in selected]
    stats = TodayStats(
        focus_count=len(focus),
        contactable_count=sum(1 for task in focus if has_real_contact(task.task.prospect)),
        missing_contact_count=sum(1 for task in focus if not has_real_contact(task.task.prospect)),
        due_count=sum(1 for task in focus if task.task.task_type in {"follow_up_due", "trial_follow_up"}),
        hot_count=sum(1 for task in focus if task.task.priority >= 85 or task.task.prospect.lead_score >= 85),
        feedback_coverage=workbench.summary.feedback_coverage,
    )
    return TodayBoard(
        workbench=workbench,
        focus_tasks=focus,
        backlog_count=max(0, len(workbench.tasks) - len(focus)),
        stats=stats,
        generated_at=datetime.now(),
        filters={
            "mode": mode,
            "platform": platform,
            "min_score": min_score,
            "daily_limit": daily_limit,
        },
    )


def select_focus_tasks(tasks: list[CadenceTask], daily_limit: int) -> list[CadenceTask]:
    ranked = sorted(tasks, key=task_rank, reverse=True)
    selected: list[CadenceTask] = []
    selected_ids: set[int] = set()

    for task_type, quota in QUOTAS.items():
        for task in ranked:
            if len(selected) >= daily_limit:
                return selected
            if task.task_type != task_type or task.prospect.id in selected_ids:
                continue
            selected.append(task)
            selected_ids.add(task.prospect.id)
            if sum(1 for item in selected if item.task_type == task_type) >= quota:
                break

    for task in ranked:
        if len(selected) >= daily_limit:
            break
        if task.prospect.id in selected_ids:
            continue
        selected.append(task)
        selected_ids.add(task.prospect.id)

    return sorted(selected, key=task_rank, reverse=True)


def task_rank(task: CadenceTask) -> tuple[int, int, int, int, int]:
    prospect = task.prospect
    contactable = 1 if has_real_contact(prospect) else 0
    due = 1 if task.task_type in {"follow_up_due", "trial_follow_up"} else 0
    high_value = 1 if task.priority >= 85 or prospect.lead_score >= 85 else 0
    task_weight = 10 - TASK_ORDER.get(task.task_type, 9)
    return (
        due,
        contactable,
        high_value,
        task_weight,
        task.priority + prospect.lead_score,
    )


def build_focus_task(task: CadenceTask) -> TodayFocusTask:
    prospect = task.prospect
    has_contact = has_real_contact(prospect)
    primary_url = primary_action_url(task)
    secondary_url = f"/prospects/{prospect.id}"
    return TodayFocusTask(
        task=task,
        display_name=p5_prospect_display_name(prospect),
        task_label=task.label,
        stage_label=stage_label(prospect),
        contact_label="可触达" if has_contact else "缺联系方式",
        primary_url=primary_url,
        secondary_url=secondary_url,
        why=why_this_task(task),
        outcome_hint=outcome_hint(task),
    )


def primary_action_url(task: CadenceTask) -> str:
    prospect = task.prospect
    if task.task_type == "contact_enrich":
        return f"/contact-workbench?mode=missing&platform={prospect.platform}&min_score=0"
    if task.task_type == "compliance_review":
        return f"/prospects/{prospect.id}"
    return f"/prospects/{prospect.id}"


def stage_label(prospect: Prospect) -> str:
    labels = {
        "new": "新客户",
        "qualified": "已筛选",
        "contacted": "已触达",
        "wechat_added": "已加微信",
        "trial_sent": "已发测试",
        "follow_up": "待复访",
        "won": "已成交",
        "invalid": "无效",
    }
    return labels.get(prospect.status, prospect.status or "新客户")


def why_this_task(task: CadenceTask) -> str:
    prospect = task.prospect
    if task.task_type == "follow_up_due":
        return "复访已经到期，继续拖会让线索变冷。"
    if task.task_type == "trial_follow_up":
        return "客户已经进入测试后阶段，应该围绕连通率、国家命中和风控反馈推进。"
    if task.task_type == "send_trial":
        return "已有联系方式和初步意向，下一步应该用小流量测试验证需求。"
    if task.task_type == "first_touch":
        return "客户可触达且场景匹配，适合今天轻触达确认平台、国家和并发。"
    if task.task_type == "contact_enrich":
        return "线索有价值但缺真实联系方式，先补联系方式比继续扩量更有用。"
    if task.task_type == "compliance_review":
        return "存在风险或用途不明，先人工审核，避免把精力花在不该跟进的人身上。"
    return prospect.next_action or task.playbook


def outcome_hint(task: CadenceTask) -> str:
    if task.task_type == "contact_enrich":
        return "补到联系方式就保存；补不到就标记暂无联系方式或 3 天后复查。"
    if task.task_type == "first_touch":
        return "触达后记录已触达；对方愿意测试就下一步发测试包。"
    if task.task_type == "send_trial":
        return "发完测试包后记录已发测试，并安排 3 天后跟进。"
    if task.task_type in {"follow_up_due", "trial_follow_up"}:
        return "记录复访结果：继续、发测试、成交或无效。"
    if task.task_type == "compliance_review":
        return "合规就标记已审核；不合规或疑似黑产直接无效。"
    return "处理后一定记录结果，否则系统不会变准。"
