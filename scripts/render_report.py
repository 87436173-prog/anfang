#!/usr/bin/env python3
"""Generate auditable PNG and XLSX reports from a 6.0-G scoring job JSON."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def pick_font(bold=False):
    candidates = ([r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"] if bold else
                  [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"])
    candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    return next((p for p in candidates if Path(p).exists()), None)


def font(size, bold=False):
    path = pick_font(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def wrap(draw, text, fnt, width):
    lines, current = [], ""
    for ch in str(text):
        trial = current + ch
        if current and draw.textlength(trial, font=fnt) > width:
            lines.append(current); current = ch
        else:
            current = trial
    if current: lines.append(current)
    return lines


def calculate(job):
    modules = job["modules"]
    na = float(job.get("na", 0))
    applicable_max = sum(float(x[1]) for x in modules)
    if abs(applicable_max - (100 - na)) > 1e-9:
        raise ValueError(f"模块适用满分合计{applicable_max:g}必须等于100-NA={100-na:g}")
    module_base = sum(float(x[2]) for x in modules)
    base = float(job["base"])
    if abs(module_base - base) > 1e-9:
        raise ValueError(f"模块实得合计{module_base:g}与base {base:g}不一致")
    bonus = float(job.get("bonus", 0))
    if not 0 <= na < 100: raise ValueError("NA必须在0到100之间")
    raw = min(100.0, base / (100.0 - na) * 100.0 + bonus)
    score = math.floor(raw + 1e-9)
    penalty = ("负激励8万元折让/家/次" if score == 0 else
               "负激励5万元折让/家" if score < 60 else
               "负激励2万元折让/家" if score < 70 else "无负激励")
    return score, raw, penalty


def render(job, out_dir):
    score, raw, penalty = calculate(job)
    out_dir.mkdir(parents=True, exist_ok=True)
    W, H = 1600, 2100
    im = Image.new("RGB", (W, H), "#F4F7FB"); d = ImageDraw.Draw(im)
    def txt(x, y, value, size=25, color="#263248", bold=False):
        d.text((x, y), str(value), font=font(size, bold), fill=color)
    def card(box, fill="white", outline=None):
        d.rounded_rectangle(box, 22, fill=fill, outline=outline, width=2)
    d.rectangle((0, 0, W, 285), fill="#123A70")
    txt(70, 50, "王朝网销售服务品质6.0-G", 38, "white", True)
    txt(70, 110, "暗访录音评分报告", 58, "white", True)
    txt(70, 205, f"销售：{job['sales']}　客户：{job['customer']}　车型：{job['car']}　录音：{job['duration']}", 24, "#D8E8FF")
    card((65, 320, 590, 570)); txt(105, 355, "最终得分", 28, "#637087", True); txt(105, 415, score, 96, "#123A70", True); txt(420, 495, "分", 30, "#123A70", True)
    card((620, 320, 1535, 570)); txt(665, 355, "考核结论", 28, "#637087", True); txt(665, 425, penalty, 45, "#15966B" if score >= 70 else "#D9534F", True)
    txt(65, 625, "一、模块得分", 34, "#123A70", True); card((65, 680, 1535, 940))
    for i, (name, maximum, got) in enumerate(job["modules"]):
        x = 95 + i * 204; txt(x, 720, name, 22, "#4E5B70", True); txt(x, 765, f"{got}/{maximum}", 31, "#123A70", True)
    txt(100, 875, f"基础实得 {job['base']}　｜　NA {job.get('na', 0)}　｜　加分 {job.get('bonus', 0)}", 24, "#627087")
    card((65, 980, 1535, 1135), "#FFF1E8", "#F1B27B"); txt(105, 1015, "静态讲解专项", 29, "#A24C14", True)
    for i, line in enumerate(wrap(d, job.get("static", ""), font(21), 1360)[:3]): txt(105, 1062 + i * 27, line, 21, "#71452C")
    txt(65, 1175, "二、主要扣分点", 34, "#123A70", True); card((65, 1230, 1535, 1660)); y = 1260
    for title, reason in job.get("deductions", [])[:7]:
        txt(105, y, "●", 20, "#E16666"); txt(140, y, title, 22, "#263248", True)
        for j, line in enumerate(wrap(d, reason, font(20), 900)[:2]): txt(485, y + j * 25, line, 20, "#5D687A")
        y += 56
    txt(65, 1710, "三、服务亮点", 34, "#123A70", True); card((65, 1765, 1535, 1990)); y = 1795
    for item in job.get("highlights", [])[:5]: txt(105, y, "●", 20, "#15966B"); txt(145, y, item, 21, "#3E4A5F"); y += 38
    txt(65, 2035, f"计算：{job['base']} ÷ (100 − {job.get('na', 0)}) × 100 + {job.get('bonus', 0)} = {raw:.2f}，整数记分 {score}", 21, "#748197")
    png = out_dir / f"{job['slug']}_6.0-G暗访评分.png"; im.save(png)

    wb = Workbook(); ws = wb.active; ws.title = "逐项得分证据"
    ws.append([f"{job['sales']} × {job['customer']}　{job['car']}　最终{score}分　{penalty}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)
    ws.append(["模块", "小项", "名称", "满分", "得分/NA", "时间戳", "证据/判定"])
    for row in job.get("rows", []): ws.append(row)
    ws.freeze_panes = "A3"; widths = [10, 12, 18, 10, 12, 18, 58]
    for i, width in enumerate(widths, 1): ws.column_dimensions[chr(64+i)].width = width
    ws["A1"].font = Font(name="Microsoft YaHei", size=16, bold=True, color="FFFFFF"); ws["A1"].fill = PatternFill("solid", fgColor="123A70")
    for c in ws[2]: c.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="2D5D92")
    for row in ws.iter_rows():
        for c in row: c.alignment = Alignment(vertical="top", wrap_text=True)
    xlsx = out_dir / f"{job['slug']}_逐项得分证据.xlsx"; wb.save(xlsx)
    return png, xlsx, score, penalty


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding="utf-8-sig"))
    for value in render(job, args.out_dir): print(value)
