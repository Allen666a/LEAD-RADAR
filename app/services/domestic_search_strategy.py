from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


STRATEGY_VERSION = "domestic-session-p4-quality-diagnostics"


@dataclass(frozen=True)
class IntentKeyword:
    phrase: str
    weight: int
    category: str
    reason: str


@dataclass(frozen=True)
class DomesticSourceQuery:
    name: str
    kind: str
    url: str
    reason: str
    priority: int


BUYING_INTENT_KEYWORDS: list[IntentKeyword] = [
    IntentKeyword("TikTok 多账号 防关联", 40, "buyer_intent", "TikTok 矩阵和小店工作室的核心风险就是账号关联。"),
    IntentKeyword("TikTok 小店 防关联", 40, "buyer_intent", "小店矩阵更接近付费客户，且对网络环境敏感。"),
    IntentKeyword("TikTok 矩阵 防封", 38, "pain", "防封通常意味着已经遇到风控或准备扩号。"),
    IntentKeyword("TikTok 养号 网络环境", 36, "pain", "养号阶段会关注 IP、设备、登录环境稳定性。"),
    IntentKeyword("亚马逊 多店铺 防关联", 42, "buyer_intent", "亚马逊多店铺客户预算高，防关联是强购买意图。"),
    IntentKeyword("亚马逊 店铺关联 怎么办", 42, "pain", "已经出现问题的人更可能接受测试包。"),
    IntentKeyword("亚马逊 登录环境异常", 36, "pain", "登录环境异常经常指向 IP、设备、浏览器环境。"),
    IntentKeyword("Shopee 多账号 防关联", 34, "buyer_intent", "东南亚店群量大，适合低客单但高复购。"),
    IntentKeyword("Shopify 店群 防关联", 34, "buyer_intent", "独立站群客户对账号和支付环境有中高端需求。"),
    IntentKeyword("指纹浏览器 怎么配 IP", 40, "buyer_intent", "这类用户已经理解防关联工具，只差 IP 方案。"),
    IntentKeyword("指纹浏览器 代理IP 怎么选", 38, "buyer_intent", "明确在比较代理方案，销售可切入测试。"),
    IntentKeyword("AdsPower IP 怎么配置", 34, "tool_workflow", "指纹浏览器具体工具词，适合找操作型客户。"),
    IntentKeyword("候鸟浏览器 IP 配置", 32, "tool_workflow", "国内跨境用户常见工具词。"),
    IntentKeyword("比特浏览器 IP 配置", 32, "tool_workflow", "国内跨境用户常见工具词。"),
    IntentKeyword("AdsPower 代理 IP 防关联", 38, "tool_workflow", "工具+代理+防关联组合，比单搜代理更接近买家。"),
    IntentKeyword("MuLogin 代理 IP 配置", 34, "tool_workflow", "指纹浏览器用户通常已经有账号矩阵需求。"),
    IntentKeyword("Hubstudio 代理 IP 配置", 34, "tool_workflow", "跨境店群和社媒矩阵常见工具。"),
    IntentKeyword("TikTok 小店 多店铺 防关联", 42, "buyer_intent", "小店多店铺是动态住宅 IP 的强场景。"),
    IntentKeyword("TikTok 直播 矩阵 网络环境", 38, "buyer_intent", "直播矩阵对地区、稳定性和封号风险敏感。"),
    IntentKeyword("亚马逊 多账号 指纹浏览器 代理", 42, "buyer_intent", "亚马逊多账号客户预算高，且通常能理解环境隔离。"),
    IntentKeyword("亚马逊 账号关联 IP", 42, "pain", "明确把关联和 IP 联系起来。"),
    IntentKeyword("Shopify 多店铺 支付风控", 34, "buyer_intent", "独立站群和支付风控经常需要更干净的环境。"),
    IntentKeyword("Facebook 多账号 防关联", 34, "buyer_intent", "海外社媒矩阵的常见需求。"),
    IntentKeyword("Instagram 养号 代理", 32, "buyer_intent", "社媒养号对动态住宅和粘性会话有需求。"),
    IntentKeyword("TikTok 本土店 多账号 防关联", 44, "buyer_intent", "本土店矩阵更依赖目标国家网络环境，是动态住宅 IP 强场景。"),
    IntentKeyword("TikTok 小店 登录环境异常", 40, "pain", "登录环境异常直接指向 IP、设备指纹和地区稳定性问题。"),
    IntentKeyword("亚马逊 多店铺 登录环境", 42, "buyer_intent", "多店铺卖家通常需要隔离账号环境和 IP。"),
    IntentKeyword("亚马逊 账号关联 被封", 44, "pain", "已经出现损失的卖家更可能愿意测试替代方案。"),
    IntentKeyword("店铺关联 IP 地址", 40, "pain", "明确把店铺关联和 IP 联系起来。"),
    IntentKeyword("指纹浏览器 住宅IP 防关联", 42, "buyer_intent", "工具、住宅 IP、防关联三词同现，购买意图强。"),
    IntentKeyword("AdsPower 住宅 IP 配置", 40, "tool_workflow", "AdsPower 用户是动态住宅 IP 的高匹配人群。"),
    IntentKeyword("比特浏览器 代理 IP 防关联", 38, "tool_workflow", "国内跨境多账号用户常用工具词。"),
    IntentKeyword("账号注册 环境异常 代理", 36, "buyer_intent", "账号注册服务商消耗高、复购强，但需人工合规审核。"),
    IntentKeyword("海外账号 养号 住宅IP", 36, "buyer_intent", "海外社媒养号更贴近动态住宅和粘性会话需求。"),
]


