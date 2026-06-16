from __future__ import annotations

import csv
import html
import re
from io import StringIO
from datetime import datetime, timedelta
from urllib.parse import quote

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import desc, select
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import create_db, get_db
from app.models import AgentJob, CandidateItem, CompanyProfile, Keyword, Mention, Prospect, Source
from app.services.ingest import purge_noise_mentions, run_domestic_acquisition_sync, run_ingestion_sync
from app.services.analytics import build_customer_type_attribution, build_keyword_attribution, build_source_attribution
from app.services.agent_queue import (
    JOB_LABELS,
    clean_old_done_jobs,
    enqueue_b2b_job,
    enqueue_job,
    enqueue_maintenance_pack,
    enqueue_practical_domestic_cycle,
    ensure_worker_pool,
    job_result_summary,
    latest_jobs,
    latest_workers,
    queue_stats,
    request_stop_workers,
    retry_failed_jobs,
    start_worker_processes,
)
from app.services.acquisition_ops import build_acquisition_ops_board
from app.services.acquisition_hub import run_unified_public_collection
from app.services.b2b_accounts import (
    build_b2b_stats,
    load_b2b_account_detail,
    load_b2b_accounts,
    search_b2b_accounts,
)
from app.services.cadence import TASK_LABELS, apply_cadence_action, load_cadence_tasks
from app.services.candidates import build_candidate_board
from app.services.contact_enrichment import enrich_missing_contacts_from_public_pages
from app.services.contact_status import contact_confidence, has_real_contact as prospect_has_real_contact
from app.services.contact_workbench import apply_contact_action, count_contact_records, load_contact_workbench_rows
from app.services.demand_radar import build_demand_stats, demand_action_labels, load_demand_signals
from app.services.feedback import (
    EVENT_LABELS,
    STATUS_OUTCOMES,
    build_feedback_board,
    load_prospect_events,
    record_prospect_event,
)
from app.services.feedback_ops import (
    OUTCOME_LABELS,
    REASON_LABELS,
    apply_structured_feedback,
    build_feedback_ops_board,
)
from app.services.growth import apply_keyword_suggestions, apply_source_suggestions, run_growth_cycle
from app.services.high_yield_sources import apply_high_yield_source_expansion
from app.services.company_profiles import rebuild_companies, rescore_dual_mode
from app.services.domestic_review import apply_domestic_review_action, load_domestic_review_rows
from app.services.home_ops import build_home_ops_board
from app.services.imports import import_prospects_csv, sample_csv
from app.services.lead_evidence import build_lead_evidence_report
from app.services.lead_finder import DEFAULT_SOURCE_SCOPE, build_lead_finder_board, run_lead_finder_search
from app.services.lead_quality_audit import build_lead_quality_audit
from app.services.learning import build_learning_report, run_feedback_learning
from app.services.notify import notify_wework
from app.services.outreach import fallback_outreach_message
from app.services.performance import build_platform_performance
from app.services.p5_workbench import (
    P5_ACTION_LABELS,
    P5_SUBTITLE,
    P5_TITLE,
    apply_p5_action,
    build_p5_workbench,
    p5_prospect_display_name,
    p5_csv_rows,
)
from app.services.today_ops import build_today_board
from app.services.platforms import build_platform_statuses
from app.services.prospects import CUSTOMER_TYPE_LABELS, rebuild_prospects
from app.services.production_report import build_production_report
from app.services.research import build_research_brief, load_research_briefs
from app.services.reports import build_daily_report, send_daily_report_wework
from app.services.session_collector import (
    PLATFORM_LABELS,
    SessionTask,
    build_session_platform_diagnostics,
    cached_login_status,
    check_login_status,
    load_progress,
    load_tasks,
    open_login_session,
    recent_session_events,
    run_enabled_session_collections,
    run_session_collection,
    run_session_smoke_test,
    session_progress_detail,
    sync_default_tasks,
    upsert_task,
    write_progress,
)
from app.services import domestic_search_strategy
from app.services.source_quality import audit_all_sources
from app.services.signals import HIGH_VALUE_SIGNALS, SIGNAL_LABELS
from app.services.strategy import build_keyword_suggestions, build_source_suggestions, build_strategy_board
from app.settings import get_settings

templates = Jinja2Templates(directory="app/templates")
app = FastAPI(title=get_settings().app_name)
scheduler = BackgroundScheduler()


def format_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")


def age_days(value: datetime | None) -> int | None:
    if not value:
        return None
    now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
    return max(0, (now - value).days)


def freshness_label(value: datetime | None) -> str:
    days = age_days(value)
    if days is None:
        return "未知时间"
    if days == 0:
        return "今天"
    if days <= 7:
        return f"{days}天内"
    if days <= 30:
        return f"{days}天前"
    if days <= 180:
        return f"{days // 30}个月前"
    if days <= 365:
        return "半年以上"
    return f"{days // 365}年前"


def freshness_class(value: datetime | None) -> str:
    days = age_days(value)
    if days is None:
        return "warn"
    if days <= 30:
        return "good"
    if days <= 180:
        return ""
    return "warn"


def mention_time(mention: Mention) -> dict[str, object]:
    source_time = mention.published_at or mention.discovered_at
    return {
        "time": source_time,
        "label": freshness_label(source_time),
        "class": freshness_class(source_time),
        "published": format_dt(mention.published_at),
        "discovered": format_dt(mention.discovered_at),
        "basis": "原文时间" if mention.published_at else "发现时间",
    }


def prospect_time(prospect: Prospect) -> dict[str, object]:
    source_time = prospect.last_seen_at or prospect.first_seen_at or prospect.created_at
    return {
        "time": source_time,
        "label": freshness_label(source_time),
        "class": freshness_class(source_time),
        "last_seen": format_dt(prospect.last_seen_at),
        "first_seen": format_dt(prospect.first_seen_at),
        "basis": "最近出现" if prospect.last_seen_at else "首次发现",
    }


def company_time(company: CompanyProfile) -> dict[str, object]:
    source_time = company.last_signal_at or company.first_seen_at or company.created_at
    return {
        "time": source_time,
        "label": freshness_label(source_time),
        "class": freshness_class(source_time),
        "last_signal": format_dt(company.last_signal_at),
        "first_seen": format_dt(company.first_seen_at),
        "basis": "最近信号" if company.last_signal_at else "首次发现",
    }


URL_RE = re.compile(r"(?P<url>https?://[^\s<>'\"，。；、]+)")
EMAIL_RE = re.compile(r"(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def linkify(value: object) -> Markup:
    text = "" if value is None else str(value)
    if not text:
        return Markup("")
    escaped = html.escape(text)

    def replace_url(match: re.Match[str]) -> str:
        url = match.group("url")
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}" target="_blank" rel="noreferrer">{safe_url}</a>'

    linked = URL_RE.sub(replace_url, escaped)

    def replace_email(match: re.Match[str]) -> str:
        email = match.group("email")
        safe_email = html.escape(email, quote=True)
        return f'<a href="mailto:{safe_email}">{safe_email}</a>'

    linked = EMAIL_RE.sub(replace_email, linked)
    return Markup(linked)


templates.env.globals.update(
    format_dt=format_dt,
    freshness_label=freshness_label,
    freshness_class=freshness_class,
    mention_time=mention_time,
    prospect_time=prospect_time,
    company_time=company_time,
    linkify=linkify,
)

STATUS_LABELS = {
    "new": "新线索",
    "review": "待复核",
    "candidate_review": "待判断候选",
    "reviewed": "已查看",
    "contacted": "已联系",
    "wechat_added": "已加微信",
    "trial_sent": "已发测试",
    "won": "已成交",
    "invalid": "无效",
}

PROSPECT_STATUS_LABELS = {
    "new": "新客户",
    "qualified": "已筛选",
    "contacted": "已触达",
    "wechat_added": "已加微信",
    "trial_sent": "已发测试",
    "follow_up": "待复访",
    "won": "已成交",
    "invalid": "无效",
}

SOURCE_QUALITY_LABELS = {
    "unchecked": "未评估",
    "excellent": "优质",
    "good": "正常",
    "low_yield": "低产",
    "blocked": "受阻",
    "unstable": "不稳",
}

SOURCE_QUALITY_CLASSES = {
    "excellent": "good",
    "good": "good",
    "low_yield": "warn",
    "blocked": "warn",
    "unstable": "warn",
}

PRODUCT_FIT_LABELS = {
    "direct_dynamic_residential": "动态住宅直匹配",
    "scenario_fit": "场景匹配",
    "weak_fit": "弱匹配",
    "mismatch_static": "静态/非目标",
    "unknown": "未知",
}

JOB_LABELS_FOR_TEMPLATE = JOB_LABELS

AGENT_JOB_STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "retry": "等待重试",
    "done": "已完成",
    "failed": "失败",
}

AGENT_WORKER_STATUS_LABELS = {
    "starting": "启动中",
    "idle": "空闲",
    "running": "运行中",
    "stopped": "已停止",
}


@app.on_event("startup")
def startup() -> None:
    create_db()
    settings = get_settings()
    if settings.agent_auto_start_workers:
        from app.database import SessionLocal

        with SessionLocal() as db:
            ensure_worker_pool(
                db,
                desired_count=settings.agent_auto_start_workers,
                poll_seconds=settings.agent_worker_poll_seconds,
            )
    if not scheduler.running:
        scheduler.add_job(
            scheduled_ingestion,
            "interval",
            minutes=settings.collector_interval_minutes,
            id="lead-ingestion",
            replace_existing=True,
        )
        scheduler.add_job(
            scheduled_agent_maintenance,
            "interval",
            minutes=5,
            id="agent-maintenance",
            replace_existing=True,
        )
        scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown()


def scheduled_ingestion() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        enqueue_practical_domestic_cycle(db, source_limit=30)
    finally:
        db.close()


def scheduled_agent_maintenance() -> None:
    from app.database import SessionLocal

    settings = get_settings()
    db = SessionLocal()
    try:
        ensure_worker_pool(
            db,
            desired_count=settings.agent_auto_start_workers,
            poll_seconds=settings.agent_worker_poll_seconds,
        )
    finally:
        db.close()


def render_leads_dashboard(
    request: Request,
    db: Session,
    segment: str = "all",
    scope: str = DEFAULT_SOURCE_SCOPE,
    pool: str = "usable",
    min_score: int = 0,
    message: str = "",
):
    board = build_lead_finder_board(
        db,
        segment=segment,
        scope=scope,
        pool=pool,
        min_score=min_score,
        message=message,
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "board": board,
            "threshold": get_settings().high_intent_threshold,
            "status_labels": STATUS_LABELS,
            "signal_labels": SIGNAL_LABELS,
        },
    )


@app.get("/", response_class=HTMLResponse)
def home_workbench(
    request: Request,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    board = build_home_ops_board(db)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "board": board,
            "message": message,
            "collector": session_progress_detail(),
        },
    )


@app.get("/toolbox", response_class=HTMLResponse)
def toolbox_page(request: Request):
    return templates.TemplateResponse(request, "toolbox.html", {})


