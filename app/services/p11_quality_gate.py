from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.schemas import RawItem
from app.services.freshness import MIN_LEAD_YEAR, freshness_decision


TARGET_PERSONAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tiktok_studio": (
        "TikTok 矩阵/小店团队",
        ("tiktok", "tk", "小店", "直播", "带货", "矩阵", "养号", "本土店", "跨境店"),
    ),
    "amazon_multi_account": (
        "亚马逊多账号/铺货团队",
        ("亚马逊", "amazon", "sellercentral", "卖家", "铺货", "多店铺", "店铺关联", "防关联"),
    ),
    "shopee_lazada_studio": (
        "Shopee/Lazada 店群团队",
        ("shopee", "lazada", "shein", "虾皮", "东南亚", "店群", "多店", "铺货"),
    ),
    "account_service_studio": (
        "账号注册/养号服务商",
        ("账号注册", "批量注册", "养号", "过验证", "接码", "注册工作室", "账号服务"),
    ),
    "crawler_data_team": (
        "爬虫/数据采集团队",
        ("爬虫", "数据采集", "采集", "抓取", "scrapy", "playwright", "puppeteer", "selenium", "spider"),
    ),
    "fingerprint_browser_user": (
        "指纹浏览器/防关联用户",
        ("指纹浏览器", "adspower", "dolphin anty", "multilogin", "比特浏览器", "候鸟浏览器", "环境隔离", "浏览器环境"),
    ),
    "social_matrix": (
        "海外社媒矩阵团队",
        ("facebook", "instagram", "youtube", "twitter", "x.com", "社媒矩阵", "海外社媒", "fb", "ig"),
    ),
}

DYNAMIC_RESIDENTIAL_TERMS = (
    "动态住宅",
    "动态住宅ip",
    "动态住宅 ip",
    "动态住宅代理",
    "海外动态住宅",
    "住宅ip",
    "住宅 ip",
    "住宅代理",
    "轮换住宅",
    "旋转住宅",
    "粘性住宅",
    "socks5住宅",
    "socks5 住宅",
    "residential proxy",
    "rotating residential",
    "dynamic residential",
    "mobile proxy",
)

SCENARIO_TERMS = (
    "防关联",
    "账号关联",
    "店铺关联",
    "多账号",
    "多店铺",
    "店群",
    "矩阵",
    "养号",
    "批量注册",
    "登录环境",
    "环境异常",
    "指纹浏览器",
    "账号环境",
    "爬虫",
    "数据采集",
    "cloudflare",
    "验证码",
    "封号",
    "封ip",
    "ip被封",
    "ip 不稳定",
    "403",
    "429",
    "captcha",
    "blocked",
    "banned",
    "rate limit",
)

BUYING_INTENT_TERMS = (
    "求推荐",
    "有没有",
    "哪里买",
    "哪家",
    "怎么买",
    "采购",
    "报价",
    "价格",
    "试用",
    "测试包",
    "找代理",
    "需要代理",
    "求渠道",
    "求靠谱",
    "求方案",
    "换供应商",
    "替代",
    "能不能测",
    "looking for",
    "recommend",
    "where to buy",
)

PAIN_TERMS = (
    "不稳定",
    "被封",
    "封ip",
    "ip被封",
    "封号",
    "验证码",
    "风控",
    "关联",
    "防关联",
    "限流",
    "环境异常",
    "登录环境异常",
    "频繁验证",
    "过不去",
    "一直验证",
    "请求太频繁",
    "cloudflare",
    "403",
    "429",
    "captcha",
    "blocked",
    "banned",
)

COMMERCIAL_CONTEXT_TERMS = (
    "工作室",
    "团队",
    "店群",
    "矩阵",
    "多账号",
    "多店铺",
    "批量",
    "并发",
    "长期",
    "月付",
    "消耗",
    "业务",
    "运营",
    "投放",
    "复购",
)

LOW_FIT_TERMS = (
    "静态住宅",
    "固定住宅",
    "固定ip",
    "固定 ip",
    "长效ip",
    "长效 ip",
    "isp proxy",
    "static residential",
    "dedicated residential",
    "机房代理",
    "数据中心代理",
    "免费代理",
    "vpn",
    "机场",
    "科学上网",
)

