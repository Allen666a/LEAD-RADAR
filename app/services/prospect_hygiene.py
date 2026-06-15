from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contact_status import has_real_contact
from app.services.freshness import MIN_LEAD_YEAR
from app.services.lead_quality import evaluate_lead_quality


DOMESTIC_PLATFORMS = {
    "zhihu",
    "tieba",
    "xiaohongshu",
    "douyin",
    "wearesellers",
    "v2ex",
    "segmentfault",
    "learnku",
    "gitee",
    "bilibili",
    "weibo",
    "amazon_seller_cn",
    "fobshanghai",
    "csdn",
    "cnblogs",
    "oschina",
    "contact",
    "import",
}

GENERIC_URL_PATHS = (
    "/search",
    "/explore/category",
    "/tag/",
    "/tags/",
    "/topics",
)

BUSINESS_NOISE_TERMS = (
    "api key",
    "apikey",
    "deepseek",
    "招聘",
    "岗位",
    "工程师",
    "简历",
    "内推",
    "ai 陪伴",
    "大模型",
    "服务器配置",
    "主机配置",
    "epyc",
    "all in one",
    "为什么写爬虫",
    "学习爬虫",
    "验证码图片",
    "去除验证码",
    "验证码识别",
    "验证码噪点",
    "验证码错误",
    "模拟登录验证码",
    "图片噪点",
    "四六级",
    "成绩查询",
    "考试成绩",
    "高德地图",
    "微信公众号",
    "指定的文章",
    "java项目",
    "临时邮箱",
    "vibe coding",
    "邮箱服务",
    "github page",
    "baidu蜘蛛",
)


@dataclass(frozen=True)
class HygieneDecision:
    action: str
    reason: str
    severity: int


def run_prospect_hygiene(db: Session, apply: bool = True) -> dict[str, object]:
    prospects = list(db.scalars(select(Prospect).order_by(desc(Prospect.lead_score))))
    reviewed = 0
    invalidated = 0
    downgraded = 0
    kept = 0
    reasons: Counter[str] = Counter()
    samples: list[dict[str, object]] = []

    for prospect in prospects:
        reviewed += 1
        mentions = valid_mentions_for_prospect(db, prospect.id)
        decision = classify_prospect(prospect, mentions)
        if decision.action == "keep":
            kept += 1
            continue

        reasons[decision.reason] += 1
        if len(samples) < 30:
            samples.append(
                {
                    "id": prospect.id,
                    "name": prospect.display_name,
                    "platform": prospect.platform,
                    "score": prospect.lead_score,
                    "action": decision.action,
                    "reason": decision.reason,
                }
            )
        if not apply:
            continue

        if decision.action == "invalidate":
            if prospect.status != "invalid":
                prospect.status = "invalid"
                prospect.next_action = f"客户质量清洗：{decision.reason}"
                prospect.updated_at = datetime.now()
                invalidated += 1
            for mention in mentions:
                if mention.status != "invalid":
                    mention.status = "invalid"
                    mention.risk_level = "low_fit"
                    mention.recommendation = f"客户画像归档：{decision.reason}"
                    mention.score_reasons = append_reason(
                        mention.score_reasons,
                        f"客户画像归档：{decision.reason}",
                    )
        elif decision.action == "downgrade":
            new_score = min(prospect.lead_score, 49)
            if prospect.lead_score != new_score:
                prospect.lead_score = new_score
                prospect.next_action = f"降为观察：{decision.reason}"
                prospect.updated_at = datetime.now()
                downgraded += 1

    if apply:
        db.commit()

    return {
        "reviewed": reviewed,
        "kept": kept,
        "invalidated": invalidated,
        "downgraded": downgraded,
        "reasons": reasons.most_common(),
        "sample": samples,
    }


def valid_mentions_for_prospect(db: Session, prospect_id: int, limit: int = 12) -> list[Mention]:
    return list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect_id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(limit)
        )
    )


def archive_pre_min_year_mentions(db: Session, apply: bool = True) -> dict[str, object]:
    reviewed = 0
    archived = 0
    samples: list[dict[str, object]] = []
    for mention in db.scalars(select(Mention).where(Mention.status != "invalid")):
        reviewed += 1
        source_time = mention.published_at or mention.discovered_at
        if source_time is None or source_time.year >= MIN_LEAD_YEAR:
            continue
        archived += 1
        if len(samples) < 20:
            samples.append(
                {
                    "id": mention.id,
                    "title": mention.title,
                    "source": mention.source_name,
                    "published_at": source_time.isoformat(timespec="seconds"),
                }
            )
        if apply:
            mention.status = "invalid"
            mention.risk_level = "stale"
            mention.recommendation = (
                f"原文时间早于 {MIN_LEAD_YEAR} 年，按当前业务要求归档，不进入获客跟进。"
            )
            reason = f"时效归档：原文时间 {source_time:%Y-%m-%d} 早于 {MIN_LEAD_YEAR} 年。"
            mention.score_reasons = append_reason(mention.score_reasons, reason)
            if mention.score > 20:
                mention.score = min(mention.score, 20)
    if apply:
        db.commit()
    return {
        "reviewed": reviewed,
        "archived": archived,
        "min_year": MIN_LEAD_YEAR,
        "samples": samples,
    }


