from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contact_status import has_real_contact
from app.services.research import DOMESTIC_PLATFORMS, ResearchBrief, build_research_brief


TASK_LABELS = {
    "contact_enrich": "补联系方式",
    "compliance_review": "人工审核",
    "first_touch": "首触达",
    "follow_up_due": "到期复访",
    "send_trial": "发测试包",
    "trial_follow_up": "测试后跟进",
    "nurture": "培育观察",
}


@dataclass(frozen=True)
class CadenceTask:
    task_id: str
    task_type: str
    title: str
    priority: int
    due_label: str
    prospect: Prospect
    brief: ResearchBrief
    playbook: str
    message: str
    checklist: list[str]
    primary_action: str
    primary_action_label: str

    @property
    def label(self) -> str:
        return TASK_LABELS.get(self.task_type, self.task_type)

    @property
    def has_contact(self) -> bool:
        return has_real_contact(self.prospect)


def load_cadence_tasks(
    db: Session,
    mode: str = "today",
    platform: str = "domestic",
    min_score: int = 60,
    limit: int = 200,
) -> list[CadenceTask]:
    prospects = load_candidate_prospects(db, platform=platform, min_score=min_score, limit=limit * 2)
    tasks: list[CadenceTask] = []
    for prospect in prospects:
        mentions = load_mentions(db, prospect.id)
        brief = build_research_brief(prospect, mentions)
        task = build_task(prospect, brief)
        if mode != "all" and task.task_type != mode:
            if mode == "today" and task.task_type in {"nurture"}:
                continue
            elif mode != "today":
                continue
        tasks.append(task)
        if len(tasks) >= limit:
            break
    return sorted(tasks, key=lambda item: (item.priority, item.prospect.lead_score), reverse=True)


def load_candidate_prospects(
    db: Session,
    platform: str,
    min_score: int,
    limit: int,
) -> list[Prospect]:
    query = (
        select(Prospect)
        .where(Prospect.status.notin_(["won", "invalid"]))
        .where(Prospect.lead_score >= min_score)
        .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
    )
    if platform == "domestic":
        query = query.where(Prospect.platform.in_(DOMESTIC_PLATFORMS))
    elif platform != "all":
        query = query.where(Prospect.platform == platform)
    return list(
        db.scalars(
            query.order_by(
                Prospect.next_follow_up_at.is_(None),
                Prospect.next_follow_up_at,
                desc(Prospect.lead_score),
                desc(Prospect.last_seen_at),
            ).limit(limit)
        )
    )


def load_mentions(db: Session, prospect_id: int, limit: int = 8) -> list[Mention]:
    return list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect_id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(limit)
        )
    )


