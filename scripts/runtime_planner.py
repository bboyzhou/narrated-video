"""Re-plan a prepared manifest against hardware detected by its Runtime launcher."""
from __future__ import annotations

from generators import get_video_generator


def hardware_from_inventory(devices, ram_available_gib=0, software=None):
    gpus = []
    for item in devices or []:
        capability = str(item.get('compute_capability') or '')
        major = int(capability.split('.')[0]) if capability[:1].isdigit() else 0
        gpus.append({
            'name': item.get('name', 'unknown'),
            'vram_gib': float(item.get('vram_gib') or
                              item.get('memory_total_mib', 0) / 1024),
            'compute_capability': capability,
            'supports_fp16': major >= 5,
            'supports_bf16': major >= 8,
        })
    return {'gpus': gpus, 'ram_available_gib': ram_available_gib,
            'software': software or {}, 'detected': True}


def replan_manifest(manifest, hardware):
    """Return a copy with an actual-hardware RuntimePlan; Jobs remain unchanged."""
    provider = get_video_generator(manifest.get('provider'))
    jobs = manifest.get('jobs') or []
    target = max((float(job.get('target_duration_sec', 1)) for job in jobs), default=1)
    plan = provider.plan(
        {'target_duration_sec': target}, manifest.get('profile'),
        manifest.get('runtime') or {'type': 'local'}, hardware)
    return {**manifest, 'runtime_plan': plan}
