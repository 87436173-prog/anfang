
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import argparse
import math
import re
import textwrap

from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont


DOWNLOADS = Path.home() / "Downloads"
OUTPUTS = Path.cwd() / "outputs"
STORE_FILE = Path()
SKU_FILE = Path()
INV_FILE = Path()
STAT_FILE = Path()
SAFETY_DAYS = 60
SKU_SITE_OVERRIDES = {"MY00614": "MY", "PHC-00085": "PH"}

# User-confirmed aliases for Thailand 100ml products only.
TH_SKU_ALIASES = {
    "6979452701534": "6976485745009",  # 勇敢女士
    "6976485740066": "6979452700766",  # 勇敢男士
}

# User-confirmed Malaysia 50ml brand merge, keeping fragrances separate.
MY_SKU_ALIASES = {
    "MY00876": "MY00956",  # 初恋草莓
    "MY00877": "MY00955",  # 栀子清茶
    "MY00875": "MY00957",  # 白月光
    "MY00878": "MY00954",  # 朱砂痣
}
MY_PRODUCT_NAMES = {
    "MY00956": "HIYESEAU女士持久淡香香水50ml-初恋草莓",
    "MY00955": "HIYESEAU女士持久淡香香水50ml-栀子清茶",
    "MY00957": "HIYESEAU女士持久淡香香水50ml-白月光",
    "MY00954": "HIYESEAU女士持久淡香香水50ml-朱砂痣",
}


def canonical_sku(site: str, sku: str) -> str:
    if site == "MY":
        return MY_SKU_ALIASES.get(sku, sku)
    return TH_SKU_ALIASES.get(sku, sku) if site == "TH" else sku

# Products that have been discontinued and therefore must never trigger
# inventory warnings or replenishment recommendations. They remain in sales
# reporting so historical performance is not distorted.
DISCONTINUED_SKUS = {
    "6925564565854",  # 用户于2026-10-01确认停售：lattafa试管香水35ml-白色
    "6976485749809",  # bare vanilla 85ml
    "6976485747171",  # sex men (black) 85ml
    "TH00035",        # 遥远女士 85ml
    "TH00025",        # NATURAL SPRAY 100ml
}

# User confirmed 2026-11-12: sell through remaining stock; exclude risk only.
SELL_THROUGH_PRODUCTS = {
    ("PH", "SEAQUEEN私密香水女士持久留香除异味自然香水礼盒10ml-玫瑰香液"),
    ("PH", "HIYES脏话坏男孩男士香水100ml"),
    ("TH", "HIYES BABY香水白色持久留香72小时1号35ml"),
    ("TH", "HIYES BABY香水蓝色持久留香72小时1号35ml"),
}
SELL_THROUGH_SKUS = {("PH", "PHC-00267"), ("PH", "PHC-00136"),
                     ("TH", "6976485740455"), ("TH", "TH00055"),
                     ("TH", "6976485740462")}


def is_sell_through(site, sku, name):
    return (site, sku) in SELL_THROUGH_SKUS or (site, name.strip()) in SELL_THROUGH_PRODUCTS


FONT_REGULAR_CANDIDATES = (
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
)
FONT_BOLD_CANDIDATES = (
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
)


@lru_cache(maxsize=2)
def font_path(bold: bool = False) -> str:
    candidates = FONT_BOLD_CANDIDATES if bold else FONT_REGULAR_CANDIDATES
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "No supported Chinese font found. Install Microsoft YaHei, PingFang/STHeiti, "
        "Noto Sans CJK, or WenQuanYi Micro Hei."
    )


def font(size: int, bold: bool = False):
    return ImageFont.truetype(font_path(bold), size)


def num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def country_metrics(shops):
    metrics = defaultdict(lambda: {"units": 0.0, "sales": 0.0})
    for shop in shops:
        metrics[shop["site"]]["units"] += num(shop["units"])
        metrics[shop["site"]]["sales"] += num(shop["yesterday"])
    return dict(metrics)


def safety_inventory(avg_units: float, days: int = SAFETY_DAYS) -> float:
    return num(avg_units) * days


def share_values(values):
    cleaned = {key: max(num(value), 0.0) for key, value in values.items()}
    total = sum(cleaned.values())
    return {key: (value / total if total else 0.0) for key, value in cleaned.items()}


def rows(path: Path):
    ws = load_workbook(path, read_only=True, data_only=True).active
    ws.reset_dimensions()
    return list(ws.iter_rows(values_only=True))


