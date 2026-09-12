#!/usr/bin/env python3
"""Official native Wan2.2 TI2V-5B batch worker; launch with torchrun."""
import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def verify_video(path, ffprobe='ffprobe'):
    command = [ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
               '-show_entries', 'stream=codec_name,nb_read_frames',
               '-show_entries', 'format=duration', '-of', 'json', str(path)]
    try:
        completed = subprocess.run(command, check=True, capture_output=True,
                                   text=True)
        report = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise RuntimeError('E_EXPORT: ffprobe validation failed: ' + str(error)) from error
    streams = report.get('streams') or []
    duration = float((report.get('format') or {}).get('duration') or 0)
    frame_count = int((streams[0].get('nb_read_frames') or 0)) if streams else 0
    if not streams or duration <= 0 or frame_count <= 0:
        raise RuntimeError('E_EXPORT: output has no valid video stream, duration, or frames')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', required=True)
    parser.add_argument('--wan-root', required=True)
    parser.add_argument('--ckpt-dir', required=True)
    parser.add_argument('--output-root', default='/kaggle/working')
    args = parser.parse_args()

    job_path = Path(args.jobs).resolve()
    root = job_path.parent
    payload = json.loads(job_path.read_text(encoding='utf-8-sig'))
    backend = payload.get('backend', {})
    require(payload.get('version') == 2 and payload.get('provider') == 'wan22_kaggle',
            'Expected a version 2 wan22_kaggle job manifest')
    require(backend.get('task') == 'ti2v-5B', 'Only Wan2.2 TI2V-5B is supported')
    world_size_config = int(backend.get('world_size', 1))
    ulysses_size = int(backend.get('ulysses_size', 1))
    t5_fsdp = bool(backend.get('t5_fsdp', False))
    dit_fsdp = bool(backend.get('dit_fsdp', False))
    t5_cpu = bool(backend.get('t5_cpu', False))
    convert_model_dtype = bool(backend.get('convert_model_dtype', False))
    require(world_size_config == 1 or ulysses_size == world_size_config,
            'ulysses_size must equal world_size for native distributed inference')
    require(not t5_cpu or not t5_fsdp,
            't5_cpu is incompatible with t5_fsdp in the official Wan2.2 worker')
    require(not convert_model_dtype or not dit_fsdp,
            'convert_model_dtype is incompatible with dit_fsdp in the official Wan2.2 worker')

    wan_root = Path(args.wan_root).resolve()
    ckpt_dir = Path(args.ckpt_dir).resolve()
    require((wan_root / 'wan').is_dir(), 'Wan2.2 source tree missing: ' + str(wan_root))
    require(ckpt_dir.is_dir(), 'Wan2.2 checkpoint directory missing: ' + str(ckpt_dir))
    required_weights = [
        'Wan2.2_VAE.pth',
        'diffusion_pytorch_model-00001-of-00003.safetensors',
        'diffusion_pytorch_model-00002-of-00003.safetensors',
        'diffusion_pytorch_model-00003-of-00003.safetensors',
        'diffusion_pytorch_model.safetensors.index.json',
        'models_t5_umt5-xxl-enc-bf16.pth',
    ]
    for filename in required_weights:
        require((ckpt_dir / filename).is_file(),
                'Wan2.2 checkpoint file missing: ' + str(ckpt_dir / filename))
    sys.path.insert(0, str(wan_root))

    import torch
    import torch.distributed as dist
    from PIL import Image
    import wan
    from wan.configs import MAX_AREA_CONFIGS, SIZE_CONFIGS, WAN_CONFIGS
    from wan.utils.utils import save_video

    rank = int(os.environ.get('RANK', '0'))
    world_size = int(os.environ.get('WORLD_SIZE', '1'))
    local_rank = int(os.environ.get('LOCAL_RANK', '0'))
    require(world_size == world_size_config, 'torchrun world size does not match job backend')
    require(torch.cuda.device_count() >= world_size,
            f'Requested {world_size} GPUs are unavailable')
    torch.cuda.set_device(local_rank)
    dist.init_process_group('nccl', init_method='env://', rank=rank, world_size=world_size)

    # Wan's sequence-parallel helper is initialized by the official generate.py.
    if ulysses_size > 1:
        from wan.distributed.util import init_distributed_group
        init_distributed_group()

    cfg = WAN_CONFIGS[backend['task']]
    require(cfg.num_heads % ulysses_size == 0,
            'ulysses_size must divide the model attention head count')
    model = wan.WanTI2V(
        config=cfg,
        checkpoint_dir=str(ckpt_dir),
        device_id=local_rank,
        rank=rank,
        t5_fsdp=t5_fsdp,
        dit_fsdp=dit_fsdp,
        use_sp=ulysses_size > 1,
        t5_cpu=t5_cpu,
        convert_model_dtype=convert_model_dtype,
    )
    output_root = Path(args.output_root).resolve()
    results_path = output_root / 'results.json'
    previous = json.loads(results_path.read_text(encoding='utf-8')) if results_path.is_file() else {}
    results = [row for row in previous.get('results', []) if row.get('status') == 'completed']
    completed_ids = {row.get('id') for row in results}
    active_job = None
    try:
        for job in payload.get('jobs', []):
            active_job = job
            output = output_root / job['output']
            if job['id'] in completed_ids and output.is_file():
                try:
                    verify_video(output)
                    continue
                except RuntimeError:
                    completed_ids.discard(job['id'])
            image_path = (root / job['image']).resolve()
            require(image_path.is_file(), job['id'] + ': input image missing')
            require(sha256(image_path) == job['source_image_sha256'],
                    job['id'] + ': input image hash mismatch')
            prompt = job['prompt']
            if job.get('constraints'):
                prompt += '\nConstraints: ' + '; '.join(job['constraints'])
            image = Image.open(image_path).convert('RGB')
            video = model.generate(
                prompt,
                img=image,
                n_prompt=job.get('negative_prompt', ''),
                size=SIZE_CONFIGS[backend['size']],
                max_area=MAX_AREA_CONFIGS[backend['size']],
                frame_num=int(job['frame_num']),
                shift=float(job['sample_shift']),
                sample_solver=job['sample_solver'],
                sampling_steps=int(job['sample_steps']),
                guide_scale=float(job['sample_guide_scale']),
                seed=int(job['seed']),
                offload_model=bool(backend.get('offload_model', False)),
            )
            if rank == 0:
                output.parent.mkdir(parents=True, exist_ok=True)
                partial = output.with_suffix(output.suffix + '.partial')
                save_video(tensor=video[None], save_file=str(partial),
                           fps=int(job['output_fps']), nrow=1,
                           normalize=True, value_range=(-1, 1))
                verify_video(partial)
                partial.replace(output)
                results.append({'id': job['id'], 'status': 'completed',
                                'cache_key': job['cache_key'],
                                'output': job['output'], 'sha256': sha256(output),
                                'frame_num': job['frame_num'],
                                'fps': job['output_fps']})
                write_json(output_root / 'results.json', {
                    'version': 2, 'provider': 'wan22_kaggle',
                    'model': backend.get('model'),
                    'model_revision': backend.get('model_revision'),
                    'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                    'results': results,
                })
            del video
            del image
            gc.collect()
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            dist.barrier()
    except Exception as error:
        if rank == 0:
            error_text = str(error)
            if isinstance(error, torch.cuda.OutOfMemoryError):
                error_code = 'E_GPU_OOM'
            elif 'E_EXPORT:' in error_text:
                error_code = 'E_EXPORT'
            elif isinstance(error, (FileNotFoundError, OSError)):
                error_code = 'E_INPUT'
            else:
                error_code = 'E_GENERATION'
            results.append({'id': active_job.get('id') if active_job else None,
                            'status': 'failed', 'code': error_code,
                            'error': error_text})
            write_json(output_root / 'results.json', {
                'version': 2, 'provider': 'wan22_kaggle',
                'model': backend.get('model'),
                'model_revision': backend.get('model_revision'),
                'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'results': results,
            })
        raise
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()


if __name__ == '__main__':
    main()
