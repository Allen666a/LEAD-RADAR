from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ContactRecord, Mention, Prospect
from app.settings import get_settings
from app.services.contact_status import has_real_contact
from app.services.contacts import ContactSignals, extract_contacts, merge_contact_notes


@dataclass(frozen=True)
class ContactEnrichmentRow:
    prospect_id: int
    identity_key: str
    display_name: str
    confidence: int
    quality: str
    enriched_fields: list[str]


@dataclass(frozen=True)
class PublicContactEnrichmentResult:
    scanned: int
    fetched_pages: int
    searched: int
    enriched: int
    contacts_created: int
    skipped_contactable: int
    failed: int
    no_public_url: int
    low_confidence: int
    samples: list[dict[str, object]]
    failure_breakdown: dict[str, int]


@dataclass(frozen=True)
class ContactWaterfallStep:
    step: str
    status: str
    source: str
    reason: str
    confidence: int = 0


def apply_contact_enrichment(db: Session, min_confidence: int = 35) -> dict[str, object]:
    prospects = list(db.scalars(select(Prospect).order_by(desc(Prospect.lead_score))))
    rows: list[ContactEnrichmentRow] = []
    scanned = 0
    enriched = 0
    already_contactable = 0
    low_confidence = 0
    missing = 0
    cleaned = 0

    for prospect in prospects:
        scanned += 1
        cleaned += prune_untrusted_existing_contacts(prospect)
        if has_real_contact(prospect):
            already_contactable += 1

        signals = extract_contacts(build_contact_haystack(db, prospect))
        if not signals.has_any_signal:
            missing += 1
            continue
        if signals.confidence_score < min_confidence:
            low_confidence += 1
            continue

        changed_fields = fill_empty_contact_fields(prospect, signals, min_confidence=min_confidence)
        if changed_fields:
            enriched += 1
            prospect.updated_at = datetime.now()
            rows.append(
                ContactEnrichmentRow(
                    prospect_id=prospect.id,
                    identity_key=prospect.identity_key,
                    display_name=prospect.display_name,
                    confidence=signals.confidence_score,
                    quality=signals.quality_label,
                    enriched_fields=changed_fields,
                )
            )

    db.commit()
    return {
        "scanned": scanned,
        "enriched": enriched,
        "already_contactable": already_contactable,
        "low_confidence": low_confidence,
        "missing": missing,
        "cleaned": cleaned,
        "sample": [
            {
                "prospect_id": row.prospect_id,
                "name": row.display_name,
                "confidence": row.confidence,
                "quality": row.quality,
                "fields": row.enriched_fields,
            }
            for row in rows[:20]
        ],
    }


