# 实施任务清单：双模式获客系统

## 1. 执行原则

后续开发按以下顺序推进：

```text
对象模型 -> 评分服务 -> 页面拆分 -> 公司合并 -> 补全闭环 -> 作战台总控
```

不再优先做：

```text
盲目扩平台
自动群发
绕平台风控
堆按钮和无用页面
```

## 2. P0：双模式最小闭环

### P0-1：新增数据模型

目标：

```text
让系统能表达 Signal / Prospect / Company / Contact / Activity。
```

涉及文件：

```text
app/models.py
app/database.py
```

任务：

- 新增 `CompanyProfile`
- 新增 `CompanySignal`
- 新增 `ContactRecord`
- 新增 `OutreachActivity`
- 新增 `SuppressionEntry`
- 给 `Mention` 增加 `mode/company_id/fit_score/intent_score/contact_score/risk_score/priority_score`
- 给 `Prospect` 增加 `company_id/mode/fit_score/intent_score/contact_score/risk_score/priority_score/contact_status/suppressed`
- 给 `Source` 增加 `mode/permission_status/noise_rate/qualified_rate/contactable_rate/roi_score`
- 更新自动迁移逻辑

验收：

- `lead-radar init-db` 不报错
- 老数据库启动后自动补字段
- 新表存在
- 老数据不丢失

### P0-2：新增双模式评分服务

目标：

```text
用 fit_score / intent_score / contact_score / risk_score 替代单一 lead_score。
```

涉及文件：

```text
app/services/scoring.py
app/services/icp_quality.py
app/services/signals.py
```

新增文件建议：

```text
app/services/dual_mode_scoring.py
```

任务：

- 实现需求雷达评分
- 实现 B2B 评分
- 输出四个基础分
- 输出 priority_score
- 输出解释字段
- 保留兼容 `lead_score`

验收：

- 同一条社区痛点走需求雷达评分
- 同一家公司走 B2B 评分
- 高风险记录不会进入高优先级
- 页面能显示评分原因

### P0-3：公司级合并服务

目标：

```text
把 Prospect/Mention 合并到 CompanyProfile。
```

新增文件建议：

```text
app/services/company_profiles.py
```

任务：

- 实现 `normalize_domain`
- 实现 `normalize_company_name`
- 实现 `build_company_key`
- 从 Prospect 创建或更新 CompanyProfile
- 从 Mention 创建 CompanySignal
- 计算 Company 聚合分数
- 统计 signal_count/source_count/contact_count

验收：

- 同一 domain 只生成一个 Company
- 同一 GitHub org 只生成一个 Company
- Company 能看到关联 Prospect 和 Signal
- Company 分数能由关联信号更新

### P0-4：回填命令

目标：

```text
把现有数据回填到 Company 层。
```

涉及文件：

```text
app/cli.py
```

新增命令：

```powershell
lead-radar rebuild-companies
lead-radar rescore-dual-mode
```

任务：

- 从已有 Prospect 生成 Company
- 从已有 Mention 生成 CompanySignal
- 从已有联系方式生成 ContactRecord
- 回写 company_id
- 重算四分制评分

验收：

- 执行命令后 B2B 客户库有数据
- 重复执行不会重复创建公司
- 命令输出创建/更新/跳过数量

### P0-5：需求雷达页面

目标：

```text
把大海捞针信号从首页/客户库里拆出来。
```

涉及文件：

```text
app/main.py
app/templates/demand_radar.html
app/templates/base.html
```

任务：

- 新增 `/demand-radar`
- 新增列表服务
- 支持筛选来源、痛点类型、分数、风险、状态
- 显示四分制
- 显示来源平台
- 支持转为线索、标记噪音、标记同行、标记风险

验收：

- 页面只展示 Signal/痛点线索
- 每条记录显示来源平台
- 高风险记录明显标记
- 操作后状态可保存

### P0-6：B2B 客户库页面

目标：

```text
新增公司级客户库。
```

涉及文件：

```text
app/main.py
app/templates/b2b_accounts.html
app/templates/company_detail.html
app/templates/base.html
```

新增服务建议：

```text
app/services/b2b_accounts.py
```

任务：

- 新增 `/b2b-accounts`
- 新增 `/b2b-accounts/{company_id}`
- 列表以 Company 为主
- 显示官网、行业、客户类型、四分制、联系方式状态、CRM 状态
- 详情显示信号、联系方式、关联线索、Activity
- 支持 CSV 导出

验收：

- B2B 页面第一列是公司/官网
- 高分公司有代理需求理由
- 公司详情能看到来源证据
- 可筛选“缺联系方式”

