# Lead Radar

Lead Radar 是一个面向海外动态住宅 IP 代理业务的独立获客工具。

第一版目标很窄：监控公开信息源，发现正在讨论“动态住宅 IP、轮换代理、爬虫封 IP、跨境电商采集、SERP 采集”等需求的人或公司，然后自动入库、评分、推送和跟进。

## 当前能力

- 关键词库：聚焦海外动态住宅 IP 和采集痛点
- 数据源：RSSHub、RSS、GitHub Search、V2EX 最新主题
- 线索入库：按 URL 去重
- 规则评分：高意向、目标场景、风险词、静态住宅排除
- 跟进工作台：线索状态、详情页、评分原因、复制话术、手动企微推送
- 企业微信推送：高分线索可自动提醒
- Web 后台：查看线索、来源、关键词
- CLI：初始化、种子数据、单次采集、回填增强信息、启动服务

## 快速开始

```powershell
cd D:\AI_Project\lead-radar
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
lead-radar init-db
lead-radar seed
lead-radar seed-rsshub --disabled
lead-radar seed-community
lead-radar seed-signals
lead-radar seed-sellers
lead-radar seed-developer
lead-radar seed-china
lead-radar seed-domestic-acquisition
lead-radar run-once
lead-radar refresh-enrichment
lead-radar audit-sources
lead-radar rebuild-prospects
lead-radar serve --host 127.0.0.1 --port 8788
```

打开：

```text
http://127.0.0.1:8788
```

## 常用命令

```powershell
.\.venv\Scripts\lead-radar.exe run-once
.\.venv\Scripts\lead-radar.exe run-domestic-acquisition --limit 30
.\.venv\Scripts\lead-radar.exe refresh-enrichment
.\.venv\Scripts\lead-radar.exe audit-sources
.\.venv\Scripts\lead-radar.exe rebuild-prospects
.\.venv\Scripts\lead-radar.exe daily-report
.\.venv\Scripts\lead-radar.exe apply-keywords --limit 10
.\.venv\Scripts\lead-radar.exe apply-sources --limit 12
.\.venv\Scripts\lead-radar.exe growth-cycle --keyword-limit 6 --source-limit 8
.\.venv\Scripts\lead-radar.exe seed-rsshub
.\.venv\Scripts\lead-radar.exe seed-community
.\.venv\Scripts\lead-radar.exe seed-signals
.\.venv\Scripts\lead-radar.exe seed-sellers
.\.venv\Scripts\lead-radar.exe seed-developer
.\.venv\Scripts\lead-radar.exe seed-china
.\.venv\Scripts\lead-radar.exe seed-domestic-acquisition
.\.venv\Scripts\lead-radar.exe serve --host 127.0.0.1 --port 8788
```

## 融合 RSSHub

本项目不魔改大型 CRM，而是把 RSSHub 作为数据源适配层。

启动 RSSHub：

```powershell
cd D:\AI_Project\lead-radar
docker compose up -d rsshub
```

检查 RSSHub：

```text
http://127.0.0.1:1200
```

把 RSSHub 路由写入线索源：

```powershell
.\.venv\Scripts\lead-radar.exe seed-rsshub
```

如果只想先登记但不启用：

```powershell
.\.venv\Scripts\lead-radar.exe seed-rsshub --disabled
```

当前默认预置：

- `RSSHub V2EX Latest` -> `/v2ex/topics/latest`

后续新增中文站点时，优先新增 RSSHub route，再让 Lead Radar 消费 feed，不在业务系统里重复写平台适配逻辑。

## 推荐第一批关键词

- 动态住宅 IP
- 海外动态 IP
- 轮换住宅代理
- residential proxy pool
- rotating residential proxy
- proxy for scraping
- 爬虫代理 IP
- 代理 IP 被封
- socks5 动态代理
- 跨境电商采集
- 亚马逊采集代理
- TikTok 代理
- SERP 采集

## 市场扩展画像

`lead-radar seed-market` 会新增一批更贴近海外动态住宅 IP 的商业画像词。它不会创建新闻检索或泛搜索来源。

- TikTok 矩阵/小店/直播工作室
- 亚马逊多账号/铺货/工作室
- Shopee、Lazada、Shein 东南亚跨境矩阵
- FB、IG、YouTube、Twitter/X 海外社媒矩阵
- 跨境爬虫、海外爬虫工作室、数据采集团队
- 独立站群、Shopify 多账号、跨境独立站工作室
- 账号注册、养号、过验证等高敏场景

