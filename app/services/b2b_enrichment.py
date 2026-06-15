from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, CompanySignal, ContactRecord, OutreachActivity
from app.services.company_profiles import extract_domain, normalize_contact_value, rescore_companies, slug
from app.services.contacts import extract_contacts
from app.settings import get_settings


WEBSITE_INTENT_TERMS = {
    "scraping": ["web scraping", "scraping", "crawler", "spider", "data extraction", "数据采集", "爬虫"],
    "proxy": ["proxy", "proxies", "residential proxy", "代理 ip", "代理IP", "动态住宅", "住宅 ip"],
    "anti_bot": ["anti-bot", "antibot", "cloudflare", "captcha", "反爬", "验证码", "blocked"],
    "price_monitoring": ["price monitoring", "价格监控", "竞品监控", "电商情报"],
    "ad_verification": ["ad verification", "广告验证", "ad monitoring"],
    "serp": ["serp", "seo", "search engine results", "搜索结果"],
    "ecommerce": ["amazon", "shopify", "shopee", "lazada", "tiktok shop", "跨境"],
}

CONTACT_PATHS = ["contact", "contact-us", "about", "about-us", "pricing", "support", "sales"]
GITHUB_REPO_TERMS = ["scraper", "crawler", "spider", "proxy", "captcha", "cloudflare", "serp", "amazon", "tiktok"]


@dataclass(frozen=True)
class StepResult:
    step: str
    scanned: int = 0
    created_signals: int = 0
    created_contacts: int = 0
    enriched_companies: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WaterfallResult:
    companies_scanned: int
    website: StepResult
    github: StepResult
    contacts: StepResult


def run_b2b_waterfall(db: Session, limit: int = 30) -> WaterfallResult:
    website = scan_company_websites(db, limit=limit)
    github = enrich_github_companies(db, limit=limit)
    contacts = enrich_company_contacts_from_pages(db, limit=limit)
    return WaterfallResult(
        companies_scanned=max(website.scanned, github.scanned, contacts.scanned),
        website=website,
        github=github,
        contacts=contacts,
    )


def scan_company_websites(db: Session, limit: int = 30) -> StepResult:
    companies = list(
        db.scalars(
            select(CompanyProfile)
            .where(CompanyProfile.website != "")
            .where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
            .order_by(desc(CompanyProfile.priority_score), desc(CompanyProfile.updated_at))
            .limit(limit * 2)
        )
    )
    scanned = signals = contacts = enriched = failed = 0
    notes: list[str] = []
    for company in companies:
        if scanned >= limit:
            break
        base_url = normalize_url(company.website)
        if not base_url or is_blocked_domain(base_url):
            continue
        scanned += 1
        pages = fetch_company_pages(base_url)
        if not pages:
            failed += 1
            add_activity(db, company, "website_scan", f"官网扫描失败或无可读页面：{base_url}")
            continue
        combined = "\n".join(page["text"] for page in pages)
        intent_hits = find_website_intent(combined)
        if intent_hits:
            signal_score = min(95, 45 + len(intent_hits) * 12)
            signals += ensure_company_signal(
                db,
                company=company,
                signal_type="website_keyword",
                title=f"官网命中动态住宅 IP 相关 B2B 信号：{', '.join(intent_hits[:4])}",
                url=base_url,
                content=combined[:1000],
                score=signal_score,
                reason="官网出现：" + "、".join(intent_hits[:10]),
            )
            company.intent_score = max(company.intent_score, signal_score)
            company.need_reason = f"官网出现代理/爬虫/数据采集相关信号：{', '.join(intent_hits[:6])}"
            company.next_action = "官网已命中 B2B 意图信号，优先补商务联系方式并人工判断是否适合触达。"
            enriched += 1
        contact_signals = extract_contacts(combined)
        contacts += save_contacts_from_signals(db, company, contact_signals, base_url, "website_scan")
        if contact_signals.companies and not company.company_name:
            company.company_name = contact_signals.companies[0][:260]
        add_activity(db, company, "website_scan", f"官网扫描完成：页面 {len(pages)}，命中 {len(intent_hits)} 个信号。")
        notes.append(f"{company.company_name or company.domain}: {len(intent_hits)} hits")

    rescore_companies(db)
    db.commit()
    return StepResult("website_scan", scanned, signals, contacts, enriched, failed, notes[:10])


