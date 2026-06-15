from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


TARGET_PERSONA_TERMS = {
    "tiktok_matrix": [
        "tiktok",
        "tk",
        "小店",
        "直播",
        "本土店",
        "带货",
        "矩阵",
        "养号",
    ],
    "cross_border_seller": [
        "亚马逊",
        "amazon",
        "shopee",
        "lazada",
        "shein",
        "shopify",
        "独立站",
        "店群",
        "铺货",
        "多店",
        "跨境",
    ],
    "social_matrix": [
        "facebook",
        "fb",
        "instagram",
        "ig",
        "youtube",
        "twitter",
        "x.com",
        "海外社媒",
        "社媒矩阵",
    ],
    "crawler_data": [
        "爬虫",
        "采集",
        "数据采集",
        "抓取",
        "scraper",
        "crawler",
        "spider",
        "playwright",
        "puppeteer",
        "selenium",
        "serp",
        "价格监控",
        "竞品监控",
    ],
    "account_service": [
        "账号注册",
        "注册账号",
        "养号",
        "过验证",
        "接码",
        "账号服务",
        "工作室",
    ],
    "antidetect_browser": [
        "指纹浏览器",
        "adspower",
        "dolphin",
        "dolphin anty",
        "比特浏览器",
        "候鸟浏览器",
        "multilogin",
        "mulogin",
        "hubstudio",
    ],
}

DIRECT_DYNAMIC_TERMS = [
    "动态住宅",
    "动态住宅ip",
    "动态住宅代理",
    "动态住宅 ip",
    "海外动态住宅",
    "住宅ip",
    "住宅 ip",
    "住宅代理",
    "住宅ip方案",
    "住宅 ip方案",
    "轮换住宅",
    "轮换代理",
    "residential proxy",
    "rotating residential",
    "dynamic residential",
    "mobile proxy",
    "4g proxy",
    "5g proxy",
]

BUYING_INTENT_TERMS = [
    "求推荐",
    "有没有",
    "哪里买",
    "哪家好",
    "怎么选",
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
    "need",
    "looking for",
    "alternative",
    "recommend",
    "where to buy",
    "替代",
    "不好用",
    "太贵",
]

PAIN_TERMS = [
    "不稳定",
    "被封",
    "封ip",
    "封 ip",
    "封号",
    "验证码",
    "风控",
    "关联",
    "防关联",
    "限流",
    "403",
    "429",
    "cloudflare",
    "captcha",
    "rate limit",
    "blocked",
    "banned",
    "环境异常",
    "登录环境",
    "频繁验证",
    "过不去",
    "请求太频繁",
    "5 秒盾",
    "5秒盾",
    "ip 不干净",
    "ip不干净",
]

COMMERCIAL_CONTEXT_TERMS = [
    "团队",
    "工作室",
    "店群",
    "矩阵",
    "多账号",
    "多店铺",
    "并发",
    "批量",
    "月付",
    "消耗",
    "长期",
    "业务",
    "客户",
    "运营",
    "投放",
    "注册",
    "养号",
]

LOW_FIT_TERMS = [
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
    "免费代理",
    "vpn",
    "科学上网",
]

CONTENT_NOISE_TERMS = [
    "教程",
    "入门",
    "新手",
    "学习",
    "原理",
    "详解",
    "指南",
    "完整教程",
    "保姆级",
    "测评",
    "横评",
    "排行榜",
    "哪家便宜",
    "新闻",
    "资讯",
    "日报",
    "周报",
    "月报",
    "研报",
    "官网文章",
    "新品推广",
    "发布会",
    "招聘",
    "岗位",
    "内推",
    "简历",
    "api key",
    "apikey",
    "openai key",
    "deepseek",
    "大模型",
    "feat",
    "fix",
    "refactor",
    "chore",
    "wire ",
    "phase ",
    "implement ",
    "backend",
    "frontend",
]

SUPPLIER_AD_TERMS = [
    "全网低价",
    "限时优惠",
    "注册送",
    "免费测试",
    "官网",
    "联系客服",
    "套餐",
    "购买链接",
    "代理ip服务商",
    "住宅ip服务商",
    "住宅代理服务商",
]

COMPETITOR_TERMS = [
    "bright data",
    "oxylabs",
    "smartproxy",
    "soax",
    "iproyal",
    "922s5",
    "luminati",
    "kookeey",
    "1024proxy",
    "novproxy",
    "abcproxy",
    "ip2world",
    "iprocket",
    "scraperapi",
]

