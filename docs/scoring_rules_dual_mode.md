# 评分规则：双模式获客系统

## 1. 评分目标

Lead Radar 评分不是为了“看起来高级”，而是为了决定销售每天先处理谁。

评分必须回答：

```text
这个对象是不是目标客户？
它现在有没有需求？
能不能联系上？
有没有风险或噪音？
今天是否值得跟进？
```

因此评分拆成四个基础分：

```text
fit_score
intent_score
contact_score
risk_score
```

最终合成：

```text
priority_score
```

## 2. 四个基础分

### 2.1 fit_score

fit_score 表示客户类型是否适合动态住宅 IP 业务。

高分对象：

- 数据采集团队
- 价格监控公司
- 广告验证公司
- SERP / SEO 工具
- 电商情报公司
- 舆情监控公司
- 金融数据公司
- AI 数据集公司
- TikTok / Shopee / Amazon 多账号服务商
- 账号注册 / 养号服务商
- 海外社媒矩阵团队

低分对象：

- 普通个人卖家
- 纯教程作者
- 普通开发者问题
- 免费代理使用者
- 静态住宅 IP 需求者
- 同行代理服务商

### 2.2 intent_score

intent_score 表示最近是否出现明确需求或行为信号。

高分信号：

- 明确说需要动态住宅 IP
- 多账号防关联痛点
- 账号被封、关联、验证受阻
- 爬虫 403 / 429 / Cloudflare
- 招聘爬虫工程师
- 官网出现 scraping / crawler / proxy / anti-bot
- GitHub 有 scraper / crawler / spider / proxy pool 项目
- 产品是 price monitoring / SERP API / ad verification

低分信号：

- 泛泛提到跨境
- 泛泛提到代理
- 普通教程
- 新闻资讯
- 行业科普

### 2.3 contact_score

contact_score 表示是否可触达，以及联系方式是否可靠。

高分联系方式：

- 官网 sales/contact 表单
- 公司邮箱
- support/sales/business 邮箱
- 企业微信/微信商务号
- Telegram 商务入口
- LinkedIn 公司页或负责人
- GitHub 组织主页和维护者

低分联系方式：

- 无联系方式
- 只有平台昵称
- 只有不完整链接
- 疑似代理 URL 中的用户名密码
- 个人敏感联系方式且无商务语境

### 2.4 risk_score

risk_score 表示噪音、合规、同行、骚扰或错误触达风险。

高风险：

- 同行代理服务商
- 新闻资讯
- 新手教程
- 免费代理
- 翻墙/机场
- 赌博、诈骗、灰产
- 明确不希望被联系
- 平台限制明显
- 个人敏感数据

注意：

```text
risk_score 越高，优先级越低。
```

## 3. 合成分 priority_score

建议初始公式：

```text
priority_score =
  fit_score * 0.35
  + intent_score * 0.35
  + contact_score * 0.20
  - risk_score * 0.30
```

归一化到 0-100：

```text
priority_score < 0 -> 0
priority_score > 100 -> 100
```

后续可根据成交反馈调整权重。

## 4. 等级

```text
A：priority_score >= 80
B：60 <= priority_score < 80
C：40 <= priority_score < 60
Risk：risk_score >= 60
Noise：priority_score < 40 或明确噪音
```

处理规则：

| 等级 | 动作 |
| --- | --- |
| A | 今日优先处理 |
| B | 补证据或补联系方式 |
| C | 观察，不主动触达 |
| Risk | 合规审核 |
| Noise | 剔除或降权 |

## 5. 需求雷达评分

需求雷达偏“大海捞针”，重点是痛点强度。

### 5.1 fit_score 规则

加分：

```text
TikTok 多账号/矩阵 +25
亚马逊/Shopee/Lazada/Shein 店群 +25
爬虫/数据采集团队 +30
指纹浏览器使用者 +20
海外社媒矩阵 +20
账号注册/养号服务 +25
价格监控/电商情报 +30
```

扣分：

```text
普通个人教程 -20
泛泛跨境运营 -10
静态住宅 IP -25
免费代理/机场 -30
同行代理 -50
```

### 5.2 intent_score 规则

加分：

```text
明确求动态住宅 IP +35
防关联/关联封号 +30
IP 被封/不稳定 +25
403/429/Cloudflare +25
代理池/轮换 IP +25
多国家/多地区需求 +20
批量注册/养号 +20
```

扣分：

