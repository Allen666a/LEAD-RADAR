from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO

from sqlalchemy.orm import Session

from app.models import Prospect
from app.services.prospects import (
    DYNAMIC_RESIDENTIAL_TERMS,
    HIGH_FIT_SCENARIOS,
    STATIC_MISMATCH_TERMS,
    build_pitch_message,
    build_stage_message,
    build_suggested_action,
    classify_customer_type,
)


IMPORT_COLUMNS = [
    "platform",
    "display_name",
    "profile_url",
    "company_name",
    "region",
    "website",
    "email",
    "wechat",
    "telegram",
    "customer_type",
    "product_fit",
    "lead_score",
    "evidence",
    "next_action",
    "contact_note",
]


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    skipped: int
    errors: list[str]


def import_prospects_csv(db: Session, content: bytes) -> ImportResult:
    text = decode_csv(content)
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        return ImportResult(0, 0, 0, ["CSV 缺少表头"])

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for line_no, row in enumerate(reader, start=2):
        try:
            normalized = normalize_row(row)
            if not normalized["display_name"] and not normalized["profile_url"]:
                skipped += 1
                continue
            result = upsert_imported_prospect(db, normalized)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第 {line_no} 行导入失败：{exc}")

    db.commit()
    return ImportResult(created=created, updated=updated, skipped=skipped, errors=errors[:20])


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    return {key: (row.get(key) or "").strip() for key in IMPORT_COLUMNS}


def upsert_imported_prospect(db: Session, row: dict[str, str]) -> str:
    platform = row["platform"] or "国内私域导入"
    display_name = row["display_name"] or row["company_name"] or row["profile_url"] or "未命名线索"
    identity_key = build_identity_key(platform, display_name, row["profile_url"], row["wechat"], row["telegram"], row["email"])
    prospect = db.query(Prospect).filter(Prospect.identity_key == identity_key).first()
    created = prospect is None
    if prospect is None:
        prospect = Prospect(identity_key=identity_key, platform=platform, display_name=display_name)
        db.add(prospect)

    evidence = row["evidence"] or row["contact_note"] or display_name
    text = " ".join([display_name, row["company_name"], row["customer_type"], row["product_fit"], evidence])
    product_fit = row["product_fit"] or classify_import_product_fit(text)
    customer_type = row["customer_type"] or classify_customer_type(text.lower())
    lead_score = parse_score(row["lead_score"], product_fit, customer_type, evidence)

    prospect.platform = platform[:80]
    prospect.display_name = display_name[:260]
    prospect.profile_url = row["profile_url"]
    prospect.company_name = row["company_name"][:260]
    prospect.region = row["region"][:120]
    prospect.website = row["website"]
    prospect.email = row["email"][:260]
    prospect.wechat = row["wechat"][:160]
    prospect.telegram = row["telegram"][:160]
    prospect.contact_note = row["contact_note"][:5000]
    prospect.product_fit = product_fit
    prospect.customer_type = customer_type
    prospect.lead_score = lead_score
    prospect.mention_count = max(prospect.mention_count or 0, 1)
    prospect.high_value_count = max(prospect.high_value_count or 0, 1 if lead_score >= 70 else 0)
    prospect.evidence = evidence[:5000]
    prospect.keywords = row["product_fit"] or row["customer_type"] or "国内获客导入"
    prospect.pitch_message = build_import_pitch_message(display_name, customer_type, product_fit, evidence)
    prospect.first_touch_message = prospect.pitch_message
    prospect.follow_up_message = build_import_stage_message(display_name, customer_type, product_fit, "follow_up")
    prospect.trial_message = build_import_stage_message(display_name, customer_type, product_fit, "trial")
    prospect.closing_message = build_import_stage_message(display_name, customer_type, product_fit, "closing")
    prospect.suggested_action = build_suggested_action(customer_type, product_fit, lead_score)
    prospect.next_action = row["next_action"][:1000] or prospect.next_action
    prospect.status = prospect.status or "new"
    now = datetime.now()
    prospect.first_seen_at = prospect.first_seen_at or now
    prospect.last_seen_at = now
    prospect.updated_at = now
    return "created" if created else "updated"


def build_identity_key(platform: str, display_name: str, profile_url: str, wechat: str, telegram: str, email: str) -> str:
    strongest = profile_url or wechat or telegram or email or display_name
    return f"import:{platform}:{strongest}".lower()[:260]


def parse_score(value: str, product_fit: str, customer_type: str, evidence: str) -> int:
    if value:
        try:
            return max(0, min(100, int(float(value))))
        except ValueError:
            pass
    score = 55
    if product_fit == "direct_dynamic_residential":
        score += 25
    elif product_fit == "scenario_fit":
        score += 15
    elif product_fit == "mismatch_static":
        score -= 25
    if customer_type != "unknown":
        score += 10
    if any(term in evidence for term in ["急", "求", "需要", "被封", "防关联", "验证码", "店群", "矩阵"]):
        score += 10
    return max(0, min(100, score))


def classify_import_product_fit(text: str) -> str:
    haystack = text.lower()
    if any(term.lower() in haystack for term in STATIC_MISMATCH_TERMS):
        return "mismatch_static"
    if any(term.lower() in haystack for term in DYNAMIC_RESIDENTIAL_TERMS):
        return "direct_dynamic_residential"
    if any(term.lower() in haystack for term in HIGH_FIT_SCENARIOS):
        return "scenario_fit"
    return "weak_fit"


def build_import_pitch_message(display_name: str, customer_type: str, product_fit: str, evidence: str) -> str:
    class MentionLike:
        title = evidence
        content = evidence
        matched_keywords = "国内获客导入"

    return build_pitch_message(display_name, customer_type, product_fit, [MentionLike()])


def build_import_stage_message(display_name: str, customer_type: str, product_fit: str, stage: str) -> str:
    class MentionLike:
        title = "国内获客导入线索"
        content = ""
        matched_keywords = "国内获客导入"

    return build_stage_message(display_name, customer_type, product_fit, [MentionLike()], stage)


def sample_csv() -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=IMPORT_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            "platform": "微信群",
            "display_name": "TikTok 小店矩阵团队",
            "profile_url": "",
            "company_name": "",
            "region": "深圳",
            "website": "",
            "email": "",
            "wechat": "example_wechat",
            "telegram": "",
            "customer_type": "tiktok_matrix",
            "product_fit": "scenario_fit",
            "lead_score": "85",
            "evidence": "群里询问 TikTok 小店多账号防关联，当前 IP 经常触发风控。",
            "next_action": "加微信确认账号规模、目标国家和当前代理方案",
            "contact_note": "来自跨境卖家交流群",
        }
    )
    return output.getvalue()
