"""Wan2.2 TI2V provider planner."""
from .base import I2VProvider


class Wan22Provider(I2VProvider):
    provider = 'wan22'
    legacy_ids = ('wan22_kaggle',)
    supported_runtimes = ('local', 'kaggle', 'runpod', 'remote_worker')
    model_defaults = {
        'engine': 'wan_native', 'model': 'Wan-AI/Wan2.2-TI2V-5B',
        'model_revision': 'requires-project-pin', 'task': 'ti2v-5B',
    }

    def capabilities(self):
        return {**super().capabilities(), 'supports_multi_gpu': True,
                'recommended_max_generated_seconds': 6}

    def _plan(self, profile, runtime, hardware, request):
        _, gpu = self._hardware(hardware)
        vram = gpu['vram_gib']
        # Unknown remote hardware receives a conservative smoke plan. The runtime
        # launcher must detect hardware and re-plan before invoking the worker.
        constrained = not vram or vram < 32
        frames = 5 if profile['name'] == 'smoke' or constrained else {
            'fast': 25, 'balanced': 49, 'quality': 73, 'max_quality': 121,
        }[profile['name']]
        steps = 8 if frames == 5 else {
            'fast': 15, 'balanced': 20, 'quality': 30, 'max_quality': 40,
        }[profile['name']]
        return {
            'dtype': 'bfloat16' if gpu['supports_bf16'] else 'float16',
            'resolution': '1280x704', 'frame_num': frames, 'fps': 24,
            'sample_steps': steps, 'sample_shift': 5.0,
            'sample_solver': 'unipc', 'sample_guide_scale': 5.0,
            't5_cpu': constrained, 'offload_model': constrained,
            'dit_fsdp': False, 't5_fsdp': False, 'ulysses_size': 1,
            'world_size': 1,
        }


WanKaggleGenerator = Wan22Provider
