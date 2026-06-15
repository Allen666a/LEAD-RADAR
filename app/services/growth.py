from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Keyword, Source
from app.services.ingest import run_ingestion_sync
from app.services.prospects import rebuild_prospects
from app.services.source_quality import audit_all_sources
from app.services.strategy import (
    KeywordSuggestion,
    SourceSuggestion,
    build_keyword_suggestions,
    build_source_suggestions,
)


@dataclass(frozen=True)
class ApplyResult:
    created: int
    updated: int
    skipped: int
    names: list[str]


@dataclass(frozen=True)
class GrowthCycleResult:
    keywords: ApplyResult
    sources: ApplyResult
    ingestion: dict[str, int] | None
    prospects: dict[str, int] | None
    audit: dict[str, int] | None
    ran_at: datetime


def apply_keyword_suggestions(db: Session, limit: int = 10) -> ApplyResult:
    suggestions = build_keyword_suggestions(db)[: max(0, limit)]
    created = 0
    updated = 0
    names: list[str] = []

    for item in suggestions:
        result = upsert_keyword(db, item)
        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        names.append(item.phrase)

    db.commit()
    return ApplyResult(created=created, updated=updated, skipped=max(0, limit - len(suggestions)), names=names)


def apply_source_suggestions(db: Session, limit: int = 12) -> ApplyResult:
    suggestions = build_source_suggestions(db)[: max(0, limit)]
    created = 0
    updated = 0
    names: list[str] = []

    for item in suggestions:
        result = upsert_source(db, item)
        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        names.append(item.name)

    db.commit()
    return ApplyResult(created=created, updated=updated, skipped=max(0, limit - len(suggestions)), names=names)


def run_growth_cycle(
    db: Session,
    keyword_limit: int = 6,
    source_limit: int = 8,
    run_collect: bool = True,
    auto_disable_sources: bool = False,
) -> GrowthCycleResult:
    keywords = apply_keyword_suggestions(db, limit=keyword_limit)
    sources = apply_source_suggestions(db, limit=source_limit)

    ingestion = run_ingestion_sync(db) if run_collect else None
    prospects = rebuild_prospects(db)
    audit = audit_all_sources(db, auto_disable=auto_disable_sources)

    return GrowthCycleResult(
        keywords=keywords,
        sources=sources,
        ingestion=ingestion,
        prospects=prospects,
        audit=audit,
        ran_at=datetime.now(),
    )


def upsert_keyword(db: Session, item: KeywordSuggestion) -> str:
    keyword = db.query(Keyword).filter(Keyword.phrase == item.phrase).first()
    if keyword is None:
        db.add(
            Keyword(
                phrase=item.phrase[:160],
                weight=max(1, min(100, item.weight)),
                category=item.category[:60],
                enabled=True,
            )
        )
        return "created"

    changed = False
    if keyword.weight != item.weight:
        keyword.weight = max(1, min(100, item.weight))
        changed = True
    if keyword.category != item.category:
        keyword.category = item.category[:60]
        changed = True
    if not keyword.enabled:
        keyword.enabled = True
        changed = True
    return "updated" if changed else "skipped"


def upsert_source(db: Session, item: SourceSuggestion) -> str:
    source = db.query(Source).filter(Source.name == item.name).first()
    if source is None:
        db.add(
            Source(
                name=item.name[:120],
                kind=item.kind[:40],
                url=item.url,
                enabled=True,
            )
        )
        return "created"

    changed = False
    if source.kind != item.kind:
        source.kind = item.kind[:40]
        changed = True
    if source.url != item.url:
        source.url = item.url
        changed = True
    if not source.enabled:
        source.enabled = True
        source.auto_disabled_at = None
        changed = True
    return "updated" if changed else "skipped"
