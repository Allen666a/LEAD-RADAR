from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors.github import GitHubSearchCollector
from app.collectors.gitee import GiteeSearchCollector
from app.collectors.html_links import HtmlLinksCollector
from app.collectors.rss import RssCollector
from app.collectors.v2ex import V2exHotCollector, V2exLatestCollector, V2exNodeCollector
from app.models import CandidateItem, Keyword, Mention, Source
from app.schemas import RawItem
from app.services.candidates import (
    classify_collector_failure,
    mark_candidate,
    mark_candidate_detail,
    reclassify_candidate_page_types,
    upsert_candidate,
)
from app.services.crawl_control import (
    apply_source_failure_schedule,
    apply_source_success_schedule,
    should_skip_known_candidate,
    source_cursor_from_items,
    source_run_decision,
)
from app.services.detail_fetcher import DetailFetchResult, fetch_detail_item
from app.services.notify import notify_wework
from app.services.outreach import build_outreach_message
from app.services.p11_quality_gate import audit_existing_mentions_p11, evaluate_raw_item_p11
from app.services.prospects import rebuild_prospects
from app.services.scoring import score_item
from app.services.signals import HIGH_VALUE_SIGNALS
from app.services.source_quality import evaluate_source_quality
from app.services.freshness import freshness_decision
from app.settings import get_settings

SOURCE_COLLECT_TIMEOUT_SECONDS = 35
DETAIL_FETCH_LIMIT_PER_SOURCE = 12
PUBLIC_COLLECT_CONCURRENCY = 8


async def run_ingestion(
    db: Session,
    source_prefixes: tuple[str, ...] = (),
    source_limit: int | None = None,
    force_run: bool = False,
    detail_fetch_limit_per_source: int | None = None,
) -> dict[str, int]:
    keywords = list(
        db.scalars(select(Keyword).where(Keyword.enabled.is_(True)).order_by(Keyword.weight.desc()))
    )
    sources = list(db.scalars(select(Source).where(Source.enabled.is_(True))))
    if source_prefixes:
        sources = [source for source in sources if source.name.startswith(source_prefixes)]
        sources = [source for source in sources if (source.consecutive_failures or 0) == 0]
    sources = sorted(sources, key=domestic_source_priority)
    due_sources = []
    skipped_sources = 0
    if force_run:
        due_sources = sorted(sources, key=volume_source_priority)
    else:
        for source in sources:
            decision = source_run_decision(source)
            if decision.allowed:
                due_sources.append(source)
            else:
                skipped_sources += 1
                source.last_run_reason = decision.reason
        if skipped_sources:
            db.commit()
    sources = due_sources
    if source_limit is not None:
        sources = sources[: max(0, source_limit)]

    source_collectors = build_collectors(sources, keywords)
    detail_fetch_limit = (
        DETAIL_FETCH_LIMIT_PER_SOURCE
        if detail_fetch_limit_per_source is None
        else max(0, detail_fetch_limit_per_source)
    )
    fetched = 0
    inserted = 0
    main_inserted = 0
    review_inserted = 0
    invalid_inserted = 0
    high_intent = 0

    collection_results = await collect_source_results(
        source_collectors,
        concurrency=PUBLIC_COLLECT_CONCURRENCY if force_run else 4,
    )

    for source, raw_items, collect_error in collection_results:
        try:
            if collect_error is not None:
                raise collect_error
            source.last_checked_at = datetime.now()
            source.success_count = (source.success_count or 0) + 1
            source.consecutive_failures = 0
            source.last_error = ""
            source.last_fetched_count = len(raw_items)

            source_inserted = 0
            source_detail_fetches = 0
            source_skipped_known = 0
            for item in raw_items:
                if not item.url or not item.title:
                    continue
                canonical = canonicalize_url(item.url)
                existing_candidate = db.scalar(select(CandidateItem).where(CandidateItem.canonical_url == canonical))
                if should_skip_known_candidate(existing_candidate):
                    source_skipped_known += 1
                    continue
                candidate = upsert_candidate(db, item, canonical)
                detail_item = item
                detail_result = DetailFetchResult("skipped", "source already has enough public evidence")
                if source_detail_fetches < detail_fetch_limit:
                    detail_item, detail_result = await fetch_detail_item(item)
                    if detail_result.status != "skipped":
                        source_detail_fetches += 1
                else:
                    detail_result = DetailFetchResult(
                        "deferred",
                        "detail fetch budget reached for this source run",
                    )
                candidate = upsert_candidate(db, detail_item, canonical)
                mark_candidate_detail(
                    candidate,
                    detail_result.status,
                    detail_result.reason,
                    excerpt=detail_result.content or detail_item.content or "",
                )
                mention = insert_item(db, detail_item, keywords, candidate=candidate)
                if mention is None:
                    continue
                inserted += 1
                source_inserted += 1
                if mention.status == "invalid":
                    invalid_inserted += 1
                elif mention.status == "review":
                    review_inserted += 1
                else:
                    main_inserted += 1
                if (
                    mention.status != "invalid"
                    and mention.score >= get_settings().high_intent_threshold
                    and mention.risk_level != "high"
                ):
                    high_intent += 1
                    await notify_wework(db, mention)

            source.last_inserted_count = source_inserted
            evaluate_source_quality(db, source)
            apply_source_success_schedule(
                source,
                fetched=len(raw_items),
                inserted=source_inserted,
                cursor=source_cursor_from_items(raw_items),
            )
            if source_skipped_known:
                source.last_run_reason = f"{source.last_run_reason}; skipped_known={source_skipped_known}"
            db.commit()
            fetched += len(raw_items)
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or exc.__class__.__name__
            failure_type = classify_collector_failure(exc)
            source.last_checked_at = datetime.now()
            source.failure_count = (source.failure_count or 0) + 1
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.last_error = f"{failure_type}: {message}"[:1000]
            source.last_fetched_count = 0
            source.last_inserted_count = 0
            evaluate_source_quality(db, source)
            apply_source_failure_schedule(source, failure_type, message)
            db.commit()
            print(f"collector failed: {source.name}: {message}")

    page_type_result = reclassify_candidate_page_types(db)
    prospect_result = rebuild_prospects(db)

    return {
        "fetched": fetched,
        "inserted": inserted,
        "main_inserted": main_inserted,
        "review_inserted": review_inserted,
        "invalid_inserted": invalid_inserted,
        "high_intent": high_intent,
        "prospects": prospect_result["prospects"],
        "page_type_reclassified": page_type_result["changed"],
        "sources_skipped": skipped_sources,
    }


