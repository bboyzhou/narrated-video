"""Registry and migration facade for generated-video providers."""
from .base import file_sha256, require
from .cogvideox import CogVideoXProvider
from .cloud import CloudI2VProvider
from .skyreels_v2 import SkyReelsV2Provider
from .svd_xt import SvdXtProvider
from .wan22 import Wan22Provider


_PROVIDERS = {item.provider: item() for item in (
    SkyReelsV2Provider, Wan22Provider, CogVideoXProvider, SvdXtProvider,
    CloudI2VProvider,
)}

_LEGACY = {
    'skyreels_v2_kaggle': ('skyreels_v2', 'kaggle'),
    'svd_xt_kaggle': ('svd_xt', 'kaggle'),
    'wan22_kaggle': ('wan22', 'kaggle'),
    'cogvideox_kaggle': ('cogvideox', 'kaggle'),
    'cogvideox_colab': ('cogvideox', 'colab'),
}

PROVIDER_REGISTRY = {
    'browser_i2v': {'type': 'i2v', 'tier': 'experimental', 'runtimes': ['browser']},
    'skyreels_v2': {'type': 'i2v', 'tier': 'experimental',
                    'runtimes': ['local', 'kaggle', 'runpod', 'remote_worker']},
    'wan22': {'type': 'i2v', 'tier': 'experimental',
              'runtimes': ['local', 'kaggle', 'runpod', 'remote_worker']},
    'cogvideox': {'type': 'i2v', 'tier': 'experimental',
                  'runtimes': ['local', 'kaggle', 'colab', 'runpod', 'remote_worker']},
    'svd_xt': {'type': 'i2v', 'tier': 'experimental',
               'runtimes': ['local', 'kaggle', 'colab', 'runpod', 'remote_worker']},
    'cloud_i2v': {'type': 'i2v', 'tier': 'production', 'runtimes': ['cloud_api']},
    'remotion_motion': {'type': 'motion', 'tier': 'production', 'runtimes': ['local']},
}


def normalize_provider(provider, runtime=None):
    if provider in _LEGACY:
        normalized, legacy_runtime = _LEGACY[provider]
        return normalized, runtime or {'type': legacy_runtime}
    return provider, runtime


def get_video_generator(provider):
    provider, _ = normalize_provider(provider)
    require(provider in _PROVIDERS,
            'Unknown generated-video provider: ' + str(provider) +
            '; available: ' + ', '.join(sorted(_PROVIDERS)))
    return _PROVIDERS[provider]


def provider_for_plan(plan, project):
    generation = plan.get('generation') or {}
    provider = generation.get('provider') or project.get('video_generation', {}).get('provider')
    require(provider, plan.get('id', '?') + ': generated_video needs generation.provider')
    return normalize_provider(provider)[0]


def runtime_for_plan(plan, project):
    generation = plan.get('generation') or {}
    original = generation.get('provider') or project.get('video_generation', {}).get('provider')
    runtime = generation.get('runtime') or project.get('video_generation', {}).get('runtime')
    provider, migrated = normalize_provider(original, runtime)
    if provider == 'cloud_i2v' and (not migrated or migrated == 'auto' or
                                    (isinstance(migrated, dict) and migrated.get('type') == 'auto')):
        migrated = {'type': 'cloud_api'}
    return migrated or {'type': 'local'}


def build_video_job(plan, image, image_sha256, project):
    provider = provider_for_plan(plan, project)
    return get_video_generator(provider).make_job(
        plan, image, image_sha256, project, runtime_for_plan(plan, project))


def validate_video_policy(project, plans):
    selected = [plan for plan in plans if plan.get('asset_strategy') == 'generated_video']
    video = project.get('video_generation', {})
    require(isinstance(video, dict), 'video_generation must be an object')
    if not selected:
        return set()
    require(video.get('enabled', True),
            'generated_video shots exist but video_generation.enabled is false')
    policy = video.get('policy', 'selected')
    require(policy in ('none', 'highlights', 'selected', 'all'),
            'video_generation.policy must be none, highlights, selected or all')
    require(policy != 'none', 'video_generation.policy=none conflicts with generated_video shots')
    budget = video.get('i2v_budget') or {}
    maximum = budget.get('max_shots', video.get('max_scenes'))
    if maximum is not None:
        require(type(maximum) is int and maximum >= 1,
                'video_generation.i2v_budget.max_shots must be a positive integer')
        require(len(selected) <= maximum,
                'generated_video shot count exceeds the project I2V budget')
    max_seconds = budget.get('max_generated_seconds_per_shot')
    providers = set()
    for plan in selected:
        provider = provider_for_plan(plan, project)
        providers.add(provider)
        generation = plan.get('generation') or {}
        target = generation.get('target_duration_sec', generation.get('duration_target'))
        if max_seconds is not None:
            require(type(max_seconds) in (int, float) and max_seconds > 0,
                    'i2v_budget.max_generated_seconds_per_shot must be positive')
            # This limits the generated clip intent, not the final timeline duration.
            require(target is not None,
                    plan.get('id', '?') + ': generated_video needs target_duration_sec')
        _, _, runtime_plan = get_video_generator(provider).make_job(
            plan, plan.get('source_image', ''), '0' * 64, project,
            runtime_for_plan(plan, project))
        if max_seconds is not None:
            fps = float(runtime_plan['execution']['fps'])
            require(runtime_plan['generated_duration_sec'] <= float(max_seconds) + 1.1 / fps,
                    plan.get('id', '?') + ': planned generated duration exceeds I2V budget')
    if policy == 'all':
        require(len(selected) == len(plans),
                'video_generation.policy=all requires every storyboard shot to use generated_video')
    return providers


__all__ = ['PROVIDER_REGISTRY', 'build_video_job', 'file_sha256',
           'get_video_generator', 'normalize_provider', 'provider_for_plan',
           'runtime_for_plan', 'validate_video_policy']
