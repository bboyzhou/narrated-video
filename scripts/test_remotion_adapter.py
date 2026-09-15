import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from remotion_adapter import build_render_plan
from pipeline import Project


class RemotionPlanTest(unittest.TestCase):
    def test_plan_stages_assets_and_preserves_frame_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / 'shot.png'
            image.write_bytes(b'fixture-image')
            project = SimpleNamespace(
                work=root / '.narrated-video',
                output={'width': 320, 'height': 180},
                fps=30,
                c={'motion': {'max_zoom': 0.06}, 'subtitles': {'enabled': True}},
                runtime={'browser': 'C:/browser.exe'},
                path_for=lambda value: image,
            )
            voices = {'N1': {'frames': 30}, 'N2': {'frames': 45}}
            selected = [
                {'id': 'S1', 'type': 'image', 'asset': 'shot.png', 'narration': ['N1'], 'motion': 'push', 'transition': .2},
                {'id': 'S2', 'type': 'image', 'asset': 'shot.png', 'narration': ['N2'], 'motion': 'still', 'transition': 0},
            ]
            timeline = [{'id': 'N1', 'start_frame': 0, 'end_frame': 30}]
            plan = build_render_plan(project, 'demo', selected, voices, timeline)
            self.assertEqual(plan['total_frames'], 75)
            self.assertEqual(plan['shots'][1]['start_frame'], 30)
            self.assertEqual(plan['shots'][1]['incoming_transition_frames'], 6)
            staged = list((project.work / 'remotion-assets').iterdir())
            self.assertEqual(len(staged), 1)
            self.assertEqual(plan['browser_executable'], 'C:/browser.exe')

    def test_enhanced_features_cannot_silently_fallback(self):
        project = Project.__new__(Project)
        project.c = {'shots': [{'graphics': [{'id': 'formula'}]}],
                     'renderer': {'engine': 'remotion', 'fallback': 'ffmpeg'}}
        with self.assertRaises(ValueError):
            project.renderer_config()
        project.c['renderer']['fallback'] = 'none'
        self.assertEqual(project.renderer_config()['engine'], 'remotion')

    def test_renderer_config_participates_in_demo_fingerprint(self):
        project = Project.__new__(Project)
        project.c = {'narration': [], 'style': {}, 'voice': {}, 'subtitles': {}, 'demo': {},
                     'renderer': {'engine': 'ffmpeg', 'fallback': 'ffmpeg'}}
        project.output = {}; project.runtime = {}
        project.selected = lambda stage: []
        project.script_key = lambda: 'script'
        project.demo_storyboard_key = lambda: 'storyboard'
        before = project.demo_key()
        project.c['renderer']['fallback'] = 'none'
        self.assertNotEqual(before, project.demo_key())


if __name__ == '__main__':
    unittest.main()
