from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phrase: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    weight: Mapped[int] = mapped_column(Integer, default=10)
    category: Mapped[str] = mapped_column(String(60), default="intent")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    last_inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[int] = mapped_column(Integer, default=50, index=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="unchecked", index=True)
    quality_reason: Mapped[str] = mapped_column(Text, default="")
    last_quality_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    feedback_score: Mapped[int] = mapped_column(Integer, default=50, index=True)
    learned_priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    learning_status: Mapped[str] = mapped_column(String(40), default="neutral", index=True)
    learning_reason: Mapped[str] = mapped_column(Text, default="")
    learning_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mode: Mapped[str] = mapped_column(String(40), default="demand_radar", index=True)
    permission_status: Mapped[str] = mapped_column(String(60), default="unknown", index=True)
    noise_rate: Mapped[int] = mapped_column(Integer, default=0)
    qualified_rate: Mapped[int] = mapped_column(Integer, default=0)
    contactable_rate: Mapped[int] = mapped_column(Integer, default=0)
    roi_score: Mapped[int] = mapped_column(Integer, default=50, index=True)
    next_collect_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    crawl_backoff_level: Mapped[int] = mapped_column(Integer, default=0)
    last_cursor: Mapped[str] = mapped_column(String(260), default="", index=True)
    last_run_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_mentions_canonical_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(120), index=True)
    source_kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    matched_keywords: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    signal_type: Mapped[str] = mapped_column(String(60), default="community_signal", index=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), default="normal", index=True)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    score_reasons: Mapped[str] = mapped_column(Text, default="")
    outreach_message: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(40), default="demand_radar", index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fit_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    intent_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    contact_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CandidateItem(Base):
    __tablename__ = "candidate_items"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_candidate_items_canonical_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(160), index=True)
    source_kind: Mapped[str] = mapped_column(String(80), index=True)
    platform: Mapped[str] = mapped_column(String(80), default="", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    canonical_url: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="candidate", index=True)
    gate_reason: Mapped[str] = mapped_column(Text, default="")
    mention_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    signal_type: Mapped[str] = mapped_column(String(60), default="", index=True)
    failure_type: Mapped[str] = mapped_column(String(60), default="", index=True)
    detail_status: Mapped[str] = mapped_column(String(40), default="not_checked", index=True)
    detail_reason: Mapped[str] = mapped_column(Text, default="")
    detail_excerpt: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (UniqueConstraint("identity_key", name="uq_prospects_identity_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(80), index=True)
    display_name: Mapped[str] = mapped_column(String(260), default="")
    company_name: Mapped[str] = mapped_column(String(260), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    profile_url: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String(260), default="")
    wechat: Mapped[str] = mapped_column(String(160), default="")
    telegram: Mapped[str] = mapped_column(String(160), default="")
    contact_note: Mapped[str] = mapped_column(Text, default="")
    product_fit: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    customer_type: Mapped[str] = mapped_column(String(60), default="unknown", index=True)
    lead_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(40), default="demand_radar", index=True)
    fit_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    intent_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    contact_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    contact_status: Mapped[str] = mapped_column(String(60), default="unknown", index=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    suppression_reason: Mapped[str] = mapped_column(Text, default="")
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    high_value_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_count: Mapped[int] = mapped_column(Integer, default=0)
    signal_types: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    pitch_message: Mapped[str] = mapped_column(Text, default="")
    first_touch_message: Mapped[str] = mapped_column(Text, default="")
    follow_up_message: Mapped[str] = mapped_column(Text, default="")
    trial_message: Mapped[str] = mapped_column(Text, default="")
    closing_message: Mapped[str] = mapped_column(Text, default="")
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    next_action: Mapped[str] = mapped_column(Text, default="")
    follow_up_note: Mapped[str] = mapped_column(Text, default="")
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    __table_args__ = (UniqueConstraint("company_key", name="uq_company_profiles_company_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(260), default="", index=True)
    domain: Mapped[str] = mapped_column(String(260), default="", index=True)
    website: Mapped[str] = mapped_column(Text, default="")
    country: Mapped[str] = mapped_column(String(120), default="", index=True)
    region: Mapped[str] = mapped_column(String(120), default="")
    industry: Mapped[str] = mapped_column(String(160), default="", index=True)
    company_size: Mapped[str] = mapped_column(String(80), default="")
    customer_type: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    product_category: Mapped[str] = mapped_column(String(120), default="", index=True)
    business_scenario: Mapped[str] = mapped_column(Text, default="")
    fit_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    intent_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    contact_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    deal_probability: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    need_reason: Mapped[str] = mapped_column(Text, default="")
    contact_status: Mapped[str] = mapped_column(String(60), default="unknown", index=True)
    crm_status: Mapped[str] = mapped_column(String(60), default="new", index=True)
    next_action: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(120), default="")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    contact_count: Mapped[int] = mapped_column(Integer, default=0)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CompanySignal(Base):
    __tablename__ = "company_signals"
    __table_args__ = (UniqueConstraint("company_id", "url", name="uq_company_signals_company_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    mention_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(160), default="", index=True)
    source_kind: Mapped[str] = mapped_column(String(80), default="", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), default="community_pain", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    content_snippet: Mapped[str] = mapped_column(Text, default="")
    matched_keywords: Mapped[str] = mapped_column(Text, default="")
    fit_delta: Mapped[int] = mapped_column(Integer, default=0)
    intent_delta: Mapped[int] = mapped_column(Integer, default=0)
    risk_delta: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ContactRecord(Base):
    __tablename__ = "contact_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    prospect_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contact_type: Mapped[str] = mapped_column(String(60), default="other", index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    normalized_value: Mapped[str] = mapped_column(String(260), default="", index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0, index=True)
    is_business_contact: Mapped[bool] = mapped_column(Boolean, default=True)
    personal_data_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(60), default="unverified", index=True)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutreachActivity(Base):
    __tablename__ = "outreach_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    prospect_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    activity_type: Mapped[str] = mapped_column(String(80), default="manual_note", index=True)
    channel: Mapped[str] = mapped_column(String(60), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(60), default="done", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(80), default="", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SuppressionEntry(Base):
    __tablename__ = "suppression_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), default="", index=True)
    value: Mapped[str] = mapped_column(String(260), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mention_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(40), default="wework")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    dedupe_key: Mapped[str] = mapped_column(String(260), default="", index=True)
    locked_by: Mapped[str] = mapped_column(String(120), default="", index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentWorker(Base):
    __tablename__ = "agent_workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    pid: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="starting", index=True)
    current_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    jobs_done: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProspectEvent(Base):
    __tablename__ = "prospect_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(Integer, index=True)
    identity_key: Mapped[str] = mapped_column(String(260), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[str] = mapped_column(String(160), default="", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(80), default="", index=True)
    customer_type: Mapped[str] = mapped_column(String(60), default="", index=True)
    product_fit: Mapped[str] = mapped_column(String(40), default="", index=True)
    lead_score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