def append_reason(old: str, reason: str) -> str:
    old = (old or "").strip()
    if reason in old:
        return old
    if not old:
        return reason
    return f"{old}\n{reason}"


def classify_prospect(prospect: Prospect, mentions: list[Mention]) -> HygieneDecision:
    if prospect.status in {"won", "invalid"}:
        return HygieneDecision("keep", "已完成或已无效", 0)

    has_contact = has_real_contact(prospect)
    if not mentions and not has_contact:
        return HygieneDecision("invalidate", "无有效原文证据且无真实联系方式", 100)

    quality = evaluate_lead_quality(
        title=prospect.display_name,
        content="\n".join(
            [
                prospect.company_name or "",
                prospect.platform or "",
                prospect.profile_url or "",
                prospect.website or "",
                prospect.customer_type or "",
                prospect.keywords or "",
                prospect.evidence or "",
                prospect.next_action or "",
                "\n".join(f"{mention.title}\n{mention.content}" for mention in mentions[:5]),
            ]
        ),
        url=prospect.profile_url,
        source_name=prospect.platform,
    )

    if quality.reject and not has_contact:
        return HygieneDecision("invalidate", "P3质量画像剔除：" + "；".join(quality.reasons[:3]), 92)

    if quality.tier in {"reject", "D"} and prospect.lead_score < 70 and not has_contact:
        return HygieneDecision("downgrade", "P3质量画像低质：" + "；".join(quality.reasons[:3]), 72)

    if prospect.product_fit == "mismatch_static" and not has_contact:
        return HygieneDecision("invalidate", "静态/固定 IP 或机房代理需求，不是动态住宅 IP", 95)

    if mentions and all(is_generic_mention(mention) for mention in mentions) and not has_contact:
        return HygieneDecision("invalidate", "只命中搜索页/类目页/标签页，未发现具体客户需求", 90)

    if mentions and all(is_business_noise(mention) for mention in mentions) and not has_contact:
        return HygieneDecision("invalidate", "招聘/API/大模型等技术噪音，不是动态住宅 IP 获客场景", 90)

    if prospect.lead_score < 45 and not has_contact:
        return HygieneDecision("downgrade", "低分且不可触达，先放观察池", 60)

    if prospect.risk_count >= 2 and "buyer_intent" not in (prospect.signal_types or ""):
        return HygieneDecision("downgrade", "风险信号偏多且缺少明确购买意图", 70)

    if prospect.customer_type == "competitor_research" and not has_contact and prospect.lead_score < 70:
        return HygieneDecision("downgrade", "竞品/替代信息不足，暂不进入销售队列", 55)

    return HygieneDecision("keep", "保留", 0)


def is_generic_mention(mention: Mention) -> bool:
    title = (mention.title or "").strip().lower()
    url = (mention.canonical_url or "").strip()
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()

    if any(path == item or path.startswith(item) for item in GENERIC_URL_PATHS):
        return True
    if title in {"站内搜索", "搜索结果", "search", "首页", "标签"}:
        return True
    if "站内搜索" in title and "search" in path:
        return True
    return False


def is_business_noise(mention: Mention) -> bool:
    text = f"{mention.title}\n{mention.content}\n{mention.matched_keywords}".lower()
    has_noise = any(term in text for term in BUSINESS_NOISE_TERMS)
    has_proxy_need = any(
        term in text
        for term in (
            "代理 ip",
            "代理ip",
            "住宅 ip",
            "住宅ip",
            "防关联",
            "指纹浏览器",
            "cloudflare",
            "403",
            "429",
        )
    )
    return has_noise and not has_proxy_need


# P6 hygiene additions for solo/small-team route.
BUSINESS_NOISE_TERMS = BUSINESS_NOISE_TERMS + (
    "教程",
    "新手教程",
    "完整教程",
    "保姆级教程",
    "原理详解",
    "测评",
    "排行榜",
    "新闻",
    "融资",
    "招聘",
    "岗位",
    "官网文章",
    "优惠码",
    "限时优惠",
    "服务商官网",
)
