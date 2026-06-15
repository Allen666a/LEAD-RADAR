from __future__ import annotations

from dataclasses import dataclass

from app.models import Keyword
from app.schemas import RawItem
from app.services.contacts import extract_contacts
from app.services.lead_quality import apply_quality_to_score, evaluate_lead_quality
from app.services.signals import classify_signal


DIRECT_DYNAMIC_TERMS = [
    "动态住宅",
    "动态住宅ip",
    "动态住宅 ip",
    "海外动态住宅",
    "住宅ip",
    "住宅 ip",
    "residential proxy",
    "rotating residential",
    "dynamic residential",
    "mobile proxy",
    "4g proxy",
    "5g proxy",
]

CORE_SCENARIOS = [
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
    "防关联",
    "账号关联",
    "多账号",
    "指纹浏览器",
    "adsPower".lower(),
    "比特浏览器",
    "候鸟浏览器",
    "爬虫",
    "采集",
    "cloudflare",
    "验证码",
    "风控",
    "被封",
    "账号一登录就验证",
    "频繁要求验证身份",
    "登录环境",
    "环境异常",
    "店铺关联",
    "店铺登录环境",
    "支付风控",
    "403",
    "429",
    "5 秒盾",
    "请求太频繁",
    "rate limit",
    "captcha",
    "blocked",
]

BUYING_WORDS = [
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
]

PAIN_WORDS = [
    "不稳定",
    "被封",
    "封ip",
    "验证码",
    "风控",
    "关联",
    "限流",
    "失败",
    "不干净",
    "过不去",
    "一登录就验证",
    "频繁验证",
    "请求太频繁",
    "5 秒盾",
    "403",
    "429",
    "captcha",
    "blocked",
    "banned",
]

LOW_FIT_PATTERNS = [
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
]

RISK_PATTERNS = ["撞库", "攻击", "ddos", "黑产", "盗号", "刷单", "群控"]
REVIEW_PATTERNS = ["防关联", "养号", "账号注册", "注册账号", "过验证", "多账号", "矩阵号", "店群"]

NOISE_PATTERNS = [
    "财经汇总",
    "财经日报",
    "美股日报",
    "日报",
    "早报",
    "晚报",
    "周报",
    "月报",
    "快讯",
    "新闻",
    "资讯",
    "研报",
    "行情",
    "官网文章",
    "新品推广",
    "教程",
    "指南",
    "保姆级",
    "完整教程",
    "实战教程",
    "新手教程",
    "测评",
    "横评",
    "详解",
    "原理",
    "百度贴吧高级搜索",
    "进入贴吧",
    "api key",
    "apikey",
    "openai key",
    "deepseek",
    "招聘",
    "岗位",
    "工程师招聘",
    "远程岗位",
    "简历",
    "内推",
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
]

HARD_NOISE = [
    "esim",
    "手机卡",
    "手机号",
    "电话卡",
    "短信",
    "保号",
    "海外号码",
    "paypal 代付",
    "patreon",
    "apikey",
    "api key",
    "deepseek",
    "招聘",
    "岗位",
    "服务器配置",
    "主机配置",
    "epyc",
    "all in one",
    "github page",
    "baidu蜘蛛",
]

COMPETITOR_NAMES = [
    "kookeey",
    "1024proxy",
    "novproxy",
    "abcproxy",
    "iprocket",
    "ip2world",
    "bright data",
    "oxylabs",
    "smartproxy",
    "scraperapi",
    "922s5",
]

AD_WORDS = ["推广", "免费测试", "全网底价", "限时", "福利", "购买", "注册即送", "官网"]

CONTENT_MARKETING_NOISE = [
    "新手教程",
    "完整教程",
    "保姆级",
    "一文看懂",
    "原理详解",
    "测评",
    "横评",
    "排行榜",
    "哪家好",
    "推荐大全",
    "优惠码",
    "官网",
    "服务商官网",
    "产品介绍",
    "软文",
    "新闻",
    "资讯",
    "行业报告",
]

ACTIONABLE_CONTEXT_TERMS = [
    "怎么办",
    "怎么解决",
    "求助",
    "求推荐",
    "有没有稳定",
    "哪里买",
    "采购",
    "报价",
    "试用",
    "测试包",
    "换供应商",
    "替换现在的代理",
    "被封",
    "封号",
    "关联",
    "环境异常",
    "登录异常",
    "过不了",
    "一直验证",
    "403",
    "429",
    "captcha",
    "cloudflare",
]

PLATFORM_CONTEXT_TERMS = [
    "tiktok",
    "小店",
    "本土店",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "facebook",
    "instagram",
    "adspower",
    "指纹浏览器",
    "店群",
    "多账号",
    "矩阵",
    "爬虫",
    "采集",
]