NOISE_TERMS = (
    "教程",
    "新手教程",
    "完整教程",
    "保姆级",
    "入门",
    "学习",
    "原理",
    "详解",
    "指南",
    "测评",
    "横评",
    "排行榜",
    "优惠码",
    "新闻",
    "资讯",
    "日报",
    "周报",
    "月报",
    "研报",
    "行业报告",
    "官网文章",
    "新品发布",
    "招聘",
    "岗位",
    "内推",
    "简历",
    "源码",
    "毕业设计",
    "api key",
    "openai key",
    "deepseek",
    "虚拟信用卡",
    "虚拟手机",
    "云手机",
    "指纹手机",
    "技术剖析",
    "完整内容",
    "安全支付",
    "重塑跨境电商效率",
    "方案重塑",
    "python爬虫基础",
    "正则表达式",
    "beautifulsoup",
    "setup guide",
    "stable account growth",
    "全球物流查询",
    "工具导航",
    "导航",
)

SUPPLIER_AD_TERMS = (
    "全网低价",
    "限时优惠",
    "免费测试",
    "免费试用",
    "试用活动",
    "注册即送",
    "注册领",
    "联系客服",
    "套餐价格",
    "购买链接",
    "服务商官网",
    "代理ip服务商",
    "住宅ip服务商",
    "住宅代理服务商",
    "必备",
    "完整内容",
    "方案重塑",
    "筑牢安全防线",
    "关键钥匙",
    "效率与流量",
    "reliable proxy",
    "stable account growth",
    "setup guide",
    "integration plugin",
    "platform review scraping",
    "fallback feed",
    "source reliability",
    "data quality",
    "福利",
    "专属福利",
    "cdk",
    "邀请码",
    "/gb",
    "$0.",
    "高性价比",
    "助力出海",
    "平替",
)

COMPETITOR_TERMS = (
    "bright data",
    "oxylabs",
    "smartproxy",
    "soax",
    "iproyal",
    "922s5",
    "kookeey",
    "1024proxy",
    "novproxy",
    "abcproxy",
    "ip2world",
    "scraperapi",
    "coinepay",
    "vcc",
    "云手机",
    "指纹手机",
)

GITHUB_ENGINEERING_TERMS = (
    "feat:",
    "fix:",
    "chore:",
    "refactor:",
    "backend:",
    "frontend:",
    "enforce ",
    "config guardrails",
    "redis-backed",
    "cross-worker",
    "proxy-bound",
    "session service",
    "chrome pool",
    "implementation",
    "unblock rate-limit",
    "safe config",
    "route ",
    "through the ci proxy",
    "typescript client",
    "matrix ci",
    "cfg.proxy",
    "browser factories",
    "geo-matched",
    "parser",
    "phase ",
    "per-solve",
    "android-solver",
    "google scholar",
    "youtube caption extraction",
    "research:",
    "new-listings parser",
    "user-agent",
    "user agent",
    "/pull/",
    "pull request",
    "layout",
    "button",
    "banner",
    "roadmap",
    "vite",
    "dock",
    "card",
    "theme polish",
    "form control",
    "切换",
    "处理反爬",
    "feat(",
    "fix(",
    "feat:",
    "fix:",
    "chore:",
    "update image",
    "ghcr.io",
    "renovate",
    "dependency",
    "internal fallback",
    "feed upload",
    "integration plugin",
    "data quality",
    "source reliability",
    "csrf-bootstrap",
    "disable_non_proxied_udp",
)

ILLEGAL_RISK_TERMS = ("ddos", "攻击", "撞库", "盗号", "黑产", "诈骗", "博彩", "刷单", "薅羊毛", "群控")


@dataclass(frozen=True)
class P11QualityDecision:
    allowed: bool
    score: int
    tier: str
    persona_key: str
    persona_label: str
    fit_label: str
    freshness_label: str
    published_at: datetime | None
    signal_tags: list[str]
    reject_reasons: list[str]
    positive_reasons: list[str]
    next_action: str

    @property
    def explanation(self) -> str:
        parts = [
            f"P11质量：{self.tier}/{self.score}",
            f"画像：{self.persona_label}",
            f"匹配：{self.fit_label}",
            f"时效：{self.freshness_label}",
        ]
        if self.positive_reasons:
            parts.append("正向证据：" + "；".join(self.positive_reasons[:5]))
        if self.reject_reasons:
            parts.append("风险/拒绝原因：" + "；".join(self.reject_reasons[:5]))
        return "\n".join(parts)


