from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import wave
from collections import defaultdict
from pathlib import Path
from typing import Iterable


RULE_VERSION = "6.0-G-HB-2026-09-14-r3"
PRICE_POLICY_VERSION = "HB-2026-09-14"
TRANSCRIPTION_AUDIT_SCHEMA = "byd-transcription-pipeline-v2"
HIGH_PRECISION_MODEL = r"C:\Users\no02\.cache\whisper\ggml-large-v3-turbo-q5_0.bin"
FALLBACK_MODEL = r"C:\Users\no02\.cache\whisper\ggml-small.bin"

REQUIRED_CATEGORIES = (
    "model_configuration",
    "price_policy",
    "interior_color",
    "test_drive_invite",
    "test_drive_response",
    "test_drive_actual",
    "purchase_timing",
    "bonus_wet_tissue",
    "bonus_starbucks",
    "h_veto",
    "na_basis",
)

PATTERNS = {
    "model_configuration": (
        r"秦\s*(?:max|MAX|l|L)", r"宋\s*(?:pro|Pro|ultra|Ultra)", r"元\s*(?:up|UP|plus|PLUS)",
        r"汉\s*EV", r"唐\s*EV", r"大唐", r"海豹", r"飞驰版", r"领先型|超越型|卓越型|尊贵型|尊荣型|旗舰型",
        r"\d{2,3}\s*(?:公里|KM|km)", r"高配|中配|低配|配置|版本",
    ),
    "price_policy": (
        r"\d+(?:\.\d+)?\s*(?:万|元|块|个点)", r"价格|报价|落地|裸车|成交价", r"优惠|补贴|返息|返现|免息",
        r"保险|购置税|上牌|服务费", r"赠送|礼品|精品|保养|充电桩", r"交车|提车周期|到车", r"内饰颜色|座椅颜色|内饰配色",
    ),
    "interior_color": (
        r"(?:内饰|座椅|舱内).{0,8}(?:颜色|配色|色系)",
        r"(?:颜色|配色|色系).{0,8}(?:内饰|座椅|舱内)",
    ),
    "test_drive_invite": (
        r"要不要.{0,8}(?:试驾|试乘|开一下|体验一下)", r"可以.{0,8}(?:试驾|试乘|试一下)",
        r"安排.{0,8}(?:试驾|试乘)", r"有试驾车", r"试驾一下|试乘试驾",
    ),
    "test_drive_response": (
        r"不用.{0,5}(?:试驾|试乘|试)", r"不想.{0,5}(?:试驾|试乘|试)", r"不试", r"拒绝.{0,5}试驾",
        r"可以.{0,5}(?:试驾|试乘|开)", r"愿意.{0,5}(?:试驾|试乘|开)", r"要开一下|去试|安排吧",
        r"(?:明天|后天|周末|下周|星期[一二三四五六日天]|周[一二三四五六日天]|上午|下午|晚上).{0,20}(?:试驾|试乘|试一下|开一下|提前试)",
        r"(?:下次|改天|回头).{0,8}(?:试驾|试乘|试一下|再试|再开)",
    ),
    "test_drive_actual": (
        r"试驾协议|试驾登记|驾驶证|驾照", r"试驾路线|路线怎么走", r"出发|开出去|上路",
        r"试驾结束|开回来|刚才试驾", r"方向盘|刹车|油门|加速" ,
    ),
    "purchase_timing": (
        r"今天.{0,10}(?:订|定|签|买|锁车)", r"明天.{0,10}(?:订|定|签|买|提车)",
        r"(?:3|三)天内", r"本周内|这个星期|星期内", r"月底前|一个月内|近期",
        r"订车|定车|下定|订金|定金|锁车|什么时候买|什么时候提车|提车时间",
    ),
    "bonus_wet_tissue": (r"湿纸巾|湿巾",),
    "bonus_starbucks": (r"星巴克", r"喝.{0,6}咖啡|咖啡.{0,6}(?:喝|饮用)"),
    "h_veto": (
        r"暗访|神秘客|检查人员|检查组", r"红包|行贿|打点", r"滚出去|驱赶", r"恐吓|威胁",
        r"隐私|偷拍|申诉造假|联络检查", r"退订.{0,8}(?:投诉|不退)|投诉.{0,8}(?:威胁|不处理)",
    ),
    "na_basis": (
        r"不需要|不用讲|不用介绍|不想听|不想了解|不体验|不试驾|不用试驾|明确拒绝",
    ),
}