PAIN_POINT_KEYWORDS: list[IntentKeyword] = [
    IntentKeyword("账号被关联怎么办", 40, "pain", "泛账号痛点，需要结合平台词判断。"),
    IntentKeyword("店铺被关联怎么办", 40, "pain", "店群和跨境卖家强痛点。"),
    IntentKeyword("登录环境异常", 34, "pain", "账号系统常见风控提示。"),
    IntentKeyword("账号环境异常", 34, "pain", "适合知乎、贴吧、微博等问答/讨论平台。"),
    IntentKeyword("验证码太频繁", 32, "pain", "爬虫和账号注册服务都可能需要动态住宅 IP。"),
    IntentKeyword("Cloudflare 一直验证", 38, "pain", "高消耗数据采集团队典型痛点。"),
    IntentKeyword("爬虫 403 怎么解决", 38, "pain", "爬虫团队的明确痛点，不直接搜产品词。"),
    IntentKeyword("爬虫 429 怎么解决", 36, "pain", "频控场景，适合代理测试。"),
    IntentKeyword("IP 被封 怎么办", 34, "pain", "泛痛点，需要二次质检过滤普通宽带问题。"),
    IntentKeyword("代理 IP 不稳定", 34, "pain", "有现有方案不满，适合替换型销售。"),
    IntentKeyword("账号一登录就验证", 34, "pain", "账号登录验证通常和环境/IP/设备指纹有关。"),
    IntentKeyword("频繁要求验证身份", 32, "pain", "平台风控痛点，需要人工判断具体平台和用途。"),
    IntentKeyword("Cloudflare 过不去", 38, "pain", "采集团队明确痛点。"),
    IntentKeyword("Cloudflare 5 秒盾", 36, "pain", "更贴近爬虫/采集技术讨论。"),
    IntentKeyword("爬虫 IP 被封", 38, "pain", "高消耗、长期稳定需求。"),
    IntentKeyword("爬虫 验证码 太多", 36, "pain", "代理质量和行为频率问题。"),
    IntentKeyword("请求太频繁 429", 34, "pain", "频控场景，适合按并发和国家做测试。"),
    IntentKeyword("店铺关联申诉", 34, "pain", "跨境卖家已出现损失，需快速止损。"),
    IntentKeyword("店铺登录环境不稳定", 34, "pain", "明确环境稳定性痛点。"),
    IntentKeyword("TikTok 账号被封 环境", 38, "pain", "封号与环境问题同现时，适合进入人工判断。"),
    IntentKeyword("小店登录环境异常", 38, "pain", "TikTok/跨境小店常见风控提示。"),
    IntentKeyword("亚马逊二审 IP", 36, "pain", "亚马逊账号审核场景会关注网络环境，但需合规跟进。"),
    IntentKeyword("买家号 环境异常", 32, "pain", "账号注册/养号服务常见痛点，需人工审核用途。"),
    IntentKeyword("指纹浏览器 IP 不稳定", 38, "pain", "已有工具和代理方案，适合替换型销售。"),
]


PERSONA_KEYWORDS: list[IntentKeyword] = [
    IntentKeyword("TikTok 工作室", 30, "persona", "找团队/工作室，而不是只找教程。"),
    IntentKeyword("TikTok 小店工作室", 34, "persona", "更接近商业化客户。"),
    IntentKeyword("亚马逊铺货团队", 34, "persona", "铺货团队通常多店铺、多账号。"),
    IntentKeyword("亚马逊测评团队", 32, "persona", "账号环境和 IP 需求明确，但需合规人工审核。"),
    IntentKeyword("跨境店群", 32, "persona", "覆盖 Shopee、Lazada、Shopify 等店群。"),
    IntentKeyword("独立站群", 30, "persona", "中高端场景，适合 Shopify。"),
    IntentKeyword("海外社媒矩阵", 32, "persona", "FB/IG/YouTube/X 多账号场景。"),
    IntentKeyword("账号注册服务", 34, "persona", "高消耗高复购，但风险需人工审核。"),
    IntentKeyword("养号工作室", 32, "persona", "社媒账号业务核心人群。"),
    IntentKeyword("数据采集团队", 32, "persona", "高消耗长期需求，关注 403/429/验证码。"),
    IntentKeyword("TikTok 带货工作室", 34, "persona", "直播/带货矩阵更接近付费客户。"),
    IntentKeyword("TikTok 本土店矩阵", 36, "persona", "本土店矩阵对地区和环境稳定性敏感。"),
    IntentKeyword("跨境铺货团队", 34, "persona", "铺货团队通常有多账号和多店铺隔离需求。"),
    IntentKeyword("独立站投放团队", 30, "persona", "广告/运营环境需要稳定海外网络身份。"),
    IntentKeyword("海外广告投放团队", 30, "persona", "社媒广告和账号环境相关。"),
    IntentKeyword("账号注册工作室", 34, "persona", "量大复购高，但必须进入人工合规审核。"),
    IntentKeyword("爬虫外包团队", 32, "persona", "项目型采集常遇到封禁和验证码。"),
    IntentKeyword("TikTok 本土店工作室", 36, "persona", "本土店工作室对国家、城市和登录环境更敏感。"),
    IntentKeyword("跨境测评团队", 32, "persona", "多账号和环境隔离需求明确，但需人工合规审核。"),
    IntentKeyword("海外账号注册团队", 34, "persona", "量大复购高，适合人工筛选后跟进。"),
    IntentKeyword("指纹浏览器服务商客户", 30, "persona", "围绕工具使用者发现代理替换需求。"),
]


NEGATIVE_KEYWORDS = [
    "代理IP推荐",
    "住宅IP评测",
    "动态住宅IP哪家好",
    "代理IP服务商",
    "IP代理排行榜",
    "代理IP测评",
    "住宅代理评测",
    "动态住宅IP评测",
    "代理IP哪家",
    "住宅IP哪家",
    "免费代理IP",
    "代理IP教程",
    "机场节点",
    "科学上网",
    "VPN",
]


