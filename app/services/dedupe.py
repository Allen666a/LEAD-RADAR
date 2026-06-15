from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectEvent
from app.services.contact_status import contact_identity


@dataclass(frozen=True)
class DuplicateGroup:
    key: str
    reason: str
    prospect_ids: list[int]
    names: list[str]


def run_dedupe_audit(db: Session, mark_candidates: bool = True) -> dict[str, object]:
    prospects = list(db.scalars(select(Prospect)))
    groups = find_duplicate_groups(prospects)
    cleared = clear_duplicate_markers(prospects) if mark_candidates else 0
    marked = mark_duplicate_candidates(prospects, groups) if mark_candidates else 0
    relinked_events = relink_prospect_events(db)
    db.commit()
    return {
        "prospects": len(prospects),
        "duplicate_groups": len(groups),
        "duplicate_prospects": sum(len(group.prospect_ids) for group in groups),
        "marked": marked,
        "cleared_old_markers": cleared,
        "relinked_events": relinked_events,
        "sample": [
            {
                "key": group.key,
                "reason": group.reason,
                "prospect_ids": group.prospect_ids,
                "names": group.names,
            }
            for group in groups[:20]
        ],
    }


def find_duplicate_groups(prospects: list[Prospect]) -> list[DuplicateGroup]:
    buckets: dict[str, list[Prospect]] = defaultdict(list)
    for prospect in prospects:
        for key in candidate_keys(prospect):
            buckets[key].append(prospect)

    groups: list[DuplicateGroup] = []
    seen_sets: set[tuple[int, ...]] = set()
    for key, rows in buckets.items():
        unique_rows = sorted({row.id: row for row in rows}.values(), key=lambda row: row.id)
        if len(unique_rows) < 2:
            continue
        ids = tuple(row.id for row in unique_rows)
        if ids in seen_sets:
            continue
        seen_sets.add(ids)
        groups.append(
            DuplicateGroup(
                key=key,
                reason=key.split(":", 1)[0],
                prospect_ids=list(ids),
                names=[row.display_name or row.identity_key for row in unique_rows],
            )
        )
    return sorted(groups, key=lambda group: len(group.prospect_ids), reverse=True)


def candidate_keys(prospect: Prospect) -> list[str]:
    keys: list[str] = []
    contact_key = contact_identity(prospect)
    if contact_key:
        keys.append(f"contact:{contact_key}")
    domain = normalize_domain(prospect.website or prospect.profile_url or "")
    if domain:
        keys.append(f"domain:{domain}")
    company = normalize_company(prospect.company_name or "")
    if company:
        keys.append(f"company:{company}")
    return keys


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    ignored = {
        "github.com",
        "gitee.com",
        "zhihu.com",
        "douyin.com",
        "xiaohongshu.com",
        "v2ex.com",
        "segmentfault.com",
        "learnku.com",
        "sellercentral.amazon.com",
        "claude.com",
        "claude.ai",
    }
    if host in ignored or not host or "." not in host:
        return ""
    return host


def normalize_company(value: str) -> str:
    compact = "".join(value.lower().split())
    if len(compact) < 4 or len(compact) > 24:
        return ""
    noise = {"个人", "工作室", "团队", "公司", "未知公司"}
    if compact in noise:
        return ""
    strong_suffixes = ("公司", "工作室", "团队", "科技", "贸易", "传媒", "集团")
    weak_sentence_starts = ("想", "没想到", "让", "用", "做个", "为什么", "怎么")
    if not compact.endswith(strong_suffixes):
        return ""
    if compact.startswith(weak_sentence_starts):
        return ""
    return compact[:80]


def clear_duplicate_markers(prospects: list[Prospect]) -> int:
    changed = 0
    for prospect in prospects:
        note = prospect.follow_up_note or ""
        if "疑似重复客户:" not in note:
            continue
        lines = [line for line in note.splitlines() if "疑似重复客户:" not in line]
        prospect.follow_up_note = "\n".join(lines)
        if prospect.next_action == "疑似重复客户，跟进前先合并证据并确认主客户。":
            prospect.next_action = prospect.suggested_action or ""
        prospect.updated_at = datetime.now()
        changed += 1
    return changed


def mark_duplicate_candidates(prospects: list[Prospect], groups: list[DuplicateGroup]) -> int:
    prospect_map = {prospect.id: prospect for prospect in prospects}
    marked = 0
    for group in groups:
        primary_id = choose_primary_id([prospect_map[item] for item in group.prospect_ids])
        for prospect_id in group.prospect_ids:
            if prospect_id == primary_id:
                continue
            prospect = prospect_map[prospect_id]
            note = f"疑似重复客户: primary={primary_id}, key={group.key}"
            if note in (prospect.follow_up_note or ""):
                continue
            prospect.follow_up_note = merge_note(prospect.follow_up_note or "", note)
            if prospect.status == "new":
                prospect.next_action = "疑似重复客户，跟进前先合并证据并确认主客户。"
            prospect.updated_at = datetime.now()
            marked += 1
    return marked


def choose_primary_id(prospects: list[Prospect]) -> int:
    primary = max(
        prospects,
        key=lambda row: (
            row.status in {"won", "trial_sent", "wechat_added", "contacted", "qualified"},
            row.lead_score or 0,
            row.mention_count or 0,
            row.id,
        ),
    )
    return primary.id


def relink_prospect_events(db: Session) -> int:
    prospects = {prospect.identity_key: prospect.id for prospect in db.scalars(select(Prospect)).all()}
    prospect_ids = set(prospects.values())
    changed = 0
    events = list(db.scalars(select(ProspectEvent).where(ProspectEvent.identity_key != "")))
    for event in events:
        current_id = prospects.get(event.identity_key)
        if current_id and (event.prospect_id not in prospect_ids or event.prospect_id != current_id):
            event.prospect_id = current_id
            changed += 1
    return changed


def merge_note(old: str, new: str) -> str:
    old = old.strip()
    new = new.strip()
    if not old:
        return new
    if not new or new in old:
        return old
    return f"{old}\n{new}"
