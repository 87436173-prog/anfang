#!/usr/bin/env python3
"""Generate deterministic, auditable PNG reports for BYD 6.0-G."""

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from starbucks_review import validate_fields as validate_starbucks_fields
from trial_assessment import report_lines as trial_report_lines
from feedback_policy import VERSION as WORKFLOW_VERSION
from service_policy import deduction_details,module_segments,active as service_active,VERSION as SERVICE_VERSION
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


NAVY = "#123A70"
TEAL = "#117C88"
GREEN = "#15966B"
ORANGE = "#D8792C"
DEFAULT_YELLOW = "#EDC348"
RED = "#D95454"
BLUE = "#2D68A2"
TEXT = "#263248"
MUTED = "#647187"
BG = "#F2F5F9"
WHITE = "#FFFFFF"


def pick_font(bold=False):
    candidates = (
        [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"]
        if bold
        else [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"]
    )
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    ]
    return next((item for item in candidates if Path(item).exists()), None)


def make_font(size, bold=False):
    path = pick_font(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def wrap(draw, value, fnt, width):
    """Wrap mixed Chinese/Latin text by measured pixel width."""
    paragraphs = str(value or "").splitlines() or [""]
    result = []
    for paragraph in paragraphs:
        if not paragraph:
            result.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if current and draw.textlength(trial, font=fnt) > width:
                result.append(current)
                current = char
            else:
                current = trial
        if current:
            result.append(current)
    return result


def calculate(job):
    modules = job["modules"]
    na = float(job.get("na", 0))
    if not 0 <= na < 100:
        raise ValueError("NA必须在0到100之间")

    applicable_max = sum(float(item[1]) for item in modules)
    expected_max = 100 - na
    if abs(applicable_max - expected_max) > 1e-9:
        raise ValueError(
            f"模块适用满分合计{applicable_max:g}必须等于100-NA={expected_max:g}"
        )

    module_base = sum(float(item[2]) for item in modules)
    base = float(job["base"])
    if abs(module_base - base) > 1e-9:
        raise ValueError(f"模块实得合计{module_base:g}与base {base:g}不一致")

    bonus = float(job.get("bonus", 0))
    raw = min(100.0, base / expected_max * 100.0 + bonus)
    score = math.floor(raw + 1e-9)
    if score == 0:
        penalty = "负激励：8万元折让/家/次"
    elif score < 60:
        penalty = "负激励：5万元折让/家"
    elif score < 70:
        penalty = "负激励：2万元折让/家"
    else:
        penalty = "无负激励"
    return score, raw, penalty


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def require_text(container, key, label):
    value = container.get(key) if isinstance(container, dict) else None
    if value is None or not str(value).strip():
        raise ValueError(f"缺少必填字段：{label}")
    return str(value).strip()


def normalized_model(value):
    text = str(value or "").lower()
    for token in (" ", "-", "_", "·", "—"):
        text = text.replace(token, "")
    return text


def validate_review_fields(job):
    starbucks_errors = validate_starbucks_fields(job)
    if starbucks_errors:
        raise ValueError("; ".join(starbucks_errors))
    models = job.get("models_of_interest")
    if not isinstance(models, dict):
        raise ValueError("models_of_interest必须是对象")
    require_text(models, "primary", "models_of_interest.primary")
    require_text(models, "evidence", "models_of_interest.evidence")
    for key in ("own_brand", "competitors"):
        value = models.get(key)
        if not isinstance(value, list) or (key=="own_brand" and not value) or any(not str(item).strip() for item in value):
            raise ValueError(f"models_of_interest.{key}必须是非空列表")

    intention = job.get("intention")
    if not isinstance(intention, dict):
        raise ValueError("intention必须是对象")
    level = require_text(intention, "level", "intention.level").upper()
    if level not in {"H", "A", "B", "C", "D", "待核实"}:
        raise ValueError("intention.level只允许H/A/B/C/D/待核实")
    require_text(intention, "reason", "intention.reason")
    require_text(intention, "evidence", "intention.evidence")

    strict = job.get("strict_control")
    if not isinstance(strict, dict):
        raise ValueError("strict_control必须是对象")
    status = require_text(strict, "status", "strict_control.status")
    if status not in {"是", "否", "待核实"}:
        raise ValueError("strict_control.status只允许是/否/待核实")
    if status == "是":
        for key in ("series", "trim", "filed_price", "policy_basis"):
            require_text(strict, key, f"strict_control.{key}")

    strict_tokens = (
        "秦maxdmi", "秦maxev", "宋prodmi飞驰版", "宋ultraev", "宋ultradmi",
        "元up", "第三代元plus", "汉ev闪充版", "大唐ev",
    )
    own_models = [normalized_model(item) for item in models["own_brand"]]
    # 2027款元UP飞驰版为一般车型，旧智驾版仍严管。
    # 版本未明不能由车系关键词强迫成已确认严管，也不能判为否。
    detected = False
    unresolved_yuanup = False
    for item in own_models:
        if any(token in item for token in strict_tokens if token != "元up"):
            detected = True
        if "元up" not in item:
            continue
        flying_2027 = "2027" in item and "飞驰" in item
        version_unknown = any(marker in item for marker in (
            "版本未明", "版本不明", "版本待核", "版本未确认", "年款未明", "年款待核",
        )) or ("智驾" not in item and not flying_2027)
        if version_unknown:
            unresolved_yuanup = True
        elif not flying_2027:
            detected = True
    if detected and status != "是":
        raise ValueError("本品关注车型命中严管车系，strict_control.status必须为是")
    if unresolved_yuanup and status == "否":
        raise ValueError("元UP版本未明，strict_control.status须为待核实或是")
    if unresolved_yuanup and status == "待核实":
        for key in ("series", "trim", "filed_price", "policy_basis"):
            require_text(strict, key, f"strict_control.{key}")

    compliance = job.get("compliance")
    if not isinstance(compliance, list):
        raise ValueError("compliance必须是列表；无问题时使用空列表")
    for index, item in enumerate(compliance, 1):
        if not isinstance(item, dict):
            raise ValueError(f"compliance第{index}项必须是对象")
        item_type = require_text(item, "type", f"compliance[{index}].type")
        if item_type not in {"违规", "风险", "待核实"}:
            raise ValueError(f"compliance第{index}项type只允许违规/风险/待核实")
        for key in ("timestamp", "quote", "ruling", "suggestion"):
            require_text(item, key, f"compliance[{index}].{key}")


def render_png(job, target, score, raw, penalty):
    width = 1600
    margin = 65
    inner = width - margin * 2
    scratch = Image.new("RGB", (width, 100), WHITE)
    measure = ImageDraw.Draw(scratch)

    models = job["models_of_interest"]
    intention = job["intention"]
    strict = job["strict_control"]
    own_models = "、".join(str(item) for item in models["own_brand"])
    competitors = "、".join(str(item) for item in models["competitors"]) or "未核到客户实际关注的竞品"
    strict_summary = f"{strict['status']}"
    if strict["status"] == "是":
        strict_summary += (
            f"｜{strict.get('series', '待核实')}｜{strict.get('trim', '待核实')}｜"
            f"备案成交价 {strict.get('filed_price', '待核实')}"
        )
    overview_values = [
        f"主关注车型：{models['primary']}",
        f"本品关注：{own_models}",
        f"竞品关注：{competitors}",
        f"客户意向：{intention['level']}级｜{intention['reason']}",
        f"意向证据：{intention['evidence']}",
        f"严管专项：{strict_summary}",
        f"车型证据：{models['evidence']}",
    ]
    overview_rows = [wrap(measure, item, make_font(21), inner - 110) for item in overview_values]

    compliance_rows = []
    for item in job["compliance"]:
        title = f"[{item['type']}] {item['timestamp']}｜{item['quote']}"
        detail = f"判定：{item['ruling']}  建议：{item['suggestion']}"
        compliance_rows.append(
            (
                item["type"],
                wrap(measure, title, make_font(22, True), inner - 110),
                wrap(measure, detail, make_font(20), inner - 110),
            )
        )

    static_lines = wrap(measure, job.get("static", "未提供"), make_font(22), inner - 90)
    deduction_rows = []
    for item in deduction_details(job):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            title, reason = item[0], item[1]
        else:
            title, reason = str(item), ""
        reason_lines = wrap(measure, reason, make_font(21), inner - 310)
        deduction_rows.append((str(title), reason_lines or [""]))
    highlight_rows = [wrap(measure, item, make_font(21), inner - 110) for item in as_list(job.get("highlights"))]
    improvement_rows = [wrap(measure, item, make_font(21), inner - 110) for item in as_list(job.get("improvements"))]
    default_values = as_list(job.get("defaults")) + trial_report_lines(job)
    default_rows = [wrap(measure, item, make_font(21), inner - 110) for item in default_values]

    starbucks = job.get("starbucks_introduction")
    starbucks_text = starbucks["evidence"] if starbucks else ""
    if starbucks and service_active(job):
        status_names = {"confirmed":"已确认", "not_confirmed":"未确认", "pending":"待核实"}
        service = job.get("starbucks_service", {})
        for key, label in (("provided","实际提供"),("consumed","实际饮用")):
            item=service.get(key,{})
            starbucks_text += "\n"+label+"："+status_names.get(item.get("status"),"待核实")+"｜"+str(item.get("evidence",""))
    starbucks_lines = wrap(measure, starbucks_text, make_font(21), inner - 100) if starbucks else []
    starbucks_height = 152 + len(starbucks_lines) * 28 if starbucks else 0
    starbucks_space = starbucks_height + 38 if starbucks else 0
    trial_lines = [line for item in trial_report_lines(job) for line in wrap(measure, item, make_font(21), inner - 100)]
    trial_height = 100 + 28 * len(trial_lines) if trial_lines else 0
    trial_space = trial_height + 38 if trial_lines else 0

    overview_height = 82 + sum(max(36, len(lines) * 28) for lines in overview_rows) + 28
    compliance_height = 82 + sum(
        max(82, len(title_lines) * 29 + len(detail_lines) * 27 + 24)
        for _, title_lines, detail_lines in compliance_rows
    ) + 28
    if not compliance_rows:
        compliance_height = 150
    module_height = 105 + max(1, len(job["modules"])) * 61 + 120
    static_height = 82 + max(1, len(static_lines)) * 31 + 34
    deduction_height = 82 + sum(max(76, len(lines) * 27 + 52) for _, lines in deduction_rows) + 25
    if not deduction_rows:
        deduction_height = 155
    highlight_height = 82 + sum(max(39, len(lines) * 28) for lines in highlight_rows) + 25
    if not highlight_rows:
        highlight_height = 145
    improvement_height = 82 + sum(max(39, len(lines) * 28) for lines in improvement_rows) + 25
    if not improvement_rows:
        improvement_height = 145
    defaults_height = 82 + sum(max(39, len(lines) * 28) for lines in default_rows) + 30
    if not default_rows:
        defaults_height = 145

    header_lines=wrap(measure, f"销售：{job.get('sales','待核实')}    客户：{job.get('customer','待核实')}    车型：{job.get('car','待核实')}    录音：{job.get('duration','待核实')}",make_font(23),inner)
    header_height=max(285,207+len(header_lines)*32+35)
    total_height = (
        header_height + 35 + 255 + 55 + overview_height + 38 + compliance_height + 38
        + module_height + 38 + static_height + 38
        + deduction_height + 38 + highlight_height + 38 + improvement_height
        + 38 + defaults_height + 115 + starbucks_space + trial_space
    )
    image = Image.new("RGB", (width, total_height), BG)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=25, color=TEXT, bold=False, anchor=None):
        draw.text((x, y), str(value), font=make_font(size, bold), fill=color, anchor=anchor)

    def card(box, fill=WHITE, outline=None, radius=20, line_width=2):
        draw.rounded_rectangle(box, radius, fill=fill, outline=outline, width=line_width)

    def section_title(y, number, title, color):
        card((margin, y, margin + 62, y + 54), color, radius=14)
        text(margin + 31, y + 27, number, 25, WHITE, True, "mm")
        text(margin + 82, y + 8, title, 33, color, True)
        return y + 72

    def bullets(y, rows, color, empty_text):
        if not rows:
            text(margin + 48, y, empty_text, 21, MUTED)
            return y + 40
        for lines in rows:
            text(margin + 42, y + 2, "●", 17, color)
            for index, line in enumerate(lines):
                text(margin + 78, y + index * 28, line, 21, TEXT)
            y += max(39, len(lines) * 28)
        return y

    # Header
    draw.rectangle((0, 0, width, header_height), fill=NAVY)
    text(margin, 45, "王朝网销售服务品质 6.0-G", 38, WHITE, True)
    text(margin, 108, "暗访录音评分报告", 58, WHITE, True)
    meta = (
        f"销售：{job.get('sales', '待核实')}    客户：{job.get('customer', '待核实')}    "
        f"车型：{job.get('car', '待核实')}    录音：{job.get('duration', '待核实')}"
    )
    for index,line in enumerate(header_lines):
        text(margin,207+index*32,line,23,"#D8E8FF")
    if job.get("report_date"):
        text(width - margin, 64, f"报告日期  {job['report_date']}", 21, "#D8E8FF", False, "ra")
    if job.get("rule_version"):
        text(width - margin, 102, f"规则版本  {job['rule_version']}", 18, "#B9D3F4", False, "ra")

    y = header_height + 35
    # Result and composition cards
    card((margin, y, 590, y + 255), "#EAF8F2", "#B9E5D3")
    text(margin + 42, y + 31, "最终得分", 27, GREEN, True)
    text(margin + 44, y + 78, score, 104, NAVY, True)
    text(margin + 286, y + 165, "分", 32, NAVY, True)
    text(margin + 42, y + 211, penalty, 23, GREEN if score >= 70 else RED, True)

    card((620, y, width - margin, y + 255))
    text(665, y + 31, "计分构成", 27, NAVY, True)
    labels = [
        ("基础实得", f"{float(job['base']):g}"),
        ("NA分值", f"{float(job.get('na', 0)):g}"),
        ("加分", f"{float(job.get('bonus', 0)):g}"),
        ("折算结果", f"{raw:.2f}"),
    ]
    for index, (label, value) in enumerate(labels):
        col = index % 2
        row = index // 2
        x = 665 + col * 415
        yy = y + 84 + row * 73
        text(x, yy, label, 20, MUTED)
        text(x + 175, yy - 6, value, 30, NAVY, True)
    text(665, y + 218, "最终分按封顶后的折算结果向下取整", 19, MUTED)

    y += 310
    if starbucks:
        status = starbucks["status"]
        color = GREEN if status == "已介绍" else RED if status == "未介绍" else ORANGE
        fill = "#F2FBF7" if status == "已介绍" else "#FFF1F1" if status == "未介绍" else "#FFF8EA"
        card((margin, y, width - margin, y + starbucks_height), fill, color, line_width=3)
        text(margin + 40, y + 22, "星巴克介绍专项｜是否向客户介绍本店星巴克", 27, NAVY, True)
        label = "已介绍" if status == "已介绍" else "警告：未介绍（录音未核验到明确介绍）" if status == "未介绍" else "待核实：介绍证据含混"
        text(margin + 40, y + 66, label, 30, color, True)
        for index, line in enumerate(starbucks_lines):
            text(margin + 40, y + 111 + index * 28, line, 21, TEXT)
        text(margin + 40, y + starbucks_height - 31, "明确介绍星巴克可加3分；提供与饮用分别记录，不重复加分。" if service_active(job) else "本项为独立提示；介绍、提供与实际饮用分别核验，不直接改变得分。", 18, MUTED)
        y += starbucks_space
    if trial_lines:
        card((margin, y, width - margin, y + trial_height), "#FFF8EA", ORANGE, line_width=3)
        text(margin + 40, y + 22, "D试驾口径｜语义推断", 27, NAVY, True)
        for index, line in enumerate(trial_lines):
            text(margin + 40, y + 68 + index * 28, line, 21, TEXT)
        y += trial_space
    # Customer models, intention and strict-control overview
    content_y = section_title(y, "01", "关注车型、客户意向与严管状态", NAVY)
    card((margin, content_y, width - margin, content_y + overview_height - 72), "#F5F8FC", "#C7D5E5")
    row_y = content_y + 28
    for lines in overview_rows:
        text(margin + 42, row_y + 2, "●", 17, NAVY)
        for index, line in enumerate(lines):
            text(margin + 78, row_y + index * 28, line, 21, TEXT, index == 0 and ("主关注车型" in line or "客户意向" in line or "严管专项" in line))
        row_y += max(36, len(lines) * 28)
    y = content_y + overview_height - 72 + 38

    # Price and benefit compliance review
    has_violation = any(item_type == "违规" for item_type, _, _ in compliance_rows)
    compliance_color = RED if has_violation else ORANGE
    content_y = section_title(y, "02", "价格、金融与赠送话术审查", compliance_color)
    card((margin, content_y, width - margin, content_y + compliance_height - 72), "#FFF8F4", "#F1C8AE")
    row_y = content_y + 28
    if not compliance_rows:
        text(margin + 45, row_y, "未发现明确违规/风险话术", 22, GREEN, True)
    for item_type, title_lines, detail_lines in compliance_rows:
        marker_color = RED if item_type == "违规" else ORANGE if item_type == "风险" else MUTED
        text(margin + 42, row_y + 2, "●", 17, marker_color)
        for index, line in enumerate(title_lines):
            text(margin + 78, row_y + index * 29, line, 22, marker_color, True)
        detail_y = row_y + len(title_lines) * 29 + 4
        for index, line in enumerate(detail_lines):
            text(margin + 78, detail_y + index * 27, line, 20, "#596578")
        row_y += max(82, len(title_lines) * 29 + len(detail_lines) * 27 + 24)
    y = content_y + compliance_height - 72 + 38

    # Modules
    content_y = section_title(y, "03", "A–G 模块得分", TEAL)
    card((margin, content_y, width - margin, content_y + module_height - 72))
    text(margin + 42, content_y + 27, "模块", 21, MUTED, True)
    text(margin + 590, content_y + 27, "得分", 21, MUTED, True)
    text(margin + 780, content_y + 27, "完成度", 21, MUTED, True)
    row_y = content_y + 76
    for name, maximum, got in job["modules"]:
        maximum_value = float(maximum)
        got_value = float(got)
        ratio = 0 if maximum_value <= 0 else max(0, min(1, got_value / maximum_value))
        text(margin + 42, row_y, name, 22, TEXT, True)
        text(margin + 590, row_y, f"{got_value:g} / {maximum_value:g}", 22, NAVY, True)
        bar_left, bar_top, bar_right = margin + 780, row_y + 5, width - margin - 130
        draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_top + 18), 9, fill="#DCE5EC")
        segments = module_segments(job, str(name)[0], maximum_value, got_value)
        if ratio > 0:
            draw.rounded_rectangle((bar_left, bar_top, bar_left + (bar_right - bar_left) * ratio, bar_top + 18), 9, fill=TEAL)
        if maximum_value > 0 and segments["default_deduction"] > 0:
            yellow_left = bar_left + (bar_right - bar_left) * ratio
            yellow_right = min(bar_right, yellow_left + (bar_right - bar_left) * segments["default_deduction"] / maximum_value)
            draw.rectangle((yellow_left, bar_top, yellow_right, bar_top + 18), fill=DEFAULT_YELLOW)
        text(width - margin - 45, row_y - 3, f"{ratio * 100:.0f}%", 18, MUTED, False, "ra")
        row_y += 61
    draw.line((margin + 40, row_y + 4, width - margin - 40, row_y + 4), fill="#DFE6ED", width=2)
    text(margin + 42, row_y + 25, f"基础实得 {float(job['base']):g}  ·  NA {float(job.get('na', 0)):g}  ·  加分 {float(job.get('bonus', 0)):g}", 22, MUTED)
    if service_active(job):
        text(margin + 42, row_y + 60, "青色：实得分  ·  黄色：默认扣分  ·  灰色：其他未得分；黄色不计入得分", 18, MUTED)
    y = content_y + module_height - 72 + 38

    # Static explanation
    content_y = section_title(y, "04", "静态讲解专项", ORANGE)
    card((margin, content_y, width - margin, content_y + static_height - 72), "#FFF3E9", "#F0C59F")
    line_y = content_y + 34
    for line in static_lines or ["未提供"]:
        text(margin + 45, line_y, line, 22, "#70472E")
        line_y += 31
    y = content_y + static_height - 72 + 38

    # Deductions
    content_y = section_title(y, "05", "主要扣分点与证据", RED)
    card((margin, content_y, width - margin, content_y + deduction_height - 72), "#FFF7F7", "#F0C5C5")
    row_y = content_y + 30
    if not deduction_rows:
        text(margin + 45, row_y, "无需列示的非默认扣分项" if service_active(job) else "无扣分项", 21, MUTED)
    for title, lines in deduction_rows:
        text(margin + 42, row_y + 2, "●", 17, RED)
        for index,line in enumerate(wrap(draw,title,make_font(22,True),205)):
            text(margin + 78,row_y+index*26,line,22,TEXT,True)
        reason_x = margin + 78
        for index, line in enumerate(lines):
            text(reason_x, row_y + 35 + index * 27, line, 21, "#596578")
        row_y += max(76, len(lines) * 27 + 52)
    y = content_y + deduction_height - 72 + 38

    # Highlights
    content_y = section_title(y, "06", "服务亮点", GREEN)
    card((margin, content_y, width - margin, content_y + highlight_height - 72), "#F2FBF7", "#BFE3D3")
    bullets(content_y + 29, highlight_rows, GREEN, "暂无明确亮点")
    y = content_y + highlight_height - 72 + 38

    # Improvements
    content_y = section_title(y, "07", "改进建议", BLUE)
    card((margin, content_y, width - margin, content_y + improvement_height - 72), "#F3F8FD", "#BED3E8")
    bullets(content_y + 29, improvement_rows, BLUE, "请根据扣分项逐一复盘改进")
    y = content_y + improvement_height - 72 + 38

    # Defaults and formula
    content_y = section_title(y, "08", "默认项与计分说明", NAVY)
    card((margin, content_y, width - margin, content_y + defaults_height - 72), "#F7F8FA", "#D8DEE6")
    bullets(content_y + 29, default_rows, NAVY, "无额外默认项说明")
    y = content_y + defaults_height - 72 + 38
    formula = (
        f"计算：{float(job['base']):g} ÷ (100 − {float(job.get('na', 0)):g}) × 100 + "
        f"{float(job.get('bonus', 0)):g} = {raw:.2f}；封顶后向下取整，记 {score} 分"
    )
    text(margin, y + 4, formula, 21, MUTED)
    rule_version = job.get("rule_version", "6.0-G（历史任务）")
    policy_label = " · " + SERVICE_VERSION if service_active(job) else ""
    text(margin, y + 44, f"依据：{rule_version}{policy_label}及有效价格管控口径", 19, "#8792A3")

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)


