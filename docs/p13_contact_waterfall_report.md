# P13 联系方式瀑布增强完成报告

完成时间：2026-06-13

## 目标

P13 的目标不是继续堆线索数量，而是把高质量线索推进成可触达客户。

核心原则：

- 只读公开页面、公开主页、公开搜索结果。
- 不登录第三方账号补联系方式。
- 不私信、不关注、不评论、不自动互动。
- 不把官网、公司名、普通主页误判成真实联系方式。
- 每次补全必须留下来源、置信度、失败原因和下一步判断。

## 已完成

### 1. 公开联系方式瀑布结构化

新增 `ContactWaterfallStep`，每个补全步骤记录：

- 步骤名称
- 成功或失败
- 来源
- 原因
- 置信度

补全流程现在会记录：

- 公开页面读取
- 作者主页读取
- 公开搜索读取
- 置信度判断
- 联系方式确认

### 2. 补全结果统计增强

`PublicContactEnrichmentResult` 新增：

- `contacts_created`
- `no_public_url`
- `low_confidence`
- `failure_breakdown`

批量补全完成后，页面提示会直接显示：

- 扫描多少条
- 读取多少页面
- 搜索多少次
- 补到多少客户
- 新增多少联系方式记录
- 多少条无公开入口
- 多少条低置信度
- 读取失败分类

### 3. ContactRecord 可审计记录

补全成功后，会同步写入 `contact_records`：

- 微信
- QQ
- Telegram
- 邮箱
- 手机号
- 网站

每条记录包含：

- `prospect_id`
- `company_id`
- `contact_type`
- `value`
- `normalized_value`
- `source_url`
- `source_type = public_waterfall`
- `confidence`
- `personal_data_flag`
- `note`

重复联系方式不会重复创建；如果新置信度更高，会更新旧记录。

### 4. 失败原因标准化

补全失败会分类：

- `no_public_url`
- `low_confidence`
- `timeout`
- `forbidden`
- `not_found`
- `non_text`
- `invalid_url`
- `ssl_error`
- `fetch_failed`
- `no_new_field`

失败原因会写入 `follow_up_note`，避免后续反复查同一条线索。

### 5. 联系方式工作台增强

`/contact-workbench` 每条线索新增展示：

- 联系方式置信度
- 联系方式记录数
- 最近一次瀑布补全结果

这样可以在列表页直接判断：

- 是否值得今天触达
- 是否只是弱主页信号
- 为什么没补到联系方式

### 6. CSV 导出增强

`/contact-workbench.csv` 新增字段：

- `contact_confidence`
- `contact_records`

导出后不会丢掉 P13 的核心判断信息。

## 修改文件

- `app/services/contact_enrichment.py`
- `app/services/contact_workbench.py`
- `app/templates/contact_workbench.html`
- `app/main.py`
- `docs/README.md`
- `docs/p13_contact_waterfall_report.md`

## 测试结果

已执行：

```text
python -m compileall app
```

通过。

已验证页面/API：

```text
/contact-workbench                                200
/contact-workbench.csv?mode=missing&platform=domestic&min_score=50 200
/prospects                                       200
/                                                200
```

已执行极小批量补全流程测试：

```text
load_contact_workbench_rows(..., limit=1)
enrich_missing_contacts_from_public_pages(..., limit=1, use_search=False)
```

当前库里没有符合“国内待补联系方式”的候选，因此没有实际抓取网页，但流程可正常返回，不报错。

## 当前业务价值

P13 完成后，工具不再只是“发现线索”，而是开始解决获客最关键的一步：

```text
高质量线索 -> 公开证据 -> 可触达入口 -> 置信度 -> 跟进动作
```

这比继续扩数据源更实用，因为没有联系方式的线索只能看，不能成交。

## 剩余风险

- 国内平台个人主页有时需要登录或被平台拦截，工具不会绕过。
- 搜索结果只能作为候选，真实联系方式必须回到公开页面验证。
- 低置信度信息不会自动当成可触达客户。

## 下一步

进入 P14：今日作战台。

重点是把 P11/P12/P13 的结果汇总成每天可执行的清单：

- 今天优先补谁的联系方式
- 今天联系谁
- 谁需要复访
- 谁已经无效
- 哪些平台/关键词今天值得继续跑
