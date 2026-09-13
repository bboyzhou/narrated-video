"""SkyReels-V2 provider planner; no runtime or GPU is encoded in its identity."""
from .base import I2VProvider


class SkyReelsV2Provider(I2VProvider):
    provider = 'skyreels_v2'
    legacy_ids = ('skyreels_v2_kaggle',)
    adapter_revision = 6
    supported_runtimes = ('local', 'kaggle', 'runpod', 'remote_worker')
    model_defaults = {
        'engine': 'skyreels_v2_native_i2v',
        'model': 'Skywork/SkyReels-V2-I2V-1.3B-540P',
        'model_revision': 'e86231f3882225e5a93eeec740c77bc7f01954ca',
        'source_revision': '9351d13152207cc04de780e055346b08ade0b851',
        'source_sha256': '3571f1f6d2da99a360d879fb6acf91850ce8c1455c8f67d13501a5b0159c77da',
    }

    def capabilities(self):
        return {**super().capabilities(), 'supports_multi_gpu': True,
                'supports_teacache': True, 'supports_ret_steps': True,
                'recommended_max_generated_seconds': 6}

    def _plan(self, profile, runtime, hardware, request):
        _, gpu = self._hardware(hardware)
        vram = gpu['vram_gib']
        constrained = not vram or vram < 24
        name = profile['name']
        frames = 49 if name == 'smoke' else 97
        if name == 'max_quality' and vram >= 40:
            frames = 145
        steps = {'smoke': 12, 'fast': 20, 'balanced': 25,
                 'quality': 40, 'max_quality': 50}[name]
        teacache = name in ('fast', 'balanced') and constrained
        return {
            'dtype': 'bfloat16' if gpu['supports_bf16'] and not constrained else 'float16',
            'resolution': '960x544', 'frame_num': frames, 'fps': 24,
            'inference_steps': steps, 'guidance_scale': 5.0, 'shift': 3.0,
            'attention_backend': 'sdpa' if constrained else 'auto',
            'teacache': teacache, 'teacache_thresh': 0.1,
            'use_ret_steps': teacache and name != 'quality',
            'offload': constrained, 'world_size': 1,
        }


# Compatibility import only; new manifests always use provider=skyreels_v2.
SkyReelsV2KaggleGenerator = SkyReelsV2Provider
