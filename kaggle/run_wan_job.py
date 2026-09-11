#!/usr/bin/env python3
"""Kaggle entry point that discovers mounted inputs and launches two Wan ranks."""
import json
import os
import subprocess
import sys
from pathlib import Path


INPUT = Path('/kaggle/input')
OUTPUT = Path('/kaggle/working')
HERE = Path(__file__).resolve().parent


def one(candidates, label):
    values = sorted({Path(value).resolve() for value in candidates})
    if len(values) != 1:
        raise RuntimeError('Expected exactly one ' + label + '; found: ' +
                           ', '.join(str(value) for value in values))
    return values[0]


def configured_path(environment, candidates, label):
    value = os.environ.get(environment)
    return Path(value).resolve() if value else one(candidates, label)


def main():
    jobs = configured_path('NARRATED_VIDEO_JOB', INPUT.rglob('video_jobs.json'),
                           'video_jobs.json under /kaggle/input')
    payload = json.loads(jobs.read_text(encoding='utf-8-sig'))
    backend = payload.get('backend', {})
    wan_root = configured_path(
        'WAN22_ROOT', (path.parent for path in INPUT.rglob('generate.py')
                       if (path.parent / 'wan').is_dir()), 'Wan2.2 source tree')
    ckpt = configured_path(
        'WAN22_CKPT', (path.parent for path in INPUT.rglob('Wan2.2_VAE.pth')),
        'Wan2.2 TI2V-5B checkpoint directory')
    world_size = int(backend.get('world_size', 2))
    command = [sys.executable, '-m', 'torch.distributed.run',
               '--nproc_per_node=' + str(world_size), str(HERE / 'wan_worker.py'),
               '--jobs', str(jobs), '--wan-root', str(wan_root),
               '--ckpt-dir', str(ckpt), '--output-root', str(OUTPUT)]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()

