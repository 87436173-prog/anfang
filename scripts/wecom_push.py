# -*- coding: utf-8 -*-
"""企微群机器人推送暗访评分报告（wecom-webhook-push-2026-11-17-v1）。

在 publish + 归档完成后调用：
    python wecom_push.py --job-dir <job目录>

流程：
1. 读取 job 目录的 published.json / case-summary.json / job.json 组装摘要；
2. 发送 markdown 摘要消息（总分、档位、模块分、扣分要点）；
3. 发送 PNG 报告图片消息（>2MB 时自动压缩，PIL 可用时）；
4. 每条消息失败自动重试 1 次；全部结果写入 <job-dir>/wecom-push.json。
5. 静默时段 22:00–08:00 不推送（--force 可临时越权），改为登记到待推清单，
   由下一个允许时段用 --pending 补推。

Webhook 地址只从配置文件读取（默认 C:/Users/no02/.workbuddy/config/wecom-webhook.json），
绝不硬编码。推送失败不阻断打分主流程。
"""
import argparse
import base64
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = Path.home() / '.workbuddy' / 'config' / 'wecom-webhook.json'
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MODULE_ORDER = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
QUIET_START_HOUR = 22   # 22:00 起静默
QUIET_END_HOUR = 8      # 次日 08:00 前静默
PENDING_FILE = Path('C:/Users/no02/WorkBuddy/2026-11-10-09-14-36/暗访打分日报/_待推清单.json')


def in_quiet_hours(now=None):
    """22:00–次日 08:00 为静默时段，群内不推送任何结果。"""
    h = (now or datetime.now()).hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def load_pending():
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def save_pending(items):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


