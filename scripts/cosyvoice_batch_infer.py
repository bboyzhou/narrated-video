#!/usr/bin/env python3
"""Generate multiple CosyVoice sentence WAVs after loading the model once.

This adapter is intentionally separate from pipeline.py because it must run in
the user-selected CosyVoice Python environment.  The jobs manifest is UTF-8
JSON with a ``jobs`` array containing ``text`` and absolute ``output`` paths.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cosyvoice-root', required=True)
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--jobs-file', required=True)
    parser.add_argument('--speaker', default='中文男')
    parser.add_argument('--speed', type=float, default=1.0)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--wetext-model', help='Optional existing local ModelScope wetext directory')
    return parser.parse_args()


def configure_local_wetext(path):
    if not path:
        return
    local = Path(path).expanduser().resolve()
    if not local.is_dir():
        raise ValueError('wetext-model directory unavailable: ' + str(local))
    import modelscope
    original = modelscope.snapshot_download

    def local_snapshot(model_id, *args, **kwargs):
        if str(model_id).rstrip('/').endswith('/wetext') or str(model_id) == 'wetext':
            return str(local)
        return original(model_id, *args, **kwargs)

    modelscope.snapshot_download = local_snapshot


def save_pcm_wav(torchaudio, speech, sample_rate, output, speed, ffmpeg):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not 0.5 <= speed <= 2.0:
        raise ValueError('speed must be between 0.5 and 2.0')
    raw = output.with_suffix('.raw.wav') if abs(speed - 1.0) > 1e-6 else output
    torchaudio.save(str(raw), speech.cpu(), sample_rate, encoding='PCM_S', bits_per_sample=16)
    if raw == output:
        return
    executable = ffmpeg or shutil.which('ffmpeg')
    if not executable:
        raw.unlink(missing_ok=True)
        raise ValueError('FFmpeg is required when CosyVoice speed is not 1.0')
    try:
        subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                        '-i', str(raw), '-filter:a', f'atempo={speed}', '-c:a', 'pcm_s16le',
                        str(output)], check=True, capture_output=True)
    finally:
        raw.unlink(missing_ok=True)


def main():
    args = parse_args()
    root = Path(args.cosyvoice_root).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve()
    jobs_file = Path(args.jobs_file).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('cosyvoice-root directory unavailable: ' + str(root))
    if not model_path.exists():
        raise ValueError('model-path unavailable: ' + str(model_path))
    manifest = json.loads(jobs_file.read_text(encoding='utf-8-sig'))
    jobs = manifest.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('jobs-file must contain a nonempty jobs array')
    for job in jobs:
        if not str(job.get('text', '')).strip() or not job.get('output'):
            raise ValueError('Each CosyVoice job requires nonempty text and output')

    # Do not allow implicit downloads when the surrounding runtime selected
    # offline operation.  The variables are harmless when already configured.
    if manifest.get('offline', False):
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
    sys.path.insert(0, str(root))
    matcha = root / 'third_party' / 'Matcha-TTS'
    if matcha.is_dir():
        sys.path.insert(0, str(matcha))
    configure_local_wetext(args.wetext_model)

    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    started = time.perf_counter()
    model = AutoModel(model_dir=str(model_path))
    loaded = time.perf_counter()
    speakers = model.list_available_spks()
    if args.speaker not in speakers:
        raise ValueError(f'Unknown speaker {args.speaker}; available: {speakers}')
    timings = []
    for job in jobs:
        item_started = time.perf_counter()
        result = next(model.inference_sft(str(job['text']), args.speaker, stream=False))
        save_pcm_wav(torchaudio, result['tts_speech'], model.sample_rate, job['output'],
                     args.speed, args.ffmpeg)
        timings.append({'id': str(job.get('id', '')), 'seconds': round(time.perf_counter() - item_started, 3)})
    print(json.dumps({'generated': len(jobs), 'model_load_seconds': round(loaded - started, 3),
                      'total_seconds': round(time.perf_counter() - started, 3),
                      'jobs': timings}, ensure_ascii=False))


if __name__ == '__main__':
    main()
