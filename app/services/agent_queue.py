from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, create_db
from app.models import AgentJob, AgentWorker, Mention, Prospect
from app.services.cadence import load_cadence_tasks
from app.services.b2b_enrichment import (
    enrich_company_contacts_from_pages,
    enrich_github_companies,
    run_b2b_waterfall,
    scan_company_websites,
)
from app.services.compliance import run_compliance_audit
from app.services.contact_enrichment import apply_contact_enrichment, build_contact_enrichment_report
from app.services.contact_workbench import load_contact_workbench_rows
from app.services.dedupe import run_dedupe_audit
from app.services.feedback import feedback_snapshot
from app.services.ingest import (
    purge_noise_mentions,
    refresh_existing_mentions,
    run_domestic_acquisition_sync,
)
from app.services.icp_audit import build_icp_quality_audit
from app.services.learning import run_feedback_learning
from app.services.performance import build_platform_performance
from app.services.prospect_hygiene import run_prospect_hygiene
from app.services.p3_quality import run_p3_quality_audit
from app.services.prospects import rebuild_prospects
from app.services.research import load_research_briefs
from app.services.session_collector import run_enabled_session_collections
from app.services.source_quality import audit_all_sources


JOB_LABELS = {
    "domestic_pipeline": "国内获客流水线",
    "collect_domestic": "国内来源采集",
    "refresh_scores": "线索重评分",
    "purge_noise": "清理噪音线索",
    "rebuild_prospects": "重建客户画像",
    "audit_sources": "来源质量审计",
    "research_snapshot": "客户研究快照",
    "cadence_snapshot": "销售节奏快照",
    "contact_snapshot": "补联系方式快照",
    "performance_snapshot": "平台效果快照",
    "feedback_snapshot": "转化反馈快照",
    "feedback_learning": "反馈学习调权",
    "contact_enrichment": "联系人自动补全",
    "prospect_hygiene": "客户质量清洗",
    "dedupe_audit": "重复客户审计",
    "compliance_audit": "合规风险审核",
    "session_domestic": "国内会话采集",
    "icp_quality_audit": "ICP 质量审计",
    "b2b_website_scan": "B2B 官网扫描",
    "b2b_github_enrich": "B2B GitHub 增强",
    "b2b_contact_waterfall": "B2B 联系方式补全",
    "b2b_waterfall": "B2B Waterfall",
    "p3_quality_audit": "P3 线索质量审计",
}

ACTIVE_JOB_STATUSES = {"queued", "retry", "running"}
WORKER_ACTIVE_STATUSES = {"starting", "idle", "running"}
AGENT_ENGINE_VERSION = "v7-p3-quality"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DATA_DIR = PROJECT_ROOT / "data" / "agents"
AGENT_LOG_DIR = AGENT_DATA_DIR / "logs"
SNAPSHOT_DIR = AGENT_DATA_DIR / "snapshots"


@dataclass(frozen=True)
class QueueStats:
    queued: int
    running: int
    retry: int
    done: int
    failed: int
    active_workers: int
    total_workers: int