def enrich_github_companies(db: Session, limit: int = 30) -> StepResult:
    companies = list(
        db.scalars(
            select(CompanyProfile)
            .where(
                (CompanyProfile.website.like("%github.com%"))
                | (CompanyProfile.company_key.like("github:%"))
                | (CompanyProfile.domain == "github.com")
            )
            .where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
            .order_by(desc(CompanyProfile.priority_score), desc(CompanyProfile.updated_at))
            .limit(limit * 2)
        )
    )
    scanned = signals = contacts = enriched = failed = 0
    notes: list[str] = []
    for company in companies:
        if scanned >= limit:
            break
        login = github_login_from_company(company)
        if not login:
            continue
        scanned += 1
        payload = fetch_github_profile(login)
        repos = fetch_github_repos(login)
        if payload is None and not repos:
            failed += 1
            add_activity(db, company, "github_enrich", f"GitHub 增强失败：{login}")
            continue
        if payload:
            company.company_name = company.company_name or payload.get("name") or login
            blog = payload.get("blog") or ""
            if blog and not company.website:
                company.website = normalize_url(blog)
                company.domain = extract_domain(company.website)
            company.region = company.region or payload.get("location") or ""
            bio = payload.get("bio") or ""
            contact_text = "\n".join([bio, payload.get("email") or "", payload.get("twitter_username") or "", blog])
            contacts += save_contacts_from_signals(db, company, extract_contacts(contact_text), f"https://github.com/{login}", "github_profile")
        repo_hits = []
        for repo in repos[:30]:
            haystack = " ".join(
                [
                    repo.get("name") or "",
                    repo.get("description") or "",
                    " ".join(repo.get("topics") or []),
                ]
            ).lower()
            if any(term in haystack for term in GITHUB_REPO_TERMS):
                repo_hits.append(repo)
        if repo_hits:
            title = "GitHub 项目命中爬虫/代理/反爬相关信号"
            content = "\n".join(
                f"{repo.get('full_name')}: {repo.get('description') or ''}" for repo in repo_hits[:8]
            )
            signals += ensure_company_signal(
                db,
                company=company,
                signal_type="github_project",
                title=title,
                url=f"https://github.com/{login}",
                content=content,
                score=min(95, 55 + len(repo_hits) * 8),
                reason=f"GitHub 仓库命中 {len(repo_hits)} 个 scraper/crawler/proxy/anti-bot 相关项目。",
            )
            company.intent_score = max(company.intent_score, min(95, 55 + len(repo_hits) * 8))
            company.need_reason = company.need_reason or "GitHub 组织/用户存在爬虫、代理、反爬或数据采集相关项目。"
            company.next_action = "GitHub 命中技术型 B2B 信号，优先确认是否为团队/公司并补商务联系方式。"
            enriched += 1
        add_activity(db, company, "github_enrich", f"GitHub 增强完成：{login}，仓库 {len(repos)}，命中 {len(repo_hits)}。")
        notes.append(f"{login}: repos={len(repos)}, hits={len(repo_hits)}")

    rescore_companies(db)
    db.commit()
    return StepResult("github_enrich", scanned, signals, contacts, enriched, failed, notes[:10])


def enrich_company_contacts_from_pages(db: Session, limit: int = 30) -> StepResult:
    companies = list(
        db.scalars(
            select(CompanyProfile)
            .where(CompanyProfile.contact_status != "contactable")
            .where(CompanyProfile.website != "")
            .where(CompanyProfile.crm_status.notin_(["invalid", "competitor", "do_not_contact"]))
            .order_by(desc(CompanyProfile.priority_score))
            .limit(limit * 3)
        )
    )
    scanned = contacts = failed = enriched = 0
    notes: list[str] = []
    for company in companies:
        if scanned >= limit:
            break
        base_url = normalize_url(company.website)
        if not base_url or is_blocked_domain(base_url):
            continue
        scanned += 1
        pages = fetch_company_pages(base_url, only_contact=True)
        if not pages:
            failed += 1
            continue
        before = contacts
        for page in pages:
            contacts += save_contacts_from_signals(
                db, company, extract_contacts(page["text"]), page["url"], "waterfall_contact_page"
            )
        if contacts > before:
            enriched += 1
            add_activity(db, company, "contact_saved", f"Waterfall 从公开页面补到联系方式：{base_url}")
        notes.append(f"{company.company_name or company.domain}: +{contacts - before}")
    rescore_companies(db)
    db.commit()
    return StepResult("contact_waterfall", scanned, 0, contacts, enriched, failed, notes[:10])


def fetch_company_pages(base_url: str, only_contact: bool = False) -> list[dict[str, str]]:
    urls = [base_url]
    if not only_contact:
        urls.extend(urljoin(base_url.rstrip("/") + "/", path) for path in ["about", "product"])
    urls.extend(urljoin(base_url.rstrip("/") + "/", path) for path in CONTACT_PATHS[:3])
    seen: set[str] = set()
    pages: list[dict[str, str]] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        page = fetch_public_page(url)
        if page:
            pages.append(page)
        if len(pages) >= 3:
            break
    return pages