def add_pending(job_dir, reason):
    items = load_pending()
    jd = str(Path(job_dir).resolve())
    for it in items:
        if it.get('job_dir') == jd:
            it['deferred_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            it['reason'] = reason
            save_pending(items)
            return
    items.append({'job_dir': jd, 'deferred_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                  'reason': reason})
    save_pending(items)


def drop_pending(job_dir):
    jd = str(Path(job_dir).resolve())
    items = [it for it in load_pending() if it.get('job_dir') != jd]
    save_pending(items)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_config(config_path):
    p = Path(config_path)
    if not p.exists():
        raise SystemExit(
            f'[企微推送] 配置文件不存在：{p}\n'
            f'请在目标企微群添加群机器人后，把 Webhook 地址写入该文件：\n'
            f'{{"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"}}')
    cfg = load_json(p)
    url = (cfg.get('webhook_url') or '').strip()
    if not url:
        raise SystemExit(f'[企微推送] {p} 中 webhook_url 为空，请填入群机器人的 Webhook 地址。')
    if 'qyapi.weixin.qq.com/cgi-bin/webhook/send' not in url:
        raise SystemExit(f'[企微推送] webhook_url 不是企微群机器人地址：{url[:60]}...')
    return cfg, url


def read_job_data(job_dir):
    """从 job 目录读取推送所需的字段，兼容缺文件的情况。"""
    jd = Path(job_dir)
    pub = load_json(jd / 'published.json') if (jd / 'published.json').exists() else {}
    case = load_json(jd / 'case-summary.json') if (jd / 'case-summary.json').exists() else {}
    job = load_json(jd / 'job.json') if (jd / 'job.json').exists() else {}
    score = case.get('score', pub.get('score'))
    if score is None:
        raise SystemExit('[企微推送] 未找到评分结果（published.json / case-summary.json），请先完成 publish。')
    penalty = case.get('negative_incentive', pub.get('negative_incentive'))
    png = pub.get('png')
    return {
        'slug': job.get('slug') or jd.name,
        'sales': job.get('sales', '未知'),
        'customer': job.get('customer', ''),
        'car': job.get('car', ''),
        'reception_date': job.get('reception_date') or case.get('date') or '',
        'base': job.get('base'),
        'na': job.get('na', 0),
        'bonus': job.get('bonus', 0),
        'modules': job.get('modules', []),
        'deductions': job.get('deductions') or pub.get('deductions', []),
        'score': score,
        'penalty': penalty,
        'png': png,
        'revise_reason': job.get('revise_reason', ''),
    }


def grade_and_incentive(score):
    """与 SKILL.md 归档口径一致的档位与负激励（以分数为准）。"""
    if score >= 90:
        return '优秀', 0
    if score >= 80:
        return '合格', 0
    if score >= 70:
        return '达标', 0
    if score >= 60:
        return '负激励 2 万', 20000
    if score >= 1:
        return '负激励 5 万', 50000
    return '负激励 8 万', 80000


def _num(v):
    """模块分/基础分统一成整数样式，避免 10.0/25.0 这种群消息里难看的写法。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if abs(f - round(f)) < 1e-9 else f'{f:.1f}'


def build_markdown(d):
    grade, inc = grade_and_incentive(d['score'])
    title = f"## 📋 暗访评分｜{d['sales']}"
    if d['customer']:
        title += f" · {d['customer']}"
    lines = [title, f"**总分：{_num(d['score'])} 分（{grade}）**"]
    if inc:
        lines.append(f"> ⚠️ {grade}")
    info = []
    if d['car']:
        info.append(f"车型：{d['car']}")
    if d['reception_date']:
        info.append(f"接待日期：{d['reception_date']}")
    if info:
        lines.append('- ' + ' · '.join(info))
    if d['modules']:
        parts = []
        for m in d['modules']:
            name, full, got = m[0], m[1], m[2]
            parts.append(f"{name} {_num(got)}/{_num(full)}")
        lines.append('> ' + ' · '.join(parts))
    sub = []
    if d['base'] is not None:
        sub.append(f"基础 {_num(d['base'])}")
    if d.get('na'):
        sub.append(f"NA {_num(d['na'])}")
    if d.get('bonus'):
        sub.append(f"加分 {_num(d['bonus'])}")
    if sub:
        lines.append('> ' + ' · '.join(sub))
    if d['deductions']:
        lines.append('**主要扣分**')
        for item, reason in d['deductions'][:3]:
            lines.append(f"- {item}：{reason}")
        if len(d['deductions']) > 3:
            lines.append(f"- ……等共 {len(d['deductions'])} 项，详见完整报告")
    return '\n'.join(lines)


def post_webhook(url, payload, retries=2):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode('utf-8'))
            if body.get('errcode') == 0:
                return {'status': 'ok', 'errcode': 0, 'attempt': attempt}
            last = {'status': 'failed', 'errcode': body.get('errcode'),
                    'errmsg': body.get('errmsg', ''), 'attempt': attempt}
        except Exception as e:  # 网络/超时
            last = {'status': 'failed', 'errcode': None,
                    'errmsg': f'{type(e).__name__}: {e}', 'attempt': attempt}
        if attempt < retries:
            time.sleep(2)
    return last


def prepare_image(png_path):
    """读取 PNG 并确保 ≤2MB（超限时用 PIL 压缩到临时文件）。"""
    p = Path(png_path)
    if not p.exists():
        raise FileNotFoundError(f'报告 PNG 不存在：{p}')
    raw = p.read_bytes()
    if len(raw) <= MAX_IMAGE_BYTES:
        return raw, str(p)
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(raw))
        scale = 0.9
        while scale > 0.3:
            w, h = img.size
            small = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            small.save(buf, format='PNG', optimize=True)
            if buf.tell() <= MAX_IMAGE_BYTES:
                return buf.getvalue(), f'{p}（压缩至{buf.tell() // 1024}KB）'
            scale -= 0.1
    except ImportError:
        pass
    raise ValueError(f'PNG 超过 2MB 且无法压缩：{p}（{len(raw) // 1024}KB）')


def send_markdown(url, markdown):
    return post_webhook(url, {'msgtype': 'markdown',
                              'markdown': {'content': markdown[:4096]}})


def send_image(url, png_path):
    raw, note = prepare_image(png_path)
    payload = {'msgtype': 'image',
               'image': {'base64': base64.b64encode(raw).decode(),
                         'md5': hashlib.md5(raw).hexdigest()}}
    r = post_webhook(url, payload)
    r['note'] = note
    return r


def build_revise_notice(d, revise):
    """修订版作废声明：群机器人消息无 msgid、无法撤回，只能用声明+新卡覆盖。"""
    old_score, old_at = (revise.split('@') + [''])[:2] if revise else ('', '')
    lines = ["## ⚠️ 报告作废声明",
             f"> 此前推送的《{d['sales']} · {d['customer']}》报告作废，以随后推送的修订版为准。"]
    detail = []
    if old_at:
        detail.append(f"原推送时间：{old_at}")
    if old_score:
        detail.append(f"原分 {old_score} → 修订后 {_num(d['score'])} 分")
    if detail:
        lines.append('> ' + ' · '.join(detail))
    if d.get('revise_reason'):
        lines.append(f"> 修订原因：{d['revise_reason']}")
    return '\n'.join(lines)


def push_one(job_dir, url, skip_image=False, revise=None):
    """推送单个 job 的报告，返回结果字典（并写入 wecom-push.json）。

    revise="旧分@旧推送时间" 时按修订版推送：先发作废声明，再发带修订标识的摘要与图片。
    """
    d = read_job_data(job_dir)
    results = {'pushed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
               'job_dir': str(Path(job_dir).resolve()),
               'slug': d['slug'], 'score': d['score'],
               'revise': revise or None, 'messages': []}

    if revise:
        notice = send_markdown(url, build_revise_notice(d, revise))
        results['messages'].append({'type': 'revise_notice', **notice})
        print(f"[企微推送] {d['slug']} 作废声明：{notice['status']}")

    md_text = build_markdown(d)
    if revise:
        old = revise.split('@')[0] if revise else ''
        md_text = (f"> 🔁 修订版：取代此前推送的 {old} 分版本，旧卡片作废\n" + md_text)
    md = send_markdown(url, md_text)
    results['messages'].append({'type': 'markdown', **md})
    print(f"[企微推送] {d['slug']} 摘要消息：{md['status']}")

    if not skip_image:
        if not d.get('png'):
            img_r = {'status': 'skipped', 'errmsg': 'published.json 中无 png 路径'}
        else:
            try:
                img_r = send_image(url, d['png'])
            except Exception as e:
                img_r = {'status': 'failed', 'errmsg': str(e)}
        results['messages'].append({'type': 'image', **img_r})
        print(f"[企微推送] {d['slug']} 报告图片：{img_r['status']}")

    ok = all(m.get('status') in ('ok', 'skipped') for m in results['messages'])
    results['overall'] = 'ok' if ok else 'failed'
    out = Path(job_dir) / 'wecom-push.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[企微推送] 结果已记录：{out}（overall={results['overall']}）")
    return results


def record_deferred(job_dir, reason):
    """静默时段：不发送，写 wecom-push.json 为 deferred 并登记待推清单。"""
    res = {'pushed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'job_dir': str(Path(job_dir).resolve()),
           'overall': 'deferred', 'reason': reason, 'messages': []}
    out = Path(job_dir) / 'wecom-push.json'
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    add_pending(job_dir, reason)
    print(f'[企微推送] 静默时段（22:00–08:00），已跳过并登记待推：{job_dir}')


def main():
    ap = argparse.ArgumentParser(description='推送暗访评分报告到企微群机器人')
    ap.add_argument('--job-dir', type=Path, help='待推送的 job 目录')
    ap.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    ap.add_argument('--skip-image', action='store_true', help='只发文字摘要')
    ap.add_argument('--pending', action='store_true',
                    help='补推待推清单中的全部报告（建议在 08:00–22:00 执行）')
    ap.add_argument('--force', action='store_true',
                    help='忽略静默时段限制（仅人工临时使用）')
    ap.add_argument('--revise', metavar='旧分@旧推送时间',
                    help='按修订版推送：先发作废声明，摘要与图片带修订标识，如 73@2026-11-17 21:32')
    args = ap.parse_args()

    cfg, url = load_config(args.config)
    quiet = in_quiet_hours()

    if args.pending:
        items = load_pending()
        if not items:
            print('[企微推送] 待推清单为空，无需补推。')
            return
        if quiet and not args.force:
            print(f'[企微推送] 当前处于静默时段（22:00–08:00），待推 {len(items)} 份，'
                  f'不在群内推送；请在 08:00–22:00 之间执行 --pending。')
            return
        print(f'[企微推送] 开始补推 {len(items)} 份待推报告…')
        ok_count = 0
        for it in list(items):
            jd = it['job_dir']
            if not Path(jd).exists():
                print(f'[企微推送] 目录已不存在，移出清单：{jd}')
                drop_pending(jd)
                continue
            r = push_one(jd, url, args.skip_image)
            if r['overall'] == 'ok':
                drop_pending(jd)
                ok_count += 1
        remaining = len(load_pending())
        print(f'[企微推送] 补推完成：成功 {ok_count} 份，仍待推 {remaining} 份')
        if remaining:
            sys.exit(1)
        return

    if not args.job_dir:
        ap.error('--job-dir 或 --pending 必填')

    if quiet and not args.force:
        record_deferred(args.job_dir, 'quiet_hours_22-08')
        return

    r = push_one(args.job_dir, url, args.skip_image, args.revise)
    if r['overall'] != 'ok':
        print('[企微推送] 存在失败消息，归档交付不受影响；可重新执行本脚本重推。',
              file=sys.stderr)
        sys.exit(1)



if __name__ == '__main__':
    main()
