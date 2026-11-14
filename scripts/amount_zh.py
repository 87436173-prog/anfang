#!/usr/bin/env python3
"""中文金额换算与价格提及统计（配套 Dolphin 主转写）。

背景：Dolphin-CN-Dialect 把金额输出为中文数字（「十二万九千九」「五万零八百」），
阿拉伯数字金额命中数为 0。若沿用 \\d{5,} 类正则，E2 报价项会整体漏采；
若直接把中文数字当文本用，又无法与备案价比对。本脚本做两件事：

1) 换算模式：从转写中抽出中文金额并换算为整数元，附时间戳与原文，
   换算不确定（如「七万零九八」「五万八二十四」这类粘连表达）时给出歧义标记，
   提示必须回听确认后才能写进 job。
2) 统计模式（默认）：分别统计阿拉伯数字与中文数字两种表达形态的出现次数，
   用于模型对照，避免把「表达形态差异」误读成「漏采」。

用法：
    python amount_zh.py --extract <转写.jsonl|transcript.json>     # 换算并列出
    python amount_zh.py [jobid ...]                                # 统计（默认）
    python amount_zh.py --check "十二万九千九"                      # 单串自测

注意：换算结果只是候选，报告里的金额必须回听原音确认，并标注时间戳。
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BYD_SCORING_ROOT") or r"C:/Users/no02/WorkBuddy/2026-11-10-09-14-36")

DIGIT = re.compile(r"\d{1,3}\.\d万|\d{2,4}万|\d{4,6}元")
# 中文数字金额：「十二万九千八」「九万九千八」「五千」「一万二」「十八万」
ZH = re.compile(
    r"[零一二三四五六七八九十百千万两]{2,}(?:元|块|万|千|百)"
    r"|[零一二三四五六七八九十]{1,3}万[零一二三四五六七八九十百千]{0,4}"
)

NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
       "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNIT = {"十": 10, "百": 100, "千": 1000}
ORDER = {"十": 1, "百": 2, "千": 3}


def _seg(s):
    """解析一段不含「万」的中文数字，返回 (值, 尾数字, 末单位, 是否含零, 是否粘连)。

    粘连指两个数字字符之间没有单位（「九八」「八二四」），属转写不规范或口误，
    一律交回听，不猜值。
    """
    total = 0
    num = None
    last = None
    ling = False
    dirty = False
    for ch in s:
        if ch == "零":
            ling = True
            continue
        if ch in NUM:
            if num is not None:
                dirty = True
            num = NUM[ch]
        elif ch in UNIT:
            if last is not None and ORDER[ch] >= ORDER[last]:
                dirty = True  # 单位不递减，如「十千」
            total += (1 if num is None else num) * UNIT[ch]
            num = None
            last = ch
        else:
            return None
    return total, num, last, ling, dirty


def _seg_val(s):
    """段值。末尾单独数字按省略单位处理（「九千九」=9900，「十二」=12）。"""
    r = _seg(s)
    if r is None:
        return None
    total, num, last, ling, dirty = r
    if dirty:
        return None
    if num is None:
        return total
    if last is None:
        return None if ling else num
    return total + num * (UNIT[last] // 10)


def zh_amount(s):
    """中文金额串 → (整数元, 歧义说明或None)。无法确定时值为 None。"""
    s = (s or "").strip().replace("元", "").replace("块", "")
    if not s:
        return None, "空串"
    if "万" in s:
        a, b = s.split("万", 1)
        if a and a[0] in "千百":
            return None, f"「{a}万」缺前导数字，疑为销量/数量语义而非金额"
        va = _seg_val(a) if a else 1
        if va is None:
            return None, f"「{a}万」前段无法解析"
        if not b:
            return va * 10000, None
        core = b.lstrip("零")
        if not core:
            return va * 10000, None
        if len(core) == 1 and core in NUM:
            return va * 10000 + NUM[core] * 1000, None  # 「一万二」=12000
        vb = _seg_val(core)
        if vb is None:
            return None, f"万后段「{b}」粘连或表达不规范，须回听"
        return va * 10000 + vb, None
    v = _seg_val(s)
    if v is None:
        return None, f"「{s}」无法确定，须回听"
    return v, None


def load(p):
    out = []
    p = Path(p)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def texts(rows):
    return "".join(r.get("text") or "" for r in rows)


def extract(path):
    rows = load(path)
    hits = []
    for r in rows:
        t = r.get("text") or ""
        t0 = int(r.get("t0") or 0)
        for m in ZH.finditer(t):
            raw = m.group(0)
            val, why = zh_amount(raw)
            if val is not None and val > 2_000_000:
                why = f"{val:,} 超出车辆金额常见区间，疑为销量/数量"
            hits.append({
                "sec": t0 // 100,
                "raw": raw,
                "yuan": val,
                "flag": why,
                "ctx": t[max(0, m.start() - 12): m.end() + 12],
            })
    for h in hits:
        ts = f"{h['sec']//60:02d}:{h['sec']%60:02d}"
        val = f"{h['yuan']:>9,}" if h["yuan"] is not None else "     ???? "
        flag = "" if h["flag"] is None else f"  [{h['flag']}]"
        print(f"{ts} {h['raw']:<12}{val}{flag}   {h['ctx']}")
    ok = sum(1 for h in hits if h["yuan"] is not None)
    print(f"\n共 {len(hits)} 处中文金额，可换算 {ok} 处，需回听 {len(hits)-ok} 处")
    return hits


def stats(ids):
    print(f"{'job':34}{'W数字':>7}{'W中文':>7}{'D数字':>7}{'D中文':>7}")
    rows_out = []
    jobs = ROOT / "jobs"
    if not jobs.exists():
        print("未找到 jobs 目录")
        return
    for jd in sorted(jobs.iterdir()):
        if ids and not any(i in jd.name for i in ids):
            continue
        w = texts(load(jd / "transcript.json"))
        d = texts(load(jd / "dolphin.jsonl"))
        if not w and not d:
            continue
        r = {
            "job": jd.name,
            "w_digit": len(DIGIT.findall(w)),
            "w_zh": len(ZH.findall(w)),
            "d_digit": len(DIGIT.findall(d)),
            "d_zh": len(ZH.findall(d)),
        }
        rows_out.append(r)
        print(f"{jd.name[:33]:34}{r['w_digit']:>7}{r['w_zh']:>7}{r['d_digit']:>7}{r['d_zh']:>7}")
    out = ROOT / "report" / "price_zh_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows_out, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    a = sys.argv[1:]
    if a and a[0] == "--extract":
        if len(a) < 2:
            print("用法：amount_zh.py --extract <转写文件>")
            return
        extract(a[1])
        return
    if a and a[0] == "--check":
        for s in a[1:]:
            v, why = zh_amount(s)
            print(f"{s:<14}{v if v is not None else '????':<12}{why or ''}")
        return
    stats(a)


if __name__ == "__main__":
    main()
