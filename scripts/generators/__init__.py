"""Registry for generated-video providers."""
from .base import file_sha256, require
from .cogvideox_colab import CogVideoXColabGenerator
from .wan_kaggle import WanKaggleGenerator


_GENERATORS = {
    CogVideoXColabGenerator.provider: CogVideoXColabGenerator(),
    WanKaggleGenerator.provider: WanKaggleGenerator(),
}


def get_video_generator(provider):
    require(provider in _GENERATORS,
            'Unknown generated-video provider: ' + str(provider) +
            '; available: ' + ', '.join(sorted(_GENERATORS)))
    return _GENERATORS[provider]


def provider_for_plan(plan, project):
    generation = plan.get('generation') or {}
    provider = generation.get('provider') or project.get('video_generation', {}).get('provider')
    require(provider, plan.get('id', '?') + ': generated_video needs generation.provider')
    return provider


def build_video_job(plan, image, image_sha256, project):
    provider = provider_for_plan(plan, project)
    job, backend = get_video_generator(provider).make_job(plan, image, image_sha256, project)
    return job, backend


def validate_video_policy(project, plans):
    selected = [plan for plan in plans if plan.get('asset_strategy') == 'generated_video']
    video = project.get('video_generation', {})
    require(isinstance(video, dict), 'video_generation must be an object')
    if not selected:
        return
    if video:
        require(video.get('enabled', True), 'generated_video shots exist but video_generation.enabled is false')
        policy = video.get('policy', 'selected')
        require(policy in ('none', 'highlights', 'selected', 'all'),
                'video_generation.policy must be none, highlights, selected or all')
        require(policy != 'none', 'video_generation.policy=none conflicts with generated_video shots')
        maximum = video.get('max_scenes')
        if maximum is not None:
            require(type(maximum) is int and maximum >= 1,
                    'video_generation.max_scenes must be a positive integer')
            require(len(selected) <= maximum,
                    'generated_video shot count exceeds video_generation.max_scenes')
        if policy == 'all':
            require(len(selected) == len(plans),
                    'video_generation.policy=all requires every storyboard shot to use generated_video')
    providers = set()
    for plan in selected:
        provider = provider_for_plan(plan, project)
        providers.add(provider)
        get_video_generator(provider).make_job(plan, plan.get('source_image', ''), '0' * 64, project)
    return providers


__all__ = ['build_video_job', 'file_sha256', 'get_video_generator',
           'provider_for_plan', 'validate_video_policy']
