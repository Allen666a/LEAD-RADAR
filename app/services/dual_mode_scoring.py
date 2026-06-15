from __future__ import annotations

from dataclasses import dataclass

from app.models import CompanyProfile, Mention, Prospect
from app.services.contact_status import has_real_contact
from app.services.contacts import extract_contacts
from app.services.lead_quality import best_customer_type, evaluate_lead_quality


FIT_TERMS = {
    "data_collection_team": ["爬虫", "采集", "scraper", "crawler", "data extraction", "数据采集"],
    "price_monitoring": ["价格监控", "price monitoring", "比价", "价格采集"],
    "ad_verification": ["广告验证", "ad verification", "广告监测"],
    "serp_seo_tool": ["serp", "seo", "搜索结果", "关键词排名"],
    "ecommerce_intelligence": ["电商情报", "竞品监控", "商品数据", "评论采集"],
    "cross_border_matrix": ["tiktok", "小店", "亚马逊", "amazon", "shopee", "lazada", "shein", "店群", "铺货"],
    "social_media_matrix": ["facebook", "instagram", "youtube", "twitter", "社媒矩阵", "海外社媒"],
    "account_farming": ["养号", "注册账号", "账号注册", "过验证"],
    "antidetect": ["防关联", "指纹浏览器", "adspower", "比特浏览器", "候鸟浏览器"],
}

INTENT_TERMS = {
    "dynamic_proxy": ["动态住宅", "住宅 ip", "住宅ip", "residential proxy", "rotating residential", "mobile proxy"],
    "blocked": ["被封", "封 ip", "封ip", "不稳定", "blocked", "banned"],
    "crawler_block": ["403", "429", "cloudflare", "验证码", "captcha", "rate limit", "反爬"],
    "buying": ["求推荐", "有没有", "哪里买", "采购", "报价", "试用", "需要代理", "找代理"],
    "jobs": ["招聘爬虫", "数据采集工程师", "爬虫工程师", "反爬", "风控工程师"],
    "github": ["scraper", "crawler", "spider", "proxy pool"],
}

RISK_TERMS = {
    "competitor": ["bright data", "oxylabs", "smartproxy", "ip2world", "922s5", "kookeey", "abcproxy", "同行"],
    "noise": ["新闻", "日报", "周报", "教程", "指南", "测评", "横评", "保姆级", "新手"],
    "bad": ["攻击", "ddos", "撞库", "盗号", "诈骗", "博彩", "黑产"],
    "low_fit": ["静态住宅", "固定 ip", "固定ip", "机房代理", "数据中心代理", "机场", "免费代理"],
}

B2B_SOURCE_HINTS = [
    "github",
    "gitee",
    "wearesellers",
    "amazon_seller_cn",
    "directory",
    "website",
    "job",
]


@dataclass(frozen=True)
class DualScore:
    mode: str
    fit_score: int
    intent_score: int
    contact_score: int
    risk_score: int
    priority_score: int
    fit_reason: str
    intent_reason: str
    contact_reason: str
    risk_reason: str
    priority_reason: str
    recommended_action: str
    customer_type: str


def score_mention(mention: Mention) -> DualScore:
    text = mention_haystack(mention)
    mode = infer_mode_from_text(text, mention.source_kind, mention.source_name)
    return score_text(
        text=text,
        mode=mode,
        base_contact=15 if mention.author else 0,
        source_name=mention.source_name,
        current_customer_type="unknown",
        existing_score=mention.score,
    )


def score_prospect(prospect: Prospect, mentions: list[Mention] | None = None) -> DualScore:
    text = prospect_haystack(prospect, mentions or [])
    mode = infer_mode_from_text(text, prospect.platform, prospect.platform)
    return score_text(
        text=text,
        mode=mode,
        base_contact=35 if has_real_contact(prospect) else 0,
        source_name=prospect.platform,
        current_customer_type=prospect.customer_type or "unknown",
        existing_score=prospect.lead_score,
    )


def score_company(company: CompanyProfile, signal_texts: list[str] | None = None) -> DualScore:
    text = "\n".join(
        [
            company.company_name or "",
            company.domain or "",
            company.website or "",
            company.customer_type or "",
            company.business_scenario or "",
            company.evidence_summary or "",
            company.need_reason or "",
            "\n".join(signal_texts or []),
        ]
    ).lower()
    return score_text(
        text=text,
        mode="b2b",
        base_contact=30 if company.contact_count else 0,
        source_name=company.domain or company.company_name,
        current_customer_type=company.customer_type or "unknown",
        existing_score=company.priority_score,
    )