def enrich_missing_contacts_from_public_pages(
    db: Session,
    prospect_ids: list[int] | None = None,
    limit: int = 12,
    min_confidence: int = 35,
    use_search: bool = True,
) -> PublicContactEnrichmentResult:
    query = (
        select(Prospect)
        .where(Prospect.status.notin_(["won", "invalid"]))
        .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
    )
    if prospect_ids:
        query = query.where(Prospect.id.in_(prospect_ids))
    prospects = list(db.scalars(query.limit(max(1, min(80, limit * 4)))))

    scanned = 0
    fetched_pages = 0
    searched = 0
    enriched = 0
    contacts_created = 0
    skipped_contactable = 0
    failed = 0
    no_public_url = 0
    low_confidence = 0
    failure_breakdown: dict[str, int] = {}
    samples: list[dict[str, object]] = []

    for prospect in prospects:
        if scanned >= limit:
            break
        if has_real_contact(prospect):
            skipped_contactable += 1
            continue

        urls = candidate_public_urls(db, prospect)
        steps: list[ContactWaterfallStep] = []
        if not urls:
            no_public_url += 1
            add_failure(failure_breakdown, "no_public_url")
            prospect.follow_up_note = merge_contact_notes(
                prospect.follow_up_note or "",
                build_waterfall_note(
                    [
                        ContactWaterfallStep(
                            "公开入口",
                            "failed",
                            "",
                            "没有可读取的公开主页、作者主页或原文 URL。",
                        )
                    ]
                ),
            )
            continue

        scanned += 1
        trusted_parts = [build_contact_haystack(db, prospect)]
        search_parts: list[str] = []
        page_notes: list[str] = []
        page_errors: list[str] = []
        for url in urls[:3]:
            api_profile = fetch_platform_profile_api_text(url)
            skip_raw_profile_page = False
            if api_profile["ok"]:
                api_text = str(api_profile["text"])
                fetched_pages += 1
                trusted_parts.append(api_text)
                skip_raw_profile_page = bool(api_profile.get("profile_only"))
                page_notes.append(f"平台公开资料补全: {api_profile['source']}")
                steps.append(ContactWaterfallStep("平台公开资料", "ok", str(api_profile["source"]), "已读取作者公开资料/API。"))
                for website in platform_profile_websites(api_profile).copy()[:2]:
                    if website not in urls and is_fetchable_public_url(website):
                        website_page = fetch_public_text(website)
                        if website_page["ok"]:
                            fetched_pages += 1
                            trusted_parts.append(str(website_page["text"]))
                            page_notes.append(f"作者外部网站补全: {website}")
                            steps.append(ContactWaterfallStep("作者外部网站", "ok", website, "已读取作者公开外部网站。"))
                        else:
                            error = str(website_page.get("error", ""))
                            page_errors.append(f"{website}: {error}")
                            add_failure(failure_breakdown, classify_fetch_error(error))
                            steps.append(ContactWaterfallStep("作者外部网站", "failed", website, error or "读取失败。"))
            elif api_profile.get("supported"):
                error = str(api_profile.get("error", ""))
                page_errors.append(f"{api_profile.get('source', url)}: {error}")
                add_failure(failure_breakdown, classify_fetch_error(error))
                steps.append(ContactWaterfallStep("平台公开资料", "failed", str(api_profile.get("source", url)), error or "读取失败。"))

            if skip_raw_profile_page:
                continue
            page = fetch_public_text(url)
            if page["ok"]:
                fetched_pages += 1
                trusted_parts.append(str(page["text"]))
                page_notes.append(f"公开页面补全: {url}")
                steps.append(ContactWaterfallStep("公开页面", "ok", url, "已读取公开页面。"))
                profile_url = extract_profile_url_from_page(url, str(page["text"]))
                if profile_url and profile_url not in urls and is_fetchable_public_url(profile_url):
                    profile_page = fetch_public_text(profile_url)
                    if profile_page["ok"]:
                        fetched_pages += 1
                        trusted_parts.append(str(profile_page["text"]))
                        page_notes.append(f"作者主页补全: {profile_url}")
                        steps.append(ContactWaterfallStep("作者主页", "ok", profile_url, "已读取作者主页。"))
                    else:
                        failed += 1
                        error = str(profile_page.get("error", ""))
                        page_errors.append(f"{profile_url}: {error}")
                        add_failure(failure_breakdown, classify_fetch_error(error))
                        steps.append(ContactWaterfallStep("作者主页", "failed", profile_url, error or "读取失败。"))
            else:
                failed += 1
                error = str(page.get("error", ""))
                page_errors.append(f"{url}: {error}")
                add_failure(failure_breakdown, classify_fetch_error(error))
                steps.append(ContactWaterfallStep("公开页面", "failed", url, error or "读取失败。"))

        if use_search:
            for query in build_contact_search_queries(prospect, db)[:3]:
                search = fetch_search_result_text(query)
                if search["ok"]:
                    searched += 1
                    search_parts.append(str(search["text"]))
                    page_notes.append(f"搜索补全: {query}")
                    steps.append(ContactWaterfallStep("公开搜索", "ok", query, "已读取搜索结果摘要。"))
                else:
                    failed += 1
                    error = str(search.get("error", ""))
                    page_errors.append(f"{query}: {error}")
                    add_failure(failure_breakdown, classify_fetch_error(error))
                    steps.append(ContactWaterfallStep("公开搜索", "failed", query, error or "读取失败。"))

        signals = merge_trusted_and_search_signals(
            extract_contacts("\n".join(trusted_parts)),
            extract_contacts("\n".join(search_parts)),
        )
        if signals.confidence_score < min_confidence:
            low_confidence += 1
            add_failure(failure_breakdown, "low_confidence")
            steps.append(
                ContactWaterfallStep(
                    "置信度判断",
                    "failed",
                    "",
                    "公开页面没有发现足够可信的微信、QQ、Telegram、邮箱或手机号。",
                    signals.confidence_score,
                )
            )
            prospect.follow_up_note = merge_contact_notes(
                prospect.follow_up_note or "",
                build_waterfall_note(steps),
                build_enrichment_failure_note(urls[:3], page_errors, signals.confidence_score),
            )
            samples.append(
                {
                    "prospect_id": prospect.id,
                    "name": prospect.display_name,
                    "status": "missing",
                    "confidence": signals.confidence_score,
                    "urls": urls[:3],
                    "reason": "low_confidence",
                }
            )
            continue

        changed = fill_empty_contact_fields(prospect, signals, min_confidence=min_confidence)
        if changed:
            created = create_contact_records_from_signals(db, prospect, signals, urls[:3], page_notes)
            contacts_created += created
            steps.append(
                ContactWaterfallStep(
                    "联系方式确认",
                    "ok",
                    urls[0] if urls else "",
                    f"补到字段：{', '.join(changed)}；新增记录 {created} 条。",
                    signals.confidence_score,
                )
            )
            prospect.contact_note = merge_contact_notes(prospect.contact_note or "", "\n".join(page_notes), signals.note())
            prospect.status = "qualified"
            prospect.contact_status = "contactable"
            prospect.contact_score = max(prospect.contact_score or 0, signals.confidence_score)
            prospect.next_action = "公开页面已补到联系方式，进入今日跟进，先确认平台、国家、并发量和当前代理痛点。"
            prospect.follow_up_note = merge_contact_notes(prospect.follow_up_note or "", build_waterfall_note(steps))
            prospect.updated_at = datetime.now()
            enriched += 1
            samples.append(
                {
                    "prospect_id": prospect.id,
                    "name": prospect.display_name,
                    "status": "enriched",
                    "confidence": signals.confidence_score,
                    "fields": changed,
                    "contacts_created": created,
                    "urls": urls[:3],
                }
            )
        else:
            add_failure(failure_breakdown, "no_new_field")
            steps.append(
                ContactWaterfallStep(
                    "联系方式确认",
                    "failed",
                    "",
                    "识别到信号，但没有新的可写入字段，可能已存在或只是不够强的辅助信息。",
                    signals.confidence_score,
                )
            )
            prospect.follow_up_note = merge_contact_notes(
                prospect.follow_up_note or "",
                build_waterfall_note(steps),
                build_enrichment_failure_note(urls[:3], page_errors, signals.confidence_score),
            )
            samples.append(
                {
                    "prospect_id": prospect.id,
                    "name": prospect.display_name,
                    "status": "no_new_field",
                    "confidence": signals.confidence_score,
                    "urls": urls[:3],
                }
            )

    db.commit()
    return PublicContactEnrichmentResult(
        scanned=scanned,
        fetched_pages=fetched_pages,
        searched=searched,
        enriched=enriched,
        contacts_created=contacts_created,
        skipped_contactable=skipped_contactable,
        failed=failed,
        no_public_url=no_public_url,
        low_confidence=low_confidence,
        samples=samples[:20],
        failure_breakdown=failure_breakdown,
    )


