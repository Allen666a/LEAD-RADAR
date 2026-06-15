from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
database_path = settings.database_path
if database_path is not None:
    database_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def create_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_columns()


def ensure_columns() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "mentions" not in table_names:
        return

    mention_columns = {column["name"] for column in inspector.get_columns("mentions")}
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    prospect_columns = (
        {column["name"] for column in inspector.get_columns("prospects")}
        if "prospects" in inspector.get_table_names()
        else set()
    )
    event_columns = (
        {column["name"] for column in inspector.get_columns("prospect_events")}
        if "prospect_events" in table_names
        else set()
    )
    missing = []
    if "score_reasons" not in mention_columns:
        missing.append("ALTER TABLE mentions ADD COLUMN score_reasons TEXT DEFAULT ''")
    if "outreach_message" not in mention_columns:
        missing.append("ALTER TABLE mentions ADD COLUMN outreach_message TEXT DEFAULT ''")
    if "signal_type" not in mention_columns:
        missing.append(
            "ALTER TABLE mentions ADD COLUMN signal_type VARCHAR(60) DEFAULT 'community_signal'"
        )
    if "prospect_id" not in mention_columns:
        missing.append("ALTER TABLE mentions ADD COLUMN prospect_id INTEGER")
    if "mode" not in mention_columns:
        missing.append("ALTER TABLE mentions ADD COLUMN mode VARCHAR(40) DEFAULT 'demand_radar'")
    if "company_id" not in mention_columns:
        missing.append("ALTER TABLE mentions ADD COLUMN company_id INTEGER")
    for score_column in [
        "fit_score",
        "intent_score",
        "contact_score",
        "risk_score",
        "priority_score",
    ]:
        if score_column not in mention_columns:
            missing.append(f"ALTER TABLE mentions ADD COLUMN {score_column} INTEGER DEFAULT 0")
    if "last_checked_at" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_checked_at DATETIME")
    if "success_count" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN success_count INTEGER DEFAULT 0")
    if "failure_count" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN failure_count INTEGER DEFAULT 0")
    if "consecutive_failures" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN consecutive_failures INTEGER DEFAULT 0")
    if "last_error" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_error TEXT DEFAULT ''")
    if "last_fetched_count" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_fetched_count INTEGER DEFAULT 0")
    if "last_inserted_count" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_inserted_count INTEGER DEFAULT 0")
    if "quality_score" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN quality_score INTEGER DEFAULT 50")
    if "quality_status" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN quality_status VARCHAR(40) DEFAULT 'unchecked'")
    if "quality_reason" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN quality_reason TEXT DEFAULT ''")
    if "last_quality_at" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_quality_at DATETIME")
    if "auto_disabled_at" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN auto_disabled_at DATETIME")
    if "feedback_score" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN feedback_score INTEGER DEFAULT 50")
    if "learned_priority" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN learned_priority INTEGER DEFAULT 50")
    if "learning_status" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN learning_status VARCHAR(40) DEFAULT 'neutral'")
    if "learning_reason" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN learning_reason TEXT DEFAULT ''")
    if "learning_updated_at" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN learning_updated_at DATETIME")
    if "mode" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN mode VARCHAR(40) DEFAULT 'demand_radar'")
    if "permission_status" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN permission_status VARCHAR(60) DEFAULT 'unknown'")
    if "noise_rate" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN noise_rate INTEGER DEFAULT 0")
    if "qualified_rate" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN qualified_rate INTEGER DEFAULT 0")
    if "contactable_rate" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN contactable_rate INTEGER DEFAULT 0")
    if "roi_score" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN roi_score INTEGER DEFAULT 50")
    if "next_collect_at" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN next_collect_at DATETIME")
    if "cooldown_until" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN cooldown_until DATETIME")
    if "crawl_backoff_level" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN crawl_backoff_level INTEGER DEFAULT 0")
    if "last_cursor" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_cursor VARCHAR(260) DEFAULT ''")
    if "last_run_reason" not in source_columns:
        missing.append("ALTER TABLE sources ADD COLUMN last_run_reason TEXT DEFAULT ''")
    if "prospects" in inspector.get_table_names():
        if "company_name" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN company_name VARCHAR(260) DEFAULT ''")
        if "region" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN region VARCHAR(120) DEFAULT ''")
        if "website" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN website TEXT DEFAULT ''")
        if "email" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN email VARCHAR(260) DEFAULT ''")
        if "wechat" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN wechat VARCHAR(160) DEFAULT ''")
        if "telegram" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN telegram VARCHAR(160) DEFAULT ''")
        if "contact_note" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN contact_note TEXT DEFAULT ''")
        if "customer_type" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN customer_type VARCHAR(60) DEFAULT 'unknown'")
        if "pitch_message" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN pitch_message TEXT DEFAULT ''")
        if "first_touch_message" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN first_touch_message TEXT DEFAULT ''")
        if "follow_up_message" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN follow_up_message TEXT DEFAULT ''")
        if "trial_message" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN trial_message TEXT DEFAULT ''")
        if "closing_message" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN closing_message TEXT DEFAULT ''")
        if "suggested_action" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN suggested_action TEXT DEFAULT ''")
        if "next_action" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN next_action TEXT DEFAULT ''")
        if "follow_up_note" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN follow_up_note TEXT DEFAULT ''")
        if "last_contacted_at" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN last_contacted_at DATETIME")
        if "next_follow_up_at" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN next_follow_up_at DATETIME")
        if "company_id" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN company_id INTEGER")
        if "mode" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN mode VARCHAR(40) DEFAULT 'demand_radar'")
        for score_column in [
            "fit_score",
            "intent_score",
            "contact_score",
            "risk_score",
            "priority_score",
        ]:
            if score_column not in prospect_columns:
                missing.append(f"ALTER TABLE prospects ADD COLUMN {score_column} INTEGER DEFAULT 0")
        if "contact_status" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN contact_status VARCHAR(60) DEFAULT 'unknown'")
        if "suppressed" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN suppressed BOOLEAN DEFAULT 0")
        if "suppression_reason" not in prospect_columns:
            missing.append("ALTER TABLE prospects ADD COLUMN suppression_reason TEXT DEFAULT ''")
    if "prospect_events" in inspector.get_table_names():
        if "identity_key" not in event_columns:
            missing.append("ALTER TABLE prospect_events ADD COLUMN identity_key VARCHAR(260) DEFAULT ''")

    if "candidate_items" in table_names:
        candidate_columns = {column["name"] for column in inspector.get_columns("candidate_items")}
        if "platform" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN platform VARCHAR(80) DEFAULT ''")
        if "gate_reason" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN gate_reason TEXT DEFAULT ''")
        if "mention_id" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN mention_id INTEGER")
        if "score" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN score INTEGER DEFAULT 0")
        if "signal_type" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN signal_type VARCHAR(60) DEFAULT ''")
        if "failure_type" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN failure_type VARCHAR(60) DEFAULT ''")
        if "detail_status" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN detail_status VARCHAR(40) DEFAULT 'not_checked'")
        if "detail_reason" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN detail_reason TEXT DEFAULT ''")
        if "detail_excerpt" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN detail_excerpt TEXT DEFAULT ''")
        if "updated_at" not in candidate_columns:
            missing.append("ALTER TABLE candidate_items ADD COLUMN updated_at DATETIME")

    with engine.begin() as connection:
        for statement in missing:
            connection.execute(text(statement))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
