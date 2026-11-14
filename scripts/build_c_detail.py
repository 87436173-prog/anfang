# -*- coding: utf-8 -*-
"""生成指定单列表的 C 项得分明细（HTML + Markdown + xlsx）。

用法：python scripts/build_c_detail.py
修改 SLUGS 列表即可换批次；输出到 <ROOT>/暗访打分日报/_汇总分析/。
"""
import json, os, io, html
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

ROOT = os.environ.get('BYD_SCORING_ROOT') or r'C:/Users/no02/WorkBuddy/2026-11-10-09-14-36'
OUT = os.path.join(ROOT, '暗访打分日报', '_汇总分析')
os.makedirs(OUT, exist_ok=True)

SLUGS = ['20261111_lilei_huangnvshi', '20261111_lixiang_bai', '20261111_lixiang_xu',
         '20261112_fushixiong_han', '20261112_lizengqiang_liu', '20261112_pokee',
         '20261112_wujie_chen', '20261112_xuyang_huang',
         '20261113_fushixiong_tong', '20261113_fushixiong_yang', '20261113_lilei_guo',
         '20261113_lilei_liu', '20261113_lixiang_wang', '20261113_wujie_wang',
         '20261113_zhangdemin_wang', '20261113_zhangting_jin']

ITEMS = [('C2', '车型推荐', 2), ('C3', '关注点挖掘', 3), ('C4', '关注点回应', 3),
         ('C5', '卖点演示', 4), ('C5bonus', '卖点超额加分', 2),
         ('C6', '疑虑解答', 2), ('C7', '竞品比较', 3), ('C8', '品牌自信', 3)]
BASE_ITEMS = ('C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8')


def load(slug):
    d = json.load(open(os.path.join(ROOT, 'jobs', slug, 'job.json'), encoding='utf-8'))
    rows = {r[1]: r for r in d['rows']}
    return d, rows


def fmt(v):
    if v == 'NA':
        return 'NA'
    return ('%g' % v) if isinstance(v, (int, float)) else str(v)


def short(c):
    c = str(c or '')
    i = c.find('（')
    return c[:i] if i > 0 else c

jobs = []
for s in SLUGS:
    d, rows = load(s)
    c_mod = [m for m in d['modules'] if m[0].startswith('C')][0]
    jobs.append({'slug': s, 'sales': d.get('sales', ''), 'cust': d.get('customer', ''), 'cust_short': short(d.get('customer')),
                 'date': d.get('reception_date', ''), 'final': d['final_score'],
                 'cmod': c_mod[2], 'rows': rows})

# ---------------- Markdown ----------------
md = ['# 16 单 C 项得分明细（静态体验 20 分）', '',
      '- 口径：王朝网 6.0-G 现行规则（2026-11-14），C1 为拒绝讲解的门禁项不单独计分，C 模块由 C2–C8 组成，满分 20（C5bonus 为超额加分，不计入模块分）。',
      '- 数据源：各单 job.json 逐项判定与证据原文。', '',
      '## 一、汇总矩阵', '',
      '| 销售 | 客户 | 接待日 | 总分 | C模块 | C2 车型<br>推荐 | C3 关注点<br>挖掘 | C4 关注点<br>回应 | C5 卖点<br>演示 | C6 疑虑<br>解答 | C7 竞品<br>比较 | C8 品牌<br>自信 |',
      '|---|---|---|---|---|---|---|---|---|---|---|---|']
for j in jobs:
    cells = []
    for k, _, mx in ITEMS:
        if k == 'C5bonus':
            continue
        v = j['rows'][k][4]
        cells.append(fmt(v))
    md.append('| %s | %s | %s | **%s** | %s/20 | %s |' % (
        j['sales'], j['cust_short'], j['date'], j['final'], fmt(j['cmod']), ' | '.join(cells)))
md += ['', '> 单位：分。C2 满分 2、C3 满分 3、C4 满分 3、C5 满分 4、C6 满分 2、C7 满分 3、C8 满分 3，合计 20。', '']

# 单项统计
md += ['## 二、单项得分率', '', '| 项目 | 满分 | 得分数 | 平均得分 | 得分率 | 满分单数 | 零分单数 |', '|---|---|---|---|---|---|---|']
for k, name, mx in ITEMS:
    if k == 'C5bonus':
        continue
    vals = [j['rows'][k][4] for j in jobs]
    nums = [v for v in vals if isinstance(v, (int, float))]
    tot = sum(nums)
    md.append('| %s %s | %d | %d | %.2f | %.0f%% | %d | %d |' % (
        k, name, mx, len(nums), tot / len(nums) if nums else 0, tot / (mx * len(nums)) * 100 if nums else 0,
        sum(1 for v in nums if v == mx), sum(1 for v in nums if v == 0)))
