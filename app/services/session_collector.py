from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Keyword, Mention
from app.schemas import RawItem
from app.services import domestic_search_strategy as search_strategy
from app.services.ingest import insert_item
from app.services.lead_quality import evaluate_lead_quality
from app.services.prospects import rebuild_prospects
from app.services.freshness import freshness_decision, parse_text_date


SESSION_DATA_DIR = Path("data/session_collector")
PROFILE_DIR = SESSION_DATA_DIR / "profiles"
TASKS_FILE = SESSION_DATA_DIR / "tasks.json"
RUN_LOG_FILE = SESSION_DATA_DIR / "runs.json"
STATUS_FILE = SESSION_DATA_DIR / "status.json"
PROGRESS_FILE = SESSION_DATA_DIR / "progress.json"


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    home_url: str
    search_url: str
    allowed_hosts: tuple[str, ...]
    card_selectors: tuple[str, ...]
    author_selectors: tuple[str, ...] = ()
    note: str = ""


PLATFORM_SPECS: dict[str, PlatformSpec] = {
    "zhihu": PlatformSpec(
        key="zhihu",
        label="知乎",
        home_url="https://www.zhihu.com/",
        search_url="https://www.zhihu.com/search?type=question&q={keyword}",
        allowed_hosts=("zhihu.com",),
        card_selectors=(".SearchResult-Card", ".ContentItem", "article", "[data-za-detail-view-path-module]"),
        author_selectors=(".AuthorInfo-name", ".UserLink-link", "[itemprop='name']"),
        note="公开搜索经常要求登录；适合登录后低频抓需求帖、回答和用户主页。",
    ),
    "tieba": PlatformSpec(
        key="tieba",
        label="百度贴吧",
        home_url="https://tieba.baidu.com/",
        search_url="https://tieba.baidu.com/f/search/res?ie=utf-8&qw={keyword}",
        allowed_hosts=("tieba.baidu.com",),
        card_selectors=(".s_post", ".p_postlist", ".j_thread_list", ".threadlist_li", "li"),
        author_selectors=(".p_author_name", ".tb_icon_author", ".author_name"),
        note="贴吧小团队线索可能有价值，但公开搜索易受限，建议小批量。",
    ),
    "xiaohongshu": PlatformSpec(
        key="xiaohongshu",
        label="小红书",
        home_url="https://www.xiaohongshu.com/",
        search_url="https://www.xiaohongshu.com/search_result?keyword={keyword}",
        allowed_hosts=("xiaohongshu.com",),
        card_selectors=(".note-item", ".feeds-page .note-item", "section", "div"),
        author_selectors=(".author", ".name", ".user-name"),
        note="只采公开搜索卡片；检测登录/验证/频控会暂停。",
    ),
    "douyin": PlatformSpec(
        key="douyin",
        label="抖音",
        home_url="https://www.douyin.com/",
        search_url="https://www.douyin.com/search/{keyword}",
        allowed_hosts=("douyin.com",),
        card_selectors=("[data-e2e*='search']", "li", "article", "div"),
        author_selectors=("[data-e2e*='user']", ".author", ".nickname"),
        note="适合发现 TikTok/跨境运营人群公开内容；不自动互动。",
    ),
    "bilibili": PlatformSpec(
        key="bilibili",
        label="B站",
        home_url="https://www.bilibili.com/",
        search_url="https://search.bilibili.com/all?keyword={keyword}",
        allowed_hosts=("bilibili.com",),
        card_selectors=(".video-list-item", ".bili-video-card", ".result-wrap", ".user-list-item"),
        author_selectors=(".bili-video-card__info--author", ".up-name", ".username"),
        note="适合找跨境教程、指纹浏览器、爬虫代理相关公开视频和UP主。",
    ),
    "weibo": PlatformSpec(
        key="weibo",
        label="微博",
        home_url="https://weibo.com/",
        search_url="https://s.weibo.com/weibo?q={keyword}",
        allowed_hosts=("weibo.com", "s.weibo.com"),
        card_selectors=(".card-wrap", ".card", "article"),
        author_selectors=(".name", ".woo-box-flex a", "a.name"),
        note="适合找公开讨论和服务商线索；登录态低频采集。",
    ),
}

PLATFORM_SEARCH_URLS = {key: spec.search_url for key, spec in PLATFORM_SPECS.items()}
PLATFORM_LABELS = {key: spec.label for key, spec in PLATFORM_SPECS.items()}

PLATFORM_STRATEGIES: dict[str, dict[str, str]] = {
    "zhihu": {
        "tier": "可自动低频",
        "risk": "中",
        "mode": "登录后低频后台采集",
        "note": "适合问题、回答、主页线索；一旦出现验证或频控，暂停 12-24 小时再跑。",
    },
    "tieba": {
        "tier": "低频观察",
        "risk": "中高",
        "mode": "先单平台试跑",
        "note": "公开搜索容易波动，优先用精准店群、账号环境、IP 关联词，小批量验证页面结构。",
    },
    "xiaohongshu": {
        "tier": "高风险半自动",
        "risk": "高",
        "mode": "只做登录后试跑",
        "note": "强风控平台，不做连续自动化；更适合人工观察、少量回收公开结果。",
    },
    "douyin": {
        "tier": "高风险半自动",
        "risk": "高",
        "mode": "只做登录后试跑",
        "note": "强风控平台，不做连续自动化；先验证搜索页能否稳定返回公开内容。",
    },
    "bilibili": {
        "tier": "低频可试",
        "risk": "中",
        "mode": "低频搜索采集",
        "note": "适合爬虫、Cloudflare、指纹浏览器类技术痛点；若无结果，多半是页面结构或关键词问题。",
    },
    "weibo": {
        "tier": "低频观察",
        "risk": "中高",
        "mode": "登录后低频试跑",
        "note": "搜索频控较常见；建议少关键词、慢速、只读公开结果。",
    },
}

