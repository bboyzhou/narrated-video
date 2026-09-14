import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from remotion_adapter import build_render_plan


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
            staged = list((project.work / 'remotion-assets').iterdir())
            self.assertEqual(len(staged), 1)
            self.assertEqual(plan['browser_executable'], 'C:/browser.exe')


if __name__ == '__main__':
    unittest.main()