def evaluate_raw_item_p11(item: RawItem) -> P11QualityDecision:
    return evaluate_text_p11(
        title=item.title,
        content=item.content,
        url=item.url,
        source_name=item.source_name,
        published_at=item.published_at,
    )


def evaluate_mention_p11(mention: Mention) -> P11QualityDecision:
    return evaluate_text_p11(
        title=mention.title or "",
        content="\n".join([mention.content or "", mention.matched_keywords or "", mention.author or ""]),
        url=mention.canonical_url or "",
        source_name=mention.source_name or "",
        published_at=mention.published_at,
    )


def evaluate_text_p11(
    *,
    title: str,
    content: str = "",
    url: str = "",
    source_name: str = "",
    published_at: datetime | None = None,
) -> P11QualityDecision:
    evidence_text = "\n".join([title or "", content or "", url or ""])
    text = evidence_text.lower()
    source_text = (source_name or "").lower()
    title_text = (title or "").lower()
    freshness = freshness_decision(
        published_at=published_at,
        title=title,
        content=content,
        url=url,
        require_known=True,
    )

    score = 0
    positive: list[str] = []
    reject: list[str] = []
    tags: list[str] = []

    persona_key, persona_label, persona_hits = detect_persona(text)
    dynamic_hits = hit_terms(text, DYNAMIC_RESIDENTIAL_TERMS)
    scenario_hits = hit_terms(text, SCENARIO_TERMS)
    buying_hits = hit_terms(text, BUYING_INTENT_TERMS)
    pain_hits = hit_terms(text, PAIN_TERMS)
    commercial_hits = hit_terms(text, COMMERCIAL_CONTEXT_TERMS)
    low_fit_hits = hit_terms(text, LOW_FIT_TERMS)
    noise_hits = hit_terms(title_text, NOISE_TERMS) or (
        hit_terms(text, NOISE_TERMS) if not (buying_hits or pain_hits or commercial_hits) else []
    )
    supplier_hits = hit_terms(text, SUPPLIER_AD_TERMS)
    competitor_hits = hit_terms(text, COMPETITOR_TERMS)
    code_source = (
        "github" in source_text
        or "gitee" in source_text
        or "github.com" in text
        or "gitee.com" in text
    )
    github_engineering_hits = hit_terms(text, GITHUB_ENGINEERING_TERMS) if code_source else []
    illegal_hits = hit_terms(text, ILLEGAL_RISK_TERMS)
    generic_page = is_generic_page(url)

    if not freshness.allowed:
        reject.append(freshness.reason)
    elif freshness.published_at:
        score += 18
        positive.append(f"原文时间 {freshness.published_at:%Y-%m-%d}，满足 {MIN_LEAD_YEAR}+")
        tags.append("fresh_2026")

    if persona_key != "unknown":
        score += 18 + min(persona_hits * 3, 12)
        positive.append(f"命中目标客户画像：{persona_label}")
        tags.append(persona_key)
    else:
        reject.append("未命中个人/小团队/工作室目标画像")

    if dynamic_hits:
        score += 26
        positive.append("命中动态住宅/住宅代理核心词：" + "、".join(dynamic_hits[:6]))
        tags.append("dynamic_residential")
    elif persona_key != "unknown" and scenario_hits and ("ip" in text or "代理" in text or "proxy" in text):
        score += 14
        positive.append("命中代理/IP 场景，但未直接命中动态住宅，需人工确认")
        tags.append("proxy_scenario")
    else:
        reject.append("未直接命中动态住宅 IP 或代理/IP 场景")

    if pain_hits:
        score += 18
        positive.append("命中痛点：" + "、".join(pain_hits[:8]))
        tags.append("pain")
    if buying_hits:
        score += 16
        positive.append("命中购买/求推荐意图：" + "、".join(buying_hits[:6]))
        tags.append("buyer_intent")
    if scenario_hits:
        score += 10
        positive.append("命中使用场景：" + "、".join(scenario_hits[:8]))
        tags.append("scenario")
    if commercial_hits:
        score += 8
        positive.append("命中团队/批量/长期等商业上下文")
        tags.append("commercial_context")

    if low_fit_hits:
        score -= 35
        reject.append("偏静态/固定/机房/VPN：" + "、".join(low_fit_hits[:5]))
        tags.append("low_fit")
    if noise_hits:
        score -= 34
        reject.append("教程/新闻/招聘/泛技术噪音：" + "、".join(noise_hits[:5]))
        tags.append("content_noise")
    if supplier_hits and (competitor_hits or not buying_hits):
        score -= 45
        reject.append("疑似同行/服务商软文：" + "、".join((competitor_hits + supplier_hits)[:6]))
        tags.append("supplier_ad")
    if github_engineering_hits:
        score -= 40
        reject.append("GitHub 工程任务/实现细节，不是获客线索：" + "、".join(github_engineering_hits[:5]))
        tags.append("github_engineering_noise")
    if generic_page:
        score -= 18
        reject.append("搜索/标签/文章列表页，缺少具体客户证据")
        tags.append("generic_page")
    if illegal_hits:
        score -= 80
        reject.append("疑似违规用途：" + "、".join(illegal_hits[:5]))
        tags.append("illegal_risk")

    has_need = bool(dynamic_hits) or bool(persona_key != "unknown" and scenario_hits and ("ip" in text or "代理" in text or "proxy" in text))
    has_actionable = bool(pain_hits or buying_hits)
    if not has_need:
        reject.append("缺少动态住宅 IP 需求证据")
    if not has_actionable and not commercial_hits:
        reject.append("缺少痛点、购买意图或团队规模信号")

    if not dynamic_hits:
        score = min(score, 68)
    if not (pain_hits or buying_hits):
        score = min(score, 72)

    hard_reject = (
        not freshness.allowed
        or bool(illegal_hits)
        or (bool(noise_hits) and not (dynamic_hits and (pain_hits or buying_hits)))
        or (bool(supplier_hits) and not (pain_hits and buying_hits))
        or bool(github_engineering_hits)
        or (bool(low_fit_hits) and not dynamic_hits)
        or not has_need
        or (persona_key == "unknown" and not (dynamic_hits and pain_hits and buying_hits))
    )

    score = max(0, min(100, score))
    if hard_reject:
        allowed = False
        tier = "reject"
        score = min(score, 39)
    elif score >= 82 and dynamic_hits and has_actionable:
        allowed = True
        tier = "A"
    elif score >= 65:
        allowed = True
        tier = "B"
    elif score >= 50:
        allowed = True
        tier = "C"
    else:
        allowed = False
        tier = "reject"
        reject.append("综合质量分不足，不进入主池")

    fit_label = build_fit_label(dynamic_hits, scenario_hits, pain_hits, buying_hits)
    freshness_label = freshness.published_at.strftime("%Y-%m-%d") if freshness.published_at else "未知时间"
    next_action = build_next_action(allowed, tier, bool(dynamic_hits), bool(pain_hits), bool(buying_hits))
    return P11QualityDecision(
        allowed=allowed,
        score=score,
        tier=tier,
        persona_key=persona_key,
        persona_label=persona_label,
        fit_label=fit_label,
        freshness_label=freshness_label,
        published_at=freshness.published_at,
        signal_tags=unique(tags),
        reject_reasons=unique(reject),
        positive_reasons=unique(positive),
        next_action=next_action,
    )


