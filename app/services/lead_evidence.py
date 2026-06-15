from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contact_enrichment import build_contact_search_queries, candidate_public_urls
from app.services.contact_status import contact_confidence, contact_identity, has_real_contact
from app.services.freshness import MIN_LEAD_YEAR, freshness_decision
from app.services.p11_quality_gate import evaluate_mention_p11


@dataclass(frozen=True)
class EvidenceItem:
    label: str
    value: str
    status: str = "neutral"


@dataclass(frozen=True)
class ContactWaterfallStep:
    label: str
    target: str
    status: str
    note: str
    url: str = ""
    query: str = ""


@dataclass(frozen=True)
class LeadEvidenceReport:
    persona: str
    fit_label: str
    freshness_label: str
    freshness_status: str
    contact_label: str
    contact_status: str
    source_platform: str
    evidence: list[EvidenceItem]
    positive_reasons: list[str]
    risk_reasons: list[str]
    qualification_questions: list[str]
    contact_steps: list[ContactWaterfallStep]
    recommended_action: str
    full_text: str


PERSONA_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("TikTok 矩阵/小店团队", ("tiktok", "tk", "抖音海外", "小店", "矩阵", "直播", "带货", "养号")),
    ("亚马逊多账号/铺货团队", ("亚马逊", "amazon", "sellercentral", "卖家", "铺货", "店群")),
    ("Shopee/Lazada/东南亚店群", ("shopee", "lazada", "东南亚", "虾皮", "店群")),
    ("账号注册/养号服务商", ("注册账号", "接码", "养号", "批量注册", "过验证")),
    ("爬虫/数据采集团队", ("爬虫", "采集", "抓取", "scrapy", "playwright", "selenium", "cloudflare", "403", "429")),
    ("海外社媒矩阵团队", ("facebook", "fb", "instagram", "ig", "youtube", "twitter", "x ", "社媒", "海外社媒")),
    ("指纹浏览器/防关联用户", ("指纹浏览器", "防关联", "账号环境", "浏览器环境", "多账号")),
]

DYNAMIC_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅代理",
    "动态ip",
    "轮换ip",
    "rotating residential",
    "residential proxy",
    "代理池",
)

PAIN_TERMS = (
    "封号",
    "封ip",
    "关联",
    "防关联",
    "验证码",
    "环境异常",
    "ip不稳定",
    "403",
    "429",
    "cloudflare",
    "风控",
    "限流",
)

NOISE_TERMS = (
    "教程",
    "入门",
    "学习",
    "源码",
    "新闻",
    "报告",
    "官网",
    "招聘",
    "毕业设计",
)


