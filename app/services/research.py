from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contact_status import has_real_contact


DOMESTIC_PLATFORMS = {
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
    "amazon_seller_cn",
    "fobshanghai",
    "csdn",
    "cnblogs",
    "oschina",
    "contact",
    "import",
}


CUSTOMER_TYPE_BRIEFS = {
    "tiktok_matrix": ("TikTok 矩阵/小店", "通常关心账号环境稳定、目标国家、直播/小店动作频率、防关联和会话粘性。"),
    "amazon_multi_account": ("亚马逊多账号/铺货", "通常关心站点国家、店铺数量、IP 关联风险、指纹浏览器搭配和长期稳定性。"),
    "shopee_lazada_shein": ("东南亚店群", "通常量大、价格敏感，先用小样本验证稳定性和地区命中。"),
    "shopify_independent": ("独立站/Shopify", "通常关心国家覆盖、广告/运营环境、站群隔离和风控触发率。"),
    "crawler_data": ("爬虫/数据采集", "通常关心 403/429、Cloudflare、验证码、成功率、并发和流量成本。"),
    "account_service": ("账号注册/养号服务商", "必须先确认合法业务用途，再评估国家、会话时长和账号量。"),
    "antidetect_browser": ("指纹浏览器/防关联", "通常关心代理协议、粘性时长、地区一致性、WebRTC/DNS 风险。"),
    "social_matrix": ("海外社媒矩阵", "通常关心平台动作频率、账号数量、目标国家和封号/验证触发率。"),
    "competitor_research": ("竞品替代调研", "通常需要围绕当前供应商痛点做同条件小样本对比。"),
    "unknown": ("未识别类型", "需要先确认平台、国家、并发量、协议和具体业务场景。"),
}


@dataclass(frozen=True)
class ResearchBrief:
    prospect: Prospect
    mentions: list[Mention]
    priority_score: int
    deal_probability: str
    account_summary: str
    pain_points: list[str]
    fit_reasons: list[str]
    missing_fields: list[str]
    qualification_questions: list[str]
    opener: str
    next_actions: list[str]
    risk_notes: list[str]
    evidence_lines: list[str]

    @property
    def has_contact(self) -> bool:
        return has_real_contact(self.prospect)


def load_research_briefs(
    db: Session,
    mode: str = "priority",
    platform: str = "domestic",
    min_score: int = 60,
    limit: int = 80,
) -> list[ResearchBrief]:
    query = (
        select(Prospect)
        .where(Prospect.status.notin_(["won", "invalid"]))
        .where(Prospect.lead_score >= min_score)
        .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
    )
    if platform == "domestic":
        query = query.where(Prospect.platform.in_(DOMESTIC_PLATFORMS))
    elif platform != "all":
        query = query.where(Prospect.platform == platform)

    prospects = list(
        db.scalars(
            query.order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at)).limit(limit * 2)
        )
    )

    briefs: list[ResearchBrief] = []
    for prospect in prospects:
        mentions = load_mentions(db, prospect.id)
        brief = build_research_brief(prospect, mentions)
        if mode == "contactable" and not brief.has_contact:
            continue
        if mode == "missing_contact" and brief.has_contact:
            continue
        if mode == "high_probability" and brief.deal_probability not in {"高", "中高"}:
            continue
        briefs.append(brief)
        if len(briefs) >= limit:
            break
    return briefs


def build_research_brief(prospect: Prospect, mentions: list[Mention]) -> ResearchBrief:
    has_contact = has_real_contact(prospect)
    profile_text = prospect_haystack(prospect, mentions)
    evidence_text = mention_haystack(mentions) or profile_text
    priority_score = calculate_priority(prospect, mentions, has_contact)
    probability = deal_probability(priority_score, prospect, has_contact)
    fit_reasons = build_fit_reasons(prospect, mentions, has_contact)
    pain_points = detect_pain_points(evidence_text)
    missing_fields = detect_missing_fields(prospect, has_contact)
    risk_notes = detect_risks(prospect, mentions, evidence_text)
    questions = build_qualification_questions(prospect, missing_fields)
    summary = build_account_summary(prospect, mentions, probability, has_contact)
    opener = build_opener(prospect, mentions, pain_points, questions)
    next_actions = build_next_actions(prospect, has_contact, probability, risk_notes)

    return ResearchBrief(
        prospect=prospect,
        mentions=mentions,
        priority_score=priority_score,
        deal_probability=probability,
        account_summary=summary,
        pain_points=pain_points,
        fit_reasons=fit_reasons,
        missing_fields=missing_fields,
        qualification_questions=questions,
        opener=opener,
        next_actions=next_actions,
        risk_notes=risk_notes,
        evidence_lines=build_evidence_lines(mentions),
    )


