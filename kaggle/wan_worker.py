#!/usr/bin/env python3
"""Distributed Wan2.2 TI2V-5B batch worker; launch with torchrun."""
import argparse
import hashlib
import json
import os
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

    wan_root = Path(args.wan_root).resolve()
    ckpt_dir = Path(args.ckpt_dir).resolve()
    require((wan_root / 'wan').is_dir(), 'Wan2.2 source tree missing: ' + str(wan_root))
    require(ckpt_dir.is_dir(), 'Wan2.2 checkpoint directory missing: ' + str(ckpt_dir))
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
    require(world_size == int(backend['world_size']), 'torchrun world size does not match job backend')
    require(torch.cuda.device_count() >= world_size,
            'Requested GPUs are unavailable; select a Kaggle dual-GPU session')
    torch.cuda.set_device(local_rank)
    dist.init_process_group('nccl', init_method='env://', rank=rank, world_size=world_size)

    # Wan's sequence-parallel helper is initialized by the official generate.py.
    if int(backend['ulysses_size']) > 1:
        from wan.distributed.util import init_distributed_group
        init_distributed_group()

    cfg = WAN_CONFIGS[backend['task']]
    require(cfg.num_heads % int(backend['ulysses_size']) == 0,
            'ulysses_size must divide the model attention head count')
    model = wan.WanTI2V(
        config=cfg,
        checkpoint_dir=str(ckpt_dir),
        device_id=local_rank,
        rank=rank,
        t5_fsdp=bool(backend.get('t5_fsdp', True)),
        dit_fsdp=bool(backend.get('dit_fsdp', True)),
        use_sp=int(backend['ulysses_size']) > 1,
        t5_cpu=bool(backend.get('t5_cpu', False)),
        convert_model_dtype=bool(backend.get('convert_model_dtype', False)),
    )
    output_root = Path(args.output_root).resolve()
    results = []
    active_job = None
    try:
        for job in payload.get('jobs', []):
            active_job = job
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
                output = output_root / job['output']
                output.parent.mkdir(parents=True, exist_ok=True)
                partial = output.with_suffix('.partial.mp4')
                save_video(tensor=video[None], save_file=str(partial),
                           fps=int(job['output_fps']), nrow=1,
                           normalize=True, value_range=(-1, 1))
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
            torch.cuda.synchronize()
            dist.barrier()
    except Exception as error:
        if rank == 0:
            results.append({'id': active_job.get('id') if active_job else None,
                            'status': 'failed', 'error': str(error)})
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
