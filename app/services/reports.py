from __future__ import annotations

from datetime import datetime, time

import httpx
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import Mention, Prospect, Source
from app.services.p5_workbench import build_p5_workbench
from app.services.prospects import CUSTOMER_TYPE_LABELS
from app.services.signals import HIGH_VALUE_SIGNALS
from app.settings import get_settings


def build_daily_report(db: Session) -> str:
    today_start = datetime.combine(datetime.now().date(), time.min)
    today_end = datetime.combine(datetime.now().date(), time.max)

    new_mentions = db.query(Mention).filter(Mention.discovered_at >= today_start).count()
    high_value_mentions = (
        db.query(Mention)
        .filter(Mention.discovered_at >= today_start)
        .filter(Mention.signal_type.in_(HIGH_VALUE_SIGNALS))
        .filter(Mention.score >= 60)
        .count()
    )
    pipeline_total = (
        db.query(Prospect)
        .filter(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .filter(Prospect.lead_score >= 60)
        .filter(Prospect.status.notin_(["won", "invalid"]))
        .count()
    )
    due_followups = (
        db.query(Prospect)
        .filter(Prospect.next_follow_up_at.is_not(None))
        .filter(Prospect.next_follow_up_at <= today_end)
        .filter(Prospect.status.notin_(["won", "invalid"]))
        .count()
    )
    top_prospects = (
        db.query(Prospect)
        .filter(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .filter(Prospect.lead_score >= 60)
        .filter(Prospect.status.notin_(["won", "invalid"]))
        .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
        .limit(5)
        .all()
    )
    blocked_sources = (
        db.query(Source)
        .filter(Source.quality_status.in_(["blocked", "unstable"]))
        .order_by(Source.quality_score, desc(Source.failure_count))
        .limit(5)
        .all()
    )
    excellent_sources = (
        db.query(Source)
        .filter(Source.quality_status == "excellent")
        .order_by(desc(Source.quality_score))
        .limit(5)
        .all()
    )

    p5 = build_p5_workbench(db, mode="today", platform="domestic", min_score=60, limit=80)

    lines = [
        f"Lead Radar 日报｜{datetime.now().strftime('%Y-%m-%d')}",
        "",
        f"新增线索：{new_mentions}",
        f"新增高价值信号：{high_value_mentions}",
        f"可跟进客户：{pipeline_total}",
        f"今日到期复访：{due_followups}",
        "",
        "今日优先客户：",
    ]
    lines.extend(
        [
            "",
            "今日获客作战：",
            f"- 今日私聊目标：{p5.summary.today_tasks}",
            f"- 高优先级行动：{p5.summary.hot_tasks}",
            f"- 缺联系方式行动：{p5.summary.missing_contact_tasks}",
            f"- 反馈事件：{p5.summary.feedback_events}",
            f"- 反馈覆盖率：{p5.summary.feedback_coverage:.1%}",
            f"- 会话采集阻塞平台：{p5.summary.session_blockers}",
        ]
    )

    if p5.feedback.recommendations:
        lines.append("")
        lines.append("获客优先建议：")
        for item in p5.feedback.recommendations[:4]:
            lines.append(f"- {item}")

    if p5.platform_issues:
        lines.append("")
        lines.append("采集平台阻塞：")
        for item in p5.platform_issues[:5]:
            lines.append(f"- {item.label}: {item.health} / {item.failure_code or item.login_label} / {item.action}")

    if top_prospects:
        for index, prospect in enumerate(top_prospects, start=1):
            action = stage_action_for_report(prospect)
            lines.append(
                f"{index}. [{prospect.lead_score}] {prospect.display_name}｜{CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type)}｜{action}"
            )
    else:
        lines.append("- 暂无")

    lines.append("")
    lines.append("优质来源：")
    if excellent_sources:
        for source in excellent_sources:
            lines.append(f"- [{source.quality_score}] {source.name}")
    else:
        lines.append("- 暂无")

    lines.append("")
    lines.append("受阻来源：")
    if blocked_sources:
        for source in blocked_sources:
            lines.append(f"- [{source.quality_score}] {source.name}：{(source.last_error or '-')[:80]}")
    else:
        lines.append("- 暂无")

    return "\n".join(lines)


def stage_action_for_report(prospect: Prospect) -> str:
    if prospect.next_action:
        return prospect.next_action
    if prospect.status == "new":
        return "发首触达话术"
    if prospect.status in {"qualified", "contacted"}:
        return "发二次跟进话术，确认目标国家/平台/并发量"
    if prospect.status == "trial_sent":
        return "按测试包结果复访，确认稳定性和下一档套餐"
    if prospect.status == "wechat_added":
        return "微信内推进测试包配置"
    if prospect.status == "follow_up":
        return "按复访话术催进度"
    return prospect.suggested_action or "待安排下一步"


async def send_daily_report_wework(db: Session) -> dict[str, str]:
    settings = get_settings()
    if not settings.wework_webhook_url:
        return {"status": "skipped", "message": "WEWORK_WEBHOOK_URL 未配置"}

    payload = {"msgtype": "text", "text": {"content": build_daily_report(db)}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.wework_webhook_url, json=payload)
            response.raise_for_status()
            return {"status": "sent", "message": response.text[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "message": str(exc)}
