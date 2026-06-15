from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models import Keyword, Source
from app.services import domestic_search_strategy as search_strategy
from app.settings import get_settings


KEYWORDS = [
    ("动态住宅 IP", 30, "core"),
    ("动态住宅IP", 30, "core"),
    ("海外动态 IP", 30, "core"),
    ("海外动态IP", 30, "core"),
    ("轮换住宅代理", 30, "core"),
    ("住宅 IP 池", 25, "core"),
    ("住宅IP池", 25, "core"),
    ("海外住宅代理", 25, "core"),
    ("residential proxy pool", 25, "core"),
    ("rotating residential proxy", 25, "core"),
    ("dynamic residential proxy", 25, "core"),
    ("web scraping proxy", 20, "scenario"),
    ("proxy for scraping", 20, "scenario"),
    ("socks5 动态代理", 20, "protocol"),
    ("SOCKS5 住宅", 20, "protocol"),
    ("爬虫代理 IP", 25, "scenario"),
    ("爬虫代理IP", 25, "scenario"),
    ("代理 IP 被封", 35, "pain"),
    ("代理IP被封", 35, "pain"),
    ("代理 IP 不稳定", 35, "pain"),
    ("代理IP不稳定", 35, "pain"),
    ("爬虫被封", 35, "pain"),
    ("跨境电商采集", 25, "scenario"),
    ("亚马逊采集代理", 25, "scenario"),
    ("TikTok 代理", 20, "scenario"),
    ("SERP 采集", 25, "scenario"),
    ("Google 采集", 20, "scenario"),
]

MARKET_KEYWORDS = [
    ("TikTok 养号", 30, "review"),
    ("TikTok 矩阵", 30, "review"),
    ("TikTok 小店工作室", 25, "review"),
    ("TikTok 小店", 20, "scenario"),
    ("TikTok 直播", 18, "scenario"),
    ("亚马逊多账号", 30, "review"),
    ("亚马逊铺货", 25, "scenario"),
    ("亚马逊工作室", 25, "scenario"),
    ("防关联", 35, "review"),
    ("亚马逊防关联", 35, "review"),
    ("Shopee 多账号", 28, "review"),
    ("Shopee 工作室", 25, "scenario"),
    ("Shopee 店群", 25, "review"),
    ("Lazada 多账号", 25, "review"),
    ("Lazada 工作室", 22, "scenario"),
    ("Shein 矩阵", 22, "scenario"),
    ("东南亚跨境矩阵", 25, "scenario"),
    ("社媒矩阵", 25, "review"),
    ("FB 养号", 25, "review"),
    ("IG 运营", 18, "scenario"),
    ("海外社媒工作室", 25, "scenario"),
    ("跨境爬虫", 30, "scenario"),
    ("数据采集", 20, "scenario"),
    ("海外爬虫工作室", 30, "scenario"),
    ("独立站群", 25, "review"),
    ("Shopify 多账号", 25, "review"),
    ("跨境独立站工作室", 22, "scenario"),
    ("账号注册服务", 30, "review"),
    ("养号服务商", 30, "review"),
    ("过验证", 25, "review"),
]

SOURCES = [
    ("V2EX Latest", "v2ex", "", True),
]

RSSHUB_SOURCES = [
    ("RSSHub V2EX Latest", "/v2ex/topics/latest"),
]

COMMUNITY_SOURCES = [
    ("GitHub Issues: rotating residential proxy", "github_search", "rotating residential proxy"),
    ("GitHub Issues: residential proxy pool", "github_search", "residential proxy pool"),
    ("GitHub Issues: proxy for scraping", "github_search", "proxy for scraping"),
    ("GitHub Issues: socks5 proxy", "github_search", "socks5 proxy"),
    ("GitHub Issues: proxy pool", "github_search", "proxy pool"),
    ("GitHub Issues: scraper proxy", "github_search", "scraper proxy"),
    ("Gitee Issues: 代理池", "gitee_search", "代理池"),
    ("Gitee Issues: 爬虫代理", "gitee_search", "爬虫代理"),
    ("Gitee Issues: 数据采集 代理", "gitee_search", "数据采集 代理"),
    ("Gitee Issues: socks5 代理", "gitee_search", "socks5 代理"),
]

SIGNAL_SOURCES = [
    ("V2EX Hot", "v2ex_hot", ""),
    ("V2EX Node: programmer", "v2ex_node", "programmer"),
    ("V2EX Node: python", "v2ex_node", "python"),
    ("V2EX Node: jobs", "v2ex_node", "jobs"),
    ("V2EX Node: global", "v2ex_node", "global"),
    ("V2EX Node: webmaster", "v2ex_node", "webmaster"),
    ("GitHub Issues: proxy blocked", "github_search", "proxy blocked"),
    ("GitHub Issues: proxy captcha", "github_search", "proxy captcha"),
    ("GitHub Issues: residential proxy alternative", "github_search", "residential proxy alternative"),
    ("GitHub Issues: bright data alternative", "github_search", "bright data alternative"),
    ("GitHub Issues: oxylabs alternative", "github_search", "oxylabs alternative"),
    ("Gitee Issues: 代理 不稳定", "gitee_search", "代理 不稳定"),
    ("Gitee Issues: IP 被封", "gitee_search", "IP 被封"),
    ("Gitee Issues: 验证码 代理", "gitee_search", "验证码 代理"),
    ("Gitee Issues: 爬虫 被封", "gitee_search", "爬虫 被封"),
]

