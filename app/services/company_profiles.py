from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, CompanySignal, ContactRecord, Mention, OutreachActivity, Prospect
from app.services.contacts import extract_contacts
from app.services.dual_mode_scoring import score_company, score_mention, score_prospect


COMPANY_PLATFORMS = {
    "github",
    "gitee",
    "wearesellers",
    "amazon_seller_cn",
    "fobshanghai",
    "v2ex",
    "segmentfault",
    "zhihu",
}


@dataclass(frozen=True)
class CompanyRebuildResult:
    companies_created: int
    companies_updated: int
    prospects_linked: int
    mentions_linked: int
    signals_created: int
    contacts_created: int
    activities_created: int


def rebuild_companies(db: Session) -> CompanyRebuildResult:
    created = updated = prospects_linked = mentions_linked = 0
    signals_created = contacts_created = activities_created = 0

    prospects = list(db.scalars(select(Prospect)).all())
    for prospect in prospects:
        key = company_key_from_prospect(prospect)
        if not key:
            continue
        company, was_created = get_or_create_company(db, key)
        if was_created:
            created += 1
        else:
            updated += 1
        update_company_from_prospect(company, prospect)
        prospect.company_id = company.id
        prospects_linked += 1
        contacts_created += sync_contacts_from_prospect(db, company, prospect)
        activities_created += ensure_activity(
            db,
            company_id=company.id,
            prospect_id=prospect.id,
            activity_type="created",
            note="由现有 Prospect 回填到 B2B 客户库。",
        )

    db.flush()

    mentions = list(db.scalars(select(Mention).where(Mention.status != "invalid")).all())
    for mention in mentions:
        company = None
        if mention.prospect_id:
            prospect = db.get(Prospect, mention.prospect_id)
            if prospect and prospect.company_id:
                company = db.get(CompanyProfile, prospect.company_id)
        if company is None:
            key = company_key_from_mention(mention)
            if key:
                company, was_created = get_or_create_company(db, key)
                if was_created:
                    created += 1
                else:
                    updated += 1
                update_company_from_mention(company, mention)
        if company is None:
            score = score_mention(mention)
            apply_score_to_mention(mention, score)
            continue
        mention.company_id = company.id
        mentions_linked += 1
        score = score_mention(mention)
        apply_score_to_mention(mention, score)
        signals_created += ensure_company_signal(db, company, mention, score)

    db.flush()
    rescore_companies(db)
    db.commit()
    return CompanyRebuildResult(
        companies_created=created,
        companies_updated=updated,
        prospects_linked=prospects_linked,
        mentions_linked=mentions_linked,
        signals_created=signals_created,
        contacts_created=contacts_created,
        activities_created=activities_created,
    )


def rescore_dual_mode(db: Session) -> dict[str, int]:
    mentions = list(db.scalars(select(Mention)).all())
    for mention in mentions:
        apply_score_to_mention(mention, score_mention(mention))

    prospects = list(db.scalars(select(Prospect)).all())
    mentions_by_prospect: dict[int, list[Mention]] = {}
    for mention in mentions:
        if mention.prospect_id:
            mentions_by_prospect.setdefault(mention.prospect_id, []).append(mention)
    for prospect in prospects:
        apply_score_to_prospect(prospect, score_prospect(prospect, mentions_by_prospect.get(prospect.id, [])))

    company_count = rescore_companies(db)
    db.commit()
    return {"mentions": len(mentions), "prospects": len(prospects), "companies": company_count}


def rescore_companies(db: Session) -> int:
    companies = list(db.scalars(select(CompanyProfile)).all())
    for company in companies:
        signals = list(
            db.scalars(
                select(CompanySignal)
                .where(CompanySignal.company_id == company.id)
                .order_by(CompanySignal.score.desc())
                .limit(20)
            )
        )
        contacts = db.scalar(
            select(func.count(ContactRecord.id)).where(ContactRecord.company_id == company.id)
        )
        contactable = db.scalar(
            select(func.count(ContactRecord.id)).where(
                ContactRecord.company_id == company.id,
                ContactRecord.contact_type.in_(["email", "wechat", "telegram", "phone", "contact_form", "linkedin"]),
            )
        )
        prospects = list(db.scalars(select(Prospect).where(Prospect.company_id == company.id)).all())
        signal_texts = [f"{signal.title}\n{signal.content_snippet}\n{signal.reason}" for signal in signals]
        score = score_company(company, signal_texts)
        company.fit_score = score.fit_score
        company.intent_score = score.intent_score
        company.contact_score = max(score.contact_score if contactable else 0, 45 if contactable else 0)
        company.risk_score = score.risk_score
        company.priority_score = max(
            0,
            min(
                100,
                int(
                    company.fit_score * 0.35
                    + company.intent_score * 0.35
                    + company.contact_score * 0.2
                    - company.risk_score * 0.3
                ),
            ),
        )
        company.customer_type = score.customer_type if score.customer_type != "unknown" else company.customer_type
        company.contact_count = int(contacts or 0)
        company.signal_count = len(signals)
        company.source_count = len({signal.source_name for signal in signals if signal.source_name})
        company.need_reason = score.priority_reason
        company.next_action = score.recommended_action
        company.contact_status = "contactable" if contactable else "missing"
        company.evidence_summary = build_company_evidence_summary(signals, prospects)
        signal_dates = [signal.detected_at for signal in signals if signal.detected_at]
        company.last_signal_at = max(signal_dates) if signal_dates else company.last_signal_at
        company.updated_at = datetime.now()
    return len(companies)


