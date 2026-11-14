# -*- coding: utf-8 -*-
"""出图前文本一致性校验：
1) 默认项与计分说明中的 基础/NA/加分/总分 必须与 job.json 一致；
2) 改进建议与亮点中“某分项 X 分”的表述必须与该项当前取值一致（排除“B7与B8合计5分”这类合计写法）；
3) 加分项明细合计必须等于 bonus；
4) 不得出现同一分项在同一条说明里给出两个不同结论的历史重算链。
"""
import json, glob, re, sys, os

ROOT = os.environ.get('BYD_SCORING_ROOT') or r'C:/Users/no02/WorkBuddy/2026-11-10-09-14-36'

BON = ['A3', 'B8', 'B8coffee', 'C5bonus', 'D8bonus']
CODE = r'[A-H]\d[a-z]?'
CLAIM = re.compile(r'(?<![与和、])(' + CODE + r')(?:只到|只记|只|已记满|记|为|得|拿到|拿满)?\s*(-?\d+)\s*分')
SUM_OK = re.compile(r'(?:B7与B8|B7、B8)')

problems = 0
for p in sorted(glob.glob(os.path.join(ROOT, 'jobs/*/job.json'))):
    d = json.load(open(p, encoding='utf-8'))
    if 'rows' not in d:
        continue
    r = {x[1]: x[4] for x in d['rows']}
    slug = d['slug']
    msgs = []

    # 1) 说明里的数值
    audit = [x for x in d.get('defaults', []) if x.startswith('2026-11-14 现行口径全量复核')]
    if audit:
        s = audit[-1]
        m = re.search(r'基础\s*(-?\d+)、NA=(\d+)、总分\s*(-?\d+)', s)
        if not m:
            msgs.append('说明结算句格式异常')
        else:
            b, na, f = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if (b, na, f) != (d['base'], d['na'], d['final_score']):
                msgs.append('说明写 基础%s/NA%s/总分%s，实际 %s/%s/%s' % (b, na, f, d['base'], d['na'], d['final_score']))
        mb = re.search(r'加分\s*(-?\d+)', s)
        if not mb or int(mb.group(1)) != d['bonus']:
            msgs.append('说明加分与 bonus=%s 不符' % d['bonus'])
    else:
        msgs.append('缺少 2026-11-14 现行口径复核 说明')

    # 2) 改进建议/亮点里的分项分值表述
    for txt in d.get('improvements', []) + d.get('highlights', []):
        if SUM_OK.search(txt):
            continue
        for m in CLAIM.finditer(txt):
            code, val = m.group(1), int(m.group(2))
            cur = r.get(code)
            if isinstance(cur, (int, float)) and code in r and cur != val:
                msgs.append('%s 表述为 %d 分，实际 %g 分｜%s' % (code, val, cur, txt[:50]))

    # 3) 加分明细
    s = sum(v for k, v in r.items() if k in BON and isinstance(v, (int, float)))
    if abs(s - d['bonus']) > 0.01:
        msgs.append('加分明细合计 %g ≠ bonus %s' % (s, d['bonus']))

    # 4) 说明里不得残留历史重算链
    for x in d.get('defaults', []):
        if '重算' in x or '更正' in x or '→' in x:
            msgs.append('说明残留历史链：%s' % x[:40])

    if msgs:
        problems += len(msgs)
        print('[FAIL] %-32s' % slug)
        for m in msgs:
            print('        -', m)

print('---')
print('校验 %d 单，问题 %d 条' % (len(glob.glob(os.path.join(ROOT, 'jobs/*/job.json'))), problems))
sys.exit(1 if problems else 0)
