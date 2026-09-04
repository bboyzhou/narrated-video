"""Isolated regression smoke test using real FFmpeg, existing images and synthetic PCM.

python test_pipeline.py --ffmpeg PATH --image PATH --alternate-image PATH --output DIR
No real approval is created: all approval records belong to the test fixture.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import wave

from pipeline import Project, initialize, write_json, read_json


def rejected(action, message):
    try:
        action()
    except (ValueError, RuntimeError, OSError) as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('Expected rejection: ' + message)


def tone(path, duration, frequency):
    rate = 24000
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(b''.join(struct.pack('<h', int(2400 * math.sin(2*math.pi*frequency*i/rate))) for i in range(round(rate*duration))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ffmpeg', 'image', 'alternate-image', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    parent = Path(args.output).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='validation-', dir=parent))
    project_file = root / 'project.json'
    initialize(project_file, None)
    rejected(lambda: initialize(project_file, None), 'already exists')
    c = read_json(project_file)
    c['output'] = {'width': 320, 'height': 180, 'fps': 30}
    c['voice'] = {'engine': 'files'}
    c['style'] = {'name': 'isolated regression fixture'}
    c['narration'] = [{'id': f'N{i}', 'text': text, 'audio': f'audio-{i}.wav'} for i, text in enumerate(['这是第一句。', '这是第二句。', '这是第三句。'], 1)]
    (root / 'approved-script.txt').write_text('这是第一句。这是第二句。这是第三句。', encoding='utf-8')
    c['shots'] = [{'id': f'S{i}', 'type': 'image', 'asset': f'image-{i}.png', 'narration': [f'N{i}'], 'motion': motion, 'transition': .2, 'source': 'Existing local validation asset'} for i, motion in enumerate(['push', 'pan-right', 'pull'], 1)]
    c['demo'] = {'shots': ['S1', 'S2']}
    c['music'] = [{'path': 'music.wav', 'start': 0, 'end': 8, 'volume': .1, 'fade_in': .2, 'fade_out': .2, 'source': 'Synthetic local test tone', 'license': 'Test generated'}]
    for i, duration in enumerate([1.07, 1.13], 1):
        tone(root / f'audio-{i}.wav', duration, 220*i)
        shutil.copyfile(args.image, root / f'image-{i}.png')
    tone(root / 'music.wav', 1.5, 110)
    write_json(project_file, c)
    p = lambda: Project(project_file, args.ffmpeg)
    rejected(lambda: p().render('demo'), 'Script approval')
    p().record('script', 'TEST FIXTURE ONLY: approve script')
    rejected(lambda: p().render('full'), 'Demo approval')
    rejected(lambda: p().record('demo', 'TEST FIXTURE'), 'Render the current Demo')
    # Missing non-Demo assets must not block a Demo.
    p().render('demo')
    demo_report = read_json(root / 'deliverables/demo-verification.json')
    assert demo_report['decoded_frames'] == 67
    p().record('demo', 'TEST FIXTURE ONLY: approve Demo')
    tone(root / 'audio-3.wav', 1.2, 660)
    shutil.copyfile(args.image, root / 'image-3.png')
    p().render('full')
    baseline = read_json(root / 'deliverables/full-verification.json')
    assert baseline['decoded_frames'] == 103
    q = p()
    q.render('full')
    assert q.stats['rendered'] == 0 and q.stats['reused'] == 8, q.stats
    # Same path, different image bytes must invalidate affected caches only.
    shutil.copyfile(args.alternate_image, root / 'image-3.png')
    q = p()
    q.render('full')
    assert q.stats['rendered'] == 4 and q.stats['reused'] == 4, q.stats
    changed = dict(q.stats)
    # Demo content modification invalidates its approval, but not script approval.
    shutil.copyfile(args.alternate_image, root / 'image-1.png')
    rejected(lambda: p().gate('full'), 'Demo approval')
    p().gate('demo')
    shutil.copyfile(args.image, root / 'image-1.png')
    # Music timing changes invalidate approval even with identical source media.
    c['demo']['start_seconds'] = 1
    write_json(project_file, c)
    rejected(lambda: p().gate('full'), 'Demo approval')
    del c['demo']['start_seconds']
    # Script changes invalidate both stages.
    c['narration'][0]['text'] = '这是修改后的句子。'
    (root / 'approved-script.txt').write_text('这是修改后的句子。这是第二句。这是第三句。', encoding='utf-8')
    write_json(project_file, c)
    rejected(lambda: p().gate('demo'), 'Script approval')
    c['narration'][0]['text'] = '这是第一句。'
    (root / 'approved-script.txt').write_text('这是第一句。这是第二句。这是第三句。', encoding='utf-8')
    write_json(project_file, c)
    # Incomplete writes are not reused after failure.
    q = p()
    def fail(target):
        target.write_text('partial', encoding='utf-8')
        raise RuntimeError('simulated failure')
    rejected(lambda: q.cached('test-failure', {}, '.txt', fail), 'simulated failure')
    done = q.cached('test-failure', {}, '.txt', lambda target: target.write_text('complete', encoding='utf-8'))
    assert done.read_text(encoding='utf-8') == 'complete'
    # Corruption of a finalized cache object is also detected.
    done.write_text('corrupt', encoding='utf-8')
    done = q.cached('test-failure', {}, '.txt', lambda target: target.write_text('recovered', encoding='utf-8'))
    assert done.read_text(encoding='utf-8') == 'recovered'
    report = {'passed': True, 'project': str(project_file), 'checks': ['init refuses overwrite', 'script gate', 'Demo gate', 'Demo approval requires artifact', 'Demo without remaining assets', 'real decode and frame counts', 'no-change cache reuse', 'same-path image invalidation', 'Demo content invalidation', 'Demo music offset invalidation', 'script invalidation', 'failed step recovery', 'cache corruption recovery'], 'demo_frames': 67, 'full_frames': 103, 'image_change_cache': changed,
              'limitations': 'Synthetic tone audio; not a speech quality or full-length performance test'}
    write_json(root / 'test-results.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