ILLEGAL_RISK_TERMS = [
    "ddos",
    "攻击",
    "撞库",
    "盗号",
    "黑产",
    "诈骗",
    "博彩",
    "刷单",
    "薅羊毛",
    "群控",
]

GENERIC_URL_PARTS = [
    "/search",
    "/tag/",
    "/tags/",
    "/topics",
    "/news",
    "/blog/",
    "/article/",
    "/articles/",
]


@dataclass(frozen=True)
class LeadQuality:
    quality_score: int
    tier: str
    customer_types: list[str]
    direct_dynamic: bool
    buying_intent: bool
    pain_signal: bool
    commercial_context: bool
    low_fit: bool
    tutorial_noise: bool
    supplier_ad: bool
    competitor_context: bool
    illegal_risk: bool
    generic_page: bool
    reject: bool
    reasons: list[str]


def evaluate_lead_quality(
    title: str = "",
    content: str = "",
    url: str = "",
    source_name: str = "",
) -> LeadQuality:
    text = f"{title}\n{content}\n{url}".lower()
    source_text = (source_name or "").lower()
    title_text = (title or "").lower()
    parsed = urlparse(url or "")
    path = (parsed.path or "").lower()

    customer_types = [
        key for key, terms in TARGET_PERSONA_TERMS.items() if contains_any(text, terms)
    ]
    direct_dynamic = contains_any(text, DIRECT_DYNAMIC_TERMS)
    buying_intent = contains_any(text, BUYING_INTENT_TERMS)
    pain_signal = contains_any(text, PAIN_TERMS)
    commercial_context = contains_any(text, COMMERCIAL_CONTEXT_TERMS)
    low_fit = contains_any(text, LOW_FIT_TERMS)
    tutorial_noise = contains_any(title_text, CONTENT_NOISE_TERMS) or (
        contains_any(text, CONTENT_NOISE_TERMS)
        and not (buying_intent or pain_signal or commercial_context)
    )
    competitor_context = contains_any(text, COMPETITOR_TERMS)
    supplier_ad = contains_any(text, SUPPLIER_AD_TERMS) and (
        competitor_context or direct_dynamic or "代理" in text or "proxy" in text
    )
    illegal_risk = contains_any(text, ILLEGAL_RISK_TERMS)
    generic_page = any(part in path for part in GENERIC_URL_PARTS)
    github_like = "github" in (parsed.netloc or "") or "github" in source_text
    engineering_noise = github_like and contains_any(title_text, CONTENT_NOISE_TERMS) and not (
        buying_intent or pain_signal or "need" in text or "alternative" in text
    )

    score = 0
    reasons: list[str] = []

    if customer_types:
        score += min(36, 18 + len(customer_types) * 6)
        reasons.append("命中目标客户画像：" + ", ".join(customer_types[:4]))
    if direct_dynamic:
        score += 24
        reasons.append("命中动态住宅/住宅代理核心词")
    if buying_intent:
        score += 22
        reasons.append("命中购买/替换/求推荐意图")
    if pain_signal:
        score += 18
        reasons.append("命中封号、关联、验证码、403/429 等痛点")
    if commercial_context:
        score += 12
        reasons.append("命中团队、矩阵、批量、长期等商业上下文")
    if competitor_context and (buying_intent or pain_signal):
        score += 8
        reasons.append("竞品替换/对比上下文可保留")

    if low_fit:
        score -= 35
        reasons.append("偏静态/固定/机房/VPN，不是动态住宅核心目标")
    if tutorial_noise or engineering_noise:
        score -= 30
        reasons.append("教程/测评/新闻/招聘等低获客价值内容")
    if supplier_ad:
        score -= 45
        reasons.append("疑似供应商广告或同行官网内容")
    if generic_page:
        score -= 18
        reasons.append("搜索页/标签页/文章列表页，缺少具体客户证据")
    if illegal_risk:
        score -= 80
        reasons.append("疑似违规或高风险用途，必须剔除或人工审核")

    scenario_proxy_need = bool(customer_types) and (
        direct_dynamic
        or ("代理" in text and (pain_signal or buying_intent or commercial_context))
        or ("ip" in text and (pain_signal or buying_intent or commercial_context))
    )
    crawler_proxy_need = "crawler_data" in customer_types and (
        "代理" in text or "proxy" in text or "ip" in text or direct_dynamic
    ) and (pain_signal or buying_intent)
    has_core_need = scenario_proxy_need or crawler_proxy_need
    has_strong_buyer = has_core_need and (buying_intent or pain_signal) and not supplier_ad
    reject = False
    if illegal_risk:
        reject = True
    elif supplier_ad and not (buying_intent and pain_signal):
        reject = True
    elif (tutorial_noise or engineering_noise) and not has_strong_buyer:
        reject = True
    elif low_fit and not has_strong_buyer:
        reject = True
    elif generic_page and not has_strong_buyer:
        reject = True
    elif not has_core_need:
        reject = True
        reasons.append("未同时命中目标客户画像与动态住宅相关需求")

    score = max(0, min(100, score))
    if reject:
        tier = "reject"
    elif score >= 78:
        tier = "A"
    elif score >= 62:
        tier = "B"
    elif score >= 45:
        tier = "C"
    else:
        tier = "D"

    if not reasons:
        reasons.append("未命中强质量信号")

    return LeadQuality(
        quality_score=score,
        tier=tier,
        customer_types=customer_types,
        direct_dynamic=direct_dynamic,
        buying_intent=buying_intent,
        pain_signal=pain_signal,
        commercial_context=commercial_context,
        low_fit=low_fit,
        tutorial_noise=tutorial_noise,
        supplier_ad=supplier_ad,
        competitor_context=competitor_context,
        illegal_risk=illegal_risk,
        generic_page=generic_page,
        reject=reject,
        reasons=reasons,
    )