def build_lead_evidence_report(db: Session, mention: Mention) -> LeadEvidenceReport:
    prospect = db.get(Prospect, mention.prospect_id) if mention.prospect_id else None
    text = build_full_text(mention, prospect)
    lowered = text.lower()
    platform = normalize_platform(mention.source_name or mention.source_kind or mention.canonical_url)
    p11 = evaluate_mention_p11(mention)
    freshness = freshness_decision(
        published_at=mention.published_at,
        title=mention.title or "",
        content=mention.content or "",
        url=mention.canonical_url or "",
        require_known=True,
    )

    persona = detect_persona(lowered, prospect)
    dynamic_hits = hit_terms(lowered, DYNAMIC_TERMS)
    pain_hits = hit_terms(lowered, PAIN_TERMS)
    noise_hits = hit_terms(lowered, NOISE_TERMS)
    contact_ok = bool(prospect and has_real_contact(prospect))

    positive: list[str] = list(p11.positive_reasons[:5])
    risks: list[str] = list(p11.reject_reasons[:5])
    if freshness.allowed and freshness.published_at:
        positive.append(f"原文时间为 {freshness.published_at:%Y-%m-%d}，满足 {MIN_LEAD_YEAR} 年以后线索要求。")
    else:
        risks.append(freshness.reason)
    if dynamic_hits:
        positive.append("命中动态住宅 IP/代理相关词：" + "、".join(dynamic_hits[:6]))
    else:
        risks.append("没有直接命中动态住宅 IP，需人工确认是否只是泛代理需求。")
    if pain_hits:
        positive.append("出现可销售痛点：" + "、".join(pain_hits[:8]))
    else:
        risks.append("痛点不够明确，首聊要先确认封号、关联、验证码或 IP 稳定性问题。")
    if persona != "未识别类型":
        positive.append(f"客户画像更像「{persona}」，适合小团队/个人获客路线。")
    if noise_hits:
        risks.append("含有可能降低质量的内容词：" + "、".join(noise_hits[:5]))
    if contact_ok and prospect:
        positive.append(f"已有可用联系方式，置信度 {contact_confidence(prospect)}。")
    else:
        risks.append("暂无可靠联系方式，需要先走公开主页/作者主页/搜索补全。")

    evidence = [
        EvidenceItem("P11质量", f"{p11.tier}/{p11.score}", "good" if p11.allowed else "warn"),
        EvidenceItem("平台", platform, "good" if platform else "neutral"),
        EvidenceItem("原文时间", freshness.published_at.strftime("%Y-%m-%d %H:%M") if freshness.published_at else "未知", "good" if freshness.allowed else "warn"),
        EvidenceItem("客户画像", p11.persona_label if p11.persona_key != "unknown" else persona, "good" if p11.persona_key != "unknown" else "warn"),
        EvidenceItem("动态住宅匹配", p11.fit_label, "good" if p11.allowed else "warn"),
        EvidenceItem("痛点证据", "、".join(pain_hits[:5]) if pain_hits else "未明确", "good" if pain_hits else "warn"),
        EvidenceItem("联系方式", contact_identity(prospect) if contact_ok and prospect else "缺失", "good" if contact_ok else "warn"),
    ]

    questions = build_qualification_questions(persona, dynamic_hits, pain_hits)
    contact_steps = build_contact_waterfall_steps(db, mention, prospect)
    action = p11.next_action if p11.next_action else recommended_action(mention, prospect, freshness.allowed, bool(dynamic_hits), bool(pain_hits), contact_ok)

    return LeadEvidenceReport(
        persona=p11.persona_label if p11.persona_key != "unknown" else persona,
        fit_label=p11.fit_label,
        freshness_label="新鲜" if freshness.allowed else "不合格",
        freshness_status="good" if freshness.allowed and p11.allowed else "warn",
        contact_label="可触达" if contact_ok else "需补联系方式",
        contact_status="good" if contact_ok else "warn",
        source_platform=platform,
        evidence=evidence,
        positive_reasons=positive,
        risk_reasons=risks,
        qualification_questions=questions,
        contact_steps=contact_steps,
        recommended_action=action,
        full_text=text,
    )


def build_contact_waterfall_steps(db: Session, mention: Mention, prospect: Prospect | None) -> list[ContactWaterfallStep]:
    steps: list[ContactWaterfallStep] = []
    if mention.canonical_url:
        steps.append(
            ContactWaterfallStep(
                label="1. 原文页",
                target=mention.canonical_url,
                status="已定位",
                note="先看作者、签名、评论区是否有微信、QQ、Telegram、邮箱或主页。",
                url=mention.canonical_url,
            )
        )
    if prospect:
        if prospect.profile_url:
            steps.append(
                ContactWaterfallStep(
                    label="2. 平台主页",
                    target=prospect.profile_url,
                    status="可检查",
                    note="优先查个人简介、置顶内容、外链和同名账号。",
                    url=prospect.profile_url,
                )
            )
        if prospect.website:
            steps.append(
                ContactWaterfallStep(
                    label="3. 自有网站",
                    target=prospect.website,
                    status="可检查",
                    note="看 contact/about/support 页面，判断是不是个人站、小团队或工具服务商。",
                    url=prospect.website,
                )
            )
        for url in candidate_public_urls(db, prospect)[:4]:
            if url not in {step.url for step in steps}:
                steps.append(
                    ContactWaterfallStep(
                        label=f"{len(steps) + 1}. 公开页",
                        target=url,
                        status="待检查",
                        note="公开页面补全，不做私信、不做批量互动。",
                        url=url,
                    )
                )
        for query in build_contact_search_queries(prospect, db)[:4]:
            steps.append(
                ContactWaterfallStep(
                    label=f"{len(steps) + 1}. 搜索补全",
                    target=query,
                    status="待搜索",
                    note="只把搜索结果当候选，联系方式必须回到公开主页验证。",
                    query=query,
                    url=f"https://www.bing.com/search?q={quote_plus(query)}",
                )
            )
    if not steps:
        steps.append(
            ContactWaterfallStep(
                label="1. 人工确认",
                target="暂无公开路径",
                status="缺资料",
                note="这条线索缺少可用链接，先不要触达，回到采集源补主页或作者。",
            )
        )
    return steps[:8]


