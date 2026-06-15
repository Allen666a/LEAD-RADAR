from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from urllib.parse import quote, urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, ContactRecord, Mention, OutreachActivity, Prospect
from app.services.contact_status import contact_confidence, has_real_contact, prospect_contact_signals
from app.services.icp_quality import ICPDecision, evaluate_icp
from app.services.company_profiles import normalize_contact_value, rescore_companies


DOMESTIC_PLATFORMS = {
    "zhihu",
    "tieba",
    "xiaohongshu",
    "douyin",
    "v2ex",
    "segmentfault",
    "learnku",
    "gitee",
    "bilibili",
    "weibo",
    "wearesellers",
    "amazon_seller_cn",
    "fobshanghai",
    "csdn",
    "cnblogs",
    "oschina",
    "contact",
    "import",
}

PLATFORM_SITE_SEARCH = {
    "zhihu": ("知乎站内", "site:zhihu.com"),
    "tieba": ("贴吧站内", "site:tieba.baidu.com"),
    "xiaohongshu": ("小红书站内", "site:xiaohongshu.com"),
    "douyin": ("抖音站内", "site:douyin.com"),
    "weibo": ("微博站内", "site:weibo.com"),
    "bilibili": ("B站站内", "site:bilibili.com"),
    "gitee": ("Gitee站内", "site:gitee.com"),
    "github": ("GitHub站内", "site:github.com"),
    "v2ex": ("V2EX站内", "site:v2ex.com"),
    "segmentfault": ("SegmentFault站内", "site:segmentfault.com"),
    "learnku": ("LearnKu站内", "site:learnku.com"),
    "wearesellers": ("卖家论坛站内", "site:wearesellers.com"),
    "amazon_seller_cn": ("亚马逊卖家论坛", "site:sellercentral.amazon.com/seller-forums"),
    "fobshanghai": ("福步论坛站内", "site:bbs.fobshanghai.com"),
    "csdn": ("CSDN站内", "site:csdn.net"),
    "cnblogs": ("博客园站内", "site:cnblogs.com"),
    "oschina": ("开源中国站内", "site:oschina.net"),
}

CONTACT_QUERY_TERMS = ("微信", "QQ", "Telegram", "邮箱", "联系方式")


@dataclass(frozen=True)
class ContactSearchLink:
    label: str
    url: str


@dataclass(frozen=True)
class ContactWorkbenchRow:
    prospect: Prospect
    top_mention: Mention | None
    priority_score: int
    enrichment_score: int
    display_label: str
    contact_state: str
    icp_status: str
    icp_score: int
    icp_reason: str
    icp_route: str
    reason: str
    search_query: str
    search_links: list[ContactSearchLink]
    action_hint: str
    enrichment_hint: str
    contact_confidence: int
    contact_records: int
    contact_summary: str
    missing_channels: list[str]
    source_label: str
    last_enrichment_note: str

    @property
    def has_contact(self) -> bool:
        return has_real_contact(self.prospect)


def load_contact_workbench_rows(
    db: Session,
    mode: str = "missing",
    platform: str = "domestic",
    min_score: int = 50,
    limit: int = 200,
) -> list[ContactWorkbenchRow]:
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
        db.scalars(query.order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at)).limit(limit * 3))
    )
    rows: list[ContactWorkbenchRow] = []
    seen_keys: set[str] = set()
    for prospect in prospects:
        real_contact = has_real_contact(prospect)
        if mode == "missing" and real_contact:
            continue
        if mode == "contactable" and not real_contact:
            continue
        if mode == "needs_intent" and (not real_contact or prospect.lead_score >= 70):
            continue
        top_mention = load_top_mention(db, prospect.id)
        if not real_contact and top_mention is None:
            continue
        if is_generic_search_result(prospect, top_mention):
            continue
        if is_contact_queue_noise(prospect, top_mention):
            continue
        icp = evaluate_icp(prospect, top_mention)
        if mode in {"missing", "contactable", "needs_intent"} and icp.route not in {"sales_queue", "contact_enrich"}:
            continue
        if not real_contact and icp.route not in {"sales_queue", "contact_enrich"} and not is_salesworthy_missing_contact(prospect, top_mention):
            continue
        row = build_workbench_row(prospect, top_mention, icp)
        dedupe_key = contact_row_dedupe_key(row)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        rows.append(row)
        if len(rows) >= limit:
            break
    return sorted(
        rows,
        key=lambda row: (
            1 if row.icp_route == "sales_queue" else 0,
            row.icp_score,
            row.enrichment_score,
            row.priority_score,
            row.prospect.lead_score,
        ),
        reverse=True,
    )


