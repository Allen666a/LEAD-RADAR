from __future__ import annotations

import argparse
import asyncio

import uvicorn

from app.database import SessionLocal, create_db
from app.services.agent_queue import (
    enqueue_b2b_job,
    enqueue_practical_domestic_cycle,
    run_worker_loop,
    start_worker_processes,
)
from app.services.b2b_enrichment import (
    enrich_company_contacts_from_pages,
    enrich_github_companies,
    run_b2b_waterfall,
    scan_company_websites,
)
from app.services.compliance import run_compliance_audit
from app.services.company_profiles import rebuild_companies, rescore_dual_mode
from app.services.contact_enrichment import apply_contact_enrichment, build_contact_enrichment_report
from app.services.dedupe import run_dedupe_audit
from app.seed import (
    seed_china_sources,
    seed_community_sources,
    seed_crossborder_sources,
    seed_developer_sources,
    seed_domestic_acquisition,
    seed_defaults,
    seed_market_expansion,
    seed_platform_matrix,
    seed_rsshub_sources,
    seed_seller_sources,
    seed_signal_sources,
)
from app.services.ingest import purge_noise_mentions, refresh_existing_mentions, run_domestic_acquisition_sync, run_ingestion_sync
from app.services.learning import run_feedback_learning
from app.services.p3_quality import run_p3_quality_audit
from app.services.growth import apply_keyword_suggestions, apply_source_suggestions, run_growth_cycle
from app.services.prospects import rebuild_prospects
from app.services.reports import build_daily_report, send_daily_report_wework
from app.services.session_collector import (
    build_session_platform_diagnostics,
    load_tasks,
    open_login_session,
    run_enabled_session_collections,
    run_session_collection,
)
from app.services.source_quality import audit_all_sources