注意：多账号、防关联、养号、账号注册等词会被标记为“需人工审核”，不建议自动触达。优先承接公开数据采集、跨境运营环境测试、价格/库存/评论监控等合规需求。

## 来源扩展原则

不要接新闻检索和泛搜索流，噪音太高。后续只接明确有讨论/求助/交易意图的平台源：

- V2EX、GitHub、Gitee、技术论坛
- 跨境电商论坛、卖家社区、问答社区
- RSSHub 中稳定的社区/帖子/话题路由
- 公开招聘信号源
- 明确的竞品讨论、评价、替代词页面

## 社区源

`lead-radar seed-community` 会新增高意图社区源：

- GitHub Issues: rotating residential proxy
- GitHub Issues: residential proxy pool
- GitHub Issues: proxy for scraping
- GitHub Issues: socks5 proxy
- GitHub Issues: proxy pool
- GitHub Issues: scraper proxy
- Gitee Issues: 代理池
- Gitee Issues: 爬虫代理
- Gitee Issues: 数据采集 代理
- Gitee Issues: socks5 代理

这些源是技术讨论/问题场景，不是新闻检索。

GitHub 获客边界：GitHub 只适合发现开发者、爬虫、数据采集团队、自动化团队的需求，不代表全部市场。TikTok 矩阵、亚马逊多账号、跨境卖家工作室等客户，需要继续依赖中文社区、卖家论坛、招聘信号、私域导入和人工线索补全。

## 信号源

`lead-radar seed-signals` 会新增更接近顶级获客工具的信号源：

- V2EX Hot
- V2EX programmer/python/jobs/global/webmaster 节点
- GitHub Issues 中的 proxy blocked、proxy captcha、竞品替代词
- Gitee Issues 中的代理不稳定、IP 被封、验证码代理、爬虫被封

这些源仍然是帖子、Issue、讨论源，不是新闻检索。

## 卖家与平台社区源

`lead-radar seed-sellers` 会新增更多高意图来源：

- WeAreSellers Forum
- Amazon Seller Forums CN/EN
- TikTok Seller Forum
- V2EX qna/create/business 等节点
- GitHub/Gitee 中更贴近代理痛点的查询：captcha proxy scraping、proxy rate limit scraping、tiktok/amazon/shopee scraping proxy、反爬代理、频率限制代理、跨境采集等

这些源会抓到不少普通运营帖，所以评分规则会强制要求出现代理、IP、采集、爬虫、验证码、风控、防关联等上下文才进入高价值信号。

## 开发者需求源

`lead-radar seed-developer` 会新增开发者、爬虫、采集、指纹浏览器相关需求源：

- V2EX tag 页面：跨境、爬虫、代理
- LearnKu/SegmentFault 站内搜索：爬虫代理、防封 IP、验证码爬虫
- GitHub Issues：403 proxy scraping、ip banned scraper、playwright/puppeteer proxy blocked、proxy rotation captcha、fingerprint browser proxy、antidetect browser proxy、amazon/tiktok account proxy
- Gitee Issues：爬虫 403、IP 限制采集、验证码爬虫、指纹浏览器代理、账号防关联、亚马逊防关联、Shopee 采集

这批源会额外过滤教程、测评、购买渠道、普通工程任务、GitHub feat/fix/refactor 类施工日志，优先保留求助、失败、被封、验证码、频率限制、代理异常等真实痛点。

## 国内平台源

`lead-radar seed-china` 会新增中文公开平台源：

- 百度贴吧搜索：动态住宅 IP、海外住宅代理、指纹浏览器代理、TikTok/亚马逊防关联、爬虫 IP 被封、Cloudflare 验证码爬虫
- V2EX tag：Cloudflare、Playwright、Puppeteer、Shopify、亚马逊、TikTok
- LearnKu/SegmentFault：Cloudflare 爬虫、Playwright 代理、IP 被封爬虫
- Gitee Issues：Cloudflare 爬虫、Playwright/Puppeteer 代理、滑块验证码代理、429 代理、账号关联代理、店群防关联等

国内平台里，贴吧/Gitee 可能出现 403 或限流；这类源后续适合做 Token、浏览器会话或代理出口采集。当前版本只抓公开页面，不绕登录。

## 国内获客源

`lead-radar seed-domestic-acquisition` 会新增更偏获客的国内关键词和公开来源。