SELLER_COMMUNITY_SOURCES = [
    ("WeAreSellers Forum", "html_links", "https://www.wearesellers.com/"),
    ("TikTok Seller Forum", "html_links", "https://seller-us.tiktok.com/university/forum"),
    ("Amazon Seller Forums CN", "html_links", "https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN"),
    ("Amazon Seller Forums EN", "html_links", "https://sellercentral.amazon.com/seller-forums/discussions"),
    ("V2EX Node: qna", "v2ex_node", "qna"),
    ("V2EX Node: create", "v2ex_node", "create"),
    ("V2EX Node: business", "v2ex_node", "business"),
]

MORE_SIGNAL_SOURCES = [
    ("GitHub Issues: captcha proxy scraping", "github_search", "captcha proxy scraping"),
    ("GitHub Issues: proxy rate limit scraping", "github_search", "proxy rate limit scraping"),
    ("GitHub Issues: tiktok scraping proxy", "github_search", "tiktok scraping proxy"),
    ("GitHub Issues: amazon scraping proxy", "github_search", "amazon scraping proxy"),
    ("GitHub Issues: shopee scraping proxy", "github_search", "shopee scraping proxy"),
    ("GitHub Issues: serp proxy", "github_search", "serp proxy"),
    ("Gitee Issues: 反爬 代理", "gitee_search", "反爬 代理"),
    ("Gitee Issues: 频率限制 代理", "gitee_search", "频率限制 代理"),
    ("Gitee Issues: 跨境 采集", "gitee_search", "跨境 采集"),
    ("Gitee Issues: 亚马逊 采集", "gitee_search", "亚马逊 采集"),
    ("Gitee Issues: TikTok 采集", "gitee_search", "TikTok 采集"),
]

DEVELOPER_DEMAND_SOURCES = [
    ("V2EX Tag: 跨境", "html_links", "https://www.v2ex.com/tag/%E8%B7%A8%E5%A2%83"),
    ("V2EX Tag: 爬虫", "html_links", "https://www.v2ex.com/tag/%E7%88%AC%E8%99%AB"),
    ("V2EX Tag: 代理", "html_links", "https://www.v2ex.com/tag/%E4%BB%A3%E7%90%86"),
    ("LearnKu Search: 爬虫 代理", "html_links", "https://learnku.com/search?q=%E7%88%AC%E8%99%AB%20%E4%BB%A3%E7%90%86"),
    ("LearnKu Search: 防封 IP", "html_links", "https://learnku.com/search?q=%E9%98%B2%E5%B0%81%20IP"),
    ("LearnKu Search: 验证码 爬虫", "html_links", "https://learnku.com/search?q=%E9%AA%8C%E8%AF%81%E7%A0%81%20%E7%88%AC%E8%99%AB"),
    ("SegmentFault Search: 爬虫 代理", "html_links", "https://segmentfault.com/search?q=%E7%88%AC%E8%99%AB%20%E4%BB%A3%E7%90%86"),
    ("SegmentFault Search: 代理 IP 防封", "html_links", "https://segmentfault.com/search?q=%E4%BB%A3%E7%90%86%20IP%20%E9%98%B2%E5%B0%81"),
    ("GitHub Issues: 403 proxy scraping", "github_search", '"403" proxy scraping'),
    ("GitHub Issues: proxy ban scraping", "github_search", "proxy ban scraping"),
    ("GitHub Issues: ip banned scraper", "github_search", "ip banned scraper"),
    ("GitHub Issues: playwright proxy blocked", "github_search", "playwright proxy blocked"),
    ("GitHub Issues: puppeteer proxy blocked", "github_search", "puppeteer proxy blocked"),
    ("GitHub Issues: proxy rotation captcha", "github_search", "proxy rotation captcha"),
    ("GitHub Issues: antidetect browser proxy", "github_search", "antidetect browser proxy"),
    ("GitHub Issues: fingerprint browser proxy", "github_search", "fingerprint browser proxy"),
    ("GitHub Issues: amazon account proxy", "github_search", "amazon account proxy"),
    ("GitHub Issues: tiktok account proxy", "github_search", "tiktok account proxy"),
    ("Gitee Issues: 爬虫 403", "gitee_search", "爬虫 403"),
    ("Gitee Issues: IP 限制 采集", "gitee_search", "IP 限制 采集"),
    ("Gitee Issues: 验证码 爬虫", "gitee_search", "验证码 爬虫"),
    ("Gitee Issues: 指纹浏览器 代理", "gitee_search", "指纹浏览器 代理"),
    ("Gitee Issues: 账号 防关联", "gitee_search", "账号 防关联"),
    ("Gitee Issues: 亚马逊 防关联", "gitee_search", "亚马逊 防关联"),
    ("Gitee Issues: Shopee 采集", "gitee_search", "Shopee 采集"),
]

