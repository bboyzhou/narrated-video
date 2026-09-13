"""Tests for the SkyReels-V2 Kaggle entry-point preflight."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (Path(__file__).resolve().parents[1] / 'kaggle' / 'skyreels_v2' /
               'run_skyreels_v2_job.py')
SPEC = importlib.util.spec_from_file_location('run_skyreels_v2_job', MODULE_PATH)
RUN_SKYREELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_SKYREELS)


class SkyReelsV2KaggleEntryTests(unittest.TestCase):
    def test_t4_is_accepted(self):
        RUN_SKYREELS.validate_gpu([{
            'name': 'Tesla T4', 'memory_total_mib': 15360,
            'memory_free_mib': 15000, 'compute_capability': '7.5',
        }])

    def test_p100_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'E_GPU_UNSUPPORTED.*P100'):
            RUN_SKYREELS.validate_gpu([{
                'name': 'Tesla P100-PCIE-16GB', 'memory_total_mib': 16384,
                'memory_free_mib': 16000, 'compute_capability': '6.0',
            }])

    def test_low_free_vram_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '13.5 GiB'):
            RUN_SKYREELS.validate_gpu([{
                'name': 'Tesla T4', 'memory_total_mib': 15360,
                'memory_free_mib': 12000, 'compute_capability': '7.5',
            }])

    def test_manifest_discovery_accepts_only_skyreels_contract(self):
        original_input = RUN_SKYREELS.INPUT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / 'datasets' / 'owner' / 'input' / 'versions' / '1'
            valid.mkdir(parents=True)
            (valid / 'video_jobs.json').write_text(json.dumps({
                'version': 3, 'provider': 'skyreels_v2', 'jobs': []
            }), encoding='utf-8')
            other = root / 'other'
            other.mkdir()
            (other / 'video_jobs.json').write_text(json.dumps({
                'version': 3, 'provider': 'cogvideox', 'jobs': []
            }), encoding='utf-8')
            try:
                RUN_SKYREELS.INPUT = root
                found = RUN_SKYREELS.fixed_manifest()
            finally:
                RUN_SKYREELS.INPUT = original_input
        self.assertEqual(found.name, 'video_jobs.json')
        self.assertIn('versions', str(found))

    def test_backend_requires_pinned_official_model(self):
        backend = {
            'engine': 'skyreels_v2_native_i2v',
            'model': RUN_SKYREELS.MODEL,
            'model_revision': RUN_SKYREELS.MODEL_REVISION,
            'source_revision': RUN_SKYREELS.SOURCE_REVISION,
            'source_sha256': RUN_SKYREELS.SOURCE_SHA256,
            'profile': 'smoke',
            'device': {'world_size': 1,
                       'compute_dtype': 'float16'},
            'generation': {'size': '960*544', 'fps': 24, 'frame_num': 49,
                           'inference_steps': 12, 'guidance_scale': 5.0,
                           'shift': 3.0},
            'acceleration': {'offload': True, 'attention_backend': 'torch_sdpa',
                             'teacache': False, 'teacache_thresh': 0.1,
                             'use_ret_steps': False},
            'monitoring': {'gpu_stats': True, 'gpu_stats_interval_sec': 30,
                           'step_timing': True, 'log_runtime_config': True},
        }
        RUN_SKYREELS.validate_backend(backend)
        with self.assertRaisesRegex(RuntimeError, 'model_revision'):
            RUN_SKYREELS.validate_backend({**backend, 'model_revision': 'main'})

    def test_job_cannot_override_profile_generation(self):
        job = {'id': 'S001', 'image': 'input/S001.png',
               'source_image_sha256': 'a' * 64, 'prompt': 'motion',
               'seed': 1, 'target_duration_sec': 10,
               'cache_key': 'b' * 64, 'output': 'output/S001.mp4',
               'frame_num': 257}
        with self.assertRaisesRegex(RuntimeError, 'performance parameters'):
            RUN_SKYREELS.validate_job(job)


if __name__ == '__main__':
    unittest.main()
