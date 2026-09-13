#!/usr/bin/env python3
"""Kaggle Runtime launcher for the SkyReels-V2 I2V provider."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path


INPUT = Path('/kaggle/input')
OUTPUT = Path('/kaggle/working')
RUNTIME = Path('/kaggle/temp')
PROVIDER = 'skyreels_v2'
MODEL = 'Skywork/SkyReels-V2-I2V-1.3B-540P'
MODEL_REVISION = 'e86231f3882225e5a93eeec740c77bc7f01954ca'
SOURCE_REVISION = '9351d13152207cc04de780e055346b08ade0b851'
SOURCE_SHA256 = '3571f1f6d2da99a360d879fb6acf91850ce8c1455c8f67d13501a5b0159c77da'
T5_SIZE = 11361920418
MODEL_FILES = (
    'config.json',
    'model.safetensors',
    'models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth',
    'Wan2.1_VAE.pth',
    'xlm-roberta-large/tokenizer.json',
    'xlm-roberta-large/sentencepiece.bpe.model',
    'xlm-roberta-large/tokenizer_config.json',
    'xlm-roberta-large/special_tokens_map.json',
    'google/umt5-xxl/tokenizer.json',
    'google/umt5-xxl/spiece.model',
    'google/umt5-xxl/tokenizer_config.json',
    'google/umt5-xxl/special_tokens_map.json',
)
FORBIDDEN_JOB_FIELDS = {
    'provider', 'profile', 'runtime', 'dtype', 'offload', 'world_size',
    'attention_backend', 'teacache',
    'frame_num', 'output_fps', 'inference_steps', 'guidance_scale', 'shift',
    'sample_steps', 'sample_shift', 'sample_solver', 'sample_guide_scale',
    'decode_chunk_size', 'motion_bucket_id', 'noise_aug_strength',
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
        if (payload.get('version') == 3 and payload.get('provider') == PROVIDER and
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
        'narrated-video-skyreels-v2-demo-input' / 'video_jobs' / 'video_jobs.json',
        INPUT / 'datasets' / 'connorbrooksz' /
        'narrated-video-skyreels-v2-demo-input' / 'video_jobs.json',
        INPUT / 'narrated-video-skyreels-v2-demo-input' /
        'video_jobs' / 'video_jobs.json',
        INPUT / 'narrated-video-skyreels-v2-demo-input' / 'video_jobs.json',
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    matches = discover_manifest()
    if len(matches) != 1:
        raise RuntimeError(
            'E_INPUT: expected exactly one SkyReels-V2 video_jobs.json; found: ' +
            ', '.join(str(path) for path in matches))
    return matches[0]


def fixed_t5_path():
    candidates = [
        INPUT / 'datasets' / 'ihsannika' / 'wan2-2-ti2v-5b' /
        'Wan2.2-TI2V-5B' / 'models_t5_umt5-xxl-enc-bf16.pth',
        INPUT / 'wan2-2-ti2v-5b' / 'Wan2.2-TI2V-5B' /
        'models_t5_umt5-xxl-enc-bf16.pth',
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size == T5_SIZE:
            return path.resolve()
    raise RuntimeError(
        'E_MODEL: mounted Wan2.2 Dataset does not contain the expected shared UMT5 checkpoint')


def source_archive():
    candidates = [
        Path(__file__).resolve().parent / 'skyreels_v2_source.zip',
        Path('/kaggle/src/skyreels_v2_source.zip'),
    ]
    for path in candidates:
        if path.is_file():
            if sha256(path).lower() != SOURCE_SHA256:
                raise RuntimeError('E_MODEL: SkyReels-V2 source archive hash mismatch')
            return path
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path = RUNTIME / f'skyreels-v2-source-{SOURCE_REVISION}.zip'
    partial = path.with_suffix('.zip.partial')
    url = f'https://github.com/SkyworkAI/SkyReels-V2/archive/{SOURCE_REVISION}.zip'
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as handle:
            shutil.copyfileobj(response, handle)
    except (OSError, TimeoutError) as error:
        raise RuntimeError('E_MODEL: failed to download pinned SkyReels-V2 source: ' +
                           str(error)) from error
    if sha256(partial).lower() != SOURCE_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError('E_MODEL: downloaded SkyReels-V2 source hash mismatch')
    partial.replace(path)
    return path


def gpu_inventory():
    command = ['nvidia-smi', '--query-gpu=name,memory.total,memory.free,compute_cap',
               '--format=csv,noheader,nounits']
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError('E_GPU_UNSUPPORTED: nvidia-smi query failed: ' + str(error)) from error
    devices = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(',')]
        if len(fields) != 4:
            raise RuntimeError('E_GPU_UNSUPPORTED: unexpected nvidia-smi output: ' + line)
        devices.append({
            'name': fields[0],
            'memory_total_mib': int(fields[1]),
            'memory_free_mib': int(fields[2]),
            'compute_capability': fields[3],
        })
    return devices


def validate_gpu(devices):
    if not devices:
        raise RuntimeError('E_GPU_UNSUPPORTED: Kaggle did not allocate a GPU')
    first = devices[0]
    capability = float(first.get('compute_capability') or 0)
    if capability < 7 or first['memory_total_mib'] < 14000:
        raise RuntimeError(
            'E_GPU_UNSUPPORTED: SkyReels-V2 requires compute capability >= 7.0 and '
            f"at least 14 GiB VRAM; Kaggle allocated: {first['name']} "
            f"({first['memory_total_mib']} MiB).")
    if first['memory_free_mib'] < 13500:
        raise RuntimeError('E_GPU_UNSUPPORTED: less than 13.5 GiB VRAM is free before model load')


def memory_available_gib():
    values = {}
    try:
        for line in Path('/proc/meminfo').read_text(encoding='utf-8').splitlines():
            key, raw = line.split(':', 1)
            values[key] = int(raw.strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return values.get('MemAvailable', 0) / 1024 / 1024


def resource_inventory():
    disk = shutil.disk_usage(OUTPUT)
    return {
        'ram_available_gib': memory_available_gib(),
        'disk_free_gib': disk.free / 1024 ** 3,
    }


def validate_resources(resources):
    ram = resources.get('ram_available_gib')
    if ram is not None and ram < 28:
        raise RuntimeError(
            f'E_RAM_PRESSURE: native SkyReels-V2 offload requires at least 28 GiB free RAM; got {ram:.1f}')
    if resources['disk_free_gib'] < 13:
        raise RuntimeError(
            'E_CONFIG: native SkyReels-V2 runtime requires at least 13 GiB free disk')


def bootstrap(backend):
    specs = backend.get('bootstrap_packages', [])
    if not specs:
        return []
    if backend.get('offline', False):
        missing = []
        for spec in specs:
            name = spec.split('==', 1)[0]
            try:
                importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(spec)
        if missing:
            raise RuntimeError('E_DEPENDENCY: offline runtime is missing: ' + ', '.join(missing))
        return []
    subprocess.run([
        sys.executable, '-m', 'pip', 'install', '--upgrade',
        '--disable-pip-version-check', '--no-input', *specs,
    ], check=True)
    return list(specs)


def runtime_versions():
    values = {'python': sys.version.split()[0]}
    for name in ('torch', 'torchvision', 'diffusers', 'transformers', 'tokenizers',
                 'accelerate', 'sentencepiece', 'safetensors', 'easydict', 'ftfy',
                 'decord', 'imageio', 'imageio-ffmpeg'):
        try:
            values[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            values[name] = None
    return values


def prepare_source(archive):
    destination = RUNTIME / 'skyreels-v2-source'
    root = destination / ('SkyReels-V2-' + SOURCE_REVISION)
    if not root.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    expected = root / 'skyreels_v2_infer' / 'pipelines' / 'image2video_pipeline.py'
    if not expected.is_file():
        raise RuntimeError('E_MODEL: pinned SkyReels-V2 source layout is invalid')
    return root


def replace_once(path, old, new):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise RuntimeError(f'E_MODEL: low-memory patch anchor mismatch in {path.name}')
    path.write_text(text.replace(old, new), encoding='utf-8')


def install_low_memory_loader_patch(source_root):
    modules = source_root / 'skyreels_v2_infer' / 'modules'
    t5_path = modules / 't5.py'
    clip_path = modules / 'clip.py'
    init_path = modules / '__init__.py'

    replace_once(t5_path, 'import torch\n',
                 'import torch\nfrom accelerate import init_empty_weights\n')
    replace_once(
        t5_path,
        '        model = umt5_xxl(encoder_only=True, return_tokenizer=False)\n',
        '        with init_empty_weights():\n'
        '            model = umt5_xxl(encoder_only=True, return_tokenizer=False)\n')
    replace_once(
        t5_path,
        '        model.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))\n',
        '        state_dict = torch.load(checkpoint_path, map_location="cpu", '
        'mmap=True, weights_only=True)\n'
        '        model.load_state_dict(state_dict, assign=True)\n'
        '        del state_dict\n')
    replace_once(
        t5_path,
        '    model = model.to(dtype=dtype, device=device)\n',
        '    if not any(parameter.is_meta for parameter in model.parameters()):\n'
        '        model = model.to(dtype=dtype, device=device)\n')

    replace_once(clip_path, 'import torch\n',
                 'import torch\nfrom accelerate import init_empty_weights\n')
    replace_once(
        clip_path,
        '        self.model, self.transforms = clip_xlm_roberta_vit_h_14(\n'
        '            pretrained=False, return_transforms=True, return_tokenizer=False\n'
        '        )\n',
        '        with init_empty_weights():\n'
        '            self.model, self.transforms = clip_xlm_roberta_vit_h_14(\n'
        '                pretrained=False, return_transforms=True, return_tokenizer=False\n'
        '            )\n')
    replace_once(
        clip_path,
        '        self.model.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))\n',
        '        state_dict = torch.load(checkpoint_path, map_location="cpu", '
        'mmap=True, weights_only=True)\n'
        '        self.model.load_state_dict(state_dict, assign=True)\n'
        '        del state_dict\n')
    replace_once(
        clip_path,
        '    model = model.to(dtype=dtype, device=device)\n',
        '    if not any(parameter.is_meta for parameter in model.parameters()):\n'
        '        model = model.to(dtype=dtype, device=device)\n')

    replace_once(init_path, 'import torch\n',
                 'import torch\nfrom accelerate import init_empty_weights\n')
    replace_once(
        init_path,
        '    transformer = WanModel.from_config(config_path).to(weight_dtype).to(device)\n',
        '    with init_empty_weights():\n'
        '        transformer = WanModel.from_config(config_path)\n')
    replace_once(
        init_path,
        '            state_dict = load_file(file_path)\n'
        '            transformer.load_state_dict(state_dict, strict=False)\n',
        '            state_dict = load_file(file_path)\n'
        '            transformer.load_state_dict(state_dict, strict=False, assign=True)\n')
    replace_once(
        init_path,
        '    transformer.requires_grad_(False)\n',
        '    transformer = transformer.to(dtype=weight_dtype, device=device)\n'
        '    transformer.requires_grad_(False)\n')
    return 'accelerate_meta_mmap_assign_v2'


def install_component_logging(pipeline_module):
    for name in ('get_transformer', 'get_vae', 'get_text_encoder', 'get_image_encoder'):
        original = getattr(pipeline_module, name)

        def tracked(*args, _name=name, _original=original, **kwargs):
            print(f'[skyreels] loading {_name}', flush=True)
            value = _original(*args, **kwargs)
            print(f'[skyreels] loaded {_name}', flush=True)
            return value

        setattr(pipeline_module, name, tracked)


def prepare_model(t5_path):
    from huggingface_hub import hf_hub_download

    destination = RUNTIME / 'skyreels-v2-model'
    destination.mkdir(parents=True, exist_ok=True)
    for filename in MODEL_FILES:
        hf_hub_download(repo_id=MODEL, revision=MODEL_REVISION, filename=filename,
                        local_dir=destination)
    target = destination / 'models_t5_umt5-xxl-enc-bf16.pth'
    if not target.exists():
        target.symlink_to(t5_path)
    if target.stat().st_size != T5_SIZE:
        raise RuntimeError('E_MODEL: shared UMT5 checkpoint size mismatch')
    missing = [name for name in MODEL_FILES if not (destination / name).is_file()]
    if missing:
        raise RuntimeError('E_MODEL: SkyReels-V2 model files are missing: ' + ', '.join(missing))
    return destination


def verify_video(path, expected_frames, fps):
    command = [
        'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,r_frame_rate,nb_read_frames',
        '-show_entries', 'format=duration', '-of', 'json', str(path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise RuntimeError('E_EXPORT: ffprobe validation failed: ' + str(error)) from error
    streams = report.get('streams') or []
    duration = float((report.get('format') or {}).get('duration') or 0)
    frames = int(streams[0].get('nb_read_frames') or 0) if streams else 0
    expected_duration = expected_frames / fps
    if (not streams or frames != expected_frames or
            abs(duration - expected_duration) > 0.25):
        raise RuntimeError(
            f'E_EXPORT: expected {expected_frames} frames and about '
            f'{expected_duration:.3f} seconds; got {frames} frames and {duration:.3f} seconds')
    return report


def classify(error):
    text = str(error)
    for code in ('E_CONFIG', 'E_INPUT', 'E_MODEL', 'E_DEPENDENCY',
                 'E_GPU_UNSUPPORTED', 'E_RAM_PRESSURE', 'E_GPU_OOM', 'E_EXPORT'):
        if code in text:
            return code
    if isinstance(error, subprocess.CalledProcessError):
        return 'E_DEPENDENCY'
    return 'E_GENERATION'


def validate_backend(backend):
    expected = {'engine': 'skyreels_v2_native_i2v', 'model': MODEL,
                'model_revision': MODEL_REVISION,
                'source_revision': SOURCE_REVISION, 'source_sha256': SOURCE_SHA256}
    for key, value in expected.items():
        if backend.get(key) != value:
            raise RuntimeError(f'E_CONFIG: expected provider_config.{key}={value!r}')
    if backend.get('profile') not in ('smoke', 'fast', 'balanced', 'quality', 'max_quality'):
        raise RuntimeError('E_CONFIG: unsupported generic Profile')
    execution = backend.get('generation') or {}
    required = ('size', 'fps', 'frame_num', 'inference_steps', 'guidance_scale', 'shift')
    if any(key not in execution for key in required):
        raise RuntimeError('E_CONFIG: incomplete RuntimePlan.execution')
    if execution.get('size') != '960*544' or execution.get('fps') != 24:
        raise RuntimeError('E_CONFIG: unsupported SkyReels RuntimePlan resolution/fps')


def print_runtime_config(backend, devices):
    generation = backend['generation']
    device = backend['device']
    acceleration = backend['acceleration']
    frames = int(generation['frame_num'])
    fps = float(generation['fps'])
    print('=' * 40, flush=True)
    print('SkyReels-V2 Runtime Configuration', flush=True)
    print('=' * 40, flush=True)


def backend_from_manifest(payload):
    if 'runtime_plan' not in payload:
        raise RuntimeError('E_CONFIG: RuntimePlan is required')
    plan = payload.get('runtime_plan') or {}
    execution = dict(plan.get('execution') or {})
    if 'resolution' in execution:
        execution['size'] = execution.pop('resolution').replace('x', '*')
    device = {'world_size': execution.pop('world_size', 1),
              'compute_dtype': execution.get('dtype')}
    generation_keys = {'size', 'fps', 'frame_num', 'inference_steps',
                       'guidance_scale', 'shift'}
    generation = {key: execution.pop(key) for key in list(execution)
                  if key in generation_keys}
    return {**(payload.get('provider_config') or {}), '_runtime_plan': True,
            'profile': plan.get('profile'), 'device': device,
            'generation': generation, 'acceleration': execution,
            'monitoring': {'gpu_stats': True, 'gpu_stats_interval_sec': 30,
                           'step_timing': True, 'log_runtime_config': True}}
    print(f"Profile:           {backend['profile']}", flush=True)
    print(f"GPU:               {devices[0]['name']}", flush=True)
    print(f"GPU count used:    {device['world_size']} / {len(devices)}", flush=True)
    print(f"dtype:             {device['compute_dtype']}", flush=True)
    print(f"resolution:        {generation['size'].replace('*', 'x')}", flush=True)
    print(f"frames:            {frames}", flush=True)
    print(f"fps:               {fps:g}", flush=True)
    print(f"generated seconds:  {frames / fps:.2f}", flush=True)
    print(f"steps:             {generation['inference_steps']}", flush=True)
    print(f"guidance:          {generation['guidance_scale']}", flush=True)
    print(f"shift:             {generation['shift']}", flush=True)
    print(f"attention:         {acceleration['attention_backend']}", flush=True)
    print(f"TeaCache:          {'ON' if acceleration['teacache'] else 'OFF'}", flush=True)
    print(f"TeaCache threshold: {acceleration['teacache_thresh']}", flush=True)
    print(f"Retention steps:   {'ON' if acceleration['use_ret_steps'] else 'OFF'}", flush=True)
    print(f"CPU offload:       {'ON' if acceleration['offload'] else 'OFF'}", flush=True)
    print('=' * 40, flush=True)


def validate_job(job):
    if not isinstance(job, dict):
        raise RuntimeError('E_CONFIG: each job must be an object')
    forbidden = sorted(FORBIDDEN_JOB_FIELDS.intersection(job))
    if forbidden:
        raise RuntimeError('E_CONFIG: job performance parameters are forbidden: ' +
                           ', '.join(forbidden))
    required = ('id', 'image', 'source_image_sha256', 'prompt', 'seed',
                'target_duration_sec', 'cache_key', 'output')
    missing = [key for key in required if key not in job]
    if missing:
        raise RuntimeError('E_CONFIG: job is missing: ' + ', '.join(missing))


def install_sdpa_fallback(torch_module):
    from skyreels_v2_infer.modules import clip as clip_module
    from skyreels_v2_infer.modules import transformer as transformer_module

    def sdpa_flash_attention(q, k, v, dropout_p=0.0, softmax_scale=None,
                             q_scale=None, causal=False, **_):
        if q_scale is not None:
            q = q * q_scale
        dtype = v.dtype
        q = q.transpose(1, 2).to(dtype)
        k = k.transpose(1, 2).to(dtype)
        v = v.transpose(1, 2)
        options = {'dropout_p': dropout_p, 'is_causal': causal}
        if softmax_scale is not None:
            options['scale'] = softmax_scale
        value = torch_module.nn.functional.scaled_dot_product_attention(q, k, v, **options)
        return value.transpose(1, 2).contiguous()

    clip_module.flash_attention = sdpa_flash_attention
    transformer_module.flash_attention = sdpa_flash_attention


def main():
    results_path = OUTPUT / 'results.json'
    preflight_path = OUTPUT / 'preflight.json'
    active_job = None
    completed_rows = []
    try:
        jobs_path = fixed_manifest(os.environ.get('NARRATED_VIDEO_JOB'))
        payload = json.loads(jobs_path.read_text(encoding='utf-8-sig'))
        if payload.get('version') != 3 or payload.get('provider') != PROVIDER:
            raise RuntimeError(f'E_CONFIG: expected version 3 {PROVIDER} manifest')
        backend = backend_from_manifest(payload)
        validate_backend(backend)
        devices = gpu_inventory()
        resources = resource_inventory()
        preflight = {
            'ok': False,
            'mode': 'skyreels-v2-native-i2v-1.3b-kaggle',
            'profile': backend['profile'],
            'jobs': str(jobs_path),
            'model': backend['model'],
            'model_revision': backend['model_revision'],
            'source_revision': backend['source_revision'],
            'source_sha256': backend['source_sha256'],
            'gpus': devices,
            'selected_gpu': 0,
            'resources': resources,
            'runtime': runtime_versions(),
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        }
        write_json(preflight_path, preflight)
        try:
            validate_gpu(devices)
            validate_resources(resources)
            archive = source_archive()
            t5_path = fixed_t5_path()
            preflight['source_archive'] = str(archive)
            preflight['shared_t5'] = str(t5_path)
            installed = bootstrap(backend)
            preflight['bootstrap_installed'] = installed
            preflight['runtime'] = runtime_versions()
        except Exception as error:
            preflight['error'] = str(error)
            write_json(preflight_path, preflight)
            raise

        os.environ['CUDA_VISIBLE_DEVICES'] = '0'
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        source_root = prepare_source(archive)
        loader_strategy = install_low_memory_loader_patch(source_root)
        model_root = prepare_model(t5_path)
        preflight['loader_strategy'] = loader_strategy
        preflight['model_files'] = {
            name: (model_root / name).stat().st_size for name in MODEL_FILES
        }
        preflight['ok'] = True
        write_json(preflight_path, preflight)
        if backend['monitoring']['log_runtime_config']:
            print_runtime_config(backend, devices)

        sys.path.insert(0, str(source_root))
        import imageio.v2 as imageio
        import torch
        from PIL import Image
        from skyreels_v2_infer.pipelines import image2video_pipeline

        Image2VideoPipeline = image2video_pipeline.Image2VideoPipeline
        resizecrop = image2video_pipeline.resizecrop

        install_sdpa_fallback(torch)
        install_component_logging(image2video_pipeline)
        try:
            torch_dtype = (torch.bfloat16 if backend['device'].get('compute_dtype') == 'bfloat16'
                           else torch.float16)
            pipeline = Image2VideoPipeline(
                model_path=str(model_root), dit_path=str(model_root),
                weight_dtype=torch_dtype, use_usp=False,
                offload=bool(backend['acceleration'].get('offload', True)))
        except Exception as error:
            raise RuntimeError('E_MODEL: failed to load pinned SkyReels-V2 model: ' +
                               str(error)) from error
        acceleration = backend['acceleration']
        pipeline.transformer.initialize_teacache(
            enable_teacache=bool(acceleration['teacache']),
            num_steps=int(backend['generation']['inference_steps']),
            teacache_thresh=float(acceleration['teacache_thresh']),
            use_ret_steps=bool(acceleration['use_ret_steps']),
            # The pinned model ID selects the official 540P I2V TeaCache
            # coefficients; the local staging directory has no model suffix.
            ckpt_dir=MODEL,
        )

        previous = (json.loads(results_path.read_text(encoding='utf-8'))
                    if results_path.is_file() else {})
        completed_rows = [row for row in previous.get('results', [])
                          if row.get('status') == 'completed']
        completed_ids = {row.get('id') for row in completed_rows}
        generation = backend['generation']
        width, height = (int(value) for value in generation['size'].split('*'))
        frame_num = int(generation['frame_num'])
        fps = int(generation['fps'])
        inference_steps = int(generation['inference_steps'])
        guidance_scale = float(generation['guidance_scale'])
        shift = float(generation['shift'])
        for job in payload.get('jobs', []):
            active_job = job
            validate_job(job)
            job_started = time.perf_counter()
            print(f"[skyreels] job={job['id']} target_duration_sec={job['target_duration_sec']} "
                  f"generated_duration_sec={frame_num / fps:.2f}", flush=True)
            output = OUTPUT / job['output']
            if job['id'] in completed_ids and output.is_file():
                verify_video(output, frame_num, fps)
                continue
            image_path = (jobs_path.parent / job['image']).resolve()
            if not image_path.is_file():
                raise RuntimeError(f"E_INPUT: {job['id']} input image is missing")
            if sha256(image_path) != job['source_image_sha256']:
                raise RuntimeError(f"E_INPUT: {job['id']} input image hash mismatch")
            with Image.open(image_path) as source:
                image = resizecrop(source.convert('RGB'), height, width)
            constraints = '; '.join(job.get('constraints', []))
            prompt = job['prompt'] + ('. Requirements: ' + constraints if constraints else '')
            motion = job.get('motion')
            if isinstance(motion, dict):
                details = ', '.join(f'{key}={motion[key]}' for key in ('strength', 'camera')
                                    if key in motion)
                if details:
                    prompt += '. Motion profile: ' + details
            generator = torch.Generator(device='cuda').manual_seed(int(job['seed']))
            with torch.cuda.amp.autocast(dtype=torch_dtype), torch.no_grad():
                frames = pipeline(
                    image=image,
                    prompt=prompt,
                    negative_prompt=job.get('negative_prompt') or '',
                    height=height,
                    width=width,
                    num_frames=frame_num,
                    num_inference_steps=inference_steps,
                    guidance_scale=guidance_scale,
                    shift=shift,
                    generator=generator,
                )[0]
            output.parent.mkdir(parents=True, exist_ok=True)
            partial = output.with_name(output.stem + '.partial' + output.suffix)
            imageio.mimwrite(partial, frames, fps=fps, quality=8,
                             output_params=['-loglevel', 'error'])
            probe = verify_video(partial, frame_num, fps)
            partial.replace(output)
            completed_rows.append({
                'id': job['id'], 'status': 'completed',
                'cache_key': job['cache_key'], 'output': job['output'],
                'sha256': sha256(output), 'frame_num': frame_num,
                'fps': fps, 'generated_duration_sec': frame_num / fps, 'probe': probe,
            })
            if backend['monitoring']['step_timing']:
                print(f"[skyreels] job={job['id']} elapsed_sec={time.perf_counter() - job_started:.2f}",
                      flush=True)
            write_json(results_path, {
                'version': 3, 'provider': PROVIDER,
                'runtime_plan_digest': (payload.get('runtime_plan') or {}).get('plan_digest'),
                'model': backend.get('model'),
                'model_revision': backend.get('model_revision'),
                'source_revision': backend.get('source_revision'),
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
            'version': 3, 'provider': PROVIDER,
            'runtime_plan_digest': (payload.get('runtime_plan') or {}).get('plan_digest'),
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'results': completed_rows + [failed],
        })
        raise


if __name__ == '__main__':
    main()