DIAGNOSTIC_GUIDE: dict[str, dict[str, str]] = {
    "blocked": {
        "label": "平台风控/验证",
        "reason": "页面出现登录、验证码、安全验证、访问频繁等提示，继续采集会增加账号风险。",
        "next_step": "暂停该平台，人工处理验证或等待冷却后，先用单平台试跑恢复。",
    },
    "captcha": {
        "label": "验证码/安全验证",
        "reason": "平台要求验证码、人机验证或安全验证。继续自动跑会放大账号风险。",
        "next_step": "暂停该平台，人工完成验证；验证后先点“检查状态”，再小批量试跑。",
    },
    "rate_limited": {
        "label": "访问频率过高",
        "reason": "平台提示访问过快、429、稍后再试或类似频控信息。",
        "next_step": "暂停 12-24 小时，降低关键词数量和频率；恢复后只跑单平台小批量。",
    },
    "login_required": {
        "label": "登录失效",
        "reason": "页面跳到登录页或提示登录后才能继续，当前浏览器会话已经不可用。",
        "next_step": "重新登录该平台，关闭登录窗口后点“检查状态”，确认已登录再采集。",
    },
    "login_page": {
        "label": "登录失效",
        "reason": "采集过程中被重定向到登录页，说明会话未生效或已过期。",
        "next_step": "重新登录并检查状态；不要连续重试后台采集。",
    },
    "account_risk": {
        "label": "账号异常",
        "reason": "平台提示账号异常、限制或安全风险。",
        "next_step": "停止该账号自动采集，先人工确认账号安全状态。",
    },
    "profile_open": {
        "label": "登录窗口未关闭",
        "reason": "同一个浏览器 profile 被登录窗口占用，后台采集无法复用会话。",
        "next_step": "关闭刚打开的平台登录窗口，再点“检查状态”。",
    },
    "not_logged_in": {
        "label": "未登录",
        "reason": "本地浏览器 profile 没有检测到有效登录态。",
        "next_step": "先登录账号，关闭窗口，然后检查状态。",
    },
    "unknown": {
        "label": "登录态未确认",
        "reason": "浏览器可能已登录，但采集器没有稳定确认账号态或搜索页状态。",
        "next_step": "点“检查状态”，通过后再做单平台试跑。",
    },
    "unsupported": {
        "label": "暂不支持",
        "reason": "该平台还没有稳定的会话采集适配器。",
        "next_step": "先走人工导入或公开源；等适配器补齐后再自动采集。",
    },
    "unsupported_platform": {
        "label": "暂不支持",
        "reason": "该平台还没有稳定的会话采集适配器。",
        "next_step": "先走人工导入或公开源；等适配器补齐后再自动采集。",
    },
    "missing_playwright": {
        "label": "采集依赖缺失",
        "reason": "本机缺少 Playwright 或浏览器依赖，无法启动会话采集。",
        "next_step": "安装 Playwright 依赖后重启服务，再从单平台试跑开始验证。",
    },
    "no_db": {
        "label": "数据库会话缺失",
        "reason": "后台任务没有拿到数据库连接，结果无法入库。",
        "next_step": "重启服务后重试；如果反复出现，需要检查后台任务上下文。",
    },
    "not_ready": {
        "label": "平台未就绪",
        "reason": "平台登录状态、浏览器会话或任务配置还没有满足后台采集条件。",
        "next_step": "先检查登录状态，确认已登录后再运行后台采集。",
    },
    "empty_page": {
        "label": "页面加载异常",
        "reason": "页面内容过少，可能是加载失败、被拦截或页面结构变化。",
        "next_step": "先人工打开原页面确认；如果页面正常，需要修该平台解析器。",
    },
    "quality_filtered": {
        "label": "质量过滤",
        "reason": "页面能读到候选结果，但大多是教程、广告、泛内容或不匹配动态住宅 IP 业务。",
        "next_step": "换成更具体的痛点词，例如“店铺关联 IP”“Cloudflare 403 住宅IP”。",
    },
    "time_filtered": {
        "label": "时间不合格",
        "reason": "线索发布时间早于 2026 年，已经不符合当前获客窗口。",
        "next_step": "保留证据但不进入跟进；优先跑 2026 年新内容和近期讨论。",
    },
    "no_candidates": {
        "label": "页面无候选",
        "reason": "页面可访问，但没有抽取到结果，可能是关键词无结果或页面结构变了。",
        "next_step": "先换关键词试跑；若仍为 0，需要修该平台解析器。",
    },
    "page_structure_changed": {
        "label": "页面结构变化",
        "reason": "平台页面可打开，但当前选择器抽不到有效卡片。",
        "next_step": "人工查看页面结构，更新该平台解析规则。",
    },
    "exception": {
        "label": "采集器异常",
        "reason": "浏览器、网络、页面超时或解析过程出现异常。",
        "next_step": "查看最近状态消息；若重复出现，需要修平台适配器。",
    },
    "none": {
        "label": "正常",
        "reason": "暂未发现阻塞。",
        "next_step": "保持小批量、低频运行，优先跟进高分线索。",
    },
}

PAUSE_PATTERNS = [
    "验证码",
    "安全验证",
    "请先登录",
    "登录验证",
    "登录后才能",
    "账号异常",
    "访问太频繁",
    "稍后再试",
    "verify",
    "captcha",
    "robot",
    "rate limit",
    "too many requests",
]

DEMAND_TERMS = [
    "动态住宅",
    "住宅ip",
    "海外ip",
    "代理ip",
    "防关联",
    "指纹浏览器",
    "矩阵",
    "店群",
    "养号",
    "多账号",
    "tiktok",
    "小店",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "爬虫",
    "采集",
    "验证码",
    "cloudflare",
    "403",
    "429",
]

NOISE_TERMS = [
    "登录",
    "注册",
    "广告",
    "隐私政策",
    "用户协议",
    "帮助中心",
    "客户端下载",
    "热搜",
    "首页",
]

PAUSE_PATTERNS = search_strategy.PAUSE_PATTERNS
DEMAND_TERMS = search_strategy.DEMAND_TERMS
NOISE_TERMS = search_strategy.NOISE_TERMS

LOW_QUALITY_CONTENT_TERMS = [
    "教程",
    "指南",
    "攻略",
    "全攻略",
    "操作手册",
    "运营指南",
    "新手",
    "小白",
    "入门",
    "科普",
    "必看",
    "必备",
    "一招",
    "3分钟",
    "三分钟",
    "从 0 到 1",
    "从0到1",
    "不踩坑",
    "方案对比",
    "全套操作",
    "手册",
    "总结出",
    "测评",
    "评测",
    "哪家好",
    "排行榜",
    "免费试用",
    "平替",
]

SUPPLIER_AD_TERMS = [
    "kookeey",
    "novproxy",
    "ipidea",
    "922s5",
    "bright data",
    "oxylabs",
    "smartproxy",
    "全球代理平台",
    "高性价比",
    "官网",
    "服务商",
]

HIGH_QUALITY_INTENT_TERMS = [
    "怎么办",
    "怎么解决",
    "求推荐",
    "求助",
    "请教",
    "有没有",
    "哪里找",
    "怎么配",
    "怎么选",
    "可以做几个",
    "能运营几个",
    "能共用",
    "多开",
    "比较好的系统",
    "比较好的方案",
    "有什么方案",
    "怎么防",
    "不会被封",
    "不被封",
    "不会关联",
    "不被关联",
    "无法",
    "失败",
    "不稳定",
    "一直验证",
    "太频繁",
    "被封",
    "封号",
    "被关联",
    "会关联吗",
    "关联吗",
    "登录环境异常",
    "账号环境异常",
    "403",
    "429",
    "captcha",
    "cloudflare",
    "有比较好",
    "靠谱",
]

HIGH_QUALITY_CONTEXT_TERMS = [
    "tiktok",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "指纹浏览器",
    "爬虫",
    "采集",
    "cloudflare",
    "店群",
    "矩阵",
    "养号",
    "多账号",
    "多店铺",
    "防关联",
    "代理ip",
    "ip",
    "跨境",
]

PAIN_SCENE_TERMS = [
    "账号关联",
    "ip关联",
    "关联限流",
    "关联封",
    "一夜被封",
    "连封",
    "封禁",
    "限流",
    "环境污染",
    "节点",
    "同一个ip",
    "独立ip",
    "公网ip",
    "风控",
    "申诉",
]


@dataclass
class SessionTask:
    platform: str
    keywords: str
    daily_limit: int = 30
    page_limit: int = 2
    delay_seconds: int = 8
    enabled: bool = True

    @property
    def keyword_list(self) -> list[str]:
        normalized = re.sub(r"[，、；;|\n]+", ",", self.keywords or "")
        return [item.strip() for item in normalized.split(",") if item.strip()]


@dataclass(frozen=True)
class SessionCollectResult:
    platform: str
    fetched: int
    inserted: int
    paused: bool
    message: str
    candidates: int = 0
    rejected: int = 0
    high_quality: int = 0
    failure_code: str = ""


