from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evidence = load_module("byd_evidence_candidates", "evidence_candidates.py")
validator = load_module("byd_validate_score_job", "validate_score_job.py")


def row(t0: int, t1: int, text: str) -> dict:
    return {"t0": t0, "t1": t1, "text": text}


class EvidenceCandidateRegressionTests(unittest.TestCase):
    def test_trial_fuzzy_phrases_create_high_recall_candidates(self):
        records = [
            row(31900, 32300, "要不要车架一下，您也可以亲自开一圈感受"),
            row(48900, 49300, "我再问一下，等会您来开一下吧"),
        ]
        candidates = evidence.build_candidates(records)
        invites = [item for item in candidates if item["category"] == "test_drive_invite"]
        self.assertGreaterEqual(len(invites), 2)

    def test_trial_sweep_covers_first_15_minutes_and_last_quarter(self):
        records = [row(0, 100, "开始接待"), row(239900, 240000, "接待结束")]
        candidates = evidence.build_candidates(records)
        sweep = [item for item in candidates if item["category"] == "test_drive_sweep"]
        self.assertTrue(any(item["start_ticks"] == 0 for item in sweep))
        self.assertTrue(any(item["end_ticks"] >= 240000 for item in sweep))

    def test_zhou_multiple_invitations_regression(self):
        records = [
            row(31900, 32300, "要不要车架一下，亲自开一下感受"),
            row(48900, 49300, "我再邀您体验一下，您来开一圈"),
            row(72000, 72400, "价格前再问一下要不要试价"),
            row(119000, 119500, "前面已经开过了，这次不用试了"),
            row(120000, 120100, "结束"),
        ]
        candidates = evidence.build_candidates(records)
        invites = [item for item in candidates if item["category"] == "test_drive_invite"]
        self.assertGreaterEqual(len(invites), 2, "周先生样本必须保留多次独立邀约")

    def test_sheng_actual_drive_chain_and_repeat_request_regression(self):
        records = [
            row(43500, 43900, "先登记驾驶证和手机号，签一下协议"),
            row(77100, 77500, "现在加速，轻踩刹车，方向盘会比较轻"),
            row(234200, 234700, "元PLUS还有试驾车吗，我想再开一次"),
            row(240000, 240100, "结束"),
        ]
        candidates = evidence.build_candidates(records)
        self.assertTrue(any(item.get("sweep_reason") == "repeat_backtrack_5_to_40_minutes" for item in candidates))
        for item in candidates:
            item["status"] = "confirmed"
            item["review_signals"] = evidence.extract_signals(item["initial_transcript"])
        timeline = evidence.derive_trial_timeline(candidates)
        event_types = {item["event_type"] for item in timeline["events"]}
        self.assertTrue({"paperwork", "dynamic", "repeat"} <= event_types)
        self.assertTrue(timeline["actual_drive_chain"])

    def test_evidence_audit_embeds_transcription_route(self):
        route = {
            "schema_version": evidence.TRANSCRIPTION_AUDIT_SCHEMA,
            "main_transcription": {
                "provider": "tencent_rec_file",
                "model": "16k_zh_en_2.0",
                "language_mode": "mixed_zh",
                "status": "success",
            },
        }
        audit = evidence.build_audit(Path("initial.jsonl"), [], route)
        self.assertEqual(audit["transcription_route"], route)

    def test_local_evidence_audit_does_not_require_cloud_route(self):
        audit = evidence.build_audit(Path("initial.jsonl"), [])
        self.assertNotIn("transcription_route", audit)

    def test_interior_color_confirmation_is_high_impact_candidate(self):
        records = [row(12000, 12400, "报价确认一下，内饰颜色选棕色，可以，就棕色")]
        candidates = evidence.build_candidates(records)
        interior = [item for item in candidates if item["category"] == "interior_color"]
        self.assertEqual(len(interior), 1)
        signals = evidence.extract_signals(interior[0]["initial_transcript"])
        self.assertTrue(signals["quote_components"]["interior_color"])

    def test_zhang_hengchao_wu_late_purchase_timing_is_detected(self):
        records = [
            row(0, 300, "先了解宋Ultra EV 605KM超越型"),
            row(100000, 100300, "价格和配置我再比较一下"),
            row(238000, 238400, "合适的话三天内，本周内就订车"),
            row(240000, 240500, "那今天先这样"),
        ]
        candidates = evidence.build_candidates(records)
        timing = [item for item in candidates if item["category"] == "purchase_timing"]
        self.assertTrue(timing, "必须扫描并发现录音后段成交时间")
        self.assertTrue(any(item["is_late_section"] for item in timing))
        self.assertTrue(any("三天内" in item["initial_transcript"] or "本周内" in item["initial_transcript"] for item in timing))

    def test_fu_shixiong_xu_wet_tissue_and_incomplete_quote_are_candidates(self):
        records = [
            row(150000, 150400, "秦L价格79800，全款，购置税、保险和上牌都算进去"),
            row(239000, 239400, "离店给您拿一包湿纸巾"),
        ]
        candidates = evidence.build_candidates(records)
        wet = [item for item in candidates if item["category"] == "bonus_wet_tissue"]
        self.assertEqual(len(wet), 1)
        for item in candidates:
            item["status"] = "confirmed"
            item["review_signals"] = evidence.extract_signals(item["initial_transcript"])
        quote = evidence.derive_quote_completeness(candidates)
        self.assertFalse(quote["complete"])
        self.assertFalse(quote["components"]["gifts"])
        self.assertFalse(quote["components"]["delivery"])

    def test_zhang_hengchao_wu_wet_tissue_and_e_components_remain_separate(self):
        records = [
            row(208000, 210000, "宋Ultra EV 605超越型159900，全款，保险5800，购置税6800，上牌500"),
            row(237900, 238300, "我给您拿个湿纸巾"),
        ]
        candidates = evidence.build_candidates(records)
        self.assertTrue(any(item["category"] == "bonus_wet_tissue" for item in candidates))
        for item in candidates:
            item["status"] = "confirmed"
            item["review_signals"] = evidence.extract_signals(item["initial_transcript"])
        quote = evidence.derive_quote_completeness(candidates)
        self.assertFalse(quote["complete"], "没有赠品和明确交期时E2不得自动得3分")

    def test_amount_conflict_requires_manual_review(self):
        status, rationale, _, _ = evidence.compare_signals(
            "price_policy", "这款成交价119900元", "这款成交价109900元"
        )
        self.assertEqual(status, "needs_manual_review")
        self.assertIn("金额冲突", rationale)


class DeterministicScoreValidationTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "rule_version": validator.RULE_VERSION,
            "price_policy_version": validator.PRICE_POLICY_VERSION,
            "models_of_interest": {"evidence": "00:30确认宋Pro飞驰版"},
            "intention": {"level": "C", "evidence": "16:20表示继续考虑"},
            "strict_control": {"status": "是", "series": "宋Pro DM-i飞驰版", "filed_price": "99900元"},
            "compliance": [],
            "base": 50,
            "na": 20,
            "bonus": 0,
            "modules": [
                ["A 欢迎", 10, 10], ["B 态度与素养", 25, 14], ["C 静态体验", 20, 11],
                ["D 试乘试驾", 5, 5], ["E 报价成交", 5, 2], ["F 跟进", 5, 0], ["G 环境", 10, 8],
            ],
        }
        coverage = {category: {"status": "scanned_no_candidates", "candidate_count": 0} for category in validator.REQUIRED_COVERAGE}
        self.audit = {
            "rule_version": validator.RULE_VERSION,
            "price_policy_version": validator.PRICE_POLICY_VERSION,
            "coverage": coverage,
            "derived": {"quote_completeness": {"complete": False, "components": {}}},
            "candidates": [
                {"id": "E001", "category": "model_configuration", "status": "confirmed", "timestamp": "00:30-00:40"},
                {"id": "E002", "category": "test_drive_invite", "status": "confirmed", "timestamp": "04:29-04:31"},
                {"id": "E003", "category": "test_drive_invite", "status": "confirmed", "timestamp": "10:52-10:55"},
            ],
            "trial_review": {
                "full_recording_trial_sweep": True,
                "all_windows_reviewed": True,
                "windows": [{"start": "00:00", "end": "15:00", "status": "confirmed"}],
                "timeline": {"events": [], "actual_drive_chain": False},
            },
        }

    def valid_job_and_audit(self):
        return copy.deepcopy(self.job), copy.deepcopy(self.audit)

    @staticmethod
    def confirmed(category: str, candidate_id: str) -> dict:
        return {
            "id": candidate_id,
            "category": category,
            "status": "confirmed",
            "timestamp": "03:20-03:30",
            "review_signals": {"trial": []},
        }

    @staticmethod
    def cloud_route(main_status: str = "success", fallback: str = "none", review_status: str = "complete") -> dict:
        return {
            "schema_version": validator.TRANSCRIPTION_AUDIT_SCHEMA,
            "main_transcription": {
                "provider": "tencent_rec_file",
                "model": "16k_zh_en_2.0",
                "language_mode": "mixed_zh",
                "status": main_status,
                "fallback": fallback,
            },
            "high_impact_review": {
                "provider": "cloud_whisper",
                "model": "large-v3-turbo",
                "status": review_status,
            },
        }

    def test_na_formula_and_floor_are_deterministic(self):
        result = validator.validate(self.job, self.audit)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["calculated_score"], 62)
        self.assertEqual(result["negative_incentive"], "2万元折让/家")

    def test_latest_policy_required_for_new_jobs_and_audits(self):
        for target in ("job", "audit"):
            job, audit = self.valid_job_and_audit()
            (job if target == "job" else audit)["price_policy_version"] = "HB-2026-08-14"
            result = validator.validate(job, audit)
            self.assertFalse(result["valid"])
            self.assertTrue(any("price_policy_version" in e for e in result["errors"]))

    def test_d1_na_cascades_without_temporary_text(self):
        job, audit = self.valid_job_and_audit()
        job.update(base=45, na=25)
        job["modules"][3] = ["D试驾", 0, 0]
        job["rows"] = [["D", "D1", "邀约", 5, "NA", "01:00", "客户主动要求"],
                       ["D", "D2-D9", "体验", 20, "NA", "01:00", "D1 NA联动"]]
        audit["candidates"].append(self.confirmed("na_basis", "NA001"))
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["calculated_score"], 60)
        job["rows"][1][4] = 0
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("requires D2-D9=NA" in e for e in result["errors"]))

    def test_incomplete_quote_blocks_e2_three_points(self):
        job = copy.deepcopy(self.job)
        job["modules"][4] = ["E 报价成交", 5, 5]
        job["base"] = 53
        result = validator.validate(job, self.audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("E2=3" in error for error in result["errors"]))

    def test_e2_three_points_requires_confirmed_interior_color(self):
        job, audit = self.valid_job_and_audit()
        job["modules"][4] = ["E 报价成交", 5, 5]
        job["base"] = 53
        audit["derived"]["quote_completeness"] = {
            "complete": True,
            "components": {
                "vehicle_or_price": True,
                "payment_or_finance": True,
                "fees": True,
                "gifts": True,
                "delivery": True,
                "interior_color": True,
            },
        }
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("quote_confirmation" in error for error in result["errors"]))
        self.assertTrue(any("interior_color audit candidate" in error for error in result["errors"]))

    def test_confirmed_interior_color_allows_e2_three_points(self):
        job, audit = self.valid_job_and_audit()
        job["modules"][4] = ["E 报价成交", 5, 5]
        job["base"] = 53
        job["quote_confirmation"] = {
            "status": "已确认",
            "interior_color": "棕色",
            "evidence": "12:05客户确认棕色内饰",
        }
        audit["derived"]["quote_completeness"] = {
            "complete": True,
            "components": {
                "vehicle_or_price": True,
                "payment_or_finance": True,
                "fees": True,
                "gifts": True,
                "delivery": True,
                "interior_color": True,
            },
        }
        audit["candidates"].append(self.confirmed("interior_color", "E004"))
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_r1_history_remains_valid_without_interior_color(self):
        job, audit = self.valid_job_and_audit()
        job["rule_version"] = "6.0-G-HB-2026-08-27-r1"
        audit["rule_version"] = "6.0-G-HB-2026-08-27-r1"
        audit["coverage"].pop("interior_color", None)
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_unresolved_candidate_blocks_report(self):
        audit = copy.deepcopy(self.audit)
        audit["candidates"][0]["status"] = "needs_manual_review"
        result = validator.validate(self.job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Unresolved high-impact evidence" in error for error in result["errors"]))

    def test_local_job_without_transcription_route_remains_valid(self):
        job, audit = self.valid_job_and_audit()
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_cloud_job_requires_transcription_route(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_codex"
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Cloud result requires transcription_route" in error for error in result["errors"]))

    def test_cloud_failure_with_local_fallback_blocks_final_score(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_codex"
        audit["transcription_route"] = self.cloud_route(main_status="failed", fallback="local_whisper")
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("must succeed" in error for error in result["errors"]))
        self.assertTrue(any("fallback cannot publish" in error for error in result["errors"]))

    def test_cloud_codex_uses_tencent_mixed_engine_and_cloud_review(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_codex"
        audit["transcription_route"] = self.cloud_route()
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_cloud_pipeline_rejects_local_accent_preclassification(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_codex"
        audit["transcription_route"] = {**self.cloud_route(), "accent": {"effective": "wuhan"}}
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("must not use local accent pre-classification" in error for error in result["errors"]))

    def test_cloud_codex_requires_completed_large_v3_turbo_review(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_codex"
        audit["transcription_route"] = self.cloud_route(review_status="failed")
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("must be complete" in error for error in result["errors"]))

    def test_cloud_shadow_never_publishes_notifies_or_counts_monthly(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_shadow"
        job["delivery_controls"] = {"publish": False, "notify": False, "monthly_count": False}
        audit["transcription_route"] = self.cloud_route()
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertEqual(
            [error for error in result["errors"] if "cloud_shadow" in error],
            ["cloud_shadow is candidate-only and cannot publish a final score"],
        )

    def test_cloud_shadow_rejects_enabled_delivery_controls(self):
        job, audit = self.valid_job_and_audit()
        job["result_mode"] = "cloud_shadow"
        job["delivery_controls"] = {"publish": True, "notify": True, "monthly_count": True}
        audit["transcription_route"] = self.cloud_route()
        result = validator.validate(job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("publish=false" in error for error in result["errors"]))
        self.assertTrue(any("notify=false" in error for error in result["errors"]))
        self.assertTrue(any("monthly_count=false" in error for error in result["errors"]))

    def test_test_drive_na_requires_two_confirmed_invitations(self):
        job, audit = self.valid_job_and_audit()
        job["na"] = 20
        job["modules"][3] = ["D试驾", 5, 5]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "03:20", "完成邀请"], ["D", "D2-D9", "试驾体验", 20, "NA", "04:10", "客户未接受"]]
        audit["candidates"] = [self.confirmed("test_drive_invite", "E001")]
        result = validator.validate(job, audit)
        self.assertTrue(any("two confirmed effective invitations" in error for error in result["errors"]))

    def test_duplicate_invitation_window_does_not_count_twice(self):
        job, audit = self.valid_job_and_audit()
        job["na"] = 20
        job["modules"][3] = ["D试驾", 5, 5]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "03:20", "两条重复候选"], ["D", "D2-D9", "试驾体验", 20, "NA", "03:20", "未接受"]]
        audit["candidates"] = [
            self.confirmed("test_drive_invite", "E001"),
            self.confirmed("test_drive_invite", "E002"),
        ]
        result = validator.validate(job, audit)
        self.assertTrue(any("distinct" in error for error in result["errors"]))

    def test_current_rule_rejects_missing_full_trial_sweep(self):
        job, audit = self.valid_job_and_audit()
        audit.pop("trial_review")
        result = validator.validate(job, audit)
        self.assertTrue(any("full-recording trial sweep" in error for error in result["errors"]))

    def test_d1_zero_is_blocked_when_actual_drive_chain_exists(self):
        job, audit = self.valid_job_and_audit()
        job["modules"][3] = ["D试驾", 25, 15]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 0, "07:15", "漏记邀约"], ["D", "D2-D9", "试驾体验", 20, 15, "12:51", "已实际试驾"]]
        audit["candidates"].append(self.confirmed("test_drive_actual", "E010"))
        result = validator.validate(job, audit)
        self.assertTrue(any("D1=0 conflicts" in error for error in result["errors"]))

    def test_customer_agreed_but_unarranged_drive_cannot_be_na(self):
        job, audit = self.valid_job_and_audit()
        job["na"] = 20
        job["modules"][3] = ["D试驾", 5, 5]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "03:20", "两次邀请"], ["D", "D2-D9", "试驾体验", 20, "NA", "04:10", "未安排"]]
        audit["candidates"] = [
            self.confirmed("test_drive_invite", "E001"),
            self.confirmed("test_drive_invite", "E002"),
            {**self.confirmed("test_drive_response", "E003"), "review_signals": {"trial": ["agree"]}},
        ]
        result = validator.validate(job, audit)
        self.assertTrue(any("customer agreed" in error for error in result["errors"]))

    def test_customer_scheduled_next_drive_allows_d2_d9_na(self):
        job, audit = self.valid_job_and_audit()
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "10:20；16:47", "两次邀请"], ["D", "D2-D9", "试驾体验", 20, "NA", "16:53", "客户明确说明明天来试驾"]]
        audit["candidates"].append(
            {**self.confirmed("test_drive_response", "E004"), "review_signals": {"trial": ["agree", "scheduled"]}}
        )
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_second_invite_then_customer_says_next_time_allows_d2_d9_na(self):
        job, audit = self.valid_job_and_audit()
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "05:43；08:22", "两次邀请"], ["D", "D2-D9", "试驾体验", 20, "NA", "09:35", "客户说下次再试"]]
        audit["candidates"].append(
            {**self.confirmed("test_drive_response", "E004"), "review_signals": {"trial": ["deferred"]}}
        )
        result = validator.validate(job, audit)
        self.assertTrue(result["valid"], result["errors"])

    def test_actual_drive_score_requires_confirmed_actual_drive(self):
        job, audit = self.valid_job_and_audit()
        job["modules"][3] = ["D试驾", 25, 20]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "03:20", "完成邀请"], ["D", "D2-D9", "试驾体验", 20, 15, "04:10", "声称完成试驾"]]
        audit["candidates"] = [self.confirmed("test_drive_invite", "E001")]
        result = validator.validate(job, audit)
        self.assertTrue(any("actual test drive" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