def get_or_create_company(db: Session, company_key: str) -> tuple[CompanyProfile, bool]:
    company = db.scalar(select(CompanyProfile).where(CompanyProfile.company_key == company_key))
    if company:
        return company, False
    company = CompanyProfile(company_key=company_key, first_seen_at=datetime.now())
    db.add(company)
    db.flush()
    return company, True


def company_key_from_prospect(prospect: Prospect) -> str:
    domain = extract_domain(prospect.website or prospect.profile_url)
    if domain and is_business_domain(domain):
        return f"domain:{domain}"
    if prospect.platform in {"github", "gitee"} and prospect.display_name:
        return f"{prospect.platform}:{slug(prospect.display_name)}"
    if prospect.company_name:
        return f"name:{slug(prospect.company_name)}:{slug(prospect.region or '')}"
    if prospect.platform in COMPANY_PLATFORMS and prospect.display_name:
        return f"{prospect.platform}:account:{slug(prospect.display_name)}"
    return ""


def company_key_from_mention(mention: Mention) -> str:
    domain = extract_domain(mention.canonical_url)
    if domain and is_business_domain(domain):
        return f"domain:{domain}"
    parsed = urlparse(mention.canonical_url or "")
    if parsed.netloc.endswith(("github.com", "gitee.com")):
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            platform = "github" if "github" in parsed.netloc else "gitee"
            return f"{platform}:{slug(parts[0])}"
    return ""


def update_company_from_prospect(company: CompanyProfile, prospect: Prospect) -> None:
    company.company_name = company.company_name or prospect.company_name or prospect.display_name
    company.domain = company.domain or extract_domain(prospect.website or prospect.profile_url)
    company.website = company.website or prospect.website or prospect.profile_url
    company.country = company.country or prospect.region
    company.region = company.region or prospect.region
    company.customer_type = (
        prospect.customer_type if prospect.customer_type and prospect.customer_type != "unknown" else company.customer_type
    )
    company.crm_status = company.crm_status if company.crm_status != "new" else prospect.status or "new"
    company.first_seen_at = company.first_seen_at or prospect.first_seen_at or prospect.created_at
    company.last_signal_at = max_datetime(company.last_signal_at, prospect.last_seen_at, prospect.updated_at)

    score = score_prospect(prospect)
    apply_score_to_prospect(prospect, score)
    company.fit_score = max(company.fit_score, score.fit_score)
    company.intent_score = max(company.intent_score, score.intent_score)
    company.contact_score = max(company.contact_score, score.contact_score)
    company.risk_score = max(company.risk_score, score.risk_score)
    company.priority_score = max(company.priority_score, score.priority_score)
    company.need_reason = company.need_reason or score.priority_reason
    company.next_action = company.next_action or score.recommended_action


def update_company_from_mention(company: CompanyProfile, mention: Mention) -> None:
    company.company_name = company.company_name or mention.author or title_to_company_name(mention.title)
    company.domain = company.domain or extract_domain(mention.canonical_url)
    company.website = company.website or mention.canonical_url
    company.first_seen_at = company.first_seen_at or mention.discovered_at
    company.last_signal_at = max_datetime(company.last_signal_at, mention.discovered_at)


def ensure_company_signal(db: Session, company: CompanyProfile, mention: Mention, score) -> int:
    if not mention.canonical_url:
        return 0
    existing = db.scalar(
        select(CompanySignal).where(
            CompanySignal.company_id == company.id,
            CompanySignal.url == mention.canonical_url,
        )
    )
    if existing:
        existing.score = score.priority_score
        existing.reason = score.priority_reason
        existing.fit_delta = score.fit_score
        existing.intent_delta = score.intent_score
        existing.risk_delta = score.risk_score
        return 0
    signal = CompanySignal(
        company_id=company.id,
        mention_id=mention.id,
        source_name=mention.source_name,
        source_kind=mention.source_kind,
        signal_type=map_signal_type(mention.signal_type, score.mode),
        title=mention.title,
        url=mention.canonical_url,
        content_snippet=(mention.content or "")[:800],
        matched_keywords=mention.matched_keywords,
        fit_delta=score.fit_score,
        intent_delta=score.intent_score,
        risk_delta=score.risk_score,
        score=score.priority_score,
        reason=score.priority_reason,
        detected_at=mention.discovered_at,
    )
    db.add(signal)
    return 1


