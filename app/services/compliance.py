from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect


BLOCKED_TERMS = [
    "盗号",
    "撞库",
    "黑产",
    "灰产",
    "赌博",
    "博彩",
    "洗钱",
    "木马",
    "钓鱼",
    "诈骗",
    "欺诈",
    "攻击",
    "ddos",
    "credential stuffing",
    "carding",
    "botnet",
    "malware",
    "phishing",
    "spam farm",
]

REVIEW_TERMS = [
    "养号",
    "多账号",
    "矩阵",
    "防关联",
    "群控",
    "接码",
    "注册账号",
    "批量注册",
    "过验证",
    "验证码",
    "店群",
    "小店矩阵",
    "封号",
]

SAFE_TERMS = [
    "公开数据",
    "价格监控",
    "库存监控",
    "舆情",
    "serp",
    "合规",
    "风控测试",
    "可用性测试",
    "跨境运营",
    "环境测试",
]


@dataclass(frozen=True)
class ComplianceDecision:
    level: str
    reason: str
    matched_terms: list[str]


def run_compliance_audit(db: Session, apply: bool = True) -> dict[str, object]:
    prospects = list(db.scalars(select(Prospect).order_by(desc(Prospect.lead_score))))
    counts = {"safe": 0, "review": 0, "blocked": 0}
    changed = 0
    samples = []

    for prospect in prospects:
        decision = classify_prospect_compliance(db, prospect)
        counts[decision.level] += 1
        if decision.level != "safe":
            samples.append(
                {
                    "prospect_id": prospect.id,
                    "name": prospect.display_name,
                    "level": decision.level,
                    "reason": decision.reason,
                    "terms": decision.matched_terms[:8],
                }
            )
        if apply and apply_decision(prospect, decision):
            changed += 1

    if apply:
        db.commit()
    return {
        "prospects": len(prospects),
        "safe": counts["safe"],
        "review": counts["review"],
        "blocked": counts["blocked"],
        "changed": changed,
        "sample": samples[:30],
    }


def classify_prospect_compliance(db: Session, prospect: Prospect) -> ComplianceDecision:
    text = build_compliance_text(db, prospect)
    blocked = matched_terms(text, BLOCKED_TERMS)
    if blocked:
        return ComplianceDecision(
            level="blocked",
            reason="出现明显违法、攻击、欺诈或黑灰产意图，禁止进入销售跟进。",
            matched_terms=blocked,
        )

    review = matched_terms(text, REVIEW_TERMS)
    safe = matched_terms(text, SAFE_TERMS)
    if review and not safe:
        return ComplianceDecision(
            level="review",
            reason="涉及多账号、养号、防关联或验证相关场景，销售前必须人工确认合法用途。",
            matched_terms=review,
        )
    if review and safe:
        return ComplianceDecision(
            level="review",
            reason="同时出现合规业务和敏感场景，先人工确认用途，再决定是否试用。",
            matched_terms=review + safe[:3],
        )
    if prospect.risk_count and prospect.risk_count > 0:
        return ComplianceDecision(
            level="review",
            reason="关联线索存在风险标记，销售前需要人工复核业务用途。",
            matched_terms=["risk_count"],
        )
    return ComplianceDecision(level="safe", reason="未发现明显高风险词。", matched_terms=safe)


def apply_decision(prospect: Prospect, decision: ComplianceDecision) -> bool:
    changed = False
    if decision.level == "blocked" and prospect.status != "invalid":
        prospect.status = "invalid"
        prospect.next_action = "合规拦截：禁止触达，避免违法、攻击、欺诈或黑灰产业务。"
        changed = True
    elif decision.level == "review" and prospect.status not in {"won", "invalid"}:
        marker = "合规复核："
        note = f"{marker}{decision.reason}"
        if marker not in (prospect.follow_up_note or ""):
            prospect.follow_up_note = merge_note(prospect.follow_up_note or "", note)
            changed = True
        if prospect.next_action == "先人工确认合法用途、目标平台、国家、并发量和使用边界，再决定是否进入试用。":
            prospect.next_action = compliance_guarded_action(prospect)
            changed = True
        elif not prospect.next_action:
            prospect.next_action = compliance_guarded_action(prospect)
            changed = True

    if changed:
        prospect.updated_at = datetime.now()
    return changed


def compliance_guarded_action(prospect: Prospect) -> str:
    action = (prospect.suggested_action or "可跟进，但先确认合法业务用途。").strip()
    guard = "跟进前先人工确认合法用途、目标平台、国家、并发量和使用边界。"
    if guard in action:
        return action
    return f"{action}\n{guard}"[:1000]


def build_compliance_text(db: Session, prospect: Prospect) -> str:
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect.id)
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(10)
        )
    )
    parts = [
        prospect.display_name or "",
        prospect.company_name or "",
        prospect.product_fit or "",
        prospect.customer_type or "",
        prospect.keywords or "",
        prospect.evidence or "",
        prospect.suggested_action or "",
        prospect.next_action or "",
        prospect.follow_up_note or "",
    ]
    for mention in mentions:
        parts.extend(
            [
                mention.title or "",
                mention.content or "",
                mention.matched_keywords or "",
                mention.signal_type or "",
                mention.recommendation or "",
            ]
        )
    return "\n".join(parts).lower()


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def merge_note(old: str, new: str) -> str:
    old = old.strip()
    new = new.strip()
    if not old:
        return new
    if not new or new in old:
        return old
    return f"{old}\n{new}"