def build_full_text(mention: Mention, prospect: Prospect | None) -> str:
    parts = [
        mention.title or "",
        mention.content or "",
        mention.matched_keywords or "",
        mention.score_reasons or "",
        mention.recommendation or "",
        mention.author or "",
        mention.canonical_url or "",
    ]
    if prospect:
        parts.extend(
            [
                prospect.display_name or "",
                prospect.company_name or "",
                prospect.customer_type or "",
                prospect.product_fit or "",
                prospect.evidence or "",
                prospect.contact_note or "",
                prospect.profile_url or "",
                prospect.website or "",
            ]
        )
    return "\n".join(item for item in parts if item)


def detect_persona(lowered_text: str, prospect: Prospect | None) -> str:
    if prospect and prospect.customer_type and prospect.customer_type != "unknown":
        return label_customer_type(prospect.customer_type)
    best_label = "未识别类型"
    best_hits = 0
    for label, terms in PERSONA_RULES:
        hits = sum(1 for term in terms if term.lower() in lowered_text)
        if hits > best_hits:
            best_label = label
            best_hits = hits
    return best_label


def hit_terms(lowered_text: str, terms: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if term.lower() in lowered_text and term not in hits:
            hits.append(term)
    return hits


def normalize_platform(value: str) -> str:
    lowered = (value or "").lower()
    parsed = urlparse(value if value.startswith(("http://", "https://")) else "")
    host = parsed.netloc.lower()
    haystack = f"{lowered} {host}"
    mapping = {
        "zhihu": "知乎",
        "tieba": "百度贴吧",
        "xiaohongshu": "小红书",
        "douyin": "抖音",
        "bilibili": "B站",
        "weibo": "微博",
        "segmentfault": "SegmentFault",
        "v2ex": "V2EX",
        "gitee": "Gitee",
        "github": "GitHub",
        "amazon": "Amazon Seller",
    }
    for key, label in mapping.items():
        if key in haystack:
            return label
    return value or "-"


def label_customer_type(value: str) -> str:
    labels = {
        "tiktok_studio": "TikTok 矩阵/小店团队",
        "cross_border_studio": "跨境店群/多账号团队",
        "crawler_team": "爬虫/数据采集团队",
        "account_service_studio": "账号注册/养号服务商",
        "social_media_matrix": "海外社媒矩阵团队",
        "social_matrix": "海外社媒矩阵团队",
        "browser_fingerprint_user": "指纹浏览器/防关联用户",
        "amazon_seller": "亚马逊多账号/铺货团队",
        "amazon_multi_account": "亚马逊多账号/铺货团队",
        "crawler_data": "爬虫/数据采集团队",
    }
    return labels.get(value, value)


def build_qualification_questions(persona: str, dynamic_hits: list[str], pain_hits: list[str]) -> list[str]:
    questions = [
        "你现在主要跑哪个平台和国家/地区？",
        "目前最卡的是封号、账号关联、验证码，还是 IP 稳定性？",
        "大概有多少账号量/并发量，单日流量消耗多少？",
        "现在用的是 HTTP、SOCKS5，还是指纹浏览器里单独配置代理？",
    ]
    if "TikTok" in persona:
        questions.insert(1, "是小店、直播、带货还是纯养号矩阵？")
    elif "亚马逊" in persona:
        questions.insert(1, "店铺是同站点多账号，还是多站点铺货？")
    elif "爬虫" in persona:
        questions.insert(1, "目标站点主要卡 403、Cloudflare、验证码还是频率限制？")
    if not dynamic_hits:
        questions.append("你需要的是动态住宅 IP，还是普通机房/静态住宅也能接受？")
    if not pain_hits:
        questions.append("现在不用代理会出现什么具体问题？")
    return questions[:6]


def recommended_action(
    mention: Mention,
    prospect: Prospect | None,
    fresh_ok: bool,
    dynamic_ok: bool,
    pain_ok: bool,
    contact_ok: bool,
) -> str:
    if not fresh_ok:
        return "先不要跟进：原文时间不符合 2026+ 要求，除非人工确认这是新近复活需求。"
    if contact_ok:
        return "进入今日跟进：先问平台、国家、账号量、当前痛点，再判断是否适合动态住宅 IP 测试。"
    if dynamic_ok and pain_ok:
        return "优先补联系方式：从原文页、作者主页、同名搜索开始，找到公开联系方式后再触达。"
    if mention.score >= 75 or (prospect and prospect.lead_score >= 75):
        return "人工复核：分数高但证据不完整，先确认是否真是动态住宅 IP 需求。"
    return "暂缓：缺少动态住宅 IP 与真实痛点证据，先留在观察池。"
