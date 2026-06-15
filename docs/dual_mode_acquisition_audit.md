# 双模式获客系统方案外部资料审计

审计对象：

- `docs/dual_mode_acquisition_plan.md`

审计日期：

- 2026-06-11

审计目标：

- 用成熟 B2B 获客、销售情报、CRM、数据补全、意图数据和合规资料，检查当前方案是否偏离企业级获客工具路线。
- 找出文档中正确、缺失、过度设计和需要修正的地方。
- 给出下一步实现优先级。

## 1. 外部资料基准

本次参考了以下公开资料和产品说明：

- Gartner 对 lead generation software 的定义：获客软件位于销售漏斗顶部，负责自动化吸引、捕获和分发 lead，并帮助销售聚焦最可能购买的客户。  
  https://www.gartner.com/reviews/market/lead-generation-software

- Apollo 官方产品页和 Sequences 文档：Apollo 将 prospecting、lead gen、deal automation、sequence 多触点触达放在一个销售平台内。Sequence 是一段时间内按步骤执行的电话、邮件、社媒和任务组合。  
  https://www.apollo.io/  
  https://knowledge.apollo.io/hc/en-us/articles/4409237165837-Sequences-Overview

- Clay 官方资料：Clay 强调 100+ 数据源、AI research agents、自动化 GTM workflow；Waterfall enrichment 会顺序查询多个数据提供商直到找到有效结果。  
  https://www.clay.com/  
  https://www.clay.com/waterfall-enrichment

- HubSpot Lead Scoring 文档：成熟评分不是只给 lead 一个分数，而是基于 record actions/properties 对 contacts、companies、deals 建分数，并用于 segments、workflows、reports。  
  https://knowledge.hubspot.com/scoring/understand-the-lead-scoring-tool

- HubSpot Pipeline 文档：Pipeline 是阶段化过程管理，可以用于 deals、tickets、listing 等对象，核心是可视化每个 record 当前处于哪个阶段。  
  https://knowledge.hubspot.com/object-settings/set-up-and-customize-pipelines

- Salesforce Lead Management：lead management 是从第一次接触到购买的全过程管理，重点包括捕获、跟踪、资格判断、跟进、来源分析和 ROI。  
  https://www.salesforce.com/sales/what-is-lead-management/  
  https://help.salesforce.com/s/articleView?id=sales.customize_leadmgmt.htm&language=en_US&type=5

- ZoomInfo Intent Data：B2B intent data 用于识别正在研究某类解决方案的账号，帮助销售优先触达、把握时机和个性化消息。  
  https://pipeline.zoominfo.com/sales/what-is-intent-data-and-how-to-use-it

- ZoomInfo Website Visitor Insights：成熟 B2B 工具会把匿名网站访问转为 account 级别 first-party intent，用于 ABM 和后续 workflow。  
  https://pipeline.zoominfo.com/marketing/prospects-web-visitor-insights

- Cognism 和 Bombora 对 sales intelligence / intent data 的描述：成熟销售情报通常包含 firmographics、technographics、intent data、outbound automation 和合规。  
  https://www.cognism.com/blog/sales-intelligence  
  https://bombora.com/integration/cognism/

- CNIL 关于 web scraping 的合法利益说明：公开在线个人数据采集通常需要合法依据，并应采取额外措施降低对个人权益的影响。  
  https://www.cnil.fr/en/legal-basis-legitimate-interest-focus-sheet-measures-implement-case-data-collection-web-scraping

- ICO 关于 direct marketing 和 privacy/electronic communications 的说明：触达和营销需要考虑 lawful basis、PECR 和数据保护要求。  
  https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/

## 2. 总体审计结论

当前实施方案的大方向是正确的。

正确点：

- 把系统拆成“需求雷达”和“B2B 客户库”是合理的。
- “一套系统，两条流水线”比两个独立系统更合理。
- 文档已经意识到爬虫只是数据源，不是获客系统本身。
- 文档已经覆盖采集、清洗、补全、评分、跟进、反馈、合规。
- 文档聚焦海外动态住宅 IP 代理业务，没有走成泛获客工具。

主要问题：

- 评分体系还写得像一个总分，缺少成熟工具常见的“fit score + intent/engagement score”拆分。
- B2B 客户库缺少“Account / Company 为主对象”的强约束，仍然有 Prospect 视角残留。
- 数据补全没有明确 waterfall enrichment、字段置信度、来源可追溯和失败原因。
- 销售序列写得还不够企业级，缺少 touchpoint、channel、stop condition、unsubscribe/suppression 等机制。
- 合规部分方向对，但缺少数据保留、删除、抑制名单、审计日志、来源许可等可执行项。
- 缺少 first-party intent 的未来路线，例如官网访问、落地页表单、试用咨询等。
- 缺少来源 ROI 的具体指标体系。

