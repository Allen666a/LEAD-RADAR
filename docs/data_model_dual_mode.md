# 数据模型设计：双模式获客系统

## 1. 设计目标

当前系统已有：

```text
Mention
Prospect
ProspectEvent
Source
Keyword
AgentJob
AgentWorker
```

双模式架构需要新增 Company/Account 层，并补齐 Contact 和 Activity。

目标对象流：

```text
Signal -> Prospect -> Company/Account -> Contact -> Activity
```

## 2. 对象定义

### 2.1 Signal

Signal 是原始信号。

来源包括：

- 社区帖子
- 问答
- 评论
- GitHub issue
- GitHub repo
- 招聘岗位
- 官网关键词
- 目录条目
- 私域导入

当前可以继续复用 `Mention`，但需要在语义上把它视为 Signal。

### 2.2 Prospect

Prospect 是可跟进线索。

它可能是：

- 个人账号
- 工作室
- 团队
- 公司线索
- 从 Signal 转化来的销售候选

当前已有 `Prospect`。

### 2.3 Company/Account

Company/Account 是 B2B 客户库核心对象。

它代表：

- 公司
- 团队品牌
- SaaS 产品
- GitHub 组织
- 跨境服务商
- 数据采集/价格监控/广告验证等业务实体

### 2.4 Contact

Contact 是联系方式或触达入口。

包括：

- 官网 contact 表单
- sales/support 邮箱
- 微信
- Telegram
- LinkedIn
- X/Twitter
- GitHub profile
- 电话
- 其他商务入口

### 2.5 Activity

Activity 是跟进和状态变化记录。

包括：

- 保存联系方式
- 标记可跟进
- 已触达
- 复查
- 有兴趣
- 无效
- 成交
- 进入抑制名单

## 3. 新增表：CompanyProfile

### 3.1 表名

```text
company_profiles
```

### 3.2 字段

```text
id                         Integer PK
company_key                String(260), unique, index
company_name               String(260), index
domain                     String(260), index
website                    Text
country                    String(120), index
region                     String(120)
industry                   String(160), index
company_size               String(80)
customer_type              String(80), index
product_category           String(120), index
business_scenario          Text
fit_score                  Integer, default 0, index
intent_score               Integer, default 0, index
contact_score              Integer, default 0, index
risk_score                 Integer, default 0, index
priority_score             Integer, default 0, index
deal_probability           String(40), default unknown, index
evidence_summary           Text
need_reason                Text
contact_status             String(60), default unknown, index
crm_status                 String(60), default new, index
next_action                Text
owner                      String(120), default ""
source_count               Integer, default 0
signal_count               Integer, default 0
contact_count              Integer, default 0
last_signal_at             DateTime, nullable, index
last_contacted_at          DateTime, nullable
next_follow_up_at          DateTime, nullable, index
first_seen_at              DateTime, nullable
updated_at                 DateTime
created_at                 DateTime
```

### 3.3 company_key 生成规则

优先级：

```text
domain:{normalized_domain}
github:{org_name}
name_country:{normalized_company_name}:{country}
social:{platform}:{handle}
email_domain:{business_email_domain}
manual:{hash}
```

## 4. 新增表：CompanySignal

### 4.1 表名

```text
company_signals
```

### 4.2 字段

```text
id                         Integer PK
company_id                 Integer, index
mention_id                 Integer, nullable, index
source_name                String(160), index
source_kind                String(80), index
signal_type                String(80), index
title                      Text
url                        Text
content_snippet            Text
matched_keywords           Text
fit_delta                  Integer, default 0
intent_delta               Integer, default 0
risk_delta                 Integer, default 0
score                      Integer, default 0, index
reason                     Text
detected_at                DateTime, nullable, index
created_at                 DateTime
```

### 4.3 signal_type

```text
job_posting
website_keyword
github_project
community_pain
directory_listing
social_profile
manual_import
contact_page
competitor
risk
```

## 5. 新增表：ContactRecord

### 5.1 表名

```text
contact_records
```

### 5.2 字段

```text
id                         Integer PK
company_id                 Integer, nullable, index
prospect_id                Integer, nullable, index
contact_type               String(60), index
value                      Text
normalized_value           String(260), index
source_url                 Text
source_type                String(80), index
confidence                 Integer, default 0, index
is_business_contact        Boolean, default true
personal_data_flag         Boolean, default false
status                     String(60), default unverified, index
failure_reason             Text
note                       Text
created_at                 DateTime
updated_at                 DateTime
```

### 5.3 contact_type

```text
email
contact_form
wechat
telegram
linkedin
twitter
github
phone
website
other
```

### 5.4 status

```text
unverified
valid
risky
invalid
suppressed
```

