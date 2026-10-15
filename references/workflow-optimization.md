# 日常评分固定入口与反馈调整

2026-10-10服务规则补充`service-policy-2026-10-10-v1`与本流程同时采用，见[service-scoring-policy.md](service-scoring-policy.md)及[na-decision-matrix.md](na-decision-matrix.md)。用户已明确授权B8介绍/湿纸巾、C/E/F NA及C5/D8原表超额加分修正，不等待试验期结束。

用户2026-10-09明确授权针对问题清单P001—P016立即调整评分流程，覆盖此前“新增建议等10月15日统一实施”的安排。本地流程版本为workflow-feedback-2026-10-09-v1；价格核查范围为price-scope-2026-10-09-v4。本次实施已授权，不重复请求确认。仅本地流程调整，未来云端腾讯主转写/云端复核合同仍独立执行。

## 正式链与交付顺序

固定入口scripts/scoring_pipeline.py；固定runtime为C:/Users/no02/Documents/Codex/byd-scoring-runtime；Python为C:/Users/no02/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe。首次preflight和规则完整阅读后按资产/内容签名复用；变动重新核验。每次接待独立目录、原音哈希、转写、审计、job及报告，不跨客户复用。

正式全量主转写继续small、Silero VAD、分段退化检测与断点续跑，一条音源成功全转写一次。取消每日自动Turbo全量shadow；只有用户明确指定质量对照样本时才用--shadow，且仍遵循试验身份和限额。GPT-6 sol/high是定时任务的主推理模型，不替换Whisper音频模型。

先完整审读主转写并扫描后段、B3、两轮邀约、成交日期、茶点、加分、NA、H及范围内报价。不能把quality=ok当语义完整，不能把候选器没提取当行为没发生。用全量上下文筛选可能改变得分、意向、重要合规结论及必须管理提示的事件，再定向原音复核；等待背景、其他接待、无关技术讨论及全部补贴/置换不扩大窗口。不得省略实际给分/H/NA及范围内金额的独立原音证据。

报告通过计分/证据/展示合同后先交付PNG，再做轻量close摘要；详细审计留每单目录。试验统计、配对报告及期后评估不阻挡报告。未知耗时/误扣/漏判保持null，无反馈、出图成功、单元测试通过都不代表录音质量通过。

## 命令与候选筛选

powershell使用上述固定Python和入口。按preflight → rules → 完整阅读并rules --ack-full-read → init --audio <用户提供原音> --job-dir <接待目录> --date YYYY-MM-DD → transcribe → plan-review执行。init保存workflow-policy.json，后续job/audit必须记录相同workflow_policy_version与price_scope_policy_version。

plan-review先产生candidate-plan.json供全量语义审读定位。写review-selection.json后，执行plan-review --decisions review-selection.json，重新生成定向窗口。筛选合同如下：

- full_transcript_read=true仅在真实完整阅读后填写；transcript_sha256必须是本接待initial.jsonl的内容哈希；rationale说明扫描与选择原则。
- candidates必须覆盖全部候选且每id一次；action为review/context，各自有rationale。真正用于计分或范围内合规的事实用review，无关背景及不采信的触发词用context。context保留original_category、原文和排除理由，fact_status=rejected、qualifies_for_scoring=false；不得解释成行为已确认存在。
- 不按关键词自动把所有试驾线索确认为已发生或统一驳回；独立主模型结合前后语义、说话人、当前客户、相反证据逐事件判断。独立邀约轮次须分开；发现漏候选时补入结构化候选后复用已核验窗口或定向补窗，不写客户结论程序。
- B3前三分钟原始各声道和混音仍必须复核，单声道只mix。执行review-selection后，plan-review生成review/selected-windows.json，合并已选普通事件与强制B3窗口；review和raw-audit默认读取该清单及其对应results_selected-windows_turbo.json。历史无筛选任务仍兼容review/windows.json和review/b3-windows.json。--windows是--manifest兼容别名，非法时间、声道、缺字段在解码前拒绝。
- 没有review-selection时保留旧固定试驾扫窗作为兜底；有完整语义筛选合同时，旧前15分钟/最后25%/报价前后90秒扫窗按逐事件相关性选择，不能把未执行的ASR窗写成“已原音复核”。semantic_scan记录全文审读与定向处理完成；老流程合同只读兼容。
- raw-audit还会从已完成的复核结果查找自动候选缺失的车型配置、NA依据、湿纸巾、星巴克和范围内价格语义，形成`SUP_...`待裁决候选，不能自动确认为得分事实。若原音已确认但转写未触发词（例如“湿纸巾”转写成“十纸巾”），可用`raw-audit --supplemental-candidates <JSON>`加入固定补充清单。每条须有`id/category/source_sha256/window_label/start/end/channel/decision_source`，窗口必须在已选复核清单中且同源同声道同时间；仅建立候选。人工补充候选在adjudicate确认为事实时，还须提供与已选窗口对应的`review_sources`（window/channel/model/conclusion/source_ref），记录独立原音结论。禁止手改candidate-plan.json或凭总结补分。
- adjudicate对已有job/audit镜像已记录的服务规则版本、逐行裁决、星巴克三态和试驾安全口径，并记录缺项；publish在生成PNG前拒绝未补全或相互矛盾的字段。E2的六要素布尔值、来源与缺项从同一审计派生，未确认来源只记线索，不得写入确认来源。