def build_collectors(sources: Iterable[Source], keywords: list[Keyword]):
    collectors = []

    for source in sources:
        if source.kind == "rss" and source.url:
            collectors.append((source, RssCollector(source.name, source.url)))
        elif source.kind == "v2ex":
            collectors.append((source, V2exLatestCollector(source.name)))
        elif source.kind == "v2ex_hot":
            collectors.append((source, V2exHotCollector(source.name)))
        elif source.kind == "v2ex_node" and source.url:
            collectors.append((source, V2exNodeCollector(source.url, source.name)))
        elif source.kind == "github_search" and source.url:
            collectors.append((source, GitHubSearchCollector(source.url, source.name)))
        elif source.kind == "gitee_search" and source.url:
            collectors.append((source, GiteeSearchCollector(source.url, source.name)))
        elif source.kind == "html_links" and source.url:
            collectors.append((source, HtmlLinksCollector(source.name, source.url)))

    return collectors


async def collect_source_results(source_collectors, concurrency: int):
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def collect_one(source, collector):
        async with semaphore:
            try:
                raw_items = await asyncio.wait_for(
                    collector.collect(),
                    timeout=SOURCE_COLLECT_TIMEOUT_SECONDS,
                )
                return source, raw_items, None
            except Exception as exc:  # noqa: BLE001
                return source, [], exc

    tasks = [collect_one(source, collector) for source, collector in source_collectors]
    if not tasks:
        return []
    return await asyncio.gather(*tasks)


