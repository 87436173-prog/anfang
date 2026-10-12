# 报告输入格式

2026-10-10起新评分及本次五单复核，另必填[服务补充合同](service-scoring-policy.md)：service_policy_version、逐行row_assessments、e2_missing_components、三种星巴克服务状态；NA原因见[矩阵](na-decision-matrix.md)。B8coffee改为介绍加分；C5bonus/D8bonus是独立0/2加分行，不计基础满分和NA。

`render_report.py`读取UTF-8 JSON。核心字段：

```json
{
  "rule_version": "6.0-G-HB-2026-09-14-r3",
  "price_policy_version": "HB-2026-09-17",
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

当前r3任务的`evidence-audit.json`还必须包含试驾专项审计：

```json
{
  "trial_review": {
    "full_recording_trial_sweep": true,
    "all_windows_reviewed": true,
    "windows": [
      {
        "candidate_id": "E012",
        "start": "05:00",
        "end": "08:00",
        "reason": "first_15_minutes",
        "status": "confirmed",
        "channel": "mix",
        "model": "large-v3-turbo"
      }
    ],
    "timeline": {
      "events": [
        {
          "event_id": "T001",
          "candidate_id": "E004",
          "event_type": "invite",
          "timestamp": "05:19-05:23",
          "channel": "mix",
          "model": "large-v3-turbo",
          "adopted_reason": "原始音频复核确认独立有效邀约"
        }
      ],
      "actual_drive_chain": false
    }
  }
}
```

`full_recording_trial_sweep`表示完整主转写已经过试驾语义扫描，并完成规定的Turbo固定窗口，不表示整条录音再次全量Turbo转写。两次邀约必须对应不同时间事件；重复切片不能重复计数。实际试驾证据链与D1或D2-D9零分冲突时禁止出图。

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

r2及r3新任务中，E2得3分还必须填写`quote_confirmation`：销售已讲解而客户未确认时，`status`填“已讲解”；客户明确选择或倾向时填“已确认”。`interior_color`填写销售向客户讲解的内饰颜色，`evidence`填写讲解时间戳，并如实记录客户是否确认。只确认外观颜色、未讲内饰颜色时E2不得分；客户未确认内饰选择本身不扣分，仍须核齐其余报价要素。报价被客户明确拒绝时仍按规则记NA，不要求填写本字段。r1历史任务及已发布报告不追溯补填。

脚本根据base、NA、bonus自动计算整数总分和负激励，不接受手工填写总分覆盖公式。`modules`每项格式是`[名称, 适用满分, 实得]`；存在NA时，相应分值从模块满分扣除，因此模块适用满分合计必须等于`100-NA`。`rows`格式是`[模块, 小项, 名称, 满分, 得分或NA, 时间戳, 证据]`，作为内部审计数据保留，不另生成表格。

`models_of_interest`、`intention`、`strict_control`和`compliance`是每条录音的必填字段：

- `models_of_interest.primary`填写客户主关注车型；`own_brand`列出全部明确关注的本品车型（包含主关注车型），`competitors`列出竞品。未提及的列表写`["未提及"]`，无法辨认写`["待核实"]`；`evidence`必须包含时间戳依据。
- 用户最新补充口径：本品其他车型和竞品车型仅列客户本人明确询问、比较或表达兴趣的车型。销售随口带过、单方面推荐、讲解时举例或用于对比但客户未表现关注的车型，一律不列入关注车型清单。
- `intention.level`只允许`H/A/B/C/D/待核实`，`reason`与`evidence`必须填写。
- `strict_control.status`只允许`是/否/待核实`。只要`own_brand`中包含任一严管车系就判“是”并触发专项审查；判“是”时必须写车系。配置、备案价无法确认时分别写“待核实”，不得猜测。
- `compliance`必须存在；无问题时传空数组，报告会显示“未发现明确违规/风险话术”。有问题时，每项必须包含`type`（违规/风险/待核实）、`timestamp`、`quote`、`ruling`和`suggestion`。

只生成PNG，不生成XLSX、CSV或其他表格文件。PNG固定采用统一信息卡样式并按以下顺序输出：关注车型与意向概览、严管状态、合规话术审查、模块得分、静态讲解专项、主要扣分点、服务亮点、核心改进建议、默认项说明。`improvements`和`defaults`允许省略；省略时脚本仍能生成完整报告。

新证据流程只用于后续新录音；历史评分仅在用户明确要求复核时创建新版本，不自动覆盖或重发旧PNG。

r3新任务的job与evidence-audit.json均须包含`price_policy_version: "HB-2026-09-17"`；实际价格和权益逐项匹配9月17日更新及完整9月基线。旧r1/r2只用于历史兼容，不为其补造当期政策版本。D1为NA时，D2-D9同为NA，D模块填`["D试驾", 0, 0]`，试驾贡献NA25且基础分不增加；审计保留D1的独立NA依据。

已完成试驾的新评分和经明确复核的历史修订，job/audit同填`trial_safety_policy_version: "trial-itemwise-2026-10-12-v1"`。确认安全事件仍在审计记录原音复核时间窗、声道、模型及事实界限；`D_safety_veto`不得为true，不能用安全事件将D1—D9全置0。独立试驾源的`D_score`等于九个基础D行实得之和，合并接待用`trial_score_reuse`记录来源哈希与逐项采用结果。旧整D0源须重新逐项裁决并以新版本报告发布，保留旧PNG；H整单否决另行审查。

## 星巴克介绍报告合同（2026-10-05起）
2026-10-05及以后每条结果必填 `report_date` 和下列独立报告字段；历史日期不自动补算。计算规则版本保持r3，此变更只增加展示和证据字段。
```json
"starbucks_introduction": {
  "status": "已介绍",
  "evidence": "23:15-23:21，销售向客户说明送上的是本店星巴克咖啡。"
}
```
`status`只允许已介绍/未介绍/待核实。未介绍必须在PNG显著红色显示“警告：未介绍（录音未核验到明确介绍）”，`evidence`记录全录音复核范围及相关窗口；待核实使用橙色，不能伪称没有。缺字段时校验和渲染均报错，不默认判否。独立卡片放在得分卡之后。
审计同名对象必须包含 `status`、`full_transcript_scanned: true`、`reviewed_at`、`rationale`、`introduced_to_customer`（true/false/null）及非空 `reviews`（每项含 `window`、`channel`、`model`、`conclusion`）。已介绍还须存在已确认的 `starbucks_introduction` 候选及 `introduced_to_customer: true`。未介绍不得与阳性候选冲突。
旧版仅管理提示的合同保留历史兼容；采用service-policy-2026-10-10-v1时，介绍行为按B8coffee给0/3，不再使用实际饮用门槛，三种行为分别记录。已发布报告只有明确范围内的新版本才补加，不覆盖原PNG。


## 固定流程输入与裁决记录

自2026-10-05起，本地通用CLI从rows重算模块、base、NA、bonus和整数总分；每个模块必须包含完整标准小项，NA必须显式记录，不能因遗漏一行而自动产生NA。A3、B8及恢复的C5bonus/D8bonus加分行独立于基础分。每单只写结构化JSON数据，不临时生成携带客户结论的Python脚本。

新裁决可同时使用 `review_status: complete` 与 `fact_status: confirmed/rejected/unresolved`。rejected候选保留original_category、原始比较、原因，并归为reviewed_context；其legacy status=confirmed仅为旧校验接口的复核完成标志，不表示原行为成立。未完成必要复核或缺少待核闭环的unresolved继续阻止最终发布；按workflow-optimization完成两轮收口且记录review_closed、closure_reason、qualifies_for_scoring=false、affected_rows及job.pending_evidence的候选，可保持unresolved按合同发布，受影响得分/加分为0，不得据此NA、触发H或价格处罚。任何候选都必须有逐项decision，不允许统一写confirmed。固定CLI validation.json保存input_fingerprint和validated_at，相同内容只校验一次，变化则失效。

## 试驾语义裁决合同
后续本地D语义判断须在job与audit保存完全相同的trial_assessment对象，schema_version=semantic-trial-v1、policy_version=trial-semantic-2026-10-06-v1，字段与计分/报告约束见[trial-semantic-policy.md](trial-semantic-policy.md)。复核完成与fact_status=inferred分别记录；不得把推断候选赋为事实confirmed、不能改成test_drive_actual，也不能设置直接证实的actual_drive_chain=true。已发布10月5日三份显式用户授权的旧字段只读兼容，不修改其历史job和PNG。
含混的星巴克介绍标橙、不得获得星巴克加分；按服务补充完成待核闭环后可发布，不能据此认定实际饮用。

## 价格考核范围记录（2026年10月9日起）

后续评分的job与审计均记录 `price_scope_policy_version: "price-scope-2026-10-09-v4"`，在审计price_adjudication中区分范围内金额核对与排除事项，不把排除解释成事实已确认合规。price_policy_version仍为实际采用的自律会表版本。

`compliance`只列自律会标准范围内价格、赠品及金融政策问题；专业知识、全部补贴/置换政策及标准未规定的税险政策/金额不得列入违规、风险或待核实。明细C6/E2/E3/H、improvements及其他分项不得以排除事项的真实性或办理细节作为扣分/建议依据；范围外候选仅记reviewed_context，不建立未决计分事实，也不写成已核实合规。其他服务行为继续按原规则取证和评分，E2报价组成与E3可考核咨询场景按scoring-rules.md执行。

每张后续PNG的defaults注明：“合规仅按自律会标准检查价格、赠品及金融政策；专业知识、补贴及置换政策不核查，标准未规定的税险政策/金额不考核。”用户另行指定历史复核时才更新历史数据和新版本PNG。

## 反馈流程合同（2026年10月9日起）

新本地job/audit同填workflow_policy_version=workflow-feedback-2026-10-09-v1、price_scope_policy_version=price-scope-2026-10-09-v4。报告默认说明包含合规仅价格/赠品/金融及专业/补贴/置换/表外税险排除。compliance每项domain为price/gift/finance且standard_ref引用自律会表条款；不列范围外事项。允许competitors=[]，展示为未核到客户实际关注竞品。完整rows留存，PNG扣分明细由实得<满分且非NA的rows派生。

全量语义筛选semantic_scan、闭环pending_evidence、context_groups、六要素显式quote_components及component_sources、trial_score_reuse、试驾matching/卫生投诉/新D5时长字段均按workflow-optimization.md。闭环待核保留unresolved，不得将其status统一confirmed；E2=3六项均有已复核候选原音来源。旧合同历史只读兼容，不自动重算或改写旧PNG。