### P0-7：补联系方式升级

目标：

```text
补联系方式支持 Company 和 ContactRecord。
```

涉及文件：

```text
app/services/contact_workbench.py
app/services/contact_enrichment.py
app/templates/contact_workbench.html
app/main.py
```

任务：

- 支持 company_id
- 保存联系方式到 ContactRecord
- 同步更新 Company/Prospect contact_status
- 记录 confidence/source_url/source_type
- 保存 Activity

验收：

- 从 B2B 客户库可进入补联系方式
- 保存联系方式后 Company 可见
- 联系方式带来源或备注
- Activity 有记录

### P0-8：作战台双模式改造

目标：

```text
作战台同时展示需求雷达和 B2B。
```

涉及文件：

```text
app/services/acquisition_ops.py
app/templates/acquisition_ops.html
```

任务：

- 增加需求雷达指标
- 增加 B2B 客户库指标
- 展示今日新增 Signal
- 展示今日新增 Company
- 展示待补联系方式 Company
- 展示高风险/受阻来源
- 给出今日建议

验收：

- 作战台明确分成需求雷达和 B2B
- 用户能看到今天该跑什么、该补什么、该跟谁
- 不再只是线索总数

### P0-9：导航和 UI 整理

目标：

```text
让双模式在 UI 上一眼可见。
```

涉及文件：

```text
app/templates/base.html
```

任务：

- 在“获客”下加入需求雷达、B2B 客户库
- 调整作战台到工作台或获客核心位置
- 左侧当前模块选中态保持
- 表格不挤压核心操作

验收：

- 用户能一眼区分大海捞针和 B2B
- 当前页面选中状态明确
- 常用操作在首屏可见

## 3. P1：B2B 数据能力

### P1-1：官网关键词扫描

任务：

- 输入 domain/website
- 抓取首页、about、product、pricing、contact
- 检测 scraping/crawler/proxy/anti-bot/data extraction 等关键词
- 生成 CompanySignal

### P1-2：GitHub 组织/项目转公司画像

任务：

- 从 GitHub repo/org 解析组织
- 识别 scraper/crawler/spider/proxy pool 项目
- 合并到 Company
- 生成 B2B intent signal

### P1-3：Waterfall enrichment 框架

任务：

- 定义 enrichment steps
- 每个 step 记录成功/失败
- 保存 confidence
- 支持跳过低置信结果

### P1-4：B2B CSV 导出

字段：

```text
company_name
website
country
customer_type
priority_score
fit_score
intent_score
contact_score
risk_score
need_reason
contact_status
crm_status
next_action
```

## 4. P2：销售闭环

### P2-1：招聘信号源

目标：

- 发现招聘爬虫、数据采集、反爬、风控岗位的公司。

### P2-2：来源 ROI 分析

指标：

```text
新增 Signal
新增 Company
A 类数量
联系方式数量
触达数量
有兴趣数量
成交数量
噪音率
```

### P2-3：Activity 时间线

目标：

- Company 和 Prospect 详情页显示所有跟进记录。

### P2-4：抑制名单

目标：

- 支持 do-not-contact。
- 防止重复触达无效或拒绝对象。

## 5. P3：自动化增强

### P3-1：销售序列草稿

只生成草稿，不自动发送。

### P3-2：飞书/企业微信提醒

提醒：

- 今日 A 类客户
- 需要补联系方式
- 明天要复查
- 来源质量异常

### P3-3：CRM 导出/集成

优先：

- CSV
- 飞书表格
- Notion
- HubSpot

## 6. 当前立即开工顺序

建议下一轮直接按这个顺序写代码：

```text
1. P0-1 新增数据模型
2. P0-2 双模式评分服务
3. P0-3 公司级合并服务
4. P0-4 回填命令
5. P0-6 B2B 客户库页面
6. P0-5 需求雷达页面
7. P0-8 作战台双模式改造
8. P0-9 导航和 UI 整理
```

原因：

- 先有模型和服务，页面才不会是假页面。
- B2B 客户库是当前最大缺口，应优先落地。
- 需求雷达拆分可以复用现有 Mention 数据。

## 7. P0 完成定义

P0 完成时，系统必须做到：

```text
可以看到需求雷达 Signal 池。
可以看到 B2B Company 客户库。
老数据能回填成 Company。
每条记录有四分制评分。
高优先级对象有原因和下一步动作。
联系方式能记录到 ContactRecord。
作战台能区分两条流水线。
```

如果这些没完成，不继续做新平台扩源。