def audit_existing_mentions_p11(db: Session, limit: int | None = None) -> dict[str, int]:
    query = select(Mention).order_by(desc(Mention.score), desc(Mention.discovered_at))
    if limit:
        query = query.limit(limit)
    mentions = list(db.scalars(query))
    checked = invalidated = updated = high_quality = 0
    for mention in mentions:
        checked += 1
        decision = evaluate_mention_p11(mention)
        if not decision.allowed:
            if decision.published_at and mention.published_at is None:
                mention.published_at = decision.published_at
            new_status = status_for_rejected_decision(decision)
            if mention.status != new_status:
                mention.status = new_status
                invalidated += 1
            mention.score = min(mention.score or 0, decision.score)
            mention.priority_score = min(mention.priority_score or 0, decision.score)
            mention.recommendation = decision.next_action
            mention.score_reasons = append_p11_reason(mention.score_reasons, decision)
            updated += 1
            continue

        if decision.published_at and mention.published_at is None:
            mention.published_at = decision.published_at
        mention.score = decision.score
        mention.priority_score = decision.score
        mention.fit_score = max(mention.fit_score or 0, 80 if decision.tier == "A" else 65)
        mention.intent_score = max(mention.intent_score or 0, 80 if "buyer_intent" in decision.signal_tags else 65 if "pain" in decision.signal_tags else 45)
        mention.risk_score = max(mention.risk_score or 0, 60 if decision.reject_reasons else 0)
        mention.risk_level = "review" if mention.risk_level == "normal" and decision.reject_reasons else mention.risk_level
        mention.recommendation = decision.next_action
        mention.score_reasons = append_p11_reason(mention.score_reasons, decision)
        if decision.tier == "A":
            high_quality += 1
        updated += 1

    db.commit()
    rebuild_prospects_after_p11(db)
    return {"checked": checked, "updated": updated, "invalidated": invalidated, "high_quality": high_quality}


