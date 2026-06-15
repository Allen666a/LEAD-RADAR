from __future__ import annotations

from app.models import Mention
from app.schemas import RawItem


def build_outreach_message(item: RawItem, matched_keywords: list[str], score: int) -> str:
    keyword_text = "、".join(matched_keywords[:3]) if matched_keywords else "动态住宅 IP / 采集代理"

    if score >= 80:
        tone = "我看到你这边提到"
        close = "可以给你开一个小流量测试包，先按你的目标国家测连通率和稳定性。"
    else:
        tone = "看到你在讨论"
        close = "如果你需要，我可以先帮你判断适合用动态住宅、数据中心还是其他代理。"

    return "\n".join(
        [
            f"你好，{tone}「{keyword_text}」相关需求。",
            "我们主要做海外动态住宅 IP，适合公开网页采集、跨境电商价格/库存监控、SERP 采集这类需要轮换出口 IP 的场景。",
            "支持 HTTP/SOCKS5、国家选择、粘性会话和小流量测试。",
            close,
        ]
    )


def fallback_outreach_message(mention: Mention) -> str:
    matched = [part.strip() for part in mention.matched_keywords.split(",") if part.strip()]
    raw_item = RawItem(
        source_name=mention.source_name,
        source_kind=mention.source_kind,
        title=mention.title,
        url=mention.canonical_url,
        author=mention.author,
        content=mention.content,
        published_at=mention.published_at,
    )
    return build_outreach_message(raw_item, matched, mention.score)
