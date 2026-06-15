from __future__ import annotations

from dataclasses import dataclass


SIGNAL_LABELS = {
    "buyer_intent": "购买意向",
    "pain_signal": "痛点信号",
    "competitor_signal": "竞品信号",
    "company_signal": "公司/团队信号",
    "risk_signal": "需人工审核",
    "community_signal": "社区讨论",
}

HIGH_VALUE_SIGNALS = {"buyer_intent", "pain_signal", "competitor_signal", "company_signal"}

BUYER_INTENT_PATTERNS = [
    "求推荐",
    "有没有",
    "哪里买",
    "哪家好",
    "推荐一个",
    "采购",
    "试用",
    "测试包",
    "报价",
    "价格",
    "购买",
    "找代理",
    "需要代理",
    "求渠道",
    "怎么选",
]

PAIN_PATTERNS = [
    "不稳定",
    "被封",
    "封ip",
    "封 ip",
    "验证码",
    "关联",
    "采集失败",
    "请求失败",
    "ip不干净",
    "ip 不干净",
    "风控",
    "403",
    "429",
    "rate limit",
    "blocked",
    "banned",
    "captcha",
    "ip banned",
    "proxy failed",
    "proxy error",
    "防封",
    "反爬",
    "限流",
]

BUYER_CONTEXT_PATTERNS = [
    "住宅ip",
    "住宅 ip",
    "动态住宅",
    "海外ip",
    "海外 ip",
    "代理ip",
    "代理 ip",
    "爬虫代理",
    "采集代理",
    "防关联",
    "验证码",
    "cloudflare",
    "风控",
    "serp",
    "residential proxy",
    "rotating proxy",
    "proxy for scraping",
    "captcha",
    "rate limit",
    "blocked",
    "banned",
    "fingerprint browser",
    "指纹浏览器",
    "tiktok",
    "亚马逊",
    "shopee",
    "shopify",
    "店群",
    "矩阵",
]

PAIN_CONTEXT_PATTERNS = [
    "代理",
    "代理ip",
    "代理 ip",
    "ip",
    "爬虫",
    "采集",
    "验证码",
    "风控",
    "proxy",
    "residential",
    "scraping",
    "captcha",
    "rate limit",
    "blocked",
    "banned",
    "fingerprint browser",
    "指纹浏览器",
    "店群",
    "矩阵",
]

COMPETITOR_PATTERNS = [
    "替代",
    "不好用",
    "太贵",
    "封号",
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
    "scraperapi",
    "ip2world",
]

COMPANY_PATTERNS = [
    "招聘",
    "招 ",
    "岗位",
    "内推",
    "爬虫工程师",
    "数据采集工程师",
    "跨境运营",
    "tiktok运营",
    "亚马逊运营",
    "scraping engineer",
    "crawler engineer",
    "data collection engineer",
    "anti bot",
]

RISK_PATTERNS = [
    "撞库",
    "攻击",
    "ddos",
    "黑产",
    "盗号",
    "刷单",
    "群控",
]

REVIEW_PATTERNS = [
    "防关联",
    "养号",
    "账号注册",
    "注册账号",
    "过验证",
    "多账号",
    "矩阵号",
    "店群",
]


@dataclass(frozen=True)
class SignalResult:
    signal_type: str
    reasons: list[str]


def classify_signal(text: str, risk_level: str) -> SignalResult:
    haystack = text.lower()
    reasons: list[str] = []

    if risk_level == "high" or contains_any(haystack, RISK_PATTERNS):
        reasons.append("命中攻击、黑产、撞库、盗号等高风险词")
        return SignalResult("risk_signal", reasons)

    if risk_level == "review" or contains_any(haystack, REVIEW_PATTERNS):
        reasons.append("命中多账号、防关联、养号、店群等需人工审核场景")
        return SignalResult("risk_signal", reasons)

    if contains_any(haystack, COMPETITOR_PATTERNS):
        reasons.append("出现竞品、替代、不好用、太贵等竞品相关表达")
        return SignalResult("competitor_signal", reasons)

    if contains_any(haystack, BUYER_INTENT_PATTERNS) and contains_any(
        haystack, BUYER_CONTEXT_PATTERNS
    ):
        reasons.append("出现求推荐、采购、测试、报价等购买意向表达")
        return SignalResult("buyer_intent", reasons)

    if contains_any(haystack, PAIN_PATTERNS) and contains_any(haystack, PAIN_CONTEXT_PATTERNS):
        reasons.append("出现封禁、不稳定、验证码、风控、限流等明确痛点")
        return SignalResult("pain_signal", reasons)

    if contains_any(haystack, COMPANY_PATTERNS):
        reasons.append("出现招聘、岗位或团队扩张信号")
        return SignalResult("company_signal", reasons)

    reasons.append("只有一般讨论或弱相关内容")
    return SignalResult("community_signal", reasons)


def contains_any(haystack: str, patterns: list[str]) -> bool:
    return any(pattern.lower() in haystack for pattern in patterns)