def status_for_rejected_decision(decision: P11QualityDecision) -> str:
    text = "\n".join(decision.reject_reasons).lower()
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
        "缺少动态住宅",
        "未直接命中动态住宅",
        "缺少痛点",
        "未命中个人",
        "未同时命中",
    )
    if any(term in text for term in hard_invalid_terms):
        return "invalid"
    return "review"


def rebuild_prospects_after_p11(db: Session) -> None:
    from app.services.prospects import rebuild_prospects

    rebuild_prospects(db)


def append_p11_reason(existing: str, decision: P11QualityDecision) -> str:
    base = (existing or "").strip()
    marker = "P11质量："
    if marker in base:
        base = base.split(marker, 1)[0].strip()
    parts = [base, decision.explanation]
    return "\n\n".join(part for part in parts if part)[:5000]


def detect_persona(text: str) -> tuple[str, str, int]:
    best_key = "unknown"
    best_label = "未识别目标画像"
    best_hits = 0
    for key, (label, terms) in TARGET_PERSONAS.items():
        hits = sum(1 for term in terms if term.lower() in text)
        if hits > best_hits:
            best_key = key
            best_label = label
            best_hits = hits
    return best_key, best_label, best_hits


def hit_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return unique([term for term in terms if term.lower() in text])


def unique(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def is_generic_page(url: str) -> bool:
    parsed = urlparse(url or "")
    path = (parsed.path or "").lower()
    if not path or path == "/":
        return False
    generic_parts = ("/search", "/tag/", "/tags/", "/topics", "/news", "/blog/", "/article/", "/articles/")
    return any(part in path for part in generic_parts)


def build_fit_label(dynamic_hits: list[str], scenario_hits: list[str], pain_hits: list[str], buying_hits: list[str]) -> str:
    if dynamic_hits and pain_hits and buying_hits:
        return "动态住宅直匹配 + 明确痛点 + 购买意图"
    if dynamic_hits and pain_hits:
        return "动态住宅直匹配 + 明确痛点"
    if dynamic_hits:
        return "动态住宅直匹配"
    if scenario_hits and pain_hits:
        return "场景匹配 + 痛点待确认"
    return "弱匹配"


def build_next_action(allowed: bool, tier: str, dynamic: bool, pain: bool, buying: bool) -> str:
    if not allowed:
        return "不进入主池：先人工确认时效、动态住宅需求和真实客户身份。"
    if tier == "A" and dynamic and (pain or buying):
        return "高优先：当天补联系方式，首轮确认平台、国家、账号量、并发量和当前代理痛点。"
    if dynamic:
        return "可跟进：先补联系方式，再确认是否必须动态住宅 IP。"
    return "观察：场景相关但动态住宅证据不足，先不要主动触达。"


def p11_tags_text(decision: P11QualityDecision) -> str:
    return ", ".join(decision.signal_tags)