def insert_item(db: Session, item: RawItem, keywords: list[Keyword], candidate=None) -> Mention | None:
    if not item.url or not item.title:
        mark_candidate(candidate, "rejected", "缺少 URL 或标题。", failure_type="invalid_path")
        return None

    freshness = freshness_decision(
        published_at=item.published_at,
        title=item.title,
        content=item.content,
        url=item.url,
        require_known=True,
    )
    if not freshness.allowed:
        failure_type = "missing_time" if freshness.published_at is None else "old_content"
        mark_candidate(candidate, "rejected", freshness.reason, failure_type=failure_type)
        return None
    if freshness.published_at and item.published_at is None:
        item = RawItem(
            source_name=item.source_name,
            source_kind=item.source_kind,
            title=item.title,
            url=item.url,
            author=item.author,
            content=item.content,
            published_at=freshness.published_at,
        )

    if not has_valid_public_result_path(item):
        mark_candidate(candidate, "rejected", "页面路径不是可用公开结果页。", failure_type="invalid_path")
        return None
    non_detail_reason = detail_evidence_reject_reason(item, candidate)
    if non_detail_reason:
        mark_candidate(candidate, "rejected", non_detail_reason, failure_type="not_detail")
        return None
    cn_gate_reason = chinese_demand_reject_reason(item)
    if cn_gate_reason:
        mark_candidate(candidate, "rejected", cn_gate_reason, failure_type="low_intent")
        return None

    canonical_url = canonicalize_url(item.url)
    exists = db.scalar(select(Mention.id).where(Mention.canonical_url == canonical_url))
    if exists is not None:
        mark_candidate(candidate, "duplicate", "线索池已存在同一 canonical URL。", mention_id=exists, failure_type="duplicate")
        return None

    result = score_item(item, keywords)
    if result.score <= 0:
        p11 = evaluate_raw_item_p11(item)
        if should_keep_for_review(p11):
            mention = create_mention_from_decision(db, item, result, p11, status="review")
            mark_candidate(
                candidate,
                "review",
                "低分但命中复核规则，进入待复核。",
                mention_id=mention.id if mention else None,
                score=mention.score if mention else 0,
                signal_type=mention.signal_type if mention else "",
                failure_type="review_required",
            )
            return mention
        mark_candidate(candidate, "rejected", "未命中有效购买意图或业务痛点。", failure_type="low_intent")
        return None
    p11 = evaluate_raw_item_p11(item)
    if not p11.allowed:
        mention_status = status_for_rejected_decision(p11)
        mention = create_mention_from_decision(db, item, result, p11, status=mention_status)
        candidate_status = "review" if mention_status == "review" else "rejected"
        mark_candidate(
            candidate,
            candidate_status,
            p11_candidate_reason(p11),
            mention_id=mention.id if mention else None,
            score=mention.score if mention else result.score,
            signal_type=mention.signal_type if mention else result.signal_type,
            failure_type="review_required" if candidate_status == "review" else "quality_rejected",
        )
        return mention
    if not accepts_public_intent_item(item, result.score, result.signal_type):
        mention = create_mention_from_decision(
            db,
            item,
            result,
            p11,
            status="review",
            recommendation_prefix="待复核：未通过公开意图闸门，可能是弱需求或上下文不足。",
        )
        mark_candidate(
            candidate,
            "review",
            "未通过公开意图门槛，进入待复核。",
            mention_id=mention.id if mention else None,
            score=mention.score if mention else result.score,
            signal_type=mention.signal_type if mention else result.signal_type,
            failure_type="review_required",
        )
        return mention
    detail_block_reason = detail_evidence_review_reason(item, candidate)
    if detail_block_reason:
        mention = create_mention_from_decision(
            db,
            item,
            result,
            p11,
            status="review",
            recommendation_prefix=f"待复核：{detail_block_reason}",
        )
        mark_candidate(
            candidate,
            "review",
            detail_block_reason,
            mention_id=mention.id if mention else None,
            score=mention.score if mention else result.score,
            signal_type=mention.signal_type if mention else result.signal_type,
            failure_type="review_required",
        )
        return mention
    final_score = max(result.score, p11.score)
    main_allowed, main_reason = qualifies_main_pool(p11, result.signal_type, final_score)
    if not main_allowed:
        mention = create_mention_from_decision(
            db,
            item,
            result,
            p11,
            status="review",
            recommendation_prefix=f"待复核：{main_reason}",
        )
        mark_candidate(
            candidate,
            "review",
            main_reason,
            mention_id=mention.id if mention else None,
            score=mention.score if mention else final_score,
            signal_type=mention.signal_type if mention else result.signal_type,
            failure_type="review_required",
        )
        return mention

    mention = build_mention(
        item,
        result,
        p11,
        score=final_score,
        status="new",
    )

    db.add(mention)
    try:
        db.commit()
        db.refresh(mention)
        mark_candidate(
            candidate,
            "accepted",
            "通过时效、场景、痛点和质量门槛，进入线索池。",
            mention_id=mention.id,
            score=mention.score,
            signal_type=mention.signal_type,
        )
        db.commit()
        return mention
    except IntegrityError:
        db.rollback()
        mark_candidate(candidate, "duplicate", "写入线索池时发现重复。", failure_type="duplicate")
        return None


def create_mention_from_decision(
    db: Session,
    item: RawItem,
    result,
    p11,
    *,
    status: str,
    recommendation_prefix: str = "",
) -> Mention | None:
    final_score = max(result.score or 0, p11.score or 0)
    mention = build_mention(
        item,
        result,
        p11,
        score=final_score,
        status=status,
        recommendation_prefix=recommendation_prefix,
    )
    db.add(mention)
    try:
        db.commit()
        db.refresh(mention)
        return mention
    except IntegrityError:
        db.rollback()
        return None


def build_mention(
    item: RawItem,
    result,
    p11,
    *,
    score: int,
    status: str,
    recommendation_prefix: str = "",
) -> Mention:
    recommendation = p11.next_action
    if recommendation_prefix:
        recommendation = f"{recommendation_prefix}\n{recommendation}"
    risk_level = result.risk_level
    if status == "review" and risk_level == "normal":
        risk_level = "review"
    return Mention(
        source_name=item.source_name,
        source_kind=item.source_kind,
        title=item.title[:1000],
        canonical_url=canonicalize_url(item.url),
        author=item.author[:160],
        content=item.content[:5000],
        matched_keywords=", ".join(result.matched_keywords),
        score=score,
        signal_type=result.signal_type,
        status=status,
        risk_level=risk_level,
        recommendation=recommendation,
        score_reasons="\n".join(result.reasons + ["", p11.explanation]),
        outreach_message=build_outreach_message(item, result.matched_keywords, score),
        fit_score=80 if p11.tier == "A" else 65 if p11.tier == "B" else 45,
        intent_score=80 if "buyer_intent" in p11.signal_tags else 65 if "pain" in p11.signal_tags else 45,
        priority_score=score,
        published_at=item.published_at,
    )


