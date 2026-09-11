"""Tests for provider-independent generated-video preparation and import."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from generators import build_video_job, file_sha256
from import_generated_videos import import_generated_videos
from pipeline import (Project, initialize, preflight_fingerprint, preflight_path,
                      read_json, write_json)
from prepare_video_jobs import prepare_video_jobs


class GeneratedVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storyboard = self.root / 'storyboard.json'
        self.project = self.root / 'project.json'
        self.image = self.root / 'source.png'
        self.image.write_bytes(b'not-an-image')
        self.plan = {
            'id': 'S001', 'asset_strategy': 'generated_video',
            'source_image': 'source.png',
            'motion_prompt': 'A gentle breeze moves the banner.',
            'motion_constraints': ['preserve identity'],
            'generation': {'provider': 'cogvideox_colab', 'mode': 'i2v',
                           'duration_target': 4, 'seed': 7}
        }
        self.storyboard.write_text(json.dumps({
            'version': 1,
            'shots': [self.plan, {'id': 'S002', 'asset_strategy': 'generate'}],
            'demo': {'shots': ['S001'], 'selection_reason': 'test',
                     'validation_goals': ['test']}
        }, ensure_ascii=False), encoding='utf-8')

    def test_prepare_filters_and_bundles(self):
        output, bundle = self.root / 'video_jobs.json', self.root / 'video_jobs.zip'
        result = prepare_video_jobs(self.storyboard, output=output, bundle=bundle)
        payload = read_json(output)
        self.assertEqual(result['jobs'], 1)
        self.assertEqual(payload['version'], 2)
        self.assertEqual([job['id'] for job in payload['jobs']], ['S001'])
        self.assertEqual(payload['jobs'][0]['prompt'], 'A gentle breeze moves the banner.')
        self.assertRegex(payload['jobs'][0]['cache_key'], r'^[0-9a-f]{64}$')
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn('video_jobs.json', archive.namelist())
            self.assertIn('input/S001.png', archive.namelist())

    def test_prepare_rejects_missing_source(self):
        data = json.loads(self.storyboard.read_text(encoding='utf-8'))
        data['shots'][0]['source_image'] = 'missing.png'
        self.storyboard.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            prepare_video_jobs(self.storyboard, output=self.root / 'jobs.json')

    def test_wan_cache_key_covers_model_prompt_seed_and_image(self):
        project = {'video_generation': {'enabled': True, 'provider': 'wan22_kaggle',
                   'providers': {'wan22_kaggle': {'model_revision': 'dataset-v1'}}}}
        plan = {**self.plan, 'generation': {**self.plan['generation'],
                                           'provider': 'wan22_kaggle'}}
        first, _ = build_video_job(plan, 'input/S001.png', 'a' * 64, project)
        changed_prompt, _ = build_video_job(
            {**plan, 'motion_prompt': 'Dust drifts.'}, 'input/S001.png', 'a' * 64, project)
        changed_image, _ = build_video_job(plan, 'input/S001.png', 'b' * 64, project)
        changed_model, _ = build_video_job(
            plan, 'input/S001.png', 'a' * 64,
            {'video_generation': {'enabled': True, 'provider': 'wan22_kaggle',
             'providers': {'wan22_kaggle': {'model_revision': 'dataset-v2'}}}})
        self.assertEqual(first['frame_num'] % 4, 1)
        self.assertEqual(len({first['cache_key'], changed_prompt['cache_key'],
                              changed_image['cache_key'], changed_model['cache_key']}), 4)

    def _ffmpeg(self):
        return os.environ.get('FFMPEG') or shutil.which('ffmpeg')

    @unittest.skipUnless(os.environ.get('FFMPEG') or shutil.which('ffmpeg'),
                         'FFmpeg unavailable')
    def test_import_preserves_fallback_and_registers_cache(self):
        self.storyboard.unlink()
        initialize(self.project, None)
        project = read_json(self.project)
        project.update({'video_generation': {'enabled': True, 'provider': 'cogvideox_colab'},
                        'shots': [
            {'id': 'S001', 'type': 'image', 'asset': 'source.png',
             'narration': ['N1'], 'motion': 'push', 'transition': .2,
             'prompt': 'x', 'negative_prompt': 'y'},
            {'id': 'S002', 'type': 'image', 'asset': 'other.png',
             'narration': ['N2'], 'motion': 'push', 'transition': .2,
             'prompt': 'x', 'negative_prompt': 'y'}
        ], 'demo': {'shots': ['S001']}})
        write_json(self.project, project)
        results = self.root / 'output'
        results.mkdir()
        subprocess.run([self._ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=8', '-t', '1',
                        '-an', results / 'S001.mp4'], check=True)
        cache_key = build_video_job(self.plan, 'input/S001.png',
                                    file_sha256(self.image), project)[0]['cache_key']
        write_json(self.storyboard, {'version': 1, 'shots': [self.plan],
                                    'demo': {'shots': ['S001']}})
        jobs = self.root / 'video_jobs.json'
        write_json(jobs, {'version': 1, 'provider': 'cogvideox_colab',
                          'jobs': [{'id': 'S001', 'output': 'S001.mp4'}]})
        outcome = import_generated_videos(self.project, results, jobs,
                                          ffmpeg=self._ffmpeg())
        updated = read_json(self.project)
        self.assertEqual(len(outcome['imported']), 1)
        self.assertEqual(updated['shots'][0]['type'], 'image')
        self.assertEqual(updated['shots'][0]['asset'], 'source.png')
        generated = updated['shots'][0]['generated_video']
        self.assertEqual(generated['cache_key'], cache_key)
        self.assertTrue((self.root / generated['asset']).is_file())
        index = read_json(self.root / '.narrated-video/generated-video-index.json')
        self.assertEqual(index['entries'][cache_key]['sha256'],
                         file_sha256(self.root / generated['asset']))
        prepared = prepare_video_jobs(self.storyboard, self.project, 'demo',
                                      self.root / 'second-jobs.json')
        self.assertEqual(prepared['jobs'], 0)
        self.assertEqual(prepared['cache_hits'], 1)

    @unittest.skipUnless(os.environ.get('FFMPEG') or shutil.which('ffmpeg'),
                         'FFmpeg unavailable')
    def test_failed_job_keeps_fallback(self):
        self.storyboard.unlink()
        initialize(self.project, None)
        project = read_json(self.project)
        project['shots'] = [{'id': 'S001', 'type': 'image', 'asset': 'source.png',
                             'narration': ['N1'], 'motion': 'push', 'transition': .2,
                             'prompt': 'x', 'negative_prompt': 'y'}]
        write_json(self.project, project)
        results = self.root / 'empty-results'
        results.mkdir()
        write_json(results / 'results.json', {'results': [
            {'id': 'S001', 'status': 'failed', 'error': 'CUDA out of memory'}]})
        jobs = self.root / 'video_jobs.json'
        write_json(jobs, {'version': 2, 'provider': 'wan22_kaggle', 'backend': {},
                          'jobs': [{'id': 'S001', 'cache_key': 'b' * 64,
                                    'output': 'output/S001.mp4'}]})
        result = import_generated_videos(self.project, results, jobs,
                                         ffmpeg=self._ffmpeg())
        self.assertEqual(result['failed'][0]['id'], 'S001')
        self.assertNotIn('generated_video', read_json(self.project)['shots'][0])


if __name__ == '__main__':
    unittest.main()
