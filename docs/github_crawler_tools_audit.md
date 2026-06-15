# GitHub 爬虫与反阻塞项目审计

审计时间：2026-06-14

目标：下载优秀开源爬虫、浏览器采集、反阻塞样本项目，研究它们和 Lead Radar 的差距。结论只服务一个方向：提升动态住宅 IP 获客工具的采集稳定性、数据量、时效性和可解释性，不把工具做成绕风控或账号滥用系统。

## 1. 已下载项目

源码统一放在：

`research/github-crawler-tools/`

### 生产级采集框架

| 项目 | 仓库 | 最近提交 | 主要价值 |
|---|---|---:|---|
| scrapy | https://github.com/scrapy/scrapy | 2026-06-12 | Python 爬虫框架标杆，适合学习 pipeline、middleware、scheduler、item 流程 |
| crawlee | https://github.com/apify/crawlee | 2026-06-12 | JS/TS 现代爬虫框架，队列、存储、代理、会话、Playwright/Puppeteer 一体化 |
| crawlee-python | https://github.com/apify/crawlee-python | 2026-06-12 | Crawlee Python 版，适合研究是否能和当前 Python 栈融合 |
| crawl4ai | https://github.com/unclecode/crawl4ai | 2026-06-04 | LLM-ready Markdown/结构化抽取，适合做网页正文清洗和证据摘要 |
| firecrawl | https://github.com/firecrawl/firecrawl | 2026-06-13 | 搜索、抓取、结构化、批量任务 API 化，适合学习产品接口设计 |
| playwright-python | https://github.com/microsoft/playwright-python | 2026-06-12 | 浏览器采集基础能力，适合登录态平台和 JS 页面 |
| puppeteer | https://github.com/puppeteer/puppeteer | 2026-06-12 | Node 浏览器自动化标杆 |
| scrapy-playwright | https://github.com/scrapy-plugins/scrapy-playwright | 2026-06-13 | 把 Scrapy 调度和 Playwright 渲染结合起来 |
| scrapy-redis | https://github.com/rmax/scrapy-redis | 2026-05-19 | 分布式队列、去重、Redis 调度，适合大规模来源采集 |

### 高风险/反阻塞样本

只作为研究样本，不直接产品化接入。

| 项目 | 仓库 | 最近提交 | 研究价值 |
|---|---|---:|---|
| undetected-chromedriver | https://github.com/ultrafunkamsterdam/undetected-chromedriver | 2025-07-05 | 浏览器会话、反自动化检测样本；提醒 IP 信誉本身也会影响访问 |
| puppeteer-extra | https://github.com/berstend/puppeteer-extra | 2023-03-01 | Puppeteer 插件体系、stealth 插件生态 |
| cloudscraper | https://github.com/VeNoMouS/cloudscraper | 2025-06-10 | Cloudflare 类阻塞识别、Session 维护、403 恢复样本 |
| FlareSolverr | https://github.com/FlareSolverr/FlareSolverr | 2026-06-05 | 将浏览器挑战处理封装成代理服务的架构样本 |
| selenium-stealth | https://github.com/diprajpatra/selenium-stealth | 2020-11-05 | 较旧的 Selenium stealth 样本，只看历史思路 |
| camoufox | https://github.com/daijro/camoufox | 2026-06-10 | 浏览器指纹/环境伪装样本，只做风险研究 |
| curl_cffi | https://github.com/lexiforest/curl_cffi | 2026-06-13 | TLS/JA3/HTTP2/HTTP3 指纹、异步请求、代理轮换样本 |
| botasaurus | https://github.com/omkarcloud/botasaurus | 2026-03-18 | 一体化采集框架、桌面/网页化封装、缓存、并行、会话思路 |
| stealth benchmark | https://github.com/omkarcloud/botasaurus-vs-undetected-chromedriver-vs-puppeteer-stealth-benchmarks | 2024-01-24 | 对抗工具对比样本，辅助理解各类方案局限 |

## 2. 最重要的发现

### 2.1 我们现在缺的不是“更多爬虫库”，而是采集工程骨架

Lead Radar 当前已经有来源、关键词、过滤、线索池，但采集层还偏轻：

