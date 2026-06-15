from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Mention, Prospect
from app.services.contacts import extract_contacts, merge_contact_notes
from app.services.domestic_identity import resolve_domestic_identity
from app.services.signals import HIGH_VALUE_SIGNALS


DYNAMIC_RESIDENTIAL_TERMS = [
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "海外住宅",
    "海外ip",
    "海外 ip",
    "轮换",
    "rotating residential",
    "dynamic residential",
    "residential proxy",
    "mobile proxy",
    "4g proxy",
    "5g proxy",
    "socks5 住宅",
]

STATIC_MISMATCH_TERMS = [
    "静态住宅",
    "固定ip",
    "固定 ip",
    "长效ip",
    "长效 ip",
    "static residential",
    "dedicated residential",
    "isp proxy",
    "机房代理",
    "数据中心代理",
]

HIGH_FIT_SCENARIOS = [
    "防关联",
    "指纹浏览器",
    "矩阵",
    "店群",
    "tiktok",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "cloudflare",
    "验证码",
    "风控",
    "被封",
    "ip 被封",
    "rate limit",
    "captcha",
    "爬虫",
    "采集",
]

CUSTOMER_TYPE_PATTERNS = {
    "tiktok_matrix": ["tiktok", "小店", "直播", "矩阵", "养号", "达人", "短视频"],
    "amazon_multi_account": ["亚马逊", "amazon", "多账号", "铺货", "店铺关联", "账号关联"],
    "shopee_lazada_shein": ["shopee", "lazada", "shein", "东南亚", "店群"],
    "shopify_independent": ["shopify", "独立站", "站群", "shopline", "woocommerce"],
    "crawler_data": ["爬虫", "采集", "scraper", "scraping", "crawler", "serp", "cloudflare", "验证码", "captcha", "rate limit", "403", "429"],
    "account_service": ["账号注册", "注册账号", "养号", "接码", "过验证", "账号服务"],
    "antidetect_browser": ["防关联", "指纹浏览器", "fingerprint browser", "antidetect", "anti detect", "adspower", "比特浏览器", "候鸟浏览器"],
    "social_matrix": ["facebook", "instagram", "youtube", "twitter", "x ", "社媒", "社交媒体", "fb", "ig"],
    "competitor_research": ["bright data", "oxylabs", "smartproxy", "kookeey", "1024proxy", "novproxy", "替代", "alternative"],
}

CUSTOMER_TYPE_LABELS = {
    "tiktok_matrix": "TikTok 矩阵/小店",
    "amazon_multi_account": "亚马逊多账号/铺货",
    "shopee_lazada_shein": "Shopee/Lazada/Shein 店群",
    "shopify_independent": "独立站/Shopify",
    "crawler_data": "爬虫/数据采集团队",
    "account_service": "账号注册/养号服务商",
    "antidetect_browser": "防关联/指纹浏览器用户",
    "social_matrix": "海外社媒矩阵",
    "competitor_research": "竞品/替代品调研",
    "unknown": "未识别",
}

PLATFORM_HOST_MAP = {
    "github.com": "github",
    "gitee.com": "gitee",
    "v2ex.com": "v2ex",
    "segmentfault.com": "segmentfault",
    "learnku.com": "learnku",
    "tieba.baidu.com": "tieba",
    "zhihu.com": "zhihu",
    "xiaohongshu.com": "xiaohongshu",
    "douyin.com": "douyin",
    "weibo.com": "weibo",
    "bilibili.com": "bilibili",
    "wearesellers.com": "wearesellers",
    "sellercentral.amazon.com": "amazon_seller_cn",
    "bbs.fobshanghai.com": "fobshanghai",
    "csdn.net": "csdn",
    "cnblogs.com": "cnblogs",
    "oschina.net": "oschina",
}