## 3. 对当前方案的逐项审计

### 3.1 双模式架构

结论：保留。

外部依据：

- Gartner 将 lead generation 放在漏斗顶部，强调捕获和分发 lead。
- Salesforce 将 lead management 扩展到从第一次接触到购买的全过程。

审计判断：

“需求雷达”负责漏斗顶部的大量信号捕获；“B2B 客户库”负责 account 级管理和销售推进。这正好对应成熟系统中 acquisition 和 lead/account management 的分工。

需要修正：

- 文档中应明确“需求雷达不是最终客户库”，它是信号池。
- B2B 客户库必须以 Company / Account 为主对象，而不是帖子或账号。

### 3.2 需求雷达

结论：保留，但要限制定位。

当前文档把需求雷达定义为“大海捞针”，这是对的。但需要更严格限制：

- 它不追求绝对精准。
- 它追求及时发现痛点。
- 它的产物是 signal，不是 customer。
- 只有经过合并、评分、补全后，才能进入跟进池。

风险：

- 如果需求雷达直接进入销售，会导致新手教程、同行软文、噪音帖子太多。
- 如果所有平台都混在一起，销售无法判断这条数据到底该不该跟。

修正建议：

```text
需求雷达 -> Signal
Signal 通过 ICP/合规/去重 -> Prospect
Prospect 合并到 Company/Account
Company/Account 再进入 B2B 跟进
```

### 3.3 B2B 客户库

结论：必须作为下一阶段主线。

外部依据：

- Clay、Apollo、ZoomInfo、Cognism 都以公司/联系人/账号为核心，而不是帖子为核心。
- ZoomInfo intent data 明确强调识别正在研究某类解决方案的 B2B accounts。

当前文档正确点：

- 已经提出公司名、官网、国家、行业、意图信号、联系方式、ICP 分数、成交概率。

缺口：

- 没有把 Account 明确为主对象。
- 没有定义 Company 与 Prospect、Mention 的关系。
- 没有定义公司级 dedupe 的主键策略。

修正建议：

公司级主键优先级：

```text
domain > normalized_company_name + country > github_org > official_social_profile > business_email_domain
```

B2B 页面第一列不应是“线索标题”，而应是：

```text
公司 / 官网 / 国家 / 客户类型
```

### 3.4 评分体系

结论：需要重构。

外部依据：

- HubSpot lead scoring 支持 contacts、companies、deals，并基于 actions/properties 建分。
- 成熟工具通常区分 account fit、intent、engagement、contactability，而不是一个混合总分。

当前文档问题：

- “ICP 分数”和“需求强度”混在一起。
- 大海捞针的痛点强度和 B2B 的公司价值混在一个评价体系里会误导销售。

建议拆成四个分数：

```text
fit_score：客户类型是否符合动态住宅 IP 业务
intent_score：最近是否表现出需求
contact_score：是否可触达，联系方式可信度
risk_score：合规、同行、噪音、骚扰风险
```

最终优先级：

```text
priority_score = fit_score * 0.35 + intent_score * 0.35 + contact_score * 0.2 - risk_score * 0.3
```

注意：权重后续要通过反馈学习，不应永久写死。

### 3.5 数据补全

结论：当前方向正确，但缺少 waterfall enrichment 思路。

外部依据：

- Clay 官方 Waterfall enrichment 会按顺序查询多个工具，直到找到有效工作邮箱。
- Cognism、Apollo、ZoomInfo 都强调 firmographics、technographics、contact data、intent data 的组合。

当前文档问题：

- 只写了“补联系方式”，没写清楚补全顺序、置信度和失败原因。

建议补全层分成三类：

```text
company_enrichment：公司名、域名、行业、国家、规模、产品
signal_enrichment：招聘、官网关键词、GitHub、目录、社媒
contact_enrichment：邮箱、表单、LinkedIn、Telegram、微信、商务入口
```

每个补全字段都应保存：

```text
value
source_url
source_type
confidence
fetched_at
failure_reason
```

### 3.6 销售序列和 CRM

结论：文档方向对，但深度不够。

外部依据：

- Apollo Sequences 是按时间执行的多触点 campaign，包括电话、邮件、社媒和任务。
- HubSpot Pipeline 强调阶段化 record 管理。
- Salesforce Lead Management 强调从首次互动到购买全过程。

当前文档问题：

- 状态枚举有了，但缺少“活动记录”和“序列步骤”。
- 没有 stop condition。
- 没有触达频率限制。

建议新增：

```text
OutreachSequence
OutreachStep
OutreachActivity
SuppressionList
```

最小可行规则：

- 没有明确联系方式，不进入触达。
- 风险高，不进入触达。
- 同行/广告/教程，不进入触达。
- 发送前必须人工确认。
- 有回复、退订、无效、投诉，停止序列。

