"""Hero-shot routing and failure isolation for optional I2V enhancement."""

FAILURE_CODES = {
    'timeout': 'E_I2V_TIMEOUT', 'provider': 'E_PROVIDER_FAILURE',
    'runtime': 'E_RUNTIME_FAILURE', 'output': 'E_EXPORT',
}


def select_provider(preferred, available, registry, runtime_type):
    """Select a provider without conflating it with runtime selection."""
    candidates = []
    for provider in available:
        metadata = registry.get(provider) or {}
        if metadata.get('type') != 'i2v' or runtime_type not in metadata.get('runtimes', []):
            continue
        score = (100 if provider == preferred else 0) + {
            'production': 20, 'experimental': 5,
        }.get(metadata.get('tier'), 0)
        candidates.append((score, provider))
    return max(candidates)[1] if candidates else 'remotion_motion'


def is_i2v_candidate(shot):
    return (shot.get('motion_mode') == 'i2v' or
            shot.get('asset_strategy') == 'generated_video')


def route_shots(shots, video_generation):
    """Select only explicitly marked hero shots within the project budget."""
    budget = video_generation.get('i2v_budget') or {}
    if not video_generation.get('enabled') or budget.get('enabled', True) is False:
        return {'i2v': [], 'motion': list(shots)}
    maximum = budget.get('max_shots', video_generation.get('max_scenes', 3))
    candidates = [shot for shot in shots if is_i2v_candidate(shot)]
    selected = candidates[:maximum]
    selected_ids = {shot.get('id') for shot in selected}
    return {'i2v': selected,
            'motion': [shot for shot in shots if shot.get('id') not in selected_ids]}


def fallback_result(requested_provider, reason, fallback_asset=None):
    code = FAILURE_CODES.get(reason, reason if str(reason).startswith('E_')
                             else 'E_PROVIDER_FAILURE')
    return {
        'requested_provider': requested_provider,
        'actual_provider': 'remotion_motion',
        'status': 'fallback', 'reason': code,
        **({'fallback_asset': fallback_asset} if fallback_asset else {}),
    }
