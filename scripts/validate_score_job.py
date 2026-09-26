from __future__ import annotations

import argparse
import itertools
import json
import math
import re
from pathlib import Path


RULE_VERSION = "6.0-G-HB-2026-09-14-r3"
PRICE_POLICY_VERSION = "HB-2026-09-14"
TRANSCRIPTION_AUDIT_SCHEMA = "byd-transcription-pipeline-v2"
LEGACY_RULE_VERSIONS = {"6.0-G-HB-2026-08-27-r1", "6.0-G-HB-2026-08-27-r2"}
SUPPORTED_RULE_VERSIONS = {RULE_VERSION, *LEGACY_RULE_VERSIONS}
CANONICAL_MAX = {"A": 10, "B": 25, "C": 20, "D": 25, "E": 5, "F": 5, "G": 10}
REQUIRED_COVERAGE = {
    "model_configuration", "price_policy", "interior_color", "test_drive_invite", "test_drive_response",
    "test_drive_actual", "test_drive_sweep", "purchase_timing", "bonus_wet_tissue", "bonus_starbucks",
    "h_veto", "na_basis", "negative_incentive",
}
TIMESTAMP_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")


def possible_sums(parts: list[set[int]]) -> set[int]:
    return {sum(values) for values in itertools.product(*parts)}


B_SCORES = possible_sums([
    {0, 3}, {0, 3}, {0, 3}, {-2, 0, 3, 5}, {0, 4}, {0, 2}, {0, 2, 3}, {0, 2}
])
C_SCORES = possible_sums([{0, 2}, {0, 3}, {0, 3}, {0, 2, 4}, {0, 2}, {0, 3}, {0, 1, 3}])


def module_letter(name: str) -> str:
    match = re.search(r"[A-G]", str(name).upper())
    if not match:
        raise ValueError(f"Unknown module name: {name}")
    return match.group(0)


def allowed_module_score(letter: str, applicable_max: int, score: int) -> bool:
    if score > applicable_max:
        return False
    if letter == "A":
        return applicable_max == 10 and score in {0, 5, 10}
    if letter == "B":
        return applicable_max == 25 and score in B_SCORES
    if letter == "C":
        return 0 <= score <= applicable_max and score in C_SCORES
    if letter == "D":
        return (applicable_max, score) in {
            (0, 0),
            (25, 0), (25, 5), (25, 15), (25, 20), (25, 25),
            (20, 15), (20, 20), (5, 5),
        }
    if letter == "E":
        return score in {0, 2, 3, 5} and score <= applicable_max and applicable_max in {0, 2, 3, 5}
    if letter == "F":
        return applicable_max == 5 and score in {0, 1, 2, 3, 4, 5}
    if letter == "G":
        return applicable_max == 10 and score in {0, 2, 4, 6, 8, 10}
    return False


def final_score(base: int, na: int, bonus: int) -> int:
    denominator = 100 - na
    if denominator <= 0:
        raise ValueError("NA must leave a positive denominator")
    return math.floor(min(100, base / denominator * 100 + bonus))


def negative_incentive(score: int) -> str:
    if score == 0:
        return "8万元折让/家/次"
    if score <= 59:
        return "5万元折让/家"
    if score <= 69:
        return "2万元折让/家"
    return "无负激励"


def confirmed_candidates(audit: dict, category: str) -> list[dict]:
    return [item for item in audit.get("candidates", []) if item.get("category") == category and item.get("status") == "confirmed"]


def has_timestamp(value: object) -> bool:
    return bool(TIMESTAMP_RE.search(str(value or "")))


def timestamp_seconds(value: object) -> int | None:
    match = TIMESTAMP_RE.search(str(value or ""))
    if not match:
        return None
    minutes, seconds = match.group(0).split(":", 1)
    return int(minutes) * 60 + int(seconds)


def distinct_invitation_count(candidates: list[dict], minimum_gap_seconds: int = 45) -> int:
    """Count invitation events, collapsing duplicate/overlapping audit windows."""
    times = sorted(
        timestamp
        for timestamp in (timestamp_seconds(item.get("timestamp")) for item in candidates)
        if timestamp is not None
    )
    distinct: list[int] = []
    for value in times:
        if not distinct or value - distinct[-1] >= minimum_gap_seconds:
            distinct.append(value)
    return len(distinct)


