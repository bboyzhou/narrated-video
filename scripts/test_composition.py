"""Unit and optional real-FFmpeg integration tests. Set FFMPEG to enable media tests."""
import copy
import contextlib
import io
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

from composition import catalog, resolve_asset, validate_layers, render_args
from pipeline import (Project, initialize, read_json, write_json, preflight_path,
                      preflight_fingerprint)
from test_pipeline import storyboard_for, tone


def png(path, width, height, pixel):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + b''.join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def layer():
    return {'id': 'actor', 'type': 'image', 'asset': 'actor.png', 'start': .2, 'end': 1.8,
            'width': .3, 'height': .3, 'easing': 'linear',
            'keyframes': [{'time': 0, 'x': .2, 'y': .5, 'scale': 1, 'rotation': 0, 'opacity': 0},
                          {'time': .4, 'x': .35, 'y': .5, 'scale': 1.2, 'rotation': 25, 'opacity': 1},
                          {'time': 1.6, 'x': .8, 'y': .5, 'scale': .7, 'rotation': 90, 'opacity': 1}]}


class CompositionTests(unittest.TestCase):
    def test_validation(self):
        shot = {'type': 'image', 'asset': 'base.png', 'layers': [layer()]}
        validate_layers(shot, 2)
        for key, bad in (('opacity', 2), ('scale', float('nan')), ('rotation', '2')):
            broken = copy.deepcopy(shot)
            broken['layers'][0]['keyframes'][0][key] = bad
            with self.assertRaises(ValueError):
                validate_layers(broken)
        with self.assertRaisesRegex(ValueError, 'duration'):
            validate_layers(shot, 1)
        shot['layers'][0]['keyframes'][1]['time'] = 0
        with self.assertRaisesRegex(ValueError, 'strictly'):
            validate_layers(shot)

    def test_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = {'id': 'smoke', 'type': 'video', 'path': 'smoke.mp4', 'source': 'test', 'license': 'test'}
            write_json(root / 'index.json', {'version': 1, 'assets': [entry]})
            resolved, meta = resolve_asset(root, {'asset_library': 'index.json'}, 'library:smoke')
            self.assertEqual(resolved, root / 'smoke.mp4')
            self.assertEqual(meta['license'], 'test')
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                resolve_asset(root, {'asset_library': 'index.json'}, 'library:missing')
            entry['path'] = '../escape.mp4'
            write_json(root / 'index.json', {'version': 1, 'assets': [entry]})
            with self.assertRaisesRegex(ValueError, 'inside'):
                catalog(root / 'index.json')


