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

from pipeline import (Project, initialize, preflight_fingerprint, preflight_path,
                      write_json, read_json, pause_seconds, trailing_silence_seconds,
                      speech_rate_adjustment)


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


def regression_pacing_checks(root):
    pacing = {'pause_policy': 'semantic', 'default_pause': 0.28,
              'continuation_pause': 0.18, 'dialogue_pause': 0.4,
              'scene_change_pause': 0.5, 'final_pause': 1.5}
    assert abs(pause_seconds({'text': '普通句。'}, pacing) - .28) < 1e-9
    assert abs(pause_seconds({'text': '未完：'}, pacing) - .18) < 1e-9
    assert abs(pause_seconds({'text': '他说！'}, pacing) - .4) < 1e-9
    assert abs(pause_seconds({'text': '切镜。'}, pacing, shot_boundary=True) - .5) < 1e-9
    assert abs(pause_seconds({'text': '收尾。'}, pacing, is_final=True) - 1.5) < 1e-9
    assert abs(pause_seconds({'text': '覆盖。', 'pause_after': .7}, pacing) - .65) < 1e-9
    assert pause_seconds({'text': '关闭。'}, {'pause_policy': 'none'}) == 0
    tail = root / 'tail.wav'
    tone(tail, .2, 440)
    with wave.open(str(tail), 'rb') as source:
        params, frames = source.getparams(), source.readframes(source.getnframes())
    with wave.open(str(tail), 'wb') as w:
        w.setparams(params)
        w.writeframes(frames + b'\x00\x00' * round(24000 * .1))
    assert .09 <= trailing_silence_seconds(tail) <= .11
    rate_cfg = {'policy': 'soft', 'target_units_per_second': 5,
                'tolerance': .12, 'min_tempo': .88, 'max_tempo': 1.12, 'min_units': 6}
    fast = root / 'fast.wav'
    tone(fast, 1.0, 440)
    fast_info = speech_rate_adjustment({'text': '一二三四五六七八九十'}, fast, rate_cfg)
    assert fast_info['rate_status'] == 'clamped' and abs(fast_info['tempo_factor'] - .88) < 1e-9
    short = root / 'short.wav'
    tone(short, 1.0, 440)
    short_info = speech_rate_adjustment({'text': '一二三'}, short, rate_cfg)
    assert short_info['rate_status'] == 'insufficient_data'
    preserved = speech_rate_adjustment({'text': '一二三四五六七八九十', 'rate_policy': 'preserve'}, fast, rate_cfg)
    assert preserved['rate_status'] == 'preserved' and preserved['tempo_factor'] == 1.0