def should_keep_for_review(p11) -> bool:
    if p11.allowed:
        return True
    if p11.score < 30:
        return False
    return status_for_rejected_decision(p11) == "review"


def p11_candidate_reason(p11) -> str:
    reasons = getattr(p11, "reject_reasons", None) or []
    if reasons:
        return "；".join(reasons[:5])
    return getattr(p11, "explanation", "") or "P11 质量闸门未通过。"


def status_for_rejected_decision(p11) -> str:
    text = "\n".join(p11.reject_reasons).lower()
    if should_review_adjacent_crossborder_pain(p11, text):
        return "review"
    hard_invalid_terms = (
        "违规",
        "同行/服务商软文",
        "工程任务",
        "教程/新闻",
        "招聘",
        "旧线索",
        "早于",
        "原文时间",
        "不满足",
        "时效",
        "静态/固定",
        "vpn",
        "低质量",
        "缺少动态住宅",
        "未直接命中动态住宅",
        "缺少痛点",
        "未命中个人",
        "未同时命中",
    )
    if any(term in text for term in hard_invalid_terms):
        return "invalid"
    return "review"


def should_review_adjacent_crossborder_pain(p11, reject_text: str) -> bool:
    tags = set(p11.signal_tags or [])
    adjacent_personas = {
        "tiktok_matrix",
        "amazon_multi_account",
        "shopee_lazada_shein",
        "shopify_independent",
        "social_matrix",
        "account_service",
    }
    if p11.score < 38:
        return False
    if "fresh_2026" not in tags:
        return False
    if p11.persona_key not in adjacent_personas:
        return False
    if not ({"pain", "buyer_intent", "scenario"} & tags):
        return False
    if "未直接命中动态住宅" not in reject_text and "缺少动态住宅" not in reject_text:
        return False
    hard_blocks = ("教程/新闻", "同行/服务商软文", "工程任务", "违规", "旧线索", "时效")
    return not any(term in reject_text for term in hard_blocks)


PUBLIC_INTENT_PREFIXES = (
    "Zhihu Intent:",
    "Zhihu Search:",
    "Baidu Tieba Intent:",
    "Baidu Tieba Search:",
    "V2EX Intent:",
    "V2EX Tag:",
    "V2EX Latest",
    "V2EX Hot",
    "V2EX Node:",
    "SegmentFault Intent:",
    "SegmentFault Search:",
    "LearnKu Intent:",
    "LearnKu Search:",
    "Gitee Intent:",
    "Gitee Issues:",
    "CSDN Ask Intent:",
    "CSDN Search Intent:",
    "OSChina Intent:",
    "CNBlogs Intent:",
    "WeAreSellers Intent:",
    "WeAreSellers:",
    "P34 WeAreSellers Intent:",
    "P34 Zhihu Intent:",
    "P34 Tieba Intent:",
    "FOB Shanghai:",
    "Amazon Seller Forum CN:",
    "P30 Bing Search:",
    "P30 GitHub Issues:",
    "P30 Gitee Issues:",
)


PUBLIC_STRONG_TITLE_TERMS = (
    "怎么办",
    "怎么解决",
    "求推荐",
    "请教",
    "有没有",
    "哪里",
    "被封",
    "封号",
    "关联",
    "防关联",
    "不稳定",
    "403",
    "429",
    "cloudflare",
    "验证码",
    "指纹浏览器",
    "代理",
    "代理ip",
    "代理 ip",
    "住宅ip",
    "住宅 ip",
    "ip关联",
    "ip 关联",
    "ip被封",
    "ip 被封",
    "多账号",
    "店群",
    "矩阵",
    "账号一登录就验证",
    "登录环境",
    "环境异常",
    "店铺登录",
    "店铺关联",
    "5 秒盾",
    "请求太频繁",
    "过不去",
    "身份验证",
    "adsPower".lower(),
    "比特浏览器",
    "候鸟浏览器",
)

PUBLIC_SCENE_TERMS = (
    "代理",
    "代理ip",
    "代理 ip",
    "住宅ip",
    "住宅 ip",
    "ip关联",
    "ip 关联",
    "ip被封",
    "ip 被封",
    "指纹浏览器",
    "爬虫",
    "403",
    "429",
    "cloudflare",
    "验证码",
    "防关联",
    "关联",
    "多账号",
    "店群",
    "矩阵",
    "养号",
    "账号一登录就验证",
    "登录环境",
    "环境异常",
    "店铺登录",
    "店铺关联",
    "5 秒盾",
    "请求太频繁",
    "adsPower".lower(),
    "比特浏览器",
    "候鸟浏览器",
    "amazon",
    "亚马逊",
    "tiktok",
    "shopify",
)

