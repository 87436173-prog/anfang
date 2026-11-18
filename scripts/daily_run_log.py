# -*- coding: utf-8 -*-
"""暗访打分每日运行日志（daily-run-log-2026-11-17-v1）。

把本次定时任务的运行结果追加到固定日志文件，跨天可追溯：
    暗访打分日报/_运行日志.md

用法（定时任务归档与推送完成后调用一次）：
    python daily_run_log.py --date 2026-11-17 --job <job目录1> --job <job目录2>
    python daily_run_log.py --date 2026-11-17 --no-new        # 当日无新增录音

每条 job 的推送状态取自该目录下的 wecom-push.json（wecom_push.py 产物）；
无该文件视为未推送。日志为追加写入，同一天重复执行只追加新的运行块。
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path('C:/Users/no02/WorkBuddy/2026-11-10-09-14-36/暗访打分日报')
LOG_NAME = '_运行日志.md'
HEADER = ('# 暗访打分运行日志\n\n'
          '| 运行时间 | 日期 | 销售 | 客户 | 总分 | 档位 | 推送 | 备注 |\n'
          '|---|---|---|---|---|---|---|---|\n')


def load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return {}


def grade(score):
    if score is None:
        return '—'
    if score >= 90:
        return '优秀'
    if score >= 80:
        return '合格'
    if score >= 70:
        return '达标'
    if score >= 60:
        return '负激励2万'
    if score >= 1:
        return '负激励5万'
    return '负激励8万'


def job_row(job_dir):
    jd = Path(job_dir)
    job = load_json(jd / 'job.json')
    pub = load_json(jd / 'published.json')
    case = load_json(jd / 'case-summary.json')
    push = load_json(jd / 'wecom-push.json')
    score = case.get('score', pub.get('score'))
    sales = job.get('sales') or jd.name
    customer = job.get('customer', '') or ''
    if push:
        status = push.get('overall', '?')
        if status == 'ok':
            push_txt = '✅ 已推送'
        elif status == 'deferred':
            push_txt = '⏸ 静默跳过(待补推)'
        else:
            bad = [m.get('type') for m in push.get('messages', []) if m.get('status') == 'failed']
            push_txt = '❌ 失败(' + ','.join(bad) + ')' if bad else '❌ 失败'
    elif (jd / 'published.json').exists():
        push_txt = '⚪ 未推送'
    else:
        push_txt = '— 未出报告'
    note = []
    if not (jd / 'published.json').exists():
        note.append('缺published.json')
    if push and push.get('overall') == 'failed':
        note.append('可重推')
    # 日期列优先取 job.json 的接待日期，其次从目录名前 8 位（YYYYMMDD）还原
    date_txt = job.get('reception_date') or job.get('report_date') or ''
    if not date_txt:
        head = jd.name[:8]
        date_txt = (f'{head[:4]}-{head[4:6]}-{head[6:]}' if head.isdigit() else jd.name)
    return (f"| {time.strftime('%Y-%m-%d %H:%M')} | {date_txt} | {sales} | {customer} "
            f"| {score if score is not None else '—'} | {grade(score)} | {push_txt} | {'；'.join(note)} |\n")


def main():
    ap = argparse.ArgumentParser(description='追加暗访打分运行日志')
    ap.add_argument('--date', required=True, help='任务日期 YYYY-MM-DD')
    ap.add_argument('--job', action='append', default=[], help='job 目录，可重复')
    ap.add_argument('--no-new', action='store_true', help='当日无新增录音')
    ap.add_argument('--root', type=Path, default=ROOT)
    args = ap.parse_args()

    log = args.root / LOG_NAME
    args.root.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text(HEADER, encoding='utf-8')

    if args.no_new or not args.job:
        block = f"| {time.strftime('%Y-%m-%d %H:%M')} | {args.date} | — | — | — | — | — | 当日无新增录音 |\n"
    else:
        block = ''.join(job_row(j) for j in args.job)
        ok = sum(1 for j in args.job if load_json(Path(j) / 'wecom-push.json').get('overall') == 'ok')
        block += (f"| {time.strftime('%Y-%m-%d %H:%M')} | {args.date} | — | — | — | — | "
                  f"{ok}/{len(args.job)} 成功 | 本次运行结束 |\n")

    with log.open('a', encoding='utf-8') as f:
        f.write(block)
    print(json.dumps({'log': str(log.resolve()), 'rows': block.count('\n')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
