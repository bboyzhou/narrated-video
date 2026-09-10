"""Tests for provider-independent generated-video preparation and import."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline import initialize, read_json, write_json
from prepare_video_jobs import main as prepare_main
from import_generated_videos import main as import_main


class GeneratedVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storyboard = self.root / 'storyboard.json'
        self.project = self.root / 'project.json'
        self.image = self.root / 'source.png'
        self.image.write_bytes(b'not-an-image')
        self.storyboard.write_text(json.dumps({
            'version': 1,
            'shots': [{
                'id': 'S001', 'asset_strategy': 'generated_video', 'source_image': 'source.png',
                'motion_prompt': 'A gentle breeze moves the banner.',
                'motion_constraints': ['preserve identity'],
                'generation': {'provider': 'cogvideox_colab', 'mode': 'i2v', 'duration_target': 4, 'seed': 7}
            }, {'id': 'S002', 'asset_strategy': 'generate'}],
            'demo': {'shots': ['S001'], 'selection_reason': 'test', 'validation_goals': ['test']}
        }, ensure_ascii=False), encoding='utf-8')

    def test_prepare_filters_and_bundles(self):
        output, bundle = self.root / 'video_jobs.json', self.root / 'video_jobs.zip'
        old = os.sys.argv
        os.sys.argv = ['prepare_video_jobs.py', str(self.storyboard), '--output', str(output), '--bundle', str(bundle)]
        try:
            prepare_main()
        finally:
            os.sys.argv = old
        payload = read_json(output)
        self.assertEqual([job['id'] for job in payload['jobs']], ['S001'])
        self.assertEqual(payload['jobs'][0]['prompt'], 'A gentle breeze moves the banner.')
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn('video_jobs.json', archive.namelist())
            self.assertIn('input/S001.png', archive.namelist())

    def test_prepare_rejects_missing_source(self):
        data = json.loads(self.storyboard.read_text(encoding='utf-8'))
        data['shots'][0]['source_image'] = 'missing.png'
        self.storyboard.write_text(json.dumps(data), encoding='utf-8')
        old = os.sys.argv
        os.sys.argv = ['prepare_video_jobs.py', str(self.storyboard), '--output', str(self.root / 'jobs.json')]
        try:
            with self.assertRaises(ValueError):
                prepare_main()
        finally:
            os.sys.argv = old

    @unittest.skipUnless(shutil.which('ffprobe') and shutil.which('ffmpeg'), 'FFmpeg tools unavailable')
    def test_import_updates_only_matching_shots(self):
        initialize(self.project, None)
        project = read_json(self.project)
        project.update({'shots': [
            {'id': 'S001', 'type': 'image', 'asset': 'source.png', 'narration': ['N1'], 'motion': 'push', 'transition': .2,
             'prompt': 'x', 'negative_prompt': 'y'},
            {'id': 'S002', 'type': 'image', 'asset': 'other.png', 'narration': ['N2'], 'motion': 'push', 'transition': .2,
             'prompt': 'x', 'negative_prompt': 'y'}
        ]})
        write_json(self.project, project)
        results = self.root / 'output'; results.mkdir()
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                        '-i', 'color=c=blue:s=64x64:r=8', '-t', '1', '-an', results / 'S001.mp4'], check=True)
        jobs = self.root / 'video_jobs.json'
        write_json(jobs, {'version': 1, 'jobs': [{'id': 'S001'}]})
        old = os.sys.argv
        os.sys.argv = ['import_generated_videos.py', str(self.project), str(results), '--jobs', str(jobs)]
        try:
            import_main()
        finally:
            os.sys.argv = old
        updated = read_json(self.project)
        self.assertEqual(updated['shots'][0]['type'], 'video')
        self.assertEqual(updated['shots'][0]['motion'], 'still')
        self.assertEqual(updated['shots'][1]['type'], 'image')
        self.assertTrue((self.root / 'assets/generated-video/S001.mp4').is_file())


if __name__ == '__main__':
    unittest.main()