## 合并、缓存和两轮停止条件

同一接待重叠窗按事件合并，成功结果可支持多个小项。缓存键含源SHA256、原始声道、数值规范化的起止秒、模型文件/参数、转写脚本和技术/语义质量脚本签名；10与10.0等数值同一窗口必须命中。标签不是音频身份，命中时保留当前请求标签。不同音源、声道、模型、参数及质量代码不能混用。依次推理，避免同机多组8线程争抢CPU。

第一轮Turbo原音复核；仍存在高影响冲突时，第二轮仅围绕原疑点选10—20秒短窗、原始分声道或Large。manifest使用稳定event_id和review_round=1/2，每事件每声道最多两种新窗请求，跨模型累计；完全相同的成功/失败结果均保留，不再次解码。超过两轮不再改事件名、连续扩窗或恢复整片低辨等待区。

技术退化结果保留。大于60秒失败窗可拆60秒窗一次；已经不超过60秒的窗不拆成同一个窗重复执行。字幕套话、媒体片尾、预期语音但为空需语义复核；稀疏或静音只标上下文注意，不武断认定漏判或强制恢复全部静音区。语义flags及未决窗口存审计，不充作漏判真值。

两轮仍不清：保留fact_status=unresolved与复核来源，填写review_closed=true、closure_reason、qualifies_for_scoring=false、affected_rows；job.pending_evidence对应candidate_id/affected_rows/award=0。受影响服务/加分行只能0分，理由明确“证据未确认”，不得伪称行为未发生、自动NA、补满分或触发处罚。只有范围内合规待核但不影响分数可使用role=compliance_only且affected_rows=[]，并在合规条目关联candidate_id、type=待核实、domain和standard_ref；H未证实可role=h_pending且H.triggered=false，不触发否决。未做审读/复核或缺乏该闭环的未决项仍阻止发布。重要字段或试驾结论无法形成可用的规则判断时不得伪造最终分。

## 裁决、报价与匹配试驾

raw-audit保留每窗结果和技术质量。adjudicate --decisions decisions.json重新生成derived字段；每个采信事实独立填写disposition/conclusion/rationale、采用声道/模型及原音来源。无关context可用{items:[...],context_groups:[{ids:[...],disposition:rejected,conclusion:...,rationale:...}]}合并相同理由；批量confirmed不允许作为简化手段。

明确原音已确认交期等报价要素时，在对应confirmed候选决策中用quote_components显式记录六项布尔值并保留review_transcript/review_sources。派生component_sources记录每项候选id，E2=3六项须全部有原音来源。旧自动字段不能覆盖明确裁决，也不从主转写或客户自己提车计划补交期。

