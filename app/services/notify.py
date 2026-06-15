from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.models import Mention, Notification
from app.settings import get_settings


def format_wework_message(mention: Mention) -> str:
    return "\n".join(
        [
            f"新线索：{mention.title}",
            f"来源：{mention.source_name}",
            f"评分：{mention.score}",
            f"关键词：{mention.matched_keywords or '-'}",
            f"风险：{mention.risk_level}",
            f"状态：{mention.status}",
            f"建议：{mention.recommendation}",
            f"链接：{mention.canonical_url}",
        ]
    )


async def notify_wework(db: Session, mention: Mention) -> None:
    settings = get_settings()
    if not settings.wework_webhook_url:
        return

    payload = {
        "msgtype": "text",
        "text": {"content": format_wework_message(mention)},
    }

    status = "sent"
    response_text = ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.wework_webhook_url, json=payload)
            response_text = response.text[:1000]
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        response_text = str(exc)

    db.add(
        Notification(
            mention_id=mention.id,
            channel="wework",
            status=status,
            response=response_text,
        )
    )
    db.commit()
