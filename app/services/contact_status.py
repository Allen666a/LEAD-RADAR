from __future__ import annotations

from app.models import Prospect
from app.services.contacts import extract_contacts


def has_real_contact(prospect: Prospect) -> bool:
    signals = prospect_contact_signals(prospect)
    return bool(signals.primary_key()) and signals.confidence_score >= 24


def contact_identity(prospect: Prospect) -> str:
    return prospect_contact_signals(prospect).primary_key()


def contact_confidence(prospect: Prospect) -> int:
    return prospect_contact_signals(prospect).confidence_score


def prospect_contact_signals(prospect: Prospect):
    parts = [
        prospect.website or "",
        prospect.company_name or "",
        prospect.contact_note or "",
    ]
    if prospect.wechat:
        parts.append(f"微信: {prospect.wechat}")
    if prospect.email:
        parts.append(f"邮箱: {prospect.email}")
    if prospect.telegram:
        parts.append(f"Telegram: {prospect.telegram}")
    return extract_contacts("\n".join(parts))
