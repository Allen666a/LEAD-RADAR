from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.signals import HIGH_VALUE_SIGNALS


DOMESTIC_SOURCE_PREFIXES = (
    "Zhihu Search:",
    "Zhihu Intent:",
    "Baidu Tieba Intent:",
    "Baidu Tieba Search:",
    "Xiaohongshu",
    "Douyin",
    "Bilibili",
    "Weibo",
    "SegmentFault Intent:",
    "SegmentFault Search:",
    "LearnKu Intent:",
    "LearnKu Search:",
    "Gitee Intent:",
    "Gitee Issues:",
    "V2EX Intent:",
    "V2EX Tag:",
    "V2EX Node:",
    "V2EX Hot",
    "V2EX Latest",
    "CSDN Ask Intent:",
    "CSDN Search Intent:",
    "OSChina Intent:",
    "CNBlogs Intent:",
    "WeAreSellers Intent:",
    "WeAreSellers:",
    "Amazon Seller Forum CN:",
    "FOB Shanghai:",
    "Session ",
    "国内私域导入",
)

DOMESTIC_PLATFORMS = (
    "zhihu",
    "tieba",
    "xiaohongshu",
    "douyin",
    "bilibili",
    "weibo",
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
    "微信群",
    "QQ群",
    "飞书群",
    "小红书",
    "抖音",
    "知乎",
    "国内私域导入",
)

COMPETITOR_AD_TERMS = (
    "kookeey",
    "922s5",
    "bright data",
    "oxylabs",
    "smartproxy",
    "novproxy",
    "1024proxy",
    "免费测试",
    "解决方案",
    "官网",
)


@dataclass(frozen=True)
class DomesticReviewRow:
    mention: Mention | None
    prospect: Prospect | None
    review_score: int
    label: str
    reason: str
    has_contact: bool

    @property
    def row_id(self) -> str:
        if self.mention is not None:
            return f"mention:{self.mention.id}"
        if self.prospect is not None:
            return f"prospect:{self.prospect.id}"
        return ""

    @property
    def title(self) -> str:
        if self.mention is not None:
            return self.mention.title
        if self.prospect is not None:
            return self.prospect.display_name
        return ""

    @property
    def source_name(self) -> str:
        if self.mention is not None:
            return self.mention.source_name
        if self.prospect is not None:
            return self.prospect.platform
        return ""

    @property
    def url(self) -> str:
        if self.mention is not None:
            return self.mention.canonical_url
        if self.prospect is not None:
            return self.prospect.profile_url
        return ""


def load_domestic_review_rows(
    db: Session,
    status: str = "open",
    min_score: int = 60,
    limit: int = 200,
) -> list[DomesticReviewRow]:
    rows: list[DomesticReviewRow] = []
    prospect_by_id = {prospect.id: prospect for prospect in db.query(Prospect).all()}

    mention_query = (
        select(Mention)
        .where(Mention.score >= min_score)
        .order_by(desc(Mention.score), desc(Mention.discovered_at))
        .limit(limit)
    )
    if status == "open":
        mention_query = mention_query.where(Mention.status.in_(["new", "reviewed"]))
    elif status in {"new", "reviewed", "contacted", "invalid"}:
        mention_query = mention_query.where(Mention.status == status)

    for mention in db.scalars(mention_query):
        if not is_domestic_mention(mention):
            continue
        prospect = prospect_by_id.get(mention.prospect_id) if mention.prospect_id else None
        rows.append(build_review_row(mention, prospect))

    imported_prospects = load_imported_prospects(db, status=status, min_score=min_score, limit=limit)
    existing_prospect_ids = {row.prospect.id for row in rows if row.prospect is not None}
    for prospect in imported_prospects:
        if prospect.id in existing_prospect_ids:
            continue
        rows.append(build_review_row(None, prospect))

    rows = sorted(rows, key=lambda row: (row.review_score, row.has_contact, row.title), reverse=True)
    return dedupe_review_rows(rows)[:limit]


def dedupe_review_rows(rows: list[DomesticReviewRow]) -> list[DomesticReviewRow]:
    deduped: list[DomesticReviewRow] = []
    seen: set[str] = set()
    for row in rows:
        key = review_dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def review_dedupe_key(row: DomesticReviewRow) -> str:
    url = row.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    match = re.search(r"/t/\d+", url)
    if match:
        return f"v2ex:{match.group(0)}"
    title = row.title
    for marker in (" 问与答", " 分享创造", " 酷工作", " VPS", " - "):
        if marker in title:
            title = title.split(marker, 1)[0]
    title = re.sub(r"\s+", "", title.lower())
    return title[:100] or url