SESSION_PLATFORM_QUERIES: dict[str, list[str]] = {
    "zhihu": [
        "TikTok 多账号会关联吗",
        "亚马逊店铺关联怎么办",
        "指纹浏览器怎么配 IP",
        "爬虫 403 怎么解决",
        "Cloudflare 一直验证怎么办",
        "亚马逊 账号关联 IP",
        "TikTok 小店 多店铺 防关联",
        "AdsPower 代理 IP 防关联",
        "TikTok 本土店矩阵 网络环境",
        "亚马逊 多账号 指纹浏览器 代理",
        "Shopify 多店铺 支付风控",
        "账号一登录就验证 怎么办",
        "TikTok 本土店 多账号 防关联",
        "TikTok 小店 登录环境异常",
        "亚马逊 账号关联 被封",
        "店铺关联 IP 地址",
        "指纹浏览器 住宅IP 防关联",
        "AdsPower 住宅 IP 配置",
    ],
    "tieba": [
        "TikTok 小店 防关联",
        "亚马逊 多店铺 防关联",
        "指纹浏览器 代理IP",
        "爬虫 IP 被封",
        "店群 防关联",
        "账号一登录就验证",
        "亚马逊 账号关联 IP",
        "TikTok 本土店矩阵",
        "跨境店群 登录环境",
        "账号注册工作室 环境",
        "Cloudflare 5 秒盾 代理",
        "TikTok 本土店 多账号 防关联",
        "小店登录环境异常",
        "店铺关联 IP 地址",
        "比特浏览器 代理 IP 防关联",
        "海外账号 养号 住宅IP",
    ],
    "xiaohongshu": [
        "TikTok 小店 防关联",
        "跨境店群 防关联",
        "指纹浏览器 IP 配置",
        "亚马逊 多账号 防关联",
        "海外社媒矩阵 养号",
        "TikTok 本土店矩阵 防关联",
        "账号注册工作室 环境",
        "TikTok 小店 工作室 网络环境",
        "跨境铺货团队 多店铺",
        "亚马逊 店铺关联 IP",
        "海外账号养号 代理",
        "TikTok 本土店工作室",
        "TikTok 小店 登录环境异常",
        "指纹浏览器 住宅IP 防关联",
        "海外账号注册团队",
        "跨境测评团队",
    ],
    "douyin": [
        "TikTok 小店 防关联",
        "TikTok 矩阵 防封",
        "跨境店群 防关联",
        "指纹浏览器 IP 配置",
        "海外社媒矩阵",
        "TikTok 直播 矩阵 网络环境",
        "TikTok 小店 多店铺 防关联",
        "TikTok 本土店 多账号",
        "跨境电商 工作室 防关联",
        "亚马逊 店群 防关联",
        "账号环境异常 代理",
        "TikTok 本土店工作室",
        "TikTok 小店 登录环境异常",
        "海外账号 养号 住宅IP",
        "指纹浏览器 住宅IP 防关联",
        "账号注册 环境异常 代理",
    ],
    "bilibili": [
        "指纹浏览器怎么配 IP",
        "爬虫 403 怎么解决",
        "Cloudflare 一直验证",
        "TikTok 多账号 防关联",
        "亚马逊 多店铺 防关联",
        "AdsPower 代理 IP 防关联",
        "Cloudflare 5 秒盾",
        "爬虫 IP 被封 怎么办",
        "请求太频繁 429 代理",
        "亚马逊 多账号 指纹浏览器",
        "TikTok 小店 多店铺 防关联",
        "TikTok 本土店 多账号 防关联",
        "亚马逊 账号关联 被封",
        "指纹浏览器 住宅IP 防关联",
        "AdsPower 住宅 IP 配置",
    ],
    "weibo": [
        "TikTok 矩阵 防封",
        "亚马逊 店铺关联",
        "账号环境异常",
        "代理 IP 不稳定",
        "爬虫 403",
        "账号一登录就验证",
        "店铺登录环境不稳定",
        "TikTok 小店 多账号",
        "跨境店群 防关联",
        "Cloudflare 一直验证",
        "账号注册 环境异常",
        "TikTok 账号被封 环境",
        "小店登录环境异常",
        "店铺关联 IP 地址",
        "海外账号 养号 住宅IP",
    ],
}


SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 20, 2, 8),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 20, 2, 8),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 15, 2, 10),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 15, 2, 10),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 20, 2, 8),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 15, 2, 10),
]


# P7: stricter buyer-intent queries. Prefer first-person pain and replacement intent,
# avoid broad "代理 IP 推荐/测评/教程" searches that mostly bring content marketing.
P7_HIGH_INTENT_SESSION_QUERIES: dict[str, list[str]] = {
    "zhihu": [
        "TikTok 小店多账号被关联怎么办",
        "TikTok 本土店登录环境异常怎么办",
        "亚马逊多店铺账号关联被封怎么办",
        "指纹浏览器住宅IP怎么配置防关联",
        "AdsPower 住宅IP 防关联怎么配置",
        "爬虫 Cloudflare 一直验证怎么解决",
        "爬虫 403 IP 被封怎么换代理",
        "代理IP不稳定想换供应商",
    ],
    "tieba": [
        "TikTok 小店账号关联怎么办",
        "亚马逊店铺关联 IP 怎么办",
        "店群登录环境异常",
        "指纹浏览器代理IP不稳定",
        "爬虫IP被封求稳定代理",
        "Cloudflare 5秒盾过不去",
    ],
    "xiaohongshu": [
        "TikTok 小店多账号防关联",
        "TikTok 本土店环境异常",
        "跨境店群账号关联",
        "指纹浏览器住宅IP配置",
        "海外账号养号网络环境",
        "亚马逊多店铺防关联",
    ],
    "douyin": [
        "TikTok 本土店多账号防关联",
        "TikTok 小店登录环境异常",
        "跨境店群防关联",
        "指纹浏览器住宅IP配置",
        "海外账号养号住宅IP",
    ],
    "bilibili": [
        "指纹浏览器住宅IP防关联",
        "AdsPower住宅IP配置",
        "爬虫403代理IP被封",
        "Cloudflare一直验证代理",
        "亚马逊多账号防关联IP",
    ],
    "weibo": [
        "TikTok账号被封环境异常",
        "亚马逊店铺关联被封",
        "代理IP不稳定换供应商",
        "爬虫403代理IP",
        "指纹浏览器住宅IP",
    ],
}

for platform, queries in P7_HIGH_INTENT_SESSION_QUERIES.items():
    SESSION_PLATFORM_QUERIES[platform] = list(dict.fromkeys(queries + SESSION_PLATFORM_QUERIES.get(platform, [])))