def rebuild_prospects(db: Session) -> dict[str, int]:
    existing = {
        prospect.identity_key: {
            "status": prospect.status,
            "company_name": prospect.company_name,
            "region": prospect.region,
            "website": prospect.website,
            "email": prospect.email,
            "wechat": prospect.wechat,
            "telegram": prospect.telegram,
            "contact_note": prospect.contact_note,
            "next_action": prospect.next_action,
            "follow_up_note": prospect.follow_up_note,
            "last_contacted_at": prospect.last_contacted_at,
            "next_follow_up_at": prospect.next_follow_up_at,
        }
        for prospect in db.scalars(select(Prospect)).all()
    }
    mentions = list(db.scalars(select(Mention).where(Mention.status != "invalid")).all())
    contact_keys = discover_contact_keys(mentions)

    db.execute(delete(Prospect))
    db.flush()

    buckets: dict[str, list[Mention]] = defaultdict(list)
    for mention in mentions:
        if mention.source_name.startswith("GitHub Search:"):
            continue
        key = prospect_key(mention, contact_keys)
        if key:
            buckets[key].append(mention)

    created = 0
    linked_mentions = 0
    for key, grouped_mentions in buckets.items():
        prospect = build_prospect(key, grouped_mentions)
        preserve_existing_fields(prospect, existing.get(key, {}))
        db.add(prospect)
        db.flush()
        created += 1
        for mention in grouped_mentions:
            mention.prospect_id = prospect.id
            linked_mentions += 1

    db.commit()
    return {"prospects": created, "linked_mentions": linked_mentions}


def discover_contact_keys(mentions: list[Mention]) -> dict[int, str]:
    keys: dict[int, str] = {}
    for mention in mentions:
        text = mention_text(mention)
        contacts = extract_contacts(text)
        if contacts.wechats:
            keys[mention.id] = f"contact:wechat:{contacts.wechats[0].lower()}"
        elif contacts.emails:
            keys[mention.id] = f"contact:email:{contacts.emails[0].lower()}"
        elif contacts.telegrams:
            keys[mention.id] = f"contact:telegram:{contacts.telegrams[0].lower()}"
        elif contacts.qqs:
            keys[mention.id] = f"contact:qq:{contacts.qqs[0]}"
        elif contacts.phones:
            keys[mention.id] = f"contact:phone:{contacts.phones[0]}"
    return keys


