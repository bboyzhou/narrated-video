"""Deterministic tests for browser I2V planning, recovery and attachment."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browser_i2v import (next_action, observe_action, plan_tasks, status_report,
                         sync_downloads)


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class FakeProject:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'project.json'
        self.c = {
            'video_generation': {
                'enabled': True, 'provider': 'browser_i2v', 'profile': 'balanced',
                'runtime': {'type': 'browser'}, 'policy': 'selected',
                'providers': {'browser_i2v': {
                    'platforms': ['pixverse', 'jimeng'], 'free_only': True,
                    'quota_max_age_seconds': 600, 'query_interval_seconds': 30,
                    'max_attempts': 2,
                }},
            },
        }
        self.storyboard_shots = {'S001': {
            'id': 'S001', 'asset_strategy': 'generated_video',
            'source_image': 'source.png', 'motion_prompt': 'The rider advances slowly.',
            'negative_prompt': 'distortion', 'motion_constraints': ['preserve identity'],
            'generation': {'provider': 'browser_i2v', 'target_duration_sec': 5,
                           'seed': 7, 'aspect_ratio': '16:9'},
        }}
        self.shot = {'id': 'S001'}

    def selected(self, stage):
        return [self.shot]


class BrowserI2VTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'source.png').write_bytes(b'fixture-image')
        self.project = FakeProject(self.root)
        self._write_legacy_project()

    def tearDown(self):
        self.temp.cleanup()

    def _write_legacy_project(self):
        write_json(self.root / 'storyboard.json', {
            'version': 1, 'creative_brief': {},
            'shots': [self.project.storyboard_shots['S001']],
            'demo': {'shots': ['S001']},
        })
        write_json(self.project.path, {
            'version': 1, 'title': 'browser test',
            'storyboard': 'storyboard.json',
            'video_generation': self.project.c['video_generation'],
            'shots': [{'id': 'S001', 'type': 'image', 'asset': 'source.png',
                       'narration': ['N1'], 'motion': 'push', 'transition': .2,
                       'prompt': 'rider', 'negative_prompt': 'distortion'}],
            'narration': [{'id': 'N1', 'text': 'test'}], 'demo': {'shots': ['S001']},
        })

    def observe(self, action, **values):
        path = self.root / 'observation.json'
        write_json(path, {'action_id': action['id'], 'platform': action['platform'], **values})
        return observe_action(self.project.path, path)

    def test_plan_is_idempotent_and_persists_source_digest(self):
        first = plan_tasks(self.project, 'demo')
        second = plan_tasks(self.project, 'demo')
        self.assertEqual(len(first['created']), 1)
        self.assertEqual(second['reused'], first['created'])
        state = json.loads(Path(first['state_file']).read_text(encoding='utf-8'))
        task = state['tasks'][first['created'][0]]
        self.assertEqual(len(task['request']['source_sha256']), 64)
        self.assertTrue(task['request']['routing']['free_only'])

    def test_free_inspection_submission_and_unknown_recovery_do_not_resubmit(self):
        plan_tasks(self.project, 'demo')
        inspect = next_action(self.project.path)
        self.assertEqual(inspect['kind'], 'inspect')
        self.observe(inspect, outcome='available', logged_in=True, free_eligible=True,
                     cost_confirmed_zero=True, model='Visible model')
        submit = next_action(self.project.path)
        self.assertEqual(submit['kind'], 'submit')
        self.observe(submit, outcome='unknown', model='Visible model')
        recovery = next_action(self.project.path)
        self.assertEqual(recovery['kind'], 'query_history')
        self.assertEqual(next_action(self.project.path)['id'], recovery['id'])
        self.observe(recovery, outcome='queued', remote_task_id='remote-1',
                     retry_after_seconds=0)
        query = next_action(self.project.path)
        self.assertEqual(query['kind'], 'query')
        self.assertEqual(query['remote']['remote_task_id'], 'remote-1')

    def test_unavailable_platform_routes_to_next_allowed_platform(self):
        plan_tasks(self.project, 'demo')
        first = next_action(self.project.path)
        self.assertEqual(first['platform'], 'pixverse')
        self.observe(first, outcome='quota_exhausted')
        second = next_action(self.project.path)
        self.assertEqual(second['kind'], 'inspect')
        self.assertEqual(second['platform'], 'jimeng')
        status = status_report(self.project.path)
        self.assertIsNone(status['tasks'][0]['blocked_reason'])

    def test_download_is_validated_and_attached_without_runtime_plan(self):
        planned = plan_tasks(self.project, 'demo')['created'][0]
        state_path = self.root / '.narrated-video' / 'i2v' / 'tasks.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        task = state['tasks'][planned]
        video = self.root / 'download.mp4';video.write_bytes(b'fake-video')
        task.update({'state': 'DOWNLOADED', 'platform': 'pixverse',
                     'download': str(video), 'attempts': [{'model': 'Visible model'}]})
        write_json(state_path, state)
        with patch('browser_i2v.manager.probe', return_value={
                'width': 1280, 'height': 720, 'duration': 5.0, 'codec': 'h264'}), \
             patch('browser_i2v.manager.validate_decodable_video'):
            report = sync_downloads(self.project.path, ffmpeg='fixture-ffmpeg')
        self.assertEqual(report['imported'][0]['runtime'], 'browser')
        self.assertNotIn('runtime_plan_digest', report['imported'][0])
        project = json.loads(self.project.path.read_text(encoding='utf-8'))
        generated = project['shots'][0]['generated_video']
        self.assertEqual(generated['platform'], 'pixverse')
        self.assertTrue((self.root / generated['asset']).is_file())

    def test_sync_rejects_a_result_after_the_current_request_changes(self):
        planned = plan_tasks(self.project, 'demo')['created'][0]
        state_path = self.root / '.narrated-video' / 'i2v' / 'tasks.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        video = self.root / 'download.mp4'
        video.write_bytes(b'fake-video')
        state['tasks'][planned].update({
            'state': 'DOWNLOADED', 'platform': 'pixverse',
            'download': str(video), 'attempts': [{'model': 'Visible model'}],
        })
        write_json(state_path, state)
        storyboard_path = self.root / 'storyboard.json'
        storyboard = json.loads(storyboard_path.read_text(encoding='utf-8'))
        storyboard['shots'][0]['motion_prompt'] = 'A different approved request.'
        write_json(storyboard_path, storyboard)
        report = sync_downloads(self.project.path, ffmpeg='fixture-ffmpeg')
        self.assertEqual(report['imported'], [])
        self.assertIn('request changed', report['failed'][0]['error'])

    def test_ready_task_stops_at_the_configured_attempt_limit(self):
        planned = plan_tasks(self.project, 'demo')['created'][0]
        inspect = next_action(self.project.path)
        self.observe(inspect, outcome='available', logged_in=True, free_eligible=True,
                     cost_confirmed_zero=True)
        state_path = self.root / '.narrated-video' / 'i2v' / 'tasks.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['tasks'][planned]['attempts'] = [{}, {}]
        write_json(state_path, state)
        self.assertEqual(next_action(self.project.path)['kind'], 'none')
        status = status_report(self.project.path)
        self.assertEqual(status['tasks'][0]['blocked_reason'], 'MAX_ATTEMPTS_REACHED')


if __name__ == '__main__':
    unittest.main()
