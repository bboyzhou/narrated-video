"""The worker boundary: content requests plus an already generated RuntimePlan."""
from __future__ import annotations


FORBIDDEN_JOB_FIELDS = {
    'provider', 'runtime', 'profile', 'frame_num', 'frames', 'steps',
    'inference_steps', 'dtype', 'offload', 'world_size',
    'attention_backend', 'teacache',
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_worker_input(manifest):
    _require(manifest.get('version') == 3, 'Worker requires video_jobs v3')
    plan = manifest.get('runtime_plan')
    _require(isinstance(plan, dict), 'Worker requires a generated RuntimePlan')
    _require(plan.get('provider') == manifest.get('provider'),
             'RuntimePlan provider does not match manifest')
    _require(plan.get('runtime') == (manifest.get('runtime') or {}).get('type'),
             'RuntimePlan runtime does not match manifest')
    _require(plan.get('profile') == manifest.get('profile'),
             'RuntimePlan profile does not match manifest')
    execution = plan.get('execution')
    _require(isinstance(execution, dict), 'RuntimePlan.execution must be an object')
    for field in ('dtype', 'resolution', 'frame_num', 'fps', 'world_size'):
        _require(field in execution, 'RuntimePlan.execution missing ' + field)
    jobs = manifest.get('jobs')
    _require(isinstance(jobs, list), 'jobs must be a list')
    for job in jobs:
        supplied = sorted(FORBIDDEN_JOB_FIELDS.intersection(job))
        _require(not supplied, str(job.get('id', '?')) +
                 ': worker request contains planner-owned fields: ' + ', '.join(supplied))
    return jobs, plan


def format_runtime_plan(plan, hardware=None, target_seconds=None):
    execution = plan['execution']
    hardware = hardware or plan.get('hardware') or {}
    gpus = hardware.get('gpus') or []
    gpu = gpus[0].get('name') if gpus else 'unknown'
    lines = [
        'Provider:          ' + str(plan['provider']),
        'Profile:           ' + str(plan['profile']),
        'Runtime:           ' + str(plan['runtime']),
        'GPU:               ' + gpu,
        'GPU Count:         ' + str(hardware.get('gpu_count', len(gpus))),
        'GPU Used:          ' + str(execution.get('world_size', 1)),
        'dtype:             ' + str(execution.get('dtype')),
        'resolution:        ' + str(execution.get('resolution')),
        'frames:            ' + str(execution.get('frame_num')),
        'fps:               ' + str(execution.get('fps')),
        'steps:             ' + str(execution.get('inference_steps',
                                                   execution.get('sample_steps'))),
        'attention:         ' + str(execution.get('attention_backend', 'n/a')),
        'TeaCache:          ' + ('ON' if execution.get('teacache') else 'OFF'),
        'offload:           ' + ('ON' if execution.get('offload') or
                                  execution.get('offload_model') or
                                  execution.get('model_cpu_offload') else 'OFF'),
        'generated seconds: ' + str(plan.get('generated_duration_sec')),
    ]
    if target_seconds is not None:
        lines.append('target seconds:    ' + str(target_seconds))
    return '\n'.join(lines)