def load_mentions(db: Session, prospect_id: int, limit: int = 8) -> list[Mention]:
    return list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect_id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(limit)
        )
    )


def calculate_priority(prospect: Prospect, mentions: list[Mention], has_contact: bool) -> int:
    score = prospect.lead_score
    if has_contact:
        score += 12
    if prospect.platform in DOMESTIC_PLATFORMS:
        score += 8
    if prospect.customer_type in {"tiktok_matrix", "amazon_multi_account", "crawler_data", "antidetect_browser"}:
        score += 8
    if prospect.product_fit == "direct_dynamic_residential":
        score += 8
    if any(mention.signal_type == "buyer_intent" for mention in mentions):
        score += 10
    if any(mention.signal_type == "pain_signal" for mention in mentions):
        score += 6
    if prospect.risk_count:
        score -= 12
    return max(0, min(100, score))


def deal_probability(priority_score: int, prospect: Prospect, has_contact: bool) -> str:
    if prospect.risk_count:
        return "需审核"
    if priority_score >= 88 and has_contact:
        return "高"
    if priority_score >= 78:
        return "中高"
    if priority_score >= 65:
        return "中"
    return "低"


def build_account_summary(
    prospect: Prospect,
    mentions: list[Mention],
    probability: str,
    has_contact: bool,
) -> str:
    label, type_note = CUSTOMER_TYPE_BRIEFS.get(prospect.customer_type, CUSTOMER_TYPE_BRIEFS["unknown"])
    latest = mentions[0].title if mentions else "暂无明确原文证据"
    contact_text = "已有真实联系方式" if has_contact else "缺少真实联系方式"
    fit_text = "动态住宅直匹配" if prospect.product_fit == "direct_dynamic_residential" else "场景匹配"
    return (
        f"{prospect.display_name} 来自 {prospect.platform}，客户类型判断为「{label}」，"
        f"当前是「{fit_text}」，成交概率为「{probability}」。{contact_text}。"
        f"主要证据：{latest[:90]}。{type_note}"
    )


def build_fit_reasons(prospect: Prospect, mentions: list[Mention], has_contact: bool) -> list[str]:
    reasons: list[str] = []
    if prospect.product_fit == "direct_dynamic_residential":
        reasons.append("直接命中动态住宅/住宅 IP 相关表达。")
    elif prospect.product_fit == "scenario_fit":
        reasons.append("命中防关联、矩阵、爬虫采集、验证码、风控等动态住宅 IP 可解决场景。")
    if prospect.customer_type != "unknown":
        label, _ = CUSTOMER_TYPE_BRIEFS.get(prospect.customer_type, CUSTOMER_TYPE_BRIEFS["unknown"])
        reasons.append(f"客户类型可归入「{label}」，方便匹配行业话术。")
    if prospect.high_value_count:
        reasons.append(f"关联 {prospect.high_value_count} 条高价值信号。")
    if has_contact:
        reasons.append("已具备真实联系方式，可进入销售动作。")
    if any(mention.signal_type == "buyer_intent" for mention in mentions):
        reasons.append("出现购买/询价/求推荐等直接意向。")
    if any(mention.signal_type == "pain_signal" for mention in mentions):
        reasons.append("出现封禁、验证码、限流、不稳定等痛点。")
    return reasons or ["相关性不足，需要继续补证据。"]


def detect_pain_points(text: str) -> list[str]:
    patterns = [
        ("验证码/Cloudflare", ["验证码", "captcha", "cloudflare"]),
        ("403/429/限流", ["403", "429", "rate limit", "限流"]),
        ("封号/封 IP", ["被封", "封ip", "封 ip", "banned", "blocked"]),
        ("防关联/多账号", ["防关联", "关联", "多账号", "店群", "矩阵"]),
        ("代理不稳定", ["不稳定", "失败", "proxy failed", "proxy error"]),
        ("采集成功率", ["爬虫", "采集", "scraping", "crawler", "serp"]),
    ]
    hits = [label for label, terms in patterns if any(term.lower() in text for term in terms)]
    return hits[:5] or ["痛点未明确，需要首轮沟通确认。"]


def detect_missing_fields(prospect: Prospect, has_contact: bool) -> list[str]:
    missing: list[str] = []
    if not has_contact:
        missing.append("真实联系方式")
    if not prospect.region:
        missing.append("目标国家/地区")
    if prospect.customer_type == "unknown":
        missing.append("客户类型")
    if not prospect.company_name:
        missing.append("公司/团队名")
    if not prospect.website and not prospect.profile_url:
        missing.append("主页/店铺/站点")
    missing.extend(["预计并发量", "协议偏好 HTTP/SOCKS5", "日流量/预算"])
    return missing[:8]