def render_xlsx(job, target, score, raw, penalty):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "逐项得分证据"
    title = (
        f"{job.get('sales', '待核实')} × {job.get('customer', '待核实')}  "
        f"{job.get('car', '待核实')}  最终{score}分  {penalty}"
    )
    sheet.append([title])
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)
    sheet.append(["模块", "小项", "名称", "满分", "得分/NA", "时间戳", "证据/判定"])
    for row in job.get("rows", []):
        sheet.append(row)
    sheet.freeze_panes = "A3"
    widths = [10, 12, 22, 10, 12, 18, 64]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet["A1"].font = Font(name="Microsoft YaHei", size=16, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="123A70")
    for cell in sheet[2]:
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="117C88")
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0

    summary = workbook.create_sheet("计分汇总")
    summary.append(["项目", "数值"])
    summary.append(["基础实得", float(job["base"])])
    summary.append(["NA", float(job.get("na", 0))])
    summary.append(["加分", float(job.get("bonus", 0))])
    summary.append(["折算结果", raw])
    summary.append(["最终整数得分", score])
    summary.append(["负激励", penalty])
    for module, maximum, got in job["modules"]:
        summary.append([module, f"{float(got):g}/{float(maximum):g}"])
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 36
    for cell in summary[1]:
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="123A70")

    audit = workbook.create_sheet("客户与合规")
    audit.append(["客户关注与严管审查", "内容", "时间戳/依据", "判定/建议"])
    models = job["models_of_interest"]
    intention = job["intention"]
    strict = job["strict_control"]
    audit.append(["主关注车型", models["primary"], models["evidence"], ""])
    audit.append(["本品关注车型", "、".join(str(item) for item in models["own_brand"]), models["evidence"], ""])
    audit.append(["竞品车型", "、".join(str(item) for item in models["competitors"]), models["evidence"], ""])
    audit.append(["客户意向", intention["level"], intention["evidence"], intention["reason"]])
    audit.append([
        "严管专项",
        strict["status"],
        strict.get("policy_basis", ""),
        f"{strict.get('series', '')}｜{strict.get('trim', '')}｜备案成交价 {strict.get('filed_price', '')}",
    ])
    audit.append([])
    audit.append(["类型", "时间戳", "话术原意", "判定与建议"])
    if job["compliance"]:
        for item in job["compliance"]:
            audit.append([
                item["type"],
                item["timestamp"],
                item["quote"],
                f"{item['ruling']}；建议：{item['suggestion']}",
            ])
    else:
        audit.append(["无", "", "未发现明确违规/风险话术", ""])
    audit.freeze_panes = "A2"
    for column, width in zip(("A", "B", "C", "D"), (22, 34, 42, 72)):
        audit.column_dimensions[column].width = width
    for cell in audit[1]:
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="123A70")
    for cell in audit[8]:
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="D8792C")
    for row in audit.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)


def render(job, out_dir):
    validate_review_fields(job)
    score, raw, penalty = calculate(job)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = job["slug"]
    png = out_dir / f"{slug}_6.0-G暗访评分.png"
    render_png(job, png, score, raw, penalty)
    return png, score, penalty


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    arguments = parser.parse_args()
    scoring_job = json.loads(arguments.job.read_text(encoding="utf-8-sig"))
    for result in render(scoring_job, arguments.out_dir):
        print(result)
