"""Provider-neutral contracts for externally generated video assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


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


def provider_settings(project, provider):
    """Merge legacy top-level provider settings with the provider map."""
    video = project.get('video_generation', {})
    require(isinstance(video, dict), 'video_generation must be an object')
    common = {'enabled', 'provider', 'execution', 'policy', 'max_scenes', 'providers'}
    legacy = ({key: value for key, value in video.items() if key not in common}
              if video.get('provider') == provider else {})
    providers = video.get('providers', {})
    require(isinstance(providers, dict), 'video_generation.providers must be an object')
    nested = providers.get(provider, {})
    require(isinstance(nested, dict), 'video_generation.providers.' + provider + ' must be an object')
    return {**legacy, **nested}


class VideoGenerator:
    """Small adapter surface shared by local packaging and remote workers."""

    provider = None
    mode = 'i2v'
    adapter_revision = 1
    defaults = {}

    def backend(self, project):
        backend = {**self.defaults, **provider_settings(project, self.provider)}
        self.validate_backend(backend)
        return backend

    def validate_backend(self, backend):
        require(isinstance(backend, dict), self.provider + ' backend must be an object')

    def normalize_generation(self, generation, backend):
        require(isinstance(generation, dict), self.provider + ' generation must be an object')
        require(generation.get('mode', self.mode) == self.mode,
                self.provider + ' only supports mode=' + self.mode)
        seed = generation.get('seed')
        require(type(seed) is int and 0 <= seed <= 2**32 - 1,
                self.provider + ' seed must be an integer in 0..2^32-1')
        duration = generation.get('duration_target')
        require(type(duration) in (int, float) and 1 <= duration <= 30,
                self.provider + ' duration_target must be 1..30 seconds')
        return {'mode': self.mode, 'seed': seed, 'duration_target': float(duration)}

    def make_job(self, plan, image, image_sha256, project):
        backend = self.backend(project)
        generation = self.normalize_generation(plan.get('generation'), backend)
        prompt = plan.get('motion_prompt')
        constraints = plan.get('motion_constraints')
        require(isinstance(prompt, str) and prompt.strip(), plan.get('id', '?') + '.motion_prompt must be nonempty')
        require(isinstance(constraints, list) and constraints and
                all(isinstance(item, str) and item.strip() for item in constraints),
                plan.get('id', '?') + '.motion_constraints must be a nonempty text list')
        identity = {
            'schema': 2,
            'provider': self.provider,
            'adapter_revision': self.adapter_revision,
            'backend': backend,
            'source_image_sha256': image_sha256,
            'motion_prompt': prompt,
            'motion_constraints': constraints,
            'generation': generation,
        }
        cache_key = canonical_digest(identity)
        return ({
            'id': plan['id'],
            'image': image,
            'source_image_sha256': image_sha256,
            'prompt': prompt,
            'negative_prompt': plan.get('negative_prompt', ''),
            'constraints': constraints,
            'provider': self.provider,
            **generation,
            'cache_key': cache_key,
            'output': 'output/' + plan['id'] + '.mp4',
        }, backend)