def detect_risks(prospect: Prospect, mentions: list[Mention], text: str) -> list[str]:
    risks: list[str] = []
    if prospect.risk_count or any(mention.risk_level in {"high", "review"} for mention in mentions):
        risks.append("出现敏感或需审核场景，触达前确认合法业务用途。")
    if any(term in text for term in ["撞库", "攻击", "ddos", "盗号", "黑产"]):
        risks.append("疑似高风险用途，不建议直接推进。")
    if prospect.customer_type == "account_service":
        risks.append("账号注册/养号服务需严格人工审核用途。")
    return risks or ["暂无明显高风险词，但仍需在首轮确认合规用途。"]


def build_qualification_questions(prospect: Prospect, missing_fields: list[str]) -> list[str]:
    base = {
        "tiktok_matrix": [
            "你主要做 TikTok 小店、直播还是养号矩阵？",
            "目标国家和账号规模大概是多少？",
            "现在最头疼的是封号、验证码，还是环境关联？",
        ],
        "amazon_multi_account": [
            "主要做亚马逊哪个站点？",
            "店铺数量和目标国家大概是多少？",
            "现在是否搭配指纹浏览器使用？",
        ],
        "crawler_data": [
            "目标站点是什么，主要卡在 403/429、Cloudflare 还是验证码？",
            "预计并发量和每日请求/流量大概是多少？",
            "需要 HTTP、HTTPS 还是 SOCKS5？",
        ],
        "antidetect_browser": [
            "现在用哪款指纹浏览器？",
            "更关注粘性时长、地区一致性，还是 WebRTC/DNS 检测？",
            "目标国家和环境数量大概是多少？",
        ],
    }
    questions = base.get(
        prospect.customer_type,
        [
            "你现在主要用在什么平台和国家？",
            "预计并发量、日流量和协议要求是什么？",
            "当前代理最大问题是稳定性、价格、国家覆盖，还是风控触发？",
        ],
    )
    if "真实联系方式" in missing_fields:
        questions.append("先补一个微信/Telegram/邮箱，方便发测试配置和结果。")
    return questions[:5]


def build_opener(
    prospect: Prospect,
    mentions: list[Mention],
    pain_points: list[str],
    questions: list[str],
) -> str:
    evidence = mentions[0].title if mentions else "你最近讨论的代理/IP 场景"
    pain = "、".join(pain_points[:2])
    question = questions[0] if questions else "你现在主要用在什么平台和国家？"
    return "\n".join(
        [
            f"你好，看到你这边提到「{evidence[:80]}」。",
            "我们主要做海外动态住宅 IP，不做静态住宅，适合需要轮换出口、国家覆盖和稳定会话的场景。",
            f"如果你现在主要卡在 {pain}，可以先按目标国家和平台测一组小流量，看连通率、稳定性和风控触发情况。",
            question,
        ]
    )


def build_next_actions(
    prospect: Prospect,
    has_contact: bool,
    probability: str,
    risk_notes: list[str],
) -> list[str]:
    if any("不建议" in note for note in risk_notes):
        return ["标记人工审核", "确认合法业务用途", "不自动触达"]
    actions: list[str] = []
    if not has_contact:
        actions.append("先去联系方式补全工作台补微信、QQ、Telegram 或邮箱。")
    if probability in {"高", "中高"} and has_contact:
        actions.append("今天触达，确认平台、目标国家、并发量和当前代理痛点。")
        actions.append("准备小流量测试包，不直接承诺大规模效果。")
    elif probability in {"中", "中高"}:
        actions.append("补齐业务场景和目标国家，再决定是否进入测试包。")
    else:
        actions.append("继续观察，不放入高优先级销售队列。")
    actions.append("首轮沟通必须确认用途合规。")
    return actions[:5]


def build_evidence_lines(mentions: list[Mention]) -> list[str]:
    if not mentions:
        return ["暂无关联原文。"]
    return [
        f"[{mention.score}] {mention.source_name} | {mention.title}"
        for mention in mentions[:5]
    ]


def prospect_haystack(prospect: Prospect, mentions: list[Mention]) -> str:
    parts = [
        prospect.display_name,
        prospect.platform,
        prospect.product_fit,
        prospect.customer_type,
        prospect.keywords,
        prospect.evidence,
        prospect.contact_note,
    ]
    for mention in mentions:
        parts.extend([mention.title, mention.content, mention.matched_keywords, mention.score_reasons])
    return "\n".join(part or "" for part in parts).lower()


def mention_haystack(mentions: list[Mention]) -> str:
    parts: list[str] = []
    for mention in mentions:
        parts.extend([mention.title, mention.content])
    return "\n".join(part or "" for part in parts).lower()


def generated_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