@dataclass(frozen=True)
class ScoreResult:
    score: int
    signal_type: str
    matched_keywords: list[str]
    reasons: list[str]
    risk_level: str
    recommendation: str


def score_item(item: RawItem, keywords: list[Keyword]) -> ScoreResult:
    title = item.title.lower()
    url = item.url.lower()
    haystack = f"{item.title}\n{item.content}\n{item.author}\n{item.url}".lower()
    quality = evaluate_lead_quality(
        title=item.title,
        content=f"{item.content}\n{item.author}",
        url=item.url,
        source_name=item.source_name,
    )

    if quality.reject or is_noise_item(title, url, haystack):
        return ScoreResult(
            score=0,
            signal_type="community_signal",
            matched_keywords=[],
            reasons=["P3质量画像剔除：" + "；".join(quality.reasons[:5])],
            risk_level="normal",
            recommendation="低质量或非目标客户内容，忽略。",
        )

    matched: list[str] = []
    score = 0
    for keyword in keywords:
        phrase = keyword.phrase.strip()
        if phrase and phrase.lower() in haystack:
            matched.append(phrase)
            score += keyword.weight

    direct_dynamic = contains_any(haystack, DIRECT_DYNAMIC_TERMS)
    core_scenario = contains_any(haystack, CORE_SCENARIOS)
    buying = contains_any(haystack, BUYING_WORDS)
    pain = contains_any(haystack, PAIN_WORDS)
    low_fit = contains_any(haystack, LOW_FIT_PATTERNS)
    actionable = has_actionable_buyer_context(haystack)
    content_marketing_noise = contains_any(haystack, CONTENT_MARKETING_NOISE)

    if content_marketing_noise and not actionable:
        return ScoreResult(
            score=0,
            signal_type="community_signal",
            matched_keywords=[],
            reasons=["内容像教程/测评/官网软文，且没有明确平台痛点或购买动作"],
            risk_level="normal",
            recommendation="低购买意图内容，跳过。",
        )

    if not matched and not direct_dynamic and not core_scenario:
        return ScoreResult(
            score=0,
            signal_type="community_signal",
            matched_keywords=[],
            reasons=["未命中动态住宅 IP 或核心使用场景"],
            risk_level="normal",
            recommendation="低相关，暂不跟进。",
        )

    reasons: list[str] = []
    if matched:
        reasons.append("命中关键词：" + "、".join(matched[:8]))
    reasons.append(f"P3质量画像：{quality.tier}/{quality.quality_score}，" + "；".join(quality.reasons[:4]))
    if direct_dynamic:
        score += 35
        reasons.append("直接命中动态住宅/住宅 IP")
    if core_scenario:
        score += 22
        reasons.append("命中跨境矩阵、店群、爬虫采集、指纹浏览器或风控痛点")
    if buying:
        score += 24
        reasons.append("出现求推荐、采购、报价、试用等购买意向")
    if pain:
        score += 18
        reasons.append("出现封禁、不稳定、验证码、风控、限流等痛点")
    if actionable:
        score += 14
        reasons.append("同时命中平台/场景和可行动痛点，优先级上调")
    if low_fit:
        score -= 35
        reasons.append("出现静态住宅、固定 IP、ISP、机房代理等非核心目标")

    contact = extract_contacts(haystack)
    if contact.score_bonus:
        score += contact.score_bonus
        reasons.append("识别到可用联系方式或公司线索")

    risk_level = "normal"
    if contains_any(haystack, REVIEW_PATTERNS):
        risk_level = "review"
        reasons.append("命中多账号、防关联、养号、店群等敏感场景，需人工审核业务用途")
    if contains_any(haystack, RISK_PATTERNS):
        risk_level = "high"
        score -= 50
        reasons.append("命中高风险或疑似违规场景，需人工合规判断")

    signal = classify_signal(haystack, risk_level)
    reasons.extend(signal.reasons)
    score = adjust_by_signal(score, signal.signal_type, haystack)
    if content_marketing_noise:
        score = min(score, 45)
        reasons.append("疑似教程/测评/营销内容，最高只保留观察分")
    if core_scenario and not actionable and not direct_dynamic:
        score = min(score, 55)
        reasons.append("只有泛场景词，缺少明确购买动作或痛点，暂不进入高优先级")
    score = apply_quality_to_score(score, quality)
    score = max(0, min(100, score))

    return ScoreResult(
        score=score,
        signal_type=signal.signal_type,
        matched_keywords=matched,
        reasons=reasons,
        risk_level=risk_level,
        recommendation=build_recommendation(score, risk_level, signal.signal_type, bool(contact.has_contact)),
    )