BROAD_PUBLIC_PREFIXES = ("V2EX Latest", "V2EX Hot")

PUBLIC_CONTENT_NOISE_TERMS = (
    "教程",
    "指南",
    "干货",
    "全覆盖",
    "入门",
    "小白",
    "从零",
    "从 0",
    "分享发现",
    "魔改版",
    "mod apk",
    "完整教程",
    "保姆级",
    "实战教程",
    "新手教程",
    "api key",
    "apikey",
    "deepseek",
    "招聘",
    "岗位",
    "工程师招聘",
    "远程岗位",
    "ai 陪伴",
    "大模型",
    "服务器配置",
    "主机配置",
    "epyc",
    "all in one",
    "为什么写爬虫",
    "学习爬虫",
    "github page",
    "baidu蜘蛛",
)

PUBLIC_COMPETITOR_PROMO_TERMS = (
    "kookeey",
    "922s5",
    "bright data",
    "oxylabs",
    "smartproxy",
    "novproxy",
    "1024proxy",
    "ipidea",
    "底价",
    "免费测试",
    "一级代理",
    "优惠",
    "官网",
    "测评",
    "排行榜",
    "哪家好",
)


def accepts_public_intent_item(item: RawItem, score: int, signal_type: str) -> bool:
    if not item.source_name.startswith(PUBLIC_INTENT_PREFIXES):
        return True
    title_context = f"{item.title}\n{item.content}".lower()
    match_text = item.title.lower() if item.source_name.startswith(BROAD_PUBLIC_PREFIXES) else title_context
    if any(term.lower() in title_context for term in PUBLIC_COMPETITOR_PROMO_TERMS):
        return False
    if any(term.lower() in title_context for term in PUBLIC_CONTENT_NOISE_TERMS):
        return False
    has_scene_term = any(term.lower() in match_text for term in PUBLIC_SCENE_TERMS)
    has_strong_term = any(term.lower() in match_text for term in PUBLIC_STRONG_TITLE_TERMS)
    if not has_scene_term or not has_strong_term:
        return False
    if score < 40:
        return False
    if signal_type in HIGH_VALUE_SIGNALS:
        return True
    if signal_type == "risk_signal" and score >= 60:
        return True
    return False


CN_DEMAND_SOURCE_PREFIXES = (
    "Zhihu Intent:",
    "Baidu Tieba Intent:",
    "WeAreSellers Intent:",
    "P34 WeAreSellers Intent:",
    "SegmentFault Intent:",
    "LearnKu Intent:",
    "CSDN Search Intent:",
    "Gitee Intent:",
    "V2EX Intent:",
)

CN_IP_CONTEXT_TERMS = (
    "代理",
    "住宅",
    "动态住宅",
    "住宅ip",
    "住宅代理",
    "指纹浏览器",
    "adspower",
    "比特浏览器",
    "候鸟浏览器",
    "hubstudio",
    "登录环境",
    "网络环境",
    "环境异常",
    "封号",
    "被封",
    "验证码",
    "cloudflare",
    "403",
    "429",
    "爬虫",
)

CN_STRONG_IP_CONTEXT_TERMS = (
    "ip",
    "代理",
    "住宅",
    "动态住宅",
    "住宅ip",
    "住宅代理",
    "指纹浏览器",
    "adspower",
    "比特浏览器",
    "候鸟浏览器",
    "hubstudio",
    "登录环境",
    "网络环境",
    "环境异常",
    "cloudflare",
    "403",
    "429",
    "爬虫",
)

CN_SCENARIO_TERMS = (
    "tiktok",
    "小店",
    "本土店",
    "矩阵",
    "养号",
    "亚马逊",
    "amazon",
    "店群",
    "多店铺",
    "多账号",
    "铺货",
    "shopee",
    "lazada",
    "shopify",
    "独立站",
    "facebook",
    "instagram",
    "海外账号",
    "账号注册",
    "数据采集",
)

CN_GENERIC_SELLER_NOISE = (
    "广告",
    "选品",
    "类目",
    "上架",
    "listing",
    "侵权",
    "专利",
    "营业执照",
    "后台地址",
    "信用卡地址",
    "库存",
    "fba",
    "绩效",
)


