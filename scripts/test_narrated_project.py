import json
from pathlib import Path
import tempfile
import unittest

from narrated_project import (load_project, migrate_project, runtime_config_for,
                              save_runtime_config)
from pipeline import (Project, initialize_v1, preflight_fingerprint,
                      preflight_path, write_json)


def legacy_fixture(root):
    project = root / 'project.json'
    storyboard = root / 'storyboard.json'
    (root / 'approved-script.txt').write_text('第一句。第二句。', encoding='utf-8')
    project.write_text(json.dumps({
        'version': 1,
        'title': '迁移测试',
        'script': 'approved-script.txt',
        'storyboard': 'storyboard.json',
        'style': {'name': 'test', 'visual': 'simple', 'tone': 'calm'},
        'output': {'width': 1280, 'height': 720, 'fps': 30},
        'voice': {'engine': 'files'},
        'pacing': {},
        'subtitles': {'enabled': True, 'font': 'Arial', 'max_chars': 24},
        'motion': {'easing': 'smoothstep', 'max_zoom': 0.06},
        'renderer': {'engine': 'ffmpeg', 'fallback': 'ffmpeg'},
        'video_generation': {
            'enabled': False, 'provider': 'wan22', 'profile': 'balanced',
            'runtime': {'type': 'kaggle'}, 'policy': 'highlights', 'providers': {},
        },
        'narration': [
            {'id': 'N1', 'text': '第一句。'}, {'id': 'N2', 'text': '第二句。'},
        ],
        'shots': [
            {'id': 'S1', 'type': 'image', 'asset': 'one.png', 'narration': ['N1'],
             'motion': 'push', 'transition': 0.3, 'prompt': 'one', 'negative_prompt': 'bad'},
            {'id': 'S2', 'type': 'image', 'asset': 'two.png', 'narration': ['N2'],
             'motion': 'pull', 'transition': 0, 'prompt': 'two', 'negative_prompt': 'bad'},
        ],
        'demo': {'shots': ['S1'], 'start_seconds': 0},
        'music': [],
    }, ensure_ascii=False), encoding='utf-8')
    storyboard.write_text(json.dumps({
        'version': 1,
        'creative_brief': {
            'audience': 'general', 'platform': 'web', 'purpose': 'teach',
            'target_duration_seconds': 10, 'narrative_arc': 'two steps',
            'visual_style': 'simple', 'pacing': 'steady', 'voice_direction': 'calm',
            'music_direction': 'none', 'continuity_anchors': ['palette'], 'constraints': [],
        },
        'shots': [
            {'id': 'S1', 'narration': ['N1'], 'purpose': 'open',
             'estimated_duration_seconds': 5, 'visual': {
                 'subject': 'one', 'action': 'still', 'setting': 'room',
                 'shot_size': 'wide', 'composition': 'center', 'lighting_color': 'warm'},
             'continuity': ['palette'], 'asset_strategy': 'user', 'prompt': 'one',
             'negative_prompt': 'bad', 'motion': 'push', 'transition_seconds': 0.3},
            {'id': 'S2', 'narration': ['N2'], 'purpose': 'close',
             'estimated_duration_seconds': 5, 'visual': {
                 'subject': 'two', 'action': 'still', 'setting': 'room',
                 'shot_size': 'wide', 'composition': 'center', 'lighting_color': 'warm'},
             'continuity': ['palette'], 'asset_strategy': 'user', 'prompt': 'two',
             'negative_prompt': 'bad', 'motion': 'pull', 'transition_seconds': 0},
        ],
        'demo': {'shots': ['S1'], 'selection_reason': 'representative',
                 'validation_goals': ['timing']},
    }, ensure_ascii=False), encoding='utf-8')
    return project


class NarratedProjectTests(unittest.TestCase):
    def test_legacy_migration_is_non_destructive_and_semantically_equivalent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = legacy_fixture(root)
            original = source.read_bytes()
            output = root / 'narrated-project.json'
            migrate_project(source, output)
            self.assertEqual(source.read_bytes(), original)
            document = load_project(output, 'production')
            self.assertEqual(document.source_format, 'v1')
            self.assertEqual(document.data['kind'], 'NarratedProject')
            self.assertEqual([shot['id'] for shot in document.data['timeline']['shots']],
                             ['S1', 'S2'])
            self.assertEqual(document.legacy_view()['shots'][0]['transition'], 0.3)
            self.assertEqual(document.storyboard_view()['demo']['shots'], ['S1'])
            with self.assertRaises(ValueError):
                migrate_project(source, output)

    def test_v1_runtime_is_a_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = legacy_fixture(root)
            output = root / 'narrated-project.json'
            migrate_project(source, output)
            before = output.read_bytes()
            saved = save_runtime_config(output, {'ffmpeg': 'D:/tools/ffmpeg.exe'})
            self.assertEqual(saved, root / '.narrated-video' / 'runtime.json')
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(runtime_config_for(output)['ffmpeg'], 'D:/tools/ffmpeg.exe')

    def test_schema_documents_are_valid_json(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('narrated-project-v1.schema.json', 'render-plan-v1.schema.json'):
            value = json.loads((root / 'schemas' / name).read_text(encoding='utf-8'))
            self.assertEqual(value['$schema'], 'https://json-schema.org/draft/2020-12/schema')

    def test_new_initializer_writes_single_file_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'narrated-project.json'
            initialize_v1(project, None)
            value = json.loads(project.read_text(encoding='utf-8'))
            self.assertEqual(value['kind'], 'NarratedProject')
            self.assertNotIn('runtime', value)
            self.assertFalse((root / 'storyboard.json').exists())

    def test_pipeline_consumes_migrated_v1_through_compatibility_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = legacy_fixture(root)
            output = root / 'narrated-project.json'
            migrate_project(source, output)
            document = load_project(output)
            config = document.legacy_view()
            write_json(preflight_path(output), {
                'ok': True, 'fingerprint': preflight_fingerprint(output, config),
            })
            project = Project(output)
            self.assertEqual(project.document.source_format, 'v1')
            self.assertEqual(list(project.shots), ['S1', 'S2'])
            self.assertEqual(project.storyboard['creative_brief']['purpose'], 'teach')


if __name__ == '__main__':
    unittest.main()