def build_contact_search_queries(prospect: Prospect, db: Session) -> list[str]:
    identity_parts = []
    if prospect.display_name and not looks_like_url_identity(prospect.display_name):
        identity_parts.append(prospect.display_name)
    if prospect.company_name:
        identity_parts.append(prospect.company_name)
    if prospect.profile_url:
        username = username_from_profile_url(prospect.profile_url)
        if username:
            identity_parts.append(username)

    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect.id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(3)
        )
    )
    for mention in mentions:
        if mention.author and not looks_like_url_identity(mention.author):
            identity_parts.append(mention.author)

    identity_parts = unique_text([clean_search_part(item) for item in identity_parts if clean_search_part(item)])
    context = clean_search_part((mentions[0].title if mentions else prospect.evidence) or "")
    queries: list[str] = []
    for identity in identity_parts[:3]:
        queries.append(f"{identity} 微信 QQ 邮箱 Telegram 联系方式")
        queries.append(f'"{identity}" 官网 联系方式')
        if prospect.platform:
            queries.append(f"{identity} {prospect.platform} 联系方式")
    if context:
        queries.append(f"{context[:60]} 联系方式 微信 邮箱")
    return unique_text(queries)


def create_contact_records_from_signals(
    db: Session,
    prospect: Prospect,
    signals: ContactSignals,
    source_urls: list[str],
    notes: list[str],
) -> int:
    created = 0
    source_url = next((url for url in source_urls if url), prospect.profile_url or prospect.website or "")
    note = "\n".join(unique_text(notes + [signals.note()]))[:2000]
    pairs: list[tuple[str, str, int, bool]] = []
    for value in signals.wechats[:2]:
        pairs.append(("wechat", value, max(65, signals.confidence_score), True))
    for value in signals.qqs[:2]:
        pairs.append(("qq", value, max(58, signals.confidence_score - 5), True))
    for value in signals.telegrams[:2]:
        pairs.append(("telegram", value, max(58, signals.confidence_score - 4), True))
    for value in signals.emails[:2]:
        pairs.append(("email", value, max(55, signals.confidence_score - 8), True))
    for value in signals.phones[:1]:
        pairs.append(("phone", value, max(60, signals.confidence_score - 6), True))
    for value in signals.websites[:2]:
        pairs.append(("website", value, max(40, min(70, signals.confidence_score - 12)), False))

    for contact_type, value, confidence, personal_flag in pairs:
        normalized = normalize_contact_value(contact_type, value)
        if not normalized:
            continue
        existing = db.scalar(
            select(ContactRecord).where(
                ContactRecord.prospect_id == prospect.id,
                ContactRecord.contact_type == contact_type,
                ContactRecord.normalized_value == normalized,
            )
        )
        if existing:
            if confidence > existing.confidence:
                existing.confidence = confidence
                existing.note = merge_contact_notes(existing.note or "", note)[:2000]
                existing.failure_reason = ""
                existing.updated_at = datetime.now()
            continue
        db.add(
            ContactRecord(
                company_id=prospect.company_id,
                prospect_id=prospect.id,
                contact_type=contact_type,
                value=value[:1000],
                normalized_value=normalized[:260],
                source_url=source_url,
                source_type="public_waterfall",
                confidence=min(100, confidence),
                is_business_contact=contact_type in {"email", "website"},
                personal_data_flag=personal_flag,
                status="unverified",
                note=note,
            )
        )
        created += 1
    return created


