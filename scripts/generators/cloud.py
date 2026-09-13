"""Managed cloud I2V service provider."""
from .base import I2VProvider


class CloudI2VProvider(I2VProvider):
    provider = 'cloud_i2v'
    supported_runtimes = ('cloud_api',)
    model_defaults = {
        'engine': 'cloud_api', 'model': 'configured-cloud-i2v',
        'model_revision': 'requires-project-pin',
    }

    def capabilities(self):
        return {**super().capabilities(), 'supports_multi_gpu': False,
                'supports_fp16': False, 'supports_bf16': False,
                'supports_offload': False,
                'recommended_max_generated_seconds': 8}

    def _plan(self, profile, runtime, hardware, request):
        seconds = min(profile['max_generated_seconds'], request['target_duration_sec'])
        return {
            'dtype': 'managed', 'resolution': '1280x720',
            'frame_num': max(1, round(seconds * 24)), 'fps': 24,
            'service_quality': profile['name'], 'world_size': 1,
        }

    def estimate_timeout(self, execution, hardware):
        expected = max(60, int(execution['frame_num'] * 2))
        return {'expected_runtime_sec': expected,
                'soft_timeout_sec': expected * 2,
                'hard_timeout_sec': expected * 4}
