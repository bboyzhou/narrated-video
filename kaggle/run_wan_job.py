#!/usr/bin/env python3
"""Kaggle entry point for the official native Wan2.2 TI2V worker."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


INPUT = Path('/kaggle/input')
OUTPUT = Path('/kaggle/working')
HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


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


def fixed_path(value, candidates, label, must_be_dir=True):
    if value:
        path = Path(value).expanduser().resolve()
        if (path.is_dir() if must_be_dir else path.is_file()):
            return path
        raise RuntimeError(f'{label} does not exist: {path}')
    existing = [Path(item).resolve() for item in candidates
                if (Path(item).is_dir() if must_be_dir else Path(item).is_file())]
    if len(existing) != 1:
        raise RuntimeError(f'Expected exactly one {label}; found: ' +
                           ', '.join(str(item) for item in existing))
    return existing[0]


def classify(error):
    text = str(error)
    if 'E_GPU_UNSUPPORTED' in text:
        return 'E_GPU_UNSUPPORTED'
    if isinstance(error, subprocess.CalledProcessError):
        if error.returncode == -9:
            return 'E_SIGKILL'
        if isinstance(error.cmd, (list, tuple)) and 'pip' in ' '.join(map(str, error.cmd)):
            return 'E_DEPENDENCY'
        return 'E_GENERATION'
    if 'No module named' in text:
        return 'E_DEPENDENCY'
    if 'checkpoint' in text.lower() or 'Wan2.2 source' in text:
        return 'E_MODEL'
    if isinstance(error, (FileNotFoundError, OSError)):
        return 'E_INPUT'
    return 'E_CONFIG'


def gpu_inventory():
    command = [
        'nvidia-smi',
        '--query-gpu=name,memory.total,compute_cap',
        '--format=csv,noheader,nounits',
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True,
                                   text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError('E_GPU_UNSUPPORTED: nvidia-smi GPU query failed: ' +
                           str(error)) from error
    devices = []
    for line in completed.stdout.splitlines():
        fields = [item.strip() for item in line.split(',')]
        if len(fields) != 3:
            raise RuntimeError('E_GPU_UNSUPPORTED: unexpected nvidia-smi output: ' + line)
        devices.append({
            'name': fields[0],
            'memory_total_mib': int(fields[1]),
            'compute_capability': fields[2],
        })
    if not devices:
        raise RuntimeError('E_GPU_UNSUPPORTED: Kaggle did not allocate a GPU')
    return devices


def validate_gpu(backend, devices):
    execution = backend.get('execution') or backend.get('generation') or {}
    minimum_vram = 14 if execution.get('frame_num', 5) <= 5 else 22
    if execution:
        if not devices:
            actual = ', '.join(item['name'] for item in devices)
            raise RuntimeError(
                'E_GPU_UNSUPPORTED: Wan2.2 RuntimePlan requires a CUDA GPU; '
                f'Kaggle allocated: {actual}.')
        if devices[0]['memory_total_mib'] < minimum_vram * 1024:
            raise RuntimeError(
                f'E_GPU_UNSUPPORTED: RuntimePlan requires at least {minimum_vram} GiB VRAM')


def bootstrap(backend):
    if backend.get('offline', False):
        return
    packages = backend.get('bootstrap_packages', [])
    if not packages:
        return
    command = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
               '--no-input', *packages]
    subprocess.run(command, check=True)


def main():
    results = OUTPUT / 'results.json'
    try:
        jobs = fixed_path(
            os.environ.get('NARRATED_VIDEO_JOB'),
            [INPUT / 'narrated-video-wan-demo-input' / 'video_jobs.json',
             INPUT / 'video_jobs.json', HERE / 'video_jobs.json'],
            'video_jobs.json', must_be_dir=False)
        payload = json.loads(jobs.read_text(encoding='utf-8-sig'))
        if payload.get('version') != 3 or payload.get('provider') != 'wan22':
            raise RuntimeError('E_CONFIG: expected version 3 wan22 manifest')
        backend = payload.get('provider_config', {})
        runtime_plan = payload.get('runtime_plan', {})
        if backend.get('engine') != 'wan_native':
            raise RuntimeError('E_CONFIG: this entry point requires provider_config.engine=wan_native')
        if backend.get('model') != 'Wan-AI/Wan2.2-TI2V-5B':
            raise RuntimeError('E_CONFIG: unsupported Wan2.2 model')
        revision = backend.get('model_revision')
        if (not isinstance(revision, str) or not revision.strip() or
                revision in ('main', 'latest')):
            raise RuntimeError('E_CONFIG: a pinned model_revision is required')
        wan_root = fixed_path(
            backend.get('source_path') or os.environ.get('WAN22_ROOT'),
            [INPUT / 'wan22-official-source-42bf4cf',
             INPUT / 'narrated-video-wan-runtime-v1'], 'Wan2.2 source')
        ckpt = fixed_path(
            backend.get('checkpoint_path') or os.environ.get('WAN22_CKPT'),
            [INPUT / 'datasets' / 'ihsannika' / 'wan2-2-ti2v-5b' / 'Wan2.2-TI2V-5B',
             INPUT / 'wan2-2-ti2v-5b' / 'Wan2.2-TI2V-5B'], 'Wan2.2 checkpoint')
        worker = fixed_path(
            os.environ.get('WAN22_WORKER'),
            [HERE / 'wan_worker.py', wan_root / 'wan_worker.py'],
            'wan_worker.py', must_be_dir=False)
        world_size = int((runtime_plan.get('execution') or {}).get('world_size', 1))
        if world_size != 1:
            raise RuntimeError('The stable Kaggle profile requires world_size=1')
        devices = gpu_inventory()
        preflight = {
            'ok': False, 'mode': 'kaggle-entry',
            'python': sys.executable, 'jobs': str(jobs),
            'wan_root': str(wan_root), 'checkpoint': str(ckpt),
            'worker': str(worker), 'gpus': devices,
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        try:
            validate_gpu(runtime_plan, devices)
        except RuntimeError as error:
            preflight['error'] = str(error)
            write_json(OUTPUT / 'preflight.json', preflight)
            raise
        preflight['ok'] = True
        write_json(OUTPUT / 'preflight.json', preflight)
        bootstrap(backend)
        command = [sys.executable, str(worker), '--jobs', str(jobs),
                   '--wan-root', str(wan_root), '--ckpt-dir', str(ckpt),
                   '--output-root', str(OUTPUT)]
        env = os.environ.copy()
        for key in ('RANK', 'WORLD_SIZE', 'LOCAL_RANK', 'LOCAL_WORLD_SIZE',
                    'MASTER_ADDR', 'MASTER_PORT'):
            env.pop(key, None)
        subprocess.run(command, check=True, env=env)
    except Exception as error:
        write_json(results, {'version': 3, 'provider': 'wan22',
                             'results': [{'id': None, 'status': 'failed',
                                          'code': classify(error),
                                          'error': str(error)}]})
        raise


if __name__ == '__main__':
    main()