def storyboard_for(shots):
    plans = []
    for i, shot in enumerate(shots, 1):
        plans.append({'id': shot['id'], 'narration': shot['narration'],
                      'purpose': f'验证镜头 {i} 的叙事信息', 'estimated_duration_seconds': 12,
                      'visual': {'subject': f'测试主体 {i}', 'action': '保持静态姿态', 'setting': '测试环境',
                                 'shot_size': '中景', 'composition': '主体居中并保留字幕安全区',
                                 'lighting_color': '柔和中性色'},
                      'continuity': ['统一主体比例与中性色调'],
                      'prompt': shot['prompt'], 'negative_prompt': shot['negative_prompt'],
                      'asset_strategy': 'user', 'motion': shot['motion'],
                      'transition_seconds': shot['transition']})
    return {'version': 1,
            'creative_brief': {'audience': '回归测试人员', 'platform': '本地验证', 'purpose': '验证制作门禁',
                               'target_duration_seconds': 36, 'narrative_arc': '依次展示三个测试镜头',
                               'visual_style': '统一测试图片', 'pacing': '每镜约十二秒',
                               'voice_direction': '合成测试音', 'music_direction': '低音量测试音',
                               'continuity_anchors': ['统一画幅与色调'], 'constraints': ['仅用于自动化测试']},
            'shots': plans,
            'demo': {'shots': ['S1', 'S2'], 'selection_reason': '连续两镜可覆盖运镜与转场',
                     'validation_goals': ['验证字幕、运镜和叠化']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ffmpeg', 'image', 'alternate-image', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    parent = Path(args.output).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='validation-', dir=parent))
    regression_pacing_checks(root)
    project_file = root / 'project.json'
    initialize(project_file, None)
    rejected(lambda: initialize(project_file, None), 'already exists')
    c = read_json(project_file)
    c['output'] = {'width': 320, 'height': 180, 'fps': 30}
    c['voice'] = {'engine': 'files'}
    c['style'] = {'name': 'isolated regression fixture'}
    c['narration'] = [{'id': f'N{i}', 'text': text, 'audio': f'audio-{i}.wav'} for i, text in enumerate(['这是第一句。', '这是第二句。', '这是第三句。'], 1)]
    (root / 'approved-script.txt').write_text('这是第一句。这是第二句。这是第三句。', encoding='utf-8')
    c['shots'] = [{'id': f'S{i}', 'type': 'image', 'asset': f'image-{i}.png', 'narration': [f'N{i}'],
                   'motion': motion, 'transition': .2, 'prompt': f'Test image {i}',
                   'negative_prompt': 'No text or watermark',
                   'source': 'Existing local validation asset'}
                  for i, motion in enumerate(['push', 'pan-right', 'pull'], 1)]
    c['demo'] = {'shots': ['S1', 'S2']}
    c['music'] = [{'path': 'music.wav', 'start': 0, 'end': 8, 'volume': .1, 'fade_in': .2, 'fade_out': .2, 'source': 'Synthetic local test tone', 'license': 'Test generated'}]
    for i, duration in enumerate([1.07, 1.13], 1):
        tone(root / f'audio-{i}.wav', duration, 220*i)
        shutil.copyfile(args.image, root / f'image-{i}.png')
    tone(root / 'music.wav', 1.5, 110)
    write_json(root / 'storyboard.json', storyboard_for(c['shots']))
    write_json(project_file, c)
    p = lambda: Project(project_file, args.ffmpeg)
    rejected(lambda: p().render('demo'), 'Preflight')
    write_json(preflight_path(project_file), {
        'ok': True,
        'fingerprint': preflight_fingerprint(project_file, c, args.ffmpeg),
        'test_fixture': True,
    })
    rejected(lambda: p().render('demo'), 'Script approval')
    p().record('script', 'TEST FIXTURE ONLY: approve script')
    rejected(lambda: p().render('demo'), 'Storyboard approval')
    p().record('storyboard', 'TEST FIXTURE ONLY: approve storyboard')
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
    assert q.stats['rendered'] == 0 and q.stats['reused'] == 11, q.stats
    # A non-Demo storyboard edit requires full-plan reapproval but preserves Demo approval.
    storyboard = read_json(root / 'storyboard.json')
    storyboard['shots'][2]['purpose'] = '更新第三镜的叙事信息'
    write_json(root / 'storyboard.json', storyboard)
    rejected(lambda: p().gate('full'), 'Storyboard approval')
    p().record('storyboard', 'TEST FIXTURE ONLY: approve updated non-Demo storyboard')
    p().gate('full')
    # Same path, different image bytes must invalidate affected caches only.
    shutil.copyfile(args.alternate_image, root / 'image-3.png')
    q = p()
    q.render('full')
    assert q.stats['rendered'] == 4 and q.stats['reused'] == 7, q.stats
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
    report = {'passed': True, 'project': str(project_file), 'checks': ['init refuses overwrite', 'preflight gate', 'script gate', 'storyboard gate', 'Demo gate', 'Demo approval requires artifact', 'Demo without remaining assets', 'real decode and frame counts', 'no-change cache reuse', 'non-Demo storyboard reapproval preserves Demo', 'same-path image invalidation', 'Demo content invalidation', 'Demo music offset invalidation', 'script invalidation', 'failed step recovery', 'cache corruption recovery'], 'demo_frames': 67, 'full_frames': 103, 'image_change_cache': changed,
              'limitations': 'Synthetic tone audio; not a speech quality or full-length performance test'}
    write_json(root / 'test-results.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