用户2026-10-09明确后续默认分支：批量上传试驾录音时，先建立本批文件及哈希清单、逐条完成独立试驾评分，再按销售、客户、车型和交接原音证据匹配对应接待，执行merge-trial合并D项与接待其他项，每次接待交付一张合并评分PNG；无需再逐单请求是否合并。批量中的未匹配录音保留匹配状态及原因，不串客户、不强行合并。没有上传试驾录音，或该接待没有可靠对应试驾时，按此前现行r3及trial-semantic-2026-10-06-v1分支评分，不要求补交试驾录音、不自行寻找其他日期或客户的录音。仅试驾录音而无对应接待时先保留独立试驾结果，收到接待录音后再匹配合并。既有匹配试驾D分项、D4默认及D5生效范围继续适用。

有对应独立试驾时先匹配销售、客户、车型与交接上下文，保存matching.json中的status=confirmed、receipt_sha256、trial_sha256和时间戳evidence。不能只靠文件名/时间匹配。执行merge-trial --job-dir <接待> --trial-job-dir <独立试驾> --decisions matching.json，沿用已完成独立试驾D1—D9逐项结果及NA；不套默认15分、不从接待重评邀约。D1按匹配口径5。源完整评分及源job内容签名、两音源哈希、D行需一致，源被改后重核来源。

D2/D3权重0；D4=2、D5=2、D6=2、D7=3、D8=9（0/3/6/9）、D9=2，D1=5；D总25。依`trial-itemwise-2026-10-12-v1`，已完成试驾的安全事件在源试驾审计独立裁决并保留管理提示，不使整D0；D1—D9按实际行为逐项评分。H整单否决仍独立判断。有匹配试驾D4默认2；客户本人明确投诉当次试驾车卫生则0，matching.hygiene_complaint记录confirmed/customer_quote/timestamp/speaker/trial_vehicle。默认不是物理卫生已直接证实。

D5时长口径仅此前D5指令之后新收到录音，matching.d5_duration_policy_applies=true时记录trial_duration.boarded_at_seconds/disembarked_at_seconds/mode/evidence；普通900秒、辅助1200秒得2。客户明确缩短用customer_shortening_request.quote/timestamp记录例外。不能用文件总长/暂停间隔代替上下车区间，不回改10月8日已评分样本。无对应试驾继续原r3及trial-semantic-2026-10-06-v1，D1 NA级联仅该分支按原规则执行。

## 合规、发布与索引

仅核自律会标准规定的价格、赠品和金融政策，全部专业知识、补贴、置换及标准未规定税险排除。范围外不核金额/资格/申请，不列风险/待核实，不转到C6/E2/E3/H扣分。compliance每项须domain=price/gift/finance、standard_ref引用实际表内条款，mixed话语只判范围内内容；排除项不得标已核实合规。实际车型配置匹配报价、保险赠送/精品/保养/折抵限制继续执行。C6等仍按服务表现，不自动满分。

publish先检查报告字段，再从完整rows复算模块/base/NA/bonus，校验一次内容指纹，成功后出深蓝PNG；同指纹复用，不同内容旧PNG保留，需新revision slug。允许competitors=[]，报告显示未核到客户实际关注竞品。页眉按长身份/车型换行增高；PNG逐项仅列非默认的实际扣分行（实得低于满分）；按row_assessments确认的默认扣分改在03进度条黄色段表示，NA、满分行及加分行不逐项占位，完整rows/audit保留计算。默认说明、理由、图及索引同步，不能留旧D0/D4待核/E2交期缺失理由。

close只写case-summary及experiment-pending队列；源签名、规则版本、报告/审计索引、未决项和事实/推断区别留存。修改旧索引只能清理已被修订结论的过时文字，保留历史，不重算旧分数或覆盖旧图。

## 试验与验证边界

原十天观测期10月5日至14日和10月15日09:00汇总时间保留。本次立即实施是用户授权，不是B1—B8已通过。旧数据按旧口径留存；新流程记录版本，分口径计算质量配对和耗时，不混合推算平均节省。summarize于报告交付后收集已知案例的轻量待统计数据；未核验用户反馈仍阻止相关项目通过，每项每口径至少10个独立质量对照才够样本，无反馈不算通过。模型推断不作驾驶/识别金标准。需要新录音才能验证端到端提速和新模型评分质量，代码回归只证明软件边界。