def main() -> None:
    parser = argparse.ArgumentParser(prog="lead-radar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("seed")
    market_parser = subparsers.add_parser("seed-market")
    market_parser.add_argument("--disabled", action="store_true")
    community_parser = subparsers.add_parser("seed-community")
    community_parser.add_argument("--disabled", action="store_true")
    signal_parser = subparsers.add_parser("seed-signals")
    signal_parser.add_argument("--disabled", action="store_true")
    seller_parser = subparsers.add_parser("seed-sellers")
    seller_parser.add_argument("--disabled", action="store_true")
    developer_parser = subparsers.add_parser("seed-developer")
    developer_parser.add_argument("--disabled", action="store_true")
    china_parser = subparsers.add_parser("seed-china")
    china_parser.add_argument("--disabled", action="store_true")
    crossborder_parser = subparsers.add_parser("seed-crossborder")
    crossborder_parser.add_argument("--disabled", action="store_true")
    platform_matrix_parser = subparsers.add_parser("seed-platform-matrix")
    platform_matrix_parser.add_argument("--disabled", action="store_true")
    domestic_acquisition_parser = subparsers.add_parser("seed-domestic-acquisition")
    domestic_acquisition_parser.add_argument("--disabled", action="store_true")
    rsshub_parser = subparsers.add_parser("seed-rsshub")
    rsshub_parser.add_argument("--disabled", action="store_true")
    subparsers.add_parser("run-once")
    domestic_run_parser = subparsers.add_parser("run-domestic-acquisition")
    domestic_run_parser.add_argument("--limit", default=30, type=int)
    subparsers.add_parser("refresh-enrichment")
    subparsers.add_parser("enrich-contacts")
    contact_report_parser = subparsers.add_parser("contact-report")
    contact_report_parser.add_argument("--limit", default=100, type=int)
    dedupe_parser = subparsers.add_parser("dedupe-audit")
    dedupe_parser.add_argument("--dry-run", action="store_true")
    compliance_parser = subparsers.add_parser("audit-compliance")
    compliance_parser.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("purge-noise")
    subparsers.add_parser("rebuild-prospects")
    subparsers.add_parser("rebuild-companies")
    subparsers.add_parser("rescore-dual-mode")
    p3_audit_parser = subparsers.add_parser("p3-quality-audit")
    p3_audit_parser.add_argument("--limit", default=500, type=int)
    website_scan_parser = subparsers.add_parser("scan-company-websites")
    website_scan_parser.add_argument("--limit", default=30, type=int)
    github_enrich_parser = subparsers.add_parser("enrich-github-companies")
    github_enrich_parser.add_argument("--limit", default=30, type=int)
    company_contact_parser = subparsers.add_parser("enrich-company-contacts")
    company_contact_parser.add_argument("--limit", default=30, type=int)
    b2b_waterfall_parser = subparsers.add_parser("b2b-waterfall")
    b2b_waterfall_parser.add_argument("--limit", default=30, type=int)
    b2b_agent_parser = subparsers.add_parser("b2b-agent-job")
    b2b_agent_parser.add_argument(
        "--kind",
        choices=["b2b_website_scan", "b2b_github_enrich", "b2b_contact_waterfall", "b2b_waterfall"],
        default="b2b_waterfall",
    )
    b2b_agent_parser.add_argument("--limit", default=10, type=int)
    report_parser = subparsers.add_parser("daily-report")
    report_parser.add_argument("--send-wework", action="store_true")
    audit_parser = subparsers.add_parser("audit-sources")
    audit_parser.add_argument("--no-disable", action="store_true")
    apply_keywords_parser = subparsers.add_parser("apply-keywords")
    apply_keywords_parser.add_argument("--limit", default=10, type=int)
    apply_sources_parser = subparsers.add_parser("apply-sources")
    apply_sources_parser.add_argument("--limit", default=12, type=int)
    growth_parser = subparsers.add_parser("growth-cycle")
    growth_parser.add_argument("--keyword-limit", default=6, type=int)
    growth_parser.add_argument("--source-limit", default=8, type=int)
    growth_parser.add_argument("--no-collect", action="store_true")
    growth_parser.add_argument("--auto-disable-sources", action="store_true")
    session_login_parser = subparsers.add_parser("session-login")
    session_login_parser.add_argument("--platform", required=True)
    session_collect_parser = subparsers.add_parser("session-collect")
    session_collect_parser.add_argument("--platform", required=True)
    session_collect_parser.add_argument("--headless", action="store_true")
    session_collect_all_parser = subparsers.add_parser("session-collect-all")
    session_collect_all_parser.add_argument("--platform-limit", default=2, type=int)
    session_collect_all_parser.add_argument("--keyword-limit", default=1, type=int)
    session_collect_all_parser.add_argument("--per-platform-limit", default=5, type=int)
    session_collect_all_parser.add_argument("--headless", action="store_true")
    subparsers.add_parser("session-diagnostics")
    agent_cycle_parser = subparsers.add_parser("agent-cycle")
    agent_cycle_parser.add_argument("--source-limit", default=30, type=int)
    agent_workers_parser = subparsers.add_parser("agent-workers")
    agent_workers_parser.add_argument("--workers", default=3, type=int)
    agent_workers_parser.add_argument("--poll", default=5, type=int)
    agent_worker_parser = subparsers.add_parser("agent-worker")
    agent_worker_parser.add_argument("--worker-id", default="cli-agent")
    agent_worker_parser.add_argument("--poll", default=5, type=int)
    agent_worker_parser.add_argument("--once", action="store_true")
    agent_run_once_parser = subparsers.add_parser("agent-run-once")
    agent_run_once_parser.add_argument("--worker-id", default="cli-agent-once")
    learning_parser = subparsers.add_parser("learn-feedback")
    learning_parser.add_argument("--dry-run", action="store_true")
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", default=8787, type=int)
    serve_parser.add_argument("--reload", action="store_true")

    args = parser.parse_args()

    if args.command == "init-db":
        create_db()
        print("database initialized")
        return

    if args.command == "seed":
        create_db()
        with SessionLocal() as db:
            result = seed_defaults(db)
        print(f"seeded: {result}")
        return

    if args.command == "seed-market":
        create_db()
        with SessionLocal() as db:
            result = seed_market_expansion(db, enabled=not args.disabled)
        print(f"seeded market: {result}")
        return

    if args.command == "seed-community":
        create_db()
        with SessionLocal() as db:
            result = seed_community_sources(db, enabled=not args.disabled)
        print(f"seeded community: {result}")
        return

    if args.command == "seed-signals":
        create_db()
        with SessionLocal() as db:
            result = seed_signal_sources(db, enabled=not args.disabled)
        print(f"seeded signals: {result}")
        return

    if args.command == "seed-sellers":
        create_db()
        with SessionLocal() as db:
            result = seed_seller_sources(db, enabled=not args.disabled)
        print(f"seeded sellers: {result}")
        return

    if args.command == "seed-developer":
        create_db()
        with SessionLocal() as db:
            result = seed_developer_sources(db, enabled=not args.disabled)
        print(f"seeded developer: {result}")
        return

    if args.command == "seed-china":
        create_db()
        with SessionLocal() as db:
            result = seed_china_sources(db, enabled=not args.disabled)
        print(f"seeded china: {result}")
        return

    if args.command == "seed-crossborder":
        create_db()
        with SessionLocal() as db:
            result = seed_crossborder_sources(db, enabled=not args.disabled)
        print(f"seeded crossborder: {result}")
        return

    if args.command == "seed-platform-matrix":
        create_db()
        with SessionLocal() as db:
            result = seed_platform_matrix(db, enabled=not args.disabled)
        print(f"seeded platform matrix: {result}")
        return

    if args.command == "seed-domestic-acquisition":
        create_db()
        with SessionLocal() as db:
            result = seed_domestic_acquisition(db, enabled=not args.disabled)
        print(f"seeded domestic acquisition: {result}")
        return

    if args.command == "seed-rsshub":
        create_db()
        with SessionLocal() as db:
            result = seed_rsshub_sources(db, enabled=not args.disabled)
        print(f"seeded rsshub: {result}")
        return

    if args.command == "run-once":
        create_db()
        with SessionLocal() as db:
            result = run_ingestion_sync(db)
        print(f"ingestion result: {result}")
        return

    if args.command == "run-domestic-acquisition":
        create_db()
        with SessionLocal() as db:
            result = run_domestic_acquisition_sync(db, source_limit=args.limit)
        print(f"domestic acquisition result: {result}")
        return

    if args.command == "refresh-enrichment":
        create_db()
        with SessionLocal() as db:
            result = refresh_existing_mentions(db)
        print(f"refresh result: {result}")
        return

    if args.command == "enrich-contacts":
        create_db()
        with SessionLocal() as db:
            result = apply_contact_enrichment(db)
        print(f"contact enrichment result: {result}")
        return

    if args.command == "contact-report":
        create_db()
        with SessionLocal() as db:
            result = build_contact_enrichment_report(db, limit=args.limit)
        print(f"contact report: {result}")
        return

    if args.command == "dedupe-audit":
        create_db()
        with SessionLocal() as db:
            result = run_dedupe_audit(db, mark_candidates=not args.dry_run)
        print(f"dedupe audit result: {result}")
        return

    if args.command == "audit-compliance":
        create_db()
        with SessionLocal() as db:
            result = run_compliance_audit(db, apply=not args.dry_run)
        print(f"compliance audit result: {result}")
        return

    if args.command == "purge-noise":
        create_db()
        with SessionLocal() as db:
            result = purge_noise_mentions(db)
        print(f"purge result: {result}")
        return

    if args.command == "rebuild-prospects":
        create_db()
        with SessionLocal() as db:
            result = rebuild_prospects(db)
        print(f"prospect rebuild result: {result}")
        return

    if args.command == "rebuild-companies":
        create_db()
        with SessionLocal() as db:
            result = rebuild_companies(db)
        print(f"company rebuild result: {result}")
        return

    if args.command == "rescore-dual-mode":
        create_db()
        with SessionLocal() as db:
            result = rescore_dual_mode(db)
        print(f"dual mode rescore result: {result}")
        return

    if args.command == "p3-quality-audit":
        create_db()
        with SessionLocal() as db:
            result = run_p3_quality_audit(db, limit=args.limit)
        print(f"p3 quality audit result: {result}")
        return

    if args.command == "scan-company-websites":
        create_db()
        with SessionLocal() as db:
            result = scan_company_websites(db, limit=args.limit)
        print(f"company website scan result: {result}")
        return

    if args.command == "enrich-github-companies":
        create_db()
        with SessionLocal() as db:
            result = enrich_github_companies(db, limit=args.limit)
        print(f"github company enrich result: {result}")
        return

    if args.command == "enrich-company-contacts":
        create_db()
        with SessionLocal() as db:
            result = enrich_company_contacts_from_pages(db, limit=args.limit)
        print(f"company contact enrich result: {result}")
        return

    if args.command == "b2b-waterfall":
        create_db()
        with SessionLocal() as db:
            result = run_b2b_waterfall(db, limit=args.limit)
        print(f"b2b waterfall result: {result}")
        return

    if args.command == "b2b-agent-job":
        create_db()
        with SessionLocal() as db:
            job = enqueue_b2b_job(db, args.kind, limit=args.limit)
        print(f"b2b job queued: job_id={job.id}, kind={job.kind}, status={job.status}")
        return

    if args.command == "daily-report":
        create_db()
        with SessionLocal() as db:
            if args.send_wework:
                result = asyncio.run(send_daily_report_wework(db))
                print(f"daily report send result: {result}")
            else:
                print(build_daily_report(db))
        return

    if args.command == "audit-sources":
        create_db()
        with SessionLocal() as db:
            result = audit_all_sources(db, auto_disable=not args.no_disable)
        print(f"source audit result: {result}")
        return

    if args.command == "apply-keywords":
        create_db()
        with SessionLocal() as db:
            result = apply_keyword_suggestions(db, limit=args.limit)
        print(f"keyword apply result: {result}")
        return

    if args.command == "apply-sources":
        create_db()
        with SessionLocal() as db:
            result = apply_source_suggestions(db, limit=args.limit)
        print(f"source apply result: {result}")
        return

    if args.command == "growth-cycle":
        create_db()
        with SessionLocal() as db:
            result = run_growth_cycle(
                db,
                keyword_limit=args.keyword_limit,
                source_limit=args.source_limit,
                run_collect=not args.no_collect,
                auto_disable_sources=args.auto_disable_sources,
            )
        print(f"growth cycle result: {result}")
        return

    if args.command == "session-login":
        result = open_login_session(args.platform)
        print(f"session login result: {result}")
        return

    if args.command == "session-collect":
        create_db()
        task = next((item for item in load_tasks() if item.platform == args.platform), None)
        if task is None:
            print(f"session collect result: no task for platform {args.platform}")
            return
        with SessionLocal() as db:
            result = run_session_collection(db, task, headless=args.headless)
        print(f"session collect result: {result}")
        return

    if args.command == "session-collect-all":
        create_db()
        with SessionLocal() as db:
            result = run_enabled_session_collections(
                db,
                platform_limit=args.platform_limit,
                keyword_limit=args.keyword_limit,
                per_platform_limit=args.per_platform_limit,
                headless=args.headless,
            )
        print(f"session collect all result: {result}")
        return

    if args.command == "session-diagnostics":
        create_db()
        with SessionLocal() as db:
            rows = build_session_platform_diagnostics(db)
        for row in rows:
            print(
                f"{row.platform}\t{row.health}\tlogin={row.login_state}\t"
                f"fetched={row.fetched}\tinserted={row.inserted}\t"
                f"candidates={row.candidates}\trejected={row.rejected}\t"
                f"high_quality={row.high_quality_session}\tfailure={row.failure_code or '-'}\t"
                f"action={row.action}"
            )
        return

    if args.command == "agent-cycle":
        create_db()
        with SessionLocal() as db:
            job = enqueue_practical_domestic_cycle(db, source_limit=args.source_limit)
        print(f"agent cycle queued: job_id={job.id}, kind={job.kind}, status={job.status}")
        return

    if args.command == "agent-workers":
        create_db()
        started = start_worker_processes(count=args.workers, poll_seconds=args.poll)
        print(f"agent workers started: {started}")
        return

    if args.command == "agent-worker":
        create_db()
        run_worker_loop(args.worker_id, poll_seconds=args.poll, once=args.once)
        print(f"agent worker stopped: {args.worker_id}")
        return

    if args.command == "agent-run-once":
        create_db()
        run_worker_loop(args.worker_id, poll_seconds=1, once=True)
        print(f"agent run once stopped: {args.worker_id}")
        return

    if args.command == "learn-feedback":
        create_db()
        with SessionLocal() as db:
            result = run_feedback_learning(db, apply=not args.dry_run)
        print(f"feedback learning result: {result}")
        return

    if args.command == "serve":
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
        return


if __name__ == "__main__":
    main()
