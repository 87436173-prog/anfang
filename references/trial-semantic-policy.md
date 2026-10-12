# 本地试驾语义与默认口径

政策版本：`trial-semantic-2026-10-06-v1`。用户已授权“根据语义推测试驾，不需要人工听辨”，并明确“有签协议或路线选择默认为有试驾”，要求同步全局技能。自同步起用于后续本地日常评分，无需每条重复申请；计算规则仍为`6.0-G-HB-2026-09-14-r3`。

## 如何判断

1. 独立扫描本接待完整转写和试驾专项时间线，复用已完成的原始窗口Turbo/Large复核。B3分声道、其他高影响复核、质量检测不减少。人工听辨不再是D必经步骤。
2. **确认签署本次试驾协议，或确认完成本次试驾路线选择，任一项成立，默认有试驾/试乘。** 两者是OR，不要求同时发生；不再额外要求出现动态驾驶或返回反馈才采用默认。不区分客户握方向盘还是作为乘客，证据只支持试乘时写试乘。
3. “签一下协议/等会去签”只证明邀请签署；“这里有两条路线/可以选路线”只证明介绍。需要已签署/签完的语义，或路线已选定的语义。购车、金融协议，导航回家或销售介绍地理位置不属于本次试驾协议/路线。
4. 无上述默认触发时，可按已复核的接待上下文判断；综合有序邀约、同意、手续、出发/动态/体验后反馈，不因单一“感觉怎么样”、坐进静态展车或录音空白直接认定完成。原音窗口已有清晰实际完成证据时直接采用其证据方式。
5. 记录取消、拒绝、延后、另一客户/车辆等相反证据。默认不代表不看反证；若明确证据表明该次试驾取消或未开展，应采用明确证据并解释为什么没有套默认。确有无法解决的矛盾，继续局部ASR复核，不能改成已确认。也不能为了输出明确结果制造事实。

## 固定计分

- 采用有试驾/试乘的默认或语义结论，D1不是NA时D2-D9固定15/20，D1独立按有效邀约评5/0。只有已签协议/选路线但销售邀约未证明时，不自动补造邀约。
- r3原有D1=0与实际开展矛盾时仍回溯邀约或客户主动要求证据；不得仅凭默认把D1改5。D1=NA仍优先联动整个D为NA25，需独立的NA依据。
- 未开展时仍按两次邀约、明确下次时间等既定NA规则评定。语义默认不能自动产生NA，不能给D2-D9额外20分。
- 不把此授权扩大到B3、C5、茶点、B8加分、购车时间、价格/H结论。星巴克按service-policy-2026-10-10-v1以简单介绍给B8加分，介绍/提供/饮用分开；品牌含混标橙不加分，按待核闭环处理。

## job/audit合同

候选器新增test_drive_default_basis类别，签署/路线表达只生成待主模型语义裁决的原窗候选，不凭关键词自动确认。

两份JSON保存完全相同的`trial_assessment`。新候选原始行为的事实状态仍按独立复核表达，不创建伪阳性的`test_drive_actual`；推断结论保存`fact_status: inferred`和`direct_audio_completion_verified: false`。

```json
{
  "trial_assessment": {
    "schema_version": "semantic-trial-v1",
    "policy_version": "trial-semantic-2026-10-06-v1",
    "mode": "semantic_inference",
    "fact_status": "inferred",
    "direct_audio_completion_verified": false,
    "conclusion": "occurred",
    "default_trigger": "signed_trial_agreement",
    "confidence": "medium",
    "reviewed_at": "YYYY-MM-DDTHH:MM:SS+08:00",
    "supporting_evidence": [
      {
        "candidate_id": "E012",
        "window": "09:53-10:25",
        "channel": "mix",
        "model": "large-v3-turbo",
        "stage": "agreement_signed",
        "summary": "本次试驾协议已签完；不是邀请以后签"
      }
    ],
    "counter_evidence": [],
    "alternative_explanations": ["已签协议本身不直接证明实际动态驾驶，按用户默认口径采用"],
    "rationale": "原窗确认本次试驾协议签署，依用户OR默认口径判有试驾/试乘"
  }
}
```

- `conclusion`允许`occurred/not_occurred/uncertain`；`confidence`为`high/medium/low`，非统计概率；`default_trigger`允许`signed_trial_agreement/trial_route_selected/context_chain`。
- 协议默认须有`agreement_signed`阶段；路线默认须有`route_selected`阶段。任一项可由单个明确的已复核事件支持，不能强制额外动态/返回窗口。支持事件按时间排序并带原音候选ID、时间窗、声道、模型和摘要。
- `context_chain`判有试驾需至少两个不同时间、不同阶段的复核事件，其中至少一个为出发、动态、返回或体验后反馈；独立主模型判断其是否属于同一次接待。未开展也须记录支持该结论的已复核事件。
- `counter_evidence`和`alternative_explanations`必填，后者非空。无需强行凑相反证据，无反证时可写空数组。
- 语义时间线`actual_drive_chain`和`verified_actual_drive_chain`不设true。`actual_drive_chain_basis`可写`user_authorized_semantic_inference`。分数采用与直接完成验证是不同字段；不能因裁决完成把推断状态改为事实confirmed。
- `uncertain`不能支撑最终正向得分或处罚；继续局部复核。原始冲突和用户线索留痕。
- D明细行、对应扣分原因、默认说明、PNG都注明默认/语义方式及实际D1、D2-D9、NA。渲染器自动加入“D试驾口径｜语义推断”卡片与默认说明，列出依据、推断把握和其他解释。
- 已发布10月5日三份显式授权的旧字段只读兼容，不修改历史job或PNG，也不把旧的推断链当成直接确认。

## 十天试验

日常评分可以采用以上默认，不表示已独立验证推断准确性。close保存推断来源；B1—B8不得用默认/语义结果作为准确性真值。仅另有真实原音独立对照、记录`independent_original_audio_comparison: true`及`audit_ref`时，才可计入对应项目独立验证数。无反馈不等于通过；到期自动汇总与原定测试日期不变。