MODEL_ALIASES = {
    "秦MAX": ("秦max", "秦 max", "秦麦克斯"),
    "秦L": ("秦l", "秦 l"),
    "宋Pro": ("宋pro", "宋 pro"),
    "宋Ultra": ("宋ultra", "宋 ultra"),
    "元UP": ("元up", "元 up"),
    "元PLUS": ("元plus", "元 plus"),
    "汉EV": ("汉ev", "汉 ev"),
    "唐EV": ("唐ev", "唐 ev", "大唐"),
    "海豹": ("海豹",),
}


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            records.append({"t0": int(row["t0"]), "t1": int(row["t1"]), "text": str(row.get("text", "")).strip()})
    return records


def timestamp(ticks: int) -> str:
    seconds = max(0, ticks // 100)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def text_for_window(records: Iterable[dict], start: int, end: int) -> str:
    return " ".join(row["text"] for row in records if row["t1"] >= start and row["t0"] <= end and row["text"]).strip()


def category_hits(records: list[dict]) -> dict[str, list[dict]]:
    compiled = {category: [re.compile(pattern, re.I) for pattern in patterns] for category, patterns in PATTERNS.items()}
    found: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        for category, regexes in compiled.items():
            terms = [match.group(0) for regex in regexes for match in regex.finditer(row["text"])]
            if terms:
                found[category].append({**row, "terms": terms})
    return found


def build_candidates(records: list[dict], context_ticks: int = 1200, merge_gap_ticks: int = 800) -> list[dict]:
    if not records:
        return []
    total_end = max(row["t1"] for row in records)
    candidates: list[dict] = []
    for category, hits in category_hits(records).items():
        groups: list[list[dict]] = []
        for hit in hits:
            if not groups or hit["t0"] - groups[-1][-1]["t1"] > merge_gap_ticks:
                groups.append([hit])
            else:
                groups[-1].append(hit)
        for group in groups:
            hit_start = min(row["t0"] for row in group)
            hit_end = max(row["t1"] for row in group)
            start = max(0, hit_start - context_ticks)
            end = min(total_end, hit_end + context_ticks)
            candidates.append({
                "category": category,
                "start_ticks": start,
                "end_ticks": end,
                "timestamp": f"{timestamp(hit_start)}-{timestamp(hit_end)}",
                "initial_transcript": text_for_window(records, start, end),
                "trigger_terms": sorted({term for row in group for term in row["terms"]}),
                "is_late_section": hit_start >= total_end * 0.75,
                "review_transcript": "",
                "adopted_conclusion": "",
                "rationale": "",
                "status": "pending",
            })
    candidates.sort(key=lambda item: (item["start_ticks"], item["category"]))
    for index, item in enumerate(candidates, 1):
        item["id"] = f"E{index:03d}"
    return candidates


def write_wav_slice(source: Path, target: Path, start_ticks: int, end_ticks: int) -> None:
    with wave.open(str(source), "rb") as src:
        if src.getnchannels() != 1 or src.getsampwidth() != 2 or src.getframerate() != 16000:
            raise ValueError("Expected 16 kHz mono 16-bit PCM WAV")
        rate = src.getframerate()
        start_frame = min(src.getnframes(), int(start_ticks / 100 * rate))
        end_frame = min(src.getnframes(), int(end_ticks / 100 * rate))
        src.setpos(start_frame)
        frames = src.readframes(max(0, end_frame - start_frame))
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as dst:
            dst.setparams(src.getparams())
            dst.writeframes(frames)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def extract_signals(text: str) -> dict:
    value = normalize(text)
    models = sorted(name for name, aliases in MODEL_ALIASES.items() if any(normalize(alias) in value for alias in aliases))
    amounts = sorted(set(re.findall(r"\d+(?:\.\d+)?(?:万|元|块|个点)", value)))
    trial = sorted(name for name, pattern in {
        "invite": r"试驾|试乘|有试驾车|开一下|体验一下",
        "agree": r"可以试|愿意试|要开一下|去试|安排吧",
        "scheduled": r"(?:明天|后天|周末|下周|星期[一二三四五六日天]|周[一二三四五六日天]|上午|下午|晚上).{0,20}(?:试驾|试乘|试一下|开一下|提前试)",
        "deferred": r"(?:下次|改天|回头).{0,8}(?:试驾|试乘|试一下|再试|再开)",
        "refuse": r"不用试|不试驾|不想试|拒绝试驾",
        "actual": r"试驾协议|试驾登记|驾驶证|试驾路线|开出去|试驾结束|刚才试驾",
    }.items() if re.search(pattern, value))
    timing = sorted(set(re.findall(r"(?:今天|明天|三天内|3天内|本周内|这个星期|星期内|月底前|一个月内|近期).{0,10}(?:订|定|签|买|提车)?", value)))
    quote = {
        "vehicle_or_price": bool(amounts or re.search(r"车型|配置|车价|报价", value)),
        "payment_or_finance": bool(re.search(r"全款|贷款|金融|免息|首付|月供", value)),
        "fees": bool(re.search(r"保险|购置税|上牌|服务费", value)),
        "gifts": bool(re.search(r"赠送|礼品|精品|脚垫|车膜|后备箱垫|保养|充电桩", value)),
        "delivery": bool(re.search(r"交车|提车|到车|周期|现车", value)),
        "interior_color": bool(re.search(r"(?:内饰|座椅|舱内).{0,8}(?:颜色|配色|色系)|(?:颜色|配色|色系).{0,8}(?:内饰|座椅|舱内)", value)),
    }
    return {
        "models": models,
        "amounts": amounts,
        "trial": trial,
        "timing": timing,
        "wet_tissue": bool(re.search(r"湿纸巾|湿巾", value)),
        "starbucks": bool(re.search(r"星巴克|咖啡.{0,6}(?:喝|饮用)|喝.{0,6}咖啡", value)),
        "h_veto": bool(any(re.search(pattern, value, re.I) for pattern in PATTERNS["h_veto"])),
        "na_basis": bool(any(re.search(pattern, value, re.I) for pattern in PATTERNS["na_basis"])),
        "quote_components": quote,
    }


def category_confirmed(category: str, signals: dict) -> bool:
    checks = {
        "model_configuration": bool(signals["models"] or re.search(r"配置|版本|公里|km", signals.get("raw", ""), re.I)),
        "price_policy": bool(signals["amounts"] or any(signals["quote_components"].values())),
        "interior_color": signals["quote_components"]["interior_color"],
        "test_drive_invite": "invite" in signals["trial"],
        "test_drive_response": bool({"agree", "scheduled", "deferred", "refuse"} & set(signals["trial"])),
        "test_drive_actual": "actual" in signals["trial"],
        "purchase_timing": bool(signals["timing"]),
        "bonus_wet_tissue": signals["wet_tissue"],
        "bonus_starbucks": signals["starbucks"],
        "h_veto": signals["h_veto"],
        "na_basis": signals["na_basis"],
    }
    return bool(checks[category])


def compare_signals(category: str, initial_text: str, review_text: str) -> tuple[str, str, dict, dict]:
    initial = extract_signals(initial_text)
    reviewed = extract_signals(review_text)
    initial["raw"] = normalize(initial_text)
    reviewed["raw"] = normalize(review_text)
    reasons: list[str] = []
    if not category_confirmed(category, reviewed):
        reasons.append("二次复核未确认该类关键行为或实体")
    if category == "price_policy" and initial["amounts"] and reviewed["amounts"]:
        if set(initial["amounts"]).isdisjoint(reviewed["amounts"]):
            reasons.append("初次与二次金额冲突")
    if category == "model_configuration" and initial["models"] and reviewed["models"]:
        if set(initial["models"]).isdisjoint(reviewed["models"]):
            reasons.append("初次与二次车型冲突")
    if category.startswith("test_drive") and initial["trial"] and reviewed["trial"]:
        if set(initial["trial"]).isdisjoint(reviewed["trial"]):
            reasons.append("初次与二次试驾行为冲突")
    status = "needs_manual_review" if reasons else "confirmed"
    rationale = "；".join(reasons) if reasons else "局部高精度复核确认，未发现关键结构化信号冲突"
    initial.pop("raw", None)
    reviewed.pop("raw", None)
    return status, rationale, initial, reviewed


def run_review(transcriber: Path, wav: Path, output: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["WHISPER_MODEL"] = HIGH_PRECISION_MODEL
    env["WHISPER_FALLBACK_MODEL"] = FALLBACK_MODEL
    env["WHISPER_CHUNK_SECONDS"] = "120"
    return subprocess.run(
        [sys.executable, str(transcriber), str(wav), str(output)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def derive_quote_completeness(candidates: list[dict]) -> dict:
    combined = {key: False for key in ("vehicle_or_price", "payment_or_finance", "fees", "gifts", "delivery", "interior_color")}
    for item in candidates:
        if item["category"] not in {"price_policy", "interior_color"} or item["status"] != "confirmed":
            continue
        for key, value in item.get("review_signals", {}).get("quote_components", {}).items():
            combined[key] = combined[key] or bool(value)
    return {"components": combined, "complete": all(combined.values())}


def load_transcription_audit(path: Path) -> dict:
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("schema_version") != TRANSCRIPTION_AUDIT_SCHEMA:
        raise ValueError("Unsupported or missing transcription audit schema")
    return audit


def build_audit(transcript: Path, candidates: list[dict], transcription_audit: dict | None = None) -> dict:
    counts = {category: sum(item["category"] == category for item in candidates) for category in REQUIRED_CATEGORIES}
    coverage = {}
    for category, count in counts.items():
        states = {item["status"] for item in candidates if item["category"] == category}
        coverage[category] = {
            "candidate_count": count,
            "status": "scanned_no_candidates" if count == 0 else ("reviewed" if states == {"confirmed"} else "attention_required"),
        }
    coverage["negative_incentive"] = {"candidate_count": 0, "status": "derived_by_score_validator"}
    audit = {
        "rule_version": RULE_VERSION,
        "price_policy_version": PRICE_POLICY_VERSION,
        "source_transcript": str(transcript),
        "review_model": HIGH_PRECISION_MODEL,
        "coverage": coverage,
        "derived": {"quote_completeness": derive_quote_completeness(candidates)},
        "candidates": candidates,
    }
    if transcription_audit is not None:
        audit["transcription_route"] = transcription_audit
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and high-precision review high-impact scoring evidence")
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--transcription-audit", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--transcriber", required=True, type=Path)
    parser.add_argument("--context-seconds", type=int, default=12)
    args = parser.parse_args()

    records = load_jsonl(args.transcript)
    transcription_audit = load_transcription_audit(args.transcription_audit) if args.transcription_audit else None
    candidates = build_candidates(records, context_ticks=max(3, args.context_seconds) * 100)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    clips = args.out_dir / "clips"
    reviews = args.out_dir / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)

    for item in candidates:
        clip = clips / f"{item['id']}_{item['category']}.wav"
        review_jsonl = reviews / f"{item['id']}.jsonl"
        write_wav_slice(args.audio, clip, item["start_ticks"], item["end_ticks"])
        item["audio_clip"] = str(clip)
        result = run_review(args.transcriber, clip, review_jsonl)
        if result.returncode != 0:
            item["status"] = "review_failed"
            item["rationale"] = "局部高精度转写失败，必须人工回听"
            item["review_log_tail"] = result.stdout[-2000:]
            continue
        review_records = load_jsonl(review_jsonl)
        review_text = " ".join(row["text"] for row in review_records if row["text"]).strip()
        status, rationale, initial_signals, review_signals = compare_signals(item["category"], item["initial_transcript"], review_text)
        item["review_transcript"] = review_text
        item["initial_signals"] = initial_signals
        item["review_signals"] = review_signals
        item["status"] = status
        item["rationale"] = rationale
        item["adopted_conclusion"] = review_text if status == "confirmed" else ""

    audit = build_audit(args.transcript, candidates, transcription_audit)
    output = args.out_dir / "evidence-audit.json"
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    unresolved = sum(item["status"] != "confirmed" for item in candidates)
    print(f"AUDIT candidates={len(candidates)} unresolved={unresolved} output={output}")
    if unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
