from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Mention, Prospect, Source
from app.services.prospects import CUSTOMER_TYPE_LABELS
from app.services.signals import HIGH_VALUE_SIGNALS


@dataclass
class SourceAttribution:
    source_name: str
    source_kind: str
    quality_score: int
    quality_status: str
    mentions: int = 0
    high_value_mentions: int = 0
    prospects: int = 0
    contacted: int = 0
    wechat_added: int = 0
    trial_sent: int = 0
    won: int = 0
    invalid: int = 0

    @property
    def trial_rate(self) -> float:
        return self.trial_sent / self.prospects if self.prospects else 0

    @property
    def win_rate(self) -> float:
        return self.won / self.prospects if self.prospects else 0


@dataclass
class CustomerTypeAttribution:
    customer_type: str
    label: str
    prospects: int = 0
    contacted: int = 0
    wechat_added: int = 0
    trial_sent: int = 0
    won: int = 0
    invalid: int = 0
    avg_score: int = 0

    @property
    def trial_rate(self) -> float:
        return self.trial_sent / self.prospects if self.prospects else 0

    @property
    def win_rate(self) -> float:
        return self.won / self.prospects if self.prospects else 0


@dataclass
class KeywordAttribution:
    keyword: str
    mentions: int = 0
    high_value_mentions: int = 0
    prospects: int = 0
    contacted: int = 0
    wechat_added: int = 0
    trial_sent: int = 0
    won: int = 0
    invalid: int = 0
    avg_score: int = 0

    @property
    def high_value_rate(self) -> float:
        return self.high_value_mentions / self.mentions if self.mentions else 0

    @property
    def trial_rate(self) -> float:
        return self.trial_sent / self.prospects if self.prospects else 0

    @property
    def win_rate(self) -> float:
        return self.won / self.prospects if self.prospects else 0

    @property
    def strategy_score(self) -> int:
        score = 0
        score += min(self.high_value_mentions * 5, 35)
        score += min(self.prospects * 4, 25)
        score += min(self.trial_sent * 10, 25)
        score += min(self.won * 20, 40)
        score += round(self.high_value_rate * 15)
        score -= min(self.invalid * 6, 25)
        return max(0, min(100, score))


def build_source_attribution(db: Session) -> list[SourceAttribution]:
    sources = {
        source.name: SourceAttribution(
            source_name=source.name,
            source_kind=source.kind,
            quality_score=source.quality_score or 0,
            quality_status=source.quality_status or "unchecked",
        )
        for source in db.query(Source).all()
    }
    prospects = {prospect.id: prospect for prospect in db.query(Prospect).all()}
    source_prospect_ids: dict[str, set[int]] = defaultdict(set)

    for mention in db.query(Mention).all():
        if mention.source_name not in sources:
            sources[mention.source_name] = SourceAttribution(
                source_name=mention.source_name,
                source_kind=mention.source_kind,
                quality_score=0,
                quality_status="unknown",
            )
        row = sources[mention.source_name]
        row.mentions += 1
        if mention.signal_type in HIGH_VALUE_SIGNALS and mention.score >= 60:
            row.high_value_mentions += 1
        if mention.prospect_id:
            source_prospect_ids[mention.source_name].add(mention.prospect_id)

    for source_name, prospect_ids in source_prospect_ids.items():
        row = sources[source_name]
        row.prospects = len(prospect_ids)
        for prospect_id in prospect_ids:
            prospect = prospects.get(prospect_id)
            if prospect is None:
                continue
            if prospect.status in {"contacted", "wechat_added", "trial_sent", "follow_up", "won"}:
                row.contacted += 1
            if prospect.status in {"wechat_added", "trial_sent", "follow_up", "won"}:
                row.wechat_added += 1
            if prospect.status in {"trial_sent", "follow_up", "won"}:
                row.trial_sent += 1
            if prospect.status == "won":
                row.won += 1
            if prospect.status == "invalid":
                row.invalid += 1

    return sorted(
        sources.values(),
        key=lambda row: (
            row.won,
            row.trial_sent,
            row.high_value_mentions,
            row.prospects,
            row.quality_score,
        ),
        reverse=True,
    )


def build_customer_type_attribution(db: Session) -> list[CustomerTypeAttribution]:
    buckets: dict[str, list[Prospect]] = defaultdict(list)
    for prospect in db.query(Prospect).all():
        buckets[prospect.customer_type or "unknown"].append(prospect)

    rows: list[CustomerTypeAttribution] = []
    for customer_type, prospects in buckets.items():
        avg_score = round(sum(item.lead_score or 0 for item in prospects) / len(prospects))
        row = CustomerTypeAttribution(
            customer_type=customer_type,
            label=CUSTOMER_TYPE_LABELS.get(customer_type, customer_type),
            prospects=len(prospects),
            avg_score=avg_score,
        )
        for prospect in prospects:
            if prospect.status in {"contacted", "wechat_added", "trial_sent", "follow_up", "won"}:
                row.contacted += 1
            if prospect.status in {"wechat_added", "trial_sent", "follow_up", "won"}:
                row.wechat_added += 1
            if prospect.status in {"trial_sent", "follow_up", "won"}:
                row.trial_sent += 1
            if prospect.status == "won":
                row.won += 1
            if prospect.status == "invalid":
                row.invalid += 1
        rows.append(row)

    return sorted(rows, key=lambda row: (row.won, row.trial_sent, row.prospects), reverse=True)


def build_keyword_attribution(db: Session) -> list[KeywordAttribution]:
    prospects = {prospect.id: prospect for prospect in db.query(Prospect).all()}
    keyword_mentions: dict[str, list[Mention]] = defaultdict(list)
    keyword_prospect_ids: dict[str, set[int]] = defaultdict(set)

    for mention in db.query(Mention).all():
        for keyword in parse_matched_keywords(mention.matched_keywords):
            keyword_mentions[keyword].append(mention)
            if mention.prospect_id:
                keyword_prospect_ids[keyword].add(mention.prospect_id)

    rows: list[KeywordAttribution] = []
    for keyword, mentions in keyword_mentions.items():
        avg_score = round(sum(mention.score or 0 for mention in mentions) / len(mentions))
        row = KeywordAttribution(
            keyword=keyword,
            mentions=len(mentions),
            high_value_mentions=sum(
                1
                for mention in mentions
                if mention.signal_type in HIGH_VALUE_SIGNALS and mention.score >= 60
            ),
            prospects=len(keyword_prospect_ids[keyword]),
            avg_score=avg_score,
        )
        for prospect_id in keyword_prospect_ids[keyword]:
            prospect = prospects.get(prospect_id)
            if prospect is None:
                continue
            if prospect.status in {"contacted", "wechat_added", "trial_sent", "follow_up", "won"}:
                row.contacted += 1
            if prospect.status in {"wechat_added", "trial_sent", "follow_up", "won"}:
                row.wechat_added += 1
            if prospect.status in {"trial_sent", "follow_up", "won"}:
                row.trial_sent += 1
            if prospect.status == "won":
                row.won += 1
            if prospect.status == "invalid":
                row.invalid += 1
        rows.append(row)

    return sorted(
        rows,
        key=lambda row: (
            row.won,
            row.trial_sent,
            row.strategy_score,
            row.high_value_mentions,
            row.prospects,
        ),
        reverse=True,
    )


def parse_matched_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("，", ",").replace("、", ",").replace("|", ",").replace("\n", ",")
    keywords = []
    seen = set()
    for item in normalized.split(","):
        keyword = item.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    return keywords