def build_waterfall_note(steps: list[ContactWaterfallStep]) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    lines = [f"{timestamp} P13 联系方式瀑布："]
    for step in steps[:12]:
        prefix = "OK" if step.status == "ok" else "FAIL"
        confidence = f"；置信度 {step.confidence}/100" if step.confidence else ""
        source = f"；来源 {step.source}" if step.source else ""
        lines.append(f"- [{prefix}] {step.step}{source}{confidence}：{step.reason}")
    return "\n".join(lines)


def add_failure(counter: dict[str, int], code: str) -> None:
    key = code or "unknown"
    counter[key] = counter.get(key, 0) + 1


def classify_fetch_error(error: str) -> str:
    lowered = (error or "").lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if "404" in lowered or "not found" in lowered:
        return "not_found"
    if "non_text" in lowered:
        return "non_text"
    if "invalid_url" in lowered:
        return "invalid_url"
    if "ssl" in lowered or "certificate" in lowered:
        return "ssl_error"
    return "fetch_failed"


def normalize_contact_value(contact_type: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if contact_type in {"email", "website"}:
        return value.lower().rstrip("/")
    if contact_type == "telegram":
        return value.lower().lstrip("@")
    return re.sub(r"\s+", "", value)


def merge_trusted_and_search_signals(trusted: ContactSignals, search: ContactSignals) -> ContactSignals:
    # Search snippets are useful for discovering candidate sites, but too noisy for direct contact fields.
    return ContactSignals(
        emails=trusted.emails,
        wechats=trusted.wechats,
        telegrams=trusted.telegrams,
        qqs=trusted.qqs,
        phones=trusted.phones,
        websites=unique_text(trusted.websites + search.websites)[:8],
        companies=trusted.companies,
    )


def fetch_search_result_text(query: str, timeout: int = 8) -> dict[str, object]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    page = fetch_public_text(url, timeout=timeout)
    if page["ok"]:
        return {"ok": True, "text": f"搜索查询: {query}\n{page['text']}", "error": ""}
    return page


def search_result_urls(text: str) -> list[str]:
    urls = []
    for match in re.findall(r"https?://[^\s\"'<>，。；;、)）\]]+", text):
        parsed = urlparse(match)
        host = parsed.netloc.lower()
        if not host or any(blocked in host for blocked in ("bing.com", "microsoft.com", "baidu.com")):
            continue
        urls.append(match)
    return unique_urls(urls)


def username_from_profile_url(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path.strip("/")
    host = parsed.netloc.lower()
    if not path:
        return ""
    if "v2ex.com" in host and "member/" in path:
        return path.rsplit("/", 1)[-1]
    if any(domain in host for domain in ("gitee.com", "github.com")):
        return path.split("/", 1)[0]
    if "zhihu.com" in host and "people/" in path:
        return path.rsplit("/", 1)[-1]
    return ""


def clean_search_part(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    value = value.strip("-_/@:：，,。")
    if not value or len(value) > 120:
        return ""
    if value.startswith(("http://", "https://")):
        return ""
    return value


def unique_text(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            rows.append(value)
    return rows


def looks_like_url_identity(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return "/" in lowered or lowered.startswith(("http:", "https:")) or lowered.endswith((".com", ".net", ".cn"))


def candidate_public_urls(db: Session, prospect: Prospect) -> list[str]:
    urls: list[str] = []
    for value in (prospect.profile_url, prospect.website):
        if value and is_fetchable_public_url(value):
            urls.append(value)
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect.id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(5)
        )
    )
    for mention in mentions:
        for value in infer_profile_urls_from_mention(mention):
            if is_fetchable_public_url(value):
                urls.append(value)
        if mention.canonical_url and is_fetchable_public_url(mention.canonical_url):
            urls.append(mention.canonical_url)
    return unique_urls(urls)


def infer_profile_urls_from_mention(mention: Mention) -> list[str]:
    urls: list[str] = []
    url = mention.canonical_url or ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    author = clean_author_candidate(mention.author or "")

    if "v2ex.com" in host:
        if "/member/" in parsed.path:
            urls.append(url)
        elif author:
            urls.append(f"https://www.v2ex.com/member/{author}")
    elif "gitee.com" in host:
        if author:
            urls.append(f"https://gitee.com/{author}")
        if path:
            urls.append(f"https://gitee.com/{path.split('/')[0]}")
    elif "segmentfault.com" in host:
        if "/u/" in parsed.path or "/user/" in parsed.path:
            urls.append(url)
        elif author:
            urls.append(f"https://segmentfault.com/u/{author}")
    elif "github.com" in host:
        if author:
            urls.append(f"https://github.com/{author}")
        if path:
            urls.append(f"https://github.com/{path.split('/')[0]}")
    elif "zhihu.com" in host:
        if "/people/" in parsed.path:
            urls.append(url)
        elif author:
            urls.append(f"https://www.zhihu.com/people/{author}")
    return urls


def clean_author_candidate(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", "", value)
    value = value.strip("@：:，,。")
    if not value or len(value) > 64:
        return ""
    if any(token in value.lower() for token in ("http", "/", "问：", "答：")):
        return ""
    return value


def extract_profile_url_from_page(source_url: str, text: str) -> str:
    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    if "v2ex.com" in host:
        match = re.search(r"https?://www\.v2ex\.com/member/[A-Za-z0-9_-]{2,40}", text)
        if match:
            return match.group(0)
        if "/t/" in parsed.path:
            author = re.search(r"\s([A-Za-z0-9_-]{2,40})\s+·\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d)", text)
            if author:
                return f"https://www.v2ex.com/member/{author.group(1)}"
        return ""
    if "segmentfault.com" in host:
        match = re.search(r"https?://segmentfault\.com/u/[A-Za-z0-9_-]{2,60}", text)
        return match.group(0) if match else ""
    if "gitee.com" in host:
        match = re.search(r"https?://gitee\.com/[A-Za-z0-9_.-]{2,60}(?!/issues|/pulls)", text)
        return match.group(0) if match else ""
    if "github.com" in host:
        match = re.search(r"https?://github\.com/[A-Za-z0-9_.-]{2,60}", text)
        return match.group(0) if match else ""
    return ""


def fetch_platform_profile_api_text(url: str, timeout: int = 8) -> dict[str, object]:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    username = username_from_profile_url(url)
    if not username:
        return {"ok": False, "supported": False, "profile_only": False, "websites": [], "text": "", "source": "", "error": ""}
    if "github.com" in host:
        return fetch_github_profile_text(username, timeout=timeout)
    if "gitee.com" in host:
        return fetch_gitee_profile_text(username, timeout=timeout)
    return {"ok": False, "supported": False, "profile_only": False, "websites": [], "text": "", "source": "", "error": ""}


def fetch_github_profile_text(username: str, timeout: int = 8) -> dict[str, object]:
    api_url = f"https://api.github.com/users/{username}"
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": settings.user_agent,
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    data = fetch_json(api_url, headers=headers, timeout=timeout)
    if not data["ok"]:
        return {"ok": False, "supported": True, "profile_only": False, "websites": [], "text": "", "source": api_url, "error": data["error"]}
    payload = data["json"] if isinstance(data["json"], dict) else {}
    parts = [
        f"GitHub 用户: {payload.get('login') or username}",
        f"姓名: {payload.get('name') or ''}",
        f"公司/团队: {payload.get('company') or ''}",
        f"博客/网站: {payload.get('blog') or ''}",
        f"邮箱: {payload.get('email') or ''}",
        f"Twitter: {payload.get('twitter_username') or ''}",
        f"主页: {payload.get('html_url') or ''}",
        f"简介: {payload.get('bio') or ''}",
    ]
    websites = clean_profile_websites([str(payload.get("blog") or "")])
    return {
        "ok": True,
        "supported": True,
        "profile_only": True,
        "websites": websites,
        "text": "\n".join(parts),
        "source": api_url,
        "error": "",
    }


def fetch_gitee_profile_text(username: str, timeout: int = 8) -> dict[str, object]:
    settings = get_settings()
    api_url = f"https://gitee.com/api/v5/users/{username}"
    if settings.gitee_token:
        api_url = f"{api_url}?access_token={quote_plus(settings.gitee_token)}"
    data = fetch_json(api_url, headers={"User-Agent": settings.user_agent}, timeout=timeout)
    if not data["ok"]:
        return {"ok": False, "supported": True, "profile_only": False, "websites": [], "text": "", "source": api_url.split("?")[0], "error": data["error"]}
    payload = data["json"] if isinstance(data["json"], dict) else {}
    parts = [
        f"Gitee 用户: {payload.get('login') or username}",
        f"姓名: {payload.get('name') or ''}",
        f"公司/团队: {payload.get('company') or ''}",
        f"博客/网站: {payload.get('blog') or ''}",
        f"邮箱: {payload.get('email') or ''}",
        f"微博: {payload.get('weibo') or ''}",
        f"主页: {payload.get('html_url') or payload.get('url') or ''}",
        f"简介: {payload.get('bio') or ''}",
    ]
    websites = clean_profile_websites([str(payload.get("blog") or ""), str(payload.get("url") or "")])
    return {
        "ok": True,
        "supported": True,
        "profile_only": True,
        "websites": websites,
        "text": "\n".join(parts),
        "source": api_url.split("?")[0],
        "error": "",
    }


def platform_profile_websites(api_profile: dict[str, object]) -> list[str]:
    values = api_profile.get("websites")
    return values if isinstance(values, list) else []


def clean_profile_websites(values: list[str]) -> list[str]:
    urls: list[str] = []
    for value in values:
        item = (value or "").strip()
        if not item:
            continue
        if not item.startswith(("http://", "https://")) and "." in item:
            item = "https://" + item
        if is_fetchable_public_url(item):
            urls.append(item)
    return unique_urls(urls)


def fetch_json(url: str, headers: dict[str, str], timeout: int = 8) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(200_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "json": {}, "error": str(exc)[:160]}
    try:
        return {"ok": True, "json": json.loads(raw.decode("utf-8", errors="ignore")), "error": ""}
    except json.JSONDecodeError as exc:
        return {"ok": False, "json": {}, "error": f"json_error: {exc}"[:160]}


def build_enrichment_failure_note(urls: list[str], errors: list[str], confidence: int) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    if errors:
        reason = "；".join(errors[:3])
    else:
        reason = "公开页面未发现微信、邮箱、Telegram、QQ、手机号。"
    url_text = " | ".join(urls[:3]) if urls else "无可读 URL"
    return f"{timestamp} 联系方式补全失败：可信度 {confidence}/100；{reason}；已查 {url_text}"


def fetch_public_text(url: str, timeout: int = 8) -> dict[str, object]:
    if not is_fetchable_public_url(url):
        return {"ok": False, "text": "", "error": "invalid_url"}
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LeadRadar/1.0 public-contact-enrichment (+manual sales research)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            if not any(kind in content_type.lower() for kind in ("text/", "html", "json", "xml")):
                return {"ok": False, "text": "", "error": "non_text"}
            raw = response.read(400_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "text": "", "error": str(exc)[:160]}
    text = raw.decode("utf-8", errors="ignore")
    return {"ok": True, "text": html_to_text(text)[:120_000], "error": ""}


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?is)<br\s*/?>", "\n", value)
    value = re.sub(r"(?is)</(p|div|li|tr|h[1-6])>", "\n", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def is_fetchable_public_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return True
    for info in infos[:4]:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    return True


def unique_urls(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().strip("`'\"<>，。；;、)）]}")
        key = key.rstrip("/")
        if key and key not in seen:
            seen.add(key)
            rows.append(key)
    return rows


def build_contact_enrichment_report(db: Session, limit: int = 100) -> dict[str, object]:
    prospects = list(db.scalars(select(Prospect).order_by(desc(Prospect.lead_score)).limit(limit)))
    rows = []
    for prospect in prospects:
        signals = extract_contacts(build_contact_haystack(db, prospect))
        rows.append(
            {
                "prospect_id": prospect.id,
                "name": prospect.display_name,
                "platform": prospect.platform,
                "lead_score": prospect.lead_score,
                "has_contact": has_real_contact(prospect),
                "contact_confidence": signals.confidence_score,
                "quality": signals.quality_label,
                "primary_key": signals.primary_key(),
            }
        )
    return {
        "rows": len(rows),
        "contactable": sum(1 for row in rows if row["has_contact"]),
        "high_confidence": sum(1 for row in rows if row["contact_confidence"] >= 70),
        "sample": rows[:30],
    }


def build_contact_haystack(db: Session, prospect: Prospect) -> str:
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect.id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(12)
        )
    )
    parts = [
        prospect.display_name or "",
        prospect.company_name or "",
        prospect.website or "",
        prospect.contact_note or "",
        prospect.evidence or "",
    ]
    if prospect.wechat:
        parts.append(f"微信: {prospect.wechat}")
    if prospect.email:
        parts.append(f"邮箱: {prospect.email}")
    if prospect.telegram:
        parts.append(f"Telegram: {prospect.telegram}")
    for mention in mentions:
        parts.extend(
            [
                mention.title or "",
                mention.content or "",
                mention.author or "",
                mention.canonical_url or "",
                mention.matched_keywords or "",
            ]
        )
    return "\n".join(parts)


def fill_empty_contact_fields(prospect: Prospect, signals, min_confidence: int = 35) -> list[str]:
    changed: list[str] = []
    if not prospect.wechat and signals.wechats:
        prospect.wechat = signals.wechats[0][:160]
        changed.append("wechat")
    if not prospect.email and signals.emails:
        prospect.email = signals.emails[0][:260]
        changed.append("email")
    if not prospect.telegram and signals.telegrams:
        prospect.telegram = signals.telegrams[0][:160]
        changed.append("telegram")
    if not prospect.website and signals.websites and signals.confidence_score >= min_confidence:
        prospect.website = signals.websites[0][:1000]
        changed.append("website")
    if not prospect.company_name and signals.companies and signals.confidence_score >= max(60, min_confidence):
        prospect.company_name = signals.companies[0][:260]
        changed.append("company_name")

    note = signals.note() if signals.has_contact or signals.confidence_score >= min_confidence else ""
    if note:
        merged = merge_contact_notes(prospect.contact_note or "", note)
        if merged != (prospect.contact_note or ""):
            prospect.contact_note = merged[:5000]
            changed.append("contact_note")
    return changed


def prune_untrusted_existing_contacts(prospect: Prospect) -> int:
    cleaned = 0
    context = "\n".join(
        [
            prospect.website or "",
            prospect.contact_note or "",
            prospect.evidence or "",
            prospect.profile_url or "",
        ]
    ).lower()

    if prospect.telegram and not extract_contacts(f"Telegram: {prospect.telegram}").telegrams:
        prospect.contact_note = remove_contact_value(prospect.contact_note or "", prospect.telegram)
        prospect.telegram = ""
        cleaned += 1

    if prospect.wechat:
        single = extract_contacts(f"微信: {prospect.wechat}")
        if not single.wechats or looks_like_session_fragment(prospect.wechat, context):
            prospect.contact_note = remove_contact_value(prospect.contact_note or "", prospect.wechat)
            prospect.wechat = ""
            cleaned += 1

    if prospect.email and not extract_contacts(prospect.email).emails:
        prospect.contact_note = remove_contact_value(prospect.contact_note or "", prospect.email)
        prospect.email = ""
        cleaned += 1

    if prospect.website:
        parsed = urlparse(prospect.website)
        if parsed.username or parsed.password or not parsed.scheme or not parsed.netloc or parsed.hostname == "localhost":
            prospect.contact_note = remove_contact_value(prospect.contact_note or "", prospect.website)
            prospect.website = ""
            cleaned += 1

    if cleaned:
        prospect.updated_at = datetime.now()
    return cleaned


def looks_like_session_fragment(value: str, context: str) -> bool:
    value = (value or "").lower()
    if not value:
        return False
    session_markers = (
        "claude.ai/code/session",
        "claude.com/claude-code",
        "session_",
        "token=",
        "access_token",
    )
    return value in context and any(marker in context for marker in session_markers)


def remove_contact_value(note: str, value: str) -> str:
    value = (value or "").strip()
    if not note or not value:
        return note
    lines = [line for line in note.splitlines() if value not in line]
    return "\n".join(lines)
