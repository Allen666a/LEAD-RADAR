from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Mention, Prospect
from app.services.contact_status import has_real_contact


@dataclass(frozen=True)
class ICPDecision:
    status: str
    score: int
    reason: str
    route: str


DIRECT_TERMS = (
    "动态住宅",
    "动态住宅ip",
    "动态住宅 ip",
    "海外动态住宅",
    "住宅ip",
    "住宅 ip",
    "residential proxy",
    "rotating residential",
    "dynamic residential",
)

SCENARIO_TERMS = (
    "tiktok",
    "小店",
    "直播",
    "矩阵",
    "养号",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shein",
    "shopify",
    "独立站",
    "店群",
    "铺货",
    "店铺关联",
    "防关联",
    "账号关联",
    "多账号",
    "多店铺",
    "指纹浏览器",
    "adspower",
    "比特浏览器",
    "候鸟浏览器",
    "海外社媒",
    "facebook",
    "instagram",
    "youtube",
)

CRAWLER_PAIN_TERMS = (
    "cloudflare",
    "403",
    "429",
    "5 秒盾",
    "5秒盾",
    "captcha",
    "blocked",
    "ip 被封",
    "ip被封",
    "代理被封",
    "代理失败",
    "代理不稳定",
    "验证码太频繁",
    "请求太频繁",
    "封号",
    "被封",
    "账号被封",
    "店铺被封",
    "环境异常",
    "登录环境",
    "频控",
    "风控",
)

ENVIRONMENT_ANCHOR_TERMS = (
    "ip",
    "代理",
    "住宅",
    "动态住宅",
    "防关联",
    "关联",
    "多账号",
    "多店铺",
    "店群",
    "矩阵",
    "养号",
    "本土店",
    "指纹浏览器",
    "登录环境",
    "环境异常",
    "被封",
    "封号",
    "验证",
    "验证码",
    "风控",
    "cloudflare",
    "403",
    "429",
)

BUYING_TERMS = (
    "求推荐",
    "有没有",
    "哪里买",
    "哪家好",
    "采购",
    "报价",
    "价格",
    "试用",
    "测试包",
    "找代理",
    "需要代理",
    "求渠道",
)

NOISE_TERMS = (
    "教程",
    "新手教程",
    "入门",
    "学习",
    "课程",
    "面试",
    "毕业设计",
    "源码",
    "验证码识别",
    "验证码图片",
    "临时邮箱",
    "邮件服务",
    "代理模式怎么写",
    "java项目",
)

LOW_FIT_TERMS = (
    "静态住宅",
    "固定ip",
    "固定 ip",
    "长效ip",
    "长效 ip",
    "isp proxy",
    "static residential",
    "dedicated residential",
    "机房代理",
    "数据中心代理",
)

COMPETITOR_AD_TERMS = (
    "官网",
    "全网底价",
    "注册即送",
    "免费测试",
    "推广",
    "限时",
    "套餐",
)

NON_PROXY_SELLER_OPS_TERMS = (
    "buyer abuse",
    "a-to-z",
    "odr",
    "消费者法案",
    "listing 图片",
    "tic实验室",
    "儿童玩具审核",
    "入职一个月",
    "奇葩日常",
    "ai 模特",
    "认证",
    "绩效",
    "订单编号",
)

HARD_PROXY_ANCHOR_TERMS = (
    "ip",
    "代理",
    "住宅",
    "指纹浏览器",
    "登录环境",
    "环境异常",
    "账号关联",
    "账户关联",
    "店铺关联",
    "多账号",
    "多店铺",
    "封号",
    "被封",
    "cloudflare",
    "403",
    "429",
)