def chinese_demand_reject_reason(item: RawItem) -> str:
    if not item.source_name.startswith(CN_DEMAND_SOURCE_PREFIXES):
        return ""
    source_text = (item.source_name or "").lower()
    title_text = (item.title or "").lower()
    body_text = f"{item.title}\n{item.content}".lower()
    has_ip_context = any(term.lower() in body_text for term in CN_IP_CONTEXT_TERMS)
    has_strong_ip_context = any(term.lower() in title_text for term in CN_STRONG_IP_CONTEXT_TERMS)
    has_scenario = any(term.lower() in body_text for term in CN_SCENARIO_TERMS) or any(
        term.lower() in source_text for term in CN_SCENARIO_TERMS
    )
    if item.source_name.startswith(("WeAreSellers Intent:", "P34 WeAreSellers Intent:")) and not has_strong_ip_context:
        return "中文卖家帖缺少强 IP/代理/住宅/指纹浏览器/登录环境证据。"
    if has_ip_context and has_scenario:
        return ""
    if item.source_name.startswith(("WeAreSellers Intent:", "P34 WeAreSellers Intent:")):
        if any(term.lower() in body_text for term in CN_GENERIC_SELLER_NOISE):
            return "中文卖家帖缺少 IP/代理/登录环境/防关联证据，像普通运营问题。"
    return "中文需求圈命中不足：需要同时出现业务场景和 IP/代理/环境/防关联痛点。"


def qualifies_main_pool(p11, signal_type: str, score: int) -> tuple[bool, str]:
    tags = set(p11.signal_tags or [])
    reject_tags = {
        "content_noise",
        "supplier_ad",
        "github_engineering_noise",
        "generic_page",
        "low_fit",
        "illegal_risk",
    }
    if tags & reject_tags:
        return False, "含教程、广告、工程噪音、泛列表页或低匹配标签。"
    if "fresh_2026" not in tags:
        return False, "缺少 2026 年有效发布时间。"
    has_need = "dynamic_residential" in tags or (
        "proxy_scenario" in tags and "scenario" in tags and p11.persona_key != "unknown"
    )
    if not has_need:
        return False, "缺少动态住宅 IP 或明确代理/IP 场景证据。"
    has_actionable = bool({"pain", "buyer_intent"} & tags)
    if not has_actionable:
        return False, "缺少痛点、求推荐、采购或换供应商信号。"
    if signal_type == "risk_signal":
        return False, "风险类信号需要人工先判断合规和真实需求。"
    if p11.tier == "A" and signal_type in HIGH_VALUE_SIGNALS and score >= 75:
        return True, "A 级高价值线索。"
    if (
        p11.tier == "B"
        and "dynamic_residential" in tags
        and {"pain", "buyer_intent"} <= tags
        and signal_type in HIGH_VALUE_SIGNALS
        and score >= 78
    ):
        return True, "B 级但同时命中动态住宅、痛点和购买信号。"
    return False, "证据不足以直接进入主池，先人工复核。"


def detail_evidence_review_reason(item: RawItem, candidate) -> str:
    if item.source_kind != "html_links" or candidate is None:
        return ""
    detail_status = getattr(candidate, "detail_status", "") or ""
    if detail_status in {"ok", "skipped"}:
        return ""
    if detail_status == "blocked":
        return "详情页被平台拦截，只有搜索摘要证据。"
    if detail_status == "failed":
        return "详情页正文或发布时间读取失败。"
    if detail_status == "deferred":
        return "本轮详情页读取达到上限。"
    if detail_status == "not_checked":
        return "详情页尚未校验。"
    return ""


def detail_evidence_reject_reason(item: RawItem, candidate) -> str:
    if item.source_kind != "html_links" or candidate is None:
        return ""
    detail_status = getattr(candidate, "detail_status", "") or ""
    if detail_status == "not_detail":
        return getattr(candidate, "detail_reason", "") or "不是具体需求详情页。"
    return ""


