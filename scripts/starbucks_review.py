"""Reporting-only Starbucks introduction check, effective 2026-10-05."""
from datetime import date
import re
EFFECTIVE_DATE = "2026-10-05"
STATUSES = {"已介绍", "未介绍", "待核实"}
TIME = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")

def required(job):
    if "starbucks_introduction" in job:
        return True
    day = job.get("report_date") or job.get("source", {}).get("task_date")
    if day:
        try:
            return date.fromisoformat(str(day)) >= date.fromisoformat(EFFECTIVE_DATE)
        except ValueError:
            return True
    return job.get("rule_version") == "6.0-G-HB-2026-09-14-r3"

def validate_fields(job):
    if not required(job):
        return []
    item = job.get("starbucks_introduction")
    if not isinstance(item, dict):
        return ["Missing required starbucks_introduction report field"]
    errors = []
    if item.get("status") not in STATUSES:
        errors.append("starbucks_introduction.status must be 已介绍/未介绍/待核实")
    if not str(item.get("evidence", "")).strip() or not TIME.search(str(item.get("evidence", ""))):
        errors.append("starbucks_introduction.evidence requires a timestamp or reviewed recording range")
    return errors

def validate_audit(job, audit):
    errors = validate_fields(job)
    if not required(job) or errors:
        return errors
    item = job["starbucks_introduction"]
    record = audit.get("starbucks_introduction")
    if not isinstance(record, dict):
        return ["Missing starbucks_introduction evidence audit"]
    if record.get("status") != item["status"]:
        errors.append("Starbucks introduction job/audit status mismatch")
    if record.get("full_transcript_scanned") is not True:
        errors.append("Starbucks introduction requires full transcript semantic scan")
    if not record.get("reviewed_at") or not record.get("rationale"):
        errors.append("Starbucks introduction audit requires review time and rationale")
    reviews = record.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        errors.append("Starbucks introduction requires reviewed hospitality audio windows")
    else:
        for review in reviews:
            if not isinstance(review, dict) or not all(review.get(k) for k in ("window", "channel", "model", "conclusion")) or not TIME.search(str(review.get("window", ""))):
                errors.append("Starbucks introduction review needs window/channel/model/conclusion")
    positive = [c for c in audit.get("candidates", []) if c.get("category") == "starbucks_introduction" and c.get("status") == "confirmed" and c.get("introduced_to_customer") is True]
    if item["status"] == "已介绍" and (not positive or record.get("introduced_to_customer") is not True):
        errors.append("已介绍 requires confirmed customer-directed brand introduction evidence")
    if item["status"] == "未介绍" and (positive or record.get("introduced_to_customer") is True):
        errors.append("未介绍 conflicts with confirmed customer-directed Starbucks introduction")
    return errors