```text
仅教程关键词 -25
仅新闻资讯 -40
无明确需求 -15
```

### 5.3 contact_score 规则

```text
有主页 +10
有邮箱/微信/TG +30
有官网 +25
有公司名 +15
仅平台昵称 +5
无可触达入口 +0
```

### 5.4 risk_score 规则

```text
同行代理 +80
新闻资讯 +70
教程/课程 +50
免费代理/机场 +70
疑似灰产 +90
平台受限严重 +30
个人敏感信息 +60
```

## 6. B2B 客户库评分

B2B 偏企业客户，重点是长期消耗能力。

### 6.1 fit_score 规则

加分：

```text
数据采集/数据服务公司 +35
价格监控公司 +35
广告验证公司 +35
SERP/SEO 工具 +30
电商情报工具 +30
舆情监控公司 +25
金融数据公司 +25
AI 数据集公司 +25
跨境多账号服务商 +25
海外社媒自动化工具 +25
```

扣分：

```text
普通电商卖家 -10
单店铺卖家 -20
代理 IP 同行 -60
无法判断业务 -10
```

### 6.2 intent_score 规则

加分：

```text
招聘爬虫工程师 +30
招聘数据采集工程师 +30
招聘反爬/风控相关岗位 +20
官网出现 scraping/crawler/proxy +25
官网出现 anti-bot/data extraction +20
GitHub 有 scraper/crawler/spider +25
GitHub 有 proxy pool +20
产品描述包含 price monitoring/SERP/ad verification +30
多国家/多地区业务 +15
最近新增多个相关信号 +15
```

扣分：

```text
信号超过 180 天未更新 -10
只有泛泛关键词 -10
只有目录条目无证据 -10
```

### 6.3 contact_score 规则

加分：

```text
官网 contact 表单 +20
sales/support/business 邮箱 +30
公司 LinkedIn +15
GitHub 组织 +10
Telegram/Discord 商务入口 +15
联系人角色明确 +20
邮箱验证有效 +20
```

扣分：

```text
无联系方式 -20
只有个人账号 -10
联系方式来源不明 -15
疑似无效邮箱 -30
```

### 6.4 risk_score 规则

```text
代理 IP 同行 +80
博彩/诈骗/灰产 +90
个人敏感信息 +70
来源不可追溯 +40
明确 do-not-contact +100
疑似垃圾站 +50
```

## 7. 客户类型标签

标准 customer_type：

```text
data_collection_team
price_monitoring
ad_verification
serp_seo_tool
ecommerce_intelligence
public_opinion_monitoring
financial_data
ai_dataset
cross_border_matrix
social_media_matrix
account_farming
developer_team
unknown
competitor
noise
```

中文显示：

```text
数据采集团队
价格监控
广告验证
SERP/SEO 工具
电商情报
舆情监控
金融数据
AI 数据集
跨境矩阵
社媒矩阵
账号注册/养号
开发团队
未知
同行
噪音
```

## 8. 痛点类型标签

```text
multi_account_association
account_ban
ip_blocked
crawler_403
cloudflare_challenge
proxy_pool_unstable
fingerprint_browser
registration_verification
geo_targeting
price_monitoring
serp_scraping
ad_verification
```

## 9. 推荐动作

按分数组合生成动作：

```text
fit 高 + intent 高 + contact 高 + risk 低 -> 今日跟进
fit 高 + intent 高 + contact 低 + risk 低 -> 优先补联系方式
fit 高 + intent 中 + contact 高 -> 轻触达/观察
fit 中 + intent 高 -> 人工复核
risk 高 -> 合规审核
priority 低 -> 剔除或观察
```

## 10. 解释字段

每次评分必须生成：

```text
fit_reason
intent_reason
contact_reason
risk_reason
priority_reason
recommended_action
```

页面不能只显示分数，必须显示原因。

## 11. 反馈学习

销售动作会影响后续评分：

```text
标记成交 -> 同来源、同类型加权
标记有兴趣 -> 同类型轻微加权
标记无效 -> 同关键词、同来源降权
标记同行 -> 同域名/同来源强降权
标记暂无联系 -> contact_score 降权
```

## 12. 验收标准

- 需求雷达和 B2B 使用不同评分入口。
- 每条记录都有四个基础分。
- 高优先级必须有解释原因。
- 风险高的对象不能进入自动触达。
- 销售反馈会影响来源和关键词权重。