CHINA_PLATFORM_SOURCES = [
    ("Baidu Tieba Search: 动态住宅 IP", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E5%8A%A8%E6%80%81%E4%BD%8F%E5%AE%85%20IP"),
    ("Baidu Tieba Search: 海外住宅代理", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E6%B5%B7%E5%A4%96%E4%BD%8F%E5%AE%85%E4%BB%A3%E7%90%86"),
    ("Baidu Tieba Search: 指纹浏览器 代理", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8%20%E4%BB%A3%E7%90%86"),
    ("Baidu Tieba Search: TikTok 防关联", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=TikTok%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Baidu Tieba Search: 亚马逊 防关联", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E4%BA%9A%E9%A9%AC%E9%80%8A%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Baidu Tieba Search: 爬虫 IP 被封", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E7%88%AC%E8%99%AB%20IP%20%E8%A2%AB%E5%B0%81"),
    ("Baidu Tieba Search: Cloudflare 验证码 爬虫", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=Cloudflare%20%E9%AA%8C%E8%AF%81%E7%A0%81%20%E7%88%AC%E8%99%AB"),
    ("V2EX Tag: Cloudflare", "html_links", "https://www.v2ex.com/tag/cloudflare"),
    ("V2EX Tag: Playwright", "html_links", "https://www.v2ex.com/tag/playwright"),
    ("V2EX Tag: Puppeteer", "html_links", "https://www.v2ex.com/tag/puppeteer"),
    ("V2EX Tag: Shopify", "html_links", "https://www.v2ex.com/tag/shopify"),
    ("V2EX Tag: 亚马逊", "html_links", "https://www.v2ex.com/tag/%E4%BA%9A%E9%A9%AC%E9%80%8A"),
    ("V2EX Tag: TikTok", "html_links", "https://www.v2ex.com/tag/tiktok"),
    ("LearnKu Search: Cloudflare 爬虫", "html_links", "https://learnku.com/search?q=Cloudflare%20%E7%88%AC%E8%99%AB"),
    ("LearnKu Search: Playwright 代理", "html_links", "https://learnku.com/search?q=Playwright%20%E4%BB%A3%E7%90%86"),
    ("LearnKu Search: IP 被封 爬虫", "html_links", "https://learnku.com/search?q=IP%20%E8%A2%AB%E5%B0%81%20%E7%88%AC%E8%99%AB"),
    ("SegmentFault Search: Cloudflare 爬虫", "html_links", "https://segmentfault.com/search?q=Cloudflare%20%E7%88%AC%E8%99%AB"),
    ("SegmentFault Search: Playwright 代理", "html_links", "https://segmentfault.com/search?q=Playwright%20%E4%BB%A3%E7%90%86"),
    ("SegmentFault Search: IP 被封 爬虫", "html_links", "https://segmentfault.com/search?q=IP%20%E8%A2%AB%E5%B0%81%20%E7%88%AC%E8%99%AB"),
    ("Gitee Issues: Cloudflare 爬虫", "gitee_search", "Cloudflare 爬虫"),
    ("Gitee Issues: Playwright 代理", "gitee_search", "Playwright 代理"),
    ("Gitee Issues: Puppeteer 代理", "gitee_search", "Puppeteer 代理"),
    ("Gitee Issues: 滑块验证码 代理", "gitee_search", "滑块验证码 代理"),
    ("Gitee Issues: 429 代理", "gitee_search", "429 代理"),
    ("Gitee Issues: 账号关联 代理", "gitee_search", "账号关联 代理"),
    ("Gitee Issues: 店群 防关联", "gitee_search", "店群 防关联"),
    ("Gitee Issues: TikTok 防关联", "gitee_search", "TikTok 防关联"),
    ("Gitee Issues: 亚马逊 代理", "gitee_search", "亚马逊 代理"),
]

CROSS_BORDER_SOURCES = [
    ("FOB Shanghai: 亚马逊 防关联", "html_links", "https://bbs.fobshanghai.com/search.php?mod=forum&searchid=&orderby=lastpost&ascdesc=desc&searchsubmit=yes&kw=%E4%BA%9A%E9%A9%AC%E9%80%8A%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("FOB Shanghai: 代理IP 防关联", "html_links", "https://bbs.fobshanghai.com/search.php?mod=forum&searchid=&orderby=lastpost&ascdesc=desc&searchsubmit=yes&kw=%E4%BB%A3%E7%90%86IP%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("FOB Shanghai: 指纹浏览器", "html_links", "https://bbs.fobshanghai.com/search.php?mod=forum&searchid=&orderby=lastpost&ascdesc=desc&searchsubmit=yes&kw=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8"),
    ("FOB Shanghai: TikTok 账号", "html_links", "https://bbs.fobshanghai.com/search.php?mod=forum&searchid=&orderby=lastpost&ascdesc=desc&searchsubmit=yes&kw=TikTok%20%E8%B4%A6%E5%8F%B7"),
    ("FOB Shanghai: IP 关联", "html_links", "https://bbs.fobshanghai.com/search.php?mod=forum&searchid=&orderby=lastpost&ascdesc=desc&searchsubmit=yes&kw=IP%20%E5%85%B3%E8%81%94"),
    ("WeAreSellers: 亚马逊 IP 关联", "html_links", "https://www.wearesellers.com/search?keyword=%E4%BA%9A%E9%A9%AC%E9%80%8A%20IP%20%E5%85%B3%E8%81%94"),
    ("WeAreSellers: 防关联 代理", "html_links", "https://www.wearesellers.com/search?keyword=%E9%98%B2%E5%85%B3%E8%81%94%20%E4%BB%A3%E7%90%86"),
    ("WeAreSellers: 住宅 IP", "html_links", "https://www.wearesellers.com/search?keyword=%E4%BD%8F%E5%AE%85%20IP"),
    ("WeAreSellers: 指纹浏览器", "html_links", "https://www.wearesellers.com/search?keyword=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8"),
    ("WeAreSellers: TikTok 小店 防关联", "html_links", "https://www.wearesellers.com/search?keyword=TikTok%20%E5%B0%8F%E5%BA%97%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("WeAreSellers: Shopee 多账号", "html_links", "https://www.wearesellers.com/search?keyword=Shopee%20%E5%A4%9A%E8%B4%A6%E5%8F%B7"),
    ("WeAreSellers: 店群 防关联", "html_links", "https://www.wearesellers.com/search?keyword=%E5%BA%97%E7%BE%A4%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Amazon Seller Forum CN: 防关联", "html_links", "https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN&searchTerm=%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Amazon Seller Forum CN: IP 关联", "html_links", "https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN&searchTerm=IP%20%E5%85%B3%E8%81%94"),
    ("Amazon Seller Forum CN: 多账号", "html_links", "https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN&searchTerm=%E5%A4%9A%E8%B4%A6%E5%8F%B7"),
]


def search_url(base: str, keyword: str, param: str = "q") -> str:
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{param}={quote(keyword)}"


PLATFORM_MATRIX_SOURCES = [
    # 跨境卖家社区和门户：优先发现亚马逊/TikTok/Shopee/独立站多账号、防关联、店群痛点。
    ("AMZ123: 跨境工具 防关联", "html_links", "https://www.amz123.com/"),
    ("AMZ123: 跨境头条 亚马逊 TikTok", "html_links", "https://www.amz123.com/t"),
    ("Yuguo: 跨境卖家 亚马逊 TikTok", "html_links", "https://www.cifnews.com/"),
    ("Yuguo: 知无不言 标签", "html_links", "https://m.cifnews.com/tag/wearesellers"),
    ("SellerHome: 卖家之家", "html_links", "https://mjzj.com/"),
    ("Ennews: 亿恩网 跨境", "html_links", "https://www.ennews.com/"),
    ("IKJZD: 跨境知道", "html_links", "https://www.ikjzd.com/"),
    ("IKJZD: 跨境工具导航", "html_links", "https://tools.ikjzd.com/"),
    ("Ebrun: 跨境电商", "html_links", "https://www.ebrun.com/fto/"),
    ("Egainnews: 蓝海亿观", "html_links", "https://www.egainnews.com/"),
    ("Shopify Community: Discussion", "html_links", "https://community.shopify.com/c/shopify-discussion/95"),
    ("Shopify Community: Search proxy", "html_links", search_url("https://community.shopify.com/c/shopify-discussion/95", "multiple accounts proxy")),
    ("eBay Community: multiple accounts proxy", "html_links", search_url("https://community.ebay.com/t5/forums/searchpage/tab/message", "multiple accounts proxy")),
    ("Etsy Community: multiple shops proxy", "html_links", search_url("https://community.etsy.com/t5/forums/searchpage/tab/message", "multiple shops proxy")),
    ("Walmart Seller: account suspension", "html_links", "https://sellerhelp.walmart.com/seller/s/community"),
    ("Shopee Seller: account security", "html_links", "https://seller.shopee.cn/edu/home"),
    ("Lazada Seller: account security", "html_links", "https://sellercenter.lazada.com.my/seller/helpcenter"),
    # 海外高意图论坛：广告多，但 multi-account/scraping/SEO automation 需求硬。
    ("BlackHatWorld: Residential Proxies", "html_links", "https://www.blackhatworld.com/tags/residential-proxies/"),
    ("BlackHatWorld: Proxies For Sale", "html_links", "https://www.blackhatworld.com/forums/proxies-for-sale.112/"),
    ("BlackHatWorld: multi accounting proxy", "html_links", search_url("https://www.blackhatworld.com/search/1/", "multi accounting proxy")),
    ("Reddit: proxies", "html_links", "https://www.reddit.com/r/proxies/"),
    ("Reddit: webscraping proxy", "html_links", "https://www.reddit.com/r/webscraping/search/?q=proxy&restrict_sr=1&sort=new"),
    ("Reddit: scraping residential proxy", "html_links", "https://www.reddit.com/r/scraping/search/?q=residential%20proxy&restrict_sr=1&sort=new"),
    ("Reddit: AmazonSeller account", "html_links", "https://www.reddit.com/r/AmazonSeller/search/?q=account%20proxy&restrict_sr=1&sort=new"),
    ("Reddit: TikTokHelp proxy", "html_links", "https://www.reddit.com/r/Tiktokhelp/search/?q=proxy&restrict_sr=1&sort=new"),
    ("WarriorForum: proxy", "html_links", search_url("https://www.warriorforum.com/search.php", "residential proxy")),
    # 爬虫/反爬技术社区：只保留 blocked/captcha/rotating residential 等明确痛点。
    ("StackOverflow: residential proxy scraping", "html_links", "https://stackoverflow.com/search?q=dynamic+residential+proxy+scraping"),
    ("StackOverflow: Cloudflare proxy scraping", "html_links", "https://stackoverflow.com/search?q=cloudflare+proxy+scraping"),
    ("Scrapy: proxy blocked issues", "github_search", "repo:scrapy/scrapy proxy blocked"),
    ("Scrapy: rotating proxy issues", "github_search", "repo:scrapy/scrapy rotating proxy"),
    ("Playwright: proxy blocked issues", "github_search", "repo:microsoft/playwright proxy blocked"),
    ("Playwright: captcha proxy issues", "github_search", "repo:microsoft/playwright captcha proxy"),
    ("Puppeteer: proxy blocked issues", "github_search", "repo:puppeteer/puppeteer proxy blocked"),
    ("Puppeteer: captcha proxy issues", "github_search", "repo:puppeteer/puppeteer captcha proxy"),
    ("Apify Community: proxy", "html_links", "https://discord.apify.com/"),
    ("Apify Docs/Forum: proxy", "html_links", "https://apify.com/proxy"),
    # 防关联/指纹浏览器生态：找代理配置、账号环境异常、IP 不稳定相关公开讨论。
    ("AdsPower: proxy configuration", "html_links", "https://help.adspower.com/docs/proxy"),
    ("AdsPower: account anti association", "html_links", "https://www.adspower.com/"),
    ("GoLogin: proxy", "html_links", "https://gologin.com/"),
    ("Dolphin Anty: proxy", "html_links", "https://dolphin-anty.com/"),
    ("Multilogin: proxy", "html_links", "https://multilogin.com/"),
    ("Octo Browser: proxy", "html_links", "https://octobrowser.net/"),
    ("BitBrowser: 代理IP 防关联", "html_links", "https://www.bitbrowser.cn/"),
    ("Hubstudio: 代理IP 防关联", "html_links", "https://www.hubstudio.cn/"),
]


HIGH_INTENT_PLATFORM_QUERIES = (
    "动态住宅IP",
    "住宅IP 防关联",
    "TikTok 小店 防关联",
    "亚马逊 多账号 防关联",
    "账号关联 IP",
    "指纹浏览器 代理IP",
    "爬虫 403 代理",
    "Cloudflare 住宅代理",
    "代理IP 不稳定",
    "换供应商 代理IP",
)


def high_intent_platform_search_sources() -> list[tuple[str, str, str]]:
    sources: list[tuple[str, str, str]] = []
    for query in HIGH_INTENT_PLATFORM_QUERIES:
        encoded = quote(query)
        sources.extend(
            [
                (
                    f"WeAreSellers Search: {query}",
                    "html_links",
                    f"https://www.wearesellers.com/search?keyword={encoded}",
                ),
                (
                    f"Amazon Seller Forum CN Search: {query}",
                    "html_links",
                    f"https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN&searchTerm={encoded}",
                ),
                (
                    f"Shopify Community Search: {query}",
                    "html_links",
                    f"https://community.shopify.com/c/shopify-discussion/95?q={encoded}",
                ),
                (
                    f"Reddit Search: {query}",
                    "html_links",
                    f"https://www.reddit.com/search/?q={encoded}&sort=new",
                ),
                (
                    f"StackOverflow Search: {query}",
                    "html_links",
                    f"https://stackoverflow.com/search?q={encoded}",
                ),
            ]
        )
    english_queries = (
        "rotating residential proxy blocked",
        "residential proxy account suspension",
        "multiple accounts proxy",
        "cloudflare 403 residential proxy",
        "captcha blocked proxy scraping",
        "tiktok account proxy",
        "amazon seller account proxy",
        "antidetect browser proxy",
    )
    for query in english_queries:
        encoded = quote(query)
        sources.extend(
            [
                (
                    f"BlackHatWorld Search: {query}",
                    "html_links",
                    f"https://www.blackhatworld.com/search/1/?q={encoded}",
                ),
                (
                    f"Reddit Search: {query}",
                    "html_links",
                    f"https://www.reddit.com/search/?q={encoded}&sort=new",
                ),
                (
                    f"WarriorForum Search: {query}",
                    "html_links",
                    f"https://www.warriorforum.com/search.php?q={encoded}",
                ),
            ]
        )
    return sources


HIGH_INTENT_PLATFORM_SEARCH_SOURCES = high_intent_platform_search_sources()


P30_SEARCH_AGGREGATION_QUERIES = (
    ("Bing Search: 2026 residential proxy blocked scraping", "2026 residential proxy blocked scraping site:github.com OR site:reddit.com OR site:stackoverflow.com"),
    ("Bing Search: 2026 cloudflare captcha proxy scraping", "2026 cloudflare captcha proxy scraping site:github.com OR site:stackoverflow.com OR site:reddit.com"),
    ("Bing Search: 2026 multiple accounts proxy", "2026 multiple accounts proxy site:community.shopify.com OR site:community.ebay.com OR site:reddit.com"),
    ("Bing Search: 2026 amazon seller account proxy", "2026 amazon seller account proxy site:sellercentral.amazon.com OR site:reddit.com"),
    ("Bing Search: 2026 tiktok account proxy", "2026 tiktok account proxy site:reddit.com OR site:github.com"),
    ("Bing Search: 2026 antidetect browser proxy", "2026 antidetect browser proxy site:reddit.com OR site:github.com"),
    ("Bing Search: 2026 rotating residential proxy captcha", "2026 rotating residential proxy captcha site:github.com OR site:stackoverflow.com"),
    ("Bing Search: 动态住宅IP 防关联 2026", "动态住宅IP 防关联 2026 site:v2ex.com OR site:segmentfault.com OR site:wearesellers.com"),
    ("Bing Search: 亚马逊 多账号 防关联 2026", "亚马逊 多账号 防关联 2026 site:wearesellers.com OR site:sellercentral.amazon.com OR site:v2ex.com"),
    ("Bing Search: TikTok 小店 登录环境异常 2026", "TikTok 小店 登录环境异常 2026 site:wearesellers.com OR site:zhihu.com OR site:v2ex.com"),
    ("Bing Search: 指纹浏览器 住宅IP 防关联 2026", "指纹浏览器 住宅IP 防关联 2026 site:v2ex.com OR site:segmentfault.com OR site:wearesellers.com"),
    ("Bing Search: 爬虫 403 住宅IP 2026", "爬虫 403 住宅IP 2026 site:segmentfault.com OR site:learnku.com OR site:github.com"),
    ("Bing Search: Cloudflare 5秒盾 代理 2026", "Cloudflare 5秒盾 代理 2026 site:segmentfault.com OR site:v2ex.com OR site:learnku.com"),
)


P30_SEARCH_AGGREGATION_SOURCES = [
    ("P30 " + name, "html_links", f"https://www.bing.com/search?q={quote(query)}")
    for name, query in P30_SEARCH_AGGREGATION_QUERIES
]


P30_PROFESSIONAL_API_SOURCES = [
    ("P30 GitHub Issues: residential proxy blocked 2026", "github_search", "residential proxy blocked"),
    ("P30 GitHub Issues: rotating residential proxy captcha 2026", "github_search", "rotating residential proxy captcha"),
    ("P30 GitHub Issues: cloudflare 403 proxy 2026", "github_search", "cloudflare 403 proxy"),
    ("P30 GitHub Issues: cloudflare captcha proxy 2026", "github_search", "cloudflare captcha proxy"),
    ("P30 GitHub Issues: playwright proxy blocked 2026", "github_search", "playwright proxy blocked"),
    ("P30 GitHub Issues: puppeteer proxy blocked 2026", "github_search", "puppeteer proxy blocked"),
    ("P30 GitHub Issues: scraper proxy banned 2026", "github_search", "scraper proxy banned"),
    ("P30 GitHub Issues: youtube residential proxy 2026", "github_search", "youtube residential proxy"),
    ("P30 GitHub Issues: tiktok proxy account 2026", "github_search", "tiktok proxy account"),
    ("P30 GitHub Issues: amazon account proxy 2026", "github_search", "amazon account proxy"),
    ("P30 GitHub Issues: repo scrapy proxy blocked 2026", "github_search", "repo:scrapy/scrapy proxy blocked"),
    ("P30 GitHub Issues: repo playwright proxy blocked 2026", "github_search", "repo:microsoft/playwright proxy blocked"),
    ("P30 GitHub Issues: repo puppeteer proxy blocked 2026", "github_search", "repo:puppeteer/puppeteer proxy blocked"),
    ("P30 Gitee Issues: 爬虫 403 住宅IP 2026", "gitee_search", "爬虫 403 住宅IP"),
    ("P30 Gitee Issues: Cloudflare 代理 2026", "gitee_search", "Cloudflare 代理"),
    ("P30 Gitee Issues: 指纹浏览器 住宅IP 2026", "gitee_search", "指纹浏览器 住宅IP"),
    ("P30 Gitee Issues: 亚马逊 防关联 IP 2026", "gitee_search", "亚马逊 防关联 IP"),
    ("P30 Gitee Issues: TikTok 防关联 IP 2026", "gitee_search", "TikTok 防关联 IP"),
]


P33_HIGH_CONFIDENCE_API_SOURCES = [
    # P33: use precise pain + buyer context. These API sources are fresher and cleaner
    # than broad public-search pages, so they should be preferred by the collector.
    ("P33 GitHub Issues: scraper 403 rotating proxy 2026", "github_search", '"scraper" "403" "rotating proxy"'),
    ("P33 GitHub Issues: cloudflare 403 residential proxy 2026", "github_search", '"cloudflare" "403" "residential proxy"'),
    ("P33 GitHub Issues: captcha residential proxy 2026", "github_search", '"captcha" "residential proxy"'),
    ("P33 GitHub Issues: ip blocked scraper proxy 2026", "github_search", '"ip blocked" "scraper" "proxy"'),
    ("P33 GitHub Issues: playwright proxy 403 2026", "github_search", '"playwright" "proxy" "403"'),
    ("P33 GitHub Issues: puppeteer proxy 403 2026", "github_search", '"puppeteer" "proxy" "403"'),
    ("P33 GitHub Issues: instagram proxy account 2026", "github_search", '"instagram" "proxy" "account"'),
    ("P33 GitHub Issues: youtube proxy account 2026", "github_search", '"youtube" "proxy" "account"'),
    ("P33 GitHub Issues: tiktok scraper blocked proxy 2026", "github_search", '"tiktok" "scraper" "proxy"'),
    ("P33 GitHub Issues: amazon scraper proxy blocked 2026", "github_search", '"amazon" "scraper" "proxy"'),
    ("P33 GitHub Issues: shopify scraper proxy blocked 2026", "github_search", '"shopify" "scraper" "proxy"'),
    ("P33 GitHub Issues: serp captcha proxy 2026", "github_search", '"serp" "captcha" "proxy"'),
    ("P33 Gitee Issues: 爬虫 403 代理 2026", "gitee_search", "爬虫 403 代理"),
    ("P33 Gitee Issues: Cloudflare 403 代理 2026", "gitee_search", "Cloudflare 403 代理"),
    ("P33 Gitee Issues: 验证码 住宅IP 2026", "gitee_search", "验证码 住宅IP"),
    ("P33 Gitee Issues: 指纹浏览器 IP 防关联 2026", "gitee_search", "指纹浏览器 IP 防关联"),
    ("P33 Gitee Issues: TikTok 小店 登录环境 2026", "gitee_search", "TikTok 小店 登录环境"),
    ("P33 Gitee Issues: 亚马逊 店铺关联 IP 2026", "gitee_search", "亚马逊 店铺关联 IP"),
]


P34_STUDIO_BUYER_SEARCH_QUERIES = (
    "TikTok 小店 登录环境异常",
    "TikTok 本土店 多账号 防关联",
    "TikTok 小店 账号关联 IP",
    "亚马逊 店铺关联 IP",
    "亚马逊 多店铺 防关联 IP",
    "亚马逊 二审 IP 环境",
    "Shopee 店群 防关联 IP",
    "Shopify 多店铺 支付风控 IP",
    "指纹浏览器 住宅IP 防关联",
    "AdsPower 住宅IP 配置",
    "比特浏览器 代理IP 防关联",
    "代理IP 不稳定 换供应商",
    "动态住宅IP 测试包",
)


def p34_studio_buyer_sources() -> list[tuple[str, str, str]]:
    sources: list[tuple[str, str, str]] = []
    for query in P34_STUDIO_BUYER_SEARCH_QUERIES:
        encoded = quote(query)
        sources.extend(
            [
                (
                    f"P34 WeAreSellers Intent: {query}",
                    "html_links",
                    f"https://www.wearesellers.com/search?keyword={encoded}",
                ),
                (
                    f"P34 Zhihu Intent: {query}",
                    "html_links",
                    f"https://www.zhihu.com/search?type=content&q={encoded}",
                ),
                (
                    f"P34 Tieba Intent: {query}",
                    "html_links",
                    f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={encoded}",
                ),
            ]
        )
    return sources


P34_STUDIO_BUYER_SOURCES = p34_studio_buyer_sources()

DOMESTIC_ACQUISITION_KEYWORDS = [
    ("动态住宅代理", 35, "core"),
    ("动态住宅IP代理", 35, "core"),
    ("海外动态住宅IP", 35, "core"),
    ("海外住宅IP代理", 32, "core"),
    ("TikTok IP 防关联", 35, "review"),
    ("TikTok 住宅IP", 32, "scenario"),
    ("TikTok 小店 防关联", 32, "review"),
    ("TikTok 矩阵 防关联", 32, "review"),
    ("亚马逊 IP 关联", 35, "review"),
    ("亚马逊 住宅IP 防关联", 35, "review"),
    ("亚马逊 多店铺 防关联", 32, "review"),
    ("Shopee 店群 IP", 30, "review"),
    ("Shopee 防关联", 30, "review"),
    ("指纹浏览器 住宅IP", 35, "review"),
    ("AdsPower 代理IP", 28, "scenario"),
    ("候鸟浏览器 代理IP", 28, "scenario"),
    ("比特浏览器 代理IP", 28, "scenario"),
    ("店匠 店群 IP", 26, "scenario"),
    ("Shopify 店群 IP", 30, "review"),
    ("Cloudflare 住宅代理", 32, "pain"),
    ("爬虫 住宅代理", 30, "scenario"),
    ("爬虫 IP 被封", 35, "pain"),
    ("数据采集 住宅IP", 30, "scenario"),
]

DOMESTIC_ACQUISITION_SOURCES = [
    ("Zhihu Search: 动态住宅代理", "html_links", "https://www.zhihu.com/search?type=content&q=%E5%8A%A8%E6%80%81%E4%BD%8F%E5%AE%85%E4%BB%A3%E7%90%86"),
    ("Zhihu Search: TikTok IP 防关联", "html_links", "https://www.zhihu.com/search?type=content&q=TikTok%20IP%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Zhihu Search: 亚马逊 IP 关联", "html_links", "https://www.zhihu.com/search?type=content&q=%E4%BA%9A%E9%A9%AC%E9%80%8A%20IP%20%E5%85%B3%E8%81%94"),
    ("Zhihu Search: 指纹浏览器 住宅IP", "html_links", "https://www.zhihu.com/search?type=content&q=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8%20%E4%BD%8F%E5%AE%85IP"),
    ("Zhihu Search: 爬虫 IP 被封", "html_links", "https://www.zhihu.com/search?type=content&q=%E7%88%AC%E8%99%AB%20IP%20%E8%A2%AB%E5%B0%81"),
    ("Baidu Tieba Search: TikTok IP 防关联", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=TikTok%20IP%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("Baidu Tieba Search: 亚马逊 IP 关联", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E4%BA%9A%E9%A9%AC%E9%80%8A%20IP%20%E5%85%B3%E8%81%94"),
    ("Baidu Tieba Search: 指纹浏览器 住宅IP", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8%20%E4%BD%8F%E5%AE%85IP"),
    ("Baidu Tieba Search: Shopee 防关联", "html_links", "https://tieba.baidu.com/f/search/res?ie=utf-8&qw=Shopee%20%E9%98%B2%E5%85%B3%E8%81%94"),
    ("V2EX Tag: 跨境电商", "html_links", "https://www.v2ex.com/tag/%E8%B7%A8%E5%A2%83%E7%94%B5%E5%95%86"),
    ("V2EX Tag: 指纹浏览器", "html_links", "https://www.v2ex.com/tag/%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8"),
    ("V2EX Tag: TikTok", "html_links", "https://www.v2ex.com/tag/tiktok"),
    ("SegmentFault Search: 指纹浏览器 代理IP", "html_links", "https://segmentfault.com/search?q=%E6%8C%87%E7%BA%B9%E6%B5%8F%E8%A7%88%E5%99%A8%20%E4%BB%A3%E7%90%86IP"),
    ("SegmentFault Search: 住宅IP 爬虫", "html_links", "https://segmentfault.com/search?q=%E4%BD%8F%E5%AE%85IP%20%E7%88%AC%E8%99%AB"),
    ("LearnKu Search: 住宅IP 爬虫", "html_links", "https://learnku.com/search?q=%E4%BD%8F%E5%AE%85IP%20%E7%88%AC%E8%99%AB"),
    ("Gitee Issues: TikTok IP 防关联", "gitee_search", "TikTok IP 防关联"),
    ("Gitee Issues: 亚马逊 IP 关联", "gitee_search", "亚马逊 IP 关联"),
    ("Gitee Issues: 指纹浏览器 住宅IP", "gitee_search", "指纹浏览器 住宅IP"),
    ("Gitee Issues: 爬虫 IP 被封", "gitee_search", "爬虫 IP 被封"),
]


DOMESTIC_ACQUISITION_KEYWORDS = search_strategy.DOMESTIC_ACQUISITION_KEYWORDS
DOMESTIC_ACQUISITION_SOURCES = search_strategy.DOMESTIC_ACQUISITION_SOURCES


def seed_defaults(db: Session) -> dict[str, int]:
    keyword_count = 0
    source_count = 0

    for phrase, weight, category in KEYWORDS:
        exists = db.query(Keyword).filter(Keyword.phrase == phrase).first()
        if exists:
            continue
        db.add(Keyword(phrase=phrase, weight=weight, category=category))
        keyword_count += 1

    for name, kind, url, enabled in SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"keywords": keyword_count, "sources": source_count}


def seed_market_expansion(db: Session, enabled: bool = True) -> dict[str, int]:
    keyword_count = 0

    for phrase, weight, category in MARKET_KEYWORDS:
        exists = db.query(Keyword).filter(Keyword.phrase == phrase).first()
        if exists:
            exists.weight = weight
            exists.category = category
            exists.enabled = True
            continue
        db.add(Keyword(phrase=phrase, weight=weight, category=category))
        keyword_count += 1

    db.commit()
    return {"keywords": keyword_count, "sources": 0, "enabled": int(enabled)}


def seed_rsshub_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    settings = get_settings()
    source_count = 0

    for name, route in RSSHUB_SOURCES:
        url = settings.rsshub_url(route)
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = "rss"
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind="rss", url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"rsshub_sources": source_count, "enabled": int(enabled)}


def seed_community_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, query in COMMUNITY_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = query
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=query, enabled=enabled))
        source_count += 1

    db.commit()
    return {"community_sources": source_count, "enabled": int(enabled)}


def seed_signal_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, query in SIGNAL_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = query
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=query, enabled=enabled))
        source_count += 1

    db.commit()
    return {"signal_sources": source_count, "enabled": int(enabled)}


def seed_seller_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, url in SELLER_COMMUNITY_SOURCES + MORE_SIGNAL_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"seller_sources": source_count, "enabled": int(enabled)}


def seed_developer_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, url in DEVELOPER_DEMAND_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"developer_sources": source_count, "enabled": int(enabled)}


def seed_china_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, url in CHINA_PLATFORM_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"china_sources": source_count, "enabled": int(enabled)}


def seed_crossborder_sources(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, url in CROSS_BORDER_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"crossborder_sources": source_count, "enabled": int(enabled)}


def seed_platform_matrix(db: Session, enabled: bool = True) -> dict[str, int]:
    source_count = 0

    for name, kind, url in (
        PLATFORM_MATRIX_SOURCES
        + HIGH_INTENT_PLATFORM_SEARCH_SOURCES
        + P30_SEARCH_AGGREGATION_SOURCES
        + P30_PROFESSIONAL_API_SOURCES
        + P33_HIGH_CONFIDENCE_API_SOURCES
        + P34_STUDIO_BUYER_SOURCES
    ):
        source_enabled = False if name.startswith("P30 Bing Search:") else enabled
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = source_enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=source_enabled))
        source_count += 1

    db.commit()
    return {"platform_matrix_sources": source_count, "enabled": int(enabled)}


def seed_domestic_acquisition(db: Session, enabled: bool = True) -> dict[str, int]:
    keyword_count = 0
    source_count = 0

    for phrase, weight, category in DOMESTIC_ACQUISITION_KEYWORDS:
        exists = db.query(Keyword).filter(Keyword.phrase == phrase).first()
        if exists:
            exists.weight = weight
            exists.category = category
            exists.enabled = True
            continue
        db.add(Keyword(phrase=phrase, weight=weight, category=category))
        keyword_count += 1

    for name, kind, url in DOMESTIC_ACQUISITION_SOURCES:
        exists = db.query(Source).filter(Source.name == name).first()
        if exists:
            exists.kind = kind
            exists.url = url
            exists.enabled = enabled
            continue
        db.add(Source(name=name, kind=kind, url=url, enabled=enabled))
        source_count += 1

    db.commit()
    return {"domestic_keywords": keyword_count, "domestic_sources": source_count, "enabled": int(enabled)}