@app.get("/leads", response_class=HTMLResponse)
def leads_dashboard(
    request: Request,
    segment: str = Query(default="all"),
    scope: str = Query(default=DEFAULT_SOURCE_SCOPE),
    pool: str = Query(default="usable"),
    min_score: int = Query(default=0),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    return render_leads_dashboard(
        request,
        db,
        segment=segment,
        scope=scope,
        pool=pool,
        min_score=max(0, min(100, min_score)),
        message=message,
    )


@app.get("/candidates", response_class=HTMLResponse)
def candidates_page(
    request: Request,
    status: str = Query(default="all"),
    limit: int = Query(default=80),
    db: Session = Depends(get_db),
):
    board = build_candidate_board(db, status=status, limit=limit)
    return templates.TemplateResponse(
        request,
        "candidates.html",
        {
            "board": board,
            "status": status,
        },
    )


@app.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(candidate_id: int, request: Request, db: Session = Depends(get_db)):
    candidate = db.get(CandidateItem, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        {
            "candidate": candidate,
            "status_labels": STATUS_LABELS,
            "signal_labels": SIGNAL_LABELS,
        },
    )


@app.get("/quality-audit", response_class=HTMLResponse)
def quality_audit_page(
    request: Request,
    limit: int = Query(default=40),
    db: Session = Depends(get_db),
):
    board = build_lead_quality_audit(db, limit=max(10, min(100, limit)))
    return templates.TemplateResponse(
        request,
        "quality_audit.html",
        {
            "board": board,
            "limit": limit,
        },
    )


@app.get("/production-report", response_class=HTMLResponse)
def production_report_page(
    request: Request,
    sample_limit: int = Query(default=50),
    db: Session = Depends(get_db),
):
    report = build_production_report(db, sample_limit=max(10, min(100, sample_limit)))
    return templates.TemplateResponse(
        request,
        "production_report.html",
        {
            "report": report,
        },
    )


@app.get("/production-report.csv")
def production_report_csv(
    sample_limit: int = Query(default=100),
    db: Session = Depends(get_db),
):
    report = build_production_report(db, sample_limit=max(10, min(300, sample_limit)))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["score", "title", "source", "platform", "status", "published_at", "next_step", "why", "url"])
    for row in report.top_leads:
        writer.writerow(
            [
                row.score,
                row.title,
                row.source,
                row.platform,
                row.status,
                format_dt(row.published_at),
                row.next_step,
                row.why,
                row.url,
            ]
        )
    filename = f"lead-radar-production-leads-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/production-collect")
def production_collect(
    background_tasks: BackgroundTasks,
    source_limit: int = Form(default=200),
):
    limit = max(20, min(500, source_limit))
    write_progress("queued", message=f"生产采集已排队：本轮最多跑 {limit} 个高优先来源。")
    background_tasks.add_task(run_production_collect_background, limit)
    message = quote(f"生产采集已启动：本轮最多跑 {limit} 个高优先来源，稍后刷新生产验收报告。")
    return RedirectResponse(f"/production-report?message={message}", status_code=303)


