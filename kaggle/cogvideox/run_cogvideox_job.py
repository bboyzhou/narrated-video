#!/usr/bin/env python3
"""Kaggle entry point for CogVideoX-5B-I2V INT8 on one Tesla T4."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path


INPUT = Path('/kaggle/input')
OUTPUT = Path('/kaggle/working')
MODULE_NAMES = {
    'torchao': 'torchao',
    'sentencepiece': 'sentencepiece',
    'imageio': 'imageio',
    'imageio-ffmpeg': 'imageio_ffmpeg',
}
FORBIDDEN_JOB_FIELDS = {
    'provider', 'profile', 'runtime', 'dtype', 'offload', 'world_size',
    'attention_backend', 'teacache',
    'frame_num', 'output_fps', 'inference_steps', 'guidance_scale',
}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def discover_manifest():
    matches = []
    for path in INPUT.rglob('video_jobs.json'):
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (payload.get('version') == 3 and
                payload.get('provider') == 'cogvideox' and
                isinstance(payload.get('jobs'), list)):
            matches.append(path)
    return sorted(matches, key=str)


def fixed_manifest(value=None):
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file():
            return path
        raise RuntimeError(f'E_INPUT: video_jobs.json does not exist: {path}')
    candidates = [
        INPUT / 'datasets' / 'connorbrooksz' /
        'narrated-video-cogvideox-demo-input' / 'video_jobs.json',
        INPUT / 'narrated-video-cogvideox-demo-input' / 'video_jobs.json',
    ]
    matches = [path.resolve() for path in candidates if path.is_file()]
    if not matches:
        matches = discover_manifest()
    if len(matches) != 1:
        raise RuntimeError('E_INPUT: expected exactly one CogVideoX video_jobs.json; found: ' +
                           ', '.join(str(path) for path in matches))
    return matches[0]


def gpu_inventory():
    command = ['nvidia-smi', '--query-gpu=name,memory.total,compute_cap',
               '--format=csv,noheader,nounits']
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError('E_GPU_UNSUPPORTED: nvidia-smi query failed: ' + str(error)) from error
    devices = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(',')]
        if len(fields) != 3:
            raise RuntimeError('E_GPU_UNSUPPORTED: unexpected nvidia-smi output: ' + line)
        devices.append({'name': fields[0], 'memory_total_mib': int(fields[1]),
                        'compute_capability': fields[2]})
    return devices


def validate_gpu(devices):
    if not devices:
        raise RuntimeError('E_GPU_UNSUPPORTED: Kaggle did not allocate a GPU')
    first = devices[0]
    if 'T4' not in first['name'].upper() or first['memory_total_mib'] < 14000:
        raise RuntimeError(
            'E_GPU_UNSUPPORTED: this Kaggle RuntimePlan requires a Tesla T4 with at least 14 GiB; '
            f"Kaggle allocated: {first['name']} ({first['memory_total_mib']} MiB).")


def package_name(spec):
    for marker in ('<', '>', '=', '!', '~', '['):
        spec = spec.split(marker, 1)[0]
    return spec.strip()


def bootstrap(backend):
    missing = []
    for spec in backend.get('bootstrap_packages', []):
        name = package_name(spec)
        module = MODULE_NAMES.get(name, name.replace('-', '_'))
        if importlib.util.find_spec(module) is None:
            missing.append(spec)
    if not missing:
        return []
    if backend.get('offline', False):
        raise RuntimeError('E_DEPENDENCY: offline runtime is missing: ' + ', '.join(missing))
    subprocess.run([sys.executable, '-m', 'pip', 'install',
                    '--disable-pip-version-check', '--no-input', *missing], check=True)
    return missing


def runtime_versions():
    values = {'python': sys.version.split()[0]}
    for name in ('torch', 'diffusers', 'transformers', 'accelerate', 'torchao',
                 'sentencepiece', 'imageio', 'imageio-ffmpeg'):
        try:
            values[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            values[name] = None
    return values


def verify_video(path, expected_frames=49):
    command = ['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
               '-show_entries', 'stream=codec_name,width,height,r_frame_rate,nb_read_frames',
               '-show_entries', 'format=duration', '-of', 'json', str(path)]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise RuntimeError('E_EXPORT: ffprobe validation failed: ' + str(error)) from error
    streams = report.get('streams') or []
    duration = float((report.get('format') or {}).get('duration') or 0)
    frames = int(streams[0].get('nb_read_frames') or 0) if streams else 0
    if not streams or not 5.5 <= duration <= 6.5 or frames != expected_frames:
        raise RuntimeError(
            f'E_EXPORT: expected {expected_frames} frames and about 6 seconds; '
            f'got {frames} frames and {duration:.3f} seconds')
    return report


def classify(error):
    text = str(error)
    for code in ('E_CONFIG', 'E_INPUT', 'E_MODEL', 'E_DEPENDENCY',
                 'E_GPU_UNSUPPORTED', 'E_GPU_OOM', 'E_EXPORT'):
        if code in text:
            return code
    if isinstance(error, subprocess.CalledProcessError):
        return 'E_DEPENDENCY'
    return 'E_GENERATION'


def validate_backend(backend):
    if backend.get('engine') != 'diffusers_cogvideox_i2v' or backend.get('model') != 'zai-org/CogVideoX-5b-I2V':
        raise RuntimeError('E_CONFIG: unsupported CogVideoX provider configuration')
    if backend.get('profile') not in ('smoke', 'fast', 'balanced', 'quality', 'max_quality'):
        raise RuntimeError('E_CONFIG: unsupported generic Profile')
    revision = backend.get('model_revision')
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError('E_CONFIG: model_revision must be a pinned commit')
    generation = backend.get('generation') or {}
    device = backend.get('device') or {}
    if generation.get('size') != '720*480' or generation.get('fps') != 8 or generation.get('frame_num') != 49:
        raise RuntimeError('E_CONFIG: unsupported CogVideoX RuntimePlan output')
    if device.get('world_size') != 1:
        raise RuntimeError('E_CONFIG: CogVideoX RuntimePlan currently requires world_size=1')


def validate_job(job):
    forbidden = sorted(FORBIDDEN_JOB_FIELDS.intersection(job))
    if forbidden:
        raise RuntimeError('E_CONFIG: job performance parameters are forbidden: ' +
                           ', '.join(forbidden))
    for key in ('id', 'image', 'source_image_sha256', 'prompt', 'seed',
                'target_duration_sec', 'cache_key', 'output'):
        if key not in job:
            raise RuntimeError(f'E_CONFIG: job is missing {key}')


def backend_from_manifest(payload):
    if 'runtime_plan' not in payload:
        raise RuntimeError('E_CONFIG: RuntimePlan is required')
    plan = payload.get('runtime_plan') or {}
    execution = dict(plan.get('execution') or {})
    if 'resolution' in execution:
        execution['size'] = execution.pop('resolution').replace('x', '*')
    device = {'world_size': execution.pop('world_size', 1),
              'compute_dtype': execution.pop('dtype', None)}
    generation_keys = {'size', 'fps', 'frame_num', 'inference_steps', 'guidance_scale'}
    generation = {key: execution.pop(key) for key in list(execution)
                  if key in generation_keys}
    return {**(payload.get('provider_config') or {}), '_runtime_plan': True,
            'profile': plan.get('profile'), 'device': device,
            'generation': generation, 'acceleration': execution}


def main():
    results_path = OUTPUT / 'results.json'
    preflight_path = OUTPUT / 'preflight.json'
    active_job = None
    completed_rows = []
    try:
        jobs_path = fixed_manifest(os.environ.get('NARRATED_VIDEO_JOB'))
        payload = json.loads(jobs_path.read_text(encoding='utf-8-sig'))
        if payload.get('version') != 3 or payload.get('provider') != 'cogvideox':
            raise RuntimeError('E_CONFIG: expected version 3 cogvideox manifest')
        backend = backend_from_manifest(payload)
        validate_backend(backend)
        generation = backend['generation']
        devices = gpu_inventory()
        preflight = {
            'ok': False,
            'mode': 'cogvideox-5b-i2v-int8-kaggle',
            'jobs': str(jobs_path),
            'model': backend['model'],
            'model_revision': backend['model_revision'],
            'gpus': devices,
            'selected_gpu': 0,
            'runtime': runtime_versions(),
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        }
        try:
            validate_gpu(devices)
            installed = bootstrap(backend)
            preflight['bootstrap_installed'] = installed
            preflight['runtime'] = runtime_versions()
        except Exception as error:
            preflight['error'] = str(error)
            write_json(preflight_path, preflight)
            raise
        preflight['ok'] = True
        write_json(preflight_path, preflight)

        # A Worker owns one physical T4. The second card is not used as pooled VRAM.
        os.environ['CUDA_VISIBLE_DEVICES'] = '0'
        import torch
        from diffusers import CogVideoXImageToVideoPipeline, TorchAoConfig
        from diffusers.quantizers import PipelineQuantizationConfig
        from diffusers.utils import export_to_video
        from PIL import Image, ImageOps
        from torchao.quantization import Int8WeightOnlyConfig

        quantization = PipelineQuantizationConfig(
            quant_mapping={
                'transformer': TorchAoConfig(Int8WeightOnlyConfig()),
            })
        try:
            pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
                backend['model'], revision=backend['model_revision'],
                torch_dtype=torch.float16, quantization_config=quantization,
                low_cpu_mem_usage=True)
        except Exception as error:
            raise RuntimeError('E_MODEL: failed to load pinned CogVideoX model: ' +
                               str(error)) from error
        pipeline.enable_sequential_cpu_offload(gpu_id=0)
        pipeline.vae.enable_slicing()
        pipeline.vae.enable_tiling()

        previous = (json.loads(results_path.read_text(encoding='utf-8'))
                    if results_path.is_file() else {})
        completed_rows = [row for row in previous.get('results', [])
                          if row.get('status') == 'completed']
        completed_ids = {row.get('id') for row in completed_rows}
        frame_num = int(generation['frame_num'])
        fps = int(generation['fps'])
        inference_steps = int(generation['inference_steps'])
        guidance_scale = float(generation['guidance_scale'])
        for job in payload.get('jobs', []):
            active_job = job
            validate_job(job)
            output = OUTPUT / job['output']
            if job['id'] in completed_ids and output.is_file():
                verify_video(output, frame_num)
                continue
            image_path = (jobs_path.parent / job['image']).resolve()
            if not image_path.is_file():
                raise RuntimeError(f"E_INPUT: {job['id']} input image is missing")
            if sha256(image_path) != job['source_image_sha256']:
                raise RuntimeError(f"E_INPUT: {job['id']} input image hash mismatch")
            with Image.open(image_path) as source:
                image = ImageOps.fit(source.convert('RGB'), (720, 480),
                                     method=Image.Resampling.LANCZOS)
            constraints = '; '.join(job.get('constraints', []))
            prompt = job['prompt'] + ('. Requirements: ' + constraints if constraints else '')
            negative = job.get('negative_prompt') or None
            generator = torch.Generator(device='cuda').manual_seed(int(job['seed']))
            frames = pipeline(
                image=image,
                prompt=prompt,
                negative_prompt=negative,
                num_frames=frame_num,
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                use_dynamic_cfg=True,
                generator=generator,
            ).frames[0]
            output.parent.mkdir(parents=True, exist_ok=True)
            partial = output.with_name(output.stem + '.partial' + output.suffix)
            export_to_video(frames, str(partial), fps=fps)
            probe = verify_video(partial, frame_num)
            partial.replace(output)
            completed_rows.append({
                'id': job['id'], 'status': 'completed',
                'cache_key': job['cache_key'], 'output': job['output'],
                'sha256': sha256(output), 'frame_num': frame_num,
                'fps': fps, 'generated_duration_sec': frame_num / fps, 'probe': probe,
            })
            write_json(results_path, {
                'version': 3, 'provider': 'cogvideox',
                'runtime_plan_digest': (payload.get('runtime_plan') or {}).get('plan_digest'),
                'model': backend.get('model'),
                'model_revision': backend.get('model_revision'),
                'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'results': completed_rows,
            })
            del frames
            del image
            torch.cuda.empty_cache()
    except Exception as error:
        code = ('E_GPU_OOM' if error.__class__.__name__ == 'OutOfMemoryError'
                else classify(error))
        failed = {'id': active_job.get('id') if active_job else None,
                  'status': 'failed', 'code': code, 'error': str(error)}
        write_json(results_path, {
            'version': 3, 'provider': 'cogvideox',
            'runtime_plan_digest': (payload.get('runtime_plan') or {}).get('plan_digest'),
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'results': completed_rows + [failed],
        })
        raise


if __name__ == '__main__':
    main()