def load_imported_prospects(
    db: Session,
    status: str = "open",
    min_score: int = 60,
    limit: int = 200,
) -> list[Prospect]:
    query = (
        select(Prospect)
        .where(Prospect.lead_score >= min_score)
        .where(Prospect.platform.in_(DOMESTIC_PLATFORMS))
        .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
        .limit(limit)
    )
    if status == "open":
        query = query.where(Prospect.status.in_(["new", "qualified", "contacted", "wechat_added", "trial_sent", "follow_up"]))
    elif status in {"new", "qualified", "contacted", "wechat_added", "trial_sent", "follow_up", "won", "invalid"}:
        query = query.where(Prospect.status == status)
    return list(db.scalars(query))


def build_review_row(mention: Mention | None, prospect: Prospect | None) -> DomesticReviewRow:
    base_score = mention.score if mention is not None else prospect.lead_score if prospect is not None else 0
    has_contact = bool(prospect and (prospect.wechat or prospect.telegram or prospect.email or prospect.website))
    review_score = base_score
    reasons: list[str] = []
    label = "可跟进"

    if mention is not None:
        if looks_like_competitor_ad(mention):
            review_score -= 45
            label = "同行广告"
            reasons.append("疑似同行广告/软文")
        if mention.signal_type in HIGH_VALUE_SIGNALS:
            review_score += 8
            reasons.append("高价值信号")
        if mention.risk_level in {"high", "review"} or mention.signal_type == "risk_signal":
            review_score -= 12
            label = "需人工审核"
            reasons.append("含防关联/养号等敏感场景")
        if mention.status == "invalid":
            review_score -= 30
            label = "已无效"

    if prospect is not None:
        if prospect.product_fit == "direct_dynamic_residential":
            review_score += 12
            reasons.append("动态住宅直匹配")
        elif prospect.product_fit == "scenario_fit":
            review_score += 8
            reasons.append("场景匹配")
        elif prospect.product_fit == "mismatch_static":
            review_score -= 30
            label = "非目标"
            reasons.append("更像静态/固定 IP")
        if prospect.customer_type and prospect.customer_type != "unknown":
            review_score += 5
            reasons.append("客户类型明确")

    if not has_contact:
        label = "需补联系方式" if label == "可跟进" else label
        reasons.append("缺联系方式")

    review_score = max(0, min(100, review_score))
    if review_score >= 85 and label == "可跟进":
        label = "优先跟进"
    elif review_score < 60 and label == "可跟进":
        label = "先观察"

    return DomesticReviewRow(
        mention=mention,
        prospect=prospect,
        review_score=review_score,
        label=label,
        reason="；".join(reasons) or "国内来源命中",
        has_contact=has_contact,
    )


def looks_like_competitor_ad(mention: Mention) -> bool:
    haystack = f"{mention.title}\n{mention.content}\n{mention.source_name}".lower()
    competitor_hit = any(term.lower() in haystack for term in COMPETITOR_AD_TERMS[:6])
    promo_hit = any(term.lower() in haystack for term in COMPETITOR_AD_TERMS[6:])
    return competitor_hit and promo_hit


def is_domestic_mention(mention: Mention) -> bool:
    return mention.source_name.startswith(DOMESTIC_SOURCE_PREFIXES)


def apply_domestic_review_action(
    db: Session,
    row_ids: list[str],
    action: str,
) -> int:
    count = 0
    now = datetime.now()
    for row_id in row_ids:
        kind, _, raw_id = row_id.partition(":")
        if not raw_id.isdigit():
            continue
        item_id = int(raw_id)
        if kind == "mention":
            mention = db.get(Mention, item_id)
            if mention is None:
                continue
            apply_mention_action(mention, action)
            if mention.prospect_id:
                prospect = db.get(Prospect, mention.prospect_id)
                if prospect is not None:
                    apply_prospect_action(prospect, action, now)
            count += 1
        elif kind == "prospect":
            prospect = db.get(Prospect, item_id)
            if prospect is None:
                continue
            apply_prospect_action(prospect, action, now)
            count += 1
    db.commit()
    return count


def apply_mention_action(mention: Mention, action: str) -> None:
    if action == "qualify":
        mention.status = "reviewed"
    elif action == "contacted":
        mention.status = "contacted"
    elif action == "invalid":
        mention.status = "invalid"


def apply_prospect_action(prospect: Prospect, action: str, now: datetime) -> None:
    if action == "qualify":
        prospect.status = "qualified"
        prospect.next_action = prospect.next_action or "补联系方式并准备首触达"
    elif action == "contacted":
        prospect.status = "contacted"
        prospect.last_contacted_at = now
    elif action == "need_contact":
        prospect.status = "qualified"
        prospect.next_action = "补充微信/主页/社群来源后再触达"
    elif action == "follow_up":
        prospect.status = "follow_up"
        prospect.next_follow_up_at = now + timedelta(days=3)
    elif action == "invalid":
        prospect.status = "invalid"
    prospect.updated_at = now