def run_production_collect_background(source_limit: int = 200) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        write_progress("running", message=f"正在生产采集：扩展高产来源并跑 {source_limit} 个来源。")
        apply_high_yield_source_expansion(db, limit=180)
        result = run_unified_public_collection(
            db,
            source_limit=source_limit,
            force_run=True,
            detail_fetch_limit_per_source=4,
        )
        cleanup = purge_noise_mentions(db)
        write_progress(
            "done",
            fetched=int(result.get("fetched", 0) or 0),
            inserted=int(result.get("inserted", 0) or 0),
            rejected=int(cleanup.get("deleted", 0) or 0),
            high_quality=int(result.get("high_intent", 0) or 0),
            message=(
                f"生产采集完成：读取 {result.get('fetched', 0)} 条候选，"
                f"入库 {result.get('inserted', 0)} 条，高意向 {result.get('high_intent', 0)} 条。"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        write_progress("failed", message=f"生产采集失败：{exc}", failure_code="production_collect_failed")
    finally:
        db.close()


@app.post("/leads/search")
def run_lead_finder(
    segment: str = Form(default="all"),
    scope: str = Form(default=DEFAULT_SOURCE_SCOPE),
    pool: str = Form(default="usable"),
    min_score: int = Form(default=0),
    source_limit: int = Form(default=0),
    db: Session = Depends(get_db),
):
    normalized_source_limit = None if source_limit <= 0 else max(1, source_limit)
    result = run_lead_finder_search(
        db,
        segment=segment,
        scope=scope,
        source_limit=normalized_source_limit,
    )
    fetched = int(result.get("fetched") or 0)
    inserted = int(result.get("inserted") or 0)
    high_intent = int(result.get("high_intent") or 0)
    main_inserted = int(result.get("main_inserted") or 0)
    review_inserted = int(result.get("review_inserted") or 0)
    invalid_inserted = int(result.get("invalid_inserted") or 0)
    if "results" in result:
        message = f"已登录平台采集完成：{result.get('results')}"
    else:
        message = (
            f"已完成：读取 {fetched} 条候选，入库 {inserted} 条；"
            f"主池 {main_inserted} 条，待复核 {review_inserted} 条，垃圾池 {invalid_inserted} 条，高意向 {high_intent} 条。"
        )
    return RedirectResponse(
        f"/leads?segment={quote(segment)}&scope={quote(scope)}&pool={quote(pool)}&min_score={max(0, min(100, min_score))}&message={quote(message)}",
        status_code=303,
    )


@app.post("/run-once")
def run_once(db: Session = Depends(get_db)):
    result = run_ingestion_sync(db)
    cleanup = purge_noise_mentions(db)
    message = quote(
        f"采集完成：读取 {result.get('fetched', 0)} 条，新增 {result.get('inserted', 0)} 条，清理低质/广告 {cleanup.get('deleted', 0)} 条。"
    )
    return RedirectResponse(
        f"/leads?segment=all&scope={DEFAULT_SOURCE_SCOPE}&pool=usable&min_score=0&message={message}",
        status_code=303,
    )


@app.post("/auto-collect")
def auto_collect(
    background_tasks: BackgroundTasks,
    source_limit: int = Form(default=0),
    session_platform_limit: int = Form(default=3),
):
    session_limit = max(0, min(6, session_platform_limit))
    normalized_source_limit = None if source_limit <= 0 else source_limit
    write_progress("queued", message="全量采集已开始，默认跑全部启用来源。")
    background_tasks.add_task(run_full_auto_collect_background, normalized_source_limit, session_limit)
    message = quote("全量采集已在后台开始。你可以先看线索池，顶部会显示采集状态。")
    return RedirectResponse(
        f"/candidates?status=all&message={message}",
        status_code=303,
    )


def run_full_auto_collect_background(source_limit: int | None = None, session_limit: int = 0) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        write_progress("running", message="正在全量采集公开来源。")
        result = run_unified_public_collection(
            db,
            source_limit=source_limit,
            force_run=True,
            detail_fetch_limit_per_source=8,
        )
        cleanup = purge_noise_mentions(db)
        write_progress(
            "done",
            fetched=int(result.get("fetched", 0) or 0),
            inserted=int(result.get("inserted", 0) or 0),
            rejected=int(cleanup.get("deleted", 0) or 0),
            high_quality=int(result.get("high_intent", 0) or 0),
            message=(
                f"全量采集完成：读取 {result.get('fetched', 0)} 条，入库 {result.get('inserted', 0)} 条，"
                f"高意向 {result.get('high_intent', 0)} 条。"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        write_progress("failed", message=f"全量采集失败：{exc}", failure_code="public_collect_failed")
    finally:
        db.close()
    if session_limit:
        run_session_batch_background(session_limit)


@app.post("/sources/expand-high-yield")
def expand_high_yield_sources(
    limit: int = Form(default=120),
):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = apply_high_yield_source_expansion(db, limit=max(1, min(240, limit)))
    finally:
        db.close()
    message = quote(
        f"高产来源扩展完成：新增 {result.created} 个，更新 {result.updated} 个，已存在 {result.skipped} 个。"
    )
    return RedirectResponse(f"/sources?message={message}", status_code=303)


@app.post("/run-domestic")
def run_domestic(
    source_limit: int = Form(default=30),
    db: Session = Depends(get_db),
):
    run_domestic_acquisition_sync(db, source_limit=max(1, min(100, source_limit)))
    return RedirectResponse("/strategy?message=%E5%9B%BD%E5%86%85%E8%8E%B7%E5%AE%A2%E6%BA%90%E9%87%87%E9%9B%86%E5%AE%8C%E6%88%90", status_code=303)


@app.get("/agents", response_class=HTMLResponse)
def agents_page(
    request: Request,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    jobs = latest_jobs(db, limit=80)
    workers = latest_workers(db, limit=30)
    return templates.TemplateResponse(
        request,
        "agents.html",
        {
            "stats": queue_stats(db),
            "jobs": jobs,
            "workers": workers,
            "message": message,
            "job_labels": JOB_LABELS_FOR_TEMPLATE,
            "job_status_labels": AGENT_JOB_STATUS_LABELS,
            "worker_status_labels": AGENT_WORKER_STATUS_LABELS,
            "job_result_summary": job_result_summary,
        },
    )


@app.post("/agents/start")
def agents_start(
    workers: int = Form(default=3),
    poll_seconds: int = Form(default=5),
):
    started = start_worker_processes(count=workers, poll_seconds=poll_seconds)
    return RedirectResponse(
        f"/agents?message=started-{len(started)}-workers",
        status_code=303,
    )


@app.post("/agents/stop")
def agents_stop(db: Session = Depends(get_db)):
    count = request_stop_workers(db)
    return RedirectResponse(f"/agents?message=stop-requested-{count}", status_code=303)


@app.post("/agents/enqueue/domestic")
def agents_enqueue_domestic(
    source_limit: int = Form(default=30),
    db: Session = Depends(get_db),
):
    job = enqueue_practical_domestic_cycle(db, source_limit=source_limit)
    return RedirectResponse(f"/agents?message=queued-job-{job.id}", status_code=303)


@app.post("/agents/enqueue/maintenance")
def agents_enqueue_maintenance(db: Session = Depends(get_db)):
    jobs = enqueue_maintenance_pack(db)
    return RedirectResponse(f"/agents?message=queued-maintenance-{len(jobs)}", status_code=303)


@app.post("/agents/enqueue/job")
def agents_enqueue_job(
    kind: str = Form(default="research_snapshot"),
    source_limit: int = Form(default=30),
    db: Session = Depends(get_db),
):
    allowed = {
        "collect_domestic",
        "refresh_scores",
        "purge_noise",
        "rebuild_prospects",
        "audit_sources",
        "research_snapshot",
        "cadence_snapshot",
        "contact_snapshot",
        "performance_snapshot",
        "feedback_snapshot",
        "feedback_learning",
        "contact_enrichment",
        "prospect_hygiene",
        "dedupe_audit",
        "compliance_audit",
        "p3_quality_audit",
        "session_domestic",
        "b2b_website_scan",
        "b2b_github_enrich",
        "b2b_contact_waterfall",
        "b2b_waterfall",
    }
    if kind not in allowed:
        return RedirectResponse("/agents?message=invalid-job-kind", status_code=303)
    payload = {"source_limit": source_limit} if kind == "collect_domestic" else {}
    if kind == "session_domestic":
        payload = {"platform_limit": 2, "keyword_limit": 1, "per_platform_limit": 5, "headless": True}
    if kind.startswith("b2b_"):
        payload = {"limit": max(1, min(80, source_limit))}
    if kind == "p3_quality_audit":
        payload = {"limit": 500}
    job = enqueue_job(db, kind, payload=payload, priority=70)
    return RedirectResponse(f"/agents?message=queued-job-{job.id}", status_code=303)


@app.post("/agents/retry-failed")
def agents_retry_failed(db: Session = Depends(get_db)):
    count = retry_failed_jobs(db)
    return RedirectResponse(f"/agents?message=retry-{count}", status_code=303)


@app.post("/agents/clean-done")
def agents_clean_done(db: Session = Depends(get_db)):
    count = clean_old_done_jobs(db, keep=200)
    return RedirectResponse(f"/agents?message=cleaned-{count}", status_code=303)


@app.get("/agents.csv")
def agents_csv(db: Session = Depends(get_db)):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "kind",
            "label",
            "status",
            "priority",
            "attempts",
            "locked_by",
            "created_at",
            "started_at",
            "finished_at",
            "summary",
            "error",
        ]
    )
    for job in latest_jobs(db, limit=500):
        writer.writerow(
            [
                job.id,
                job.kind,
                job.label,
                job.status,
                job.priority,
                f"{job.attempts}/{job.max_attempts}",
                job.locked_by,
                job.created_at,
                job.started_at,
                job.finished_at,
                job_result_summary(job),
                job.error,
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agent_jobs.csv"},
    )


@app.get("/agents/status.json")
def agents_status_json(db: Session = Depends(get_db)):
    stats = queue_stats(db)
    jobs = latest_jobs(db, limit=30)
    workers = latest_workers(db, limit=20)
    return JSONResponse(
        {
            "stats": stats.__dict__,
            "jobs": [
                {
                    "id": job.id,
                    "kind": job.kind,
                    "label": job.label,
                    "status": job.status,
                    "priority": job.priority,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "locked_by": job.locked_by,
                    "created_at": str(job.created_at),
                    "started_at": str(job.started_at) if job.started_at else "",
                    "finished_at": str(job.finished_at) if job.finished_at else "",
                    "summary": job_result_summary(job),
                    "error": job.error,
                }
                for job in jobs
            ],
            "workers": [
                {
                    "worker_id": worker.worker_id,
                    "pid": worker.pid,
                    "status": worker.status,
                    "current_job_id": worker.current_job_id,
                    "jobs_done": worker.jobs_done,
                    "jobs_failed": worker.jobs_failed,
                    "heartbeat_at": str(worker.heartbeat_at) if worker.heartbeat_at else "",
                    "message": worker.message,
                }
                for worker in workers
            ],
        }
    )


@app.post("/audit-sources")
def audit_sources(db: Session = Depends(get_db)):
    counters = audit_all_sources(db, auto_disable=False)
    message = f"来源审计完成：检查 {counters.get('audited', 0)} 个来源，只更新质量评分，不自动停用。"
    return RedirectResponse(f"/sources?message={quote(message)}", status_code=303)


@app.post("/sources/enable-all")
def enable_all_sources(db: Session = Depends(get_db)):
    rows = list(db.query(Source).all())
    changed = 0
    for source in rows:
        if not source.enabled:
            changed += 1
        source.enabled = True
        source.auto_disabled_at = None
        source.consecutive_failures = 0
        source.cooldown_until = None
        source.crawl_backoff_level = 0
    db.commit()
    message = f"已启用全部来源：共 {len(rows)} 个，恢复 {changed} 个停用来源。"
    return RedirectResponse(f"/sources?message={quote(message)}", status_code=303)


@app.post("/rebuild-prospects")
def rebuild_prospect_view(db: Session = Depends(get_db)):
    rebuild_prospects(db)
    return RedirectResponse("/prospects", status_code=303)


@app.get("/pipeline", response_class=HTMLResponse)
def pipeline(
    request: Request,
    status: str = Query(default="active"),
    product_fit: str = Query(default="sales_fit"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    rows = load_pipeline_rows(db, status=status, product_fit=product_fit, min_score=min_score)
    today = datetime.now().date()
    stats = {
        "total": len(rows),
        "due": sum(1 for row in rows if row.next_follow_up_at and row.next_follow_up_at.date() <= today),
        "new": sum(1 for row in rows if row.status == "new"),
        "trial_sent": sum(1 for row in rows if row.status == "trial_sent"),
    }
    return templates.TemplateResponse(
        request,
        "pipeline.html",
        {
            "prospects": rows,
            "stats": stats,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
            "filters": {
                "status": status,
                "product_fit": product_fit,
                "min_score": min_score,
            },
        },
    )


@app.get("/pipeline.csv")
def pipeline_csv(
    status: str = Query(default="active"),
    product_fit: str = Query(default="sales_fit"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    rows = load_pipeline_rows(db, status=status, product_fit=product_fit, min_score=min_score, limit=1000)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "display_name",
            "platform",
            "lead_score",
            "contact_confidence",
            "contact_records",
            "product_fit",
            "customer_type",
            "status",
            "profile_url",
            "company_name",
            "region",
            "website",
            "email",
            "wechat",
            "telegram",
            "next_action",
            "suggested_action",
            "pitch_message",
            "first_touch_message",
            "follow_up_message",
            "trial_message",
            "closing_message",
            "next_follow_up_at",
            "keywords",
            "evidence",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.display_name,
                row.platform,
                row.lead_score,
                contact_confidence(row),
                count_contact_records(row),
                PRODUCT_FIT_LABELS.get(row.product_fit, row.product_fit),
                CUSTOMER_TYPE_LABELS.get(row.customer_type, row.customer_type),
                PROSPECT_STATUS_LABELS.get(row.status, row.status),
                row.profile_url,
                row.company_name,
                row.region,
                row.website,
                row.email,
                row.wechat,
                row.telegram,
                row.next_action,
                row.suggested_action,
                row.pitch_message,
                row.first_touch_message,
                row.follow_up_message,
                row.trial_message,
                row.closing_message,
                row.next_follow_up_at.strftime("%Y-%m-%d %H:%M") if row.next_follow_up_at else "",
                row.keywords,
                row.evidence,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-pipeline-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def load_pipeline_rows(
    db: Session,
    status: str = "active",
    product_fit: str = "sales_fit",
    min_score: int = 60,
    limit: int = 200,
) -> list[Prospect]:
    query = select(Prospect).where(Prospect.lead_score >= min_score)
    if product_fit == "sales_fit":
        query = query.where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
    elif product_fit in PRODUCT_FIT_LABELS:
        query = query.where(Prospect.product_fit == product_fit)

    if status == "active":
        query = query.where(Prospect.status.notin_(["won", "invalid"]))
    elif status in PROSPECT_STATUS_LABELS:
        query = query.where(Prospect.status == status)

    query = query.order_by(
        Prospect.next_follow_up_at.is_(None),
        Prospect.next_follow_up_at,
        desc(Prospect.lead_score),
        desc(Prospect.last_seen_at),
    ).limit(limit)
    return list(db.scalars(query))


@app.get("/tasks", response_class=HTMLResponse)
def tasks_board(request: Request, db: Session = Depends(get_db)):
    groups = load_task_groups(db)
    return templates.TemplateResponse(
        request,
        "tasks.html",
        {
            "groups": groups,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/today", response_class=HTMLResponse)
def today_page(
    request: Request,
    mode: str = Query(default="today"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=50),
    daily_limit: int = Query(default=5),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    board = build_today_board(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        daily_limit=max(1, min(8, daily_limit)),
    )
    platforms = sorted({task.prospect.platform for task in board.workbench.tasks if task.prospect.platform})
    return templates.TemplateResponse(
        request,
        "today_ops.html",
        {
            "board": board,
            "filters": {"mode": mode, "platform": platform, "min_score": min_score, "daily_limit": daily_limit},
            "platforms": platforms,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
            "message": message,
        },
    )


@app.post("/today/action")
def today_action(
    prospect_id: int = Form(...),
    action: str = Form(default=""),
    note: str = Form(default=""),
    mode: str = Form(default="today"),
    platform: str = Form(default="domestic"),
    min_score: int = Form(default=50),
    daily_limit: int = Form(default=5),
    db: Session = Depends(get_db),
):
    ok = apply_p5_action(db, prospect_id, action, note)
    message = quote("今日任务已记录，系统学习已更新。" if ok else "今日任务动作无效。")
    return RedirectResponse(
        f"/today?mode={quote(mode)}&platform={quote(platform)}&min_score={min_score}&daily_limit={daily_limit}&message={message}",
        status_code=303,
    )


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request, db: Session = Depends(get_db)):
    rows = build_platform_performance(db)
    stats = {
        "platforms": len(rows),
        "focus": sum(1 for row in rows if row.score >= 75),
        "contactable": sum(row.contactable_prospects for row in rows),
        "high_value": sum(row.high_value_mentions for row in rows),
    }
    return templates.TemplateResponse(
        request,
        "performance.html",
        {
            "rows": rows,
            "stats": stats,
        },
    )


@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(
    request: Request,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    board = build_feedback_board(db)
    ops = build_feedback_ops_board(db)
    learning = build_learning_report(db, apply=False)
    return templates.TemplateResponse(
        request,
        "feedback.html",
        {
            "board": board,
            "ops": ops,
            "learning": learning,
            "message": message,
            "event_labels": EVENT_LABELS,
            "status_outcomes": STATUS_OUTCOMES,
            "outcome_labels": OUTCOME_LABELS,
            "reason_labels": REASON_LABELS,
        },
    )


@app.post("/feedback/learn")
def feedback_learn(db: Session = Depends(get_db)):
    result = run_feedback_learning(db, apply=True)
    message = (
        "学习完成："
        f"客户微调 {result['prospects_adjusted']}，"
        f"来源调权 {result['sources_adjusted']}，"
        f"关键词调权 {result['keywords_adjusted']}，"
        f"暂停关键词 {result['keywords_paused']}。"
    )
    return RedirectResponse(f"/feedback?message={quote(message)}", status_code=303)


@app.post("/feedback/record")
def feedback_record(
    prospect_id: int = Form(...),
    outcome: str = Form(default=""),
    reason: str = Form(default=""),
    note: str = Form(default=""),
    follow_up_days: int = Form(default=0),
    db: Session = Depends(get_db),
):
    ok = apply_structured_feedback(
        db,
        prospect_id=prospect_id,
        outcome=outcome,
        reason=reason,
        note=note,
        follow_up_days=follow_up_days,
    )
    message = "反馈已记录，系统学习已更新。" if ok else "反馈无效：请确认线索和结果类型。"
    return RedirectResponse(f"/feedback?message={quote(message)}", status_code=303)


@app.get("/feedback.csv")
def feedback_csv(db: Session = Depends(get_db)):
    board = build_feedback_board(db)
    ops = build_feedback_ops_board(db)
    learning = build_learning_report(db, apply=False)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "section",
            "name",
            "score",
            "prospects",
            "contacted",
            "trial_sent",
            "won",
            "invalid",
            "contact_rate",
            "trial_rate",
            "win_rate",
            "invalid_rate",
            "events",
        ]
    )
    for section, rows in (("platform", board.platform_rows), ("customer_type", board.customer_type_rows)):
        for row in rows:
            writer.writerow(
                [
                    section,
                    row.name,
                    row.score,
                    row.prospects,
                    row.contacted,
                    row.trial_sent,
                    row.won,
                    row.invalid,
                    f"{row.contact_rate:.2%}",
                    f"{row.trial_rate:.2%}",
                    f"{row.win_rate:.2%}",
                    f"{row.invalid_rate:.2%}",
                    row.events,
                ]
            )
    writer.writerow([])
    writer.writerow(["section", "name", "priority_or_weight", "delta", "status", "quality_score", "feedback_score", "reason"])
    for row in learning.source_rows:
        writer.writerow(
            [
                "source_learning",
                row.source_name,
                row.learned_priority,
                "",
                row.status,
                row.quality_score,
                row.feedback_score,
                row.reason,
            ]
        )
    for row in learning.keyword_rows:
        writer.writerow(
            [
                "keyword_learning",
                row.keyword,
                row.new_weight,
                row.delta,
                row.status,
                "",
                "",
                row.reason,
            ]
        )
    writer.writerow([])
    writer.writerow(["section", "reason", "label", "count", "positive", "negative"])
    for row in ops.reason_rows:
        writer.writerow(["feedback_reason", row.reason, row.label, row.count, row.positive, row.negative])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=lead-radar-feedback.csv"},
    )


@app.post("/leads/{mention_id}/action")
def lead_list_action(
    mention_id: int,
    action: str = Form(default=""),
    segment: str = Form(default="all"),
    scope: str = Form(default="all"),
    pool: str = Form(default="usable"),
    min_score: int = Form(default=0),
    db: Session = Depends(get_db),
):
    mention = db.get(Mention, mention_id)
    message = "线索不存在。"
    if mention is not None:
        prospect = db.get(Prospect, mention.prospect_id) if mention.prospect_id else None
        if action == "invalid":
            mention.status = "invalid"
            message = "已标记为无效线索。"
            if prospect is not None:
                prospect.status = "invalid"
                prospect.suppressed = True
                prospect.suppression_reason = "P23 线索列表标记无效"
                prospect.next_action = "无效线索，后续同类内容降低优先级。"
                record_prospect_event(db, prospect, "outcome", value="invalid", note="P23 lead list invalid", commit=False)
        elif action == "need_contact":
            mention.status = "reviewed"
            message = "已加入补联系方式队列。"
            if prospect is not None:
                prospect.status = "qualified"
                prospect.next_action = "先补微信、QQ、Telegram、邮箱或手机号，再做轻触达。"
                record_prospect_event(db, prospect, "status_change", value="qualified", note="P23 lead list need contact", commit=False)
        elif action == "qualify":
            mention.status = "reviewed"
            message = "已加入今日跟进。"
            if prospect is not None:
                prospect.status = "qualified"
                prospect.next_action = "打开原文确认平台、国家、并发量和当前代理痛点。"
                record_prospect_event(db, prospect, "status_change", value="qualified", note="P23 lead list qualified", commit=False)
        db.commit()
    return RedirectResponse(
        f"/leads?segment={quote(segment)}&scope={quote(scope)}&pool={quote(pool)}&min_score={max(0, min(100, min_score))}&message={quote(message)}",
        status_code=303,
    )


@app.post("/leads/bulk-action")
def lead_list_bulk_action(
    row_ids: list[int] = Form(default=[]),
    action: str = Form(default=""),
    segment: str = Form(default="all"),
    scope: str = Form(default="all"),
    pool: str = Form(default="usable"),
    min_score: int = Form(default=0),
    db: Session = Depends(get_db),
):
    allowed_actions = {"invalid", "need_contact", "qualify"}
    if not row_ids or action not in allowed_actions:
        message = "请选择线索和操作。"
        return RedirectResponse(
            f"/leads?segment={quote(segment)}&scope={quote(scope)}&pool={quote(pool)}&min_score={max(0, min(100, min_score))}&message={quote(message)}",
            status_code=303,
        )

    updated = 0
    for mention_id in row_ids[:200]:
        mention = db.get(Mention, mention_id)
        if mention is None:
            continue
        prospect = db.get(Prospect, mention.prospect_id) if mention.prospect_id else None
        if action == "invalid":
            mention.status = "invalid"
            if prospect is not None:
                prospect.status = "invalid"
                prospect.suppressed = True
                prospect.suppression_reason = "线索池批量标记无效"
                prospect.next_action = "无效线索，后续同类内容降低优先级。"
                record_prospect_event(db, prospect, "outcome", value="invalid", note="lead bulk invalid", commit=False)
        elif action == "need_contact":
            mention.status = "reviewed"
            if prospect is not None:
                prospect.status = "qualified"
                prospect.next_action = "先补微信、QQ、Telegram、邮箱或手机号，再做轻触达。"
                record_prospect_event(db, prospect, "status_change", value="qualified", note="lead bulk need contact", commit=False)
        elif action == "qualify":
            mention.status = "reviewed"
            if prospect is not None:
                prospect.status = "qualified"
                prospect.next_action = "打开原文确认平台、国家、并发量和当前代理痛点。"
                record_prospect_event(db, prospect, "status_change", value="qualified", note="lead bulk qualified", commit=False)
        updated += 1

    db.commit()
    labels = {"invalid": "无效", "need_contact": "补联系方式", "qualify": "加入跟进"}
    message = f"已批量处理 {updated} 条：{labels.get(action, action)}。"
    return RedirectResponse(
        f"/leads?segment={quote(segment)}&scope={quote(scope)}&pool={quote(pool)}&min_score={max(0, min(100, min_score))}&message={quote(message)}",
        status_code=303,
    )


@app.get("/p5-workbench", response_class=HTMLResponse)
def p5_workbench_page(
    request: Request,
    mode: str = Query(default="today"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=50),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    board = build_p5_workbench(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
    )
    platforms = sorted({item[0] for item in db.query(Prospect.platform).distinct().all() if item[0]})
    return templates.TemplateResponse(
        request,
        "p5_workbench.html",
        {
            "board": board,
            "filters": {"mode": mode, "platform": platform, "min_score": min_score},
            "platforms": platforms,
            "message": message,
            "action_labels": P5_ACTION_LABELS,
            "p5_prospect_display_name": p5_prospect_display_name,
            "p5_title": P5_TITLE,
            "p5_subtitle": P5_SUBTITLE,
            "p5_export_path": "/p5-workbench.csv",
            "p5_filter_action": "/p5-workbench",
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/p5-workbench.csv")
def p5_workbench_csv(
    mode: str = Query(default="today"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    board = build_p5_workbench(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=1000,
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(p5_csv_rows(board))
    output.seek(0)
    filename = f"lead-radar-p5-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/p5-workbench/action")
def p5_workbench_action(
    prospect_id: int = Form(...),
    action: str = Form(default=""),
    note: str = Form(default=""),
    mode: str = Form(default="today"),
    platform: str = Form(default="domestic"),
    min_score: int = Form(default=60),
    return_path: str = Form(default="/p5-workbench"),
    db: Session = Depends(get_db),
):
    ok = apply_p5_action(db, prospect_id, action, note)
    message = quote("P5 动作已记录，反馈学习已更新。" if ok else "P5 动作无效。")
    target = return_path if return_path in {"/", "/today", "/p5-workbench"} else "/p5-workbench"
    return RedirectResponse(
        f"{target}?mode={quote(mode)}&platform={quote(platform)}&min_score={min_score}&message={message}",
        status_code=303,
    )


@app.get("/contact-workbench", response_class=HTMLResponse)
def contact_workbench_page(
    request: Request,
    mode: str = Query(default="missing"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=50),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    rows = load_contact_workbench_rows(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
    )
    stats = {
        "total": len(rows),
        "missing": sum(1 for row in rows if not row.has_contact),
        "contactable": sum(1 for row in rows if row.has_contact),
        "hot": sum(1 for row in rows if row.priority_score >= 85),
    }
    platforms = sorted({item[0] for item in db.query(Prospect.platform).distinct().all() if item[0]})
    return templates.TemplateResponse(
        request,
        "contact_workbench.html",
        {
            "rows": rows,
            "stats": stats,
            "filters": {"mode": mode, "platform": platform, "min_score": min_score},
            "platforms": platforms,
            "message": message,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/research", response_class=HTMLResponse)
def research_page(
    request: Request,
    mode: str = Query(default="priority"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    briefs = load_research_briefs(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
    )
    stats = {
        "total": len(briefs),
        "high": sum(1 for brief in briefs if brief.deal_probability == "高"),
        "contactable": sum(1 for brief in briefs if brief.has_contact),
        "needs_review": sum(1 for brief in briefs if brief.deal_probability == "需审核"),
    }
    platforms = sorted({item[0] for item in db.query(Prospect.platform).distinct().all() if item[0]})
    return templates.TemplateResponse(
        request,
        "research.html",
        {
            "briefs": briefs,
            "stats": stats,
            "filters": {"mode": mode, "platform": platform, "min_score": min_score},
            "platforms": platforms,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
        },
    )


@app.get("/cadence", response_class=HTMLResponse)
def cadence_page(
    request: Request,
    mode: str = Query(default="today"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=60),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    tasks = load_cadence_tasks(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
    )
    stats = {
        "total": len(tasks),
        "contact_enrich": sum(1 for task in tasks if task.task_type == "contact_enrich"),
        "first_touch": sum(1 for task in tasks if task.task_type == "first_touch"),
        "trial": sum(1 for task in tasks if task.task_type in {"send_trial", "trial_follow_up"}),
    }
    platforms = sorted({item[0] for item in db.query(Prospect.platform).distinct().all() if item[0]})
    return templates.TemplateResponse(
        request,
        "cadence.html",
        {
            "tasks": tasks,
            "stats": stats,
            "filters": {"mode": mode, "platform": platform, "min_score": min_score},
            "platforms": platforms,
            "message": message,
            "task_labels": TASK_LABELS,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/cadence.csv")
def cadence_csv(
    mode: str = Query(default="today"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    tasks = load_cadence_tasks(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=1000,
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "priority",
            "task_type",
            "task",
            "due",
            "display_name",
            "platform",
            "lead_score",
            "deal_probability",
            "has_contact",
            "customer_type",
            "status",
            "playbook",
            "message",
            "checklist",
            "primary_action",
            "profile_url",
        ]
    )
    for task in tasks:
        prospect = task.prospect
        writer.writerow(
            [
                task.priority,
                task.task_type,
                task.title,
                task.due_label,
                prospect.display_name,
                prospect.platform,
                prospect.lead_score,
                task.brief.deal_probability,
                "yes" if task.has_contact else "no",
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type),
                PROSPECT_STATUS_LABELS.get(prospect.status, prospect.status),
                task.playbook,
                task.message,
                " | ".join(task.checklist),
                task.primary_action_label,
                prospect.profile_url,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-cadence-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/cadence/action")
def cadence_action(
    prospect_id: int = Form(...),
    action: str = Form(default=""),
    mode: str = Form(default="today"),
    platform: str = Form(default="domestic"),
    min_score: int = Form(default=60),
    db: Session = Depends(get_db),
):
    ok = apply_cadence_action(db, prospect_id, action)
    message = quote("任务已处理" if ok else "任务动作无效")
    return RedirectResponse(
        f"/cadence?mode={quote(mode)}&platform={quote(platform)}&min_score={min_score}&message={message}",
        status_code=303,
    )


@app.get("/research.csv")
def research_csv(
    mode: str = Query(default="priority"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=60),
    db: Session = Depends(get_db),
):
    briefs = load_research_briefs(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=1000,
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "priority_score",
            "deal_probability",
            "display_name",
            "platform",
            "lead_score",
            "has_contact",
            "product_fit",
            "customer_type",
            "summary",
            "pain_points",
            "missing_fields",
            "questions",
            "opener",
            "next_actions",
            "risks",
            "evidence",
            "profile_url",
        ]
    )
    for brief in briefs:
        prospect = brief.prospect
        writer.writerow(
            [
                brief.priority_score,
                brief.deal_probability,
                prospect.display_name,
                prospect.platform,
                prospect.lead_score,
                "yes" if brief.has_contact else "no",
                PRODUCT_FIT_LABELS.get(prospect.product_fit, prospect.product_fit),
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type),
                brief.account_summary,
                " | ".join(brief.pain_points),
                " | ".join(brief.missing_fields),
                " | ".join(brief.qualification_questions),
                brief.opener,
                " | ".join(brief.next_actions),
                " | ".join(brief.risk_notes),
                " | ".join(brief.evidence_lines),
                prospect.profile_url,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-research-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/contact-workbench.csv")
def contact_workbench_csv(
    mode: str = Query(default="missing"),
    platform: str = Query(default="domestic"),
    min_score: int = Query(default=50),
    db: Session = Depends(get_db),
):
    rows = load_contact_workbench_rows(
        db,
        mode=mode,
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=1000,
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "priority_score",
            "contact_state",
            "display_name",
            "display_label",
            "platform",
            "lead_score",
            "contact_confidence",
            "contact_records",
            "product_fit",
            "customer_type",
            "wechat",
            "telegram",
            "email",
            "website",
            "profile_url",
            "search_query",
            "search_links",
            "action_hint",
            "reason",
            "next_action",
            "evidence",
        ]
    )
    for row in rows:
        prospect = row.prospect
        writer.writerow(
            [
                row.priority_score,
                row.contact_state,
                prospect.display_name,
                row.display_label,
                prospect.platform,
                prospect.lead_score,
                row.contact_confidence,
                row.contact_records,
                PRODUCT_FIT_LABELS.get(prospect.product_fit, prospect.product_fit),
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type),
                prospect.wechat,
                prospect.telegram,
                prospect.email,
                prospect.website,
                prospect.profile_url,
                row.search_query,
                " | ".join(f"{link.label}: {link.url}" for link in row.search_links),
                row.action_hint,
                row.reason,
                prospect.next_action or prospect.suggested_action,
                prospect.evidence,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-contact-workbench-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/contact-workbench/action")
def contact_workbench_action(
    prospect_id: int = Form(...),
    action: str = Form(default=""),
    wechat: str = Form(default=""),
    qq: str = Form(default=""),
    telegram: str = Form(default=""),
    email: str = Form(default=""),
    website: str = Form(default=""),
    contact_source: str = Form(default=""),
    contact_note: str = Form(default=""),
    no_contact_reason: str = Form(default=""),
    next_action: str = Form(default=""),
    mode: str = Form(default="missing"),
    platform: str = Form(default="domestic"),
    min_score: int = Form(default=50),
    db: Session = Depends(get_db),
):
    ok = apply_contact_action(
        db,
        prospect_id=prospect_id,
        action=action,
        wechat=wechat,
        qq=qq,
        telegram=telegram,
        email=email,
        website=website,
        contact_source=contact_source,
        contact_note=contact_note,
        no_contact_reason=no_contact_reason,
        next_action=next_action,
    )
    message = quote("已处理客户" if ok else "未找到客户或动作无效")
    return RedirectResponse(
        f"/contact-workbench?mode={quote(mode)}&platform={quote(platform)}&min_score={min_score}&message={message}",
        status_code=303,
    )


@app.post("/contact-workbench/enrich-public")
def contact_workbench_enrich_public(
    mode: str = Form(default="missing"),
    platform: str = Form(default="domestic"),
    min_score: int = Form(default=50),
    limit: int = Form(default=12),
    db: Session = Depends(get_db),
):
    rows = load_contact_workbench_rows(
        db,
        mode="missing",
        platform=platform,
        min_score=max(0, min(100, min_score)),
        limit=max(1, min(80, limit)),
    )
    result = enrich_missing_contacts_from_public_pages(
        db,
        prospect_ids=[row.prospect.id for row in rows],
        limit=max(1, min(30, limit)),
    )
    failures = "，".join(f"{key}:{value}" for key, value in result.failure_breakdown.items()) or "无"
    message = quote(
        f"公开页面补全完成：扫描 {result.scanned}，读取页面 {result.fetched_pages}，搜索 {result.searched}，"
        f"补到 {result.enriched}，新增记录 {result.contacts_created}，"
        f"无公开入口 {result.no_public_url}，低置信度 {result.low_confidence}，读取失败 {result.failed}。失败分类：{failures}。"
    )
    return RedirectResponse(
        f"/contact-workbench?mode={quote(mode)}&platform={quote(platform)}&min_score={min_score}&message={message}",
        status_code=303,
    )


@app.get("/tasks.csv")
def tasks_csv(db: Session = Depends(get_db)):
    groups = load_task_groups(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "group",
            "display_name",
            "platform",
            "lead_score",
            "product_fit",
            "customer_type",
            "status",
            "next_action",
            "suggested_action",
            "next_follow_up_at",
            "profile_url",
            "wechat",
            "telegram",
            "email",
            "evidence",
        ]
    )
    for group_name, rows in groups:
        for row in rows:
            writer.writerow(
                [
                    group_name,
                    row.display_name,
                    row.platform,
                    row.lead_score,
                    PRODUCT_FIT_LABELS.get(row.product_fit, row.product_fit),
                    CUSTOMER_TYPE_LABELS.get(row.customer_type, row.customer_type),
                    PROSPECT_STATUS_LABELS.get(row.status, row.status),
                    row.next_action,
                    row.suggested_action,
                    row.next_follow_up_at.strftime("%Y-%m-%d %H:%M") if row.next_follow_up_at else "",
                    row.profile_url,
                    row.wechat,
                    row.telegram,
                    row.email,
                    row.evidence,
                ]
            )
    output.seek(0)
    filename = f"lead-radar-tasks-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/domestic-review", response_class=HTMLResponse)
def domestic_review_page(
    request: Request,
    status: str = Query(default="open"),
    min_score: int = Query(default=40),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    rows = load_domestic_review_rows(db, status=status, min_score=min_score)
    stats = {
        "total": len(rows),
        "priority": sum(1 for row in rows if row.label == "优先跟进"),
        "need_contact": sum(1 for row in rows if row.label == "需补联系方式"),
        "risk": sum(1 for row in rows if row.label == "需人工审核"),
    }
    return templates.TemplateResponse(
        request,
        "domestic_review.html",
        {
            "rows": rows,
            "stats": stats,
            "filters": {"status": status, "min_score": min_score},
            "message": message,
            "signal_labels": SIGNAL_LABELS,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/ops", response_class=HTMLResponse)
def acquisition_ops_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "acquisition_ops.html",
        {
            "board": build_acquisition_ops_board(db),
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/demand-radar", response_class=HTMLResponse)
def demand_radar_page(
    request: Request,
    status: str = Query(default="all"),
    risk: str = Query(default="all"),
    min_score: int = Query(default=40),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    rows = load_demand_signals(db, status=status, risk=risk, min_score=min_score)
    return templates.TemplateResponse(
        request,
        "demand_radar.html",
        {
            "rows": rows,
            "stats": build_demand_stats(rows),
            "filters": {"status": status, "risk": risk, "min_score": min_score},
            "status_labels": demand_action_labels(),
            "signal_labels": SIGNAL_LABELS,
            "message": message,
        },
    )


@app.post("/demand-radar/action")
def demand_radar_action(
    mention_id: int = Form(...),
    action: str = Form(...),
    status: str = Form(default="all"),
    risk: str = Form(default="all"),
    min_score: int = Form(default=40),
    db: Session = Depends(get_db),
):
    mention = db.get(Mention, mention_id)
    if mention is None:
        message = "信号不存在。"
    else:
        if action == "qualify":
            mention.status = "qualified"
            message = "已标记为可跟进信号。"
        elif action == "noise":
            mention.status = "noise"
            mention.priority_score = min(mention.priority_score, 20)
            message = "已标记为噪音。"
        elif action == "risk":
            mention.status = "review"
            mention.risk_score = max(mention.risk_score, 70)
            message = "已标记为合规审核。"
        elif action == "rebuild_company":
            rebuild_companies(db)
            message = "已尝试合并到 B2B 客户库。"
        else:
            message = "未知操作。"
        db.commit()
    return RedirectResponse(
        f"/demand-radar?status={quote(status)}&risk={quote(risk)}&min_score={min_score}&message={quote(message)}",
        status_code=303,
    )


@app.get("/b2b-accounts", response_class=HTMLResponse)
def b2b_accounts_page(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default="all"),
    contact: str = Query(default="all"),
    min_score: int = Query(default=0),
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    rows = search_b2b_accounts(db, q) if q.strip() else load_b2b_accounts(db, status=status, contact=contact, min_score=min_score)
    b2b_job_kinds = {"b2b_website_scan", "b2b_github_enrich", "b2b_contact_waterfall", "b2b_waterfall"}
    recent_jobs = list(
        db.scalars(
            select(AgentJob)
            .where(AgentJob.kind.in_(b2b_job_kinds))
            .order_by(desc(AgentJob.created_at))
            .limit(8)
        )
    )
    return templates.TemplateResponse(
        request,
        "b2b_accounts.html",
        {
            "rows": rows,
            "stats": build_b2b_stats(rows),
            "filters": {"q": q, "status": status, "contact": contact, "min_score": min_score},
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "recent_jobs": recent_jobs,
            "job_status_labels": AGENT_JOB_STATUS_LABELS,
            "job_result_summary": job_result_summary,
            "message": message,
        },
    )


@app.get("/b2b-accounts.csv")
def b2b_accounts_csv(
    status: str = Query(default="all"),
    contact: str = Query(default="all"),
    min_score: int = Query(default=0),
    db: Session = Depends(get_db),
):
    rows = load_b2b_accounts(db, status=status, contact=contact, min_score=min_score, limit=1000)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "company_name",
            "website",
            "domain",
            "country",
            "customer_type",
            "priority_score",
            "fit_score",
            "intent_score",
            "contact_score",
            "risk_score",
            "need_reason",
            "signal_count",
            "source_count",
            "contact_count",
            "contact_status",
            "crm_status",
            "next_action",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.company_name,
                row.website,
                row.domain,
                row.country,
                row.customer_type,
                row.priority_score,
                row.fit_score,
                row.intent_score,
                row.contact_score,
                row.risk_score,
                row.need_reason,
                row.signal_count,
                row.source_count,
                row.contact_count,
                row.contact_status,
                row.crm_status,
                row.next_action,
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=lead-radar-b2b-accounts.csv"},
    )


@app.get("/b2b-accounts/{company_id}", response_class=HTMLResponse)
def b2b_account_detail_page(
    request: Request,
    company_id: int,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    detail = load_b2b_account_detail(db, company_id)
    if detail is None:
        return RedirectResponse("/b2b-accounts?message=" + quote("公司不存在。"), status_code=303)
    return templates.TemplateResponse(
        request,
        "company_detail.html",
        {
            "detail": detail,
            "company": detail.company,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
            "message": message,
        },
    )


@app.post("/b2b-accounts/rebuild")
def b2b_accounts_rebuild(db: Session = Depends(get_db)):
    result = rebuild_companies(db)
    message = (
        f"B2B 回填完成：新增 {result.companies_created}，更新 {result.companies_updated}，"
        f"关联线索 {result.prospects_linked}，信号 {result.signals_created}。"
    )
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)


@app.post("/b2b-accounts/rescore")
def b2b_accounts_rescore(db: Session = Depends(get_db)):
    result = rescore_dual_mode(db)
    message = f"四分制重算完成：信号 {result['mentions']}，线索 {result['prospects']}，公司 {result['companies']}。"
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)


@app.post("/b2b-accounts/scan-websites")
def b2b_accounts_scan_websites(limit: int = Form(default=5), db: Session = Depends(get_db)):
    job = enqueue_b2b_job(db, "b2b_website_scan", limit=max(1, min(80, limit)))
    worker_info = ensure_worker_pool(db, desired_count=1, poll_seconds=5)
    message = f"官网扫描已加入后台队列：job #{job.id}，worker 启动 {len(worker_info.get('started', []))} 个。"
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)
    result = scan_company_websites(db, limit=max(1, min(80, limit)))
    message = (
        f"官网扫描完成：扫描 {result.scanned}，新增信号 {result.created_signals}，"
        f"新增联系方式 {result.created_contacts}，失败 {result.failed}。"
    )
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)


@app.post("/b2b-accounts/enrich-github")
def b2b_accounts_enrich_github(limit: int = Form(default=5), db: Session = Depends(get_db)):
    job = enqueue_b2b_job(db, "b2b_github_enrich", limit=max(1, min(80, limit)))
    worker_info = ensure_worker_pool(db, desired_count=1, poll_seconds=5)
    message = f"GitHub 增强已加入后台队列：job #{job.id}，worker 启动 {len(worker_info.get('started', []))} 个。"
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)
    result = enrich_github_companies(db, limit=max(1, min(80, limit)))
    message = (
        f"GitHub 增强完成：扫描 {result.scanned}，新增信号 {result.created_signals}，"
        f"新增联系方式 {result.created_contacts}，失败 {result.failed}。"
    )
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)


@app.post("/b2b-accounts/waterfall")
def b2b_accounts_waterfall(limit: int = Form(default=3), db: Session = Depends(get_db)):
    job = enqueue_b2b_job(db, "b2b_waterfall", limit=max(1, min(80, limit)))
    worker_info = ensure_worker_pool(db, desired_count=1, poll_seconds=5)
    message = f"B2B Waterfall 已加入后台队列：job #{job.id}，worker 启动 {len(worker_info.get('started', []))} 个。"
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)
    result = run_b2b_waterfall(db, limit=max(1, min(80, limit)))
    message = (
        f"Waterfall 完成：官网信号 {result.website.created_signals}，GitHub 信号 {result.github.created_signals}，"
        f"联系方式 {result.contacts.created_contacts}。"
    )
    return RedirectResponse("/b2b-accounts?message=" + quote(message), status_code=303)


@app.get("/platforms", response_class=HTMLResponse)
def platforms_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "platforms.html",
        {
            "platforms": build_platform_statuses(db),
        },
    )


@app.get("/platforms.csv")
def platforms_csv(db: Session = Depends(get_db)):
    rows = build_platform_statuses(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "platform",
            "mode",
            "status",
            "quality_score",
            "source_count",
            "enabled_sources",
            "success_count",
            "failure_count",
            "blocked_sources",
            "candidates",
            "candidate_accepted",
            "candidate_review",
            "not_detail",
            "missing_time",
            "old_content",
            "low_intent",
            "detail_ok",
            "detail_blocked",
            "detail_failed",
            "usable_mentions",
            "review_mentions",
            "invalid_mentions",
            "high_value_mentions",
            "next_collect_at",
            "cooldown_until",
            "recommended_action",
            "note",
            "last_error",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.name,
                row.mode,
                row.status,
                row.quality_score,
                row.source_count,
                row.enabled_sources,
                row.success_count,
                row.failure_count,
                row.blocked_sources,
                row.candidates,
                row.candidate_accepted,
                row.candidate_review,
                row.not_detail,
                row.missing_time,
                row.old_content,
                row.low_intent,
                row.detail_ok,
                row.detail_blocked,
                row.detail_failed,
                row.usable_mentions,
                row.review_mentions,
                row.invalid_mentions,
                row.high_value_mentions,
                row.next_collect_at.isoformat(sep=" ") if row.next_collect_at else "",
                row.cooldown_until.isoformat(sep=" ") if row.cooldown_until else "",
                row.recommended_action,
                row.note,
                row.last_error,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-platforms-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/domestic-review.csv")
def domestic_review_csv(
    status: str = Query(default="open"),
    min_score: int = Query(default=40),
    db: Session = Depends(get_db),
):
    rows = load_domestic_review_rows(db, status=status, min_score=min_score, limit=1000)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "review_score",
            "label",
            "title",
            "source",
            "url",
            "mention_score",
            "signal_type",
            "risk_level",
            "prospect",
            "product_fit",
            "customer_type",
            "prospect_status",
            "has_contact",
            "reason",
            "next_action",
        ]
    )
    for row in rows:
        mention = row.mention
        prospect = row.prospect
        writer.writerow(
            [
                row.review_score,
                row.label,
                row.title,
                row.source_name,
                row.url,
                mention.score if mention else "",
                SIGNAL_LABELS.get(mention.signal_type, mention.signal_type) if mention else "",
                mention.risk_level if mention else "",
                prospect.display_name if prospect else "",
                PRODUCT_FIT_LABELS.get(prospect.product_fit, prospect.product_fit) if prospect else "",
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type) if prospect else "",
                PROSPECT_STATUS_LABELS.get(prospect.status, prospect.status) if prospect else "",
                "yes" if row.has_contact else "no",
                row.reason,
                prospect.next_action if prospect else "",
            ]
        )
    output.seek(0)
    filename = f"lead-radar-domestic-review-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/domestic-review/bulk")
def domestic_review_bulk(
    row_ids: list[str] = Form(default=[]),
    action: str = Form(default=""),
    status: str = Form(default="open"),
    min_score: int = Form(default=60),
    db: Session = Depends(get_db),
):
    if not row_ids or action not in {"qualify", "contacted", "need_contact", "follow_up", "invalid"}:
        return RedirectResponse("/domestic-review", status_code=303)
    count = apply_domestic_review_action(db, row_ids, action)
    message = quote(f"已处理 {count} 条国内线索")
    return RedirectResponse(
        f"/domestic-review?status={quote(status)}&min_score={min_score}&message={message}",
        status_code=303,
    )


def load_task_groups(db: Session) -> list[tuple[str, list[Prospect]]]:
    today_end = datetime.combine(datetime.now().date(), datetime.max.time())
    base = (
        select(Prospect)
        .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .where(Prospect.lead_score >= 60)
        .where(Prospect.status.notin_(["won", "invalid"]))
    )
    due = list(
        db.scalars(
            base.where(Prospect.next_follow_up_at.is_not(None))
            .where(Prospect.next_follow_up_at <= today_end)
            .order_by(Prospect.next_follow_up_at, desc(Prospect.lead_score))
            .limit(50)
        )
    )
    new = list(
        db.scalars(
            base.where(Prospect.status == "new")
            .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(50)
        )
    )
    no_action = list(
        db.scalars(
            base.where(Prospect.next_action == "")
            .where(Prospect.status.in_(["new", "qualified", "contacted"]))
            .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(50)
        )
    )
    trial_follow = list(
        db.scalars(
            base.where(Prospect.status == "trial_sent")
            .order_by(Prospect.next_follow_up_at.is_(None), Prospect.next_follow_up_at, desc(Prospect.lead_score))
            .limit(50)
        )
    )
    return [
        ("今日到期复访", due),
        ("新客户优先处理", new),
        ("缺少下一步动作", no_action),
        ("已发测试待推进", trial_follow),
    ]


def load_today_rows(db: Session, limit: int = 120) -> list[Prospect]:
    today_end = datetime.combine(datetime.now().date(), datetime.max.time())
    domestic_platforms = [
        "zhihu",
        "tieba",
        "xiaohongshu",
        "douyin",
        "wearesellers",
        "v2ex",
        "segmentfault",
        "learnku",
        "gitee",
        "bilibili",
        "weibo",
        "contact",
        "import",
    ]
    base = (
        select(Prospect)
        .where(Prospect.platform.in_(domestic_platforms))
        .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .where(Prospect.lead_score >= 60)
        .where(Prospect.status.notin_(["won", "invalid"]))
    )
    due = list(
        db.scalars(
            base.where(Prospect.next_follow_up_at.is_not(None))
            .where(Prospect.next_follow_up_at <= today_end)
            .order_by(Prospect.next_follow_up_at, desc(Prospect.lead_score))
            .limit(limit)
        )
    )
    due_ids = {row.id for row in due}
    hot_query = base.where(Prospect.status.in_(["new", "qualified", "follow_up"]))
    if due_ids:
        hot_query = hot_query.where(Prospect.id.notin_(due_ids))
    hot = list(
        db.scalars(
            hot_query.order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(max(0, limit - len(due)))
        )
    )
    return due + hot


def has_contact(prospect: Prospect) -> bool:
    return prospect_has_real_contact(prospect)
    note = (prospect.contact_note or "").lower()
    return bool(
        prospect.wechat
        or prospect.email
        or prospect.telegram
        or "qq:" in note
        or "手机:" in note
        or "邮箱:" in note
        or "telegram:" in note
        or "微信:" in note
    )


@app.get("/mentions/{mention_id}", response_class=HTMLResponse)
def mention_detail(mention_id: int, request: Request, db: Session = Depends(get_db)):
    mention = db.get(Mention, mention_id)
    if mention is None:
        return RedirectResponse("/", status_code=303)

    if not mention.outreach_message:
        mention.outreach_message = fallback_outreach_message(mention)
        db.commit()
        db.refresh(mention)

    return templates.TemplateResponse(
        request,
        "mention_detail.html",
        {
            "mention": mention,
            "evidence_report": build_lead_evidence_report(db, mention),
            "status_labels": STATUS_LABELS,
            "signal_labels": SIGNAL_LABELS,
        },
    )


@app.post("/mentions/{mention_id}/status/{status}")
def update_mention_status(mention_id: int, status: str, db: Session = Depends(get_db)):
    mention = db.get(Mention, mention_id)
    if mention is not None and status in STATUS_LABELS:
        mention.status = status
        db.commit()

    return RedirectResponse(f"/mentions/{mention_id}", status_code=303)


@app.post("/mentions/{mention_id}/notify")
async def notify_mention(mention_id: int, db: Session = Depends(get_db)):
    mention = db.get(Mention, mention_id)
    if mention is not None:
        await notify_wework(db, mention)

    return RedirectResponse(f"/mentions/{mention_id}", status_code=303)


@app.post("/mentions/{mention_id}/enrich-contact")
def enrich_mention_contact(mention_id: int, db: Session = Depends(get_db)):
    mention = db.get(Mention, mention_id)
    if mention is not None and mention.prospect_id:
        enrich_missing_contacts_from_public_pages(
            db,
            prospect_ids=[mention.prospect_id],
            limit=1,
            min_confidence=35,
            use_search=True,
        )
    return RedirectResponse(f"/mentions/{mention_id}", status_code=303)


@app.get("/keywords", response_class=HTMLResponse)
def keywords(request: Request, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Keyword).order_by(desc(Keyword.weight), Keyword.phrase)))
    return templates.TemplateResponse(
        request,
        "keywords.html",
        {
            "keywords": rows,
            "suggestions": build_keyword_suggestions(db),
        },
    )


@app.post("/keywords")
def add_keyword(
    phrase: str = Form(default=""),
    weight: int = Form(default=20),
    category: str = Form(default="scenario"),
    db: Session = Depends(get_db),
):
    phrase = phrase.strip()
    category = category.strip() or "scenario"
    weight = max(1, min(100, weight))
    if phrase:
        keyword = db.query(Keyword).filter(Keyword.phrase == phrase).first()
        if keyword is None:
            db.add(Keyword(phrase=phrase[:160], weight=weight, category=category[:60], enabled=True))
        else:
            keyword.weight = weight
            keyword.category = category[:60]
            keyword.enabled = True
        db.commit()
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/{keyword_id}/toggle")
def toggle_keyword(keyword_id: int, db: Session = Depends(get_db)):
    keyword = db.get(Keyword, keyword_id)
    if keyword is not None:
        keyword.enabled = not keyword.enabled
        db.commit()
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/{keyword_id}/weight")
def update_keyword_weight(
    keyword_id: int,
    weight: int = Form(default=20),
    category: str = Form(default="scenario"),
    db: Session = Depends(get_db),
):
    keyword = db.get(Keyword, keyword_id)
    if keyword is not None:
        keyword.weight = max(1, min(100, weight))
        keyword.category = (category.strip() or keyword.category)[:60]
        db.commit()
    return RedirectResponse("/keywords", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings_status": {
                "github_token": bool(settings.github_token),
                "gitee_token": bool(settings.gitee_token),
                "wework_webhook_url": bool(settings.wework_webhook_url),
                "rsshub_base_url": settings.rsshub_base_url,
                "collector_interval_minutes": settings.collector_interval_minutes,
                "high_intent_threshold": settings.high_intent_threshold,
            }
        },
    )


@app.get("/imports", response_class=HTMLResponse)
def imports_page(
    request: Request,
    message: str = Query(default=""),
):
    return templates.TemplateResponse(
        request,
        "imports.html",
        {
            "message": message,
        },
    )


@app.get("/session-collector", response_class=HTMLResponse)
def session_collector_page(
    request: Request,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    tasks = load_tasks()
    login_statuses = {task.platform: cached_login_status(task.platform) for task in tasks}
    session_diagnostics = build_session_platform_diagnostics(db)
    recent_mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.source_kind == "session_browser")
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.discovered_at))
            .limit(30)
        )
    )
    logged_in_count = sum(1 for status in login_statuses.values() if status.state == "logged_in")
    ready_platforms = [
        row for row in session_diagnostics
        if row.login_state == "logged_in" and row.health not in {"受阻", "需处理"}
    ]
    blocked_platforms = [
        row for row in session_diagnostics
        if row.health in {"受阻", "需处理"} or row.login_state in {"blocked", "profile_open", "error"}
    ]
    high_value_recent = sum(1 for row in recent_mentions if row.score >= 70)
    if logged_in_count == 0:
        next_step = "先选一个平台登录账号，然后关闭登录窗口，再点检查状态。"
        next_url = "#session-platform-tasks"
    elif not ready_platforms:
        next_step = "先处理登录窗口未关闭、验证码、频控或账号异常的平台。"
        next_url = "#session-diagnostics"
    elif high_value_recent == 0:
        next_step = "运行后台批量采集，先小批量验证关键词质量。"
        next_url = "#session-batch-run"
    else:
        next_step = "已有可用线索，去国内质检筛掉噪音后进入今日作战。"
        next_url = "/domestic-review?min_score=40"
    session_flow = {
        "logged_in": logged_in_count,
        "ready": len(ready_platforms),
        "blocked": len(blocked_platforms),
        "recent": len(recent_mentions),
        "high_value": high_value_recent,
        "next_step": next_step,
        "next_url": next_url,
    }
    return templates.TemplateResponse(
        request,
        "session_collector.html",
        {
            "tasks": tasks,
            "platform_labels": PLATFORM_LABELS,
            "login_statuses": login_statuses,
            "session_diagnostics": session_diagnostics,
            "session_flow": session_flow,
            "session_progress": load_progress(),
            "session_events": recent_session_events(12),
            "recent_mentions": recent_mentions,
            "signal_labels": SIGNAL_LABELS,
            "session_source_meta": session_source_meta,
            "session_quality_label": session_quality_label,
            "strategy_version": domestic_search_strategy.STRATEGY_VERSION,
            "message": message,
        },
    )


def session_source_meta(mention: Mention) -> dict[str, str]:
    platform = ""
    keyword = ""
    quality = ""
    for line in (mention.content or "").splitlines()[:5]:
        if line.startswith("平台:"):
            platform = line.split(":", 1)[1].strip()
        elif line.startswith("关键词:"):
            keyword = line.split(":", 1)[1].strip()
        elif line.startswith("质量层级:"):
            quality = line.split(":", 1)[1].strip()
    if not platform and mention.source_name.startswith("Session "):
        source = mention.source_name.removeprefix("Session ")
        if ":" in source:
            platform, keyword = [part.strip() for part in source.split(":", 1)]
        else:
            platform = source.strip()
    return {
        "platform": platform or "未知平台",
        "keyword": keyword or "-",
        "method": "登录会话",
        "quality": quality or session_quality_label(mention),
    }


def session_quality_label(mention: Mention) -> str:
    for line in (mention.content or "").splitlines()[:5]:
        if line.startswith("质量层级:"):
            return line.split(":", 1)[1].strip()
    if mention.score >= 70:
        return "高意向"
    if mention.score >= 40:
        return "待复核"
    return "低价值"


def session_progress_payload() -> dict[str, object]:
    progress = session_progress_detail()
    running = progress["state"] in {"queued", "starting", "running"}
    stale = False
    if running and progress["updated_at"]:
        try:
            updated_at = datetime.fromisoformat(str(progress["updated_at"]))
            stale = datetime.now() - updated_at > timedelta(minutes=15)
        except ValueError:
            stale = False
    if stale:
        running = False
    payload = dict(progress)
    payload["running"] = running
    payload["stale"] = stale
    if stale:
        payload["state"] = "paused"
        payload["state_label"] = "进度停滞"
        payload["failure_code"] = payload.get("failure_code") or "stale"
        payload["failure_label"] = payload.get("failure_label") or "进度停滞"
        payload["failure_reason"] = payload.get("failure_reason") or "后台采集超过 15 分钟没有更新，可能已被平台拦截、浏览器卡住或进程异常。"
        payload["next_step"] = "刷新平台状态；如果仍无变化，重启服务后从单平台试跑开始。"
    return payload


def run_session_platform_background(platform: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        task = next((item for item in load_tasks() if item.platform == platform), None)
        if task is None:
            write_progress("paused", platform=platform, message="未找到该平台任务。")
            return
        result = run_session_collection(db, task, headless=True)
        if result.inserted:
            rebuild_prospects(db)
    finally:
        db.close()


def run_session_smoke_background(platform: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        task = next((item for item in load_tasks() if item.platform == platform), None)
        if task is None:
            write_progress("paused", platform=platform, message="未找到该平台任务。")
            return
        result = run_session_smoke_test(db, task, headless=True)
        if result.inserted:
            rebuild_prospects(db)
    finally:
        db.close()


def run_session_batch_background(platform_limit: int) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        run_enabled_session_collections(
            db,
            platform_limit=max(1, min(6, platform_limit)),
            keyword_limit=3,
            per_platform_limit=18,
            headless=True,
        )
    finally:
        db.close()


@app.get("/session-collector/progress.json")
def session_collector_progress_json():
    return JSONResponse(session_progress_payload())


@app.post("/session-collector/tasks")
def save_session_task(
    platform: str = Form(default="zhihu"),
    keywords: str = Form(default=""),
    daily_limit: int = Form(default=20),
    page_limit: int = Form(default=2),
    delay_seconds: int = Form(default=8),
):
    if keywords.strip():
        upsert_task(
            SessionTask(
                platform=platform,
                keywords=keywords.strip()[:1000],
                daily_limit=max(1, min(200, daily_limit)),
                page_limit=max(1, min(10, page_limit)),
                delay_seconds=max(3, min(120, delay_seconds)),
                enabled=True,
            )
        )
    message = quote("会话采集任务已保存")
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/tasks/sync")
def sync_session_tasks():
    result = sync_default_tasks(overwrite_keywords=True)
    message = quote(
        f"已同步推荐任务：策略 {result['strategy_version']}，新增 {result['added']}，更新 {result['updated']}，平台 {result['tasks']}。"
    )
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/login/{platform}")
def session_collector_login(platform: str):
    result = open_login_session(platform)
    message = quote(result.message)
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/status/{platform}")
def session_collector_status(platform: str):
    status = check_login_status(platform, headless=True)
    message = quote(f"{PLATFORM_LABELS.get(platform, platform)}：{status.label}。{status.message}")
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/run/{platform}")
def session_collector_run(platform: str, background_tasks: BackgroundTasks):
    task = next((item for item in load_tasks() if item.platform == platform), None)
    if task is None:
        message = quote("未找到该平台任务")
        return RedirectResponse(f"/session-collector?message={message}", status_code=303)
    write_progress(
        "queued",
        platform=platform,
        message=f"{PLATFORM_LABELS.get(platform, platform)} 已加入后台采集队列，页面会自动刷新进度。",
    )
    background_tasks.add_task(run_session_platform_background, platform)
    message = quote(f"{PLATFORM_LABELS.get(platform, platform)} 已开始后台采集，请看当前运行状态。")
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/smoke/{platform}")
def session_collector_smoke(platform: str, background_tasks: BackgroundTasks):
    task = next((item for item in load_tasks() if item.platform == platform), None)
    if task is None:
        message = quote("未找到该平台任务")
        return RedirectResponse(f"/session-collector?message={message}", status_code=303)
    write_progress(
        "queued",
        platform=platform,
        keyword=(task.keyword_list[0] if task.keyword_list else ""),
        message=f"{PLATFORM_LABELS.get(platform, platform)} 单平台试跑已开始：1 个关键词，最多 5 条。",
    )
    background_tasks.add_task(run_session_smoke_background, platform)
    message = quote(f"{PLATFORM_LABELS.get(platform, platform)} 已开始单平台试跑，请看当前运行状态。")
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.post("/session-collector/run-all")
def session_collector_run_all(
    background_tasks: BackgroundTasks,
    platform_limit: int = Form(default=2),
    headless: str = Form(default=""),
):
    limit = max(1, min(6, platform_limit))
    write_progress("queued", message=f"批量后台采集已加入队列：最多 {limit} 个平台。")
    background_tasks.add_task(run_session_batch_background, limit)
    message = quote("批量后台采集已开始，请看当前运行状态。")
    return RedirectResponse(f"/session-collector?message={message}", status_code=303)


@app.get("/imports/sample.csv")
def imports_sample_csv():
    return StreamingResponse(
        iter([sample_csv()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": 'attachment; filename="lead-radar-import-template.csv"'},
    )


@app.post("/imports/prospects")
async def imports_prospects(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    result = import_prospects_csv(db, content)
    message = f"导入完成：新增 {result.created}，更新 {result.updated}，跳过 {result.skipped}"
    if result.errors:
        message += f"，错误 {len(result.errors)} 条"
    return RedirectResponse(f"/imports?message={quote(message)}", status_code=303)


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "source_rows": build_source_attribution(db),
            "customer_type_rows": build_customer_type_attribution(db),
            "keyword_rows": build_keyword_attribution(db),
        },
    )


@app.get("/analytics.csv")
def analytics_csv(db: Session = Depends(get_db)):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "source_name",
            "source_kind",
            "quality_score",
            "quality_status",
            "mentions",
            "high_value_mentions",
            "prospects",
            "contacted",
            "wechat_added",
            "trial_sent",
            "won",
            "invalid",
            "trial_rate",
            "win_rate",
        ]
    )
    for row in build_source_attribution(db):
        writer.writerow(
            [
                row.source_name,
                row.source_kind,
                row.quality_score,
                row.quality_status,
                row.mentions,
                row.high_value_mentions,
                row.prospects,
                row.contacted,
                row.wechat_added,
                row.trial_sent,
                row.won,
                row.invalid,
                f"{row.trial_rate:.2%}",
                f"{row.win_rate:.2%}",
            ]
        )
    output.seek(0)
    filename = f"lead-radar-analytics-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/strategy", response_class=HTMLResponse)
def strategy_page(
    request: Request,
    message: str = Query(default=""),
    db: Session = Depends(get_db),
):
    board = build_strategy_board(db)
    return templates.TemplateResponse(
        request,
        "strategy.html",
        {
            "board": board,
            "message": message,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.get("/strategy.csv")
def strategy_csv(db: Session = Depends(get_db)):
    board = build_strategy_board(db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "metric", "value"])
    writer.writerow(["sales_brief", "active_pipeline", board.sales_brief.active_pipeline])
    writer.writerow(["sales_brief", "due_followups", board.sales_brief.due_followups])
    writer.writerow(["sales_brief", "high_score_new", board.sales_brief.high_score_new])
    writer.writerow(["sales_brief", "no_next_action", board.sales_brief.no_next_action])
    writer.writerow(["sales_brief", "trial_pending", board.sales_brief.trial_pending])
    writer.writerow(["sales_brief", "missing_contact", board.sales_brief.missing_contact])
    writer.writerow([])
    writer.writerow(["section", "priority", "kind", "title", "reason", "next_step"])
    for action in board.actions:
        writer.writerow(["action", action.priority, action.kind, action.title, action.reason, action.next_step])
    writer.writerow([])
    writer.writerow(["section", "keyword", "strategy_score", "mentions", "high_value_mentions", "prospects", "trial_sent", "won", "invalid"])
    for row in board.top_keywords:
        writer.writerow(["top_keyword", row.keyword, row.strategy_score, row.mentions, row.high_value_mentions, row.prospects, row.trial_sent, row.won, row.invalid])
    for row in board.weak_keywords:
        writer.writerow(["weak_keyword", row.keyword, row.strategy_score, row.mentions, row.high_value_mentions, row.prospects, row.trial_sent, row.won, row.invalid])
    writer.writerow([])
    writer.writerow(["section", "source_name", "source_kind", "quality_score", "quality_status", "mentions", "high_value_mentions", "prospects", "trial_sent", "won", "invalid"])
    for row in board.top_sources:
        writer.writerow(["top_source", row.source_name, row.source_kind, row.quality_score, row.quality_status, row.mentions, row.high_value_mentions, row.prospects, row.trial_sent, row.won, row.invalid])
    for row in board.weak_sources:
        writer.writerow(["weak_source", row.source_name, row.source_kind, row.quality_score, row.quality_status, row.mentions, row.high_value_mentions, row.prospects, row.trial_sent, row.won, row.invalid])
    writer.writerow([])
    writer.writerow(["section", "phrase", "priority", "category", "weight", "reason"])
    for item in board.keyword_suggestions:
        writer.writerow(["keyword_suggestion", item.phrase, item.priority, item.category, item.weight, item.reason])
    writer.writerow([])
    writer.writerow(["section", "name", "priority", "kind", "url", "reason"])
    for item in board.source_suggestions:
        writer.writerow(["source_suggestion", item.name, item.priority, item.kind, item.url, item.reason])
    writer.writerow([])
    writer.writerow(["section", "display_name", "platform", "lead_score", "product_fit", "customer_type", "status", "next_action", "profile_url"])
    for prospect in board.priority_prospects:
        writer.writerow(
            [
                "priority_prospect",
                prospect.display_name,
                prospect.platform,
                prospect.lead_score,
                PRODUCT_FIT_LABELS.get(prospect.product_fit, prospect.product_fit),
                CUSTOMER_TYPE_LABELS.get(prospect.customer_type, prospect.customer_type),
                PROSPECT_STATUS_LABELS.get(prospect.status, prospect.status),
                prospect.next_action or prospect.suggested_action,
                prospect.profile_url,
            ]
        )
    output.seek(0)
    filename = f"lead-radar-strategy-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/strategy/apply-keywords")
def strategy_apply_keywords(
    limit: int = Form(default=10),
    db: Session = Depends(get_db),
):
    result = apply_keyword_suggestions(db, limit=max(1, min(30, limit)))
    message = f"已应用关键词候选：新增 {result.created}，更新 {result.updated}。"
    return RedirectResponse(f"/strategy?message={quote(message)}", status_code=303)


@app.post("/strategy/apply-sources")
def strategy_apply_sources(
    limit: int = Form(default=12),
    db: Session = Depends(get_db),
):
    result = apply_source_suggestions(db, limit=max(1, min(40, limit)))
    message = f"已应用来源候选：新增 {result.created}，更新 {result.updated}。"
    return RedirectResponse(f"/strategy?message={quote(message)}", status_code=303)


@app.post("/strategy/growth-cycle")
def strategy_growth_cycle(
    keyword_limit: int = Form(default=6),
    source_limit: int = Form(default=8),
    run_collect: str = Form(default="on"),
    auto_disable_sources: str = Form(default=""),
    db: Session = Depends(get_db),
):
    result = run_growth_cycle(
        db,
        keyword_limit=max(0, min(30, keyword_limit)),
        source_limit=max(0, min(40, source_limit)),
        run_collect=run_collect == "on",
        auto_disable_sources=auto_disable_sources == "on",
    )
    ingestion_inserted = result.ingestion.get("inserted", 0) if result.ingestion else 0
    message = (
        f"增长循环完成：关键词新增 {result.keywords.created}，来源新增 {result.sources.created}，"
        f"本轮入库 {ingestion_inserted}，客户重建 {result.prospects or {}}。"
    )
    return RedirectResponse(f"/strategy?message={quote(message)}", status_code=303)


@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": build_daily_report(db),
            "wework_enabled": bool(get_settings().wework_webhook_url),
            "send_result": "",
        },
    )


@app.get("/reports")
def reports_alias():
    return RedirectResponse("/report", status_code=303)


@app.post("/report/send-wework", response_class=HTMLResponse)
async def report_send_wework(request: Request, db: Session = Depends(get_db)):
    result = await send_daily_report_wework(db)
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": build_daily_report(db),
            "wework_enabled": bool(get_settings().wework_webhook_url),
            "send_result": f"{result['status']}: {result['message']}",
        },
    )


@app.get("/sources", response_class=HTMLResponse)
def sources(request: Request, message: str = Query(default=""), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Source).order_by(Source.name)))
    source_metrics = {}
    for source in rows:
        high_value = (
            db.query(Mention)
            .filter(Mention.source_name == source.name)
            .filter(Mention.signal_type.in_(HIGH_VALUE_SIGNALS))
            .filter(Mention.score >= 60)
            .count()
        )
        risk = (
            db.query(Mention)
            .filter(Mention.source_name == source.name)
            .filter(Mention.signal_type == "risk_signal")
            .count()
        )
        total = db.query(Mention).filter(Mention.source_name == source.name).count()
        source_metrics[source.name] = {
            "total": total,
            "high_value": high_value,
            "risk": risk,
        }

    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "sources": rows,
            "source_metrics": source_metrics,
            "source_quality_labels": SOURCE_QUALITY_LABELS,
            "source_quality_classes": SOURCE_QUALITY_CLASSES,
            "source_suggestions": build_source_suggestions(db),
            "message": message,
        },
    )