def score_text(
    text: str,
    mode: str,
    base_contact: int,
    source_name: str,
    current_customer_type: str,
    existing_score: int = 0,
) -> DualScore:
    haystack = text.lower()
    quality = evaluate_lead_quality(title="", content=text, source_name=source_name)
    fit_score, fit_hits, customer_type = score_fit(haystack, current_customer_type)
    intent_score, intent_hits = score_intent(haystack, mode)
    contact_score, contact_hits = score_contact(haystack, base_contact)
    risk_score, risk_hits = score_risk(haystack)

    if quality.customer_types:
        customer_type = best_customer_type(quality.customer_types, customer_type)
        fit_score = min(100, max(fit_score, quality.quality_score))
        fit_hits.append(f"P3客户画像: {', '.join(quality.customer_types[:4])}")
    if quality.direct_dynamic:
        intent_score = min(100, intent_score + 12)
        intent_hits.append("P3命中动态住宅/住宅代理")
    if quality.buying_intent:
        intent_score = min(100, intent_score + 12)
        intent_hits.append("P3命中购买/替换/求推荐意图")
    if quality.pain_signal:
        intent_score = min(100, intent_score + 8)
        intent_hits.append("P3命中封号/关联/验证码/403 等痛点")
    if quality.reject:
        fit_score = min(fit_score, 25)
        intent_score = min(intent_score, 25)
        risk_score = max(risk_score, 70)
        risk_hits.append("P3质量画像剔除/降权: " + "；".join(quality.reasons[:4]))
    elif quality.tutorial_noise or quality.supplier_ad or quality.low_fit:
        risk_score = max(risk_score, 45)
        risk_hits.append("P3质量画像降权: " + "；".join(quality.reasons[:4]))

    if mode == "b2b":
        fit_score = min(100, fit_score + 10)
        if any(hint in (source_name or "").lower() for hint in B2B_SOURCE_HINTS):
            intent_score = min(100, intent_score + 8)

    if existing_score:
        intent_score = min(100, max(intent_score, int(existing_score * 0.7)))

    priority = int(fit_score * 0.35 + intent_score * 0.35 + contact_score * 0.2 - risk_score * 0.3)
    priority = max(0, min(100, priority))
    action = recommended_action(fit_score, intent_score, contact_score, risk_score, priority)
    return DualScore(
        mode=mode,
        fit_score=fit_score,
        intent_score=intent_score,
        contact_score=contact_score,
        risk_score=risk_score,
        priority_score=priority,
        fit_reason=reason("客户匹配", fit_hits),
        intent_reason=reason("需求信号", intent_hits),
        contact_reason=reason("联系方式", contact_hits),
        risk_reason=reason("风险", risk_hits),
        priority_reason=f"综合优先级 {priority}：{action}",
        recommended_action=action,
        customer_type=customer_type,
    )


def score_fit(text: str, current_customer_type: str) -> tuple[int, list[str], str]:
    score = 0
    hits: list[str] = []
    best_type = current_customer_type if current_customer_type and current_customer_type != "unknown" else "unknown"
    for customer_type, terms in FIT_TERMS.items():
        matched = [term for term in terms if term in text]
        if matched:
            score += 20 + min(20, len(matched) * 5)
            hits.append(f"{customer_type}: {', '.join(matched[:4])}")
            if best_type == "unknown":
                best_type = customer_type
    for term in RISK_TERMS["low_fit"]:
        if term in text:
            score -= 25
            hits.append(f"低匹配: {term}")
    return clamp(score), hits, best_type


def score_intent(text: str, mode: str) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    for group, terms in INTENT_TERMS.items():
        matched = [term for term in terms if term in text]
        if matched:
            score += 18 + min(18, len(matched) * 4)
            hits.append(f"{group}: {', '.join(matched[:5])}")
    if mode == "b2b" and any(term in text for term in ["官网", "招聘", "github", "公司", "team"]):
        score += 12
        hits.append("B2B 来源/公司信号")
    return clamp(score), hits