### 3.7 合规边界

结论：现有文档方向正确，但需要更可执行。

外部依据：

- CNIL 认为在线公开个人数据采集需要合法依据，并应采取额外措施降低对个人权益影响。
- ICO 的 direct marketing 指南强调 direct marketing 与隐私/电子通信规则。

当前文档已有：

- 不绕验证码
- 不绕登录限制
- 不批量私信
- 优先公司级数据

缺少：

- 数据保留周期
- 删除/排除机制
- suppression list
- 数据来源审计
- robots.txt / ToS 标记
- 联系频率限制
- 人工确认机制

建议新增合规字段：

```text
source_permission_status
personal_data_flag
lawful_basis_note
retention_until
do_not_contact
suppression_reason
```

### 3.8 Agent 自动化

结论：保留，但不能先做花。

当前文档中的 Agent 类型合理，但实现顺序要调整。

优先做：

```text
source_auditor
company_enricher
icp_judge
contact_enricher
```

后做：

```text
outreach_agent
crm_scheduler
```

原因：

- 没有干净数据和评分，Agent 只会自动放大噪音。
- 自动触达最容易产生合规和品牌风险，必须最后做。

## 4. 文档需要立即修订的地方

### 4.1 P0 任务调整

原 P0：

```text
拆出“需求雷达”页面
新增“B2B 客户库”页面
作战台改成双模式总控
两套评分模型分开
更新导航结构
```

审计后建议 P0：

```text
1. 明确数据对象分层：Signal -> Prospect -> Company/Account
2. 拆出需求雷达页面，定位为 Signal 池
3. 新增 B2B 客户库页面，定位为 Company/Account 池
4. 拆分 fit_score、intent_score、contact_score、risk_score
5. 作战台改成双模式总控
6. 导航更新为双模式
```

### 4.2 P1 任务调整

原 P1 偏“加数据源”，审计后应先做公司和补全框架。

审计后建议 P1：

```text
1. CompanyProfile / CompanySignal / ContactRecord 最小模型
2. 公司级 dedupe 和合并
3. Waterfall enrichment 框架
4. 官网关键词扫描
5. GitHub 组织/项目转公司画像
6. B2B CSV 导出
```

### 4.3 P2 任务调整

审计后 P2：

```text
1. 招聘信号源
2. SaaS/工具目录源
3. 来源 ROI 分析
4. 联系方式可信度
5. CRM 活动记录
6. 回复/成交反馈
```

### 4.4 P3 任务调整

审计后 P3：

```text
1. 销售序列草稿
2. 人工确认后触达
3. 企业微信/飞书提醒
4. HubSpot/飞书/Notion 导出或集成
5. first-party intent：官网访问、表单、试用咨询
```

## 5. 当前方案的评分

按企业级获客工具标准，当前方案文档评分：

```text
战略方向：8.5/10
业务聚焦：9/10
数据源设计：7/10
公司级客户库：6/10
评分体系：6/10
补全体系：6.5/10
CRM/跟进：6.5/10
合规可执行性：6/10
实现优先级：7/10
```

综合评分：

```text
7.1/10
```

评价：

```text
方向已经从“爬虫工具”转向“专业获客系统”，但还没有完全进入企业级 GTM/CRM 思维。
最大的短板不是平台不够多，而是 Company/Account 层、评分拆分、补全置信度和反馈闭环不够硬。
```

## 6. 审计后的推荐路线

不要继续盲目扩源。下一步应按以下顺序实现：

```text
第一步：数据对象分层
Signal / Prospect / Company / Contact / Activity

第二步：双模式页面
需求雷达 = Signal 池
B2B 客户库 = Company 池

第三步：评分拆分
fit_score / intent_score / contact_score / risk_score

第四步：公司级补全
domain、官网、行业、国家、产品、GitHub、招聘、联系方式

第五步：销售跟进闭环
跟进状态、活动记录、下一步动作、转化反馈

第六步：自动化
Agent 只自动做研究、补全、评分；触达保持人工确认
```

## 7. 最终结论

文档的“双模式”方向是正确的，但需要从“功能列表”进一步升级成“对象模型 + 工作流 + 指标体系”。

最关键的修正是：

```text
大海捞针不是客户库，而是 Signal 池。
B2B 客户库不是线索列表，而是 Company/Account 池。
评分不能只有一个 lead_score，必须拆成 fit、intent、contact、risk。
补全不能只是找联系方式，必须记录来源、置信度和失败原因。
触达不能自动群发，必须走序列、抑制名单、人工确认和合规记录。
```

如果按这个审计结果推进，Lead Radar 才会更接近 Clay、Apollo、ZoomInfo、HubSpot/Salesforce 这类成熟系统的工作方式，同时保持对“海外动态住宅 IP 代理业务”的垂直聚焦。