def has_valid_public_result_path(item: RawItem) -> bool:
    parsed = urlparse(item.url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host.endswith("v2ex.com"):
        return path.startswith("/t/")
    if host.endswith("segmentfault.com"):
        return path.startswith("/q/")
    return True


def run_ingestion_sync(db: Session) -> dict[str, int]:
    return asyncio.run(run_ingestion(db))


def run_domestic_acquisition_sync(
    db: Session,
    source_limit: int | None = None,
    force_run: bool = False,
    detail_fetch_limit_per_source: int | None = None,
) -> dict[str, int]:
    return asyncio.run(
        run_ingestion(
            db,
            source_prefixes=(
                "Zhihu Search:",
                "Zhihu Intent:",
                "Baidu Tieba Search:",
                "Baidu Tieba Intent:",
                "V2EX Tag:",
                "V2EX Intent:",
                "SegmentFault Search:",
                "SegmentFault Intent:",
                "LearnKu Search:",
                "LearnKu Intent:",
                "Gitee Issues:",
                "Gitee Intent:",
                "GitHub Issues:",
                "CSDN Search Intent:",
                "OSChina Intent:",
                "CNBlogs Intent:",
                "FOB Shanghai:",
                "WeAreSellers Search:",
                "WeAreSellers:",
                "WeAreSellers Intent:",
                "Amazon Seller Forum CN Search:",
                "Amazon Seller Forum CN:",
                "AMZ123:",
                "Yuguo:",
                "SellerHome:",
                "Ennews:",
                "IKJZD:",
                "Ebrun:",
                "Egainnews:",
                "Shopify Community Search:",
                "Shopify Community:",
                "eBay Community:",
                "Etsy Community:",
                "Walmart Seller:",
                "Shopee Seller:",
                "Lazada Seller:",
                "BlackHatWorld Search:",
                "BlackHatWorld:",
                "Reddit Search:",
                "Reddit:",
                "WarriorForum Search:",
                "WarriorForum:",
                "StackOverflow Search:",
                "StackOverflow:",
                "Scrapy:",
                "Playwright:",
                "Puppeteer:",
                "Apify",
                "AdsPower:",
                "GoLogin:",
                "Dolphin Anty:",
                "Multilogin:",
                "Octo Browser:",
                "BitBrowser:",
                "Hubstudio:",
                "P30 Bing Search:",
                "P30 GitHub Issues:",
                "P30 Gitee Issues:",
                "P33 GitHub Issues:",
                "P33 Gitee Issues:",
                "P34 WeAreSellers Intent:",
                "P34 Zhihu Intent:",
                "P34 Tieba Intent:",
            ),
            source_limit=source_limit,
            force_run=force_run,
            detail_fetch_limit_per_source=detail_fetch_limit_per_source,
        )
    )


def domestic_source_priority(source: Source) -> tuple[int, int, int, str]:
    priorities = [
        ("Zhihu Intent:", 0),
        ("Baidu Tieba Intent:", 1),
        ("WeAreSellers Intent:", 2),
        ("P34 WeAreSellers Intent:", 2),
        ("SegmentFault Intent:", 3),
        ("V2EX Intent:", 4),
        ("V2EX Tag:", 4),
        ("LearnKu Intent:", 5),
        ("CSDN Search Intent:", 6),
        ("Gitee Intent:", 7),
        ("P34 Zhihu Intent:", 7),
        ("P34 Tieba Intent:", 7),
        ("SegmentFault Search:", 8),
        ("LearnKu Search:", 8),
        ("Baidu Tieba Search:", 8),
        ("Gitee Issues:", 9),
        ("GitHub Issues:", 12),
        ("OSChina Intent:", 10),
        ("CNBlogs Intent:", 11),
        ("WeAreSellers Search:", 4),
        ("WeAreSellers:", 4),
        ("FOB Shanghai:", 6),
        ("Amazon Seller Forum CN Search:", 6),
        ("Amazon Seller Forum CN:", 7),
        ("AMZ123:", 13),
        ("Yuguo:", 13),
        ("SellerHome:", 6),
        ("Ennews:", 8),
        ("IKJZD:", 6),
        ("Ebrun:", 9),
        ("Egainnews:", 9),
        ("Shopify Community Search:", 6),
        ("Shopify Community:", 6),
        ("eBay Community:", 7),
        ("Etsy Community:", 7),
        ("Walmart Seller:", 7),
        ("Shopee Seller:", 7),
        ("Lazada Seller:", 7),
        ("BlackHatWorld Search:", 8),
        ("BlackHatWorld:", 8),
        ("Reddit Search:", 8),
        ("Reddit:", 8),
        ("WarriorForum Search:", 10),
        ("WarriorForum:", 10),
        ("StackOverflow Search:", 9),
        ("StackOverflow:", 9),
        ("Scrapy:", 9),
        ("Playwright:", 9),
        ("Puppeteer:", 9),
        ("Apify", 9),
        ("AdsPower:", 8),
        ("GoLogin:", 8),
        ("Dolphin Anty:", 8),
        ("Multilogin:", 8),
        ("Octo Browser:", 8),
        ("BitBrowser:", 8),
        ("Hubstudio:", 8),
        ("P30 Bing Search:", 6),
        ("P30 GitHub Issues:", 12),
        ("P30 Gitee Issues:", 6),
        ("P33 GitHub Issues:", 12),
        ("P33 Gitee Issues:", 4),
        ("Zhihu Search:", 13),
    ]
    for prefix, priority in priorities:
        if source.name.startswith(prefix):
            learned = 100 - (source.learned_priority or source.quality_score or 50)
            quality = 100 - (source.quality_score or 50)
            return (priority, learned, quality, source.name)
    learned = 100 - (source.learned_priority or source.quality_score or 50)
    quality = 100 - (source.quality_score or 50)
    return (99, learned, quality, source.name)


def volume_source_priority(source: Source) -> tuple[int, int, int, int, str]:
    fetched = source.last_fetched_count or 0
    inserted = source.last_inserted_count or 0
    quality = source.quality_status or "unchecked"
    if inserted > 0:
        bucket = 0
    elif fetched > 0:
        bucket = 1
    elif quality in {"excellent", "good"}:
        bucket = 2
    elif quality == "unchecked":
        bucket = 3
    elif quality == "low_yield":
        bucket = 5
    else:
        bucket = 4
    return (bucket, -inserted, -fetched, -(source.success_count or 0), source.name)


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or parsed.path
    if parsed.netloc.endswith("v2ex.com") and path.startswith("/t/"):
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    if parsed.netloc.endswith("tieba.baidu.com") and path.startswith("/p/"):
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def refresh_existing_mentions(db: Session) -> dict[str, int]:
    keywords = list(
        db.scalars(select(Keyword).where(Keyword.enabled.is_(True)).order_by(Keyword.weight.desc()))
    )
    mentions = list(db.scalars(select(Mention)))
    refreshed = 0

    for mention in mentions:
        item = RawItem(
            source_name=mention.source_name,
            source_kind=mention.source_kind,
            title=mention.title,
            url=mention.canonical_url,
            author=mention.author,
            content=mention.content,
            published_at=mention.published_at,
        )
        result = score_item(item, keywords)
        if result.score <= 0:
            continue

        mention.score = result.score
        mention.signal_type = result.signal_type
        mention.matched_keywords = ", ".join(result.matched_keywords)
        mention.risk_level = result.risk_level
        mention.recommendation = result.recommendation
        mention.score_reasons = "\n".join(result.reasons)
        mention.outreach_message = build_outreach_message(item, result.matched_keywords, result.score)
        refreshed += 1

    db.commit()
    p11_result = audit_existing_mentions_p11(db)
    return {"refreshed": refreshed, "p11_invalidated": p11_result["invalidated"], "p11_high_quality": p11_result["high_quality"]}


def purge_noise_mentions(db: Session) -> dict[str, int]:
    keywords = list(
        db.scalars(select(Keyword).where(Keyword.enabled.is_(True)).order_by(Keyword.weight.desc()))
    )
    mentions = list(db.scalars(select(Mention)))
    deleted = 0
    seen_urls: set[str] = set()

    for mention in mentions:
        normalized_url = canonicalize_url(mention.canonical_url)
        if normalized_url in seen_urls:
            db.delete(mention)
            deleted += 1
            continue
        seen_urls.add(normalized_url)

        item = RawItem(
            source_name=mention.source_name,
            source_kind=mention.source_kind,
            title=mention.title,
            url=mention.canonical_url,
            author=mention.author,
            content=mention.content,
            published_at=mention.published_at,
        )
        result = score_item(item, keywords)
        p11 = evaluate_raw_item_p11(item)
        invalid_reasons = [
            result.score <= 0 and not should_keep_for_review(p11),
            status_for_rejected_decision(p11) == "invalid" and not p11.allowed,
            is_stale_mention(mention),
            not has_valid_public_result_path(item),
            is_rejected_session_mention(mention),
            is_weak_html_title(mention),
            mention.source_name.startswith("GitHub Search:"),
            mention.source_name.startswith("Bing Search:"),
        ]
        review_reasons = [
            result.score <= 0 and should_keep_for_review(p11),
            not p11.allowed and status_for_rejected_decision(p11) == "review",
            p11.allowed and not accepts_public_intent_item(item, result.score, result.signal_type),
        ]
        if any(invalid_reasons):
            mention.status = "invalid"
            mention.score = min(mention.score or 0, max(0, p11.score or 0, result.score or 0))
            mention.priority_score = mention.score
            mention.recommendation = p11.next_action
            mention.score_reasons = "\n".join(result.reasons + ["", p11.explanation])
            deleted += 1
        elif any(review_reasons):
            final_score = max(result.score or 0, p11.score or 0)
            mention.status = "review"
            mention.score = final_score
            mention.priority_score = final_score
            mention.signal_type = result.signal_type
            mention.risk_level = "review" if mention.risk_level == "normal" else mention.risk_level
            mention.recommendation = p11.next_action
            mention.score_reasons = "\n".join(result.reasons + ["", p11.explanation])
        else:
            final_score = max(result.score, p11.score)
            if mention.status == "invalid":
                mention.status = "review" if p11.reject_reasons else "new"
            mention.score = final_score
            mention.priority_score = final_score
            mention.signal_type = result.signal_type
            mention.recommendation = p11.next_action
            mention.score_reasons = "\n".join(result.reasons + ["", p11.explanation])

    db.commit()
    prospect_result = rebuild_prospects(db)
    return {"deleted": deleted, "prospects": prospect_result["prospects"]}


def is_rejected_session_mention(mention: Mention) -> bool:
    if not mention.source_name.startswith("Session "):
        return False
    text = f"{mention.content}\n{mention.score_reasons}".lower()
    return "质量层级: 剔除" in text or "剔除" in text


def is_stale_mention(mention: Mention) -> bool:
    decision = freshness_decision(
        published_at=mention.published_at,
        title=mention.title,
        content=mention.content,
        url=mention.canonical_url,
        require_known=True,
    )
    return not decision.allowed


def is_weak_html_title(mention: Mention) -> bool:
    title = mention.title.strip()
    if mention.source_kind != "html_links" or len(title) > 18:
        return False
    return all(char.isascii() and (char.isalnum() or char in "_-.") for char in title)