@app.post("/sources/{source_id}/toggle")
def toggle_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if source is not None:
        source.enabled = not source.enabled
        if source.enabled:
            source.auto_disabled_at = None
            source.consecutive_failures = 0
        db.commit()

    return RedirectResponse("/sources", status_code=303)


@app.post("/sources")
def add_source(
    name: str = Form(default=""),
    kind: str = Form(default="github_search"),
    url: str = Form(default=""),
    enabled: str = Form(default="on"),
    db: Session = Depends(get_db),
):
    name = name.strip()
    kind = kind.strip() or "github_search"
    url = url.strip()
    if name and kind:
        source = db.query(Source).filter(Source.name == name).first()
        if source is None:
            db.add(Source(name=name[:120], kind=kind[:40], url=url, enabled=enabled == "on"))
        else:
            source.kind = kind[:40]
            source.url = url
            source.enabled = enabled == "on"
            source.auto_disabled_at = None
        db.commit()
    return RedirectResponse("/sources", status_code=303)


@app.get("/prospects", response_class=HTMLResponse)
def prospects(request: Request, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Prospect).order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at)).limit(200)))
    return templates.TemplateResponse(
        request,
        "prospects.html",
        {
            "prospects": rows,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
        },
    )


@app.get("/prospects/{prospect_id}", response_class=HTMLResponse)
def prospect_detail(prospect_id: int, request: Request, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if prospect is None:
        return RedirectResponse("/prospects", status_code=303)
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect.id)
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
        )
    )
    research = build_research_brief(prospect, mentions)
    events = load_prospect_events(db, prospect.id)
    return templates.TemplateResponse(
        request,
        "prospect_detail.html",
        {
            "prospect": prospect,
            "mentions": mentions,
            "research": research,
            "events": events,
            "event_labels": EVENT_LABELS,
            "status_outcomes": STATUS_OUTCOMES,
            "product_fit_labels": PRODUCT_FIT_LABELS,
            "customer_type_labels": CUSTOMER_TYPE_LABELS,
            "signal_labels": SIGNAL_LABELS,
            "prospect_status_labels": PROSPECT_STATUS_LABELS,
        },
    )


