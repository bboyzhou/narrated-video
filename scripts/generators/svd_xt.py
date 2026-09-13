"""Stable Video Diffusion XT provider planner."""
from .base import I2VProvider


class SvdXtProvider(I2VProvider):
    provider = 'svd_xt'
    legacy_ids = ('svd_xt_kaggle',)
    model_defaults = {
        'engine': 'diffusers_svd',
        'model': 'stabilityai/stable-video-diffusion-img2vid-xt',
        'model_revision': 'requires-project-pin',
    }

    def capabilities(self):
        return {**super().capabilities(), 'supports_bf16': False,
                'recommended_max_generated_seconds': 4}

    def _plan(self, profile, runtime, hardware, request):
        _, gpu = self._hardware(hardware)
        frames = {'smoke': 8, 'fast': 14, 'balanced': 25,
                  'quality': 25, 'max_quality': 25}[profile['name']]
        steps = {'smoke': 8, 'fast': 15, 'balanced': 25,
                 'quality': 35, 'max_quality': 50}[profile['name']]
        return {
            'dtype': 'float16', 'resolution': '1024x576', 'frame_num': frames,
            'fps': 7, 'inference_steps': steps, 'decode_chunk_size': 2,
            'motion_bucket_id': 80, 'noise_aug_strength': 0.02,
            'model_cpu_offload': not gpu['vram_gib'] or gpu['vram_gib'] < 24,
            'forward_chunking': True, 'vae_slicing': False, 'world_size': 1,
        }


SvdKaggleGenerator = SvdXtProvider
