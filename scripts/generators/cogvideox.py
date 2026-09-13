"""CogVideoX I2V provider planner."""
from .base import I2VProvider


class CogVideoXProvider(I2VProvider):
    provider = 'cogvideox'
    legacy_ids = ('cogvideox_kaggle', 'cogvideox_colab')
    model_defaults = {
        'engine': 'diffusers_cogvideox_i2v',
        'model': 'zai-org/CogVideoX-5b-I2V',
        'model_revision': 'a6f0f4858a8395e7429d82493864ce92bf73af11',
    }

    def _plan(self, profile, runtime, hardware, request):
        _, gpu = self._hardware(hardware)
        constrained = not gpu['vram_gib'] or gpu['vram_gib'] < 24
        steps = {'smoke': 10, 'fast': 25, 'balanced': 40,
                 'quality': 50, 'max_quality': 50}[profile['name']]
        return {
            'dtype': 'bfloat16' if gpu['supports_bf16'] and not constrained else 'float16',
            'resolution': '720x480', 'frame_num': 49, 'fps': 8,
            'inference_steps': steps, 'guidance_scale': 6.0,
            'quantization': 'torchao_int8_weight_only' if constrained else 'none',
            'sequential_cpu_offload': constrained, 'vae_slicing': constrained,
            'vae_tiling': constrained, 'world_size': 1,
        }


CogVideoXKaggleGenerator = CogVideoXProvider
CogVideoXColabGenerator = CogVideoXProvider