def validate_rows(job: dict, errors: list[str]) -> None:
    allowed = {
        "A1": {0, 5, "NA"}, "A2": {0, 5, "NA"}, "A3": {0, 3},
        "B1": {0, 3}, "B2": {0, 3}, "B3": {0, 3}, "B4": {-2, 0, 3, 5},
        "B5a": {0, 4}, "B5b": {0, 2}, "B6": {0, 2, 3}, "B7": {0, 2},
        "C2": {0, 2, "NA"}, "C3": {0, 3, "NA"}, "C4": {0, 3, "NA"},
        "C5": {0, 2, 4, "NA"}, "C6": {0, 2, "NA"}, "C7": {0, 3, "NA"}, "C8": {0, 1, 3, "NA"},
        "D1": {0, 5, "NA"}, "D2-D9": {0, 15, 20, "NA"},
        "E2": {0, 3, "NA"}, "E3": {0, 2, "NA"},
        "F1": {0, 1}, "F2": {0, 2}, "F3": {0, 2},
        "G1": {0, 4}, "G2": {0, 4}, "G3": {0, 2},
    }
    for row in job.get("rows", []):
        if len(row) < 7:
            errors.append(f"Malformed scoring row: {row}")
            continue
        key = str(row[1])
        value = row[4]
        if key in allowed and value not in allowed[key]:
            errors.append(f"Disallowed score for {key}: {value}")
        if key in allowed and value != "NA" and not has_timestamp(row[5]) and int(value) != 0:
            errors.append(f"Scored row lacks timestamp: {key}")


def row_value(job: dict, key: str) -> object | None:
    for row in job.get("rows", []):
        if len(row) >= 5 and str(row[1]) == key:
            return row[4]
    return None


def validate_transcription_route(job: dict, audit: dict, errors: list[str]) -> None:
    result_mode = str(job.get("result_mode", "local_codex_test"))
    if result_mode not in {"local_codex_test", "cloud_shadow", "cloud_codex"}:
        errors.append("result_mode must be local_codex_test/cloud_shadow/cloud_codex")
        return

    if result_mode == "local_codex_test":
        return

    if result_mode == "cloud_shadow":
        controls = job.get("delivery_controls", {})
        if controls.get("publish") is not False:
            errors.append("cloud_shadow requires delivery_controls.publish=false")
        if controls.get("notify") is not False:
            errors.append("cloud_shadow requires delivery_controls.notify=false")
        if controls.get("monthly_count") is not False:
            errors.append("cloud_shadow requires delivery_controls.monthly_count=false")
        errors.append("cloud_shadow is candidate-only and cannot publish a final score")

    route = audit.get("transcription_route")
    if route is None:
        errors.append("Cloud result requires transcription_route audit")
        return
    if route.get("schema_version") != TRANSCRIPTION_AUDIT_SCHEMA:
        errors.append("Unsupported transcription_route.schema_version")
    if any(key in route for key in ("accent", "requested_accent", "effective_accent")):
        errors.append("Cloud pipeline must not use local accent pre-classification")

    main = route.get("main_transcription", {})
    if main.get("provider") != "tencent_rec_file":
        errors.append("Cloud main transcription provider must be tencent_rec_file")
    if main.get("model") != "16k_zh_en_2.0":
        errors.append("Cloud main transcription model must be 16k_zh_en_2.0")
    if main.get("language_mode") != "mixed_zh":
        errors.append("Cloud main transcription language_mode must be mixed_zh")
    if main.get("status") != "success":
        errors.append("Cloud main transcription must succeed before publication")
    if main.get("fallback") not in {None, "none"}:
        errors.append("Cloud main transcription fallback cannot publish a final score")

    review = route.get("high_impact_review", {})
    if review.get("provider") != "cloud_whisper":
        errors.append("Cloud high-impact review provider must be cloud_whisper")
    if review.get("model") != "large-v3-turbo":
        errors.append("Cloud high-impact review model must be large-v3-turbo")
    if review.get("status") != "complete":
        errors.append("Cloud high-impact review must be complete before publication")