关键词聚焦：动态住宅代理、海外动态住宅 IP、TikTok IP 防关联、亚马逊 IP 关联、多店铺防关联、Shopee 店群、Shopify 店群、指纹浏览器住宅 IP、AdsPower/比特/候鸟浏览器代理 IP、Cloudflare、爬虫 IP 被封、数据采集住宅 IP。

公开来源聚焦：知乎搜索、百度贴吧搜索、V2EX 标签、SegmentFault/LearnKu 搜索、Gitee Issues。

小红书、抖音、微信群、QQ群、飞书群等更接近真实获客，但通常需要登录或人工识别，默认走 `/imports` 私域导入，不做无授权抓取。

```powershell
.\.venv\Scripts\lead-radar.exe seed-domestic-acquisition
.\.venv\Scripts\lead-radar.exe seed-domestic-acquisition --disabled
.\.venv\Scripts\lead-radar.exe run-domestic-acquisition --limit 30
```

## 来源质量审计

`lead-radar audit-sources` 会给每个来源计算健康分，并在必要时自动暂停低质量来源。

质量状态：

- `优质`：稳定且持续产出高价值线索
- `正常`：可继续观察
- `低产`：抓得到数据，但有效线索偏少
- `受阻`：连续出现 403、401、429、rate limit、Forbidden、ConnectTimeout 等问题
- `不稳`：连续失败次数过多

默认会自动停用连续受阻或长期低产的来源。如果只想审计、不自动停用：

```powershell
.\.venv\Scripts\lead-radar.exe audit-sources --no-disable
```

## 客户画像

`lead-radar rebuild-prospects` 会把单条帖子/Issue 聚合成潜在客户画像。

当前聚合维度：

- GitHub/Gitee 作者或仓库 owner
- V2EX、SegmentFault、LearnKu 等平台账号或帖子 URL
- 同一来源里的同一作者

产品匹配分只围绕海外动态住宅 IP：

- `动态住宅直匹配`：出现动态住宅、住宅 IP、海外住宅、rotating/dynamic residential、mobile proxy 等直接词
- `场景匹配`：出现防关联、指纹浏览器、矩阵、店群、Cloudflare、验证码、风控、被封等可由动态住宅 IP 解决的场景
- `弱匹配`：只有泛爬虫/泛代理讨论，先观察
- `静态/非目标`：静态住宅、固定 IP、ISP proxy、dedicated residential 等，不作为重点线索

Web 后台 `/prospects` 可以查看画像列表和关联证据。

## 销售跟进池

Web 后台 `/pipeline` 是销售执行页。

默认只进入跟进池的客户：

- 产品匹配为 `动态住宅直匹配` 或 `场景匹配`
- 客户画像评分不低于 60
- 状态不是已成交或无效

支持动作：

- 推进阶段：新客户、已筛选、已触达、已加微信、已发测试、待复访、已成交、无效
- 安排复访：1 天、3 天、7 天、14 天后
- 记录下一步动作和跟进备注

重建客户画像时，会保留已有销售状态、备注、复访时间和最近联系时间。

## 转化归因分析

Web 后台 `/analytics` 用来判断哪些来源和客户类型真的值得继续投入。

当前统计维度：

- 来源归因：来源类型、健康分、入库线索、高价值信号、关联客户、已触达、已加微信、已发测试、已成交、无效客户
- 客户类型归因：TikTok 矩阵、跨境卖家、爬虫/数据采集、指纹浏览器/防关联、社媒矩阵等类型的客户数、平均分、试用率、成交率
- CSV 导出：`/analytics.csv`

`audit-sources` 已经把销售结果纳入来源质量评分：能带来试用和成交的来源会加权，持续产生无效客户的来源会降权。这样后续扩源不是盲目堆数量，而是按真实转化反推优先级。

## 获客策略台

Web 后台 `/strategy` 会把分析结果转成可执行任务：

- 销售执行：当前最该处理的高分客户
- 关键词加码：值得继续扩词、扩平台搜索的需求词
- 来源加码：值得复制相邻板块或同类搜索语法的来源
- 客户画像：当前最值得聚焦的话术方向
- 来源/关键词降噪：高噪音、低产出的来源和词

CSV 导出：`/strategy.csv`。

这个页面是后续迭代的主控台：先看策略台，再决定是扩源、降噪、改话术，还是推进销售跟进。

策略台和 `/sources` 都会生成下一轮来源候选，可以一键加入来源库。候选源只来自 GitHub/Gitee Issue、中文技术问答、社区搜索等公开讨论页面，不接新闻检索，也不接同行官网软文。