def score_contact(text: str, base_contact: int) -> tuple[int, list[str]]:
    contacts = extract_contacts(text)
    score = base_contact
    hits: list[str] = []
    if contacts.emails:
        score += 35
        hits.append("邮箱")
    if contacts.wechats:
        score += 30
        hits.append("微信")
    if contacts.telegrams:
        score += 25
        hits.append("Telegram")
    if contacts.companies:
        score += 15
        hits.append("公司名")
    if "contact" in text or "sales" in text or "商务" in text:
        score += 15
        hits.append("商务入口")
    if not hits and base_contact:
        hits.append("已有触达信息")
    return clamp(score), hits


def score_risk(text: str) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    for group, terms in RISK_TERMS.items():
        matched = [term for term in terms if term in text]
        if matched:
            delta = {"competitor": 70, "noise": 45, "bad": 90, "low_fit": 50}[group]
            score += delta
            hits.append(f"{group}: {', '.join(matched[:5])}")
    return clamp(score), hits


def infer_mode_from_text(text: str, source_kind: str, source_name: str) -> str:
    haystack = f"{text}\n{source_kind}\n{source_name}".lower()
    if any(hint in haystack for hint in B2B_SOURCE_HINTS):
        return "b2b"
    if any(term in haystack for term in ["招聘", "官网", "公司", "price monitoring", "ad verification", "serp api"]):
        return "b2b"
    return "demand_radar"


def recommended_action(fit: int, intent: int, contact: int, risk: int, priority: int) -> str:
    if risk >= 70:
        return "风险较高，先合规审核，不进入触达。"
    if priority >= 80 and contact >= 45:
        return "A 类客户，今日优先跟进。"
    if priority >= 70:
        return "高优先级，24 小时内处理。"
    if fit >= 60 and intent >= 60 and contact < 45:
        return "优先补联系方式。"
    if fit >= 45 and intent >= 50:
        return "保留观察，补证据后再判断。"
    return "低优先级，暂不主动触达。"


def reason(label: str, hits: list[str]) -> str:
    if not hits:
        return f"{label}：未命中强信号。"
    return f"{label}：" + "；".join(hits[:5])


def clamp(value: int) -> int:
    return max(0, min(100, value))


# P6: formal B2B is no longer the main route. Prioritize small teams, studios and solo operators.
FIT_TERMS.update(
    {
        "studio_operator": ["工作室", "小团队", "个人卖家", "店群", "矩阵", "多账号", "多店铺", "批量账号"],
        "fingerprint_browser_user": ["指纹浏览器", "adspower", "比特浏览器", "候鸟浏览器", "环境隔离"],
        "account_service_studio": ["账号注册", "养号", "批量注册", "过验证", "接码", "账号服务"],
    }
)
INTENT_TERMS.update(
    {
        "studio_pain": ["防关联", "账号关联", "店铺关联", "登录环境异常", "环境异常", "验证码太频繁"],
        "trial_intent": ["测试包", "试用", "能不能测", "小样本测试", "换供应商", "替换现在的代理"],
    }
)
RISK_TERMS["noise"] = RISK_TERMS["noise"] + [
    "教程",
    "新手教程",
    "完整教程",
    "保姆级",
    "测评",
    "排行榜",
    "新闻",
    "官网文章",
    "招聘",
    "岗位",
]
RISK_TERMS["low_fit"] = RISK_TERMS["low_fit"] + ["静态住宅", "固定ip", "固定 IP", "长效ip", "机场节点"]
B2B_SOURCE_HINTS = ["wearesellers", "amazon_seller_cn", "directory", "website"]


def mention_haystack(mention: Mention) -> str:
    return "\n".join(
        [
            mention.title or "",
            mention.content or "",
            mention.author or "",
            mention.source_name or "",
            mention.source_kind or "",
            mention.matched_keywords or "",
            mention.score_reasons or "",
            mention.canonical_url or "",
        ]
    )


def prospect_haystack(prospect: Prospect, mentions: list[Mention]) -> str:
    return "\n".join(
        [
            prospect.display_name or "",
            prospect.company_name or "",
            prospect.platform or "",
            prospect.profile_url or "",
            prospect.website or "",
            prospect.email or "",
            prospect.wechat or "",
            prospect.telegram or "",
            prospect.contact_note or "",
            prospect.customer_type or "",
            prospect.keywords or "",
            prospect.evidence or "",
            "\n".join(mention_haystack(mention) for mention in mentions[:10]),
        ]
    )
