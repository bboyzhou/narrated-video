"""Tests for the Kaggle Wan entry-point preflight."""
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / 'kaggle' / 'run_wan_job.py'
SPEC = importlib.util.spec_from_file_location('run_wan_job', MODULE_PATH)
RUN_WAN_JOB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_WAN_JOB)

WORKER_PATH = Path(__file__).resolve().parents[1] / 'kaggle' / 'wan_worker.py'
WORKER_SPEC = importlib.util.spec_from_file_location('wan_worker', WORKER_PATH)
WAN_WORKER = importlib.util.module_from_spec(WORKER_SPEC)
WORKER_SPEC.loader.exec_module(WAN_WORKER)


class KaggleEntryTests(unittest.TestCase):
    @staticmethod
    def backend():
        return {
            'engine': 'wan_native', 'model': 'Wan-AI/Wan2.2-TI2V-5B',
            'model_revision': 'dataset-v1', 'task': 'ti2v-5B',
            'profile': 'smoke',
            'device': {'world_size': 1},
            'generation': {
                'size': '1280*704', 'fps': 24, 'frame_num': 5,
                'sample_steps': 8, 'sample_shift': 5.0,
                'sample_solver': 'unipc', 'sample_guide_scale': 5.0,
            },
            'acceleration': {
                'dit_fsdp': False, 't5_fsdp': False, 't5_cpu': True,
                'convert_model_dtype': True, 'offload_model': True,
                'ulysses_size': 1,
            },
        }

    def test_worker_accepts_runtime_plan(self):
        generation, _, acceleration = WAN_WORKER.validate_backend(self.backend())
        self.assertEqual(generation['frame_num'], 5)
        self.assertTrue(acceleration['offload_model'])

    def test_worker_rejects_invalid_runtime_plan(self):
        backend = self.backend()
        backend['generation']['fps'] = 25
        with self.assertRaisesRegex(RuntimeError, 'RuntimePlan output is invalid'):
            WAN_WORKER.validate_backend(backend)

    def test_runtime_plan_accepts_sufficient_vram(self):
        RUN_WAN_JOB.validate_gpu(
            {'execution': {'frame_num': 49}},
            [{'name': 'NVIDIA L4', 'memory_total_mib': 23034,
              'compute_capability': '8.9'}])

    def test_runtime_plan_rejects_insufficient_vram_before_model_load(self):
        with self.assertRaisesRegex(RuntimeError, 'E_GPU_UNSUPPORTED.*22 GiB'):
            RUN_WAN_JOB.validate_gpu(
                {'execution': {'frame_num': 49}},
                [{'name': 'Tesla P100-PCIE-16GB', 'memory_total_mib': 16280,
                  'compute_capability': '6.0'}])

    def test_gpu_error_has_specific_classification(self):
        error = RuntimeError('E_GPU_UNSUPPORTED: wrong accelerator')
        self.assertEqual(RUN_WAN_JOB.classify(error), 'E_GPU_UNSUPPORTED')


if __name__ == '__main__':
    unittest.main()