def build_workbench_row(
    prospect: Prospect, top_mention: Mention | None, icp: ICPDecision | None = None
) -> ContactWorkbenchRow:
    icp = icp or evaluate_icp(prospect, top_mention)
    real_contact = has_real_contact(prospect)
    priority_score = max(prospect.lead_score, icp.score)
    if not real_contact:
        priority_score += 10
    if prospect.customer_type in {"tiktok_matrix", "amazon_multi_account", "crawler_data", "antidetect_browser"}:
        priority_score += 6
    if prospect.platform in DOMESTIC_PLATFORMS:
        priority_score += 5
    if top_mention and top_mention.score >= 75:
        priority_score += 4
    if icp.route == "sales_queue":
        priority_score += 8
    elif icp.route == "contact_enrich":
        priority_score += 5
    priority_score = min(100, priority_score)

    if real_contact and prospect.lead_score >= 70:
        state = "可直接触达"
        reason = "已有真实联系方式，建议进入今日跟进，先确认平台、国家、并发量和当前代理痛点。"
        action_hint = "今天首触达"
    elif real_contact:
        state = "可培育"
        reason = "已有联系方式，但意向证据不够强，先补业务场景再决定是否触达。"
        action_hint = "补场景后触达"
    elif priority_score >= 85:
        state = "优先补联系"
        reason = "高相关客户缺微信、QQ、Telegram、邮箱或手机号，先查主页和全网同名信息。"
        action_hint = "先补联系方式"
    else:
        state = "待补联系方式"
        reason = "线索相关但暂不可触达，适合批量查联系方式或等新动态。"
        action_hint = "批量补全"

    query = build_search_query(prospect, top_mention)
    enrichment_score = calculate_enrichment_score(prospect, top_mention, priority_score)
    return ContactWorkbenchRow(
        prospect=prospect,
        top_mention=top_mention,
        priority_score=priority_score,
        enrichment_score=enrichment_score,
        display_label=display_label(prospect, top_mention),
        contact_state=state,
        icp_status=icp.status,
        icp_score=icp.score,
        icp_reason=icp.reason,
        icp_route=icp.route,
        reason=reason,
        search_query=query,
        search_links=build_search_links(prospect, query),
        action_hint=action_hint,
        enrichment_hint=build_enrichment_hint(prospect, top_mention),
        contact_confidence=contact_confidence(prospect),
        contact_records=count_contact_records(prospect),
        contact_summary=build_contact_summary(prospect),
        missing_channels=missing_contact_channels(prospect),
        source_label=source_label(prospect, top_mention),
        last_enrichment_note=last_enrichment_note(prospect),
    )