@dataclass(frozen=True)
class SessionLoginStatus:
    platform: str
    state: str
    label: str
    message: str
    checked_at: str = ""


@dataclass(frozen=True)
class SessionPlatformDiagnostic:
    platform: str
    label: str
    login_label: str
    login_state: str
    last_checked_at: str
    task_enabled: bool
    keyword_count: int
    daily_limit: int
    delay_seconds: int
    runs: int
    fetched: int
    inserted: int
    candidates: int
    rejected: int
    high_quality_session: int
    paused: int
    recent_mentions: int
    high_value_mentions: int
    last_run_at: str
    last_message: str
    health: str
    action: str
    failure_code: str = ""
    diagnostic_label: str = ""
    diagnostic_reason: str = ""
    next_step: str = ""
    strategy_tier: str = ""
    strategy_risk: str = ""
    strategy_mode: str = ""
    strategy_note: str = ""


@dataclass(frozen=True)
class ExtractionResult:
    items: list[RawItem]
    candidates: int
    rejected: int
    high_quality: int


@dataclass(frozen=True)
class PageDiagnosis:
    code: str
    label: str
    message: str
    should_pause: bool = False


@dataclass(frozen=True)
class SessionProgress:
    state: str
    platform: str
    keyword: str
    fetched: int
    inserted: int
    candidates: int
    rejected: int
    high_quality: int
    message: str
    updated_at: str
    failure_code: str = ""


def load_tasks() -> list[SessionTask]:
    ensure_dirs()
    if not TASKS_FILE.exists():
        tasks = default_tasks()
        save_tasks(tasks)
        return tasks
    data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    return [SessionTask(**item) for item in data]