策略台顶部有超级任务列表：

- 批量加入关键词：把高优先扩词候选写入关键词库
- 批量加入来源：把高优先来源候选写入来源库
- 执行增长循环：扩词、扩源、采集、重建客户、审计来源一次跑完
- 今日作战摘要：活跃跟进池、到期复访、高分新客户、缺下一步动作、测试待推进、缺联系方式

CLI 也可以执行同样动作：

```powershell
.\.venv\Scripts\lead-radar.exe apply-keywords --limit 10
.\.venv\Scripts\lead-radar.exe apply-sources --limit 12
.\.venv\Scripts\lead-radar.exe growth-cycle --keyword-limit 6 --source-limit 8
```

谨慎自动停用来源：网页里的增长循环默认不会自动停用低质源，先看审计结果再决定。命令行只有显式加 `--auto-disable-sources` 才会自动停用。

## 关键词管理

Web 后台 `/keywords` 支持新增关键词、调整权重、启用/停用关键词，并会生成下一轮扩词候选。

扩词候选只围绕海外动态住宅 IP 的真实需求场景：

- TikTok 矩阵、小店、养号和 IP 防关联
- 亚马逊多账号、IP 关联、住宅代理防关联
- 指纹浏览器、AdsPower、Dolphin Anty 等环境工具
- Cloudflare 验证码、429、Playwright/Puppeteer 采集被封
- 社媒矩阵和账号环境

不把静态住宅、固定 IP、ISP 专线、新闻热词、同行软文作为核心扩词方向。

## 国内私域导入

Web 后台 `/imports` 支持 CSV 导入国内获客线索，适合微信群、QQ群、飞书群、小红书、抖音、知乎人工筛选、展会名片、朋友圈和销售手工整理表格。

下载模板：`/imports/sample.csv`。

导入后会进入客户画像和跟进池，系统自动补产品匹配、客户类型、分数、话术和下一步建议。

## 国内平台矩阵

Web 后台 `/platforms` 会展示国内平台覆盖状态：可自动采集、受阻需会话/Token、私域/人工导入，并统计来源数、成功失败、线索数、高价值线索和推荐动作。

CSV 导出：`/platforms.csv`。

## 会话采集器

Web 后台 `/session-collector` 支持登录态浏览器采集。你手动登录知乎、贴吧、小红书、抖音等平台，工具使用本地浏览器 profile 低频打开关键词搜索页，抽取公开可见内容并入库。

CLI：

```powershell
.\.venv\Scripts\lead-radar.exe session-login --platform zhihu
.\.venv\Scripts\lead-radar.exe session-collect --platform zhihu
```

边界：不破解验证码、不绕登录、不自动私信、不自动关注/评论。遇到验证码、登录失效、访问频繁会暂停，留给人工处理。

## Token 与配置检查

Web 后台 `/settings` 可以检查关键配置是否已启用，不会显示 token 明文。

建议配置：

```env
GITHUB_TOKEN=
GITEE_TOKEN=
WEWORK_WEBHOOK_URL=
```

没有 token 时，GitHub/Gitee 搜索源容易出现 rate limit、403、Forbidden。来源页会记录最近错误，`audit-sources` 会识别受阻源并降权或暂停。

## 销售日报

Web 后台 `/report` 可以查看销售日报，并在配置企业微信 webhook 后一键推送。

CLI：

```powershell
.\.venv\Scripts\lead-radar.exe daily-report
.\.venv\Scripts\lead-radar.exe daily-report --send-wework
```

日报包含：

- 今日新增线索
- 今日新增高价值信号
- 当前可跟进客户
- 今日到期复访
- 今日优先客户
- 优质来源
- 受阻来源

销售任务看板 `/tasks` 支持导出 `/tasks.csv`，策略台 `/strategy.csv` 会同时导出行动建议、销售摘要、扩词候选、来源候选和高优先客户。

## 合规边界

只监控公开页面和公开接口，不绕登录、不采集敏感个人信息、不做批量骚扰。高风险场景会被评分规则标记为风险线索。

## 业界路线

获客工具常见做法不是纯智能体一把梭，而是分层：

- 数据源层：RSSHub、搜索 API、公开站点抓取、GitHub API
- 管道层：Python workers、队列、定时任务
- 规则层：关键词、场景、风险词、竞品词、去重
- AI 层：摘要、意向判断、话术生成，不负责直接骚扰用户
- 销售层：企业微信、SCRM、人工跟进、试用包转化
