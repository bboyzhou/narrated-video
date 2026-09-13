"""Tests for the SVD-XT Kaggle entry-point preflight."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (Path(__file__).resolve().parents[1] / 'kaggle' / 'svd_xt' /
               'run_svd_job.py')
SPEC = importlib.util.spec_from_file_location('run_svd_job', MODULE_PATH)
RUN_SVD_JOB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_SVD_JOB)


class SvdKaggleEntryTests(unittest.TestCase):
    @staticmethod
    def backend():
        return {
            'engine': 'diffusers_svd',
            'model': 'stabilityai/stable-video-diffusion-img2vid-xt',
            'model_revision': 'dataset-v1',
            'profile': 'smoke',
            'device': {'world_size': 1,
                       'dtype': 'float16'},
            'generation': {
                'size': '1024*576', 'fps': 7, 'frame_num': 8,
                'inference_steps': 8, 'decode_chunk_size': 2,
                'motion_bucket_id': 80, 'noise_aug_strength': 0.02,
            },
            'acceleration': {
                'model_cpu_offload': True, 'forward_chunking': True,
                'vae_slicing': False,
            },
        }

    def test_backend_contract_accepts_pinned_svd_profile(self):
        RUN_SVD_JOB.validate_backend(self.backend())

    def test_backend_contract_rejects_unpinned_revision(self):
        backend = self.backend()
        backend['model_revision'] = 'main'
        with self.assertRaisesRegex(RuntimeError, 'pinned model_revision'):
            RUN_SVD_JOB.validate_backend(backend)

    def test_t4_is_accepted(self):
        RUN_SVD_JOB.validate_gpu([
            {'name': 'Tesla T4', 'memory_total_mib': 15360,
             'compute_capability': '7.5'}])

    def test_p100_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'E_GPU_UNSUPPORTED.*P100'):
            RUN_SVD_JOB.validate_gpu([
                {'name': 'Tesla P100-PCIE-16GB', 'memory_total_mib': 16384,
                 'compute_capability': '6.0'}])

    def test_package_name_strips_version_constraints(self):
        self.assertEqual(RUN_SVD_JOB.package_name('diffusers>=0.30,<0.36'),
                         'diffusers')
        self.assertEqual(RUN_SVD_JOB.package_name('imageio-ffmpeg>=0.5,<1'),
                         'imageio-ffmpeg')

    def test_manifest_discovery_accepts_only_svd_contract(self):
        original_input = RUN_SVD_JOB.INPUT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / 'datasets' / 'owner' / 'input' / 'versions' / '3'
            valid.mkdir(parents=True)
            (valid / 'video_jobs.json').write_text(json.dumps({
                'version': 3, 'provider': 'svd_xt', 'jobs': []
            }), encoding='utf-8')
            other = root / 'other'
            other.mkdir()
            (other / 'video_jobs.json').write_text(json.dumps({
                'version': 3, 'provider': 'wan22', 'jobs': []
            }), encoding='utf-8')
            try:
                RUN_SVD_JOB.INPUT = root
                found = RUN_SVD_JOB.fixed_file(
                    None, [root / 'legacy' / 'video_jobs.json'],
                    'video_jobs.json', discover=RUN_SVD_JOB.discover_manifest)
            finally:
                RUN_SVD_JOB.INPUT = original_input
        self.assertEqual(found.name, 'video_jobs.json')
        self.assertIn('versions', str(found))

    def test_model_discovery_validates_pipeline_contract(self):
        original_input = RUN_SVD_JOB.INPUT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / 'models' / 'owner' / 'svd' / 'versions' / '1'
            for relative in ('unet/config.json', 'vae/config.json',
                             'image_encoder/config.json',
                             'scheduler/scheduler_config.json',
                             'feature_extractor/preprocessor_config.json'):
                path = model / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}', encoding='utf-8')
            (model / 'model_index.json').write_text(json.dumps({
                '_class_name': 'StableVideoDiffusionPipeline'
            }), encoding='utf-8')
            try:
                RUN_SVD_JOB.INPUT = root
                found = RUN_SVD_JOB.fixed_model_path()
            finally:
                RUN_SVD_JOB.INPUT = original_input
        self.assertEqual(found, model.resolve())


if __name__ == '__main__':
    unittest.main()