def save_tasks(tasks: list[SessionTask]) -> None:
    ensure_dirs()
    TASKS_FILE.write_text(
        json.dumps([asdict(task) for task in tasks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def upsert_task(task: SessionTask) -> None:
    tasks = [item for item in load_tasks() if item.platform != task.platform]
    tasks.append(task)
    save_tasks(sorted(tasks, key=lambda item: item.platform))


def sync_default_tasks(overwrite_keywords: bool = True) -> dict[str, int | str]:
    current = {task.platform: task for task in load_tasks()}
    default_order = [platform for platform, *_ in search_strategy.SESSION_TASK_DEFAULTS]
    added = 0
    updated = 0

    for platform, keywords, daily_limit, page_limit, delay_seconds in search_strategy.SESSION_TASK_DEFAULTS:
        existing = current.get(platform)
        if existing is None:
            current[platform] = SessionTask(
                platform=platform,
                keywords=keywords,
                daily_limit=daily_limit,
                page_limit=page_limit,
                delay_seconds=delay_seconds,
                enabled=True,
            )
            added += 1
            continue

        if overwrite_keywords and (
            existing.keywords != keywords
            or existing.daily_limit != daily_limit
            or existing.page_limit != page_limit
            or existing.delay_seconds != delay_seconds
            or not existing.enabled
        ):
            current[platform] = SessionTask(
                platform=platform,
                keywords=keywords,
                daily_limit=daily_limit,
                page_limit=page_limit,
                delay_seconds=delay_seconds,
                enabled=True,
            )
            updated += 1

    save_tasks(
        sorted(
            current.values(),
            key=lambda task: default_order.index(task.platform) if task.platform in default_order else len(default_order),
        )
    )
    return {
        "strategy_version": search_strategy.STRATEGY_VERSION,
        "added": added,
        "updated": updated,
        "tasks": len(current),
    }


def default_tasks() -> list[SessionTask]:
    return [
        SessionTask(
            platform=platform,
            keywords=keywords,
            daily_limit=daily_limit,
            page_limit=page_limit,
            delay_seconds=delay_seconds,
        )
        for platform, keywords, daily_limit, page_limit, delay_seconds in search_strategy.SESSION_TASK_DEFAULTS
    ]


def load_login_statuses() -> dict[str, SessionLoginStatus]:
    ensure_dirs()
    if not STATUS_FILE.exists():
        return {}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    statuses: dict[str, SessionLoginStatus] = {}
    for platform, row in data.items():
        statuses[platform] = SessionLoginStatus(
            platform=platform,
            state=row.get("state", "unknown"),
            label=row.get("label", "未检查"),
            message=row.get("message", ""),
            checked_at=row.get("checked_at", ""),
        )
    return statuses


def save_login_status(status: SessionLoginStatus) -> None:
    ensure_dirs()
    data = {
        platform: asdict(row)
        for platform, row in load_login_statuses().items()
    }
    data[status.platform] = asdict(status)
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cached_login_status(platform: str) -> SessionLoginStatus:
    return load_login_statuses().get(
        platform,
        SessionLoginStatus(platform=platform, state="unknown", label="未检查", message="还没有检查该平台登录态。"),
    )


def check_login_status(platform: str, headless: bool = True) -> SessionLoginStatus:
    ensure_dirs()
    spec = PLATFORM_SPECS.get(platform)
    if spec is None:
        status = SessionLoginStatus(platform, "unsupported", "不支持", "暂不支持该平台。", now_iso())
        save_login_status(status)
        return status
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        status = SessionLoginStatus(platform, "error", "无法检查", "缺少 playwright 依赖。", now_iso())
        save_login_status(status)
        return status

    profile_path = PROFILE_DIR / platform
    profile_path.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                headless=headless,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(spec.home_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text(timeout=8000)
                url = page.url
                cookies = context.cookies()
            finally:
                context.close()
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:220]
        if "user data directory is already in use" in message.lower() or "process singleton" in message.lower():
            label = "登录窗口未关闭"
            message = "检测到该平台浏览器会话还开着。请先关闭登录窗口，再检查状态或后台采集。"
            state = "profile_open"
        else:
            label = "无法检查"
            state = "error"
        status = SessionLoginStatus(platform, state, label, message, now_iso())
        save_login_status(status)
        return status

    diagnosis = diagnose_page_text(text, url)
    if is_logged_in(platform, text, url, cookies):
        status = SessionLoginStatus(platform, "logged_in", "已登录", "本地浏览器会话已登录，可以后台采集。", now_iso())
    elif diagnosis.should_pause:
        status = SessionLoginStatus(platform, "blocked", diagnosis.label, diagnosis.message, now_iso())
    else:
        status = SessionLoginStatus(platform, "not_logged_in", "未登录", "未检测到登录态。请点“登录账号”，登录后关闭窗口，再点“检查状态”。", now_iso())
    save_login_status(status)
    return status


def diagnose_page_text(text: str, url: str = "") -> PageDiagnosis:
    lowered = (text or "").lower()
    url_lower = (url or "").lower()
    if any(term in lowered for term in ["验证码", "安全验证", "captcha", "verify", "robot"]):
        return PageDiagnosis("captcha", "需验证", "页面出现验证码或安全验证，已暂停，人工处理后再采集。", True)
    if any(term in lowered for term in ["访问太频繁", "稍后再试", "too many requests", "rate limit", "429"]):
        return PageDiagnosis("rate_limited", "频控", "页面提示访问太频繁或 429，已暂停。建议降低频率，稍后再试。", True)
    if any(term in lowered for term in ["请先登录", "登录后才能", "登录验证", "login required"]):
        return PageDiagnosis("login_required", "需登录", "页面提示需要登录，登录态可能失效。请重新登录后检查状态。", True)
    if any(term in lowered for term in ["账号异常", "账户异常", "account suspended", "account restricted"]):
        return PageDiagnosis("account_risk", "账号异常", "页面提示账号异常，停止采集，交给人工处理。", True)
    if any(term in url_lower for term in ["/login", "passport", "signin"]):
        return PageDiagnosis("login_page", "登录页", "当前跳转到登录页，登录态无效。", True)
    if len((text or "").strip()) < 80:
        return PageDiagnosis("empty_page", "空页面", "页面内容过少，可能加载失败或被拦截。", False)
    return PageDiagnosis("ok", "正常", "页面可读。", False)


def is_logged_in(platform: str, text: str, url: str = "", cookies: list[dict[str, object]] | None = None) -> bool:
    lowered = text.lower()
    cookie_names = {str(cookie.get("name", "")).lower() for cookie in cookies or []}
    if platform == "zhihu":
        if {"z_c0", "d_c0"} & cookie_names:
            return True
        positive = ("私信", "创作中心", "我的主页", "写回答", "写文章")
        negative = ("登录/注册", "登录知乎", "注册知乎")
        return any(item in text for item in positive) and not any(item in text for item in negative)
    if platform == "bilibili":
        if {"sessdata", "bili_jct", "dedeuserid"} & cookie_names:
            return True
        return "个人中心" in text or "动态" in text and "登录" not in text[:800]
    if platform == "weibo":
        if {"sub", "subp", "sso_login_status"} & cookie_names:
            return True
        return "我的首页" in text or "私信" in text or "发微博" in text
    if platform == "tieba":
        if {"bduss", "stoken"} & cookie_names:
            return True
        return "我的i贴吧" in text or "消息" in text and "登录" not in text[:800]
    if platform in {"xiaohongshu", "douyin"}:
        if platform == "xiaohongshu" and {"web_session"} & cookie_names:
            return True
        if platform == "douyin" and {"sessionid", "sid_guard"} & cookie_names:
            return True
        return "登录" not in text[:1200] and any(token in lowered for token in ["profile", "message", "creator"])
    return "登录" not in text[:1200] and "captcha" not in lowered


def open_login_session(platform: str) -> SessionCollectResult:
    task = get_or_default_task(platform)
    return run_session_collection(None, task, login_only=True, headless=False)


def run_enabled_session_collections(
    db: Session,
    platform_limit: int = 2,
    keyword_limit: int = 1,
    per_platform_limit: int = 5,
    headless: bool = True,
) -> dict[str, object]:
    write_progress("starting", message="Preparing session collection batch.")
    results: list[SessionCollectResult] = []
    skipped: list[dict[str, str]] = []
    runnable_tasks = []
    for task in [item for item in load_tasks() if item.enabled]:
        status = cached_login_status(task.platform)
        if status.state != "logged_in":
            skipped.append(
                {
                    "platform": task.platform,
                    "state": status.state,
                    "reason": status.message or "未确认登录态，先登录并检查状态。",
                }
            )
            continue
        runnable_tasks.append(task)

    for task in runnable_tasks[: max(1, platform_limit)]:
        write_progress("running", platform=task.platform, message=f"Starting {task.platform}.")
        limited_task = SessionTask(
            platform=task.platform,
            keywords=",".join(task.keyword_list[: max(1, keyword_limit)]),
            daily_limit=max(1, min(task.daily_limit, per_platform_limit)),
            page_limit=max(1, min(task.page_limit, 1)),
            delay_seconds=max(3, min(task.delay_seconds, 5)),
            enabled=task.enabled,
        )
        result = run_session_collection(db, limited_task, headless=headless)
        results.append(result)
        if result.paused:
            time.sleep(2)
    total_inserted = sum(item.inserted for item in results)
    prospects = rebuild_prospects(db)["prospects"] if total_inserted else 0
    payload = {
        "platforms": len(results),
        "fetched": sum(item.fetched for item in results),
        "inserted": total_inserted,
        "paused": sum(1 for item in results if item.paused),
        "prospects_rebuilt": prospects if total_inserted else 0,
        "skipped": skipped,
        "results": [asdict(item) for item in results],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_run_log(payload)
    write_progress(
        "done",
        fetched=sum(item.fetched for item in results),
        inserted=total_inserted,
        candidates=sum(item.candidates for item in results),
        rejected=sum(item.rejected for item in results),
        high_quality=sum(item.high_quality for item in results),
        message=f"Batch finished. Platforms {len(results)}, inserted {total_inserted}, skipped {len(skipped)}.",
    )
    return payload


def run_session_smoke_test(db: Session, task: SessionTask, headless: bool = True) -> SessionCollectResult:
    """Run a tiny, low-risk collection to verify login, search and extraction."""
    first_keyword = next(iter(task.keyword_list), "")
    limited_task = SessionTask(
        platform=task.platform,
        keywords=first_keyword or task.keywords,
        daily_limit=5,
        page_limit=1,
        delay_seconds=max(8, min(task.delay_seconds, 15)),
        enabled=task.enabled,
    )
    write_progress(
        "queued",
        platform=task.platform,
        keyword=first_keyword,
        message=f"{PLATFORM_LABELS.get(task.platform, task.platform)} 单平台试跑已排队：1 个关键词，最多 5 条。",
    )
    result = run_session_collection(db, limited_task, headless=headless)
    return result


def load_run_logs(limit: int = 100) -> list[dict[str, object]]:
    ensure_dirs()
    if not RUN_LOG_FILE.exists():
        return []
    try:
        rows = json.loads(RUN_LOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [row for row in rows[-max(1, limit):] if isinstance(row, dict)]


def recent_session_events(limit: int = 12) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for log in reversed(load_run_logs(80)):
        generated_at = str(log.get("generated_at", "") or "")
        kind = str(log.get("kind", "collection") or "collection")
        skipped = log.get("skipped", [])
        if isinstance(skipped, list):
            for item in skipped:
                if not isinstance(item, dict):
                    continue
                platform = str(item.get("platform", "") or "")
                events.append(
                    {
                        "time": generated_at,
                        "kind": "skipped",
                        "platform": platform,
                        "platform_label": PLATFORM_LABELS.get(platform, platform),
                        "status": "跳过",
                        "fetched": 0,
                        "inserted": 0,
                        "candidates": 0,
                        "rejected": 0,
                        "failure_code": str(item.get("state", "") or ""),
                        "message": str(item.get("reason", "") or ""),
                    }
                )
                if len(events) >= limit:
                    return events
        results = log.get("results", [])
        if not isinstance(results, list):
            continue
        for result in reversed(results):
            if not isinstance(result, dict):
                continue
            platform = str(result.get("platform", "") or "")
            paused = bool(result.get("paused"))
            inserted = int(result.get("inserted", 0) or 0)
            status = "暂停" if paused else ("有入库" if inserted else "完成")
            events.append(
                {
                    "time": generated_at,
                    "kind": kind,
                    "platform": platform,
                    "platform_label": PLATFORM_LABELS.get(platform, platform),
                    "status": status,
                    "fetched": int(result.get("fetched", 0) or 0),
                    "inserted": inserted,
                    "candidates": int(result.get("candidates", 0) or 0),
                    "rejected": int(result.get("rejected", 0) or 0),
                    "high_quality": int(result.get("high_quality", 0) or 0),
                    "failure_code": str(result.get("failure_code", "") or ""),
                    "message": str(result.get("message", "") or "")[:180],
                }
            )
            if len(events) >= limit:
                return events
    return events[:limit]


def write_progress(
    state: str,
    platform: str = "",
    keyword: str = "",
    fetched: int = 0,
    inserted: int = 0,
    candidates: int = 0,
    rejected: int = 0,
    high_quality: int = 0,
    message: str = "",
    failure_code: str = "",
) -> None:
    ensure_dirs()
    progress = SessionProgress(
        state=state,
        platform=platform,
        keyword=keyword,
        fetched=fetched,
        inserted=inserted,
        candidates=candidates,
        rejected=rejected,
        high_quality=high_quality,
        message=message,
        updated_at=now_iso(),
        failure_code=failure_code,
    )
    PROGRESS_FILE.write_text(json.dumps(asdict(progress), ensure_ascii=False, indent=2), encoding="utf-8")


def load_progress() -> SessionProgress:
    ensure_dirs()
    if not PROGRESS_FILE.exists():
        return SessionProgress("idle", "", "", 0, 0, 0, 0, 0, "还没有后台采集运行记录。", "")
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return SessionProgress("unknown", "", "", 0, 0, 0, 0, 0, "运行状态文件损坏，下一次采集会自动覆盖。", now_iso())
    return SessionProgress(
        state=str(data.get("state", "unknown")),
        platform=str(data.get("platform", "")),
        keyword=str(data.get("keyword", "")),
        fetched=int(data.get("fetched", 0) or 0),
        inserted=int(data.get("inserted", 0) or 0),
        candidates=int(data.get("candidates", 0) or 0),
        rejected=int(data.get("rejected", 0) or 0),
        high_quality=int(data.get("high_quality", 0) or 0),
        message=str(data.get("message", "")),
        updated_at=str(data.get("updated_at", "")),
        failure_code=str(data.get("failure_code", "") or ""),
    )


SESSION_STATE_LABELS = {
    "queued": "已排队",
    "starting": "启动中",
    "running": "采集中",
    "done": "已完成",
    "paused": "已暂停",
    "idle": "空闲",
    "unknown": "未知",
}


def normalize_failure_code(code: str = "", message: str = "") -> str:
    raw = (code or "").strip()
    lowered = f"{raw} {message or ''}".lower()
    if raw in DIAGNOSTIC_GUIDE:
        return raw
    if any(token in lowered for token in ["captcha", "verify", "验证码", "安全验证", "人机"]):
        return "captcha"
    if any(token in lowered for token in ["rate", "429", "too many", "访问频繁", "稍后再试", "频控"]):
        return "rate_limited"
    if any(token in lowered for token in ["login", "登录页", "请先登录", "登录后"]):
        return "login_required"
    if any(token in lowered for token in ["selector", "结构", "card", "解析"]):
        return "page_structure_changed"
    if any(token in lowered for token in ["profile", "user data directory", "process singleton"]):
        return "profile_open"
    return raw or "none"


def session_failure_detail(code: str = "", message: str = "") -> dict[str, str]:
    normalized = normalize_failure_code(code, message)
    detail = dict(DIAGNOSTIC_GUIDE.get(normalized, DIAGNOSTIC_GUIDE["exception"]))
    detail["code"] = normalized
    if message and normalized not in {"none", "not_logged_in"}:
        detail["reason"] = f"{detail['reason']} 最近消息：{message[:160]}"
    return detail


def session_progress_detail() -> dict[str, object]:
    progress = load_progress()
    platform_label = PLATFORM_LABELS.get(progress.platform, progress.platform) if progress.platform else ""
    failure_code = progress.failure_code
    last_event: dict[str, object] = {}
    active = progress.state in {"queued", "starting", "running"}
    if not active:
        for event in recent_session_events(20):
            if progress.platform and event.get("platform") != progress.platform:
                continue
            last_event = event
            break
        if not failure_code and last_event:
            failure_code = str(last_event.get("failure_code", "") or "")
    message = progress.message or str(last_event.get("message", "") or "")
    detail = session_failure_detail(failure_code, message)
    state_label = SESSION_STATE_LABELS.get(progress.state, progress.state or "未知")
    return {
        "state": progress.state,
        "state_label": state_label,
        "platform": progress.platform,
        "platform_label": platform_label,
        "keyword": progress.keyword,
        "fetched": progress.fetched,
        "inserted": progress.inserted,
        "candidates": progress.candidates,
        "rejected": progress.rejected,
        "high_quality": progress.high_quality,
        "message": message,
        "updated_at": progress.updated_at,
        "failure_code": "" if detail["code"] == "none" else detail["code"],
        "failure_label": "" if detail["code"] == "none" else detail["label"],
        "failure_reason": "" if detail["code"] == "none" else detail["reason"],
        "next_step": detail["next_step"],
    }


def build_session_platform_diagnostics(db: Session) -> list[SessionPlatformDiagnostic]:
    tasks = {task.platform: task for task in load_tasks()}
    logs = load_run_logs(200)
    rows: list[SessionPlatformDiagnostic] = []
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.source_kind == "session_browser")
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.discovered_at))
        )
    )
    for platform, spec in PLATFORM_SPECS.items():
        task = tasks.get(platform) or get_or_default_task(platform)
        status = cached_login_status(platform)
        label_prefix = f"Session {spec.label}:"
        platform_mentions = [mention for mention in mentions if mention.source_name.startswith(label_prefix)]
        run_results = session_run_results(logs, platform)
        fetched = sum(int(row.get("fetched", 0) or 0) for row in run_results)
        inserted = sum(int(row.get("inserted", 0) or 0) for row in run_results)
        candidates = sum(int(row.get("candidates", 0) or 0) for row in run_results)
        rejected = sum(int(row.get("rejected", 0) or 0) for row in run_results)
        high_quality_session = sum(int(row.get("high_quality", 0) or 0) for row in run_results)
        paused = sum(1 for row in run_results if row.get("paused"))
        last_result = run_results[-1] if run_results else {}
        last_run_at = str(last_result.get("generated_at", "") or "")
        last_message = str(last_result.get("message", "") or status.message or "")
        failure_code = str(last_result.get("failure_code", "") or "")
        health = classify_session_health(status.state, run_results, len(platform_mentions), paused)
        detail = session_diagnostic_detail(
            login_state=status.state,
            health=health,
            failure_code=failure_code,
            last_message=last_message,
            runs=len(run_results),
            inserted=inserted,
            candidates=candidates,
            rejected=rejected,
        )
        strategy = PLATFORM_STRATEGIES.get(platform, {})
        rows.append(
            SessionPlatformDiagnostic(
                platform=platform,
                label=spec.label,
                login_label=status.label,
                login_state=status.state,
                last_checked_at=status.checked_at,
                task_enabled=task.enabled,
                keyword_count=len(task.keyword_list),
                daily_limit=task.daily_limit,
                delay_seconds=task.delay_seconds,
                runs=len(run_results),
                fetched=fetched,
                inserted=inserted,
                candidates=candidates,
                rejected=rejected,
                high_quality_session=high_quality_session,
                paused=paused,
                recent_mentions=len(platform_mentions[:50]),
                high_value_mentions=sum(1 for mention in platform_mentions if mention.score >= 60),
                last_run_at=last_run_at,
                last_message=last_message[:220],
                health=health,
                action=session_health_action(health, status.state, len(run_results), inserted, paused),
                failure_code=failure_code,
                diagnostic_label=detail["label"],
                diagnostic_reason=detail["reason"],
                next_step=detail["next_step"],
                strategy_tier=strategy.get("tier", "观察"),
                strategy_risk=strategy.get("risk", "-"),
                strategy_mode=strategy.get("mode", "小批量试跑"),
                strategy_note=strategy.get("note", ""),
            )
        )
    return rows


