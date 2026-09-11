# 本地与云端转写双路径

## 适用边界

本地暗访评分程序与未来小程序线上评分是两条独立链路，不通过口音判断互相切换：

- **本地现行链路**：继续使用当前本地 Whisper 全量转写和高影响窗口复核。默认行为、任务目录、历史缓存和评分规则保持不变。
- **云端线上链路**：所有新线上录音，不论普通话、武汉话或混合口音，主转写统一使用腾讯云录音文件识别 `16k_zh_en_2.0`。不得先运行本地方言分类器，也不得把推测的方言类别写成评分事实。

全局Skill只规定选择、审计与发布门禁，不负责创建云数据库、队列、COS、Worker或腾讯云资源。业务部署必须按已批准的云架构在独立环境完成。

## 环境、任务与结果隔离

本地与云端必须使用不同部署环境、数据库、对象存储、队列和Worker ID，不争抢同一任务。对应配置语义为：

- 本地：`APP_ENV=local`、`TRANSCRIBER_BACKEND=pywhispercpp`、`result_mode=local_codex_test`。
- 云影子：`APP_ENV=cloud`、`TRANSCRIBER_BACKEND=tencent_rec_file`、`result_mode=cloud_shadow`。
- 云正式：`APP_ENV=cloud`、`TRANSCRIBER_BACKEND=tencent_rec_file`、`result_mode=cloud_codex`。

同一业务录音用于对照时必须生成不同环境的job和run，用脱敏`comparison_id`关联；不得复用job ID、run ID或覆盖既有结果。历史job缺少`result_mode`时按本地历史流程解释，不要求补写云审计。

## 云端主转写

云端主转写固定使用腾讯录音文件识别：

- provider：`tencent_rec_file`
- model：`16k_zh_en_2.0`
- language mode：`mixed_zh`

云端适配器应保存非敏感checkpoint，使Worker恢复时先查询既有腾讯任务，不重复提交同一源文件。业务唯一性由环境内job、run和源音频SHA-256共同保证，腾讯TaskId不能单独充当业务唯一键。

审计可记录内部job/run/source标识、源SHA-256、腾讯TaskId、RequestId、提交/完成时间、恢复次数和稳定错误码。不得记录SecretId、SecretKey、签名URL或完整客户转写。签名URL只在运行时短暂使用，不写入数据库、日志、checkpoint或审计。

## 云端高影响证据复核

云端主转写只用于发现候选，不能单独决定高影响评分事实。车型/配置、金额、内饰颜色、试驾邀请及回应、实际试驾、购买时点、NA依据、湿纸巾、星巴克、H项和价格违规窗口，必须由部署在云端Worker环境中的 `large-v3-turbo` 独立进行第二遍复核。

不得调用正在运行的本地Worker替云任务复核。主转写与复核冲突、窗口无语音、复核失败或覆盖不足时，任务进入`review_required`，不得选择性采信更有利的文本。

## 失败、恢复与取消

云端鉴权、配额、格式、对象下载、超时和响应校验错误必须映射稳定错误码，并保存可恢复checkpoint。取消检查至少发生在上传前、提交前、每次轮询后和写入结果前。

云端失败时不得静默切换本地主转写后发布。可以在显式开发诊断中运行本地工具，但诊断结果不得冒充云端主转写，也不得使失败的云run进入published。

## 影子与发布门禁

`cloud_shadow`仅用于候选对照，必须同时满足：

- `delivery_controls.publish=false`
- `delivery_controls.notify=false`
- `delivery_controls.monthly_count=false`

影子run始终保持candidate，不生成或发送正式评分报告，不替换已有run，不进入月报。

`cloud_codex`只有在腾讯主转写成功、云端large-v3-turbo高影响复核完整、所有证据冲突已解决且现有6.0-G确定性校验全部通过后才可发布。每个云端job最多一个当前published run；正式切流前，本地与云端月报不得直接合并。

## 转写审计格式

云端`evidence-audit.json`必须嵌入：

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

本地job不强制包含该云审计。云job缺少审计、模型或provider不符、存在本地主转写fallback、云端复核未完成时，`scripts/validate_score_job.py`必须拒绝最终报告。

## 验证限制

自动化测试只使用fake client或合成审计，不访问腾讯云、不上传真实录音。只有另行授权真实样本后才能做金标准盲测；报告关键实体错误率、证据冲突率和人工复核率，不得外推或宣称总体准确率。