@unittest.skipUnless(os.environ.get('FFMPEG'), 'Set FFMPEG for real media integration')
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ffmpeg = os.environ['FFMPEG']
        png(self.root / 'base.png', 160, 96, lambda x, y: (10, 30, 80, 255))
        png(self.root / 'actor.png', 32, 32,
            lambda x, y: (255, 0, 0, 255 if 8 <= x < 24 and 3 <= y < 29 else 0))
        self.ff(['-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=10', '-f', 'lavfi',
                 '-i', 'sine=frequency=900', '-t', .5, '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-c:a', 'aac', self.root / 'video.mp4'])

    def ff(self, args):
        return subprocess.run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                               *map(str, args)], check=True, capture_output=True).stdout

    def pixels(self, path):
        data = self.ff(['-i', path, '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        stride = 160 * 96 * 3
        self.assertEqual(len(data), stride * 20)
        return [data[i:i+stride] for i in range(0, len(data), stride)]

    def test_alpha_keyframes_and_video_end(self):
        shot = {'type': 'image', 'asset': 'base.png', 'layers': [layer()]}
        output = self.root / 'layers.mp4'
        self.ff(render_args(shot, lambda p: self.root / p, 160, 96, 10, 20, 'null') + [output])
        frames = self.pixels(output)
        def red_center(frame):
            positions = [i // 3 % 160 for i in range(0, len(frame), 3)
                         if frame[i] > 150 and frame[i+1] < 70 and frame[i+2] < 70]
            return sum(positions) / len(positions) if positions else None
        self.assertIsNone(red_center(frames[0]))
        self.assertIsNone(red_center(frames[2]))
        self.assertIsNone(red_center(frames[18]))
        self.assertLess(red_center(frames[7]), red_center(frames[15]))
        # Transparent padding must leave the background visible.
        self.assertLess(frames[10][0], 20)
        png(self.root / 'green.png', 16, 16, lambda x, y: (0, 255, 0, 255))
        top = layer()
        top.update(id='top', asset='green.png', width=.1, height=.1)
        for key in top['keyframes']:
            key.update(x=.5, y=.5, scale=1, rotation=0, opacity=1)
        shot['layers'].append(top)
        self.ff(render_args(shot, lambda p: self.root / p, 160, 96, 10, 20, 'null') + [output])
        center = (48 * 160 + 80) * 3
        self.assertGreater(self.pixels(output)[10][center+1], 200)
        for looping in (False, True):
            shot = {'type': 'video', 'asset': 'video.mp4', 'loop': looping, 'source_start': .1}
            self.ff(render_args(shot, lambda p: self.root / p, 160, 96, 10, 20, 'null') + [output])
            frames = self.pixels(output)
            delta = sum(abs(a-b) for a, b in zip(frames[10], frames[15])) / len(frames[10])
            if looping:
                # Compare distinct source phases (five-frame source loops).
                self.assertNotEqual(frames[10], frames[12])
            else:
                self.assertLess(delta, 1)

    def test_pipeline_cache_approvals_manifest(self):
        project_file = self.root / 'project.json'
        with contextlib.redirect_stdout(io.StringIO()):
            initialize(project_file, None)
        c = read_json(project_file)
        c.update(output={'width': 160, 'height': 96, 'fps': 10}, voice={'engine': 'files'}, music=[])
        c['subtitles']['enabled'] = False
        c['narration'] = [{'id': f'N{i}', 'text': '测试。', 'audio': f'{i}.wav'} for i in range(1, 4)]
        (self.root / 'approved-script.txt').write_text('测试。' * 3, encoding='utf-8')
        c['shots'] = [{'id': f'S{i}', 'type': 'video' if i == 2 else 'image',
                       'asset': 'video.mp4' if i == 2 else 'base.png', 'motion': 'still',
                       'transition': .2, 'prompt': 'Test', 'negative_prompt': 'None',
                       'narration': [f'N{i}']} for i in range(1, 4)]
        c['shots'][0]['layers'] = [layer()]
        c['asset_library'] = 'index.json'
        write_json(self.root / 'index.json', {'version': 1, 'assets': [
            {'id': 'actor', 'type': 'image', 'path': 'actor.png', 'source': 'Generated test', 'license': 'Test'}]})
        c['shots'][0]['layers'][0]['asset'] = 'library:actor'
        c['shots'][1]['loop'] = True
        video_layer = layer()
        video_layer.update(type='video', asset='video.mp4', loop=True, source_start=.1)
        c['shots'][2]['layers'] = [video_layer]
        c['demo'] = {'shots': ['S1', 'S2']}
        for i in range(1, 4):
            tone(self.root / f'{i}.wav', 2, 220)
        board = storyboard_for(c['shots'])
        for plan, shot in zip(board['shots'], c['shots']):
            plan.update({k: shot[k] for k in ('type', 'layers', 'loop') if k in shot})
        write_json(self.root / 'storyboard.json', board)
        write_json(project_file, c)
        write_json(preflight_path(project_file), {'ok': True, 'test_fixture': True,
                    'fingerprint': preflight_fingerprint(project_file, c, self.ffmpeg)})
        p = Project(project_file, self.ffmpeg)
        p.record('script', 'TEST ONLY')
        p.record('storyboard', 'TEST ONLY')
        with contextlib.redirect_stdout(io.StringIO()):
            p.render('demo')
            p.record('demo', 'TEST ONLY')
            p.render('full')
            q = Project(project_file, self.ffmpeg)
            q.render('full')
        self.assertEqual(q.stats['rendered'], 0)
        manifest = read_json(self.root / 'deliverables/full-manifest.json')
        self.assertEqual(len(manifest['layers']), 2)
        self.assertTrue(all(m['sha256'] for m in manifest['layers']))
        # A changed layer in a non-Demo shot leaves Demo approval intact.
        before = q.demo_key()
        c['shots'][2]['layers'][0]['keyframes'][0]['x'] = .1
        board['shots'][2]['layers'] = c['shots'][2]['layers']
        write_json(project_file, c)
        write_json(self.root / 'storyboard.json', board)
        q = Project(project_file, self.ffmpeg)
        self.assertEqual(before, q.demo_key())
        with self.assertRaisesRegex(ValueError, 'Storyboard approval'):
            q.gate('full')
        q.record('storyboard', 'TEST ONLY')
        q.gate('full')
        # Same path with changed bytes invalidates Demo approval.
        png(self.root / 'actor.png', 32, 32, lambda x, y: (0, 255, 0, 255))
        with self.assertRaisesRegex(ValueError, 'Demo approval'):
            Project(project_file, self.ffmpeg).gate('full')
        preview = os.environ.get('COMPOSITION_PREVIEW')
        if preview:
            import shutil
            Path(preview).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / 'deliverables/full.mp4', Path(preview) / 'composition-test.mp4')
            for i in range(1, 4):
                shutil.copyfile(self.root / f'deliverables/full-check-{i}.png', Path(preview) / f'check-{i}.png')
        # Invalid video offsets must fail before silently omitting the layer/video.
        c['shots'][1]['source_start'] = 99
        board['shots'][1]['source_start'] = 99
        write_json(project_file, c)
        write_json(self.root / 'storyboard.json', board)
        q = Project(project_file, self.ffmpeg)
        q.record('storyboard', 'TEST ONLY')
        with self.assertRaisesRegex(ValueError, 'No decodable video frame'):
            q.render('demo')


if __name__ == '__main__':
    unittest.main()
