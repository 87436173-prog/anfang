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
            "coverage": coverage,
            "derived": {"quote_completeness": {"complete": False, "components": {}}},
            "candidates": [
                {"id": "E001", "category": "model_configuration", "status": "confirmed", "timestamp": "00:30-00:40"},
                {"id": "E002", "category": "test_drive_invite", "status": "confirmed", "timestamp": "04:29-04:31"},
                {"id": "E003", "category": "test_drive_invite", "status": "confirmed", "timestamp": "10:52-10:55"},
            ],
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

    def test_na_formula_and_floor_are_deterministic(self):
        result = validator.validate(self.job, self.audit)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["calculated_score"], 62)
        self.assertEqual(result["negative_incentive"], "2万元折让/家")

    def test_incomplete_quote_blocks_e2_three_points(self):
        job = copy.deepcopy(self.job)
        job["modules"][4] = ["E 报价成交", 5, 5]
        job["base"] = 53
        result = validator.validate(job, self.audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("E2=3" in error for error in result["errors"]))

    def test_unresolved_candidate_blocks_report(self):
        audit = copy.deepcopy(self.audit)
        audit["candidates"][0]["status"] = "needs_manual_review"
        result = validator.validate(self.job, audit)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Unresolved high-impact evidence" in error for error in result["errors"]))

    def test_test_drive_na_requires_two_confirmed_invitations(self):
        job, audit = self.valid_job_and_audit()
        job["na"] = 20
        job["modules"][3] = ["D试驾", 5, 5]
        job["base"] = sum(row[2] for row in job["modules"])
        job["rows"] = [["D", "D1", "试驾邀请", 5, 5, "03:20", "完成邀请"], ["D", "D2-D9", "试驾体验", 20, "NA", "04:10", "客户未接受"]]
        audit["candidates"] = [self.confirmed("test_drive_invite", "E001")]
        result = validator.validate(job, audit)
        self.assertTrue(any("two confirmed effective invitations" in error for error in result["errors"]))

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