def evaluate_icp(prospect: Prospect, mention: Mention | None = None) -> ICPDecision:
    text = "\n".join(
        [
            prospect.display_name or "",
            prospect.company_name or "",
            clean_evidence_text(prospect.evidence or ""),
            prospect.product_fit or "",
            mention.title if mention else "",
            clean_evidence_text(mention.content if mention else ""),
        ]
    ).lower()
    title = ((mention.title if mention else prospect.display_name) or "").lower()

    score = 0
    reasons: list[str] = []
    direct = contains_any(text, DIRECT_TERMS)
    scenario = contains_any(text, SCENARIO_TERMS)
    crawler_pain = contains_any(text, CRAWLER_PAIN_TERMS)
    buying = contains_any(text, BUYING_TERMS)
    environment_anchor = contains_any(text, ENVIRONMENT_ANCHOR_TERMS)
    low_fit = contains_any(text, LOW_FIT_TERMS)
    noise = contains_any(text, NOISE_TERMS)
    competitor_ad = contains_any(text, COMPETITOR_AD_TERMS) and direct
    seller_ops_noise = contains_any(text, NON_PROXY_SELLER_OPS_TERMS) and not contains_any(text, HARD_PROXY_ANCHOR_TERMS)

    if direct:
        score += 38
        reasons.append("直接命中动态住宅/住宅 IP")
    if scenario:
        score += 28
        reasons.append("命中跨境矩阵、防关联、店群或指纹浏览器场景")
    if crawler_pain:
        score += 24
        reasons.append("出现 403、Cloudflare、IP 被封或代理不稳定等痛点")
    if buying:
        score += 22
        reasons.append("出现求推荐、采购、试用、价格等购买意图")
    if (direct or scenario or crawler_pain or buying) and prospect.customer_type in {
        "tiktok_matrix",
        "amazon_multi_account",
        "shopify_independent",
        "antidetect_browser",
    }:
        score += 12
        reasons.append("客户类型贴近动态住宅 IP")
    elif prospect.customer_type == "crawler_data" and crawler_pain:
        score += 8
        reasons.append("爬虫线索存在真实受阻证据")
    if mention and mention.score >= 75:
        score += 8

    if low_fit:
        score -= 35
        reasons.append("含静态、固定、ISP 或机房代理倾向")
    if noise and not (direct or scenario or crawler_pain):
        score -= 45
        reasons.append("更像教程/学习/泛技术内容")
    if competitor_ad:
        score -= 30
        reasons.append("疑似同行广告或官网内容，先排除销售触达")
    if seller_ops_noise:
        score = min(score, 35)
        reasons.append("更像卖家运营/认证/订单纠纷，不是 IP 或环境需求")
    if not direct and not crawler_pain and not environment_anchor:
        score = min(score, 40)
        reasons.append("只有泛平台/经营话题，缺少 IP、代理、环境或防关联锚点")
    if prospect.platform == "segmentfault" and prospect.customer_type == "crawler_data" and not crawler_pain:
        score -= 25
        reasons.append("泛爬虫问答未出现代理/IP 受阻痛点")

    score = max(0, min(100, score))
    has_contact = has_real_contact(prospect)

    if low_fit or competitor_ad or seller_ops_noise:
        return ICPDecision("risk", score, first_reason(reasons, "非核心目标或疑似同行内容"), "invalid")
    if score >= 72 and has_contact:
        return ICPDecision("qualified", score, first_reason(reasons, "高匹配且可触达"), "sales_queue")
    if score >= 60:
        return ICPDecision("qualified", score, first_reason(reasons, "高匹配，优先补联系方式"), "contact_enrich")
    if score >= 50 and (scenario or crawler_pain or buying):
        return ICPDecision("review", score, first_reason(reasons, "有业务场景但证据不完整"), "observe")
    return ICPDecision("noise", score, first_reason(reasons, "未证明是动态住宅 IP 目标客户"), "invalid")


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term_matches(text, term) for term in terms)


def term_matches(text: str, term: str) -> bool:
    lowered = text.lower()
    needle = term.lower()
    if needle in {"403", "429"}:
        return bool(re.search(rf"(?<!\d){needle}(?!\d)", lowered))
    if needle == "ip":
        return bool(re.search(r"(?<![a-z0-9])ip(?![a-z0-9])", lowered))
    return needle in lowered


def first_reason(reasons: list[str], fallback: str) -> str:
    return "；".join(reasons[:3]) if reasons else fallback


def clean_evidence_text(value: str) -> str:
    lines: list[str] = []
    for line in (value or "").splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("平台:", "关键词:", "质量层级:", "source:", "keyword:")):
            continue
        if stripped.startswith("[") and " | " in stripped:
            stripped = stripped.rsplit(" | ", 1)[-1].strip()
        lines.append(stripped)
    return "\n".join(lines)