STRATEGY_VERSION = "solo-studio-dynamic-residential-p7-high-intent"

SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 20, 2, 8),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 20, 2, 8),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 15, 2, 10),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 15, 2, 10),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 20, 2, 8),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 15, 2, 10),
]

PUBLIC_PLATFORM_QUERIES: dict[str, list[str]] = {
    "v2ex": [
        "跨境电商",
        "爬虫",
        "代理",
        "cloudflare",
        "tiktok",
        "shopify",
        "指纹浏览器",
        "亚马逊",
        "广告投放",
    ],
    "csdn_search": [
        "爬虫 403 怎么解决",
        "Cloudflare 一直验证",
        "IP 被封 爬虫",
        "指纹浏览器 代理IP",
        "Playwright 代理 IP 被封",
        "爬虫 验证码 太多",
        "请求太频繁 429",
        "爬虫 住宅IP 被封",
        "Cloudflare 代理 IP 不稳定",
    ],
    "oschina": [
        "爬虫 403 代理",
        "Cloudflare 验证 代理",
        "指纹浏览器 代理IP",
        "代理 IP 不稳定",
        "Cloudflare 5 秒盾",
        "请求太频繁 429",
        "爬虫 住宅IP 被封",
        "Cloudflare 代理 IP 不稳定",
    ],
    "cnblogs": [
        "爬虫 403 代理",
        "Cloudflare 验证 代理",
        "Playwright 代理 IP",
        "Puppeteer 代理 IP",
        "Cloudflare 5 秒盾",
        "爬虫 IP 被封",
        "爬虫 住宅IP 被封",
        "Cloudflare 代理 IP 不稳定",
    ],
}


DEMAND_TERMS = [
    "防关联",
    "关联",
    "防封",
    "封号",
    "养号",
    "矩阵",
    "多账号",
    "多店铺",
    "店群",
    "小店",
    "登录环境",
    "环境异常",
    "账号一登录就验证",
    "店铺登录环境",
    "支付风控",
    "指纹浏览器",
    "代理ip",
    "住宅ip",
    "动态住宅",
    "海外ip",
    "tiktok",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "facebook",
    "instagram",
    "youtube",
    "爬虫",
    "采集",
    "验证码",
    "cloudflare",
    "5 秒盾",
    "403",
    "429",
    "请求太频繁",
]


NOISE_TERMS = [
    "登录",
    "注册",
    "广告",
    "隐私政策",
    "用户协议",
    "帮助中心",
    "客户端下载",
    "热搜",
    "首页",
    "百科",
    "排行榜",
    "哪家好",
    "推荐",
    "评测",
    "免费代理",
]


PAUSE_PATTERNS = [
    "验证码",
    "安全验证",
    "请先登录",
    "登录验证",
    "登录后才能",
    "账号异常",
    "访问太频繁",
    "稍后再试",
    "verify",
    "captcha",
    "robot",
    "rate limit",
    "too many requests",
]


def all_intent_keywords() -> list[IntentKeyword]:
    return BUYING_INTENT_KEYWORDS + PAIN_POINT_KEYWORDS + PERSONA_KEYWORDS


def source_queries() -> list[DomesticSourceQuery]:
    rows: list[DomesticSourceQuery] = []
    for query in SESSION_PLATFORM_QUERIES["zhihu"]:
        rows.append(
            DomesticSourceQuery(
                name=f"Zhihu Intent: {query}",
                kind="html_links",
                url=f"https://www.zhihu.com/search?type=content&q={quote(query)}",
                reason="知乎适合问题型搜索，优先搜客户痛点问题，不搜供应商产品词。",
                priority=88,
            )
        )
    for query in SESSION_PLATFORM_QUERIES["tieba"]:
        rows.append(
            DomesticSourceQuery(
                name=f"Baidu Tieba Intent: {query}",
                kind="html_links",
                url=f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={quote(query)}",
                reason="贴吧适合工作室、店群和异常求助类讨论。",
                priority=82,
            )
        )
    for tag in PUBLIC_PLATFORM_QUERIES["v2ex"]:
        rows.append(
            DomesticSourceQuery(
                name=f"V2EX Intent: {tag}",
                kind="html_links",
                url=f"https://www.v2ex.com/tag/{quote(tag)}",
                reason="V2EX 公开标签页稳定，适合作为国内公开源底盘，先抓技术/跨境/采集场景讨论。",
                priority=84,
            )
        )
    technical_queries = [
        "爬虫 403 怎么解决",
        "Cloudflare 一直验证",
        "Cloudflare 5 秒盾",
        "指纹浏览器 代理IP",
        "Playwright 代理 IP 被封",
        "Puppeteer 代理 IP 被封",
        "爬虫 验证码 太多",
        "请求太频繁 429",
    ]
    for query in technical_queries:
        rows.append(
            DomesticSourceQuery(
                name=f"SegmentFault Intent: {query}",
                kind="html_links",
                url=f"https://segmentfault.com/search?q={quote(query)}",
                reason="技术社区适合发现爬虫/采集团队的真实报错和替换需求。",
                priority=78,
            )
        )
        rows.append(
            DomesticSourceQuery(
                name=f"LearnKu Intent: {query}",
                kind="html_links",
                url=f"https://learnku.com/search?q={quote(query)}",
                reason="开发者问答适合补充 403、验证码、代理不稳等痛点。",
                priority=72,
            )
        )
    for query in PUBLIC_PLATFORM_QUERIES["csdn_search"]:
        rows.append(
            DomesticSourceQuery(
                name=f"CSDN Search Intent: {query}",
                kind="html_links",
                url=f"https://so.csdn.net/so/search?q={quote(query)}&t=all",
                reason="CSDN 全站搜索作为低优先级公开补充源，只保留标题/上下文命中痛点的结果。",
                priority=74,
            )
        )
    for query in PUBLIC_PLATFORM_QUERIES["oschina"]:
        rows.append(
            DomesticSourceQuery(
                name=f"OSChina Intent: {query}",
                kind="html_links",
                url=f"https://www.oschina.net/search?q={quote(query)}",
                reason="开源中国公开搜索适合补充国内开发者采集/代理问题。",
                priority=70,
            )
        )
    for query in PUBLIC_PLATFORM_QUERIES["cnblogs"]:
        rows.append(
            DomesticSourceQuery(
                name=f"CNBlogs Intent: {query}",
                kind="html_links",
                url=f"https://zzk.cnblogs.com/s?w={quote(query)}",
                reason="博客园搜索作为低优先级公开补充源，只保留命中痛点和场景的结果。",
                priority=62,
            )
        )
    gitee_queries = [
        "爬虫 403 代理",
        "Cloudflare 验证 代理",
        "指纹浏览器 代理IP",
        "TikTok 多账号 防关联",
        "亚马逊 多店铺 防关联",
        "账号环境异常 代理",
        "AdsPower 代理 IP 防关联",
        "爬虫 IP 被封",
        "指纹浏览器 住宅IP 防关联",
        "AdsPower 住宅 IP 配置",
        "TikTok 本土店 多账号 防关联",
        "店铺关联 IP 地址",
    ]
    for query in gitee_queries:
        rows.append(
            DomesticSourceQuery(
                name=f"Gitee Intent: {query}",
                kind="gitee_search",
                url=query,
                reason="Gitee issue 适合发现国内开发/采集团队的具体问题。",
                priority=76,
            )
        )
    seller_queries = [
        "亚马逊 多店铺 防关联",
        "亚马逊 店铺关联 怎么办",
        "TikTok 小店 防关联",
        "TikTok 小店 多店铺 防关联",
        "Shopee 多账号 防关联",
        "店群 防关联",
        "亚马逊 账号关联 IP",
        "店铺登录环境不稳定",
        "TikTok 本土店 多账号 防关联",
        "TikTok 小店 登录环境异常",
        "亚马逊 账号关联 被封",
        "店铺关联 IP 地址",
        "指纹浏览器 住宅IP 防关联",
    ]
    for query in seller_queries:
        rows.append(
            DomesticSourceQuery(
                name=f"WeAreSellers Intent: {query}",
                kind="html_links",
                url=f"https://www.wearesellers.com/search?keyword={quote(query)}",
                reason="跨境卖家社区更接近付费客户，优先搜场景痛点。",
                priority=86,
            )
        )
    return rows