def fetch_public_page(url: str) -> dict[str, str] | None:
    settings = get_settings()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(6.0, connect=3.0),
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return None
            soup = BeautifulSoup(response.text[:400_000], "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            text = soup.get_text(" ", strip=True)
            return {"url": str(response.url), "title": title, "text": text[:20_000]}
    except (httpx.HTTPError, ValueError, httpx.InvalidURL):
        return None


def fetch_github_profile(login: str) -> dict | None:
    url = f"https://api.github.com/users/{login}"
    return github_get_json(url)


def fetch_github_repos(login: str) -> list[dict]:
    url = f"https://api.github.com/users/{login}/repos?sort=updated&per_page=50"
    payload = github_get_json(url)
    return payload if isinstance(payload, list) else []


def github_get_json(url: str):
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": settings.user_agent}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    try:
        with httpx.Client(timeout=15, headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def find_website_intent(text: str) -> list[str]:
    lowered = (text or "").lower()
    hits: list[str] = []
    for group, terms in WEBSITE_INTENT_TERMS.items():
        matched = [term for term in terms if term.lower() in lowered]
        if matched:
            hits.append(f"{group}:{matched[0]}")
    return hits


def ensure_company_signal(
    db: Session,
    company: CompanyProfile,
    signal_type: str,
    title: str,
    url: str,
    content: str,
    score: int,
    reason: str,
) -> int:
    existing = db.scalar(
        select(CompanySignal).where(CompanySignal.company_id == company.id, CompanySignal.url == url)
    )
    if existing:
        existing.score = max(existing.score, score)
        existing.reason = reason
        existing.content_snippet = content[:1200]
        return 0
    db.add(
        CompanySignal(
            company_id=company.id,
            source_name="B2B Enrichment",
            source_kind=signal_type,
            signal_type=signal_type,
            title=title[:500],
            url=url,
            content_snippet=content[:1200],
            score=score,
            reason=reason,
            detected_at=datetime.now(),
        )
    )
    return 1


def save_contacts_from_signals(
    db: Session,
    company: CompanyProfile,
    signals,
    source_url: str,
    source_type: str,
) -> int:
    created = 0
    contact_pairs: list[tuple[str, str, int]] = []
    contact_pairs.extend(("email", value, 75) for value in signals.emails)
    contact_pairs.extend(("wechat", value, 75) for value in signals.wechats)
    contact_pairs.extend(("telegram", value, 70) for value in signals.telegrams)
    contact_pairs.extend(("phone", value, 65) for value in signals.phones)
    if "contact" in source_url or "sales" in source_url:
        contact_pairs.append(("contact_form", source_url, 55))
    for contact_type, value, confidence in contact_pairs:
        normalized = normalize_contact_value(contact_type, value)
        if not normalized:
            continue
        exists = db.scalar(
            select(ContactRecord).where(
                ContactRecord.company_id == company.id,
                ContactRecord.contact_type == contact_type,
                ContactRecord.normalized_value == normalized,
            )
        )
        if exists:
            continue
        db.add(
            ContactRecord(
                company_id=company.id,
                contact_type=contact_type,
                value=value,
                normalized_value=normalized,
                source_url=source_url,
                source_type=source_type,
                confidence=confidence,
                status="unverified",
                note=f"{source_type} 自动补全",
            )
        )
        created += 1
    if created:
        company.contact_status = "contactable"
        company.contact_count = (company.contact_count or 0) + created
    return created


def add_activity(db: Session, company: CompanyProfile, activity_type: str, note: str) -> None:
    db.add(
        OutreachActivity(
            company_id=company.id,
            activity_type=activity_type,
            channel="system",
            status="done",
            note=note[:2000],
        )
    )


def github_login_from_company(company: CompanyProfile) -> str:
    for value in [company.website, company.domain, company.company_key]:
        if not value:
            continue
        if "github.com" in value:
            parsed = urlparse(normalize_url(value))
            parts = [part for part in parsed.path.split("/") if part]
            if parts:
                return slug(parts[0])
        if value.startswith("github:"):
            return slug(value.split(":", 1)[1])
    return ""


def normalize_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    raw = raw.strip("`'\" <>，。；;、)")
    if raw.startswith("mailto:"):
        return ""
    if "@" in raw and not raw.startswith(("http://", "https://")):
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if "@" in parsed.netloc:
        return ""
    try:
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return ""
    except ValueError:
        return ""
    return raw


def is_blocked_domain(url: str) -> bool:
    domain = extract_domain(url)
    return domain in {
        "zhihu.com",
        "tieba.baidu.com",
        "xiaohongshu.com",
        "douyin.com",
        "weibo.com",
        "bilibili.com",
        "segmentfault.com",
        "v2ex.com",
        "csdn.net",
        "cnblogs.com",
        "oschina.net",
    }