def calculate_enrichment_score(prospect: Prospect, top_mention: Mention | None, priority_score: int) -> int:
    score = min(60, priority_score // 2)
    url = ((top_mention.canonical_url if top_mention else "") or prospect.profile_url or prospect.website or "").lower()
    if prospect.platform in {"v2ex", "gitee", "github"}:
        score += 35
    elif prospect.platform in {"zhihu", "bilibili", "weibo"}:
        score += 22
    elif prospect.platform == "segmentfault":
        score += 6
    else:
        score += 12

    if any(pattern in url for pattern in ("/member/", "/people/", "github.com/", "gitee.com/")):
        score += 18
    if prospect.website and not looks_like_url_identity(prospect.website):
        score += 8
    if top_mention and top_mention.author and not looks_like_url_identity(top_mention.author):
        score += 10
    if "segmentfault.com/q/" in url:
        score -= 16
    if "segmentfault.com/t/" in url:
        score -= 24
    if "zhihu.com/question/" in url or "zhihu.com/zvideo/" in url:
        score -= 8
    if "联系方式补全失败" in (prospect.follow_up_note or ""):
        score -= 12
    return max(0, min(100, score))


def count_contact_records(prospect: Prospect) -> int:
    return sum(
        1
        for value in (
            prospect.wechat,
            prospect.telegram,
            prospect.email,
            prospect.website,
            prospect.contact_note if any(token in (prospect.contact_note or "").lower() for token in ("qq", "手机", "phone")) else "",
        )
        if value
    )


def build_contact_summary(prospect: Prospect) -> str:
    signals = prospect_contact_signals(prospect)
    parts: list[str] = []
    if prospect.wechat:
        parts.append(f"微信：{prospect.wechat}")
    if signals.qqs:
        parts.append("QQ：" + "、".join(signals.qqs[:2]))
    if prospect.telegram:
        parts.append(f"Telegram：{prospect.telegram}")
    if signals.phones:
        parts.append("手机：" + "、".join(signals.phones[:2]))
    if prospect.email:
        parts.append(f"邮箱：{prospect.email}")
    if prospect.website:
        parts.append(f"网站：{prospect.website}")
    return "；".join(parts)


def missing_contact_channels(prospect: Prospect) -> list[str]:
    signals = prospect_contact_signals(prospect)
    missing: list[str] = []
    if not prospect.wechat:
        missing.append("微信")
    if not signals.qqs:
        missing.append("QQ")
    if not prospect.telegram:
        missing.append("Telegram")
    if not prospect.email:
        missing.append("邮箱")
    if not signals.phones:
        missing.append("手机")
    return missing


def source_label(prospect: Prospect, top_mention: Mention | None) -> str:
    if top_mention:
        return top_mention.source_name or prospect.platform
    return prospect.platform


def last_enrichment_note(prospect: Prospect) -> str:
    lines = [line.strip() for line in (prospect.follow_up_note or "").splitlines() if line.strip()]
    for index in range(len(lines) - 1, -1, -1):
        if "P13 联系方式瀑布" in lines[index] or "联系方式补全失败" in lines[index]:
            return "\n".join(lines[index : index + 4])[:500]
    return ""


def is_contact_queue_noise(prospect: Prospect, mention: Mention | None) -> bool:
    text = "\n".join(
        [
            prospect.display_name or "",
            prospect.evidence or "",
            prospect.keywords or "",
            mention.title if mention else "",
            mention.content if mention else "",
            mention.matched_keywords if mention else "",
        ]
    ).lower()
    hard_noise = (
        "验证码图片",
        "验证码识别",
        "去除验证码",
        "验证码错误",
        "模拟登录验证码",
        "图片噪点",
        "验证码噪点",
        "四六级",
        "成绩查询",
        "考试成绩",
        "高德地图",
        "微信公众号",
        "指定的文章",
        "java项目",
        "node怎么去除验证码",
    )
    absolute_noise = (
        "临时邮箱",
        "vibe coding",
        "邮箱服务",
    )
    if any(term in text for term in absolute_noise):
        return True
    if any(term in text for term in hard_noise):
        has_strong_proxy_need = any(
            term in text
            for term in (
                "动态住宅",
                "住宅ip",
                "住宅 ip",
                "防关联",
                "多账号",
                "多店铺",
                "店群",
                "矩阵",
                "指纹浏览器",
                "代理 ip 不稳定",
                "代理ip不稳定",
                "ip 被封",
                "ip被封",
                "cloudflare",
                "403",
                "429",
            )
        )
        return not has_strong_proxy_need
    return False


def is_salesworthy_missing_contact(prospect: Prospect, mention: Mention | None) -> bool:
    title_text = (mention.title if mention else "").lower()
    mention_text = "\n".join(
        [
            mention.title if mention else "",
            mention.content if mention else "",
            mention.matched_keywords if mention else "",
        ]
    ).lower()
    text = "\n".join(
        [
            prospect.display_name or "",
            prospect.evidence or "",
            prospect.keywords or "",
            prospect.customer_type or "",
            mention.title if mention else "",
            mention.content if mention else "",
            mention.matched_keywords if mention else "",
        ]
    ).lower()
    business_terms = (
        "tiktok",
        "亚马逊",
        "amazon",
        "shopee",
        "lazada",
        "shopify",
        "facebook",
        "instagram",
        "youtube",
        "小店",
        "本土店",
        "店群",
        "矩阵",
        "多账号",
        "多店铺",
        "防关联",
        "账号关联",
        "店铺关联",
        "指纹浏览器",
        "adspower",
        "mulogin",
        "hubstudio",
        "动态住宅",
        "住宅ip",
        "住宅 ip",
        "账号注册",
        "养号工作室",
    )
    crawler_pain_terms = (
        "cloudflare",
        "5 秒盾",
        "403",
        "429",
        "请求太频繁",
        "ip 被封",
        "ip被封",
        "代理 ip 被封",
        "代理ip被封",
        "代理失败",
        "代理不稳定",
        "代理 ip 不稳定",
        "代理ip不稳定",
        "验证码太频繁",
        "一直验证",
        "频控",
    )
    if any(term in mention_text for term in business_terms):
        return True
    if prospect.customer_type == "crawler_data" and any(term in title_text for term in crawler_pain_terms):
        return True
    return prospect.lead_score >= 90 and any(term in text for term in crawler_pain_terms) and any(
        term in title_text for term in ("代理", "ip", "cloudflare", "403", "429", "验证")
    )


def load_top_mention(db: Session, prospect_id: int) -> Mention | None:
    mentions = list(
        db.scalars(
            select(Mention)
            .where(Mention.prospect_id == prospect_id)
            .where(Mention.status != "invalid")
            .order_by(desc(Mention.score), desc(Mention.discovered_at))
            .limit(10)
        )
    )
    for mention in mentions:
        if is_rejected_session_candidate(mention):
            continue
        return mention
    return mentions[0] if mentions else None


def is_rejected_session_candidate(mention: Mention) -> bool:
    text = f"{mention.title}\n{mention.content}\n{mention.score_reasons}".lower()
    return "质量层级: 剔除" in text or "剔除" in text and mention.source_name.startswith("Session ")


def _legacy_load_top_mention(db: Session, prospect_id: int) -> Mention | None:
    return db.scalar(
        select(Mention)
        .where(Mention.prospect_id == prospect_id)
        .where(Mention.status != "invalid")
        .order_by(desc(Mention.score), desc(Mention.discovered_at))
        .limit(1)
    )


def apply_contact_action(
    db: Session,
    prospect_id: int,
    action: str,
    wechat: str = "",
    qq: str = "",
    telegram: str = "",
    email: str = "",
    website: str = "",
    contact_source: str = "",
    contact_note: str = "",
    no_contact_reason: str = "",
    next_action: str = "",
) -> bool:
    prospect = db.get(Prospect, prospect_id)
    if prospect is None:
        return False

    if action == "save_contact":
        source_note = build_contact_source_note(contact_source)
        if wechat.strip():
            prospect.wechat = wechat.strip()[:160]
            save_contact_record(db, prospect, "wechat", prospect.wechat, source_note or contact_note)
        if qq.strip():
            qq_value = qq.strip()[:80]
            prospect.contact_note = merge_note(prospect.contact_note, f"QQ：{qq_value}")
            save_contact_record(db, prospect, "qq", qq_value, source_note or contact_note)
        if telegram.strip():
            prospect.telegram = telegram.strip().lstrip("@")[:160]
            save_contact_record(db, prospect, "telegram", prospect.telegram, source_note or contact_note)
        if email.strip():
            prospect.email = email.strip()[:260]
            save_contact_record(db, prospect, "email", prospect.email, source_note or contact_note)
        if website.strip():
            prospect.website = website.strip()[:1000]
            save_contact_record(db, prospect, "website", prospect.website, source_note or contact_note)
        if contact_note.strip():
            prospect.contact_note = merge_note(prospect.contact_note, contact_note.strip()[:2000])
        if source_note:
            prospect.contact_note = merge_note(prospect.contact_note, source_note)
        prospect.status = "qualified"
        prospect.contact_status = "contactable"
        prospect.next_action = (
            next_action.strip()[:1000]
            or "已补联系方式，进入今日跟进，确认平台、目标国家、并发量和当前代理痛点。"
        )
        save_outreach_activity(db, prospect, "contact_saved", "补充并保存联系方式。")
    elif action == "qualify":
        prospect.status = "qualified"
        prospect.next_action = next_action.strip()[:1000] or prospect.suggested_action or "可跟进，先确认动态住宅 IP 使用场景。"
        save_outreach_activity(db, prospect, "qualified", "标记为可跟进。")
    elif action == "no_contact":
        reason = no_contact_label(no_contact_reason)
        prospect.next_action = f"暂无真实联系方式（{reason}），后续通过会话采集、主页检查或私域导入补全。"
        prospect.follow_up_note = merge_note(prospect.follow_up_note, f"{timestamp()} 标记暂无联系方式：{reason}。")
        save_outreach_activity(db, prospect, "manual_note", f"标记暂无联系方式：{reason}。")
    elif action == "follow_up":
        prospect.status = "follow_up"
        prospect.next_follow_up_at = datetime.now() + timedelta(days=3)
        prospect.next_action = next_action.strip()[:1000] or "3 天后复查是否出现联系方式或新动态。"
        save_outreach_activity(db, prospect, "follow_up", "设置 3 天后复查。")
    elif action == "competitor":
        prospect.status = "invalid"
        prospect.suppressed = True
        prospect.suppression_reason = "同行/广告"
        prospect.next_action = "同行/广告，暂不进入销售跟进。"
        prospect.follow_up_note = merge_note(prospect.follow_up_note, f"{timestamp()} 标记为同行或广告。")
        save_outreach_activity(db, prospect, "invalid", "标记为同行或广告。")
    elif action == "invalid":
        prospect.status = "invalid"
        prospect.suppressed = True
        prospect.suppression_reason = "无效客户"
        prospect.next_action = "无效客户，停止跟进。"
        save_outreach_activity(db, prospect, "invalid", "标记为无效客户。")
    else:
        return False

    prospect.updated_at = datetime.now()
    if prospect.company_id:
        company = db.get(CompanyProfile, prospect.company_id)
        if company:
            company.contact_status = "contactable" if has_real_contact(prospect) else company.contact_status
            company.crm_status = prospect.status if prospect.status != "new" else company.crm_status
            company.next_action = prospect.next_action or company.next_action
            company.updated_at = datetime.now()
        rescore_companies(db)
    db.commit()
    return True


def save_contact_record(
    db: Session,
    prospect: Prospect,
    contact_type: str,
    value: str,
    note: str = "",
) -> None:
    normalized = normalize_contact_value(contact_type, value)
    if not normalized:
        return
    existing = db.scalar(
        select(ContactRecord).where(
            ContactRecord.contact_type == contact_type,
            ContactRecord.normalized_value == normalized,
        )
    )
    if existing:
        if prospect.company_id and not existing.company_id:
            existing.company_id = prospect.company_id
        if not existing.prospect_id:
            existing.prospect_id = prospect.id
        return
    db.add(
        ContactRecord(
            company_id=prospect.company_id,
            prospect_id=prospect.id,
            contact_type=contact_type,
            value=value,
            normalized_value=normalized,
            source_url=prospect.profile_url or prospect.website,
            source_type="manual",
            confidence=80 if contact_type in {"email", "wechat", "telegram"} else 55,
            status="unverified",
            note=note[:1000],
        )
    )


CONTACT_SOURCE_LABELS = {
    "homepage": "主页/个人资料",
    "original": "原文",
    "site_search": "站内搜索",
    "same_name": "同名全网搜索",
    "manual": "人工确认",
}


NO_CONTACT_REASON_LABELS = {
    "not_found": "公开页面未找到",
    "private_only": "只看到私信入口",
    "generic_page": "页面太泛，无法确认本人",
    "low_intent": "意向不够强，暂不继续找",
    "platform_blocked": "平台登录/验证受阻",
}


def build_contact_source_note(contact_source: str) -> str:
    label = CONTACT_SOURCE_LABELS.get((contact_source or "").strip(), "")
    return f"联系方式来源：{label}" if label else ""


def no_contact_label(reason: str) -> str:
    return NO_CONTACT_REASON_LABELS.get((reason or "").strip(), "公开页面未找到")


def save_outreach_activity(db: Session, prospect: Prospect, activity_type: str, note: str) -> None:
    db.add(
        OutreachActivity(
            company_id=prospect.company_id,
            prospect_id=prospect.id,
            activity_type=activity_type,
            channel="manual",
            status="done",
            note=note,
        )
    )


def build_search_query(prospect: Prospect, top_mention: Mention | None = None) -> str:
    identity = searchable_display_name(prospect, top_mention)
    parts = [identity, prospect.platform]
    if prospect.company_name:
        parts.append(prospect.company_name)
    if top_mention and top_mention.author:
        parts.append(top_mention.author)
    if top_mention and top_mention.title:
        parts.append(top_mention.title)
    if prospect.customer_type and prospect.customer_type != "unknown":
        parts.append(customer_query_word(prospect.customer_type))
    parts.extend(CONTACT_QUERY_TERMS)
    return " ".join(clean_query_part(part) for part in parts if clean_query_part(part)).strip()


def build_search_links(prospect: Prospect, query: str) -> list[ContactSearchLink]:
    encoded = quote(query)
    links = [
        ContactSearchLink("百度", f"https://www.baidu.com/s?wd={encoded}"),
        ContactSearchLink("Bing", f"https://www.bing.com/search?q={encoded}"),
    ]

    if prospect.profile_url:
        links.append(ContactSearchLink("主页", prospect.profile_url))

    site = PLATFORM_SITE_SEARCH.get(prospect.platform)
    if site:
        label, site_query = site
        links.append(ContactSearchLink(label, f"https://www.bing.com/search?q={quote(site_query + ' ' + query)}"))

    if prospect.platform == "zhihu":
        links.append(ContactSearchLink("知乎搜索", f"https://www.zhihu.com/search?type=content&q={encoded}"))
    elif prospect.platform == "tieba":
        links.append(ContactSearchLink("贴吧搜索", f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={encoded}"))
    elif prospect.platform == "xiaohongshu":
        links.append(ContactSearchLink("小红书搜索", f"https://www.xiaohongshu.com/search_result?keyword={encoded}"))
    elif prospect.platform == "douyin":
        links.append(ContactSearchLink("抖音搜索", f"https://www.douyin.com/search/{encoded}"))
    elif prospect.platform == "gitee":
        links.append(ContactSearchLink("Gitee搜索", f"https://search.gitee.com/?q={encoded}"))

    display = clean_query_part(search_identity_for_links(prospect))
    if display:
        links.append(ContactSearchLink("同名联系方式", f"https://www.baidu.com/s?wd={quote(f'{display} 微信 QQ 邮箱 Telegram 联系方式')}"))
        links.append(ContactSearchLink("同名全网", f"https://www.bing.com/search?q={quote(f'\"{display}\" 联系方式 微信 邮箱')}"))
    else:
        links.append(ContactSearchLink("标题找联系", f"https://www.baidu.com/s?wd={quote(query)}"))
        links.append(ContactSearchLink("标题全网", f"https://www.bing.com/search?q={quote(query)}"))

    if prospect.company_name:
        company = clean_query_part(prospect.company_name)
        links.append(ContactSearchLink("公司联系", f"https://www.baidu.com/s?wd={quote(f'{company} 官网 联系方式 微信')}"))

    return dedupe_links(links)[:8]


def build_enrichment_hint(prospect: Prospect, top_mention: Mention | None) -> str:
    latest_failure = ""
    for line in reversed((prospect.follow_up_note or "").splitlines()):
        if "联系方式补全失败" in line or "联系方式补全：" in line:
            latest_failure = line.strip()
            break
    if latest_failure:
        return latest_failure[:260]
    if prospect.platform in {"v2ex", "gitee", "github", "segmentfault"}:
        return "优先查作者主页，再查同名全网；技术社区常在个人主页或 GitHub/Gitee 留邮箱。"
    if prospect.platform == "zhihu":
        return "知乎公开页通常不直接给联系方式，优先查回答作者、公司名和同名全网。"
    if top_mention and top_mention.author:
        return f"优先围绕作者「{top_mention.author[:40]}」查微信、邮箱、Telegram。"
    return "先查主页和原文；若没有作者名，再用标题关键词做站内和全网搜索。"


def search_identity_for_links(prospect: Prospect) -> str:
    candidates = [
        prospect.display_name or "",
        prospect.company_name or "",
    ]
    for value in candidates:
        cleaned = clean_query_part(value)
        if cleaned and not looks_like_url_identity(cleaned):
            return cleaned
    if prospect.profile_url:
        parsed = urlparse(prospect.profile_url)
        path = parsed.path.strip("/")
        if "v2ex.com" in parsed.netloc and "/member/" in parsed.path:
            return path.rsplit("/", 1)[-1]
        if "gitee.com" in parsed.netloc and path:
            return path.split("/", 1)[0]
        if "github.com" in parsed.netloc and path:
            return path.split("/", 1)[0]
    return ""


def dedupe_links(links: list[ContactSearchLink]) -> list[ContactSearchLink]:
    rows: list[ContactSearchLink] = []
    seen: set[str] = set()
    for link in links:
        key = link.url
        if key in seen:
            continue
        seen.add(key)
        rows.append(link)
    return rows


def clean_query_part(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("http://", "").replace("https://", "")
    return " ".join(value.split())[:80]


def searchable_display_name(prospect: Prospect, top_mention: Mention | None) -> str:
    name = (prospect.display_name or "").strip()
    if name and not looks_like_url_identity(name):
        return name
    if top_mention and top_mention.author and not looks_like_url_identity(top_mention.author):
        return top_mention.author.strip()
    if top_mention and top_mention.title:
        return top_mention.title.strip()
    return name


def display_label(prospect: Prospect, top_mention: Mention | None) -> str:
    name = (prospect.display_name or "").strip()
    if name and not looks_like_url_identity(name):
        return name
    if top_mention and top_mention.author and not looks_like_url_identity(top_mention.author):
        return top_mention.author.strip()
    if top_mention and top_mention.title:
        title = top_mention.title.strip()
        for sep in (" 问与答 •", " 分享创造 •", " 酷工作 •", " VPS •", " • "):
            if sep in title:
                title = title.split(sep, 1)[0].strip()
        return title[:90]
    return name or "未命名客户"


def looks_like_url_identity(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return "/" in lowered or lowered.startswith(("http:", "https:")) or lowered.endswith((".com", ".net", ".cn"))


def is_generic_search_result(prospect: Prospect, top_mention: Mention | None) -> bool:
    name = (prospect.display_name or "").strip().lower()
    title = ((top_mention.title if top_mention else "") or "").strip().lower()
    url = ((top_mention.canonical_url if top_mention else prospect.profile_url) or "").strip().lower()
    generic_titles = ("站内搜索", "search", "搜索结果")
    generic_paths = ("/search", "/search?", "/explore/category")
    if any(item in title for item in generic_titles) and any(path in url for path in generic_paths):
        return True
    if name.endswith("/search") or name.endswith("/explore/category-amazon"):
        return True
    return False


def contact_row_dedupe_key(row: ContactWorkbenchRow) -> str:
    mention = row.top_mention
    url = ((mention.canonical_url if mention else row.prospect.profile_url) or "").split("#", 1)[0].split("?", 1)[0]
    title = (mention.title if mention else row.display_label) or row.display_label
    for marker in (" 问与答 •", " 分享创造 •", " 酷工作 •", " VPS •", " • "):
        if marker in title:
            title = title.split(marker, 1)[0]
    title = re.sub(r"\s+", " ", title).strip().lower()
    if "v2ex.com" in url and title:
        return f"v2ex:title:{title[:120]}"

    match = re.search(r"v2ex\.com/(?:t/(\d+)|member/[^/]+)", url)
    if match and match.group(1):
        return f"v2ex:t:{match.group(1)}"

    if title:
        return f"{row.prospect.platform}:title:{title[:120]}"
    return f"{row.prospect.platform}:prospect:{row.prospect.id}"


def customer_query_word(customer_type: str) -> str:
    mapping = {
        "tiktok_matrix": "TikTok 矩阵",
        "amazon_multi_account": "亚马逊多账号",
        "shopee_lazada_shein": "Shopee 店群",
        "shopify_independent": "Shopify 独立站",
        "crawler_data": "爬虫采集",
        "account_service": "账号注册养号",
        "antidetect_browser": "指纹浏览器防关联",
        "social_matrix": "海外社媒矩阵",
    }
    return mapping.get(customer_type, customer_type)


def merge_note(old: str, new: str) -> str:
    old = (old or "").strip()
    new = (new or "").strip()
    if not old:
        return new
    if not new or new in old:
        return old
    return f"{old}\n{new}"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