def latest_export(folder: Path, keyword: str) -> Path:
    matches = sorted(folder.glob(f"*{keyword}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"No XLSX export matching {keyword!r} in {folder}")
    return matches[0]


def country_name(code: str) -> str:
    return {"TH": "泰国", "PH": "菲律宾", "MY": "马来西亚", "GB": "英国"}.get(code, code or "未知")


def country_abbr(code: str) -> str:
    return {"TH": "TH", "PH": "PH", "MY": "MY", "GB": "UK"}.get(code, code or "--")


def inventory_country(warehouse: str) -> str | None:
    w = (warehouse or "").upper()
    if "泰国" in warehouse or "THAILAND" in w or re.search(r"(^|[-_])TH($|[-_])", w):
        return "TH"
    if "菲律宾" in warehouse or "PHILIPP" in w or "-PH-" in w or w.startswith("PH-") or "XIAGU-PH" in w:
        return "PH"
    if "马来" in warehouse or "MALAYS" in w or w.startswith("MY-") or "-MY-" in w:
        return "MY"
    if w == "ISAAC":
        return "MY"
    if "UK" in w or "英国" in warehouse:
        return "GB"
    return None


def daily_sales_groups(table):
    groups = []
    for col, value in enumerate(table[0]):
        date = str(value or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or table[1][col] != "销售额":
            continue
        columns = {table[1][i]: i for i, header in enumerate(table[0]) if str(header) == date}
        groups.append((date, col, columns["销售订单量"], columns["销售SKU数量"]))
    if not groups:
        raise ValueError("销售日报缺少日期或销售额、销售订单量、销售SKU数量表头")
    return groups


def parse_data(days: int = 1):
    store_rows = rows(STORE_FILE)
    shop_to_site: dict[str, str] = {}
    shops = []
    store_date_groups = daily_sales_groups(store_rows)
    use_store_groups = store_date_groups[:max(1, days)]
    latest_date = store_date_groups[0][0]
    for r in store_rows[2:]:
        shop, site = str(r[0] or "").strip(), str(r[1] or "").strip().upper()
        if not shop:
            continue
        shop_to_site[shop] = site
        shops.append({
            "shop": shop,
            "site": site,
            "yesterday": sum(num(r[c]) for _, c, _, _ in use_store_groups),
            "avg30": num(r[3]),
            "orders": sum(num(r[c]) for _, _, c, _ in use_store_groups),
            "units": sum(num(r[c]) for _, _, _, c in use_store_groups),
        })
    shops.sort(key=lambda x: x["yesterday"], reverse=True)

    stat_rows = rows(STAT_FILE)
    stat_header = [str(value or "").strip() for value in stat_rows[0]]
    try:
        stat_sku_col = stat_header.index("系统SKU")
        stat_units30_col = stat_header.index("30日销量")
    except ValueError as exc:
        raise ValueError("商品销售统计-按sku导出缺少系统SKU或30日销量列") from exc
    units30_by_sku = defaultdict(float)
    for r in stat_rows[1:]:
        sku = str(r[stat_sku_col] or "").strip()
        if sku:
            units30_by_sku[sku] += num(r[stat_units30_col])

    sku_rows = rows(SKU_FILE)
    date_cols = daily_sales_groups(sku_rows)
    recent_days = date_cols[:max(1, days)]
    sku_sales = []
    unmapped_shops = set()
    multisite = []
    missing_stat_skus = set()
    for r in sku_rows[2:]:
        sku = str(r[0] or "").strip()
        if not sku:
            continue
        listed = [s.strip() for s in str(r[8] or "").split(",") if s.strip()]
        sites = {shop_to_site[s] for s in listed if s in shop_to_site}
        unmapped_shops.update(s for s in listed if s not in shop_to_site)
        if len(sites) != 1:
            multisite.append((sku, sorted(sites), listed))
            continue
        site = next(iter(sites))
        if sku not in units30_by_sku:
            missing_stat_skus.add(sku)
        period_sales = sum(num(r[col]) for _, col, _, _ in recent_days)
        period_units = sum(num(r[col]) for _, _, _, col in recent_days)
        sku_sales.append({
            "sku": sku,
            "name": str(r[1] or ""),
            "site": site,
            "yesterday_sales": period_sales,
            "yesterday_units": period_units,
            "avg30_units": units30_by_sku.get(sku, 0) / 30,
        })
    if missing_stat_skus:
        sample = ", ".join(sorted(missing_stat_skus)[:10])
        raise ValueError(f"商品销售统计缺少{len(missing_stat_skus)}个SKU的30日销量：{sample}")

    grouped_sales = {}
    for item in sku_sales:
        key = (item["site"], canonical_sku(item["site"], item["sku"]))
        if key not in grouped_sales:
            grouped_sales[key] = {**item, "sku": key[1]}
            if key[0] == "MY" and key[1] in MY_PRODUCT_NAMES:
                grouped_sales[key]["name"] = MY_PRODUCT_NAMES[key[1]]
        else:
            for field in ("yesterday_sales", "yesterday_units", "avg30_units"):
                grouped_sales[key][field] += item[field]
    sku_sales = list(grouped_sales.values())

    inv_rows = rows(INV_FILE)
    inv_header = [str(value or "").strip() for value in inv_rows[0]]
    modern_inventory = "商品编码" in inv_header and "可用量" in inv_header
    if modern_inventory:
        inv_start = 1
        sku_col = inv_header.index("商品编码")
        name_col = inv_header.index("商品名称")
        warehouse_col = inv_header.index("仓库")
        available_col = inv_header.index("可用量")
        transit_col = inv_header.index("在途量")
    else:
        inv_start = 2
        inv_header = [str(value or "").strip() for value in inv_rows[1]]
        sku_col = inv_header.index("商品编码")
        name_col = inv_header.index("商品名称")
        warehouse_col = inv_header.index("仓库")
        available_col = inv_header.index("可用量")
        transit_col = inv_header.index("在途量")
    units15_col = inv_header.index("15天销量")
    inventory = defaultdict(lambda: {"available": 0.0, "transit": 0.0, "shared_units15": 0.0, "name": ""})
    unknown_warehouses = set()
    for r in inv_rows[inv_start:]:
        sku = str(r[sku_col] or "").strip()
        wh = str(r[warehouse_col] or "").strip()
        site = inventory_country(wh)
        if not sku or not site:
            if wh and not site:
                unknown_warehouses.add(wh)
            continue
        confirmed_site = SKU_SITE_OVERRIDES.get(sku)
        if confirmed_site and site != confirmed_site:
            if any(num(r[col]) != 0 for col in (available_col, transit_col, units15_col)):
                raise ValueError(f"SKU站点与仓库不符且存在库存或销量，需核查：{sku} / {wh}")
            continue
        key = (site, canonical_sku(site, sku))
        inventory[key]["available"] += num(r[available_col])
        inventory[key]["transit"] += num(r[transit_col])
        if r[units15_col] is None or str(r[units15_col]).strip() == "":
            raise ValueError(f"库存表缺少15天销量：{wh} / {sku}")
        inventory[key]["shared_units15"] += float(r[units15_col])
        inventory[key]["name"] = MY_PRODUCT_NAMES.get(key[1], str(r[name_col] or "")) if site == "MY" else str(r[name_col] or "")

    # Match names only inside a country; keep SKU lookup for sales-name differences.
    inventory_groups = {}
    inventory_group_keys = {}
    for key, inv in inventory.items():
        if key[1] in DISCONTINUED_SKUS or is_sell_through(key[0], key[1], inv["name"]):
            continue
        group = (key[0], inv["name"].strip()) if inv["name"].strip() else key
        inventory_group_keys[key] = group
        if group not in inventory_groups:
            inventory_groups[group] = {**inv, "member_skus": [key[1]]}
        else:
            for field in ("available", "transit", "shared_units15"):
                inventory_groups[group][field] += inv[field]
            inventory_groups[group]["member_skus"].append(key[1])

    risks = []
    discontinued_excluded = []
    missing_inventory_excluded = []
    seen_inventory_groups = set()
    for s in sku_sales:
        if s["sku"] in DISCONTINUED_SKUS or is_sell_through(s["site"], s["sku"], s["name"]):
            discontinued_excluded.append(s)
            continue
        key = (s["site"], s["sku"])
        if key in inventory:
            group = inventory_group_keys[key]
        else:
            group = (s["site"], s["name"].strip())
            if not group[1] or group not in inventory_groups:
                if key in {("PH", "PHC-00014"), ("TH", "6925564565502")} and s["yesterday_sales"] == 0 and s["yesterday_units"] == 0 and not any(num(row[c]) or num(row[u]) for row in sku_rows[2:] if str(row[0]) == s["sku"] for _, c, _, u in date_cols):
                    missing_inventory_excluded.append(s)
                    continue
                raise ValueError(f"库存表缺少武汉经营SKU的共用仓库记录：{key}")
        if group in seen_inventory_groups:
            continue
        seen_inventory_groups.add(group)
        inv = inventory_groups[group]
        avg15_units = inv["shared_units15"] / 15
        if avg15_units <= 0:
            continue
        target = safety_inventory(avg15_units)
        total = inv["available"] + inv["transit"]
        coverage = total / target if target else math.inf
        gap = max(target - total, 0)
        if coverage < 0.5:
            level, rank = "紧急", 0
        elif coverage < 0.8:
            level, rank = "预警", 1
        elif coverage < 1:
            level, rank = "关注", 2
        else:
            level, rank = "健康", 3
        risks.append({**s, **inv, "avg15_units": avg15_units, "name": inv["name"] or s["name"], "target": target, "coverage": coverage, "gap": gap, "level": level, "rank": rank})
    risks.sort(key=lambda x: (x["rank"], -x["gap"]))

    # Merge exact product names within each country for sales reporting only.
    named_sales = {}
    for item in sku_sales:
        key = (item["site"], item["name"].strip())
        if key not in named_sales:
            named_sales[key] = dict(item)
        else:
            for field in ("yesterday_sales", "yesterday_units", "avg30_units"):
                named_sales[key][field] += item[field]
    sku_sales = list(named_sales.values())

    # Management ranking is sales-led; units remain a supporting display metric.
    sku_top = sorted(sku_sales, key=lambda x: x["yesterday_sales"], reverse=True)[:15]
    return {
        "latest_date": latest_date if days == 1 else f"{latest_date}（近{days}日）",
        "shops": shops,
        "country_metrics": country_metrics(shops),
        "sku_top": sku_top,
        "sku_sales": sku_sales,
        "risks": risks[:15],
        "all_risks": risks,
        "discontinued_excluded": discontinued_excluded,
        "missing_inventory_excluded": missing_inventory_excluded,
        "unmapped_shops": sorted(unmapped_shops),
        "multisite": multisite,
        "unknown_warehouses": sorted(unknown_warehouses),
    }


THEMES = {
    "business": {
        "filename": "销售战报_商务风.png", "bg": "#F3F7FA", "panel": "#FFFFFF", "text": "#14283D",
        "muted": "#6B7D8E", "primary": "#145DA0", "accent": "#20A39E", "line": "#DCE6ED", "title": "商务风",
    },
    "minimal": {
        "filename": "销售战报_极简黑白风.png", "bg": "#F7F7F5", "panel": "#FFFFFF", "text": "#161616",
        "muted": "#777777", "primary": "#222222", "accent": "#707070", "line": "#DEDEDA", "title": "极简黑白风",
    },
    "commerce": {
        "filename": "销售战报_鲜明电商风.png", "bg": "#FFF7EE", "panel": "#FFFFFF", "text": "#2C183A",
        "muted": "#806D85", "primary": "#6C3DF4", "accent": "#FF6B35", "line": "#ECDFF0", "title": "鲜明电商风",
    },
}


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def fit_text(draw, text, max_width, size=28, min_size=18, bold=False):
    t = str(text)
    for s in range(size, min_size - 1, -1):
        f = font(s, bold)
        if draw.textbbox((0, 0), t, font=f)[2] <= max_width:
            return t, f
    while t and draw.textbbox((0, 0), t + "…", font=font(min_size, bold))[2] > max_width:
        t = t[:-1]
    return t + "…", font(min_size, bold)


def truncate_text(draw, text, max_width, size=18, bold=False):
    t = str(text)
    f = font(size, bold)
    if draw.textbbox((0, 0), t, font=f)[2] <= max_width:
        return t, f
    while t and draw.textbbox((0, 0), t + "…", font=f)[2] > max_width:
        t = t[:-1]
    return t + "…", f


def wrap_full_text(draw, text, max_width, size=14):
    f = font(size)
    lines, current = [], ""
    for ch in str(text):
        candidate = current + ch
        if current and draw.textbbox((0, 0), candidate, font=f)[2] > max_width:
            lines.append(current)
            current = ch
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines, f


def draw_country_donut(draw, center, radius, values, colors, panel_fill):
    shares = share_values(values)
    box = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
    if sum(max(num(value), 0) for value in values.values()) > 0:
        start = -90
        for site in ["TH", "PH", "MY", "GB"]:
            end = start + shares.get(site, 0) * 360
            draw.pieslice(box, start=start, end=end, fill=colors[site])
            start = end
    else:
        draw.ellipse(box, fill="#E7DFE8")
    inner = radius * 0.44
    draw.ellipse((center[0] - inner, center[1] - inner, center[0] + inner, center[1] + inner), fill=panel_fill)
    return shares


def render(data, key, theme):
    shops = data["shops"]
    store_layout_shift = max(0, 180 + max(0, len(shops) - 1) * 47 - 895)
    W, H = 1440, 4970 + store_layout_shift
    im = Image.new("RGB", (W, H), theme["bg"])
    d = ImageDraw.Draw(im)
    pad = 64
    latest = datetime.strptime(data["latest_date"][:10], "%Y-%m-%d")

    # Header
    d.text((pad, 54), f"销售战报-{latest.month}月{latest.day}日", font=font(58, True), fill=theme["text"])
    d.text((W - pad, 76), theme["title"], font=font(25, True), fill=theme["accent"], anchor="ra")
    d.line((pad, 142, W - pad, 142), fill=theme["primary"], width=5)

    total_sales = sum(x["yesterday"] for x in shops)
    total_orders = sum(x.get("orders", 0) for x in shops)
    total_units = data.get("reported_units", sum(x["units"] for x in shops))
    metrics = data["country_metrics"]
    site_units = {site: metrics.get(site, {}).get("units", 0.0) for site in ["TH", "PH", "MY", "GB"]}
    site_sales = {site: metrics.get(site, {}).get("sales", 0.0) for site in ["TH", "PH", "MY", "GB"]}
    cards = [
        ("昨日销售额", f"¥{total_sales:,.0f}"),
        ("原表订单量", f"{total_orders:,.0f}"),
        ("昨日销量（剔除小样）", f"{total_units:,.0f}"),
    ]
    y = 176
    gap = 16
    cw = (W - pad * 2 - gap * 2) / 3
    for i, (label, value) in enumerate(cards):
        x = pad + i * (cw + gap)
        rounded(d, (x, y, x + cw, y + 130), 20, theme["panel"], theme["line"])
        d.text((x + 20, y + 19), label, font=font(22), fill=theme["muted"])
        val, vf = fit_text(d, value, cw - 40, 34, 25, True)
        d.text((x + 20, y + 67), val, font=vf, fill=theme["primary"])

    # Country sales-volume and sales-amount donuts
    y = 334
    rounded(d, (pad, y, W - pad, y + 410), 22, theme["panel"], theme["line"])
    d.text((pad + 28, y + 24), "各国家昨日占比", font=font(31, True), fill=theme["text"])
    country_colors = {"TH": "#6C3DF4", "PH": "#FF6B35", "MY": "#20A39E", "GB": "#F0B429"}
    left_center = (pad + 135, y + 235)
    right_center = (pad + 790, y + 235)
    d.text((left_center[0], y + 76), "销量占比", font=font(24, True), fill=theme["text"], anchor="ma")
    d.text((right_center[0], y + 76), "销售额占比", font=font(24, True), fill=theme["text"], anchor="ma")
    unit_shares = draw_country_donut(d, left_center, 92, site_units, country_colors, theme["panel"])
    sales_shares = draw_country_donut(d, right_center, 92, site_sales, country_colors, theme["panel"])
    for i, site in enumerate(["TH", "PH", "MY", "GB"]):
        ly = y + 112 + i * 65
        lx = pad + 255
        rounded(d, (lx, ly + 4, lx + 22, ly + 26), 6, country_colors[site])
        d.text((lx + 36, ly), country_name(site), font=font(19, True), fill=theme["text"])
        d.text((lx + 36, ly + 29), f"{site_units[site]:,.0f}件 · {unit_shares[site]:.1%}", font=font(19), fill=theme["muted"])
        rx = pad + 910
        rounded(d, (rx, ly + 4, rx + 22, ly + 26), 6, country_colors[site])
        d.text((rx + 36, ly), country_name(site), font=font(19, True), fill=theme["text"])
        d.text((rx + 36, ly + 29), f"¥{site_sales[site]:,.0f} · {sales_shares[site]:.1%}", font=font(19), fill=theme["muted"])

    # Store table
    y = 770
    rounded(d, (pad, y, W - pad, y + 895 + store_layout_shift), 22, theme["panel"], theme["line"])
    d.text((pad + 28, y + 24), "店铺销售排名", font=font(31, True), fill=theme["text"])
    d.text((W - pad - 28, y + 31), "按昨日销售额降序", font=font(20), fill=theme["muted"], anchor="ra")
    hy = y + 82
    store_name_x = pad + 30
    store_site_x = pad + 565
    store_sales_x = pad + 835
    store_units_x = pad + 980
    store_avg_x = pad + 1160
    store_delta_x = W - pad - 28
    cols = [
        (store_name_x, "排名/店铺", "la"),
        (store_site_x, "站点", "la"),
        (store_sales_x, "昨日销售额", "ra"),
        (store_units_x, "销量*", "ra"),
        (store_avg_x, "区间日均", "ra"),
        (store_delta_x, "较日均", "ra"),
    ]
    for x, label, anchor in cols:
        d.text((x, hy), label, font=font(20, True), fill=theme["muted"], anchor=anchor)
    d.line((pad + 28, hy + 37, W - pad - 28, hy + 37), fill=theme["line"], width=2)
    row_y = hy + 48
    for i, s in enumerate(shops):
        yy = row_y + i * 47
        delta = (s["yesterday"] / s["avg30"] - 1) if s["avg30"] else 0
        name, nf = fit_text(d, f"{i+1:02d}  {s['shop']}", 500, 22, 17, i < 3)
        d.text((store_name_x, yy), name, font=nf, fill=theme["text"])
        d.text((store_site_x, yy), country_name(s["site"]), font=font(21), fill=theme["muted"])
        d.text((store_sales_x, yy), f"¥{s['yesterday']:,.0f}", font=font(22, True), fill=theme["primary"], anchor="ra")
        d.text((store_units_x, yy), s.get("units_display", f"{s['units']:,.0f}"), font=font(22), fill=theme["text"], anchor="ra")
        d.text((store_avg_x, yy), f"¥{s['avg30']:,.0f}", font=font(22), fill=theme["text"], anchor="ra")
        d.text((store_delta_x, yy), f"{delta:+.0%}", font=font(19, True), fill=("#D64545" if delta < 0 else "#1B9A6C"), anchor="ra")

    # Top SKU bars
    y = 1690 + store_layout_shift
    rounded(d, (pad, y, W - pad, y + 1665), 22, theme["panel"], theme["line"])
    d.text((pad + 28, y + 24), "昨日销售额 TOP15 SKU", font=font(36, True), fill=theme["text"])
    top_units_x = pad + 1080
    top_sales_x = W - pad - 28
    d.text((top_units_x, y + 39), "销量", font=font(22, True), fill=theme["muted"], anchor="ra")
    d.text((top_sales_x, y + 39), "销售额", font=font(22, True), fill=theme["muted"], anchor="ra")
    top = data["sku_top"]
    mx = max([x["yesterday_sales"] for x in top] or [1])
    grouped = defaultdict(list)
    for item in top:
        grouped[item["site"]].append(item)
    cy = y + 78
    global_index = 0
    for site in ["TH", "PH", "MY", "GB"]:
        items = grouped.get(site, [])
        if not items:
            continue
        d.text((pad + 30, cy), f"{country_name(site)}（{len(items)}款）", font=font(27, True), fill=theme["accent"])
        cy += 44
        for local_index, s in enumerate(items, 1):
            yy = cy
            d.text((pad + 30, yy), f"{local_index:02d}", font=font(21, True), fill=theme["muted"])
            lines, lf = wrap_full_text(d, s["name"], 475, 22)
            for li, line in enumerate(lines):
                d.text((pad + 85, yy + li * 28), line, font=lf, fill=theme["text"])
            bx = pad + 600
            bw = 360 * s["yesterday_sales"] / mx
            rounded(d, (bx, yy + 22, bx + 360, yy + 46), 10, theme["bg"])
            rounded(d, (bx, yy + 22, bx + max(8, bw), yy + 46), 10, theme["accent"] if global_index < 3 else theme["primary"])
            d.text((top_units_x, yy + 13), f"{s['yesterday_units']:,.0f}", font=font(26, True), fill=theme["text"], anchor="ra")
            d.text((top_sales_x, yy + 13), f"¥{s['yesterday_sales']:,.0f}", font=font(26, True), fill=theme["text"], anchor="ra")
            cy += 88
            global_index += 1
        cy += 18

    # Risk table
    y = 3380 + store_layout_shift
    rounded(d, (pad, y, W - pad, y + 1390), 22, theme["panel"], theme["line"])
    risk_title = f"风险库存 TOP15（{len(data['missing_inventory_excluded'])}款待核）" if data["missing_inventory_excluded"] else "风险库存 TOP15"
    d.text((pad + 28, y + 24), risk_title, font=font(36, True), fill=theme["text"])
    headers = [(pad+30,"国家/商品名"),(pad+545,"可用"),(pad+685,"在途"),(pad+865,"近15日均销量"),(pad+1015,"安全库存"),(pad+1190,"建议补货"),(W-pad-52,"等级")]
    hy = y + 80
    for x, label in headers:
        d.text((x, hy), label, font=font(22, True), fill=theme["muted"], anchor="ra" if x > pad+400 else "la")
    d.line((pad + 28, hy + 34, W - pad - 28, hy + 34), fill=theme["line"], width=2)
    risk_colors = {"紧急": "#D64545", "预警": "#F08C2E", "关注": "#D4A514", "健康": "#2D9D78"}
    for i, r in enumerate(data["risks"]):
        yy = hy + 50 + i * 82
        lines, lf = wrap_full_text(d, f"{country_name(r['site'])} · {r['name']}", 395, 18)
        for li, line in enumerate(lines):
            d.text((pad + 30, yy + li * 23), line, font=lf, fill=theme["text"])
        for x, v, fmt in [(pad+545,r['available'],",.0f"), (pad+685,r['transit'],",.0f"), (pad+865,r['avg15_units'],",.1f"), (pad+1190,r['gap'],",.0f")]:
            d.text((x, yy + 17), format(v, fmt), font=font(24), fill=theme["text"], anchor="ra")
        d.text((pad + 1015, yy + 17), f"{r['target']:,.0f}", font=font(24, True), fill=theme["text"], anchor="ra")
        rounded(d, (pad + 1230, yy + 8, W - pad - 28, yy + 43), 12, risk_colors[r["level"]])
        badge_left = pad + 1230
        badge_right = W - pad - 28
        d.text(((badge_left + badge_right) / 2, yy + 25), r["level"], font=font(20, True), fill="#FFFFFF", anchor="mm")

    # Footer
    foot_y = 4800 + store_layout_shift
    d.text((pad, foot_y), "库存口径：深圳＋武汉共用仓库15天销量÷15×60；补货=MAX(安全库存−可用−在途,0)", font=font(19), fill=theme["muted"])
    d.text((pad, foot_y + 34), "范围：武汉；销量及占比剔除零金额小样，订单为原表口径；同站点同名合并，跨站点独立。", font=font(19), fill=theme["muted"])
    d.text((pad, foot_y + 68), "* 店铺销量剔除小样；—表示小样跨店汇总、无法准确分摊；零金额小样不列入商品及风险榜。", font=font(19), fill=theme["muted"])
    d.text((pad, foot_y + 102), "库存排除深圳中转仓、停售及售完停卖商品；区间日均为导出范围内的日均销售额。", font=font(19), fill=theme["muted"])
    if data["missing_inventory_excluded"]:
        d.text((pad, foot_y + 136), "注：" + "、".join(x["sku"] for x in data["missing_inventory_excluded"]) + " 缺对应站点库存记录，未纳入库存风险计算。", font=font(19), fill=theme["muted"])

    path = OUTPUTS / theme["filename"]
    if path.exists():
        raise FileExistsError(f"输出文件已存在，请指定新目录：{path}")
    im.save(path, quality=96)
    return path


def prepare_report_data():
    d = parse_data(1)
    raw = {"STORE_FILE": rows(STORE_FILE), "SKU_FILE": rows(SKU_FILE)}
    skugroups = daily_sales_groups(raw["SKU_FILE"])
    assert [g[0] for g in daily_sales_groups(raw["STORE_FILE"])] == [g[0] for g in skugroups], "店铺与SKU日报日期不一致"
    assert not d["unmapped_shops"] and not d["multisite"], "存在未映射或跨站点SKU，需核对"
    stat_rows = rows(STAT_FILE)
    scope = list(stat_rows[0]).index("时间范围")
    assert all(str(r[scope]).endswith(d["latest_date"].replace("-", "")) for r in stat_rows[1:] if r[0]), "SKU统计与日报截止日期不一致"
    rawsales=sum(s['yesterday'] for s in d['shops']);rawunits=sum(s['units'] for s in d['shops'])
    assert abs(rawsales-sum(x['yesterday_sales'] for x in d['sku_sales']))<.01
    assert rawunits==sum(x['yesterday_units'] for x in d['sku_sales'])
    shopsite={x['shop']:x['site'] for x in d['shops']};canonical_names={(x['site'],x['sku']):x['name'] for x in d['sku_sales']}
    zero=defaultdict(float);known=defaultdict(float);ambiguous=set();period_sales=defaultdict(float);period_sku_sales=defaultdict(float);zero_rows=[]
    for r in raw['SKU_FILE'][2:]:
     if not r[0]:continue
     shops=[x.strip() for x in str(r[8] or '').split(',') if x.strip() in shopsite];sites={shopsite[x] for x in shops};assert len(sites)==1
     site=next(iter(sites));canon=canonical_sku(site,str(r[0]));name=canonical_names.get((site,canon),str(r[1] or '').strip())
     if site=='MY':name=MY_PRODUCT_NAMES.get(canon,name)
     key=(site,name)
     period_value=sum(num(r[c]) for _,c,_,_ in skugroups)
     period_sales[key]+=period_value;period_sku_sales[(site,canon)]+=period_value
     u=num(r[skugroups[0][3]]);v=num(r[skugroups[0][1]])
     if v==0 and u:
      zero[key]+=u;zero_rows.append({'sku':str(r[0]),'name':name,'site':site,'shops':shops,'units':u})
      if len(shops)==1:known[shops[0]]+=u
      else:ambiguous.update(shops)
    for x in d['sku_sales']:
     x['yesterday_units']-=zero[(x['site'],x['name'])];assert x['yesterday_units']>=0
    d['sku_sales']=[x for x in d['sku_sales'] if x['yesterday_sales']!=0]
    d['sku_top']=sorted(d['sku_sales'],key=lambda x:x['yesterday_sales'],reverse=True)[:15]
    d['reported_units']=sum(x['yesterday_units'] for x in d['sku_sales'])
    assert d['reported_units']+sum(x['units'] for x in zero_rows)==rawunits
    for x in d['shops']:
     if x['yesterday']==0:x['units_display']='0'
     elif x['shop'] in ambiguous:x['units_display']='—'
     else:x['units_display']=f"{x['units']-known[x['shop']]:,.0f}"
    for site,m in d['country_metrics'].items():m['units']=sum(x['yesterday_units'] for x in d['sku_sales'] if x['site']==site)
    assert sum(x['units'] for x in d['country_metrics'].values())==d['reported_units']
    excluded_risks=[];risks=[]
    for x in d['all_risks']:
     if sum(period_sku_sales[(x['site'],sku)] for sku in x['member_skus'])==0:excluded_risks.append(x)
     else:risks.append(x)
    d['all_risks']=risks;d['risks']=risks[:15]
    for x in risks:
     assert not is_sell_through(x['site'],x['sku'],x['name'])
     assert not any((x['site'],sku) in SELL_THROUGH_SKUS for sku in x['member_skus'])
     assert abs(x['avg15_units']-x['shared_units15']/15)<1e-8
     assert abs(x['target']-x['shared_units15']*4)<1e-8
     assert abs(x['gap']-max(x['target']-x['available']-x['transit'],0))<1e-8
     assert not set(x['member_skus'])&DISCONTINUED_SKUS
    for k in ['sales','units']:assert abs(sum(share_values({s:x[k] for s,x in d['country_metrics'].items()}).values())-1)<1e-9
    assert len(d['shops'])==len([r for r in raw['STORE_FILE'][2:] if r[0]]) and len(d['sku_top'])==min(15,len(d['sku_sales']))

    d["zero_units_excluded"]=sum(x["units"] for x in zero_rows)
    return d


def main():
    global DOWNLOADS, OUTPUTS, STORE_FILE, SKU_FILE, INV_FILE, STAT_FILE
    parser = argparse.ArgumentParser(description="Generate the vivid cross-border sales battle report PNG.")
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads", help="Folder containing source XLSX exports")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "outputs", help="Destination folder for the PNG")
    parser.add_argument("--days", type=int, choices=[1], default=1, help="Latest complete natural day only")
    args = parser.parse_args()
    DOWNLOADS = args.downloads.resolve()
    OUTPUTS = args.output.resolve()
    STORE_FILE = latest_export(DOWNLOADS, "销售日报店铺维度按日期对比导出")
    SKU_FILE = latest_export(DOWNLOADS, "销售日报SKU维度按日期对比导出")
    STAT_FILE = latest_export(DOWNLOADS, "商品销售统计-按sku导出")
    inventory_candidates = list(DOWNLOADS.glob("*库存报表*.xlsx")) + list(DOWNLOADS.glob("*库存查询导出*.xlsx"))
    INV_FILE = max(inventory_candidates, key=lambda path: path.stat().st_mtime)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    data = prepare_report_data()
    paths = [render(data, "commerce", THEMES["commerce"])]
    print("latest_date", data["latest_date"])
    print("sales", sum(s["yesterday"] for s in data["shops"]), "orders_original", sum(s["orders"] for s in data["shops"]), "units_excluding_zero", data["reported_units"], "samples_excluded", data["zero_units_excluded"])
    print("shops", len(data["shops"]), "sku_top", len(data["sku_top"]), "risks", len(data["all_risks"]))
    print("discontinued_excluded", len(data["discontinued_excluded"]), [item["sku"] for item in data["discontinued_excluded"]])
    print("multisite_excluded", len(data["multisite"]), "unmapped_shops", len(data["unmapped_shops"]))
    print("unknown_warehouses", len(data["unknown_warehouses"]))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
