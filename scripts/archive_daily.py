#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把暗访评分报告归档到统一目录，并按日期生成汇总表。

用法：
    python tools/archive_daily.py                   # 全量重建（推荐，幂等）
    python tools/archive_daily.py --date 2026-11-14  # 只重建某一天

规则：
- 新单按 PNG 出图日期归档；已归档过的单**不移动**，只原地更新图片与所属日汇总，
  避免重算/重渲染把历史单从旧日期文件夹拖到新日期。
- 每个日期目录内：全部 PNG + 打分汇总_YYYY-MM-DD.md/.csv。
- 幂等：重复执行只覆盖，不产生重复文件。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
from pathlib import Path

ROOT = Path(os.environ.get("BYD_SCORING_ROOT") or r"C:/Users/no02/WorkBuddy/2026-11-10-09-14-36")
JOBS = ROOT / "jobs"
OUT_BASE = ROOT / "暗访打分日报"


def grade(score: float) -> str:
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "合格"
    if score >= 70:
        return "达标"
    if score >= 60:
        return "负激励2万"
    if score > 0:
        return "负激励5万"
    return "负激励8万"


def incentive(score: float, field) -> str:
    """负激励以分数为准，job 里历史字段可能为空。"""
    if field:
        return str(field)
    if score >= 70:
        return "无"
    if score >= 60:
        return "2万"
    if score > 0:
        return "5万"
    return "8万"


def existing_homes() -> dict[str, str]:
    """已归档的 PNG 文件名 -> 日期目录名。"""
    homes: dict[str, str] = {}
    if not OUT_BASE.exists():
        return homes
    for day_dir in OUT_BASE.iterdir():
        if not day_dir.is_dir():
            continue
        for png in day_dir.glob("*.png"):
            homes.setdefault(png.name, day_dir.name)
    return homes


def all_rows() -> list[dict]:
    homes = existing_homes()
    rows: list[dict] = []
    for job_path in sorted(JOBS.glob("*/job.json")):
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pngs = sorted((job_path.parent / "report").glob("*.png"))
        if not pngs:
            continue
        png = pngs[0]
        stamp = dt.date.fromtimestamp(png.stat().st_mtime).isoformat()
        # 归档键统一用接待日期：重渲染不会把历史单搬到新日期目录，管理者按接待日查看
        rec = str(job.get("reception_date") or "").strip()
        home = rec if len(rec) == 10 and rec[4] == "-" else homes.get(png.name, stamp)
        score = float(job.get("final_score") or 0)
        rows.append(
            {
                "日期": home,
                "销售": job.get("sales", ""),
                "客户": job.get("customer", ""),
                "接待日期": str(job.get("reception_date") or ""),
                "总分": job.get("final_score"),
                "基础实得": job.get("base"),
                "NA": job.get("na"),
                "加分": job.get("bonus", 0),
                "档位": grade(score),
                "负激励": incentive(score, job.get("negative_incentive")),
                "报告文件": png.name,
                "源目录": job_path.parent.name,
                "PNG": png,
            }
        )
    return rows


def write_day(day: str, rows: list[dict]) -> Path:
    out_dir = OUT_BASE / day
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = {r["报告文件"] for r in rows}
    for old in out_dir.glob("*.png"):
        if old.name not in keep:
            old.unlink()
    for r in rows:
        shutil.copy2(r["PNG"], out_dir / r["报告文件"])

    fields = ["日期", "销售", "客户", "接待日期", "总分", "基础实得", "NA", "加分", "档位", "负激励", "报告文件"]
    with (out_dir / f"打分汇总_{day}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    scores = [float(r["总分"] or 0) for r in rows]
    avg = sum(scores) / len(scores) if scores else 0.0
    lines = [
        f"# 暗访打分汇总 {day}",
        "",
        f"- 接待单数：**{len(rows)}**",
        f"- 平均分：**{avg:.1f}**" if rows else "- 平均分：—",
        f"- 最高分：{max(scores):g}" if scores else "- 最高分：—",
        f"- 最低分：{min(scores):g}" if scores else "- 最低分：—",
        f"- 负激励单数：{sum(1 for r in rows if r['负激励'] != '无')}",
        "",
    ]
    if rows:
        lines += [
            "| 销售 | 客户 | 接待日期 | 总分 | 基础/NA/加分 | 档位 | 负激励 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| {r['销售']} | {r['客户']} | {r['接待日期']} | **{r['总分']}** | "
                f"{r['基础实得']}/{r['NA']}/{r['加分']} | {r['档位']} | {r['负激励']} |"
            )
    else:
        lines.append("当日无新增打分记录。")
    (out_dir / f"打分汇总_{day}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="只重建指定日期（默认全量重建）")
    args = ap.parse_args()

    rows = all_rows()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["日期"], []).append(r)
    if args.date:
        grouped = {args.date: grouped.get(args.date, [])}
    for day in sorted(grouped):
        subset = sorted(grouped[day], key=lambda r: (-float(r["总分"] or 0), r["销售"]))
        out_dir = write_day(day, subset)
        print(f"ARCHIVED {len(subset)} -> {out_dir}")
        for r in subset:
            print(f"  {r['总分']:>4}  {r['销售']:<6} {r['客户'][:20]}")

    # 清理不再对应任何接待日的旧目录（只删本脚本生成的 PNG 与汇总表）
    for day_dir in sorted(OUT_BASE.iterdir()):
        if not day_dir.is_dir() or day_dir.name in grouped:
            continue
        for png in day_dir.glob("*.png"):
            png.unlink()
        for f in list(day_dir.glob("打分汇总_*.csv")) + list(day_dir.glob("打分汇总_*.md")):
            f.unlink()
        if not any(day_dir.iterdir()):
            day_dir.rmdir()
            print(f"CLEANED empty {day_dir}")


if __name__ == "__main__":
    main()