md.append('')

md += ['## 三、逐单明细', '']
for i, j in enumerate(jobs, 1):
    md.append('### %d. %s · %s（%s，总分 %s，C 模块 %s/20）' % (
        i, j['sales'], j['cust_short'], j['date'], j['final'], fmt(j['cmod'])))
    md += ['', '| 项目 | 满分 | 得分 | 得分/失分理由 |', '|---|---|---|---|']
    for k, name, mx in ITEMS:
        r = j['rows'][k]
        ev = str(r[6]).replace('\n', ' ')
        if len(ev) > 340:
            ev = ev[:340] + '…（全文见 HTML 明细或报告图）'
        ev = ev.replace('|', '／')
        md.append('| %s %s | %d | **%s** | %s |' % (k, name, mx, fmt(r[4]), ev))
    md.append('')
md_path = os.path.join(OUT, 'C项得分明细_16单_2026-11-14.md')
open(md_path, 'w', encoding='utf-8').write('\n'.join(md) + '\n')

# ---------------- xlsx ----------------
wb = Workbook()
ws = wb.active
ws.title = '汇总矩阵'
head = ['销售', '客户', '接待日期', '总分', 'C模块得分'] + [f'{k}\n{n}' for k, n, _ in ITEMS]
ws.append(head)
for j in jobs:
    ws.append([j['sales'], j['cust'], j['date'], j['final'], j['cmod']] +
              [j['rows'][k][4] for k, _, _ in ITEMS])

ws2 = wb.create_sheet('逐项明细')
ws2.append(['销售', '客户', '接待日期', '项目', '项目名', '满分', '得分', '判定与理由'])
for j in jobs:
    for k, name, mx in ITEMS:
        r = j['rows'][k]
        ws2.append([j['sales'], j['cust'], j['date'], k, name, mx, r[4], str(r[6])])