def sync_contacts_from_prospect(db: Session, company: CompanyProfile, prospect: Prospect) -> int:
    created = 0
    pairs = [
        ("email", prospect.email),
        ("wechat", prospect.wechat),
        ("telegram", prospect.telegram),
        ("website", prospect.website or prospect.profile_url),
    ]
    for contact_type, value in pairs:
        normalized = normalize_contact_value(contact_type, value)
        if not normalized:
            continue
        exists = db.scalar(
            select(ContactRecord).where(
                ContactRecord.normalized_value == normalized,
                ContactRecord.contact_type == contact_type,
            )
        )
        if exists:
            continue
        db.add(
            ContactRecord(
                company_id=company.id,
                prospect_id=prospect.id,
                contact_type=contact_type,
                value=value,
                normalized_value=normalized,
                source_url=prospect.profile_url or prospect.website,
                source_type="prospect",
                confidence=70 if contact_type in {"email", "wechat", "telegram"} else 45,
                status="unverified",
                note=prospect.contact_note,
            )
        )
        created += 1
    return created


def ensure_activity(
    db: Session,
    company_id: int | None,
    prospect_id: int | None,
    activity_type: str,
    note: str,
) -> int:
    exists = db.scalar(
        select(OutreachActivity).where(
            OutreachActivity.company_id == company_id,
            OutreachActivity.prospect_id == prospect_id,
            OutreachActivity.activity_type == activity_type,
            OutreachActivity.note == note,
        )
    )
    if exists:
        return 0
    db.add(
        OutreachActivity(
            company_id=company_id,
            prospect_id=prospect_id,
            activity_type=activity_type,
            note=note,
            status="done",
            channel="system",
        )
    )
    return 1


def apply_score_to_mention(mention: Mention, score) -> None:
    mention.mode = score.mode
    mention.fit_score = score.fit_score
    mention.intent_score = score.intent_score
    mention.contact_score = score.contact_score
    mention.risk_score = score.risk_score
    mention.priority_score = score.priority_score
    mention.recommendation = score.recommended_action
    if score.risk_score >= 70 and mention.status == "new":
        mention.status = "review"


def apply_score_to_prospect(prospect: Prospect, score) -> None:
    prospect.mode = score.mode
    prospect.fit_score = score.fit_score
    prospect.intent_score = score.intent_score
    prospect.contact_score = score.contact_score
    prospect.risk_score = score.risk_score
    prospect.priority_score = score.priority_score
    prospect.contact_status = "contactable" if score.contact_score >= 45 else "missing"
    prospect.suggested_action = prospect.suggested_action or score.recommended_action
    if prospect.customer_type in {"", "unknown"}:
        prospect.customer_type = score.customer_type


def build_company_evidence_summary(signals: list[CompanySignal], prospects: list[Prospect]) -> str:
    parts = []
    for signal in signals[:3]:
        parts.append(f"[{signal.score}] {signal.title}")
    for prospect in prospects[:2]:
        if prospect.evidence:
            parts.append(prospect.evidence[:180])
    return "\n".join(parts)[:1200]


def map_signal_type(signal_type: str, mode: str) -> str:
    if mode == "b2b":
        if signal_type in {"company_signal", "buyer_intent"}:
            return "website_keyword"
        return "github_project" if signal_type == "developer_signal" else "community_pain"
    if signal_type == "risk_signal":
        return "risk"
    if signal_type == "competitor_signal":
        return "competitor"
    return "community_pain"


def normalize_contact_value(contact_type: str, value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if contact_type in {"email", "website"}:
        return value.lower()
    return value


def extract_domain(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if not host:
        return ""
    if "@" in host:
        host = host.split("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.removeprefix("www.")


def is_business_domain(domain: str) -> bool:
    if not domain:
        return False
    noisy = [
        "zhihu.com",
        "tieba.baidu.com",
        "xiaohongshu.com",
        "douyin.com",
        "weibo.com",
        "bilibili.com",
        "v2ex.com",
        "segmentfault.com",
        "csdn.net",
        "cnblogs.com",
        "oschina.net",
    ]
    return domain not in noisy


def slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff_.-]+", "", value)
    return value[:160]


def title_to_company_name(title: str | None) -> str:
    title = (title or "").strip()
    return re.split(r"[|｜\-_:：]", title, maxsplit=1)[0][:160]


def max_datetime(*values):
    clean = [value for value in values if value is not None]
    return max(clean) if clean else None