# P6 positioning update: focus on solo operators, small teams and studios instead of formal B2B procurement.
STRATEGY_VERSION = "solo-studio-dynamic-residential-p6"

SOLO_STUDIO_INTENT_KEYWORDS: list[IntentKeyword] = [
    IntentKeyword("TikTok 小店 多账号 防关联", 48, "studio_buyer", "小店矩阵强痛点，成交路径短，适合轻触达。"),
    IntentKeyword("TikTok 本土店 登录环境异常", 46, "studio_pain", "登录环境异常直接关联 IP、设备指纹和地区稳定性。"),
    IntentKeyword("TikTok 矩阵 住宅IP", 46, "studio_buyer", "明确矩阵和住宅 IP，适合动态住宅测试包。"),
    IntentKeyword("指纹浏览器 住宅IP 防关联", 48, "studio_buyer", "指纹浏览器用户已经理解环境隔离，转化阻力低。"),
    IntentKeyword("AdsPower 住宅IP 配置", 44, "tool_workflow", "工具+住宅 IP 配置是操作型需求，不是泛教程词。"),
    IntentKeyword("比特浏览器 代理IP 防关联", 42, "tool_workflow", "国内工作室常用工具词，适合找多账号团队。"),
    IntentKeyword("亚马逊 多店铺 防关联 IP", 48, "studio_buyer", "多店铺防关联是高付费意愿场景。"),
    IntentKeyword("亚马逊 店铺关联 被封", 48, "studio_pain", "已经产生损失，优先进入人工判断和轻触达。"),
    IntentKeyword("Shopee 店群 防关联", 40, "studio_buyer", "东南亚店群量大，适合价格敏感型测试。"),
    IntentKeyword("跨境店群 登录环境", 40, "studio_pain", "小团队常说法，不依赖正式公司身份。"),
    IntentKeyword("账号注册 环境异常 代理", 40, "studio_pain", "账号服务商复购强，但需要人工合规审核。"),
    IntentKeyword("海外账号 养号 住宅IP", 40, "studio_buyer", "养号工作室常见需求，需先判断合法用途。"),
    IntentKeyword("爬虫 403 代理IP", 42, "solo_dev_pain", "个人开发者/接单团队真实痛点。"),
    IntentKeyword("Cloudflare 5秒盾 代理", 42, "solo_dev_pain", "采集场景痛点明确，适合询问目标站点和并发。"),
    IntentKeyword("爬虫 IP 被封 住宅IP", 44, "solo_dev_pain", "明确被封和住宅 IP，强相关。"),
    IntentKeyword("验证码 太频繁 代理IP", 38, "studio_pain", "账号和采集都可能出现，需结合平台判断。"),
    IntentKeyword("代理IP 不稳定 换供应商", 42, "replacement_intent", "替换型需求，适合小样本对比测试。"),
    IntentKeyword("动态住宅IP 测试包", 44, "buyer_intent", "明确测试包，直接对应当前成交方式。"),
]

SOLO_STUDIO_NEGATIVE_KEYWORDS = [
    "代理IP测评",
    "住宅IP测评",
    "代理IP排行榜",
    "代理IP推荐大全",
    "新手教程",
    "完整教程",
    "保姆级教程",
    "原理详解",
    "行业报告",
    "新闻",
    "融资",
    "官网文章",
    "服务商官网",
    "优惠码",
    "限时优惠",
    "API Key",
    "招聘",
    "内推",
    "岗位",
]

BUYING_INTENT_KEYWORDS = SOLO_STUDIO_INTENT_KEYWORDS + BUYING_INTENT_KEYWORDS
NEGATIVE_KEYWORDS = SOLO_STUDIO_NEGATIVE_KEYWORDS + NEGATIVE_KEYWORDS
DEMAND_TERMS = [
    "多账号",
    "防关联",
    "登录环境异常",
    "本土店",
    "小店",
    "店群",
    "矩阵",
    "指纹浏览器",
    "住宅IP",
    "动态住宅IP",
    "账号注册",
    "养号",
    "Cloudflare",
    "5秒盾",
    "403",
    "429",
    "验证码",
    "IP被封",
] + DEMAND_TERMS
NOISE_TERMS = SOLO_STUDIO_NEGATIVE_KEYWORDS + NOISE_TERMS