def build_task(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    now = datetime.now()
    has_contact = has_real_contact(prospect)
    due = prospect.next_follow_up_at

    if due and due <= now:
        return make_follow_up_due(prospect, brief)
    if prospect.risk_count or brief.deal_probability == "需审核":
        return make_compliance_review(prospect, brief)
    if not has_contact:
        return make_contact_enrich(prospect, brief)
    if prospect.status in {"new", "qualified"}:
        return make_first_touch(prospect, brief)
    if prospect.status in {"contacted", "wechat_added"}:
        return make_send_trial(prospect, brief)
    if prospect.status == "trial_sent":
        return make_trial_follow_up(prospect, brief)
    return make_nurture(prospect, brief)


def make_contact_enrich(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"contact_enrich:{prospect.id}",
        task_type="contact_enrich",
        title="先补真实联系方式",
        priority=min(100, brief.priority_score + 8),
        due_label="今天",
        prospect=prospect,
        brief=brief,
        playbook="先把客户变成可联系资产，再进入销售触达。",
        message="去补联系方式工作台查微信、QQ、Telegram、邮箱或手机号；只找到主页/公司名不算完成。",
        checklist=["打开原文和主页", "用推荐搜索词查联系方式", "补微信/QQ/TG/邮箱/手机号", "补不到就标记暂无联系方式"],
        primary_action="no_contact",
        primary_action_label="暂无联系方式",
    )


def make_compliance_review(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"compliance_review:{prospect.id}",
        task_type="compliance_review",
        title="先人工审核用途",
        priority=min(100, brief.priority_score + 6),
        due_label="今天",
        prospect=prospect,
        brief=brief,
        playbook="敏感场景先确认合法用途，不自动触达。",
        message="只承接公开数据采集、跨境运营环境测试、风控排查等合规用途；疑似攻击/黑产/盗号直接无效。",
        checklist=["看原文是否涉及高风险用途", "确认是否可合规服务", "保留人工审核备注", "不确定就不推进"],
        primary_action="reviewed",
        primary_action_label="已审核",
    )


def make_first_touch(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"first_touch:{prospect.id}",
        task_type="first_touch",
        title="今天首触达",
        priority=min(100, brief.priority_score + 10),
        due_label="今天",
        prospect=prospect,
        brief=brief,
        playbook="轻触达，不硬卖；先确认平台、国家、并发和当前痛点。",
        message=brief.opener,
        checklist=["确认用途合规", "问目标国家/平台", "问并发量和协议", "问当前代理痛点", "约定是否发测试包"],
        primary_action="contacted",
        primary_action_label="标记已触达",
    )


def make_follow_up_due(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"follow_up_due:{prospect.id}",
        task_type="follow_up_due",
        title="到期复访",
        priority=min(100, brief.priority_score + 12),
        due_label=prospect.next_follow_up_at.strftime("%Y-%m-%d %H:%M") if prospect.next_follow_up_at else "今天",
        prospect=prospect,
        brief=brief,
        playbook="复访要带上下文，不重复自我介绍。",
        message=prospect.follow_up_message or brief.opener,
        checklist=["回看上次备注", "确认是否测试过", "问阻塞点", "安排下一次复访或发测试包"],
        primary_action="schedule_3",
        primary_action_label="3天后复访",
    )


def make_send_trial(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"send_trial:{prospect.id}",
        task_type="send_trial",
        title="发小流量测试包",
        priority=min(100, brief.priority_score + 8),
        due_label="今天",
        prospect=prospect,
        brief=brief,
        playbook="只发小样本测试包，先验证国家命中、连通率、稳定性和风控触发。",
        message=prospect.trial_message or "可以先按你的目标国家和平台开一个小测试包，重点看连通率、稳定性和验证码/风控触发。",
        checklist=["确认目标国家", "确认协议 HTTP/SOCKS5", "确认并发量", "确认测试指标", "约定反馈时间"],
        primary_action="trial_sent",
        primary_action_label="标记已发测试",
    )


def make_trial_follow_up(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"trial_follow_up:{prospect.id}",
        task_type="trial_follow_up",
        title="测试后跟进",
        priority=min(100, brief.priority_score + 10),
        due_label=prospect.next_follow_up_at.strftime("%Y-%m-%d %H:%M") if prospect.next_follow_up_at else "今天",
        prospect=prospect,
        brief=brief,
        playbook="围绕测试结果推进，不泛聊。",
        message=prospect.closing_message or "测试结果如果连通率和稳定性 OK，下一步可以按实际量级配套餐。",
        checklist=["问连通率", "问验证码/风控触发", "问国家命中", "确认量级", "推进套餐或继续测试"],
        primary_action="schedule_3",
        primary_action_label="3天后复访",
    )


def make_nurture(prospect: Prospect, brief: ResearchBrief) -> CadenceTask:
    return CadenceTask(
        task_id=f"nurture:{prospect.id}",
        task_type="nurture",
        title="培育观察",
        priority=brief.priority_score,
        due_label="本周",
        prospect=prospect,
        brief=brief,
        playbook="信息还不够，先补证据，不占用高优先级销售时间。",
        message="继续观察新动态，补业务场景、目标国家和联系方式。",
        checklist=["补联系方式", "补目标国家", "补平台场景", "等新信号再触达"],
        primary_action="schedule_7",
        primary_action_label="7天后复查",
    )


def apply_cadence_action(db: Session, prospect_id: int, action: str) -> bool:
    prospect = db.get(Prospect, prospect_id)
    if prospect is None:
        return False

    now = datetime.now()
    event_note = f"cadence action: {action}"
    if action == "contacted":
        prospect.status = "contacted"
        prospect.last_contacted_at = now
        prospect.next_follow_up_at = now + timedelta(days=3)
        prospect.next_action = "已首触达，3 天后复访，确认平台、国家、并发量和当前代理痛点。"
    elif action == "wechat_added":
        prospect.status = "wechat_added"
        prospect.last_contacted_at = now
        prospect.next_follow_up_at = now + timedelta(days=1)
        prospect.next_action = "已加微信，下一步确认测试包需求。"
    elif action == "trial_sent":
        prospect.status = "trial_sent"
        prospect.last_contacted_at = now
        prospect.next_follow_up_at = now + timedelta(days=3)
        prospect.next_action = "已发测试包，复访测试结果：连通率、国家命中、稳定性、验证码/风控触发。"
    elif action == "reviewed":
        prospect.status = "qualified"
        prospect.next_action = "已人工审核，下一步确认合法业务用途和具体使用场景。"
    elif action == "no_contact":
        prospect.next_action = "暂无真实联系方式，后续通过补联系方式工作台、主页检查或私域导入补全。"
        prospect.follow_up_note = append_note(prospect.follow_up_note, "标记暂无真实联系方式。")
    elif action == "invalid":
        prospect.status = "invalid"
        prospect.next_action = "无效客户，停止跟进。"
    elif action == "won":
        prospect.status = "won"
        prospect.next_action = "已成交，记录来源和客户类型用于归因。"
    elif action.startswith("schedule_"):
        days = int(action.replace("schedule_", "", 1))
        if days not in {1, 3, 7, 14}:
            return False
        prospect.status = "follow_up"
        prospect.next_follow_up_at = now + timedelta(days=days)
        prospect.next_action = f"{days} 天后复访。"
    else:
        return False

    prospect.updated_at = now
    from app.services.feedback import record_prospect_event

    record_prospect_event(db, prospect, "outcome", action, event_note, commit=False)
    db.commit()
    return True


def append_note(old: str, new: str) -> str:
    old = (old or "").strip()
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {new}"
    if not old:
        return line
    return f"{old}\n{line}"
