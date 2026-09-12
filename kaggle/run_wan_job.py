#!/usr/bin/env python3
"""Kaggle entry point for the official native Wan2.2 TI2V worker."""
import json
import os
import subprocess
import sys
from pathlib import Path


INPUT = Path('/kaggle/input')
OUTPUT = Path('/kaggle/working')
HERE = Path(__file__).resolve().parent


def explicit_path(backend, key, environment, label, must_be_dir=True):
    value = backend.get(key) or os.environ.get(environment)
    if not value:
        raise RuntimeError(f'{label} is required in backend.{key} or {environment}')
    path = Path(value).expanduser().resolve()
    if must_be_dir and not path.is_dir():
        raise RuntimeError(f'{label} directory does not exist: {path}')
    if not must_be_dir and not path.is_file():
        raise RuntimeError(f'{label} file does not exist: {path}')
    return path


def main():
    jobs_value = os.environ.get('NARRATED_VIDEO_JOB')
    if not jobs_value:
        raise RuntimeError('NARRATED_VIDEO_JOB must point to the prepared video_jobs.json')
    jobs = Path(jobs_value).expanduser().resolve()
    if not jobs.is_file():
        raise RuntimeError('video_jobs.json does not exist: ' + str(jobs))
    payload = json.loads(jobs.read_text(encoding='utf-8-sig'))
    backend = payload.get('backend', {})
    if backend.get('engine') not in (None, 'wan_native'):
        raise RuntimeError('This entry point supports only backend.engine=wan_native')
    wan_root = explicit_path(backend, 'source_path', 'WAN22_ROOT', 'Wan2.2 source')
    ckpt = explicit_path(backend, 'checkpoint_path', 'WAN22_CKPT',
                         'Wan2.2 checkpoint')
    worker = HERE / 'wan_worker.py'
    if not worker.is_file():
        raise RuntimeError('wan_worker.py is missing: ' + str(worker))
    world_size = int(backend.get('world_size', 1))
    if world_size < 1:
        raise RuntimeError('backend.world_size must be positive')
    command = [sys.executable, '-m', 'torch.distributed.run',
               '--nproc_per_node=' + str(world_size), str(worker),
               '--jobs', str(jobs), '--wan-root', str(wan_root),
               '--ckpt-dir', str(ckpt), '--output-root', str(OUTPUT)]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()