- 来源是顺序跑，缺少真正的 URL 队列。
- 失败只记录错误文本，缺少标准化失败类型。
- 每个平台没有独立的请求预算、降频策略和恢复策略。
- 对 JS 页面、登录态页面、列表页翻页、详情页二跳采集还不够系统。
- 对“采集了多少、过滤了多少、为什么过滤”的可解释进度还不够强。

成熟框架的共同点是：

- 有 Request Queue。
- 有 Dedup Fingerprint。
- 有 Retry / Timeout / Backoff。
- 有 Item Pipeline。
- 有 Session Pool。
- 有 Proxy / Browser Pool。
- 有结构化存储和导出。
- 有失败诊断。

这才是我们下一阶段最该补的。

### 2.2 Crawlee 是最值得借鉴的工程模型

Crawlee 的价值不在某个选择器，而在整体抽象：

- 同时支持 HTTP 和浏览器采集。
- 持久化请求队列。
- 数据集存储。
- 自动扩缩容。
- 会话管理。
- 代理轮换。
- Hooks。
- 错误重试。
- Playwright/Puppeteer 统一入口。

对 Lead Radar 的启发：

我们应该把“自动采集”改成一个真正的任务队列：

`SourceTask -> SearchPage -> ResultCard -> DetailPage -> RawItem -> Freshness -> QualityGate -> LeadPool`

用户点击一次“自动采集”，后台应该能展示：

- 正在跑哪些来源。
- 每个来源抓了多少候选。
- 多少因为 2026 时间过滤被丢弃。
- 多少因为广告/教程/同行软文被丢弃。
- 多少进入线索池。
- 哪些来源被验证码、登录、403、频控阻塞。

### 2.3 Scrapy + Scrapy-Redis 适合学习大规模稳定性

Scrapy 的成熟点：

- middleware 分层清晰。
- item pipeline 清晰。
- scheduler/downloader/spider 分工明确。
- 可测试、可扩展。

Scrapy-Redis 的成熟点：

- 多 worker 共享队列。
- URL 去重。
- item 后处理队列。

对我们最有用的是：

- 不要让一个来源采集失败影响整个采集。
- 每个平台独立任务、独立失败计数、独立降频。
- URL 去重不能只靠 canonical_url，还应该有 source + title + author + published_at 的近似去重。
- 大量候选先进入候选池，再做时效和质量筛选。

### 2.4 Crawl4AI / Firecrawl 值得学习“正文清洗和结构化输出”

我们现在有时会把页面标题、搜索摘要当成线索证据，这会导致误判。

Crawl4AI / Firecrawl 的启发：

- 把网页转成干净 Markdown。
- 从正文中抽取结构化字段。
- 支持截图、HTML、正文、metadata 多种证据。
- 搜索结果不等于线索，详情页正文才是更可靠证据。

对我们很关键：

- 每条线索应该尽量有“原文时间、正文片段、详情页证据、来源链接”。
- 搜索页只做候选，详情页才进入高质量判断。
- 没读到详情页正文的线索，最多进入“待复核池”，不要直接高分。

### 2.5 高风险项目说明了一件事：平台受阻不是一个问题，而是一组问题

反阻塞项目里常见的受阻类型：

- IP 信誉差。
- 数据中心 IP 被识别。
- TLS/JA3/HTTP2 指纹不像真实浏览器。
- Headless 浏览器特征。
- Cookie/Session 不稳定。
- 访问频率异常。
- 页面要求登录。
- 页面要求验证码/安全验证。
- JS Challenge。
- 平台动态 DOM/接口变化。

这对我们有两个启发：

1. 产品里不要只显示“受阻”  
   要显示“受阻原因”：未登录、验证码、403、超时、低质过多、详情页不可读、时间不合格、疑似广告等。

2. 不要盲目重试  
   连续受阻的平台应该自动降频，等待人工确认或换来源，不要反复请求。

## 3. 不建议直接融合的东西

不建议把以下能力接进 Lead Radar：

- 自动绕验证码。
- 自动绕登录保护。
- 自动绕 Cloudflare/风控挑战。
- 自动私信、自动评论、自动关注。
- 大规模账号池、多账号批量操作。
- 自动化模拟真人互动来规避平台规则。

原因：

- 账号风险高。
- 法务和平台规则风险高。
- 容易把获客工具变成灰产工具。
- 对当前业务真正收益不一定高。

我们可以借鉴的是工程思想：