def apply_quality_to_score(base_score: int, quality: LeadQuality) -> int:
    if quality.reject:
        return 0
    score = int(base_score * 0.65 + quality.quality_score * 0.35)
    if quality.tier == "A":
        score += 8
    elif quality.tier == "B":
        score += 3
    elif quality.tier == "C":
        score = min(score, 62)
    if quality.low_fit:
        score = min(score, 55)
    if quality.tutorial_noise:
        score = min(score, 50)
    if quality.supplier_ad:
        score = min(score, 45)
    return max(0, min(100, score))


def best_customer_type(customer_types: list[str], fallback: str = "unknown") -> str:
    if not customer_types:
        return fallback or "unknown"
    priority = [
        "tiktok_studio",
        "tiktok_matrix",
        "studio_operator",
        "cross_border_studio",
        "fingerprint_browser_user",
        "cross_border_seller",
        "antidetect_browser",
        "crawler_data",
        "account_service_studio",
        "account_service_studio",
        "account_service",
        "social_matrix",
    ]
    for item in priority:
        if item in customer_types:
            return item
    return customer_types[0]


def contains_any(haystack: str, patterns: list[str]) -> bool:
    return any(pattern.lower() in haystack for pattern in patterns)


# P6 quality tuning: optimize for solo operators, studios and small teams.
TARGET_PERSONA_TERMS.update(
    {
        "studio_operator": [
            "工作室",
            "小团队",
            "个人卖家",
            "接单",
            "代运营",
            "店群",
            "矩阵",
            "批量账号",
            "私域",
        ],
        "fingerprint_browser_user": [
            "指纹浏览器",
            "adspower",
            "比特浏览器",
            "候鸟浏览器",
            "dolphin anty",
            "multilogin",
            "环境隔离",
        ],
    }
)
DIRECT_DYNAMIC_TERMS.extend(
    [
        "动态住宅ip",
        "动态住宅 IP",
        "海外动态住宅IP",
        "住宅ip",
        "住宅 IP",
        "轮换住宅",
        "粘性住宅",
        "socks5住宅",
    ]
)
BUYING_INTENT_TERMS.extend(
    [
        "求推荐",
        "哪里买",
        "有没有靠谱",
        "求渠道",
        "求供应商",
        "测试包",
        "能不能测",
        "换供应商",
        "替换现在的代理",
    ]
)
PAIN_TERMS.extend(
    [
        "防关联",
        "账号关联",
        "店铺关联",
        "登录环境异常",
        "环境异常",
        "ip被封",
        "IP被封",
        "验证码太频繁",
        "5秒盾",
        "过不了验证",
        "代理不稳定",
        "账号一登录就验证",
    ]
)
COMMERCIAL_CONTEXT_TERMS.extend(
    [
        "工作室",
        "小团队",
        "店群",
        "矩阵",
        "多账号",
        "多店铺",
        "批量注册",
        "养号",
        "测试包",
        "复购",
    ]
)
LOW_FIT_TERMS.extend(["静态住宅", "固定住宅", "固定IP", "长效IP", "数据中心代理", "机房代理", "机场节点"])
CONTENT_NOISE_TERMS.extend(
    [
        "教程",
        "新手教程",
        "完整教程",
        "保姆级",
        "原理详解",
        "测评",
        "排行榜",
        "新闻",
        "资讯",
        "日报",
        "周报",
        "招聘",
        "岗位",
        "融资",
        "发布会",
        "官网文章",
    ]
)
SUPPLIER_AD_TERMS.extend(
    [
        "限时优惠",
        "优惠码",
        "全网低价",
        "服务商官网",
        "联系客服购买",
        "套餐价格",
        "代理ip服务商",
        "住宅ip服务商",
        "免费试用",
        "试用活动",
        "注册领",
        "专属福利",
        "cdk",
        "邀请码",
        "/gb",
        "$0.",
        "高性价比",
        "助力出海",
        "平替",
    ]
)


