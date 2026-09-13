"""Tests for generic I2V providers, planning, packaging and fallback."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from generators import build_video_job, get_video_generator, normalize_provider
from generators import PROVIDER_REGISTRY
from generators.router import fallback_result, route_shots, select_provider
from import_generated_videos import import_generated_videos
from planners import PROFILES
from prepare_video_jobs import prepare_video_jobs
from workers.i2v import format_runtime_plan, validate_worker_input
from runtime_planner import hardware_from_inventory, replan_manifest


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class GeneratedVideoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'source.png').write_bytes(b'not-a-real-png-but-packaging-only')
        self.plan = {
            'id': 'S001', 'asset_strategy': 'generated_video',
            'source_image': 'source.png',
            'motion_prompt': 'Cavalry advances through dust.',
            'negative_prompt': 'distortion',
            'motion_constraints': ['preserve identity', 'preserve composition'],
            'generation': {'provider': 'skyreels_v2', 'mode': 'i2v',
                           'seed': 7, 'target_duration_sec': 8,
                           'motion': {'strength': 'high', 'camera': 'tracking'}},
        }
        self.project = {
            'title': 'test',
            'video_generation': {
                'enabled': True, 'provider': 'skyreels_v2', 'profile': 'balanced',
                'runtime': {'type': 'kaggle', 'hardware': {
                    'gpus': [{'name': 'Tesla T4', 'vram_gib': 16,
                              'supports_fp16': True, 'supports_bf16': False}] }},
                'policy': 'highlights',
                'i2v_budget': {'enabled': True, 'max_shots': 3,
                               'max_generated_seconds_per_shot': 4},
                'providers': {},
            },
            'shots': [{'id': 'S001', 'type': 'image', 'asset': 'source.png'}],
            'demo': {'shots': ['S001']},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_profiles_are_hardware_neutral(self):
        self.assertEqual(set(PROFILES), {'smoke', 'fast', 'balanced', 'quality', 'max_quality'})
        serialized = json.dumps(PROFILES).lower()
        for token in ('t4', 'a100', 'fp16', 'bf16', 'frame_num', 'steps', 'offload'):
            self.assertNotIn(token, serialized)

    def test_legacy_combined_ids_only_select_runtime(self):
        self.assertEqual(normalize_provider('skyreels_v2_kaggle'),
                         ('skyreels_v2', {'type': 'kaggle'}))
        self.assertEqual(normalize_provider('cogvideox_colab'),
                         ('cogvideox', {'type': 'colab'}))

    def test_same_balanced_profile_plans_for_hardware(self):
        provider = get_video_generator('skyreels_v2')
        request = {'target_duration_sec': 8}
        t4 = provider.plan(request, 'balanced', {'type': 'kaggle'}, {
            'gpus': [{'name': 'Tesla T4', 'vram_gib': 16,
                      'supports_fp16': True, 'supports_bf16': False}]})
        a100 = provider.plan(request, 'balanced', {'type': 'runpod'}, {
            'gpus': [{'name': 'A100', 'vram_gib': 40,
                      'supports_fp16': True, 'supports_bf16': True}]})
        self.assertEqual(t4['profile'], a100['profile'])
        self.assertEqual(t4['execution']['dtype'], 'float16')
        self.assertTrue(t4['execution']['offload'])
        self.assertEqual(a100['execution']['dtype'], 'bfloat16')
        self.assertFalse(a100['execution']['offload'])

    def test_job_is_content_only_and_target_is_not_generated_duration(self):
        job, config, runtime_plan = build_video_job(
            self.plan, 'input/S001.png', 'a' * 64, self.project)
        self.assertEqual(job['target_duration_sec'], 8)
        self.assertAlmostEqual(runtime_plan['generated_duration_sec'], 97 / 24, places=3)
        self.assertEqual(runtime_plan['provider'], 'skyreels_v2')
        self.assertEqual(runtime_plan['runtime'], 'kaggle')
        self.assertIn('model', config)
        for field in ('provider', 'runtime', 'profile', 'frame_num', 'steps', 'dtype',
                      'offload', 'world_size', 'attention_backend', 'teacache'):
            self.assertNotIn(field, job)

    def test_job_rejects_execution_override(self):
        changed = {**self.plan, 'generation': {**self.plan['generation'], 'frame_num': 49}}
        with self.assertRaisesRegex(ValueError, 'planner-owned'):
            build_video_job(changed, 'input/S001.png', 'a' * 64, self.project)

    def test_provider_config_rejects_execution_override(self):
        project = json.loads(json.dumps(self.project))
        project['video_generation']['providers'] = {'skyreels_v2': {'dtype': 'float16'}}
        with self.assertRaisesRegex(ValueError, 'planner-owned'):
            build_video_job(self.plan, 'input/S001.png', 'a' * 64, project)

    def test_prepare_writes_runtime_plan_and_content_jobs(self):
        storyboard = self.root / 'storyboard.json'
        project = self.root / 'project.json'
        write_json(storyboard, {'version': 1, 'shots': [self.plan],
                                'demo': {'shots': ['S001']}})
        write_json(project, self.project)
        output, bundle = self.root / 'jobs.json', self.root / 'jobs.zip'
        result = prepare_video_jobs(storyboard, project, 'demo', output, bundle)
        payload = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['provider'], 'skyreels_v2')
        self.assertEqual(payload['runtime'], {'type': 'kaggle'})
        self.assertEqual(payload['profile'], 'balanced')
        self.assertIn('runtime_plan', payload)
        self.assertNotIn('backend', payload)
        validate_worker_input(payload)
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn('video_jobs.json', archive.namelist())
            self.assertIn('input/S001.png', archive.namelist())
            self.assertIn('runtime_support/runtime_planner.py', archive.namelist())

    def test_runtime_launcher_can_replan_without_changing_jobs(self):
        job, config, plan = build_video_job(
            self.plan, 'input/S001.png', 'a' * 64, self.project)
        manifest = {'version': 3, 'provider': 'skyreels_v2', 'profile': 'balanced',
                    'runtime': {'type': 'kaggle'}, 'provider_config': config,
                    'runtime_plan': plan, 'jobs': [job]}
        hardware = hardware_from_inventory([{
            'name': 'A100', 'memory_total_mib': 40960, 'compute_capability': '8.0'}])
        replanned = replan_manifest(manifest, hardware)
        self.assertEqual(replanned['jobs'], manifest['jobs'])
        self.assertEqual(replanned['runtime_plan']['hardware_basis'], 'detected')
        self.assertEqual(replanned['runtime_plan']['execution']['dtype'], 'bfloat16')

    def test_runtime_plan_log_is_auditable(self):
        _, _, plan = build_video_job(self.plan, 'input/S001.png', 'a' * 64, self.project)
        output = format_runtime_plan(plan, target_seconds=8)
        for value in ('skyreels_v2', 'balanced', 'kaggle', 'Tesla T4',
                      'float16', 'generated seconds', 'target seconds'):
            self.assertIn(value, output)

    def test_worker_rejects_model_parameters_in_job(self):
        job, config, plan = build_video_job(self.plan, 'input/S001.png', 'a' * 64, self.project)
        job['inference_steps'] = 1
        manifest = {'version': 3, 'provider': 'skyreels_v2', 'profile': 'balanced',
                    'runtime': {'type': 'kaggle'}, 'provider_config': config,
                    'runtime_plan': plan, 'jobs': [job]}
        with self.assertRaisesRegex(ValueError, 'planner-owned'):
            validate_worker_input(manifest)

    def test_hero_router_enforces_budget(self):
        shots = [{'id': 'A', 'motion_mode': 'i2v'}, {'id': 'B'},
                 {'id': 'C', 'asset_strategy': 'generated_video'}]
        routed = route_shots(shots, {'enabled': True,
                                     'i2v_budget': {'enabled': True, 'max_shots': 1}})
        self.assertEqual([row['id'] for row in routed['i2v']], ['A'])
        self.assertEqual([row['id'] for row in routed['motion']], ['B', 'C'])

    def test_failure_becomes_remotion_fallback(self):
        result = fallback_result('skyreels_v2', 'timeout', 'images/S001.png')
        self.assertEqual(result['actual_provider'], 'remotion_motion')
        self.assertEqual(result['status'], 'fallback')
        self.assertEqual(result['reason'], 'E_I2V_TIMEOUT')

    def test_failed_import_records_fallback_without_mutating_shot(self):
        project_path = self.root / 'project.json'
        write_json(project_path, self.project)
        job, config, runtime_plan = build_video_job(
            self.plan, 'input/S001.png', 'a' * 64, self.project)
        jobs_path = self.root / 'video_jobs.json'
        write_json(jobs_path, {
            'version': 3, 'project_id': 'test', 'provider': 'skyreels_v2',
            'profile': 'balanced', 'runtime': {'type': 'kaggle'},
            'mode': 'i2v', 'stage': 'demo', 'provider_config': config,
            'runtime_plan': runtime_plan, 'jobs': [job], 'cache_hits': [],
        })
        results = self.root / 'results'
        results.mkdir()
        write_json(results / 'results.json', {'results': [{
            'id': 'S001', 'status': 'failed', 'code': 'E_I2V_TIMEOUT',
            'error': 'timed out',
        }]})
        outcome = import_generated_videos(project_path, results, jobs_path)
        self.assertEqual(outcome['failed'][0]['actual_provider'], 'remotion_motion')
        self.assertEqual(outcome['failed'][0]['reason'], 'E_I2V_TIMEOUT')
        self.assertNotIn('generated_video',
                         json.loads(project_path.read_text(encoding='utf-8'))['shots'][0])

    def test_provider_selection_is_separate_from_runtime(self):
        self.assertEqual(select_provider('skyreels_v2', ['skyreels_v2', 'cogvideox'],
                                         PROVIDER_REGISTRY, 'kaggle'), 'skyreels_v2')
        self.assertEqual(select_provider('skyreels_v2', ['skyreels_v2'],
                                         PROVIDER_REGISTRY, 'cloud_api'),
                         'remotion_motion')

    def test_wan_and_cogvideox_share_job_contract(self):
        for provider in ('wan22', 'cogvideox', 'svd_xt'):
            project = json.loads(json.dumps(self.project))
            project['video_generation']['provider'] = provider
            project['video_generation']['providers'] = {
                provider: {'model_revision': 'pinned-test-revision'}}
            plan = json.loads(json.dumps(self.plan))
            plan['generation']['provider'] = provider
            job, _, runtime_plan = build_video_job(
                plan, 'input/S001.png', 'a' * 64, project)
            self.assertEqual(set(job), set(build_video_job(
                self.plan, 'input/S001.png', 'a' * 64, self.project)[0]))
            self.assertEqual(runtime_plan['provider'], provider)

    def test_cloud_provider_uses_same_job_contract(self):
        project = json.loads(json.dumps(self.project))
        project['video_generation'].update({'provider': 'cloud_i2v',
                                            'runtime': {'type': 'cloud_api'}})
        project['video_generation']['providers'] = {
            'cloud_i2v': {'model': 'vendor/model', 'model_revision': 'api-v1'}}
        plan = json.loads(json.dumps(self.plan))
        plan['generation']['provider'] = 'cloud_i2v'
        job, _, runtime_plan = build_video_job(
            plan, 'input/S001.png', 'a' * 64, project)
        self.assertNotIn('service_quality', job)
        self.assertEqual(runtime_plan['runtime'], 'cloud_api')
        self.assertEqual(runtime_plan['execution']['dtype'], 'managed')


if __name__ == '__main__':
    unittest.main()