- Session 保持。
- 失败分类。
- 低频采集。
- 人工介入点。
- 来源健康度。
- 采集预算。
- 队列和重试。
- 详情页证据抽取。

## 4. 对 Lead Radar 的差距判断

### 现在已经有的能力

- 来源管理。
- GitHub/Gitee/V2EX/SegmentFault/WeAreSellers 等公开来源采集。
- 国内平台登录态采集雏形。
- 2026 时效过滤。
- 动态住宅 IP 业务画像。
- 线索池、补联系方式、跟进和反馈。
- 基础任务队列。

### 仍然不够产品级的地方

1. 自动采集还不够像“采集引擎”  
   现在更像多个 collector 的串行执行，缺少统一 URL 队列、详情页队列、失败分类、重试预算。

2. 详情页证据不足  
   很多线索还依赖搜索摘要。搜索摘要容易错配、过期、广告化。

3. 来源健康不够可操作  
   只说受阻不够，要能告诉用户：为什么受阻、要不要登录、是否降频、下次何时再跑。

4. 去重还可以更强  
   同一问题可能在搜索页、详情页、作者页、多个来源重复出现。

5. 采集数量不稳定  
   用户期望“默认全部来源海量找线索”，但实际受限于平台阻塞、关键词命中和强过滤。

6. 高质量和高召回还没分层  
   应该先大规模进“候选池”，再筛到“线索池”。不要一开始过滤太狠导致用户看到数量少。

## 5. 推荐融合路线

### P27：采集引擎骨架

做一个轻量版 Crawlee/Scrapy 思路的内部引擎：

- `SourceTask`：一个来源的一轮采集。
- `FetchJob`：一个具体 URL 或搜索任务。
- `CandidateItem`：搜索页候选。
- `RawItem`：详情页读完后的原始线索。
- `Mention`：通过时效和质量门槛后的正式线索。

关键字段：

- source_id
- platform
- query
- url
- canonical_url
- status
- failure_type
- attempts
- next_run_at
- fetched_at
- published_at
- evidence_text

### P28：详情页二跳采集

所有搜索结果先进入候选池。

高质量判断优先读详情页：

- 标题。
- 作者。
- 发布时间。
- 正文。
- 评论/回答摘要。
- 链接。

只有读不到详情页时，才使用搜索摘要，并降低可信度。

### P29：来源失败分类和降频

标准化失败类型：

- `login_required`
- `captcha_required`
- `forbidden_403`
- `rate_limited_429`
- `timeout`
- `empty_result`
- `low_quality_result`
- `old_content_only`
- `parser_changed`
- `network_error`

每个来源有独立策略：

- 成功：正常频率。
- 低质：降低优先级。
- 受阻：暂停一段时间。
- 需要登录：提示用户登录。
- 验证码：停止自动重试，等待人工处理。

### P30：候选池和线索池分离

现在用户看到线索少，一个原因是过滤太强。

改成两层：

- 候选池：大海捞针，数量可以大。
- 线索池：通过 2026 + 场景 + 痛点 + 意向 + 非广告过滤。

这样用户既能看到系统确实采了很多，也能看到为什么最终留下少数高质量线索。

### P31：正文清洗和证据摘要

借 Crawl4AI / Firecrawl 的思路，不一定直接依赖它们：

- 清掉导航、广告、推荐列表。
- 提取主标题、正文、发布时间。
- 保留原文证据。
- 生成“为什么留下/为什么丢弃”的短解释。

### P32：采集进度面板

用户点击自动采集后，应看到：

- 总来源数。
- 正在跑的平台。
- 候选数量。
- 详情页成功数量。
- 过滤数量。
- 进入线索池数量。
- 失败平台及原因。

这是用户信任工具的关键。

## 6. 结论

这次下载的爬虫项目给出的结论很清楚：

Lead Radar 不应该继续堆按钮，也不应该直接集成高风险绕过工具。

下一阶段应该做“采集引擎升级”：

1. 默认全部来源采集。
2. 搜索页先进入候选池。
3. 详情页二跳读取证据。
4. 2026 时间强过滤。
5. 广告/教程/同行软文降权或丢弃。
6. 来源失败标准化。
7. 平台受阻自动降频。
8. 用户看到完整采集进度。

这条路线最实用，能直接解决用户现在最关心的问题：线索少、旧数据混入、来源受阻看不懂、自动采集不像真正的采集引擎。
