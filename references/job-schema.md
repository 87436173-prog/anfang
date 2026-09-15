# 报告输入格式

`render_report.py`读取UTF-8 JSON。核心字段：

```json
{
  "rule_version": "6.0-G-HB-2026-09-14-r3",
  "price_policy_version": "HB-2026-09-14",
  "slug": "20260813_sales_customer_car",
  "sales": "销售姓名",
  "customer": "客户称谓",
  "car": "车型",
  "duration": "约30分",
  "audio": "录音文件名（可选）",
  "report_date": "2026-09-14（可选）",
  "models_of_interest": {
    "primary": "元UP 401KM领先型",
    "own_brand": ["元UP 401KM领先型", "第三代元PLUS"],
    "competitors": ["吉利星愿", "广汽埃安UT"],
    "evidence": "03:18询问元UP续航；09:42比较第三代元PLUS；12:05提到星愿和埃安UT"
  },
  "intention": {
    "level": "A",
    "reason": "1个月内购车，目标车型明确并同意下一步到店试驾",
    "evidence": "08:15明确表示月底前购车；18:40约定周末到店"
  },
  "strict_control": {
    "status": "是",
    "series": "元UP",
    "trim": "401KM领先型",
    "filed_price": "94800元",
    "policy_basis": "2026-09-14湖北省活动备案表；元UP严管补充口径"
  },
  "compliance": [
    {
      "type": "风险",
      "timestamp": "16:22",
      "quote": "价格到店还能再谈",
      "ruling": "未给出具体金额，暂不能认定低于备案价；存在突破严管价格的诱导风险",
      "suggestion": "统一表述为按备案价执行，具体权益到店按已备案政策核对"
    }
  ],
  "quote_confirmation": {
    "status": "已确认",
    "interior_color": "棕色",
    "evidence": "16:28客户确认选择棕色内饰"
  },
  "base": 78,
  "na": 20,
  "bonus": 0,
  "modules": [
    ["A欢迎", 10, 10], ["B态度", 25, 18], ["C静态", 20, 12],
    ["D试驾", 25, 20], ["E报价", 5, 3], ["F跟进", 5, 5], ["G环境", 10, 10]
  ],
  "static": "C5得分与证据摘要",
  "deductions": [["D2-D9 15/20", "实际试驾，按音频口径记15分"]],
  "highlights": ["03:20主动邀请试驾"],
  "improvements": ["报价时明确告知订车后的预计交车周期"],
  "defaults": "A1/A2、B1等按音频默认口径处理",
  "rows": [["D", "D1", "试驾邀请", 5, 5, "03:20", "真诚邀请并说明路线"]]
}
```

后续新录音和明确复核任务必须增加`rule_version`。本地现行job可省略`result_mode`，按`local_codex_test`兼容处理，不强制补写云审计。云端job必须显式填写`result_mode`为`cloud_shadow`或`cloud_codex`，并生成独立的`transcription-audit.json`，再嵌入`evidence-audit.json.transcription_route`。审计文件不写入PNG，也不作为默认交付物。

云端`evidence-audit.json`必须包含：

```json
{
  "transcription_route": {
    "schema_version": "byd-transcription-pipeline-v2",
    "main_transcription": {
      "provider": "tencent_rec_file",
      "model": "16k_zh_en_2.0",
      "language_mode": "mixed_zh",
      "status": "success",
      "fallback": "none"
    },
    "high_impact_review": {
      "provider": "cloud_whisper",
      "model": "large-v3-turbo",
      "status": "complete"
    }
  }
}
```

云端不记录或依赖本地方言预分类；普通话、武汉话和混合口音均使用同一`mixed_zh`引擎。任何云主转写失败、本地主转写fallback或云端高影响复核不完整都禁止最终报告。

`cloud_shadow`的`job.json`还必须包含：

```json
{
  "result_mode": "cloud_shadow",
  "delivery_controls": {
    "publish": false,
    "notify": false,
    "monthly_count": false
  }
}
```

`cloud_shadow`只能保存candidate用于对照，不能通过最终报告校验。`cloud_codex`仍须通过所有现有规则和证据门禁。不同环境对照时使用不同job/run，并仅以脱敏`comparison_id`关联；不得覆盖历史run、旧报告或源录音。

r2及r3任务中，E2得3分还必须填写`quote_confirmation`：`status`固定为“已确认”，`interior_color`填写客户明确选择或倾向的内饰颜色，`evidence`填写时间戳。仅确认外观颜色、只列举可选内饰色或无法确认客户选择时，E2记0分；报价被客户明确拒绝时仍按规则记NA，不要求填写本字段。r1历史任务不追溯补填。

脚本根据base、NA、bonus自动计算整数总分和负激励，不接受手工填写总分覆盖公式。`modules`每项格式是`[名称, 适用满分, 实得]`；存在NA时，相应分值从模块满分扣除，因此模块适用满分合计必须等于`100-NA`。`rows`格式是`[模块, 小项, 名称, 满分, 得分或NA, 时间戳, 证据]`，作为内部审计数据保留，不另生成表格。

`models_of_interest`、`intention`、`strict_control`和`compliance`是每条录音的必填字段：

- `models_of_interest.primary`填写客户主关注车型；`own_brand`列出全部明确关注的本品车型（包含主关注车型），`competitors`列出竞品。未提及的列表写`["未提及"]`，无法辨认写`["待核实"]`；`evidence`必须包含时间戳依据。
- 用户最新补充口径：本品其他车型和竞品车型仅列客户本人明确询问、比较或表达兴趣的车型。销售随口带过、单方面推荐、讲解时举例或用于对比但客户未表现关注的车型，一律不列入关注车型清单。
- `intention.level`只允许`H/A/B/C/D/待核实`，`reason`与`evidence`必须填写。
- `strict_control.status`只允许`是/否/待核实`。只要`own_brand`中包含任一严管车系就判“是”并触发专项审查；判“是”时必须写车系。配置、备案价无法确认时分别写“待核实”，不得猜测。
- `compliance`必须存在；无问题时传空数组，报告会显示“未发现明确违规/风险话术”。有问题时，每项必须包含`type`（违规/风险/待核实）、`timestamp`、`quote`、`ruling`和`suggestion`。

只生成PNG，不生成XLSX、CSV或其他表格文件。PNG固定采用统一信息卡样式并按以下顺序输出：关注车型与意向概览、严管状态、合规话术审查、模块得分、静态讲解专项、主要扣分点、服务亮点、核心改进建议、默认项说明。`improvements`和`defaults`允许省略；省略时脚本仍能生成完整报告。

新证据流程只用于后续新录音；历史评分仅在用户明确要求复核时创建新版本，不自动覆盖或重发旧PNG。

r3新任务的job与evidence-audit.json均须包含`price_policy_version: "HB-2026-09-14"`；实际价格和权益逐项匹配完整9月快照。旧r1/r2只用于历史兼容，不为其补造当期政策版本。D1为NA时，D2-D9同为NA，D模块填`["D试驾", 0, 0]`，试驾贡献NA25且基础分不增加；审计保留D1的独立NA依据。
