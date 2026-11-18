# -*- coding: utf-8 -*-
"""publish 步骤：把 job.json 的评分结果 + 报告 PNG 固化为 published.json。

用途：
- wecom_push.py 依赖 published.json 的 score / png 字段，缺失会直接退出；
- 早期批次（如 2026-11-16）只写了 job.json，没有 published.json，可用本脚本补齐。

用法：
    python publish_job.py --job-dir <job目录> [--png <指定PNG>]

产出：
    <job目录>/published.json
    {
      "slug", "score", "negative_incentive", "png", "published_at",
      "modules", "base", "na", "bonus", "deductions"
    }
不修改 job.json，不重算分数（分数以 job.json 的 final_score 为准）。
"""
import argparse
import json
import re
import time
from pathlib import Path

ITEM_RE = re.compile(r'^([A-Z]\d+[a-z]?)\s*[^：:]{0,12}[：:]\s*(.+)$')


def build_deductions(job):
    """从 improvements 里提取「项号：原因」，作为群消息的主要扣分（最多 3 条）。"""
    out = []
    for s in job.get('improvements', []) or []:
        m = ITEM_RE.match(s.strip())
        if not m:
            continue
        code, reason = m.group(1), m.group(2).strip()
        reason = re.split(r'[。；]', reason)[0].strip()
        head = reason.split('，')[0].strip()
        if len(head) >= 12:
            reason = head
        if len(reason) > 40:
            reason = reason[:40] + '…'
        item = f"{code}{_name_of(job, code)}"
        out.append([item, reason])
    # 去重（同一项号只留第一条）
    seen, uniq = set(), []
    for item, reason in out:
        code = re.match(r'^([A-Z]\d+[a-z]?)', item).group(1)
        if code in seen:
            continue
        seen.add(code)
        uniq.append([item, reason])
    return uniq[:3]


def _name_of(job, code):
    for r in job.get('rows', []) or []:
        if len(r) > 2 and r[1] == code:
            return str(r[2])
    return ''


def main():
    ap = argparse.ArgumentParser(description='生成 published.json')
    ap.add_argument('--job-dir', type=Path, required=True)
    ap.add_argument('--png', type=str, default=None, help='报告 PNG 路径（默认取 report/*.png 第一张）')
    args = ap.parse_args()

    jd = Path(args.job_dir)
    job_path = jd / 'job.json'
    if not job_path.exists():
        raise SystemExit(f'[publish] 缺少 job.json：{job_path}')
    job = json.loads(job_path.read_text(encoding='utf-8'))

    score = job.get('final_score')
    if score is None:
        raise SystemExit(f'[publish] job.json 缺 final_score，请先跑 finalize_job.py：{job_path}')

    if args.png:
        png = Path(args.png)
    else:
        cands = sorted((jd / 'report').glob('*.png'))
        png = cands[0] if cands else None
    if png is None or not png.exists():
        raise SystemExit(f'[publish] 未找到报告 PNG，请先渲染：{jd / "report"}')

    data = {
        'slug': job.get('slug') or jd.name,
        'score': score,
        'negative_incentive': job.get('negative_incentive'),
        'png': str(png.resolve()),
        'published_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'modules': job.get('modules', []),
        'base': job.get('base'),
        'na': job.get('na', 0),
        'bonus': job.get('bonus', 0),
        'deductions': build_deductions(job),
    }
    out = jd / 'published.json'
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"[publish] {data['slug']}  score={score}  png={png.name}  deductions={len(data['deductions'])}")


if __name__ == '__main__':
    main()