def session_diagnostic_detail(
    *,
    login_state: str,
    health: str,
    failure_code: str,
    last_message: str,
    runs: int,
    inserted: int,
    candidates: int,
    rejected: int,
) -> dict[str, str]:
    code = failure_code or "none"
    if login_state in {"blocked", "profile_open", "not_logged_in", "unknown"}:
        code = login_state
    elif health == "受阻":
        code = failure_code or "blocked"
    elif health == "低质过滤":
        code = "quality_filtered"
    elif health == "无候选":
        code = "no_candidates"
    elif runs == 0:
        return {
            "label": "未试跑",
            "reason": "登录态可用但还没有实际搜索采集记录。",
            "next_step": "点击“试跑”，用 1 个关键词采 3-5 条验证链路。",
        }
    elif candidates > 0 and inserted == 0 and rejected > 0:
        code = "quality_filtered"

    detail = dict(DIAGNOSTIC_GUIDE.get(code, DIAGNOSTIC_GUIDE["none"]))
    if last_message and code not in {"none", "not_logged_in"}:
        detail["reason"] = f"{detail['reason']} 最近消息：{last_message[:120]}"
    return detail


def session_run_results(logs: list[dict[str, object]], platform: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for log in logs:
        generated_at = str(log.get("generated_at", "") or "")
        for result in log.get("results", []) if isinstance(log.get("results"), list) else []:
            if not isinstance(result, dict) or result.get("platform") != platform:
                continue
            row = dict(result)
            row["generated_at"] = generated_at
            rows.append(row)
    return rows[-20:]


def classify_session_health(login_state: str, run_results: list[dict[str, object]], mentions: int, paused: int) -> str:
    if login_state in {"blocked", "profile_open", "error"}:
        return "需处理"
    if login_state in {"not_logged_in", "unknown"}:
        return "未就绪"
    if paused and not any(int(row.get("inserted", 0) or 0) for row in run_results[-3:]):
        return "受阻"
    if run_results and any(str(row.get("failure_code", "")) == "quality_filtered" for row in run_results[-3:]):
        return "低质过滤"
    if run_results and any(str(row.get("failure_code", "")) == "no_candidates" for row in run_results[-3:]):
        return "无候选"
    if mentions > 0 or any(int(row.get("inserted", 0) or 0) for row in run_results[-5:]):
        return "可采集"
    if login_state == "logged_in" and run_results:
        return "低产"
    if login_state == "logged_in":
        return "待试跑"
    return "观察"


def session_health_action(health: str, login_state: str, runs: int, inserted: int, paused: int) -> str:
    if login_state == "profile_open":
        return "先关闭登录窗口，再检查状态或后台采集。"
    if login_state in {"not_logged_in", "unknown"}:
        return "先点登录账号，登录后关闭窗口，再检查状态。"
    if health == "需处理":
        return "人工处理验证码、登录失效或频控提示，处理后再低频采集。"
    if health == "受阻":
        return "暂停该平台，降低频率或换更精准关键词，避免反复触发风控。"
    if health == "低产":
        return "登录态可用但产出低，优先同步推荐任务或换强意图关键词。"
    if health == "低质过滤":
        return "页面能读到内容，但 P3 过滤较多；换更具体的痛点词，例如“店铺关联 IP”“Cloudflare 403”。"
    if health == "无候选":
        return "页面结构可能变化或关键词无结果；先换词，再检查平台是否改版。"
    if health == "待试跑":
        return "状态可用但还没跑过，先单平台小批量采集。"
    if inserted > 0:
        return "继续小批量采集，并把高分结果推到补联系方式。"
    if runs == 0:
        return "还没有采集记录，先试跑一次。"
    return "继续观察。"


def run_session_collection(
    db: Session | None,
    task: SessionTask,
    login_only: bool = False,
    headless: bool = False,
) -> SessionCollectResult:
    ensure_dirs()
    write_progress("starting", platform=task.platform, message="Starting session collector.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result = SessionCollectResult(task.platform, 0, 0, True, "缺少 playwright 依赖，无法会话采集。", failure_code="missing_playwright")
        append_session_result(result)
        write_progress("paused", platform=task.platform, message=result.message, failure_code=result.failure_code)
        return result

    spec = PLATFORM_SPECS.get(task.platform)
    if spec is None:
        result = SessionCollectResult(task.platform, 0, 0, True, "暂不支持该平台。", failure_code="unsupported_platform")
        append_session_result(result)
        write_progress("paused", platform=task.platform, message=result.message, failure_code=result.failure_code)
        return result

    if not login_only:
        status = cached_login_status(task.platform)
        if status.state != "logged_in":
            message = session_not_ready_message(status)
            result = SessionCollectResult(task.platform, 0, 0, True, message, failure_code=status.state or "not_ready")
            append_session_result(result)
            write_progress("paused", platform=task.platform, message=message, failure_code=result.failure_code)
            return result

    profile_path = PROFILE_DIR / task.platform
    profile_path.mkdir(parents=True, exist_ok=True)
    fetched = 0
    inserted = 0
    candidates = 0
    rejected = 0
    high_quality = 0
    failure_code = ""
    paused = False
    message = "完成"
    context = None

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                headless=headless,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else context.new_page()

            if login_only:
                page.goto(spec.home_url, wait_until="domcontentloaded", timeout=60000)
                message = "已打开登录窗口。请手动登录，登录完成后关闭浏览器，再回到后台点“检查状态”。"
                page.wait_for_timeout(120000)
                try:
                    text = page.locator("body").inner_text(timeout=5000)
                    if is_logged_in(task.platform, text, page.url):
                        save_login_status(
                            SessionLoginStatus(task.platform, "logged_in", "已登录", "本地浏览器会话已登录，可以后台采集。", now_iso())
                        )
                    else:
                        save_login_status(
                            SessionLoginStatus(task.platform, "unknown", "未确认", "登录窗口已打开过，但未确认登录态。请点“检查状态”。", now_iso())
                        )
                except Exception:  # noqa: BLE001
                    save_login_status(
                        SessionLoginStatus(task.platform, "unknown", "未确认", "登录窗口可能已关闭。请点“检查状态”确认是否登录成功。", now_iso())
                    )
                return SessionCollectResult(task.platform, 0, 0, False, message)

            if db is None:
                result = SessionCollectResult(task.platform, 0, 0, True, "缺少数据库会话，无法后台采集。", failure_code="no_db")
                append_session_result(result)
                return result

            active_keywords = list(
                db.scalars(select(Keyword).where(Keyword.enabled.is_(True)).order_by(Keyword.weight.desc()))
            )
            budget = max(1, task.daily_limit)
            keywords = task.keyword_list
            per_keyword_budget = max(3, min(12, (budget + max(1, len(keywords)) - 1) // max(1, len(keywords))))
            for keyword in keywords:
                if fetched >= budget:
                    break
                keyword_fetched = 0
                search_url = spec.search_url.format(keyword=quote(keyword))
                write_progress(
                    "running",
                    platform=task.platform,
                    keyword=keyword,
                    fetched=fetched,
                    inserted=inserted,
                    candidates=candidates,
                    rejected=rejected,
                    high_quality=high_quality,
                    message="Opening search page.",
                )
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(max(3, task.delay_seconds) * 1000)

                for _ in range(max(1, min(8, task.page_limit))):
                    text = page.locator("body").inner_text(timeout=10000)
                    diagnosis = diagnose_page_text(text, page.url)
                    if diagnosis.should_pause:
                        paused = True
                        failure_code = diagnosis.code
                        message = diagnosis.message
                        write_progress(
                            "paused",
                            platform=task.platform,
                            keyword=keyword,
                            fetched=fetched,
                            inserted=inserted,
                            candidates=candidates,
                            rejected=rejected,
                        high_quality=high_quality,
                        message=message,
                        failure_code=failure_code,
                    )
                        save_login_status(
                            SessionLoginStatus(task.platform, "blocked", diagnosis.label, message, now_iso())
                        )
                        break

                    extraction = extract_items_with_stats(page, spec, keyword)
                    candidates += extraction.candidates
                    rejected += extraction.rejected
                    high_quality += extraction.high_quality
                    write_progress(
                        "running",
                        platform=task.platform,
                        keyword=keyword,
                        fetched=fetched,
                        inserted=inserted,
                        candidates=candidates,
                        rejected=rejected,
                        high_quality=high_quality,
                        message=f"Extracted {extraction.candidates} candidates, usable {len(extraction.items)}.",
                    )
                    for item in extraction.items:
                        if fetched >= budget or keyword_fetched >= per_keyword_budget:
                            break
                        fetched += 1
                        keyword_fetched += 1
                        mention = insert_item(db, item, active_keywords)
                        if mention is not None:
                            inserted += 1

                    if fetched >= budget or keyword_fetched >= per_keyword_budget or paused:
                        break
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(max(2, task.delay_seconds) * 1000)
                if paused:
                    break
                time.sleep(max(1, task.delay_seconds))
    except Exception as exc:  # noqa: BLE001
        paused = True
        message = str(exc)[:300] or exc.__class__.__name__
        failure_code = "exception"
        lowered = message.lower()
        if "user data directory is already in use" in lowered or "process singleton" in lowered:
            failure_code = "profile_open"
            message = "登录窗口还开着，浏览器 profile 被占用。请先关闭登录窗口，再点后台采集。"
            save_login_status(SessionLoginStatus(task.platform, "profile_open", "登录窗口未关闭", message, now_iso()))
        write_progress(
            "paused",
            platform=task.platform,
            fetched=fetched,
            inserted=inserted,
            candidates=candidates,
            rejected=rejected,
            high_quality=high_quality,
            message=message,
            failure_code=failure_code,
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass

    if inserted and db is not None:
        rebuild_prospects(db)
    if not paused:
        save_login_status(
            SessionLoginStatus(task.platform, "logged_in", "已登录", "本次后台采集已完成，登录态可用。", now_iso())
        )
    if not paused and candidates == 0:
        failure_code = "no_candidates"
        message = "页面可访问，但没有抽取到候选结果。建议检查关键词或平台页面结构。"
    elif not paused and inserted == 0 and rejected > 0:
        failure_code = "quality_filtered"
        message = f"候选结果已读取，但被 P3 质量规则过滤 {rejected} 条。"
    result = SessionCollectResult(
        task.platform,
        fetched,
        inserted,
        paused,
        message,
        candidates=candidates,
        rejected=rejected,
        high_quality=high_quality,
        failure_code=failure_code,
    )
    append_session_result(result)
    write_progress(
        "paused" if result.paused else "done",
        platform=task.platform,
        fetched=fetched,
        inserted=inserted,
        candidates=candidates,
        rejected=rejected,
        high_quality=high_quality,
        message=message,
        failure_code=result.failure_code,
    )
    return result


def append_session_result(result: SessionCollectResult) -> None:
    append_run_log({"generated_at": datetime.now().isoformat(timespec="seconds"), "results": [asdict(result)]})


def session_not_ready_message(status: SessionLoginStatus) -> str:
    if status.state == "blocked":
        return "该平台当前标记为需处理：请先人工处理验证码、登录失效或频控提示，再检查状态。"
    if status.state == "profile_open":
        return "登录窗口还开着，profile 被占用。请先关闭该平台登录窗口，再检查状态。"
    if status.state == "not_logged_in":
        return "该平台未登录。请先点“登录账号”，登录完成后关闭窗口，再点“检查状态”。"
    if status.state == "unknown":
        return "该平台登录态未确认。请先点“检查状态”，确认已登录后再后台采集。"
    return status.message or "该平台暂不可采集，请先确认登录状态。"

def extract_items(page, spec: PlatformSpec, keyword: str) -> list[RawItem]:
    return extract_items_with_stats(page, spec, keyword).items


def parse_session_published_at(date_text: str, content: str) -> datetime | None:
    parsed = parse_text_date("\n".join([date_text or "", content or ""]))
    if parsed is not None:
        return parsed
    match = re.search(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)", "\n".join([date_text or "", content or ""]))
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    now = datetime.now()
    try:
        inferred = datetime(now.year, month, day)
    except ValueError:
        return None
    if inferred.date() > (now + timedelta(days=7)).date():
        try:
            inferred = datetime(now.year - 1, month, day)
        except ValueError:
            return None
    return inferred


def extract_items_with_stats(page, spec: PlatformSpec, keyword: str) -> ExtractionResult:
    source_name = f"Session {spec.label}: {keyword}"
    raw_items = page.evaluate(
        """
        ({ selectors, authorSelectors, platform }) => {
          const cards = [];
          const seen = new Set();
          const userLinkPatterns = {
            zhihu: ['/people/'],
            xiaohongshu: ['/user/profile/'],
            douyin: ['/user/'],
            bilibili: ['space.bilibili.com/'],
            weibo: ['/u/']
          };
          const authorFromLinks = (node) => {
            const patterns = userLinkPatterns[platform] || [];
            for (const link of Array.from(node.querySelectorAll('a[href]'))) {
              const href = link.href || '';
              if (!patterns.some((pattern) => href.includes(pattern))) continue;
              const text = (link.innerText || link.textContent || '').trim().replace(/\\s+/g, ' ');
              if (text && text.length <= 60) return text;
              const label = (link.getAttribute('aria-label') || link.getAttribute('title') || '').trim();
              if (label && label.length <= 60) return label;
            }
            return '';
          };
          for (const selector of selectors) {
            for (const node of Array.from(document.querySelectorAll(selector))) {
              if (seen.has(node)) continue;
              seen.add(node);
              const box = node.getBoundingClientRect();
              if (box.width < 80 || box.height < 20) continue;
              const anchor = node.matches && node.matches('a[href]')
                ? node
                : node.querySelector('a[href]');
              if (!anchor) continue;
              const title = (anchor.innerText || anchor.textContent || '').trim().replace(/\\s+/g, ' ');
              const href = anchor.href || '';
              const content = (node.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 1600);
              let author = '';
              for (const authorSelector of authorSelectors) {
                const authorNode = node.querySelector(authorSelector);
                if (authorNode) {
                  author = (authorNode.innerText || authorNode.textContent || '').trim().replace(/\\s+/g, ' ');
                  break;
                }
              }
              if (!author) author = authorFromLinks(node);
              const dateText = content.match(/20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}/)?.[0] || '';
              cards.push({ title, url: href, content, author, dateText });
              if (cards.length >= 80) return cards;
            }
          }
          for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
            const title = (anchor.innerText || anchor.textContent || '').trim().replace(/\\s+/g, ' ');
            const href = anchor.href || '';
            if (!title || !href) continue;
            const parent = anchor.closest('article, li, section, div');
            const content = parent ? (parent.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 1600) : title;
            const author = parent ? authorFromLinks(parent) : '';
            const dateText = content.match(/20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}/)?.[0] || '';
            cards.push({ title, url: href, content, author, dateText });
            if (cards.length >= 120) break;
          }
          return cards;
        }
        """,
        {"selectors": list(spec.card_selectors), "authorSelectors": list(spec.author_selectors), "platform": spec.key},
    )
    items: list[RawItem] = []
    seen: set[str] = set()
    candidates = 0
    rejected = 0
    high_quality = 0
    for row in raw_items:
        url = normalize_url(row.get("url", ""))
        title = clean_title(row.get("title", ""))
        content = clean_content(row.get("content", ""))
        if not url or not title:
            continue
        candidates += 1
        published_at = parse_session_published_at(str(row.get("dateText", "") or ""), content)
        freshness = freshness_decision(
            published_at=published_at,
            title=title,
            content=content,
            url=url,
        )
        if not freshness.allowed:
            rejected += 1
            continue
        quality_level = candidate_quality_level(spec, title, url, content)
        if not is_usable_candidate(spec, keyword, title, url, content, quality_level=quality_level):
            rejected += 1
            continue
        p3_quality = evaluate_lead_quality(
            title=title,
            content=f"{content}\n关键词: {keyword}",
            url=url,
            source_name=source_name,
        )
        if p3_quality.reject:
            rejected += 1
            continue
        if p3_quality.tier in {"A", "B"}:
            high_quality += 1
        key = canonical_candidate_key(url, title)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            RawItem(
                source_name=source_name,
                source_kind="session_browser",
                title=title[:300],
                url=url,
                author=clean_author(row.get("author", ""))[:160],
                content=(
                    f"平台: {spec.label}\n"
                    f"关键词: {keyword}\n"
                    f"质量层级: {quality_level}\n"
                    f"P3质量: {p3_quality.tier}/{p3_quality.quality_score}\n"
                    f"P3原因: {'；'.join(p3_quality.reasons[:4])}\n"
                    f"{content}"
                )[:5000],
                published_at=freshness.published_at,
            )
        )
        if len(items) >= 30:
            break
    return ExtractionResult(items=items, candidates=candidates, rejected=rejected, high_quality=high_quality)


def is_usable_candidate(
    spec: PlatformSpec,
    keyword: str,
    title: str,
    url: str,
    content: str,
    quality_level: str | None = None,
) -> bool:
    if not url or not title:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(host == allowed or host.endswith("." + allowed) for allowed in spec.allowed_hosts):
        return False
    text = f"{title}\n{content}".lower()
    if len(title) < 6 or len(text) < 20:
        return False
    if any(term.lower() in title.lower() for term in NOISE_TERMS) and not any(
        term.lower() in text for term in DEMAND_TERMS
    ):
        return False
    keyword_parts = [part.lower() for part in re.split(r"\s+", keyword) if part.strip()]
    has_keyword = any(part and part in text for part in keyword_parts)
    has_demand = any(term.lower() in text for term in DEMAND_TERMS)
    if not (has_keyword or has_demand):
        return False
    return (quality_level or candidate_quality_level(spec, title, url, content)) != "剔除"


def is_high_quality_lead_candidate(spec: PlatformSpec, title: str, url: str, content: str) -> bool:
    return candidate_quality_level(spec, title, url, content) == "高意向"


def candidate_quality_level(spec: PlatformSpec, title: str, url: str, content: str) -> str:
    text = f"{title}\n{content}".lower()
    title_lower = title.lower()
    parsed = urlparse(url)
    path = parsed.path.lower()

    if any(term.lower() in text for term in SUPPLIER_AD_TERMS):
        return "剔除"

    p3_quality = evaluate_lead_quality(
        title=title,
        content=content,
        url=url,
        source_name=f"Session {spec.label}",
    )

    has_intent = any(term.lower() in text for term in HIGH_QUALITY_INTENT_TERMS)
    title_has_intent = any(term.lower() in title_lower for term in HIGH_QUALITY_INTENT_TERMS)
    has_context = any(term.lower() in text for term in HIGH_QUALITY_CONTEXT_TERMS)
    title_has_context = any(term.lower() in title_lower for term in HIGH_QUALITY_CONTEXT_TERMS)
    has_pain_scene = any(term.lower() in text for term in PAIN_SCENE_TERMS)
    title_has_pain_scene = any(term.lower() in title_lower for term in PAIN_SCENE_TERMS)
    commercial_terms = [
        "工作室",
        "团队",
        "店群",
        "矩阵",
        "多账号",
        "多店铺",
        "本土店",
        "小店",
        "铺货",
        "账号注册",
        "养号",
        "采集",
        "爬虫",
        "指纹浏览器",
    ]
    has_commercial_context = any(term.lower() in text for term in commercial_terms)
    title_has_commercial_context = any(term.lower() in title_lower for term in commercial_terms)
    has_action_question = "?" in title or "？" in title or any(
        term in title for term in ["怎么办", "怎么解决", "怎么配", "怎么选", "求", "请教", "有没有", "哪里找"]
    )
    has_low_quality_title = any(term.lower() in title_lower for term in LOW_QUALITY_CONTENT_TERMS)
    is_tutorial_only = any(
        term in title for term in ["教程", "入门", "新手", "学习", "原理", "详解", "完整指南", "保姆级"]
    ) and not (has_pain_scene or has_commercial_context or has_action_question)

    if spec.key == "zhihu":
        if path.startswith("/search"):
            return "剔除"
        if "zhuanlan.zhihu.com" in parsed.netloc:
            return "剔除"
        if not p3_quality.reject and p3_quality.tier == "A":
            return "高意向"
        if not p3_quality.reject and p3_quality.tier == "B":
            return "待复核"
        if has_low_quality_title or is_tutorial_only:
            return "剔除"
        if has_context and title_has_intent and has_action_question and (has_pain_scene or has_commercial_context):
            return "高意向"
        if title_has_context and title_has_pain_scene and (has_commercial_context or title_has_commercial_context):
            return "待复核"
        if title_has_context and title_has_intent and has_action_question:
            return "待复核"
        return "剔除"

    if not p3_quality.reject and p3_quality.tier == "A":
        return "高意向"
    if not p3_quality.reject and p3_quality.tier == "B":
        return "待复核"
    if (has_low_quality_title or is_tutorial_only) and not (has_intent and has_pain_scene):
        return "剔除"
    if has_context and has_intent and has_action_question and (has_pain_scene or has_commercial_context):
        return "高意向"
    if title_has_context and (title_has_intent or title_has_pain_scene) and (has_commercial_context or title_has_commercial_context):
        return "待复核"
    return "剔除"


def should_pause(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in PAUSE_PATTERNS)


def get_or_default_task(platform: str) -> SessionTask:
    for task in load_tasks():
        if task.platform == platform:
            return task
    return SessionTask(platform, "动态住宅代理,TikTok IP 防关联,亚马逊 IP 关联")


def platform_home_url(platform: str) -> str:
    spec = PLATFORM_SPECS.get(platform)
    return spec.home_url if spec else "https://www.baidu.com/"


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def clean_content(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def clean_author(value: str) -> str:
    value = clean_title(value)
    return value if len(value) <= 80 else ""


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        return "https:" + url
    return url


def canonical_candidate_key(url: str, title: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}|{title[:60].lower()}"


def append_run_log(payload: dict[str, object]) -> None:
    ensure_dirs()
    rows = []
    if RUN_LOG_FILE.exists():
        try:
            rows = json.loads(RUN_LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows = []
    rows.append(payload)
    RUN_LOG_FILE.write_text(json.dumps(rows[-100:], ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    SESSION_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
