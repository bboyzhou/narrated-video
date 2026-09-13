#!/usr/bin/env python3
"""Kaggle entry point for Stable Video Diffusion XT on one T4."""
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
    'diffusers': 'diffusers',
    'transformers': 'transformers',
    'accelerate': 'accelerate',
    'imageio': 'imageio',
    'imageio-ffmpeg': 'imageio_ffmpeg',
}
FORBIDDEN_JOB_FIELDS = {
    'provider', 'profile', 'runtime', 'dtype', 'offload', 'world_size',
    'attention_backend', 'teacache',
    'frame_num', 'output_fps', 'inference_steps', 'decode_chunk_size',
    'motion_bucket_id', 'noise_aug_strength',
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


def fixed_file(value, candidates, label, discover=None):
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file():
            return path
        raise RuntimeError(f'E_INPUT: {label} does not exist: {path}')
    existing = [Path(item).resolve() for item in candidates if Path(item).is_file()]
    if not existing and discover:
        existing = [Path(item).resolve() for item in discover()]
    existing = sorted(set(existing), key=str)
    if len(existing) != 1:
        raise RuntimeError(f'E_INPUT: expected exactly one {label}; found: ' +
                           ', '.join(str(item) for item in existing))
    return existing[0]


def discover_manifest():
    matches = []
    for path in INPUT.rglob('video_jobs.json'):
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (payload.get('version') == 3 and
                payload.get('provider') == 'svd_xt' and
                isinstance(payload.get('jobs'), list)):
            matches.append(path)
    return matches


def is_svd_model(path):
    required = (
        'model_index.json', 'unet/config.json', 'vae/config.json',
        'image_encoder/config.json', 'scheduler/scheduler_config.json',
        'feature_extractor/preprocessor_config.json',
    )
    if not all((path / item).is_file() for item in required):
        return False
    try:
        metadata = json.loads((path / 'model_index.json').read_text(
            encoding='utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return metadata.get('_class_name') == 'StableVideoDiffusionPipeline'


def discover_model_paths():
    matches = []
    for index in INPUT.rglob('model_index.json'):
        candidate = index.parent
        if is_svd_model(candidate):
            matches.append(candidate)
    return matches


def fixed_model_path(value=None):
    candidates = [
        INPUT / 'stable-video-diffusion-img2vid-xt' /
        'stable-video-diffusion-img2vid-xt',
        INPUT / 'stable-video-diffusion-img2vid-xt' / 'other' /
        'weights' / '1' / 'stable-video-diffusion-img2vid-xt',
        INPUT / 'stable-video-diffusion-img2vid-xt' / 'other' /
        'weights' / '1',
    ]
    if value:
        candidates = [Path(value).expanduser()]
    matches = [path.resolve() for path in candidates if is_svd_model(path)]
    if not matches and not value:
        matches = [path.resolve() for path in discover_model_paths()]
    matches = sorted(set(matches), key=str)
    if len(matches) != 1:
        raise RuntimeError('E_MODEL: expected one pinned SVD-XT model directory; found: ' +
                           ', '.join(str(item) for item in matches))
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
            'E_GPU_UNSUPPORTED: t4_stable requires a Tesla T4 with at least 14 GiB; '
            f"Kaggle allocated: {first['name']} ({first['memory_total_mib']} MiB).")


def package_name(spec):
    for marker in ('<', '>', '=', '!', '~', '['):
        spec = spec.split(marker, 1)[0]
    return spec.strip()


def bootstrap(backend):
    packages = backend.get('bootstrap_packages', [])
    missing = []
    for spec in packages:
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
    for name in ('torch', 'diffusers', 'transformers', 'accelerate',
                 'imageio', 'imageio-ffmpeg'):
        try:
            values[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            values[name] = None
    return values


def verify_video(path):
    command = ['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
               '-show_entries', 'stream=codec_name,width,height,nb_read_frames',
               '-show_entries', 'format=duration', '-of', 'json', str(path)]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise RuntimeError('E_EXPORT: ffprobe validation failed: ' + str(error)) from error
    streams = report.get('streams') or []
    duration = float((report.get('format') or {}).get('duration') or 0)
    frames = int(streams[0].get('nb_read_frames') or 0) if streams else 0
    if not streams or duration <= 0 or frames <= 0:
        raise RuntimeError('E_EXPORT: output has no valid video stream, duration, or frames')
    return report


def classify(error):
    text = str(error)
    for code in ('E_INPUT', 'E_MODEL', 'E_DEPENDENCY', 'E_GPU_UNSUPPORTED',
                 'E_GPU_OOM', 'E_EXPORT'):
        if code in text:
            return code
    if isinstance(error, subprocess.CalledProcessError):
        return 'E_DEPENDENCY'
    return 'E_GENERATION'


def validate_backend(backend):
    if backend.get('engine') != 'diffusers_svd':
        raise RuntimeError('E_CONFIG: SVD worker requires engine=diffusers_svd')
    if backend.get('model') != 'stabilityai/stable-video-diffusion-img2vid-xt':
        raise RuntimeError('E_CONFIG: unsupported SVD model')
    revision = backend.get('model_revision')
    if not isinstance(revision, str) or not revision.strip() or revision in ('main', 'latest'):
        raise RuntimeError('E_CONFIG: SVD worker requires a pinned model_revision')
    if backend.get('profile') not in ('smoke', 'fast', 'balanced', 'quality', 'max_quality'):
        raise RuntimeError('E_CONFIG: unsupported generic Profile')
    generation = backend.get('generation') or {}
    device = backend.get('device') or {}
    acceleration = backend.get('acceleration') or {}
    if generation.get('size') != '1024*576' or generation.get('fps') != 7:
        raise RuntimeError('E_CONFIG: unsupported SVD RuntimePlan resolution/fps')
    if device.get('world_size') != 1 or device.get('dtype') != 'float16':
        raise RuntimeError('E_CONFIG: unsupported SVD RuntimePlan device')
    if acceleration.get('vae_slicing') is not False:
        raise RuntimeError('E_CONFIG: SVD temporal VAE does not support vae_slicing')


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
              'dtype': execution.pop('dtype', None)}
    generation_keys = {'size', 'fps', 'frame_num', 'inference_steps',
                       'decode_chunk_size', 'motion_bucket_id', 'noise_aug_strength'}
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
        jobs_path = fixed_file(
            os.environ.get('NARRATED_VIDEO_JOB'),
            [INPUT / 'narrated-video-svd-demo-input' / 'video_jobs.json'],
            'video_jobs.json', discover=discover_manifest)
        payload = json.loads(jobs_path.read_text(encoding='utf-8-sig'))
        backend = backend_from_manifest(payload)
        if payload.get('version') != 3 or payload.get('provider') != 'svd_xt':
            raise RuntimeError('E_CONFIG: expected version 3 svd_xt manifest')
        validate_backend(backend)
        generation = backend['generation']
        acceleration = backend['acceleration']
        model_path = fixed_model_path(
            backend.get('model_path') or os.environ.get('SVD_XT_MODEL'))
        devices = gpu_inventory()
        preflight = {
            'ok': False,
            'mode': 'svd-xt-kaggle',
            'jobs': str(jobs_path),
            'model_path': str(model_path),
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

        # One worker owns one T4. The second Kaggle T4 stays isolated until the
        # single-worker profile has passed repeated production smoke tests.
        os.environ['CUDA_VISIBLE_DEVICES'] = '0'
        import torch
        from diffusers import StableVideoDiffusionPipeline
        from diffusers.utils import export_to_video
        from PIL import Image, ImageOps

        pipeline = StableVideoDiffusionPipeline.from_pretrained(
            str(model_path), torch_dtype=torch.float16, variant='fp16',
            local_files_only=True)
        pipeline.enable_model_cpu_offload(gpu_id=0)
        if acceleration.get('forward_chunking', True):
            pipeline.unet.enable_forward_chunking()
        # AutoencoderKLTemporalDecoder raises NotImplementedError for slicing;
        # decode_chunk_size is the supported SVD decode-memory control.
        if acceleration.get('vae_slicing', False):
            pipeline.vae.enable_slicing()

        previous = (json.loads(results_path.read_text(encoding='utf-8'))
                    if results_path.is_file() else {})
        completed_rows = [row for row in previous.get('results', [])
                          if row.get('status') == 'completed']
        completed_ids = {row.get('id') for row in completed_rows}
        frame_num = int(generation['frame_num'])
        fps = int(generation['fps'])
        inference_steps = int(generation['inference_steps'])
        decode_chunk_size = int(generation['decode_chunk_size'])
        motion_bucket_id = int(generation.get('motion_bucket_id', 80))
        noise_aug_strength = float(generation.get('noise_aug_strength', 0.02))
        for job in payload.get('jobs', []):
            active_job = job
            validate_job(job)
            output = OUTPUT / job['output']
            if job['id'] in completed_ids and output.is_file():
                verify_video(output)
                continue
            image_path = (jobs_path.parent / job['image']).resolve()
            if not image_path.is_file():
                raise RuntimeError(f"E_INPUT: {job['id']} input image is missing")
            if sha256(image_path) != job['source_image_sha256']:
                raise RuntimeError(f"E_INPUT: {job['id']} input image hash mismatch")
            with Image.open(image_path) as source:
                image = ImageOps.fit(source.convert('RGB'), (1024, 576),
                                     method=Image.Resampling.LANCZOS)
            generator = torch.Generator(device='cuda').manual_seed(int(job['seed']))
            frames = pipeline(
                image=image,
                num_frames=frame_num,
                num_inference_steps=inference_steps,
                decode_chunk_size=decode_chunk_size,
                motion_bucket_id=motion_bucket_id,
                noise_aug_strength=noise_aug_strength,
                generator=generator,
            ).frames[0]
            output.parent.mkdir(parents=True, exist_ok=True)
            partial = output.with_name(output.stem + '.partial' + output.suffix)
            export_to_video(frames, str(partial), fps=fps)
            verify_video(partial)
            partial.replace(output)
            completed_rows.append({
                'id': job['id'], 'status': 'completed',
                'cache_key': job['cache_key'], 'output': job['output'],
                'sha256': sha256(output), 'frame_num': frame_num,
                'fps': fps, 'generated_duration_sec': frame_num / fps,
            })
            write_json(results_path, {
                'version': 3, 'provider': 'svd_xt',
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
            'version': 3, 'provider': 'svd_xt',
            'runtime_plan_digest': (payload.get('runtime_plan') or {}).get('plan_digest'),
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'results': completed_rows + [failed],
        })
        raise


if __name__ == '__main__':
    main()