def adjust_by_signal(score: int, signal_type: str, haystack: str) -> int:
    if signal_type == "buyer_intent":
        score += 12
    elif signal_type == "pain_signal":
        score += 8
    elif signal_type == "company_signal":
        score += 5
    elif signal_type == "competitor_signal":
        score += 6
        if is_competitor_ad(haystack):
            score = min(score, 55)
    elif signal_type == "risk_signal":
        score = min(score, 70)
    elif signal_type == "community_signal":
        score = min(score, 58)
    return score


def is_noise_item(title: str, url: str, haystack: str) -> bool:
    if contains_any(haystack, HARD_NOISE):
        return True
    if "github.com" in url and is_github_engineering_noise(title, haystack):
        return True
    title_noise = contains_any(title, NOISE_PATTERNS)
    url_noise = any(path in url for path in ["/news", "/blog/", "/article/", "/articles/"])
    keep_signal = contains_any(haystack, BUYING_WORDS + PAIN_WORDS + DIRECT_DYNAMIC_TERMS)
    return (title_noise or url_noise) and not keep_signal


def has_actionable_buyer_context(haystack: str) -> bool:
    has_platform = contains_any(haystack, PLATFORM_CONTEXT_TERMS)
    has_action = contains_any(haystack, ACTIONABLE_CONTEXT_TERMS)
    has_proxy_context = contains_any(haystack, DIRECT_DYNAMIC_TERMS + ["代理ip", "住宅ip", "动态住宅ip", "residential proxy"])
    return (has_platform and has_action) or (has_proxy_context and has_action)


def is_github_engineering_noise(title: str, haystack: str) -> bool:
    prefixes = (
        "feat",
        "fix",
        "refactor",
        "chore",
        "backend:",
        "frontend:",
        "merge:",
        "plugin:",
        "add ",
        "implement ",
        "enhance",
        "replace ",
        "improve ",
    )
    if title.startswith(prefixes) and not contains_any(haystack, BUYING_WORDS + PAIN_WORDS):
        return True
    keep = ["proxy", "residential", "scraping", "crawler", "captcha", "cloudflare", "fingerprint", "socks5", "403", "blocked", "banned", "rate limit", "代理", "爬虫", "采集", "验证码", "防封", "反爬"]
    return not contains_any(title, keep)


def is_competitor_ad(haystack: str) -> bool:
    return contains_any(haystack, COMPETITOR_NAMES) and contains_any(haystack, AD_WORDS)


def build_recommendation(score: int, risk_level: str, signal_type: str, has_contact: bool) -> str:
    if risk_level == "high":
        return "高风险场景，先人工判断合规性，不建议直接触达。"
    if risk_level == "review":
        return "敏感场景，先人工审核业务用途，只承接公开数据采集、跨境运营环境测试等合规需求。"
    if score >= 85:
        return "高意向线索，当天联系；优先确认平台、目标国家、并发量和是否使用指纹浏览器。"
    if score >= 70:
        return "中高意向线索，24 小时内轻触达；先问具体使用场景和当前代理痛点。"
    if score >= 55 and has_contact:
        return "有联系方式但意向一般，进入低优先级培育池。"
    if signal_type == "competitor_signal":
        return "竞品情报，记录痛点和替代机会，暂不作为高优先级客户。"
    return "低相关或信息不足，先观察。"


def contains_any(haystack: str, patterns: list[str]) -> bool:
    return any(pattern.lower() in haystack for pattern in patterns)


# P6 scoring additions: prioritize studio/solo demand and aggressively drop content marketing.
DIRECT_DYNAMIC_TERMS.extend(["动态住宅IP", "动态住宅 IP", "海外动态住宅IP", "住宅IP", "住宅 IP", "轮换住宅", "粘性住宅"])
CORE_SCENARIOS.extend(
    [
        "多账号",
        "多店铺",
        "店群",
        "矩阵",
        "防关联",
        "账号关联",
        "店铺关联",
        "登录环境异常",
        "指纹浏览器",
        "账号注册",
        "养号",
        "5秒盾",
    ]
)
BUYING_WORDS.extend(["求推荐", "哪里买", "有没有靠谱", "测试包", "能不能测", "换供应商", "替换现在的代理"])
PAIN_WORDS.extend(["IP被封", "ip被封", "验证码太频繁", "登录环境异常", "账号一登录就验证", "代理不稳定"])
LOW_FIT_PATTERNS.extend(["静态住宅", "固定IP", "固定 IP", "长效IP", "数据中心代理", "机房代理", "机场节点"])
NOISE_PATTERNS.extend(
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
        "官网文章",
        "优惠码",
        "服务商官网",
        "招聘",
        "岗位",
    ]
)
HARD_NOISE.extend(["优惠码", "限时优惠", "服务商官网", "代理IP排行榜", "住宅IP测评"])
