"""Provider contracts for model-independent I2V jobs and planned execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from planners import detect_hardware, get_profile, normalize_hardware
from runtimes import resolve_runtime


PERFORMANCE_FIELDS = {
    'frame_num', 'frames', 'output_fps', 'fps', 'size', 'resolution',
    'inference_steps', 'steps', 'guidance_scale', 'shift', 'sample_steps',
    'sample_shift', 'sample_solver', 'sample_guide_scale', 'decode_chunk_size',
    'motion_bucket_id', 'noise_aug_strength', 'dtype', 'compute_dtype',
    'offload', 'world_size', 'attention_backend', 'teacache',
    'gpu_mode', 'offline', 'bootstrap_packages',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def provider_settings(project, provider, aliases=()):
    """Read model/source metadata while rejecting execution parameters."""
    video = project.get('video_generation', {})
    require(isinstance(video, dict), 'video_generation must be an object')
    providers = video.get('providers', {})
    require(isinstance(providers, dict), 'video_generation.providers must be an object')
    selected = {}
    for name in (provider, *aliases):
        if name in providers:
            require(isinstance(providers[name], dict),
                    'video_generation.providers.' + name + ' must be an object')
            selected = providers[name]
            break
    forbidden = sorted(PERFORMANCE_FIELDS.intersection(selected))
    require(not forbidden,
            'Provider configuration contains planner-owned execution fields: ' +
            ', '.join(forbidden))
    return dict(selected)


class I2VProvider:
    """A model/service provider. Runtime selection is deliberately external."""

    provider = None
    legacy_ids = ()
    adapter_revision = 1
    model_defaults = {}
    supported_runtimes = ('local', 'kaggle', 'colab', 'runpod', 'remote_worker')

    def capabilities(self):
        return {
            'supports_i2v': True, 'supports_t2v': False,
            'supports_multi_gpu': False, 'supports_fp16': True,
            'supports_bf16': True, 'supports_teacache': False,
            'supports_ret_steps': False, 'supports_offload': True,
        }

    def configuration(self, project):
        value = {**self.model_defaults,
                 **provider_settings(project, self.provider, self.legacy_ids)}
        revision = value.get('model_revision')
        require(isinstance(value.get('model'), str) and value['model'].strip(),
                self.provider + ' requires a model identifier')
        require(isinstance(revision, str) and revision.strip() and
                revision not in ('main', 'latest', 'requires-project-pin'),
                self.provider + ' requires a pinned model_revision')
        return value

    def validate_request(self, generation):
        require(isinstance(generation, dict), self.provider + ' generation must be an object')
        supplied = sorted(PERFORMANCE_FIELDS.intersection(generation))
        require(not supplied,
                self.provider + ' execution parameters are planner-owned: ' + ', '.join(supplied))
        require(generation.get('mode', 'i2v') == 'i2v',
                self.provider + ' only supports mode=i2v')
        seed = generation.get('seed')
        require(type(seed) is int and 0 <= seed <= 2**32 - 1,
                self.provider + ' seed must be an integer in 0..2^32-1')
        duration = generation.get('target_duration_sec', generation.get('duration_target'))
        require(type(duration) in (int, float) and 1 <= duration <= 30,
                self.provider + ' target_duration_sec must be 1..30 seconds')
        motion = generation.get('motion')
        if motion is not None:
            require(isinstance(motion, dict), self.provider + ' motion must be an object')
        return {'mode': 'i2v', 'seed': seed, 'target_duration_sec': float(duration),
                **({'motion': motion} if motion is not None else {})}

    def _hardware(self, hardware):
        value = normalize_hardware(hardware)
        gpu = value['gpus'][0] if value['gpus'] else {
            'name': 'unknown', 'vram_gib': 0, 'supports_fp16': True,
            'supports_bf16': False, 'compute_capability': '',
        }
        return value, gpu

    def _plan(self, profile, runtime, hardware, request):
        raise NotImplementedError

    def estimate_timeout(self, execution, hardware):
        steps = execution.get('inference_steps', execution.get('sample_steps', 20))
        frames = execution.get('frame_num', 49)
        expected = max(120, int(frames * steps * 0.9))
        return {'expected_runtime_sec': expected,
                'soft_timeout_sec': int(expected * 1.5),
                'hard_timeout_sec': int(expected * 2.25)}

    def plan(self, request, profile, runtime, hardware):
        profile_value = get_profile(profile) if isinstance(profile, str) else profile
        require(isinstance(profile_value, dict) and profile_value.get('name'),
                'profile must be a named generic generation intent')
        runtime_value = resolve_runtime(runtime)
        require(runtime_value['type'] in self.supported_runtimes,
                self.provider + ' does not support runtime=' + runtime_value['type'])
        hardware_value = normalize_hardware(hardware)
        if not hardware_value['gpus'] and runtime_value.get('requested_type') in ('auto', 'local'):
            hardware_value = detect_hardware()
        maximum_vram = runtime_value.get('overrides', {}).get('max_vram_gib')
        if maximum_vram:
            for gpu in hardware_value['gpus']:
                gpu['vram_gib'] = min(gpu['vram_gib'], float(maximum_vram))
        execution = self._plan(profile_value, runtime_value, hardware_value, request)
        generated_seconds = execution['frame_num'] / execution['fps']
        value = {
            'provider': self.provider, 'runtime': runtime_value['type'],
            'profile': profile_value['name'], 'execution': execution,
            'generated_duration_sec': round(generated_seconds, 4),
            'hardware': hardware_value,
            'hardware_basis': ('detected' if hardware_value.get('detected') and
                               hardware_value['gpus'] else 'unknown_conservative'),
        }
        value['timeout'] = self.estimate_timeout(execution, hardware_value)
        value['plan_digest'] = canonical_digest({key: item for key, item in value.items()
                                                 if key != 'timeout'})
        return value

    def make_job(self, plan, image, image_sha256, project, runtime=None, hardware=None):
        generation = self.validate_request(plan.get('generation'))
        prompt = plan.get('motion_prompt')
        constraints = plan.get('motion_constraints')
        require(isinstance(prompt, str) and prompt.strip(),
                plan.get('id', '?') + '.motion_prompt must be nonempty')
        require(isinstance(constraints, list) and constraints and
                all(isinstance(item, str) and item.strip() for item in constraints),
                plan.get('id', '?') + '.motion_constraints must be a nonempty text list')
        motion = generation.get('motion')
        if motion is None and isinstance(plan.get('motion'), dict):
            motion = plan['motion']
        request = {'target_duration_sec': generation['target_duration_sec'],
                   **({'motion': motion} if motion is not None else {})}
        video = project.get('video_generation', {})
        profile_name = video.get('profile', 'balanced')
        runtime_value = resolve_runtime(runtime or video.get('runtime') or {'type': 'local'})
        hardware_value = hardware or runtime_value.get('hardware') or {}
        runtime_plan = self.plan(request, profile_name, runtime_value, hardware_value)
        provider_config = self.configuration(project)
        identity = {
            'schema': 3, 'provider': self.provider,
            'adapter_revision': self.adapter_revision,
            'provider_config': provider_config, 'profile': runtime_plan['profile'],
            'source_image_sha256': image_sha256, 'prompt': prompt,
            'constraints': constraints, 'negative_prompt': plan.get('negative_prompt', ''),
            'seed': generation['seed'], 'motion': motion,
        }
        cache_key = canonical_digest(identity)
        job = {
            'id': plan['id'], 'image': image,
            'source_image_sha256': image_sha256, 'prompt': prompt,
            'negative_prompt': plan.get('negative_prompt', ''),
            'constraints': constraints, 'seed': generation['seed'],
            'target_duration_sec': generation['target_duration_sec'],
            'cache_key': cache_key, 'output': 'output/' + plan['id'] + '.mp4',
        }
        if motion is not None:
            job['motion'] = motion
        return job, provider_config, runtime_plan


VideoGenerator = I2VProvider
