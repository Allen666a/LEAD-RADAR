from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, CompanySignal, ContactRecord, Mention, OutreachActivity, Prospect


@dataclass(frozen=True)
class B2BAccountDetail:
    company: CompanyProfile
    signals: list[CompanySignal]
    contacts: list[ContactRecord]
    prospects: list[Prospect]
    activities: list[OutreachActivity]


def load_b2b_accounts(
    db: Session,
    status: str = "all",
    contact: str = "all",
    min_score: int = 0,
    limit: int = 100,
) -> list[CompanyProfile]:
    query = select(CompanyProfile).where(CompanyProfile.priority_score >= min_score)
    if status == "all":
        query = query.where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
    elif status != "all":
        query = query.where(CompanyProfile.crm_status == status)
    if contact == "missing":
        query = query.where(CompanyProfile.contact_status.in_(["", "unknown", "missing"]))
    elif contact == "contactable":
        query = query.where(CompanyProfile.contact_status == "contactable")
    return list(
        db.scalars(
            query.order_by(desc(CompanyProfile.priority_score), desc(CompanyProfile.last_signal_at)).limit(limit)
        ).all()
    )


def load_b2b_account_detail(db: Session, company_id: int) -> B2BAccountDetail | None:
    company = db.get(CompanyProfile, company_id)
    if company is None:
        return None
    signals = list(
        db.scalars(
            select(CompanySignal)
            .where(CompanySignal.company_id == company_id)
            .order_by(desc(CompanySignal.score), desc(CompanySignal.detected_at))
            .limit(50)
        ).all()
    )
    contacts = list(
        db.scalars(
            select(ContactRecord)
            .where(ContactRecord.company_id == company_id)
            .order_by(desc(ContactRecord.confidence), desc(ContactRecord.created_at))
        ).all()
    )
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.company_id == company_id)
            .order_by(desc(Prospect.priority_score), desc(Prospect.updated_at))
        ).all()
    )
    activities = list(
        db.scalars(
            select(OutreachActivity)
            .where(OutreachActivity.company_id == company_id)
            .order_by(desc(OutreachActivity.created_at))
            .limit(50)
        ).all()
    )
    return B2BAccountDetail(company, signals, contacts, prospects, activities)


def build_b2b_stats(rows: list[CompanyProfile]) -> dict[str, int]:
    return {
        "companies": len(rows),
        "a_accounts": sum(1 for row in rows if row.priority_score >= 80),
        "missing_contact": sum(1 for row in rows if row.contact_status != "contactable"),
        "contactable": sum(1 for row in rows if row.contact_status == "contactable"),
    }


def search_b2b_accounts(db: Session, q: str, limit: int = 100) -> list[CompanyProfile]:
    keyword = f"%{q.strip()}%"
    if not q.strip():
        return load_b2b_accounts(db, limit=limit)
    return list(
        db.scalars(
            select(CompanyProfile)
            .where(
                or_(
                    CompanyProfile.company_name.like(keyword),
                    CompanyProfile.domain.like(keyword),
                    CompanyProfile.customer_type.like(keyword),
                    CompanyProfile.evidence_summary.like(keyword),
                )
            )
            .where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
            .order_by(desc(CompanyProfile.priority_score))
            .limit(limit)
        ).all()
    )


def company_signal_mentions(db: Session, company_id: int) -> list[Mention]:
    return list(
        db.scalars(
            select(Mention)
            .where(Mention.company_id == company_id)
            .order_by(desc(Mention.priority_score), desc(Mention.discovered_at))
            .limit(50)
        ).all()
    )