@app.post("/prospects/{prospect_id}/status/{status}")
def update_prospect_status(prospect_id: int, status: str, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None and status in PROSPECT_STATUS_LABELS:
        old_status = prospect.status
        prospect.status = status
        if status in {"contacted", "wechat_added", "trial_sent"}:
            prospect.last_contacted_at = datetime.now()
        if status == "follow_up" and prospect.next_follow_up_at is None:
            prospect.next_follow_up_at = datetime.now() + timedelta(days=3)
        event_type = "outcome" if status in {"won", "invalid"} else "status_change"
        record_prospect_event(
            db,
            prospect,
            event_type,
            value=status,
            note=f"{old_status or '-'} -> {status}",
            commit=False,
        )
        db.commit()
    return RedirectResponse(f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/schedule/{days}")
def schedule_prospect_follow_up(prospect_id: int, days: int, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None and days in {1, 3, 7, 14}:
        prospect.status = "follow_up"
        prospect.next_follow_up_at = datetime.now() + timedelta(days=days)
        record_prospect_event(
            db,
            prospect,
            "follow_up_scheduled",
            value=f"{days}d",
            note=f"{days} 天后复访",
            commit=False,
        )
        db.commit()
    return RedirectResponse(f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/note")
def update_prospect_note(
    prospect_id: int,
    follow_up_note: str = Form(default=""),
    next_action: str = Form(default=""),
    db: Session = Depends(get_db),
):
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None:
        prospect.follow_up_note = follow_up_note[:5000]
        prospect.next_action = next_action[:1000]
        prospect.updated_at = datetime.now()
        record_prospect_event(
            db,
            prospect,
            "note_saved",
            value="note",
            note=(next_action or follow_up_note)[:1000],
            commit=False,
        )
        db.commit()
    return RedirectResponse(f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/contact")
def update_prospect_contact(
    prospect_id: int,
    company_name: str = Form(default=""),
    region: str = Form(default=""),
    website: str = Form(default=""),
    email: str = Form(default=""),
    wechat: str = Form(default=""),
    telegram: str = Form(default=""),
    contact_note: str = Form(default=""),
    db: Session = Depends(get_db),
):
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None:
        prospect.company_name = company_name[:260]
        prospect.region = region[:120]
        prospect.website = website[:1000]
        prospect.email = email[:260]
        prospect.wechat = wechat[:160]
        prospect.telegram = telegram[:160]
        prospect.contact_note = contact_note[:5000]
        prospect.updated_at = datetime.now()
        record_prospect_event(
            db,
            prospect,
            "contact_saved",
            value="contact",
            note="保存联系方式",
            commit=False,
        )
        db.commit()
    return RedirectResponse(f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/event")
def add_prospect_event(
    prospect_id: int,
    event_type: str = Form(default="outcome"),
    value: str = Form(default=""),
    note: str = Form(default=""),
    update_status: str = Form(default=""),
    db: Session = Depends(get_db),
):
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None:
        if update_status in PROSPECT_STATUS_LABELS:
            prospect.status = update_status
            if update_status in {"contacted", "wechat_added", "trial_sent"}:
                prospect.last_contacted_at = datetime.now()
        record_prospect_event(
            db,
            prospect,
            event_type if event_type in EVENT_LABELS else "outcome",
            value=(value or update_status)[:160],
            note=note[:2000],
            commit=False,
        )
        prospect.updated_at = datetime.now()
        db.commit()
    return RedirectResponse(f"/prospects/{prospect_id}", status_code=303)


@app.post("/pipeline/bulk")
def pipeline_bulk_action(
    prospect_ids: list[int] = Form(default=[]),
    bulk_status: str = Form(default=""),
    follow_up_days: int = Form(default=0),
    db: Session = Depends(get_db),
):
    if not prospect_ids:
        return RedirectResponse("/pipeline", status_code=303)

    prospects = db.scalars(select(Prospect).where(Prospect.id.in_(prospect_ids))).all()
    for prospect in prospects:
        if bulk_status in PROSPECT_STATUS_LABELS:
            old_status = prospect.status
            prospect.status = bulk_status
            if bulk_status in {"contacted", "wechat_added", "trial_sent"}:
                prospect.last_contacted_at = datetime.now()
            record_prospect_event(
                db,
                prospect,
                "outcome" if bulk_status in {"won", "invalid"} else "status_change",
                value=bulk_status,
                note=f"bulk: {old_status or '-'} -> {bulk_status}",
                commit=False,
            )
        if follow_up_days in {1, 3, 7, 14}:
            prospect.status = "follow_up"
            prospect.next_follow_up_at = datetime.now() + timedelta(days=follow_up_days)
            record_prospect_event(
                db,
                prospect,
                "follow_up_scheduled",
                value=f"{follow_up_days}d",
                note=f"bulk: {follow_up_days} 天后复访",
                commit=False,
            )
        prospect.updated_at = datetime.now()
    db.commit()
    return RedirectResponse("/pipeline", status_code=303)


@app.get("/api/mentions")
def api_mentions(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Mention).order_by(desc(Mention.discovered_at)).limit(100)))
    return [
        {
            "id": row.id,
            "title": row.title,
            "url": row.canonical_url,
            "source": row.source_name,
            "score": row.score,
            "risk_level": row.risk_level,
            "signal_type": row.signal_type,
            "status": row.status,
            "matched_keywords": row.matched_keywords,
            "score_reasons": row.score_reasons,
            "recommendation": row.recommendation,
            "outreach_message": row.outreach_message,
            "discovered_at": row.discovered_at,
        }
        for row in rows
    ]