for platform, queries in SESSION_PLATFORM_QUERIES.items():
    SESSION_PLATFORM_QUERIES[platform] = list(dict.fromkeys([
        keyword.phrase for keyword in SOLO_STUDIO_INTENT_KEYWORDS[:10]
    ] + queries))

SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 20, 2, 8),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 20, 2, 8),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 15, 2, 10),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 15, 2, 10),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 20, 2, 8),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 15, 2, 10),
]

for platform, queries in P7_HIGH_INTENT_SESSION_QUERIES.items():
    SESSION_PLATFORM_QUERIES[platform] = list(dict.fromkeys(queries + SESSION_PLATFORM_QUERIES.get(platform, [])))

STRATEGY_VERSION = "solo-studio-dynamic-residential-p7-high-intent"

SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 20, 2, 8),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 20, 2, 8),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 15, 2, 10),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 15, 2, 10),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 20, 2, 8),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 15, 2, 10),
]


DOMESTIC_ACQUISITION_KEYWORDS = [
    (item.phrase, item.weight, item.category) for item in all_intent_keywords()
]


DOMESTIC_ACQUISITION_SOURCES = [
    (item.name, item.kind, item.url) for item in source_queries()
]


# P8: production search profile. Prefer buyer pain, replacement intent and
# current-operation questions. Avoid broad tutorial/review terms unless they
# include a concrete platform, account, crawler or anti-association problem.
P8_BUYER_PAIN_QUERIES: dict[str, list[str]] = {
    "zhihu": [
        "TikTok 小店登录环境异常 住宅IP",
        "TikTok 多账号关联 怎么解决",
        "亚马逊 多店铺 账号关联 IP",
        "指纹浏览器 住宅IP 防关联 怎么配",
        "Cloudflare 403 爬虫 住宅IP",
        "爬虫 代理IP 不稳定 一直验证",
        "海外账号养号 网络环境 住宅IP",
        "AdsPower 住宅IP 节点 不稳定",
        "住宅代理 换供应商 不稳定",
        "动态住宅IP 哪家稳定 真实使用",
    ],
    "tieba": [
        "TikTok 小店 关联 IP",
        "亚马逊 店铺 关联 IP",
        "店群 登录环境异常",
        "指纹浏览器 代理IP 不稳定",
        "爬虫 403 求稳定代理",
        "住宅IP 测试包 求推荐",
        "动态住宅代理 不稳定 换",
        "账号养号 IP 环境",
    ],
    "xiaohongshu": [
        "TikTok 小店 防关联 住宅IP",
        "跨境店群 账号关联 IP",
        "指纹浏览器 住宅IP 配置",
        "海外社媒矩阵 养号 网络环境",
        "亚马逊多店铺 防关联 IP",
        "爬虫代理IP 403 验证",
    ],
    "douyin": [
        "TikTok 矩阵 防封 住宅IP",
        "跨境店群 防关联 IP",
        "指纹浏览器 住宅IP",
        "海外账号养号 网络环境",
        "爬虫代理 IP 不稳定",
    ],
    "bilibili": [
        "指纹浏览器 住宅IP 防关联 实测",
        "TikTok 小店 多账号 防关联",
        "亚马逊 多店铺 防关联 IP",
        "爬虫 Cloudflare 403 代理IP",
        "住宅代理 不稳定 解决",
    ],
    "weibo": [
        "TikTok 矩阵 防关联 IP",
        "跨境店群 住宅IP",
        "爬虫代理IP 不稳定",
        "账号环境异常 住宅IP",
        "动态住宅代理 求推荐",
    ],
}

for platform, queries in P8_BUYER_PAIN_QUERIES.items():
    SESSION_PLATFORM_QUERIES[platform] = list(dict.fromkeys(queries + SESSION_PLATFORM_QUERIES.get(platform, [])))[:35]

STRATEGY_VERSION = "solo-studio-dynamic-residential-p8-production-intent"
SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 24, 2, 9),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 24, 2, 9),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 18, 2, 12),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 18, 2, 12),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 20, 2, 10),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 18, 2, 12),
]


# P9: practical domestic acquisition profile.
# Focus only on dynamic residential IP buyers: solo operators, studios and small
# teams with anti-association, account environment, crawler blocking and proxy
# replacement pain. Avoid broad supplier/review/tutorial queries.
P9_DYNAMIC_RESIDENTIAL_BUYER_QUERIES: dict[str, list[str]] = {
    "zhihu": [
        "TikTok 小店多账号关联怎么解决 住宅IP",
        "TikTok 本土店登录环境异常 住宅IP",
        "亚马逊多店铺账号关联 IP 怎么办",
        "指纹浏览器住宅IP防关联怎么配置",
        "AdsPower 住宅IP 节点不稳定怎么办",
        "爬虫 Cloudflare 403 住宅IP",
        "代理IP不稳定想换供应商",
        "海外账号养号网络环境住宅IP",
        "店铺关联 IP 地址怎么处理",
        "动态住宅IP测试包求推荐",
    ],
    "tieba": [
        "TikTok 小店 关联 IP",
        "亚马逊 店铺 关联 IP",
        "跨境店群 登录环境异常",
        "指纹浏览器 代理IP 不稳定",
        "爬虫 403 求稳定代理",
        "住宅IP 测试包 求推荐",
        "账号养号 IP 环境",
        "动态住宅代理 不稳定 换",
    ],
    "xiaohongshu": [
        "TikTok 小店 防关联 住宅IP",
        "跨境店群 账号关联 IP",
        "指纹浏览器 住宅IP 配置",
        "海外账号养号 网络环境",
        "亚马逊多店铺 防关联 IP",
        "账号注册 环境异常 代理",
    ],
    "douyin": [
        "TikTok 矩阵 防封 住宅IP",
        "跨境店群 防关联 IP",
        "指纹浏览器 住宅IP",
        "海外账号养号 网络环境",
        "爬虫代理 IP 不稳定",
    ],
    "bilibili": [
        "指纹浏览器 住宅IP 防关联 实测",
        "TikTok 小店 多账号 防关联",
        "亚马逊 多店铺 防关联 IP",
        "爬虫 Cloudflare 403 代理IP",
        "住宅代理 不稳定 解决",
    ],
    "weibo": [
        "TikTok 矩阵 防关联 IP",
        "跨境店群 住宅IP",
        "爬虫代理IP 不稳定",
        "账号环境异常 住宅IP",
        "动态住宅代理 求推荐",
    ],
}