def validate(job: dict, audit: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    validate_transcription_route(job, audit, errors)
    job_version = job.get("rule_version")
    audit_version = audit.get("rule_version")
    if job_version not in SUPPORTED_RULE_VERSIONS:
        errors.append(f"unsupported job.rule_version: {job_version}; active version is {RULE_VERSION}")
    if audit_version != job_version:
        errors.append("audit.rule_version must match job.rule_version")

    if job_version == RULE_VERSION:
        if job.get("price_policy_version") != PRICE_POLICY_VERSION:
            errors.append("Current job requires price_policy_version=" + PRICE_POLICY_VERSION)
        if audit.get("price_policy_version") != PRICE_POLICY_VERSION:
            errors.append("Current audit requires price_policy_version=" + PRICE_POLICY_VERSION)

    modules = job.get("modules", [])
    seen: dict[str, tuple[int, int]] = {}
    for row in modules:
        if len(row) != 3:
            errors.append(f"Malformed module row: {row}")
            continue
        letter = module_letter(row[0])
        applicable_max, score = int(row[1]), int(row[2])
        if letter in seen:
            errors.append(f"Duplicate module: {letter}")
        seen[letter] = (applicable_max, score)
        if applicable_max > CANONICAL_MAX[letter] or applicable_max < 0:
            errors.append(f"Invalid applicable max for {letter}: {applicable_max}")
        if not allowed_module_score(letter, applicable_max, score):
            errors.append(f"Disallowed module score: {letter} {score}/{applicable_max}")
    if set(seen) != set(CANONICAL_MAX):
        errors.append("Modules must contain A-G exactly once")

    base = int(job.get("base", -999))
    na = int(job.get("na", -1))
    bonus = int(job.get("bonus", 0))
    if modules and sum(score for _, score in seen.values()) != base:
        errors.append("base does not equal the sum of module scores")
    if modules and sum(maximum for maximum, _ in seen.values()) != 100 - na:
        errors.append("applicable module maxima do not equal 100-NA")
    if bonus not in {0, 3, 6, 9}:
        errors.append(f"bonus must be 0/3/6/9, got {bonus}")

    calculated = final_score(base, na, bonus) if base >= 0 and 0 <= na < 100 else -1
    if "final_score" in job and int(job["final_score"]) != calculated:
        errors.append("job.final_score conflicts with deterministic calculation")
    expected_negative = negative_incentive(calculated) if calculated >= 0 else "invalid"
    if "negative_incentive" in job and job["negative_incentive"] != expected_negative:
        errors.append("job.negative_incentive conflicts with deterministic calculation")

    coverage = audit.get("coverage", {})
    if job_version == RULE_VERSION:
        required_coverage = REQUIRED_COVERAGE
    elif job_version == "6.0-G-HB-2026-08-27-r1":
        required_coverage = REQUIRED_COVERAGE - {"interior_color", "test_drive_sweep"}
    else:
        required_coverage = REQUIRED_COVERAGE - {"test_drive_sweep"}
    missing = required_coverage - set(coverage)
    if missing:
        errors.append(f"Missing audit coverage: {sorted(missing)}")
    unresolved = [item.get("id", "unknown") for item in audit.get("candidates", []) if item.get("status") != "confirmed"]
    if unresolved:
        errors.append(f"Unresolved high-impact evidence: {unresolved}")
    if job_version == RULE_VERSION:
        trial_review = audit.get("trial_review", {})
        if trial_review.get("full_recording_trial_sweep") is not True or trial_review.get("all_windows_reviewed") is not True:
            errors.append("Current rule requires a completed full-recording trial sweep before publication")

    if not has_timestamp(job.get("models_of_interest", {}).get("evidence")):
        errors.append("models_of_interest.evidence lacks timestamp")
    if not has_timestamp(job.get("intention", {}).get("evidence")):
        errors.append("intention.evidence lacks timestamp")
    for item in job.get("compliance", []):
        if not has_timestamp(item.get("timestamp")):
            errors.append("compliance item lacks timestamp")

    intent = job.get("intention", {}).get("level")
    if intent in {"H", "A"} and not confirmed_candidates(audit, "purchase_timing"):
        errors.append(f"Intent {intent} requires confirmed purchase_timing evidence")
    if job.get("strict_control", {}).get("status") == "是" and not confirmed_candidates(audit, "model_configuration"):
        errors.append("Strict-control status requires confirmed model/configuration evidence")

    if na > 0:
        na_candidates = confirmed_candidates(audit, "na_basis")
        drive_invites = confirmed_candidates(audit, "test_drive_invite")
        drive_responses_for_na = confirmed_candidates(audit, "test_drive_response")
        scheduled_next_drive = any(
            "scheduled" in item.get("review_signals", {}).get("trial", [])
            for item in drive_responses_for_na
        )
        if not na_candidates and distinct_invitation_count(drive_invites) < 2 and not scheduled_next_drive:
            errors.append("NA requires confirmed refusal/NA evidence or two confirmed test-drive invitations")
    if bonus > 0:
        bonus_candidates = confirmed_candidates(audit, "bonus_wet_tissue") + confirmed_candidates(audit, "bonus_starbucks")
        if len(bonus_candidates) * 3 < bonus:
            errors.append("bonus exceeds confirmed wet-tissue/Starbucks evidence")

    drive_invites = confirmed_candidates(audit, "test_drive_invite")
    drive_responses = confirmed_candidates(audit, "test_drive_response")
    drive_actual = confirmed_candidates(audit, "test_drive_actual")
    response_signals = {
        signal
        for item in drive_responses
        for signal in item.get("review_signals", {}).get("trial", [])
    }
    d1_value = row_value(job, "D1")
    d2_d9_value = row_value(job, "D2-D9")
    # User rule updated 2026-09-15: D1 NA always makes the full drive module NA.
    d1_na_cascade = d1_value == "NA"
    if d1_na_cascade and d2_d9_value != "NA":
        errors.append("User policy requires D2-D9=NA when D1=NA")
    if d1_na_cascade and not confirmed_candidates(audit, "na_basis"):
        errors.append("D1=NA requires confirmed NA-basis evidence")
    if d1_na_cascade and (seen.get("D") != (0, 0) or na < 25):
        errors.append("D1=NA requires full D module NA25 with applicable max/score 0/0")
    distinct_drive_invites = distinct_invitation_count(drive_invites)
    timeline = audit.get("trial_review", {}).get("timeline", {})
    actual_drive_confirmed = bool(drive_actual) or timeline.get("actual_drive_chain") is True
    if d1_value == 5 and not actual_drive_confirmed and distinct_drive_invites < 2:
        errors.append("D1=5 without actual test drive requires two confirmed effective invitations")
    if d1_value == 5 and actual_drive_confirmed and not drive_invites:
        errors.append("D1=5 requires confirmed invitation evidence")
    if d1_value == 0 and actual_drive_confirmed:
        errors.append("D1=0 conflicts with confirmed actual test-drive evidence; verify invitation or customer-initiated NA")
    if d2_d9_value == 0 and actual_drive_confirmed:
        errors.append("D2-D9=0 conflicts with confirmed actual test-drive evidence")
    if d2_d9_value in {15, 20} and not actual_drive_confirmed:
        errors.append("D2-D9 test-drive score requires confirmed actual test drive evidence")
    if d2_d9_value == "NA":
        scheduled_next_drive = "scheduled" in response_signals
        deferred_next_drive = "deferred" in response_signals
        if not d1_na_cascade and distinct_drive_invites < 2 and not scheduled_next_drive:
            errors.append("D2-D9=NA requires two distinct confirmed effective invitations or a confirmed next-drive schedule")
        if not d1_na_cascade and "agree" in response_signals and not actual_drive_confirmed and not scheduled_next_drive and not deferred_next_drive:
            errors.append("D2-D9 cannot be NA when customer agreed but sales did not arrange the drive")

    if "E" in seen:
        e_max, e_score = seen["E"]
        e2_awarded = (e_max == 5 and e_score in {3, 5}) or (e_max == 3 and e_score == 3)
        quote = audit.get("derived", {}).get("quote_completeness", {})
        if e2_awarded and not quote.get("complete"):
            errors.append("E2=3 requires confirmed vehicle/price, payment/finance, fees, gifts, delivery and interior-color evidence")
        if job_version != "6.0-G-HB-2026-08-27-r1" and e2_awarded:
            confirmation = job.get("quote_confirmation", {})
            interior_color = str(confirmation.get("interior_color", "")).strip()
            if confirmation.get("status") != "已确认" or not interior_color or interior_color in {"未确认", "待核实"}:
                errors.append("E2=3 requires quote_confirmation.status=已确认 and a confirmed interior_color")
            if not has_timestamp(confirmation.get("evidence")):
                errors.append("E2=3 requires timestamped interior-color confirmation evidence")
            if not confirmed_candidates(audit, "interior_color"):
                errors.append("E2=3 requires a confirmed interior_color audit candidate")
        if not quote:
            warnings.append("quote completeness derivation is absent")

    h_triggered = bool(job.get("h_veto", {}).get("triggered", False))
    if h_triggered and not confirmed_candidates(audit, "h_veto"):
        errors.append("H veto requires confirmed H evidence")

    validate_rows(job, errors)
    return {
        "rule_version": job_version,
        "active_rule_version": RULE_VERSION,
        "valid": not errors,
        "calculated_score": calculated,
        "negative_incentive": expected_negative,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate deterministic BYD 6.0-G score and evidence coverage")
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding="utf-8"))
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    result = validate(job, audit)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    if not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
