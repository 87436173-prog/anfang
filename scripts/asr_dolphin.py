#!/usr/bin/env python3
"""Dolphin-CN-Dialect (small.cn) 全量主转写，输出与历史 whisper transcript 一致的 jsonl schema。

版本：asr-dolphin-cn-dialect-2026-11-14-v1（见 references/asr-model-policy.md）

用法（PYTHONPATH 需指向 dolphin 虚拟环境根目录）：
  PYTHONPATH=<venv根目录> python scripts/asr_dolphin.py <audio> <out.jsonl> [--threads 6]

输出每行：{"t0": 厘秒, "t1": 厘秒, "text": "..."}
"""
import os
import sys
import json
import time
import re
import argparse

# 可用环境变量覆盖：DOLPHIN_VENV 指向装好 funasr/torch 的虚拟环境 Scripts 目录
VENV = os.environ.get("DOLPHIN_VENV") or r"C:/Users/no02/WorkBuddy/2026-11-13-17-08-59/.venv-dolphin/Scripts"
os.environ["PATH"] = VENV + os.pathsep + os.environ.get("PATH", "")

# 可用 DOLPHIN_MODEL_DIR 覆盖（snapshot 目录内含 small.cn.pt）
MODEL_DIR = os.environ.get("DOLPHIN_MODEL_DIR") or r"C:/Users/no02/.cache/modelscope/models/DataoceanAI--dolphin-cn-dialect-small/snapshots/master"

TAG = re.compile(r"<[^>]{1,16}>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--region", default="CN")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--model", default="small.cn")
    a = ap.parse_args()

    import torch
    torch.set_num_threads(a.threads)

    # patch torchaudio.load -> soundfile（规避 torchcodec/ffmpeg 后端缺失）
    import torchaudio
    import soundfile as sf
    import soxr
    import numpy as np

    def _load(uri, *args, **kw):
        if isinstance(uri, torch.Tensor):
            return uri, 16000
        data, sr = sf.read(str(uri), dtype="float32", always_2d=True)
        wav = torch.from_numpy(np.ascontiguousarray(data.T))
        if sr != 16000:
            wav = torch.from_numpy(np.ascontiguousarray(soxr.resample(wav.numpy(), sr, 16000)))
            sr = 16000
        return wav, sr

    torchaudio.load = _load

    import dolphin

    t0 = time.time()
    model = dolphin.load_model(a.model, model_dir=MODEL_DIR)
    print(f"[load] {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    t1 = time.time()
    from dolphin.transcribe import transcribe_long
    res = transcribe_long(
        model, a.audio, lang_sym="zh", region_sym=a.region,
        predict_time=True, word_timestamp=False,
        decoding_method="attention_rescoring", beam_size=10,
    )
    el = time.time() - t1
    segs = res if isinstance(res, list) else [res]
    print(f"[asr] {len(segs)} segs  {el:.1f}s", file=sys.stderr, flush=True)

    with open(a.out, "w", encoding="utf-8") as f:
        for s in segs:
            txt = TAG.sub("", str(getattr(s, "text_nospecial", None) or s.text)).strip()
            if not txt:
                continue
            st = float(getattr(s, "start", 0.0) or 0.0)
            en = float(getattr(s, "end", 0.0) or 0.0)
            f.write(json.dumps({
                "t0": int(round(st * 100)),
                "t1": int(round(en * 100)),
                "text": txt,
            }, ensure_ascii=False) + "\n")

    print(f"[done] -> {a.out}  total {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