for platform, queries in P9_DYNAMIC_RESIDENTIAL_BUYER_QUERIES.items():
    SESSION_PLATFORM_QUERIES[platform] = list(dict.fromkeys(queries + SESSION_PLATFORM_QUERIES.get(platform, [])))[:35]

STRATEGY_VERSION = "dynamic-residential-domestic-p9-diagnostic-smoke"
SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(SESSION_PLATFORM_QUERIES["zhihu"]), 24, 2, 9),
    ("tieba", ",".join(SESSION_PLATFORM_QUERIES["tieba"]), 18, 1, 12),
    ("xiaohongshu", ",".join(SESSION_PLATFORM_QUERIES["xiaohongshu"]), 12, 1, 18),
    ("douyin", ",".join(SESSION_PLATFORM_QUERIES["douyin"]), 12, 1, 18),
    ("bilibili", ",".join(SESSION_PLATFORM_QUERIES["bilibili"]), 16, 1, 12),
    ("weibo", ",".join(SESSION_PLATFORM_QUERIES["weibo"]), 12, 1, 18),
]


# P27: Chinese demand circle reset.
# Earlier profiles accumulated mojibake keywords in this file, which hurt recall
# for domestic buyer communities. Keep the old history for compatibility, but
# override the public strategy surface with clean Chinese terms.
STRATEGY_VERSION = "dynamic-residential-cn-demand-circle-p27"

CN_DEMAND_QUERIES = [
    "TikTok 小店 多账号 防关联",
    "TikTok 本土店 登录环境异常",
    "TikTok 矩阵 封号 住宅IP",
    "TikTok 养号 网络环境",
    "亚马逊 多店铺 防关联 IP",
    "亚马逊 账号关联 被封",
    "亚马逊 铺货团队 登录环境",
    "店群 防关联 IP 地址",
    "Shopee 店群 防关联",
    "Lazada 多账号 防关联",
    "Shopify 多店铺 支付风控",
    "独立站 店群 IP 环境",
    "指纹浏览器 住宅IP 防关联",
    "AdsPower 住宅IP 配置",
    "比特浏览器 代理IP 防关联",
    "候鸟浏览器 代理IP 配置",
    "Hubstudio 代理IP 配置",
    "海外社媒矩阵 住宅IP",
    "Facebook 多账号 防关联",
    "Instagram 养号 代理IP",
    "海外账号注册 环境异常 代理",
    "账号养号 工作室 住宅IP",
    "爬虫 403 代理IP 被封",
    "Cloudflare 一直验证 代理IP",
    "爬虫 429 住宅IP",
    "代理IP 不稳定 换供应商",
    "动态住宅IP 测试包",
    "住宅代理 不稳定",
]

CN_SESSION_QUERIES = {
    "zhihu": [
        "TikTok 小店多账号会关联吗",
        "亚马逊多店铺账号关联怎么办",
        "指纹浏览器怎么配住宅IP",
        "AdsPower 住宅IP怎么配置",
        "爬虫403代理IP被封怎么办",
        "Cloudflare一直验证怎么解决",
        "动态住宅IP哪家稳定真实使用",
    ],
    "tieba": [
        "TikTok小店防关联IP",
        "亚马逊店群防关联",
        "指纹浏览器代理IP不稳定",
        "爬虫IP被封求稳定代理",
        "住宅IP测试包求推荐",
    ],
    "xiaohongshu": [
        "TikTok小店防关联住宅IP",
        "跨境店群账号关联IP",
        "指纹浏览器住宅IP配置",
        "海外账号养号网络环境",
    ],
    "douyin": [
        "TikTok矩阵防封住宅IP",
        "跨境店群防关联IP",
        "指纹浏览器住宅IP",
        "海外账号养号网络环境",
    ],
    "bilibili": [
        "指纹浏览器住宅IP防关联",
        "AdsPower住宅IP配置",
        "爬虫Cloudflare403代理IP",
        "亚马逊多账号防关联IP",
    ],
    "weibo": [
        "TikTok矩阵防关联IP",
        "跨境店群住宅IP",
        "爬虫代理IP不稳定",
        "账号环境异常住宅IP",
    ],
}

CN_INTENT_KEYWORDS = [
    IntentKeyword("TikTok 小店 多账号 防关联", 58, "cn_buyer_intent", "中文 TikTok 小店工作室核心场景。"),
    IntentKeyword("TikTok 本土店 登录环境异常", 56, "cn_pain", "登录环境异常直接指向网络环境和 IP 稳定性。"),
    IntentKeyword("亚马逊 多店铺 防关联 IP", 60, "cn_buyer_intent", "亚马逊多账号/铺货团队高付费场景。"),
    IntentKeyword("亚马逊 账号关联 被封", 58, "cn_pain", "已出现损失，优先人工判断和轻触达。"),
    IntentKeyword("店群 防关联 IP 地址", 54, "cn_buyer_intent", "中文店群圈常见表达。"),
    IntentKeyword("指纹浏览器 住宅IP 防关联", 60, "cn_buyer_intent", "指纹浏览器用户已经理解环境隔离，转化阻力低。"),
    IntentKeyword("AdsPower 住宅IP 配置", 52, "cn_tool_workflow", "工具配置型需求，适合补联系方式后触达。"),
    IntentKeyword("比特浏览器 代理IP 防关联", 50, "cn_tool_workflow", "国内指纹浏览器生态关键词。"),
    IntentKeyword("海外社媒矩阵 住宅IP", 52, "cn_buyer_intent", "FB/IG/TikTok/YouTube 多账号场景。"),
    IntentKeyword("账号养号 工作室 住宅IP", 54, "cn_buyer_intent", "养号/注册服务商量大、复购高，但需人工合规判断。"),
    IntentKeyword("爬虫 403 代理IP 被封", 54, "cn_pain", "数据采集团队高消耗痛点。"),
    IntentKeyword("Cloudflare 一直验证 代理IP", 52, "cn_pain", "反爬验证和代理质量痛点。"),
    IntentKeyword("代理IP 不稳定 换供应商", 56, "cn_replacement_intent", "替换型需求，比泛搜索更接近成交。"),
    IntentKeyword("动态住宅IP 测试包", 58, "cn_buyer_intent", "直接对应当前可成交动作。"),
]