thin = Side(style='thin', color='D9D9D9')
for sh in (ws, ws2):
    for c in sh[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill('solid', fgColor='EAF1FB')
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    sh.freeze_panes = 'A2'
    for row in sh.iter_rows():
        for c in row:
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            if c.column_letter in ('H',) and sh is ws2:
                c.alignment = Alignment(wrap_text=True, vertical='top')
ws.column_dimensions['B'].width = 30
for col in 'CDEFGHIJKLM':
    ws.column_dimensions[col].width = 10
for col, w in (('A', 12), ('B', 30), ('C', 12), ('D', 8), ('E', 12), ('F', 8), ('G', 8), ('H', 90)):
    ws2.column_dimensions[col].width = w
xls_path = os.path.join(OUT, 'C项得分明细_16单_2026-11-14.xlsx')
wb.save(xls_path)

# ---------------- HTML ----------------
def esc(s):
    return html.escape(str(s))


cards = []
for i, j in enumerate(jobs, 1):
    rows_html = []
    for k, name, mx in ITEMS:
        r = j['rows'][k]
        v = r[4]
        cls = 'full' if isinstance(v, (int, float)) and v == mx else ('zero' if v == 0 else 'part')
        rows_html.append(
            '<tr class="%s"><td class="k">%s</td><td class="n">%s</td><td class="mx">%d</td>'
            '<td class="sc">%s</td><td class="ev">%s</td></tr>' % (cls, k, esc(name), mx, fmt(v), esc(r[6])))
    cards.append('''
<section class="card">
  <header>
    <div class="idx">%d</div>
    <div class="who"><b>%s</b> · %s</div>
    <div class="meta">接待 %s ｜ 总分 <b>%s</b> ｜ C 静态 <b>%s</b>/20</div>
  </header>
  <table>
    <colgroup><col style="width:78px"><col style="width:110px"><col style="width:52px"><col style="width:56px"><col></colgroup>
    <thead><tr><th>项目</th><th>考核点</th><th>满分</th><th>得分</th><th>得分 / 失分理由</th></tr></thead>
    <tbody>%s</tbody>
  </table>
</section>''' % (i, esc(j['sales']), esc(j['cust_short']), esc(j['date']), j['final'], fmt(j['cmod']), ''.join(rows_html)))

stat_rows = []
for k, name, mx in ITEMS:
    if k == 'C5bonus':
        continue
    vals = [j['rows'][k][4] for j in jobs]
    nums = [v for v in vals if isinstance(v, (int, float))]
    tot = sum(nums)
    rate = tot / (mx * len(nums)) * 100 if nums else 0
    stat_rows.append('<tr><td class="k">%s</td><td>%s</td><td>%d</td><td>%.2f</td><td><div class="bar"><i style="width:%.0f%%"></i></div>%.0f%%</td><td>%d</td><td>%d</td></tr>'
                     % (k, esc(name), mx, tot / len(nums) if nums else 0, rate, rate,
                        sum(1 for v in nums if v == mx), sum(1 for v in nums if v == 0)))

tpl = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>16 单 C 项得分明细</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2129;--sub:#5c6470;--line:#e5e8ec;--accent:#1664ff;--ok:#0f9d58;--warn:#c47f00;--bad:#d93025}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 6px}
.sub{color:var(--sub);font-size:13px;margin-bottom:18px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:22px}
.panel h2{font-size:16px;margin:0 0 12px}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f2f5f9;font-weight:600;font-size:13px;color:#333}
td.k{font-weight:600;color:#333;white-space:nowrap}
td.mx,td.sc{text-align:center;white-space:nowrap}
tr.full td.sc{color:var(--ok);font-weight:700}
tr.part td.sc{color:var(--warn);font-weight:700}
tr.zero td.sc{color:var(--bad);font-weight:700}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;overflow:hidden}
.card header{display:flex;align-items:center;gap:12px;padding:12px 16px;background:#fafbfc;border-bottom:1px solid var(--line);flex-wrap:wrap}
.card .idx{width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;font-size:13px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.card .who{font-size:15px}
.card .meta{color:var(--sub);font-size:12.5px;margin-left:auto}
.card table{font-size:13px}
.card tbody tr:last-child td{border-bottom:none}
.ev{color:#333;white-space:normal;word-break:break-word}
.bar{display:inline-block;width:90px;height:7px;background:#eceff3;border-radius:4px;margin-right:8px;vertical-align:middle;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.note{color:var(--sub);font-size:12.5px}
</style></head><body><div class="wrap">
<h1>16 单 C 项得分明细</h1>
<div class="sub">静态体验 20 分（C2–C8）｜口径：王朝网 6.0-G 现行规则 2026-11-14｜C1 为拒绝讲解门禁项，不单独计分；C5bonus 为 C5 满 4/4 后的超额加分，不计入模块分</div>
<div class="panel"><h2>单项得分率</h2>
<table><thead><tr><th>项目</th><th>考核点</th><th>满分</th><th>平均得分</th><th>得分率</th><th>满分单数</th><th>零分单数</th></tr></thead>
<tbody>__STAT__</tbody></table></div>
__CARDS__
<div class="panel"><h2>计分口径说明</h2>
<div class="note">
C2 车型推荐：推荐合适车型或客户明确意向车型任一成立即 2 分；仅铺价格带、无推荐指向记 0。<br>
C3 关注点挖掘：客户明确说出在意什么、或销售挖掘后客户确认才 3 分；仅预算、配置意向、问了没答、回绝介绍记 0。<br>
C4 关注点回应：须针对已确认的关注点做优势分析或场景讲解；无关注点或无回应记 0。<br>
C5 卖点演示：每个达标卖点 2 分，须属本品优势或客户兴趣点，且同时满足差异化讲解与场景化收益，能展示优先展示、能体验就让客户体验；4 分为两点及以上，C5bonus 另计。<br>
C6 疑虑解答：全有或全无——客户全部疑问任一条未解答即 0。<br>
C7 竞品比较：有竞品须至少 2 条客观对比；无竞品须先称赞选择眼光或感谢信任、再给 2 条选车衡量标准，两要件缺一即 0。<br>
C8 品牌自信：品牌故事或品牌实力不少于 2 点记 3；仅机械背书记 1；无内容 0；出现非比亚迪 Logo 物料或对品牌消极言论 -5。
</div></div>
</div></body></html>'''
tpl = tpl.replace('__STAT__', ''.join(stat_rows)).replace('__CARDS__', ''.join(cards))
html_path = os.path.join(OUT, 'C项得分明细_16单_2026-11-14.html')
open(html_path, 'w', encoding='utf-8').write(tpl)

print(md_path)
print(xls_path)
print(html_path)