# P9 production tuning for the current business:
# only dynamic residential IP, mainly domestic acquisition, solo/studio buyers.
TARGET_PERSONA_TERMS.update(
    {
        "tiktok_studio": [
            "TikTok 小店",
            "TikTok 矩阵",
            "TikTok 本土店",
            "TikTok 养号",
            "TikTok 多账号",
            "直播矩阵",
        ],
        "cross_border_studio": [
            "亚马逊多店铺",
            "亚马逊多账号",
            "Shopee 店群",
            "Lazada 店群",
            "跨境店群",
            "铺货团队",
        ],
        "account_service_studio": [
            "账号注册",
            "账号养号",
            "海外账号养号",
            "注册工作室",
            "养号工作室",
        ],
    }
)

DIRECT_DYNAMIC_TERMS.extend(
    [
        "动态住宅IP",
        "动态住宅 IP",
        "动态住宅代理",
        "海外动态住宅",
        "住宅IP",
        "住宅 IP",
        "住宅代理",
        "轮换住宅",
        "旋转住宅",
        "socks5 住宅",
    ]
)

BUYING_INTENT_TERMS.extend(
    [
        "求推荐",
        "求靠谱",
        "求渠道",
        "找供应商",
        "换供应商",
        "想换代理",
        "测试包",
        "能不能测试",
        "哪里买",
        "怎么买",
        "有稳定的吗",
        "有靠谱的吗",
        "怎么解决",
        "怎么办",
    ]
)

PAIN_TERMS.extend(
    [
        "防关联",
        "账号关联",
        "店铺关联",
        "IP 关联",
        "IP关联",
        "登录环境异常",
        "账号环境异常",
        "环境异常",
        "IP 不稳定",
        "IP不稳定",
        "IP 被封",
        "IP被封",
        "一直验证",
        "验证码太频繁",
        "Cloudflare 403",
        "爬虫 403",
        "请求 429",
        "封号",
        "限流",
    ]
)

COMMERCIAL_CONTEXT_TERMS.extend(
    [
        "工作室",
        "小团队",
        "矩阵",
        "店群",
        "多账号",
        "多店铺",
        "批量",
        "养号",
        "测试包",
        "长期用",
        "复购",
    ]
)

LOW_FIT_TERMS.extend(
    [
        "静态住宅",
        "固定住宅",
        "固定IP",
        "长效IP",
        "机房代理",
        "数据中心代理",
        "机场节点",
        "科学上网",
    ]
)

CONTENT_NOISE_TERMS.extend(
    [
        "新手教程",
        "完整教程",
        "保姆级",
        "一文读懂",
        "原理详解",
        "测评",
        "横评",
        "排行榜",
        "新闻",
        "资讯",
        "日报",
        "周报",
        "官网文章",
        "发布会",
        "招聘",
        "岗位",
        "融资",
    ]
)

SUPPLIER_AD_TERMS.extend(
    [
        "限时优惠",
        "优惠码",
        "全网低价",
        "联系客服购买",
        "套餐价格",
        "服务商官网",
        "代理IP服务商",
        "住宅IP服务商",
        "免费试用",
        "试用活动",
        "注册领",
        "专属福利",
        "cdk",
        "邀请码",
        "/gb",
        "$0.",
        "高性价比",
        "助力出海",
        "平替",
    ]
)