## 6. 新增表：OutreachActivity

### 6.1 表名

```text
outreach_activities
```

### 6.2 字段

```text
id                         Integer PK
company_id                 Integer, nullable, index
prospect_id                Integer, nullable, index
contact_id                 Integer, nullable, index
activity_type              String(80), index
channel                    String(60), default manual, index
status                     String(60), default done, index
message                    Text
result                     String(80), default "", index
note                       Text
next_follow_up_at          DateTime, nullable, index
created_by                 String(120), default ""
created_at                 DateTime
```

### 6.3 activity_type

```text
created
qualified
contact_saved
contacted
follow_up
reply_positive
reply_negative
trial_sent
won
lost
invalid
suppressed
manual_note
```

## 7. 新增表：SuppressionEntry

### 7.1 表名

```text
suppression_entries
```

### 7.2 字段

```text
id                         Integer PK
scope                      String(40), index
value                      String(260), index
reason                     Text
source                     String(120)
created_at                 DateTime
```

### 7.3 scope

```text
email
domain
company
prospect
platform_account
```

## 8. 现有表扩展建议

### 8.1 Mention 扩展

新增字段：

```text
mode                       String(40), default demand_radar, index
fit_score                  Integer, default 0, index
intent_score               Integer, default 0, index
contact_score              Integer, default 0, index
risk_score                 Integer, default 0, index
priority_score             Integer, default 0, index
company_id                 Integer, nullable, index
converted_at               DateTime, nullable
```

### 8.2 Prospect 扩展

新增字段：

```text
company_id                 Integer, nullable, index
mode                       String(40), default demand_radar, index
fit_score                  Integer, default 0, index
intent_score               Integer, default 0, index
contact_score              Integer, default 0, index
risk_score                 Integer, default 0, index
priority_score             Integer, default 0, index
contact_status             String(60), default unknown, index
suppressed                 Boolean, default false, index
suppression_reason         Text
```

### 8.3 Source 扩展

新增字段：

```text
mode                       String(40), default demand_radar, index
permission_status          String(60), default unknown, index
noise_rate                 Integer, default 0
qualified_rate             Integer, default 0
contactable_rate           Integer, default 0
roi_score                  Integer, default 50, index
```

## 9. 关系

```text
CompanyProfile 1 - N CompanySignal
CompanyProfile 1 - N ContactRecord
CompanyProfile 1 - N OutreachActivity
CompanyProfile 1 - N Prospect
Prospect 1 - N Mention
Prospect 1 - N ContactRecord
Prospect 1 - N OutreachActivity
Mention 0/1 - 1 CompanySignal
```

## 10. 迁移顺序

### 阶段一

```text
新增 company_profiles
新增 company_signals
新增 contact_records
新增 outreach_activities
新增 suppression_entries
```

### 阶段二

```text
扩展 mentions
扩展 prospects
扩展 sources
```

### 阶段三

```text
从现有 Prospect 回填 CompanyProfile
从现有 Mention 回填 CompanySignal
从现有 Prospect 联系方式回填 ContactRecord
从现有 ProspectEvent 回填 OutreachActivity
```

## 11. 回填规则

### 11.1 Prospect -> CompanyProfile

满足任一条件就尝试生成 Company：

```text
有 website
有 company_name
platform 是 github/gitee/wearesellers/amazon_seller_cn 等偏公司或团队来源
customer_type 属于数据采集团队/跨境店群/海外社媒矩阵/公司团队
```

### 11.2 Mention -> CompanySignal

满足任一条件就生成 CompanySignal：

```text
mention.prospect_id 对应的 Prospect 已绑定 company_id
canonical_url 可解析出公司域名
source_kind 是 github_search / directory / job / website
signal_type 不是 risk_signal
```

### 11.3 Prospect 联系方式 -> ContactRecord

字段映射：

```text
email -> contact_type=email
wechat -> contact_type=wechat
telegram -> contact_type=telegram
website/profile_url -> contact_type=website
contact_note -> note
```

## 12. 最小实现优先级

P0 最小闭环只需要：

```text
CompanyProfile
CompanySignal
ContactRecord
OutreachActivity
Mention/Prospect 增加 company_id 和四分制字段
```

P0 可以暂不实现：

```text
复杂外键约束
第三方邮箱验证
自动销售序列
CRM 外部集成
```

## 13. 验收标准

- 数据库能表示 Signal、Prospect、Company、Contact、Activity。
- 一个 Company 能关联多个 Prospect 和 Signal。
- 一个 Contact 能追踪来源和置信度。
- B2B 客户库能按 Company 查询。
- 老数据可以回填到 Company 层，不丢失现有 Prospect。
