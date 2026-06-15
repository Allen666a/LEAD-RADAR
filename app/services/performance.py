from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Mention, Prospect, Source
from app.services.contact_status import has_real_contact as prospect_has_real_contact
from app.services.signals import HIGH_VALUE_SIGNALS


@dataclass(frozen=True)
class PlatformPerformance:
    platform: str
    sources: int
    mentions: int
    high_value_mentions: int
    prospects: int
    contactable_prospects: int
    direct_fit: int
    scenario_fit: int
    due_today: int
    contacted: int
    trial_sent: int
    won: int
    invalid: int
    avg_score: float
    score: int
    recommendation: str

    @property
    def contact_rate(self) -> float:
        if self.prospects == 0:
            return 0
        return self.contactable_prospects / self.prospects

    @property
    def high_value_rate(self) -> float:
        if self.mentions == 0:
            return 0
        return self.high_value_mentions / self.mentions


def build_platform_performance(db: Session) -> list[PlatformPerformance]:
    platforms = sorted(
        {
            *(platform_from_source(source.name, source.kind) for source in db.query(Source).all()),
            *(prospect.platform for prospect in db.query(Prospect).all()),
        }
    )
    today = datetime.now().date()
    rows: list[PlatformPerformance] = []
    for platform in platforms:
        sources = [
            source for source in db.query(Source).all()
            if platform_from_source(source.name, source.kind) == platform
        ]
        mentions = [
            mention for mention in db.query(Mention).all()
            if platform_from_mention(mention) == platform
        ]
        prospects = list(db.query(Prospect).filter(Prospect.platform == platform).all())
        high_value = [
            mention for mention in mentions
            if mention.signal_type in HIGH_VALUE_SIGNALS and mention.score >= 60
        ]
        contactable = [prospect for prospect in prospects if prospect_has_real_contact(prospect)]
        avg_score = sum(prospect.lead_score for prospect in prospects) / len(prospects) if prospects else 0
        due_today = sum(
            1
            for prospect in prospects
            if prospect.next_follow_up_at and prospect.next_follow_up_at.date() <= today
        )
        contacted = sum(1 for prospect in prospects if prospect.status in {"contacted", "wechat_added", "trial_sent", "follow_up", "won"})
        trial_sent = sum(1 for prospect in prospects if prospect.status == "trial_sent")
        won = sum(1 for prospect in prospects if prospect.status == "won")
        invalid = sum(1 for prospect in prospects if prospect.status == "invalid")
        direct_fit = sum(1 for prospect in prospects if prospect.product_fit == "direct_dynamic_residential")
        scenario_fit = sum(1 for prospect in prospects if prospect.product_fit == "scenario_fit")
        score = calculate_platform_score(
            mentions=len(mentions),
            high_value_mentions=len(high_value),
            prospects=len(prospects),
            contactable=len(contactable),
            avg_score=avg_score,
            direct_fit=direct_fit,
            scenario_fit=scenario_fit,
            invalid=invalid,
        )
        if platform == "github":
            score = min(score, 55)
        elif platform in {
            "zhihu",
            "tieba",
            "xiaohongshu",
            "douyin",
            "wearesellers",
            "amazon_seller_cn",
            "fobshanghai",
            "csdn",
            "cnblogs",
            "oschina",
            "v2ex",
            "segmentfault",
            "learnku",
            "gitee",
            "bilibili",
            "weibo",
        }:
            score = min(100, score + 8)
        rows.append(
            PlatformPerformance(
                platform=platform,
                sources=len(sources),
                mentions=len(mentions),
                high_value_mentions=len(high_value),
                prospects=len(prospects),
                contactable_prospects=len(contactable),
                direct_fit=direct_fit,
                scenario_fit=scenario_fit,
                due_today=due_today,
                contacted=contacted,
                trial_sent=trial_sent,
                won=won,
                invalid=invalid,
                avg_score=avg_score,
                score=score,
                recommendation=recommend_platform(platform, score, len(contactable), len(high_value), len(prospects)),
            )
        )
    return sorted(rows, key=lambda row: (row.score, row.contactable_prospects, row.high_value_mentions), reverse=True)


def calculate_platform_score(
    mentions: int,
    high_value_mentions: int,
    prospects: int,
    contactable: int,
    avg_score: float,
    direct_fit: int,
    scenario_fit: int,
    invalid: int,
) -> int:
    score = 0
    score += min(high_value_mentions * 4, 28)
    score += min(contactable * 6, 30)
    score += min(prospects * 2, 16)
    score += min(direct_fit * 5 + scenario_fit * 3, 18)
    score += min(int(avg_score / 10), 8)
    score -= min(invalid * 4, 20)
    if mentions > 0 and high_value_mentions == 0:
        score -= 10
    return max(0, min(100, score))


def recommend_platform(platform: str, score: int, contactable: int, high_value: int, prospects: int) -> str:
    if platform == "github":
        return "技术情报源：适合发现爬虫/采集团队痛点，但不是国内获客主战场。"
    if score >= 75:
        return "重点投入：继续采集并优先安排销售跟进。"
    if contactable > 0 and high_value > 0:
        return "可放大：补关键词和会话采集，提升联系方式覆盖。"
    if contactable > 0:
        return "可培育：已有联系方式，但需要补意向证据和场景确认。"
    if prospects > 0:
        return "先质检：有线索但可联系比例不足，重点补联系方式。"
    return "观察：暂时没有稳定产出，降低采集频率。"


def platform_from_mention(mention: Mention) -> str:
    return platform_from_source(mention.source_name, mention.source_kind, mention.canonical_url)


def has_real_contact(prospect: Prospect) -> bool:
    note = (prospect.contact_note or "").lower()
    return bool(
        prospect.wechat
        or prospect.email
        or prospect.telegram
        or "qq:" in note
        or "手机:" in note
        or "邮箱:" in note
        or "telegram:" in note
        or "微信:" in note
    )


def platform_from_source(name: str, kind: str = "", url: str = "") -> str:
    text = f"{name} {kind} {url}".lower()
    mapping = [
        ("xiaohongshu", ["小红书", "xiaohongshu"]),
        ("douyin", ["抖音", "douyin"]),
        ("zhihu", ["知乎", "zhihu"]),
        ("tieba", ["贴吧", "tieba.baidu"]),
        ("v2ex", ["v2ex"]),
        ("segmentfault", ["segmentfault"]),
        ("learnku", ["learnku"]),
        ("gitee", ["gitee"]),
        ("github", ["github"]),
        ("wearesellers", ["wearesellers", "卖家论坛"]),
        ("amazon_seller_cn", ["amazon seller forum cn", "sellercentral.amazon.com", "亚马逊卖家论坛"]),
        ("fobshanghai", ["fob shanghai", "bbs.fobshanghai.com", "福步"]),
        ("csdn", ["csdn"]),
        ("cnblogs", ["cnblogs", "博客园"]),
        ("oschina", ["oschina", "开源中国"]),
        ("bilibili", ["bilibili", "哔哩", "b站"]),
        ("weibo", ["weibo", "微博"]),
    ]
    for platform, patterns in mapping:
        if any(pattern in text for pattern in patterns):
            return platform
    return kind or "unknown"