def prospect_key(mention: Mention, contact_keys: dict[int, str] | None = None) -> str:
    if contact_keys and mention.id in contact_keys:
        return contact_keys[mention.id]

    author = (mention.author or "").strip().lower()
    platform = normalize_platform(mention)
    domestic_identity = resolve_domestic_identity(
        platform=platform,
        author=mention.author or "",
        url=mention.canonical_url or "",
        title=mention.title or "",
        content=mention.content or "",
    )
    if domestic_identity is not None and domestic_identity.confidence >= 48:
        return domestic_identity.key

    if author and not looks_like_anonymous(author):
        return f"{platform}:author:{author}"

    parsed = urlparse(mention.canonical_url or "")
    if parsed.netloc.endswith("github.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return f"github:repo_owner:{parts[0].lower()}"

    if parsed.netloc:
        compact_path = re.sub(r"/+$", "", parsed.path.lower())
        return f"{platform}:url:{parsed.netloc.lower()}{compact_path}"

    return ""


def normalize_platform(mention: Mention) -> str:
    source = mention.source_name.lower()
    url = mention.canonical_url.lower()
    for host, platform in PLATFORM_HOST_MAP.items():
        if host in source or host in url:
            return platform
    if "小红书" in source:
        return "xiaohongshu"
    if "抖音" in source:
        return "douyin"
    if "知乎" in source:
        return "zhihu"
    if "贴吧" in source:
        return "tieba"
    if "wearesellers" in source or "卖家" in source:
        return "wearesellers"
    if "amazon seller forum cn" in source:
        return "amazon_seller_cn"
    if "fob shanghai" in source or "福步" in source:
        return "fobshanghai"
    if "csdn" in source:
        return "csdn"
    if "cnblogs" in source or "博客园" in source:
        return "cnblogs"
    if "oschina" in source or "开源中国" in source:
        return "oschina"
    return mention.source_kind or "unknown"


def build_prospect(identity_key: str, mentions: list[Mention]) -> Prospect:
    display_name = best_display_name(identity_key, mentions)
    platform = identity_key.split(":", 1)[0]
    profile_url = best_profile_url(platform, display_name, mentions)
    product_fit = classify_product_fit(mentions)
    haystack = prospect_haystack(mentions)
    customer_type = classify_customer_type(haystack)
    contacts = extract_contacts(haystack + "\n" + profile_url)
    lead_score = calculate_prospect_score(mentions, product_fit, contacts.score_bonus)
    signal_types = sorted({mention.signal_type for mention in mentions if mention.signal_type})
    keywords = sorted(
        {
            item.strip()
            for mention in mentions
            for item in (mention.matched_keywords or "").split(",")
            if item.strip()
        }
    )
    first_seen = min((m.discovered_at for m in mentions if m.discovered_at), default=None)
    last_seen = max((m.discovered_at for m in mentions if m.discovered_at), default=None)
    high_value_count = sum(
        1 for mention in mentions if mention.signal_type in HIGH_VALUE_SIGNALS and mention.score >= 60
    )
    risk_count = sum(1 for mention in mentions if mention.risk_level == "high")

    return Prospect(
        identity_key=identity_key,
        platform=platform,
        display_name=display_name,
        company_name=contacts.companies[0] if contacts.companies else "",
        profile_url=profile_url,
        website=contacts.websites[0] if contacts.websites else "",
        email=contacts.emails[0] if contacts.emails else "",
        wechat=contacts.wechats[0] if contacts.wechats else "",
        telegram=contacts.telegrams[0] if contacts.telegrams else "",
        contact_note=contacts.note(),
        product_fit=product_fit,
        customer_type=customer_type,
        lead_score=lead_score,
        mention_count=len(mentions),
        high_value_count=high_value_count,
        risk_count=risk_count,
        signal_types=", ".join(signal_types),
        keywords=", ".join(keywords[:20]),
        evidence="\n".join(build_evidence_lines(mentions)),
        pitch_message=build_pitch_message(display_name, customer_type, product_fit, mentions),
        first_touch_message=build_stage_message(display_name, customer_type, product_fit, mentions, "first_touch"),
        follow_up_message=build_stage_message(display_name, customer_type, product_fit, mentions, "follow_up"),
        trial_message=build_stage_message(display_name, customer_type, product_fit, mentions, "trial"),
        closing_message=build_stage_message(display_name, customer_type, product_fit, mentions, "closing"),
        suggested_action=build_suggested_action(customer_type, product_fit, lead_score, contacts.has_contact),
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        updated_at=datetime.now(),
    )


def preserve_existing_fields(prospect: Prospect, preserved: dict[str, object]) -> None:
    if not preserved:
        return
    prospect.status = preserved.get("status") or prospect.status
    for field in ["company_name", "region", "website", "email", "wechat", "telegram"]:
        old_value = (preserved.get(field) or "").strip() if isinstance(preserved.get(field), str) else ""
        if old_value:
            setattr(prospect, field, old_value)
    old_note = preserved.get("contact_note") if isinstance(preserved.get("contact_note"), str) else ""
    prospect.contact_note = merge_contact_notes(prospect.contact_note, old_note)
    prospect.next_action = preserved.get("next_action") or prospect.next_action
    prospect.follow_up_note = preserved.get("follow_up_note") or prospect.follow_up_note
    prospect.last_contacted_at = preserved.get("last_contacted_at") or prospect.last_contacted_at
    prospect.next_follow_up_at = preserved.get("next_follow_up_at") or prospect.next_follow_up_at


def best_display_name(identity_key: str, mentions: list[Mention]) -> str:
    platform = identity_key.split(":", 1)[0]
    for mention in mentions:
        domestic_identity = resolve_domestic_identity(
            platform=platform,
            author=mention.author or "",
            url=mention.canonical_url or "",
            title=mention.title or "",
            content=mention.content or "",
        )
        if domestic_identity is not None:
            return domestic_identity.display_name
    for mention in mentions:
        if mention.author:
            return mention.author
    if identity_key.startswith("contact:"):
        return identity_key.rsplit(":", 1)[-1]
    return identity_key.rsplit(":", 1)[-1]


def best_profile_url(platform: str, display_name: str, mentions: list[Mention]) -> str:
    if platform == "github" and display_name:
        return f"https://github.com/{display_name}"
    if platform == "gitee" and display_name:
        return f"https://gitee.com/{display_name}"
    for mention in mentions:
        domestic_identity = resolve_domestic_identity(
            platform=platform,
            author=mention.author or "",
            url=mention.canonical_url or "",
            title=mention.title or "",
            content=mention.content or "",
        )
        if domestic_identity is not None and domestic_identity.profile_url:
            return domestic_identity.profile_url
    if mentions:
        return mentions[0].canonical_url
    return ""


def classify_product_fit(mentions: list[Mention]) -> str:
    haystack = prospect_haystack(mentions)
    if contains_any(haystack, STATIC_MISMATCH_TERMS):
        return "mismatch_static"
    if contains_any(haystack, DYNAMIC_RESIDENTIAL_TERMS):
        return "direct_dynamic_residential"
    if contains_any(haystack, HIGH_FIT_SCENARIOS):
        return "scenario_fit"
    return "weak_fit"


def classify_customer_type(haystack: str) -> str:
    scores = {
        customer_type: sum(1 for pattern in patterns if pattern.lower() in haystack)
        for customer_type, patterns in CUSTOMER_TYPE_PATTERNS.items()
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return "unknown"
    return best_type


def calculate_prospect_score(mentions: list[Mention], product_fit: str, contact_bonus: int = 0) -> int:
    max_mention_score = max((mention.score or 0 for mention in mentions), default=0)
    high_value_count = sum(
        1 for mention in mentions if mention.signal_type in HIGH_VALUE_SIGNALS and mention.score >= 60
    )
    score = max_mention_score + min(high_value_count * 6, 18) + min(len(mentions) * 2, 10) + contact_bonus

    if product_fit == "direct_dynamic_residential":
        score += 18
    elif product_fit == "scenario_fit":
        score += 10
    elif product_fit == "weak_fit":
        score -= 20
    elif product_fit == "mismatch_static":
        score -= 45

    if any(mention.risk_level == "high" for mention in mentions):
        score -= 35

    signals = {mention.signal_type for mention in mentions}
    has_sales_signal = bool(signals & {"buyer_intent", "pain_signal", "company_signal"})
    if not has_sales_signal and signals <= {"competitor_signal", "risk_signal", "community_signal"}:
        score = min(score, 58)

    if any(mention.signal_type == "risk_signal" for mention in mentions) and not has_sales_signal:
        score = min(score, 55)

    if product_fit == "mismatch_static":
        score = min(score, 35)

    return max(0, min(100, score))


def build_pitch_message(display_name: str, customer_type: str, product_fit: str, mentions: list[Mention]) -> str:
    evidence = mentions[0].title if mentions else "你最近讨论的代理/IP 场景"
    greeting = f"你好，看到你这边提到“{evidence[:80]}”。"
    fit_line = "我们主要做海外动态住宅 IP，不做静态住宅，适合需要轮换出口、国家/地区覆盖和稳定会话的场景。"

    body_map = {
        "crawler_data": "如果你在做公开网页采集、SERP、价格/库存/评论监控，可以先按目标站点和目标国家测一组小流量，看 Cloudflare、验证码、429/403 和成功率表现。",
        "amazon_multi_account": "如果你是亚马逊多账号或铺货团队，可以先用少量店铺做环境连通、IP 纯净度和地区稳定性测试，确认适合再扩大。",
        "tiktok_matrix": "如果你是 TikTok 小店、直播或矩阵运营，可以先按目标国家、账号数量和使用频率评估动态住宅 IP 的会话策略。",
        "shopee_lazada_shein": "如果你做东南亚平台店群，可以先按平台、国家和店铺数量测稳定性，避免一开始大批量切换。",
        "shopify_independent": "如果你做独立站或 Shopify 站群，可以先测目标国家覆盖、会话粘性和风控触发情况。",
        "account_service": "如果你做账号注册或养号服务，需要先确认业务用途合规，再评估国家、会话时长和并发规模。",
        "antidetect_browser": "如果你在用指纹浏览器或多环境管理，建议先测代理协议、粘性时长、地区一致性和 WebRTC/DNS 泄漏风险。",
        "social_matrix": "如果你做海外社媒运营，可以先按平台、地区和账号动作频率测试 IP 稳定性，避免一开始大规模切换。",
        "competitor_research": "如果你在对比 Bright Data、Oxylabs、Smartproxy 或其他服务，可以拿目标国家和使用场景做同条件小样本测试。",
    }
    body = body_map.get(customer_type, "如果你方便，可以先说下目标国家、并发量、协议和主要平台，我帮你判断是否适合动态住宅 IP。")
    caution = "只建议用于合规业务，比如公开数据采集、跨境运营环境测试和风控排查。"
    return "\n".join([greeting, fit_line, body, caution])


def build_stage_message(display_name: str, customer_type: str, product_fit: str, mentions: list[Mention], stage: str) -> str:
    base = build_pitch_message(display_name, customer_type, product_fit, mentions)
    if stage == "first_touch":
        return base
    if stage == "follow_up":
        return "\n".join([
            "补充一下，我们不是泛代理服务，主要做海外动态住宅 IP。",
            build_scenario_question(customer_type),
            "如果你愿意，我可以按你的目标国家和平台给一个小流量测试方案，重点看连通率、稳定性、验证码/风控触发情况。",
        ])
    if stage == "trial":
        return "\n".join([
            "可以先按你当前场景开一个小测试包。",
            "建议测试：目标国家命中、协议可用性、粘性时长、并发稳定性、403/验证码触发率。",
            "你把目标平台、国家、预计并发、HTTP/SOCKS5 偏好发我，我按这个配置测试包。",
        ])
    if stage == "closing":
        return "\n".join([
            "如果测试结果连通率和稳定性 OK，下一步可以按实际量级配套餐。",
            "建议先小规模跑 1-2 天，不要一开始大批量切换，先确认账号/采集环境稳定。",
            "你把目标国家、日消耗流量和并发量给我，我可以直接给你一版更贴近实际使用的方案。",
        ])
    return base


def build_scenario_question(customer_type: str) -> str:
    questions = {
        "crawler_data": "你现在主要卡在哪里：403/429、Cloudflare、验证码，还是代理稳定性和成功率？",
        "amazon_multi_account": "你现在主要是亚马逊哪个站点？店铺数量和目标国家大概是多少？",
        "tiktok_matrix": "你这边是 TikTok 小店、直播还是养号矩阵？目标国家和账号规模大概是多少？",
        "shopee_lazada_shein": "你主要做 Shopee、Lazada 还是 Shein？目标国家和店铺数量大概是多少？",
        "shopify_independent": "你做的是独立站投放、站群运营还是数据监控？目标国家集中在哪些地区？",
        "account_service": "你这边的账号服务具体用于哪个平台？目标国家、账号量和验证方式大概是什么？",
        "antidetect_browser": "你现在用的是哪款指纹浏览器？更关注粘性时长、地区一致性，还是 WebRTC/DNS 检测？",
        "social_matrix": "你主要做哪个社媒平台？账号动作频率高不高，目标国家集中在哪些地区？",
        "competitor_research": "你当前供应商主要问题是价格、稳定性、国家覆盖，还是风控触发率？",
    }
    return questions.get(customer_type, "你现在的目标国家、平台、并发量和协议要求大概是什么？")


def build_suggested_action(customer_type: str, product_fit: str, lead_score: int, has_contact: bool = False) -> str:
    if product_fit == "mismatch_static":
        return "不优先跟进：对方更像静态/固定 IP 需求。"
    if lead_score >= 85:
        prefix = "当天跟进"
    elif lead_score >= 70:
        prefix = "24 小时内轻触达"
    elif has_contact:
        prefix = "加入低优先级培育"
    else:
        prefix = "先观察，补联系方式后再判断"

    actions = {
        "crawler_data": "询问目标站点、目标国家、并发量、403/验证码情况，提供小流量测试。",
        "amazon_multi_account": "询问站点、店铺数量、目标国家、是否使用指纹浏览器，先做环境测试。",
        "tiktok_matrix": "询问 TikTok 国家、账号规模、直播/小店/养号场景，强调动态住宅和粘性会话。",
        "shopee_lazada_shein": "询问平台、国家、店群规模和价格敏感度，先小样本验证稳定性。",
        "shopify_independent": "询问站点数量、目标国家和会话稳定要求，先测地区命中和风控触发率。",
        "account_service": "先确认合法业务用途，再评估国家、会话时长和并发规模。",
        "antidetect_browser": "询问浏览器工具、代理协议、粘性时长、WebRTC/DNS 检测要求。",
        "social_matrix": "询问平台、地区、账号动作频率，先测稳定性和环境一致性。",
        "competitor_research": "让对方提供当前供应商痛点，做同国家/同流量对比测试。",
    }
    return f"{prefix}：{actions.get(customer_type, '确认合法业务、目标国家、协议、并发量和预算范围。')}"


def build_evidence_lines(mentions: list[Mention]) -> list[str]:
    sorted_mentions = sorted(mentions, key=lambda item: item.score or 0, reverse=True)
    return [
        f"[{mention.score}] {mention.signal_type} | {mention.source_name} | {mention.title}"
        for mention in sorted_mentions[:5]
    ]


def prospect_haystack(mentions: list[Mention]) -> str:
    return "\n".join(mention_text(mention) for mention in mentions).lower()


def mention_text(mention: Mention) -> str:
    return f"{mention.title}\n{mention.content}\n{mention.author}\n{mention.matched_keywords}\n{mention.canonical_url}"


def looks_like_anonymous(author: str) -> bool:
    return author in {"匿名用户", "unknown", "user", "author", "-"}


def contains_any(haystack: str, patterns: list[str]) -> bool:
    return any(pattern.lower() in haystack for pattern in patterns)


# P6 persona and outreach overrides: focus on solo sellers, studios and small teams.
CUSTOMER_TYPE_PATTERNS.update(
    {
        "studio_operator": ["工作室", "小团队", "个人卖家", "接单", "代运营", "店群", "矩阵", "多账号", "多店铺"],
        "fingerprint_browser_user": ["指纹浏览器", "adspower", "比特浏览器", "候鸟浏览器", "multilogin", "环境隔离"],
        "account_service_studio": ["账号注册", "养号", "批量注册", "过验证", "接码", "账号服务", "注册工作室"],
    }
)
CUSTOMER_TYPE_LABELS.update(
    {
        "studio_operator": "小团队/工作室",
        "fingerprint_browser_user": "指纹浏览器用户",
        "account_service_studio": "账号注册/养号工作室",
        "tiktok_matrix": "TikTok 矩阵/小店",
        "crawler_data": "爬虫/数据采集团队",
        "unknown": "未识别",
    }
)
DYNAMIC_RESIDENTIAL_TERMS.extend(["动态住宅IP", "动态住宅 IP", "海外动态住宅IP", "住宅IP", "住宅 IP", "轮换住宅", "粘性住宅"])
HIGH_FIT_SCENARIOS.extend(["防关联", "多账号", "多店铺", "登录环境异常", "指纹浏览器", "账号关联", "店铺关联", "验证码太频繁", "5秒盾"])
STATIC_MISMATCH_TERMS.extend(["静态住宅", "固定IP", "固定 IP", "长效IP", "机场节点"])


def build_pitch_message(display_name: str, customer_type: str, product_fit: str, mentions: list[Mention]) -> str:
    evidence = mentions[0].title if mentions else "你提到的代理/IP 场景"
    greeting = f"你好，看到你在聊「{evidence[:70]}」。"
    fit_line = "我这边只做海外动态住宅 IP，不做静态住宅，主要适合多账号防关联、养号、店群、指纹浏览器和爬虫风控这类场景。"
    body_map = {
        "tiktok_matrix": "你现在主要卡在 TikTok 小店/矩阵的 IP 关联、验证码，还是登录环境稳定性？如果目标国家明确，可以先小流量测一下命中率和稳定性。",
        "amazon_multi_account": "你这边是亚马逊哪个站点？店铺数量和目标国家大概多少？可以先用少量店铺测环境隔离和 IP 稳定性，不建议一上来大批量切。",
        "shopee_lazada_shein": "如果你是 Shopee/Lazada/Shein 店群，可以先按国家、店铺数量和预算测一组，重点看登录环境、验证码和稳定性。",
        "shopify_independent": "如果你做独立站或 Shopify 站群，可以先测目标国家覆盖、会话稳定和风控触发情况。",
        "crawler_data": "如果你是爬虫/采集团队，我会先问目标站点、并发、403/429/Cloudflare/验证码情况，再判断动态住宅 IP 是否适合。",
        "account_service": "如果你做账号注册或养号，先确认业务用途合规，再看目标平台、国家、会话时长和并发量。",
        "account_service_studio": "如果你是账号注册/养号工作室，先确认业务用途合规，再看目标平台、国家、会话时长和并发量。",
        "antidetect_browser": "你现在用的是哪款指纹浏览器？更在意粘性会话、地区一致性，还是 WebRTC/DNS 这类环境检测？",
        "fingerprint_browser_user": "你现在用的是哪款指纹浏览器？更在意粘性会话、地区一致性，还是 WebRTC/DNS 这类环境检测？",
        "social_matrix": "如果你做海外社媒矩阵，可以先按平台、国家和账号动作频率测稳定性，避免一开始大规模切换。",
        "studio_operator": "如果你是小团队/工作室，我建议先别大批量上，先按一个平台、一个目标国家、小流量测稳定性和风控触发。",
        "competitor_research": "如果你是在换供应商，可以拿当前痛点做同国家、同流量的小样本对比，不用先承诺长期量。",
    }
    body = body_map.get(customer_type, "你方便说下目标平台、国家、账号量/并发量，以及现在主要卡在哪个风控点吗？我先帮你判断适不适合动态住宅 IP。")
    close = "如果合适，可以先给你小测试包；不合适我也会直接说，不硬推。"
    return "\n".join([greeting, fit_line, body, close])


def build_stage_message(display_name: str, customer_type: str, product_fit: str, mentions: list[Mention], stage: str) -> str:
    if stage == "first_touch":
        return build_pitch_message(display_name, customer_type, product_fit, mentions)
    if stage == "follow_up":
        return "\n".join(
            [
                "我补充问一下，方便判断要不要测：",
                build_scenario_question(customer_type),
                "如果你愿意，可以先按一个目标国家和一个平台小流量测，不需要一开始上大量。",
            ]
        )
    if stage == "trial":
        return "\n".join(
            [
                "可以先开小测试包。",
                "建议只测四件事：目标国家命中、连接稳定、粘性会话、验证码/403/风控触发率。",
                "你把平台、国家、协议 HTTP/SOCKS5、并发量发我，我按这个配置给你测。",
            ]
        )
    if stage == "closing":
        return "\n".join(
            [
                "如果测试结果稳定，下一步再按实际消耗配套餐。",
                "建议先跑 1-2 天小量，不要马上大批量切换，先确认账号/采集环境稳定。",
                "你把日消耗、目标国家和并发量给我，我给你一个更贴近实际使用的方案。",
            ]
        )
    return build_pitch_message(display_name, customer_type, product_fit, mentions)


def build_scenario_question(customer_type: str) -> str:
    questions = {
        "tiktok_matrix": "你这边是 TikTok 小店、直播、带货，还是养号矩阵？目标国家和账号规模大概多少？",
        "amazon_multi_account": "你现在是亚马逊哪个站点？店铺数量、目标国家、是否用指纹浏览器？",
        "crawler_data": "你现在主要卡在 403/429、Cloudflare、验证码，还是代理稳定性和成功率？",
        "fingerprint_browser_user": "你用的是哪款指纹浏览器？更在意粘性时长、地区一致性，还是环境检测？",
        "antidetect_browser": "你用的是哪款指纹浏览器？更在意粘性时长、地区一致性，还是环境检测？",
        "account_service_studio": "你主要做哪个平台的注册/养号？目标国家、账号量和验证方式大概是什么？",
        "account_service": "你主要做哪个平台的注册/养号？目标国家、账号量和验证方式大概是什么？",
        "studio_operator": "你们现在主要做哪个平台？是账号关联、验证码，还是 IP 稳定性最影响效率？",
    }
    return questions.get(customer_type, "你现在的目标平台、国家、账号量/并发量和主要风控点是什么？")


def build_suggested_action(customer_type: str, product_fit: str, lead_score: int, has_contact: bool = False) -> str:
    if product_fit == "mismatch_static":
        return "暂不主动跟进：更像静态/固定 IP 需求，不是动态住宅主线。"
    if lead_score >= 85:
        prefix = "今天优先私聊"
    elif lead_score >= 70:
        prefix = "24 小时内轻触达"
    elif has_contact:
        prefix = "低优先级培育"
    else:
        prefix = "先补联系方式"
    action_map = {
        "tiktok_matrix": "问 TikTok 国家、账号规模、小店/直播/养号场景，先给小测试包。",
        "amazon_multi_account": "问站点、店铺数量、指纹浏览器和当前关联风险。",
        "crawler_data": "问目标站点、并发、403/验证码/Cloudflare 情况。",
        "fingerprint_browser_user": "问浏览器工具、粘性时长、地区一致性和 WebRTC/DNS 检测。",
        "antidetect_browser": "问浏览器工具、粘性时长、地区一致性和 WebRTC/DNS 检测。",
        "account_service_studio": "先做合规判断，再问目标平台、国家和账号量。",
        "studio_operator": "确认平台、国家、账号量和当前最痛的风控点。",
    }
    return f"{prefix}：{action_map.get(customer_type, '确认平台、国家、并发量和当前代理痛点。')}"
