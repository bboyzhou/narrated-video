import json
from pathlib import Path
import tempfile
import unittest

from adapters import get_adapter, list_adapters
from adapters.base import UnsupportedFeatures


def plan():
    return {
        'kind': 'RenderPlan', 'version': 1,
        'source_project': {'kind': 'NarratedProject', 'version': 1, 'id': 'demo'},
        'stage': 'full', 'fps': 30, 'width': 1280, 'height': 720,
        'total_frames': 90, 'motion': {}, 'subtitles': {}, 'music': [],
        'shots': [{
            'id': 'S1', 'start_frame': 0, 'duration_frames': 90,
            'spoken_frames': 90, 'transition_frames': 0,
            'incoming_transition_frames': 0, 'type': 'image',
            'asset': 'D:/assets/one.png', 'source_start': 0, 'loop': False,
            'motion': 'push', 'layers': [], 'graphics': [], 'effects': {},
        }],
        'captions': [{
            'id': 'N1', 'shot': 'S1', 'text': 'hello',
            'start_frame': 0, 'end_frame': 90,
        }],
        'audio': {'N1': {'path': 'D:/assets/N1.wav', 'sha256': '0' * 64, 'frames': 90}},
    }


class AdapterTests(unittest.TestCase):
    def test_registry_has_three_explicit_adapters(self):
        self.assertEqual(set(list_adapters()), {'ffmpeg', 'remotion', 'openchatcut'})

    def test_ffmpeg_rejects_unrepresentable_graphics(self):
        value = plan()
        value['shots'][0]['graphics'] = [{'id': 'g'}]
        with self.assertRaises(UnsupportedFeatures):
            get_adapter('ffmpeg').require_lossless(value)

    def test_openchatcut_export_is_editable_and_reports_loss(self):
        value = plan()
        value['shots'][0]['effects'] = {'particles': 10}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'openchatcut.json'
            get_adapter('openchatcut').export(value, output)
            payload = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(payload['kind'], 'OpenChatCutImportPlan')
            self.assertEqual([track['kind'] for track in payload['tracks']],
                             ['video', 'audio', 'audio', 'captions'])
            self.assertFalse(payload['loss_report']['lossless'])
            self.assertEqual(payload['loss_report']['unsupported_features'], ['effects'])


if __name__ == '__main__':
    unittest.main()
