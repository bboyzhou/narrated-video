"""Unit tests for storyboard schema and approval invalidation without FFmpeg."""
import tempfile
import unittest
from pathlib import Path

from pipeline import Project, initialize, preflight_fingerprint, preflight_path, read_json, write_json
from test_pipeline import storyboard_for


class StoryboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project_path = self.root / 'project.json'
        initialize(self.project_path, None)
        config = read_json(self.project_path)
        config['voice'] = {'engine': 'files'}
        config['narration'] = [
            {'id': 'N1', 'text': '第一句。'},
            {'id': 'N2', 'text': '第二句。'},
            {'id': 'N3', 'text': '第三句。'},
        ]
        (self.root / 'approved-script.txt').write_text('第一句。第二句。第三句。', encoding='utf-8')
        config['shots'] = []
        for i, motion in enumerate(('push', 'pan-right', 'pull'), 1):
            config['shots'].append({'id': f'S{i}', 'type': 'image', 'asset': f'image-{i}.png',
                                    'narration': [f'N{i}'], 'motion': motion, 'transition': 0.2,
                                    'prompt': f'Test image {i}', 'negative_prompt': 'No text or watermark'})
        config['demo'] = {'shots': ['S1', 'S2']}
        write_json(self.root / 'storyboard.json', storyboard_for(config['shots']))
        write_json(self.project_path, config)
        write_json(preflight_path(self.project_path), {
            'ok': True,
            'fingerprint': preflight_fingerprint(self.project_path, config),
            'test_fixture': True,
        })

    def project(self):
        return Project(self.project_path)

    def test_storyboard_is_required_before_demo(self):
        project = self.project()
        project.record('script', 'TEST FIXTURE: approve script')
        with self.assertRaisesRegex(ValueError, 'Storyboard approval'):
            project.gate('demo')
        project.record('storyboard', 'TEST FIXTURE: approve storyboard')
        self.project().gate('demo')

    def test_preflight_is_required_before_script_approval(self):
        preflight_path(self.project_path).unlink()
        with self.assertRaisesRegex(ValueError, 'Preflight'):
            self.project().record('script', 'TEST FIXTURE: approve script')

    def test_voice_change_invalidates_preflight(self):
        config = read_json(self.project_path)
        config['voice'] = {'engine': 'files', 'revision': 'changed'}
        write_json(self.project_path, config)
        with self.assertRaisesRegex(ValueError, 'Preflight'):
            self.project().require_preflight()

    def test_script_can_be_approved_before_shots_exist(self):
        config = read_json(self.project_path)
        config['shots'] = []
        config['demo'] = {'shots': []}
        write_json(self.project_path, config)
        project = Project(self.project_path, validation_stage='script')
        project.record('script', 'TEST FIXTURE: approve script before storyboard')
        self.assertEqual(project.state['script']['fingerprint'], project.script_key())

    def test_non_demo_plan_change_preserves_demo_fingerprint(self):
        project = self.project()
        before = project.demo_key()
        storyboard = read_json(self.root / 'storyboard.json')
        storyboard['shots'][2]['purpose'] = '只调整非 Demo 镜头'
        write_json(self.root / 'storyboard.json', storyboard)
        self.assertEqual(before, self.project().demo_key())
        self.assertNotEqual(project.storyboard_key(), self.project().storyboard_key())

    def test_demo_plan_change_invalidates_demo_fingerprint(self):
        project = self.project()
        before = project.demo_key()
        storyboard = read_json(self.root / 'storyboard.json')
        storyboard['shots'][0]['purpose'] = '调整 Demo 镜头'
        write_json(self.root / 'storyboard.json', storyboard)
        self.assertNotEqual(before, self.project().demo_key())

    def test_prompt_must_match_project_execution(self):
        storyboard = read_json(self.root / 'storyboard.json')
        storyboard['shots'][0]['prompt'] = 'Different prompt'
        write_json(self.root / 'storyboard.json', storyboard)
        with self.assertRaisesRegex(ValueError, 'project prompt must match'):
            self.project()


if __name__ == '__main__':
    unittest.main()