CN_NEGATIVE_KEYWORDS = [
    "代理IP推荐",
    "代理IP测评",
    "住宅IP测评",
    "代理IP排行榜",
    "免费代理IP",
    "代理IP教程",
    "新手教程",
    "完整教程",
    "行业报告",
    "新闻",
    "官网文章",
    "优惠码",
    "招聘",
    "岗位",
]


def all_intent_keywords() -> list[IntentKeyword]:
    return CN_INTENT_KEYWORDS


def source_queries() -> list[DomesticSourceQuery]:
    rows: list[DomesticSourceQuery] = []

    for query in CN_SESSION_QUERIES["zhihu"]:
        rows.append(
            DomesticSourceQuery(
                name=f"Zhihu Intent: {query}",
                kind="html_links",
                url=f"https://www.zhihu.com/search?type=content&q={quote(query)}",
                reason="中文问答需求圈，优先找真实求助和替换需求。",
                priority=96,
            )
        )
    for query in CN_SESSION_QUERIES["tieba"]:
        rows.append(
            DomesticSourceQuery(
                name=f"Baidu Tieba Intent: {query}",
                kind="html_links",
                url=f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={quote(query)}",
                reason="中文小团队、工作室和吧内求助补充源。",
                priority=90,
            )
        )

    for query in [
        "TikTok 小店 多账号 防关联",
        "亚马逊 多店铺 防关联 IP",
        "指纹浏览器 住宅IP 防关联",
        "AdsPower 住宅IP 配置",
        "爬虫 403 代理IP 被封",
        "Cloudflare 一直验证 代理IP",
        "代理IP 不稳定 换供应商",
    ]:
        encoded = quote(query)
        rows.extend(
            [
                DomesticSourceQuery(
                    name=f"SegmentFault Intent: {query}",
                    kind="html_links",
                    url=f"https://segmentfault.com/search?q={encoded}",
                    reason="中文技术问答，适合爬虫、403、Cloudflare、代理不稳定痛点。",
                    priority=88,
                ),
                DomesticSourceQuery(
                    name=f"LearnKu Intent: {query}",
                    kind="html_links",
                    url=f"https://learnku.com/search?q={encoded}",
                    reason="中文开发者社区补充源，只保留真实问题。",
                    priority=78,
                ),
                DomesticSourceQuery(
                    name=f"CSDN Search Intent: {query}",
                    kind="html_links",
                    url=f"https://so.csdn.net/so/search?q={encoded}&t=all",
                    reason="中文技术内容补充源，严格过滤教程和泛文章。",
                    priority=70,
                ),
                DomesticSourceQuery(
                    name=f"Gitee Intent: {query}",
                    kind="gitee_search",
                    url=query,
                    reason="国内开发者 issue 补充源，旧内容会被时间过滤。",
                    priority=72,
                ),
            ]
        )

    for query in [
        "亚马逊 多店铺 防关联",
        "亚马逊 账号关联 被封",
        "TikTok 小店 防关联",
        "Shopee 店群 防关联",
        "店群 防关联 IP 地址",
        "指纹浏览器 住宅IP 防关联",
        "代理IP 不稳定 换供应商",
    ]:
        rows.append(
            DomesticSourceQuery(
                name=f"WeAreSellers Intent: {query}",
                kind="html_links",
                url=f"https://www.wearesellers.com/search?keyword={quote(query)}",
                reason="中文跨境卖家圈，优先找防关联、账号关联和店群痛点。",
                priority=94,
            )
        )

    for tag in ["爬虫", "代理", "跨境电商", "tiktok", "shopify", "cloudflare"]:
        rows.append(
            DomesticSourceQuery(
                name=f"V2EX Intent: {tag}",
                kind="html_links",
                url=f"https://www.v2ex.com/tag/{quote(tag)}",
                reason="中文技术/独立开发社区，适合补充真实问题。",
                priority=82,
            )
        )

    return rows


SESSION_PLATFORM_QUERIES = CN_SESSION_QUERIES
SESSION_TASK_DEFAULTS = [
    ("zhihu", ",".join(CN_SESSION_QUERIES["zhihu"]), 24, 2, 9),
    ("tieba", ",".join(CN_SESSION_QUERIES["tieba"]), 18, 1, 12),
    ("xiaohongshu", ",".join(CN_SESSION_QUERIES["xiaohongshu"]), 12, 1, 18),
    ("douyin", ",".join(CN_SESSION_QUERIES["douyin"]), 12, 1, 18),
    ("bilibili", ",".join(CN_SESSION_QUERIES["bilibili"]), 16, 1, 12),
    ("weibo", ",".join(CN_SESSION_QUERIES["weibo"]), 12, 1, 18),
]
NEGATIVE_KEYWORDS = CN_NEGATIVE_KEYWORDS
DEMAND_TERMS = CN_DEMAND_QUERIES
NOISE_TERMS = CN_NEGATIVE_KEYWORDS
DOMESTIC_ACQUISITION_KEYWORDS = [(item.phrase, item.weight, item.category) for item in all_intent_keywords()]
DOMESTIC_ACQUISITION_SOURCES = [(item.name, item.kind, item.url) for item in source_queries()]