def ensure_agent_dirs() -> None:
    AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def enqueue_job(
    db: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    priority: int = 50,
    dedupe_key: str = "",
    max_attempts: int = 2,
) -> AgentJob:
    payload = payload or {}
    label = JOB_LABELS.get(kind, kind)
    if dedupe_key:
        existing = db.scalar(
            select(AgentJob)
            .where(AgentJob.dedupe_key == dedupe_key)
            .where(AgentJob.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(desc(AgentJob.created_at))
            .limit(1)
        )
        if existing is not None:
            return existing

    now = datetime.now()
    job = AgentJob(
        kind=kind,
        label=label,
        status="queued",
        priority=priority,
        payload_json=json_dumps(payload),
        result_json="{}",
        error="",
        attempts=0,
        max_attempts=max_attempts,
        dedupe_key=dedupe_key,
        next_run_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_practical_domestic_cycle(
    db: Session,
    source_limit: int = 30,
    dedupe_minutes: int = 20,
) -> AgentJob:
    bucket = datetime.now().strftime("%Y%m%d%H")
    minute_bucket = datetime.now().minute // max(1, dedupe_minutes)
    return enqueue_job(
        db,
        "domestic_pipeline",
        payload={"source_limit": max(1, min(100, source_limit))},
        priority=100,
        dedupe_key=f"domestic-pipeline:{bucket}:{minute_bucket}",
        max_attempts=2,
    )


def enqueue_b2b_job(db: Session, kind: str, limit: int = 10) -> AgentJob:
    allowed = {
        "b2b_website_scan": 70,
        "b2b_github_enrich": 68,
        "b2b_contact_waterfall": 72,
        "b2b_waterfall": 85,
    }
    if kind not in allowed:
        raise ValueError(f"unknown b2b job kind: {kind}")
    safe_limit = max(1, min(80, int(limit)))
    bucket = datetime.now().strftime("%Y%m%d%H%M")
    return enqueue_job(
        db,
        kind,
        payload={"limit": safe_limit},
        priority=allowed[kind],
        dedupe_key=f"{kind}:{safe_limit}:{bucket}",
        max_attempts=2,
    )


def enqueue_maintenance_pack(db: Session) -> list[AgentJob]:
    jobs = [
        enqueue_job(db, "refresh_scores", priority=80, dedupe_key=hourly_key("refresh_scores")),
        enqueue_job(db, "purge_noise", priority=78, dedupe_key=hourly_key("purge_noise")),
        enqueue_job(db, "rebuild_prospects", priority=75, dedupe_key=hourly_key("rebuild_prospects")),
        enqueue_job(db, "audit_sources", priority=65, dedupe_key=hourly_key("audit_sources")),
        enqueue_job(db, "research_snapshot", priority=60, dedupe_key=hourly_key("research_snapshot")),
        enqueue_job(db, "cadence_snapshot", priority=60, dedupe_key=hourly_key("cadence_snapshot")),
        enqueue_job(db, "contact_snapshot", priority=58, dedupe_key=hourly_key("contact_snapshot")),
        enqueue_job(db, "performance_snapshot", priority=55, dedupe_key=hourly_key("performance_snapshot")),
        enqueue_job(db, "feedback_snapshot", priority=54, dedupe_key=hourly_key("feedback_snapshot")),
        enqueue_job(db, "feedback_learning", priority=82, dedupe_key=hourly_key("feedback_learning")),
        enqueue_job(db, "contact_enrichment", priority=81, dedupe_key=hourly_key("contact_enrichment")),
        enqueue_job(db, "prospect_hygiene", priority=79, dedupe_key=hourly_key("prospect_hygiene")),
        enqueue_job(db, "dedupe_audit", priority=74, dedupe_key=hourly_key("dedupe_audit")),
        enqueue_job(db, "compliance_audit", priority=73, dedupe_key=hourly_key("compliance_audit")),
        enqueue_job(db, "p3_quality_audit", priority=76, dedupe_key=hourly_key("p3_quality_audit")),
    ]
    return jobs


def hourly_key(kind: str) -> str:
    return f"{kind}:{datetime.now().strftime('%Y%m%d%H')}"


def reset_stale_jobs(db: Session, stale_minutes: int = 90) -> int:
    cutoff = datetime.now() - timedelta(minutes=stale_minutes)
    stale_jobs = list(
        db.scalars(
            select(AgentJob)
            .where(AgentJob.status == "running")
            .where(AgentJob.started_at.is_not(None))
            .where(AgentJob.started_at < cutoff)
        )
    )
    for job in stale_jobs:
        if job.attempts < job.max_attempts:
            job.status = "retry"
            job.next_run_at = datetime.now() + timedelta(minutes=3)
            job.error = "worker heartbeat expired; job will retry"
        else:
            job.status = "failed"
            job.finished_at = datetime.now()
            job.error = "worker heartbeat expired; max attempts reached"
        job.locked_by = ""
        job.updated_at = datetime.now()
    db.commit()
    return len(stale_jobs)


def claim_next_job(db: Session, worker_id: str) -> AgentJob | None:
    now = datetime.now()
    statement = text(
        """
        UPDATE agent_jobs
        SET status = 'running',
            locked_by = :worker_id,
            started_at = :now,
            updated_at = :now,
            attempts = attempts + 1,
            error = ''
        WHERE id = (
            SELECT id
            FROM agent_jobs
            WHERE status IN ('queued', 'retry')
              AND (next_run_at IS NULL OR next_run_at <= :now)
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        )
        """
    )
    result = db.execute(statement, {"worker_id": worker_id, "now": now})
    db.commit()
    if result.rowcount == 0:
        return None
    return db.scalar(
        select(AgentJob)
        .where(AgentJob.status == "running")
        .where(AgentJob.locked_by == worker_id)
        .order_by(desc(AgentJob.started_at), desc(AgentJob.id))
        .limit(1)
    )


def complete_job(db: Session, job: AgentJob, result: dict[str, Any]) -> None:
    now = datetime.now()
    job.status = "done"
    job.result_json = json_dumps(result)
    job.error = ""
    job.finished_at = now
    job.updated_at = now
    db.commit()


def fail_job(db: Session, job: AgentJob, error: str) -> None:
    now = datetime.now()
    short_error = (error or "unknown error")[:2000]
    if job.attempts < job.max_attempts:
        job.status = "retry"
        job.next_run_at = now + timedelta(minutes=min(20, 2 * job.attempts + 1))
    else:
        job.status = "failed"
        job.finished_at = now
    job.error = short_error
    job.locked_by = ""
    job.updated_at = now
    db.commit()


def execute_job(db: Session, job: AgentJob) -> dict[str, Any]:
    payload = json_loads(job.payload_json, {})
    kind = job.kind
    if kind == "domestic_pipeline":
        return run_domestic_pipeline(db, payload)
    if kind == "collect_domestic":
        return run_domestic_acquisition_sync(db, source_limit=int(payload.get("source_limit", 30)))
    if kind == "refresh_scores":
        return refresh_existing_mentions(db)
    if kind == "purge_noise":
        return purge_noise_mentions(db)
    if kind == "rebuild_prospects":
        return rebuild_prospects(db)
    if kind == "audit_sources":
        return audit_all_sources(db, auto_disable=bool(payload.get("auto_disable", True)))
    if kind == "research_snapshot":
        return build_research_snapshot(db)
    if kind == "cadence_snapshot":
        return build_cadence_snapshot(db)
    if kind == "contact_snapshot":
        return build_contact_snapshot(db)
    if kind == "icp_quality_audit":
        return build_icp_quality_snapshot(db)
    if kind == "performance_snapshot":
        return build_performance_snapshot(db)
    if kind == "feedback_snapshot":
        return build_feedback_snapshot(db)
    if kind == "feedback_learning":
        return run_feedback_learning(db, apply=bool(payload.get("apply", True)))
    if kind == "contact_enrichment":
        return build_contact_enrichment_snapshot(db)
    if kind == "prospect_hygiene":
        return build_prospect_hygiene_snapshot(db)
    if kind == "dedupe_audit":
        return build_dedupe_audit_snapshot(db)
    if kind == "compliance_audit":
        return build_compliance_audit_snapshot(db)
    if kind == "p3_quality_audit":
        return build_p3_quality_snapshot(db, payload)
    if kind == "session_domestic":
        return build_session_domestic_snapshot(db, payload)
    if kind == "b2b_website_scan":
        return build_b2b_website_scan_snapshot(db, payload)
    if kind == "b2b_github_enrich":
        return build_b2b_github_enrich_snapshot(db, payload)
    if kind == "b2b_contact_waterfall":
        return build_b2b_contact_waterfall_snapshot(db, payload)
    if kind == "b2b_waterfall":
        return build_b2b_waterfall_snapshot(db, payload)
    raise ValueError(f"unknown agent job kind: {kind}")


def run_domestic_pipeline(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    source_limit = int(payload.get("source_limit", 30))
    result: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source_limit": source_limit,
    }
    result["collect"] = run_domestic_acquisition_sync(db, source_limit=source_limit)
    result["refresh_scores"] = refresh_existing_mentions(db)
    result["purge_noise"] = purge_noise_mentions(db)
    result["rebuild_prospects"] = rebuild_prospects(db)
    result["prospect_hygiene"] = build_prospect_hygiene_snapshot(db)
    result["audit_sources"] = audit_all_sources(db, auto_disable=True)
    result["feedback_learning"] = run_feedback_learning(db, apply=True)
    result["contact_enrichment"] = build_contact_enrichment_snapshot(db)
    result["dedupe_audit"] = build_dedupe_audit_snapshot(db)
    result["compliance_audit"] = build_compliance_audit_snapshot(db)
    result["contact_snapshot"] = build_contact_snapshot(db)
    result["icp_quality_audit"] = build_icp_quality_snapshot(db)
    result["research_snapshot"] = build_research_snapshot(db)
    result["cadence_snapshot"] = build_cadence_snapshot(db)
    result["performance_snapshot"] = build_performance_snapshot(db)
    result["feedback_snapshot"] = build_feedback_snapshot(db)
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_snapshot("domestic_pipeline_latest", result)
    return result


def build_icp_quality_snapshot(db: Session) -> dict[str, Any]:
    result = build_icp_quality_audit(db)
    write_snapshot("icp_quality_latest", result)
    return result


def build_contact_snapshot(db: Session) -> dict[str, Any]:
    rows = load_contact_workbench_rows(db, mode="missing", platform="domestic", min_score=60, limit=300)
    hot = [row for row in rows if row.priority_score >= 80]
    by_platform = Counter(row.prospect.platform for row in rows)
    result = {
        "missing_contacts": len(rows),
        "hot_missing_contacts": len(hot),
        "top_platforms": by_platform.most_common(8),
        "top_prospects": [
            {
                "id": row.prospect.id,
                "name": row.display_label,
                "platform": row.prospect.platform,
                "score": row.priority_score,
                "query": row.search_query,
                "action_hint": row.action_hint,
                "links": [{"label": link.label, "url": link.url} for link in row.search_links],
            }
            for row in hot[:20]
        ],
    }
    write_snapshot("contact_latest", result)
    return result


def build_prospect_hygiene_snapshot(db: Session) -> dict[str, Any]:
    result = run_prospect_hygiene(db, apply=True)
    write_snapshot("prospect_hygiene_latest", result)
    return result


def build_research_snapshot(db: Session) -> dict[str, Any]:
    briefs = load_research_briefs(db, mode="priority", platform="domestic", min_score=60, limit=120)
    high = [brief for brief in briefs if brief.priority_score >= 85]
    contactable = [brief for brief in briefs if brief.has_contact]
    by_type = Counter(brief.prospect.customer_type for brief in briefs)
    result = {
        "briefs": len(briefs),
        "high_priority": len(high),
        "contactable": len(contactable),
        "top_customer_types": by_type.most_common(8),
        "top_accounts": [
            {
                "id": brief.prospect.id,
                "name": brief.prospect.display_name,
                "platform": brief.prospect.platform,
                "score": brief.priority_score,
                "customer_type": brief.prospect.customer_type,
                "has_contact": brief.has_contact,
                "next_actions": brief.next_actions[:3],
            }
            for brief in high[:20]
        ],
    }
    write_snapshot("research_latest", result)
    return result


def build_cadence_snapshot(db: Session) -> dict[str, Any]:
    tasks = load_cadence_tasks(db, mode="today", platform="domestic", min_score=60, limit=300)
    by_type = Counter(task.task_type for task in tasks)
    result = {
        "tasks": len(tasks),
        "by_type": by_type.most_common(),
        "top_tasks": [
            {
                "prospect_id": task.prospect.id,
                "name": task.prospect.display_name,
                "type": task.task_type,
                "priority": task.priority,
                "action": task.primary_action_label,
            }
            for task in tasks[:30]
        ],
    }
    write_snapshot("cadence_latest", result)
    return result


def build_performance_snapshot(db: Session) -> dict[str, Any]:
    rows = build_platform_performance(db)
    result = {
        "platforms": len(rows),
        "top_platforms": [
            {
                "platform": row.platform,
                "score": row.score,
                "prospects": row.prospects,
                "contactable": row.contactable_prospects,
                "high_value": row.high_value_mentions,
                "recommendation": row.recommendation,
            }
            for row in rows[:12]
        ],
    }
    write_snapshot("performance_latest", result)
    return result


def build_feedback_snapshot(db: Session) -> dict[str, Any]:
    result = feedback_snapshot(db)
    write_snapshot("feedback_latest", result)
    return result


def build_contact_enrichment_snapshot(db: Session) -> dict[str, Any]:
    result = apply_contact_enrichment(db)
    result["report"] = build_contact_enrichment_report(db, limit=120)
    write_snapshot("contact_enrichment_latest", result)
    return result


def build_dedupe_audit_snapshot(db: Session) -> dict[str, Any]:
    result = run_dedupe_audit(db, mark_candidates=True)
    write_snapshot("dedupe_latest", result)
    return result


def build_compliance_audit_snapshot(db: Session) -> dict[str, Any]:
    result = run_compliance_audit(db, apply=True)
    write_snapshot("compliance_latest", result)
    return result


def build_p3_quality_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = run_p3_quality_audit(db, limit=int(payload.get("limit", 500)))
    write_snapshot("p3_quality_latest", result)
    return result


def build_session_domestic_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = run_enabled_session_collections(
        db,
        platform_limit=int(payload.get("platform_limit", 2)),
        keyword_limit=int(payload.get("keyword_limit", 1)),
        per_platform_limit=int(payload.get("per_platform_limit", 5)),
        headless=bool(payload.get("headless", True)),
    )
    result["p4"] = {
        "candidates": sum(int(row.get("candidates", 0) or 0) for row in result.get("results", [])),
        "rejected": sum(int(row.get("rejected", 0) or 0) for row in result.get("results", [])),
        "high_quality": sum(int(row.get("high_quality", 0) or 0) for row in result.get("results", [])),
        "failure_codes": [
            row.get("failure_code")
            for row in result.get("results", [])
            if isinstance(row, dict) and row.get("failure_code")
        ],
    }
    write_snapshot("session_domestic_latest", result)
    return result


def step_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "step": getattr(result, "step", ""),
        "scanned": getattr(result, "scanned", 0),
        "created_signals": getattr(result, "created_signals", 0),
        "created_contacts": getattr(result, "created_contacts", 0),
        "enriched_companies": getattr(result, "enriched_companies", 0),
        "failed": getattr(result, "failed", 0),
        "notes": list(getattr(result, "notes", []) or [])[:12],
    }


def build_b2b_website_scan_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = scan_company_websites(db, limit=int(payload.get("limit", 10)))
    data = step_result_to_dict(result)
    write_snapshot("b2b_website_scan_latest", data)
    return data


def build_b2b_github_enrich_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = enrich_github_companies(db, limit=int(payload.get("limit", 10)))
    data = step_result_to_dict(result)
    write_snapshot("b2b_github_enrich_latest", data)
    return data


def build_b2b_contact_waterfall_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = enrich_company_contacts_from_pages(db, limit=int(payload.get("limit", 10)))
    data = step_result_to_dict(result)
    write_snapshot("b2b_contact_waterfall_latest", data)
    return data


def build_b2b_waterfall_snapshot(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    result = run_b2b_waterfall(db, limit=int(payload.get("limit", 10)))
    data = {
        "companies_scanned": result.companies_scanned,
        "website": step_result_to_dict(result.website),
        "github": step_result_to_dict(result.github),
        "contacts": step_result_to_dict(result.contacts),
    }
    write_snapshot("b2b_waterfall_latest", data)
    return data


def write_snapshot(name: str, data: dict[str, Any]) -> None:
    ensure_agent_dirs()
    path = SNAPSHOT_DIR / f"{name}.json"
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "data": data}
    path.write_text(json_dumps(payload), encoding="utf-8")


def run_one_job(worker_id: str) -> bool:
    create_db()
    with SessionLocal() as db:
        reset_stale_jobs(db)
        job = claim_next_job(db, worker_id)
        if job is None:
            heartbeat_worker(db, worker_id, "idle", "waiting for jobs")
            return False
        heartbeat_worker(db, worker_id, "running", f"running {job.label or job.kind}", job.id)
        try:
            result = execute_job(db, job)
            complete_job(db, job, result)
            mark_worker_job_done(db, worker_id)
            return True
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            fail_job(db, job, str(exc) or exc.__class__.__name__)
            mark_worker_job_failed(db, worker_id, str(exc) or exc.__class__.__name__)
            return True


def run_worker_loop(worker_id: str, poll_seconds: int = 5, once: bool = False) -> None:
    create_db()
    with SessionLocal() as db:
        register_worker(db, worker_id, os.getpid())
    while True:
        with SessionLocal() as db:
            if worker_should_stop(db, worker_id):
                heartbeat_worker(db, worker_id, "stopped", "stop requested")
                return
        did_work = run_one_job(worker_id)
        if once:
            with SessionLocal() as db:
                heartbeat_worker(db, worker_id, "stopped", "one-shot worker finished")
            return
        if not did_work:
            time.sleep(max(1, poll_seconds))


def register_worker(db: Session, worker_id: str, pid: int) -> AgentWorker:
    worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
    now = datetime.now()
    if worker is None:
        worker = AgentWorker(worker_id=worker_id)
        db.add(worker)
    worker.pid = pid
    worker.status = "idle"
    worker.current_job_id = None
    worker.stop_requested = False
    worker.message = versioned_message("registered")
    worker.started_at = now
    worker.heartbeat_at = now
    worker.stopped_at = None
    db.commit()
    db.refresh(worker)
    return worker


def heartbeat_worker(
    db: Session,
    worker_id: str,
    status: str,
    message: str = "",
    current_job_id: int | None = None,
) -> None:
    worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
    if worker is None:
        worker = AgentWorker(worker_id=worker_id, pid=os.getpid())
        db.add(worker)
    worker.status = status
    worker.current_job_id = current_job_id
    worker.message = versioned_message(message)[:1000]
    worker.heartbeat_at = datetime.now()
    if status == "stopped":
        worker.stopped_at = datetime.now()
        worker.current_job_id = None
    db.commit()


def mark_worker_job_done(db: Session, worker_id: str) -> None:
    worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
    if worker is None:
        return
    worker.jobs_done = (worker.jobs_done or 0) + 1
    worker.current_job_id = None
    worker.status = "idle"
    worker.message = versioned_message("job done")
    worker.heartbeat_at = datetime.now()
    db.commit()


def mark_worker_job_failed(db: Session, worker_id: str, message: str) -> None:
    worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
    if worker is None:
        return
    worker.jobs_failed = (worker.jobs_failed or 0) + 1
    worker.current_job_id = None
    worker.status = "idle"
    worker.message = versioned_message(f"job failed: {message}")[:1000]
    worker.heartbeat_at = datetime.now()
    db.commit()


def worker_should_stop(db: Session, worker_id: str) -> bool:
    worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
    return bool(worker and worker.stop_requested)


def request_stop_workers(db: Session) -> int:
    workers = list(db.scalars(select(AgentWorker).where(AgentWorker.status.in_(WORKER_ACTIVE_STATUSES))))
    for worker in workers:
        worker.stop_requested = True
        worker.message = "stop requested"
        worker.heartbeat_at = datetime.now()
    db.commit()
    return len(workers)


def start_worker_processes(count: int = 3, poll_seconds: int = 5) -> list[dict[str, Any]]:
    ensure_agent_dirs()
    count = max(1, min(8, count))
    started: list[dict[str, Any]] = []
    for index in range(count):
        suffix = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{index}-{random.randint(1000, 9999)}"
        worker_id = f"agent-{suffix}"
        log_path = AGENT_LOG_DIR / f"{worker_id}.log"
        command = [
            sys.executable,
            "-m",
            "app.agent_worker",
            "--worker-id",
            worker_id,
            "--poll",
            str(max(1, poll_seconds)),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_file = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        started.append({"worker_id": worker_id, "pid": process.pid, "log": str(log_path)})
        with SessionLocal() as db:
            worker = db.scalar(select(AgentWorker).where(AgentWorker.worker_id == worker_id))
            if worker is None:
                worker = AgentWorker(worker_id=worker_id)
                db.add(worker)
            worker.pid = process.pid
            worker.status = "starting"
            worker.message = versioned_message("process started")
            worker.heartbeat_at = datetime.now()
            db.commit()
    return started


def ensure_worker_pool(
    db: Session,
    desired_count: int = 3,
    poll_seconds: int = 5,
) -> dict[str, Any]:
    desired_count = max(0, min(8, desired_count))
    if desired_count <= 0:
        return {"desired": 0, "active": queue_stats(db).active_workers, "started": []}
    mark_stale_workers(db)
    outdated = mark_outdated_workers(db)
    current_active = current_active_worker_count(db)
    missing = max(0, desired_count - current_active)
    started = start_worker_processes(missing, poll_seconds=poll_seconds) if missing else []
    return {
        "desired": desired_count,
        "active": current_active,
        "outdated": outdated,
        "missing": missing,
        "started": started,
    }


def versioned_message(message: str) -> str:
    message = (message or "").strip()
    if not message:
        return f"engine={AGENT_ENGINE_VERSION}"
    return f"{message} | engine={AGENT_ENGINE_VERSION}"


def worker_is_current(worker: AgentWorker) -> bool:
    return (not worker.stop_requested) and f"engine={AGENT_ENGINE_VERSION}" in (worker.message or "")


def current_active_worker_count(db: Session) -> int:
    workers = list(db.scalars(select(AgentWorker).where(AgentWorker.status.in_(WORKER_ACTIVE_STATUSES))))
    return sum(1 for worker in workers if worker_is_current(worker))


def mark_outdated_workers(db: Session) -> int:
    workers = list(db.scalars(select(AgentWorker).where(AgentWorker.status.in_(WORKER_ACTIVE_STATUSES))))
    outdated = [worker for worker in workers if not worker_is_current(worker)]
    for worker in outdated:
        worker.stop_requested = True
        worker.message = "restart requested for new engine"
        worker.heartbeat_at = datetime.now()
    db.commit()
    return len(outdated)


def queue_stats(db: Session) -> QueueStats:
    mark_stale_workers(db)
    mark_outdated_workers(db)
    counts = dict(db.query(AgentJob.status, func.count(AgentJob.id)).group_by(AgentJob.status).all())
    worker_counts = dict(
        db.query(AgentWorker.status, func.count(AgentWorker.id)).group_by(AgentWorker.status).all()
    )
    active_workers = current_active_worker_count(db)
    return QueueStats(
        queued=counts.get("queued", 0),
        running=counts.get("running", 0),
        retry=counts.get("retry", 0),
        done=counts.get("done", 0),
        failed=counts.get("failed", 0),
        active_workers=active_workers,
        total_workers=sum(worker_counts.values()),
    )


def mark_stale_workers(db: Session, stale_seconds: int = 300) -> int:
    cutoff = datetime.now() - timedelta(seconds=stale_seconds)
    workers = list(
        db.scalars(
            select(AgentWorker)
            .where(AgentWorker.status.in_(WORKER_ACTIVE_STATUSES))
            .where(AgentWorker.heartbeat_at.is_not(None))
            .where(AgentWorker.heartbeat_at < cutoff)
        )
    )
    for worker in workers:
        worker.status = "stopped"
        worker.current_job_id = None
        worker.message = "heartbeat stale"
        worker.stopped_at = datetime.now()
    db.commit()
    return len(workers)


def latest_jobs(db: Session, limit: int = 100) -> list[AgentJob]:
    return list(db.scalars(select(AgentJob).order_by(desc(AgentJob.created_at)).limit(limit)))


def latest_workers(db: Session, limit: int = 50) -> list[AgentWorker]:
    return list(db.scalars(select(AgentWorker).order_by(desc(AgentWorker.heartbeat_at)).limit(limit)))


def retry_failed_jobs(db: Session) -> int:
    jobs = list(db.scalars(select(AgentJob).where(AgentJob.status.in_(["failed", "retry"]))))
    now = datetime.now()
    for job in jobs:
        job.status = "retry"
        job.next_run_at = now
        job.finished_at = None
        job.locked_by = ""
        job.error = ""
        job.updated_at = now
    db.commit()
    return len(jobs)


def clean_old_done_jobs(db: Session, keep: int = 200) -> int:
    old_done = list(
        db.scalars(
            select(AgentJob)
            .where(AgentJob.status == "done")
            .order_by(desc(AgentJob.finished_at), desc(AgentJob.id))
            .offset(max(0, keep))
        )
    )
    for job in old_done:
        db.delete(job)
    db.commit()
    return len(old_done)


def job_result_summary(job: AgentJob) -> str:
    data = json_loads(job.result_json, {})
    if not data:
        return ""
    if job.kind == "domestic_pipeline":
        collect = data.get("collect", {})
        contacts = data.get("contact_snapshot", {})
        enriched = data.get("contact_enrichment", {})
        compliance = data.get("compliance_audit", {})
        cadence = data.get("cadence_snapshot", {})
        feedback = data.get("feedback_snapshot", {})
        learning = data.get("feedback_learning", {})
        return (
            f"采集 {collect.get('inserted', 0)} 条，"
            f"补联 {enriched.get('enriched', 0)}，"
            f"合规复核 {compliance.get('review', 0)}，"
            f"待补联系 {contacts.get('missing_contacts', 0)}，"
            f"今日任务 {cadence.get('tasks', 0)}，"
            f"成交 {feedback.get('won', 0)}，"
            f"调权来源 {learning.get('sources_adjusted', 0)}"
        )
    if job.kind in {"b2b_website_scan", "b2b_github_enrich", "b2b_contact_waterfall"}:
        return (
            f"扫描 {data.get('scanned', 0)}，"
            f"新增信号 {data.get('created_signals', 0)}，"
            f"新增联系方式 {data.get('created_contacts', 0)}，"
            f"失败 {data.get('failed', 0)}"
        )
    if job.kind == "b2b_waterfall":
        website = data.get("website", {})
        github = data.get("github", {})
        contacts = data.get("contacts", {})
        return (
            f"公司 {data.get('companies_scanned', 0)}，"
            f"官网信号 {website.get('created_signals', 0)}，"
            f"GitHub信号 {github.get('created_signals', 0)}，"
            f"联系方式 {contacts.get('created_contacts', 0)}"
        )
    if job.kind == "p3_quality_audit":
        return (
            f"线索高质量 {data.get('high_quality_mentions', 0)}/{data.get('reviewed_mentions', 0)}，"
            f"客户高质量 {data.get('high_quality_prospects', 0)}/{data.get('reviewed_prospects', 0)}，"
            f"公司高质量 {data.get('high_quality_companies', 0)}/{data.get('reviewed_companies', 0)}"
        )
    if job.kind == "session_domestic":
        p4 = data.get("p4", {}) if isinstance(data.get("p4"), dict) else {}
        return (
            f"平台 {data.get('platforms', 0)}，读取 {data.get('fetched', 0)}，入库 {data.get('inserted', 0)}，"
            f"候选 {p4.get('candidates', 0)}，P3过滤 {p4.get('rejected', 0)}，高质 {p4.get('high_quality', 0)}"
        )
    if isinstance(data, dict):
        parts = []
        for key, value in list(data.items())[:4]:
            if isinstance(value, (str, int, float, bool)):
                parts.append(f"{key}: {value}")
        return "；".join(parts)
    return str(data)[:300]
