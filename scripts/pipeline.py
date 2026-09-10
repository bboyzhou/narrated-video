#!/usr/bin/env python3
"""Config-driven image narration pipeline. Python standard library + FFmpeg.

Run --help and read ../references/project.md. No dependency installation.
"""
import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import wave
from runtime import (resolve_paths, validate_paths, relaunch, path_report, doctor,
                     update_config, write_global_runtime)
from composition import resolve_asset, validate_layers, render_args

VERSION = 1

# High-risk readings frequently encountered in Chinese narration.  This is a
# review prompt, not an automatic rewrite: context still decides the reading.
POLYPHONE_HINTS = {
    '率军': '率(shuài)军', '统率': '统(shuài)率', '概率': '概(lǜ)率',
    '长安': '长(cháng)安', '成长': '成(zhǎng)', '行军': '行(xíng)军',
    '银行': '银(háng)行', '乐府': '乐(yuè)府', '音乐': '音(yīn)乐(yuè)',
    '重兵': '重(zhòng)兵', '重复': '重(chóng)复', '将领': '将(jiàng)领',
    '将军': '将(jiàng)军', '朝廷': '朝(cháo)廷', '朝夕': '朝(zhāo)夕',
    '破敌': '破(pò)敌', '敌军': '敌(dí)军',
    '降服': '降(xiáng)服', '投降': '投降(xiáng)',
    '钟繇': '钟(zhōng)繇(yáo)', '繇': '繇(yáo)',
    '单于': '单(chán)于', '高干': '高(gāo)干(gàn)',
    '傅干': '傅(fù)干(gàn)', '车骑': '车(chē)骑(qí)',
    '逢纪': '逢(féng)纪(jì)', '沮授': '沮(jǔ)授(shòu)',
    '审配': '审(shěn)配(pèi)', '贾逵': '贾(jiǎ)逵(kuí)',
    '绛县': '绛(jiàng)县(xiàn)', '汾河': '汾(fén)河',
    '谯县': '谯(qiáo)县', '浚仪': '浚(jùn)仪', '睢阳': '睢(suī)阳'
}

PAUSE_ROLES = {'default', 'continuation', 'dialogue', 'scene_change', 'dramatic', 'final'}


def trailing_silence_seconds(path, threshold_db=-45, window_ms=20):
    """Measure trailing near-silence in a PCM WAV without changing its audio."""
    with wave.open(str(path), 'rb') as audio:
        require(audio.getcomptype() == 'NONE' and audio.getsampwidth() == 2,
                'Trailing-silence measurement requires 16-bit PCM WAV')
        rate, channels, total = audio.getframerate(), audio.getnchannels(), audio.getnframes()
        if not total:
            return 0.0
        samples = array('h', audio.readframes(total))
    threshold = 32767 * (10 ** (threshold_db / 20))
    window = max(1, int(rate * window_ms / 1000)) * channels
    silent_frames = 0
    for end in range(len(samples), 0, -window):
        block = samples[max(0, end - window):end]
        if not block:
            break
        rms = math.sqrt(sum(sample * sample for sample in block) / len(block))
        if rms > threshold:
            break
        silent_frames += len(block) // channels
    return min(total / rate, silent_frames / rate)


def pause_seconds(sentence, pacing, is_final=False, shot_boundary=False):
    """Return the requested post-sentence pause, independent of TTS engine."""
    if not pacing or pacing.get('pause_policy', 'semantic') in ('none', 'off'):
        return 0.0
    explicit = sentence.get('pause_after')
    if explicit is not None:
        value = float(explicit)
    else:
        role = sentence.get('pause_role')
        text = sentence.get('text', '').rstrip()
        if is_final:
            role = 'final'
        elif shot_boundary and role is None:
            role = 'scene_change'
        elif role is None and text.endswith(('：', ':', '；', ';')):
            role = 'continuation'
        elif role is None and text.endswith(('！', '？', '!', '?', '”', '"')):
            role = 'dialogue'
        else:
            role = role or 'default'
        require(role in PAUSE_ROLES, 'Unsupported pause_role: ' + str(role))
        value = float(pacing.get(role + '_pause', pacing.get('default_pause', 0.28)))
    if not is_final:
        value = min(max(value, 0.15), 0.65)
    return max(0.0, value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def compact(text):
    return re.sub(r'\s+', '', text)


def pronunciation_audit(sentences):
    """Return context-sensitive polyphone hits and whether their reading is documented."""
    hits = []
    for sentence in sentences:
        text = sentence['text']
        phrases = [phrase for phrase in POLYPHONE_HINTS if phrase in text]
        phrases = [phrase for phrase in phrases if not any(
            phrase != other and phrase in other for other in phrases)]
        found = [f'{phrase} → {POLYPHONE_HINTS[phrase]}' for phrase in phrases]
        if not found:
            continue
        documented = bool(sentence.get('tts_text') or sentence.get('pronunciation') or sentence.get('pronunciation_note'))
        hits.append({'id': sentence['id'], 'text': text, 'hints': found,
                     'status': 'documented' if documented else 'needs_reading_confirmation',
                     'action': ('已记录目标读音；试听确认，CosyVoice 若误读则填写 pronunciation 或 tts_text。'
                                if documented else
                                '试听确认；填写 pronunciation_note，并在模型误读时加入 pronunciation（优先）或 tts_text。')})
    return hits



def tts_input(sentence):
    """Build engine input while preserving subtitle/approved text.

    ``pronunciation`` is a list of {text, proxy, reading} entries. Proxy
    substitutions are TTS-only and must keep the same spoken intent;
    ``tts_text`` remains available for engine-specific overrides.
    """
    explicit = sentence.get('tts_text')
    value = sentence['text'] if explicit is None else explicit
    for item in sentence.get('pronunciation', []):
        source = str(item.get('text', ''))
        proxy = str(item.get('proxy', ''))
        require(source and proxy, f"Invalid pronunciation entry in {sentence['id']}")
        value = value.replace(source, proxy)
    return value


def motion_filter(width, height, frames, motion, easing='smoothstep', max_zoom=0.06):
    """Build a subpixel Ken Burns filter using FFmpeg perspective resampling.

    Unlike zoompan, perspective keeps the source crop coordinates as floating
    point values and resamples them with cubic interpolation, so slow pans do
    not become repeated frames followed by integer-pixel jumps.
    """
    require(motion in ('still', 'push', 'pull', 'pan-left', 'pan-right'),
            'Unsupported motion')
    denominator = max(frames - 1, 1)
    progress = f'(on-1)/{denominator}'
    if easing == 'smoothstep':
        eased = f'(({progress})*({progress})*(3-2*({progress})))'
    else:
        eased = progress
    base = (f'scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,'
            f'crop={width}:{height},format=gbrp')
    if motion == 'still':
        return base + ',setsar=1,format=yuv420p'
    if motion == 'push':
        zoom = f'(1+{max_zoom}*{eased})'
    elif motion == 'pull':
        zoom = f'(1+{max_zoom}*(1-({eased})))'
    else:
        zoom = f'(1+{max_zoom}*0.5)'
    sample_w = f'(W/{zoom})'
    sample_h = f'(H/{zoom})'
    max_x = f'(W-{sample_w})'
    max_y = f'(H-{sample_h})'
    if motion == 'push' or motion == 'pull':
        left = f'({max_x}/2)'
    elif motion == 'pan-right':
        left = f'({max_x})*{eased}'
    else:
        left = f'({max_x})*(1-({eased}))'
    top = f'({max_y}/2)'
    right = f'({left}+{sample_w})'
    bottom = f'({top}+{sample_h})'
    perspective = ("perspective="
                   f"x0='{left}':y0='{top}':"
                   f"x1='{right}':y1='{top}':"
                   f"x2='{left}':y2='{bottom}':"
                   f"x3='{right}':y3='{bottom}':"
                   "sense=source:eval=frame:interpolation=cubic")
    return base + ',' + perspective + ',setsar=1,format=yuv420p'

def char_units(ch):
    """Approximate rendered width in half-em units for deterministic wrapping."""
    if ch.isspace():
        return 1
    east = unicodedata.east_asian_width(ch)
    return 2 if east in ('W', 'F', 'A') else 1


def wrap_caption(text, max_units):
    """Wrap captions by approximate pixel width, preferring natural punctuation."""
    text = re.sub(r'\s+', ' ', text).strip()
    lines = []
    rest = text
    breaks = set('，。！？；：、,。!?;:')
    while rest:
        used = 0
        end = 0
        candidates = []
        for i, ch in enumerate(rest):
            nxt = used + char_units(ch)
            if nxt > max_units:
                break
            used = nxt
            end = i + 1
            if ch in breaks:
                candidates.append(end)
        if end == len(rest):
            lines.append(rest)
            break
        cut = candidates[-1] if candidates else end
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return lines


def run(command, cwd=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd, capture_output=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Command failed: ' + str(command[0]) + '\n' + result.stderr[-6000:])
    return result


def preflight_path(project):
    return Path(project).resolve().parent / '.narrated-video' / 'preflight.json'


def _executable_identity(value):
    if not value:
        return None
    path = Path(value).resolve()
    if not path.is_file():
        return {'path': str(path), 'exists': False}
    stat = path.stat()
    return {'path': str(path), 'exists': True, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def preflight_fingerprint(project, config, ffmpeg_override=None):
    runtime_config = config.get('runtime', {})
    paths = resolve_paths(project, runtime_config)
    ffmpeg = str(Path(ffmpeg_override).resolve()) if ffmpeg_override else paths.get('ffmpeg') or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    return digest({'schema': 1,
                   'runtime': {**runtime_config, **paths},
                   'python': _executable_identity(paths.get('python') or sys.executable),
                   'ffmpeg': _executable_identity(ffmpeg),
                   'voice': config.get('voice', {})})


class Project:
    def __init__(self, path, ffmpeg=None, validation_stage='production'):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.c = read_json(self.path)
        self.work = self.root / '.narrated-video'
        self.cache = self.work / 'cache'
        self.state_path = self.work / 'state.json'
        self.preflight_path = preflight_path(self.path)
        self.state = read_json(self.state_path) if self.state_path.exists() else {}
        self.runtime = resolve_paths(self.path, self.c.get('runtime', {}))
        self.ffmpeg = str(Path(ffmpeg).resolve()) if ffmpeg else self.runtime.get('ffmpeg') or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
        self.stats = {'rendered': 0, 'reused': 0}
        self.require_preflight()
        self.validate(validation_stage)

    def preflight_key(self):
        return preflight_fingerprint(self.path, self.c, self.ffmpeg)

    def require_preflight(self):
        record = read_json(self.preflight_path) if self.preflight_path.is_file() else {}
        require(record.get('ok') and record.get('fingerprint') == self.preflight_key(),
                'Preflight missing or stale; run preflight before script or storyboard planning')

    def path_for(self, value):
        return resolve_asset(self.root, self.c, value)[0]

    @staticmethod
    def _text(value, label):
        require(isinstance(value, str) and value.strip(), label + ' must be nonempty text')

    @staticmethod
    def _text_list(value, label, allow_empty=False):
        expectation = ' must be a list' if allow_empty else ' must be a nonempty list'
        require(isinstance(value, list) and (allow_empty or value), label + expectation)
        require(all(isinstance(item, str) and item.strip() for item in value), label + ' must contain nonempty text')

    def validate_storyboard(self):
        c = self.c
        value = c.get('storyboard')
        require(isinstance(value, str) and value.strip(),
                'Project needs storyboard path; prepare a production brief and shot plan before Demo production')
        self.storyboard_path = self.path_for(value)
        require(self.storyboard_path.is_file(), 'Storyboard file missing: ' + str(self.storyboard_path))
        self.storyboard = read_json(self.storyboard_path)
        require(self.storyboard.get('version') == 1, 'Unsupported storyboard version')

        brief = self.storyboard.get('creative_brief')
        require(isinstance(brief, dict), 'storyboard.creative_brief must be an object')
        for key in ('audience', 'platform', 'purpose', 'narrative_arc', 'visual_style',
                    'pacing', 'voice_direction', 'music_direction'):
            self._text(brief.get(key), 'storyboard.creative_brief.' + key)
        target = brief.get('target_duration_seconds')
        require(type(target) in (int, float) and 1 <= target <= 21600,
                'storyboard.creative_brief.target_duration_seconds must be 1..21600')
        self._text_list(brief.get('continuity_anchors'), 'storyboard.creative_brief.continuity_anchors')
        self._text_list(brief.get('constraints'), 'storyboard.creative_brief.constraints', allow_empty=True)

        planned = self.storyboard.get('shots')
        require(isinstance(planned, list) and planned, 'storyboard.shots must be a nonempty list')
        require(all(isinstance(shot, dict) for shot in planned), 'storyboard.shots must contain objects')
        require([shot.get('id') for shot in planned] == list(self.shots),
                'Storyboard shots must match project shots exactly and in order')
        self.storyboard_shots = {shot['id']: shot for shot in planned}
        for shot_id, plan in self.storyboard_shots.items():
            shot = self.shots[shot_id]
            require(plan.get('narration') == shot['narration'],
                    shot_id + ': storyboard narration must match project shot narration')
            self._text(plan.get('purpose'), shot_id + '.purpose')
            estimate = plan.get('estimated_duration_seconds')
            require(type(estimate) in (int, float) and estimate > 0,
                    shot_id + '.estimated_duration_seconds must be positive')
            visual = plan.get('visual')
            require(isinstance(visual, dict), shot_id + '.visual must be an object')
            for key in ('subject', 'action', 'setting', 'shot_size', 'composition', 'lighting_color'):
                self._text(visual.get(key), shot_id + '.visual.' + key)
            self._text_list(plan.get('continuity'), shot_id + '.continuity')
            self._text(plan.get('prompt'), shot_id + '.prompt')
            self._text(plan.get('negative_prompt'), shot_id + '.negative_prompt')
            require(plan.get('asset_strategy') in ('user', 'generate', 'licensed', 'mixed', 'generated_video'),
                    shot_id + '.asset_strategy must be user, generate, licensed, mixed or generated_video')
            if plan.get('asset_strategy') == 'generated_video':
                self._text(plan.get('source_image'), shot_id + '.source_image')
                source_image = self.path_for(plan['source_image'])
                require(source_image.is_file(), shot_id + '.source_image missing: ' + str(source_image))
                self._text(plan.get('motion_prompt'), shot_id + '.motion_prompt')
                self._text_list(plan.get('motion_constraints'), shot_id + '.motion_constraints')
                generation = plan.get('generation')
                require(isinstance(generation, dict), shot_id + '.generation must be an object')
                require(generation.get('provider') == 'cogvideox_colab',
                        shot_id + '.generation.provider must be cogvideox_colab')
                require(generation.get('mode') == 'i2v', shot_id + '.generation.mode must be i2v')
                require(type(generation.get('duration_target')) in (int, float) and
                        1 <= generation['duration_target'] <= 30,
                        shot_id + '.generation.duration_target must be 1..30 seconds')
                require(type(generation.get('seed')) is int and 0 <= generation['seed'] <= 2**32 - 1,
                        shot_id + '.generation.seed must be an integer in 0..2^32-1')
            require(plan.get('motion') == shot.get('motion', 'push'),
                    shot_id + ': storyboard motion must match project shot motion')
            require(type(plan.get('transition_seconds')) in (int, float) and
                    abs(plan['transition_seconds'] - shot.get('transition', 0.3)) < 1e-9,
                    shot_id + ': storyboard transition_seconds must match project shot transition')
            require(shot.get('prompt') == plan['prompt'],
                    shot_id + ': project prompt must match the approved storyboard prompt')
            require(shot.get('negative_prompt') == plan['negative_prompt'],
                    shot_id + ': project negative_prompt must match the approved storyboard')
            for key, default in (('layers', []), ('type', 'image'), ('source_start', 0), ('loop', False)):
                require(plan.get(key, default) == shot.get(key, default),
                        shot_id + ': storyboard ' + key + ' must match project shot')

        demo = self.storyboard.get('demo')
        require(isinstance(demo, dict), 'storyboard.demo must be an object')
        require(demo.get('shots') == c['demo']['shots'],
                'storyboard.demo.shots must match project demo.shots')
        self._text(demo.get('selection_reason'), 'storyboard.demo.selection_reason')
        self._text_list(demo.get('validation_goals'), 'storyboard.demo.validation_goals')

    def validate(self, validation_stage='production'):
        c = self.c
        require(validation_stage in ('script', 'production'), 'Unknown validation stage')
        require(c.get('version') == VERSION, 'Unsupported project version')
        self.output = c['output']
        self.fps = self.output['fps']
        require(type(self.fps) is int and 1 <= self.fps <= 60, 'fps must be an integer in 1..60')
        for k in ('width', 'height'):
            require(type(self.output[k]) is int and self.output[k] >= 64 and self.output[k] % 2 == 0, k + ' must be even and >=64')
        require(c['narration'], 'Fill narration first')
        self.sentences = {s['id']: s for s in c['narration']}
        require(len(self.sentences) == len(c['narration']), 'Duplicate narration IDs')
        for item in c['narration']:
            require(re.fullmatch(r'[A-Za-z0-9_-]+', item['id']), 'IDs must use ASCII letters, digits, _ or -')
        for sentence in c['narration']:
            require(isinstance(sentence['text'], str) and compact(sentence['text']), 'Empty narration text')
        pacing = c.get('pacing', {})
        require(isinstance(pacing, dict), 'pacing must be an object')
        require(pacing.get('pause_policy', 'semantic') in ('semantic', 'none', 'off'),
                'pacing.pause_policy must be semantic, none or off')
        for key in ('default_pause', 'continuation_pause', 'dialogue_pause', 'scene_change_pause', 'dramatic_pause', 'final_pause'):
            if key in pacing:
                require(type(pacing[key]) in (int, float) and 0 <= pacing[key] <= 10,
                        'pacing.' + key + ' must be 0..10 seconds')
        if 'respect_existing_tail' in pacing:
            require(type(pacing['respect_existing_tail']) is bool, 'pacing.respect_existing_tail must be boolean')
        if 'subtitle_during_pause' in pacing:
            require(type(pacing['subtitle_during_pause']) is bool, 'pacing.subtitle_during_pause must be boolean')
        for sentence in c['narration']:
            if 'pause_after' in sentence:
                require(type(sentence['pause_after']) in (int, float) and 0 <= sentence['pause_after'] <= 10,
                        sentence['id'] + ': pause_after must be 0..10 seconds')
            if 'pause_role' in sentence:
                require(sentence['pause_role'] in PAUSE_ROLES,
                        sentence['id'] + ': unsupported pause_role')
        text = self.path_for(c['script']).read_text(encoding='utf-8-sig')
        require(compact(text) == compact(''.join(s['text'] for s in c['narration'])), 'Narration must match the approved plain spoken script exactly (except whitespace)')
        sub = c['subtitles']
        require(re.fullmatch(r'[\w -]+', sub['font'], re.UNICODE), 'Use a plain font family name')
        require(8 <= sub.get('size', 24) <= 120, 'Subtitle size must be 8..120 at 720p')
        require(5 <= sub.get('max_chars', 24) <= 60, 'Subtitle max_chars must be 5..60')
        for sentence in c['narration']:
            require(len(re.sub(r'\s+', ' ', sentence['text']).strip()) <= sub.get('max_chars', 24) * 2,
                    sentence['id'] + ': subtitle exceeds two lines; split at real spoken boundaries')
        if validation_stage == 'script':
            return
        require(c['shots'], 'Fill shots and storyboard before production')
        self.shots = {s['id']: s for s in c['shots']}
        require(len(self.shots) == len(c['shots']), 'Duplicate shot IDs')
        for item in c['shots']:
            require(re.fullmatch(r'[A-Za-z0-9_-]+', item['id']), 'IDs must use ASCII letters, digits, _ or -')
        covered = []
        for shot in c['shots']:
            validate_layers(shot)
            if shot['type'] == 'video':
                require(shot.get('motion', 'push') == 'still', 'Video shots require motion=still')
            for media in [shot, *shot.get('layers', [])]:
                _, entry = resolve_asset(self.root, c, media['asset'])
                require(not entry or entry['type'] == media['type'], 'Catalog media type mismatch')
            require(shot['narration'], 'Each shot needs narration IDs')
            covered.extend(shot['narration'])
            require(shot.get('motion', 'push') in ('still', 'push', 'pull', 'pan-left', 'pan-right'), 'Unsupported motion')
            require(0 <= shot.get('transition', 0.3) <= 2, 'transition must be 0..2 seconds')
        require(covered == list(self.sentences), 'Shots must cover narration once, in order, without gaps')
        demo = c['demo']['shots']
        require(demo and all(s in self.shots for s in demo), 'Demo must reference existing shots')
        positions = [list(self.shots).index(s) for s in demo]
        require(positions == list(range(positions[0], positions[0] + len(positions))), 'Demo shots must be consecutive and ordered')
        self.validate_storyboard()
        voice = c['voice']
        require(voice['engine'] in ('files', 'melotts', 'cosyvoice'), 'voice.engine must be files, melotts or cosyvoice')
        if voice['engine'] == 'cosyvoice':
            require(voice.get('provider', 'cosyvoice').lower() == 'cosyvoice', 'cosyvoice engine requires provider=cosyvoice')
            require(isinstance(voice.get('command'), list) and voice['command'],
                    'CosyVoice requires voice.command: an argv list with {text_file} and {output} placeholders')
            require('{output}' in voice['command'] and ('{text_file}' in voice['command'] or '{text}' in voice['command']),
                    'CosyVoice command must include {output} and {text_file} or {text}')
            batch_command = voice.get('batch_command')
            if batch_command is not None:
                require(isinstance(batch_command, list) and batch_command,
                        'CosyVoice batch_command must be a nonempty argv list')
                require(any('{jobs_file}' in str(item) for item in batch_command),
                        'CosyVoice batch_command must include {jobs_file}')
            require(voice.get('model') and voice.get('model_path'), 'CosyVoice requires model and model_path')
            require(voice.get('license'), 'CosyVoice requires model license notes')
            require(self.path_for(voice['model_path']).exists(), 'CosyVoice model_path unavailable: ' + str(voice['model_path']))
        require(0.1 <= voice.get('speed', 1) <= 3, 'voice.speed must be 0.1..3')
        require(c['demo'].get('start_seconds', 0) >= 0, 'Demo start_seconds cannot be negative')
        for music in c.get('music', []):
            require(music['end'] > music['start'] >= 0, 'Invalid music interval')
            require(0 <= music.get('volume', 0.15) <= 1, 'Music volume must be 0..1')
            require(music.get('fade_in', 1) >= 0 and music.get('fade_out', 1) >= 0, 'Negative music fade')
            require(music.get('source') and music.get('license'), 'Music needs source and license notes')
        mix = c.get('mix', {})
        require(-30 <= float(mix.get('music_relative_db', -12)) <= 0, 'music_relative_db must be -30..0 dB')
        motion_cfg = c.get('motion', {})
        require(motion_cfg.get('easing', 'smoothstep') in ('linear', 'smoothstep'), 'motion.easing must be linear or smoothstep')
        require(0 <= float(motion_cfg.get('max_zoom', 0.06)) <= 0.15, 'motion.max_zoom must be 0..0.15')

    def selected(self, stage):
        return [self.shots[s] for s in self.c['demo']['shots']] if stage == 'demo' else self.c['shots']

    def script_key(self):
        return digest([{'id': s['id'], 'text': s['text']} for s in self.c['narration']])

    def storyboard_execution(self, shot_ids=None):
        ids = set(shot_ids) if shot_ids is not None else None
        return [{key: shot.get(key) for key in ('id', 'type', 'narration', 'motion', 'transition',
                                                 'prompt', 'negative_prompt', 'layers', 'source_start', 'loop')}
                for shot in self.c['shots'] if ids is None or shot['id'] in ids]

    def storyboard_key(self):
        return digest({'script': self.script_key(), 'storyboard': self.storyboard,
                       'style': self.c['style'], 'output': self.output,
                       'motion': self.c.get('motion', {}),
                       'execution': self.storyboard_execution()})

    def demo_storyboard_key(self):
        ids = self.c['demo']['shots']
        plans = [self.storyboard_shots[shot_id] for shot_id in ids]
        return digest({'script': self.script_key(),
                       'creative_brief': self.storyboard['creative_brief'],
                       'shots': plans, 'demo': self.storyboard['demo'],
                       'execution': self.storyboard_execution(ids)})

    def storyboard_report(self):
        total = sum(shot['estimated_duration_seconds'] for shot in self.storyboard['shots'])
        demo_total = sum(self.storyboard_shots[shot_id]['estimated_duration_seconds']
                         for shot_id in self.c['demo']['shots'])
        target = self.storyboard['creative_brief']['target_duration_seconds']
        warnings = []
        if abs(total - target) / target > 0.2:
            warnings.append('Storyboard estimate differs from target duration by more than 20%; review pacing before approval')
        if not 20 <= demo_total <= 40:
            warnings.append('Demo estimate is outside the recommended 20-40 second range; confirm that the selected span is still representative')
        return {'status': 'passed', 'shots': len(self.storyboard['shots']),
                'estimated_duration_seconds': total, 'target_duration_seconds': target,
                'demo_estimated_duration_seconds': demo_total,
                'demo_selection_reason': self.storyboard['demo']['selection_reason'],
                'demo_validation_goals': self.storyboard['demo']['validation_goals'],
                'warnings': warnings}

    def asset(self, value):
        p, metadata = resolve_asset(self.root, self.c, value)
        return {**metadata, 'path': str(p), 'sha256': file_hash(p) if p.is_file() else None}

    def layer_assets(self, shots):
        return [{**layer, **self.asset(layer['asset']), 'shot': shot['id']}
                for shot in shots for layer in shot.get('layers', [])]

    def demo_key(self):
        shots = self.selected('demo')
        voices = []
        for shot in shots:
            for sid in shot['narration']:
                sentence = self.sentences[sid]
                if sentence.get('audio'):
                    voices.append(self.asset(sentence['audio']))
        return digest({'script': self.script_key(), 'style': self.c['style'], 'voice': self.c['voice'],
                       'storyboard': self.demo_storyboard_key(),
                       'output': self.output, 'subtitles': self.c['subtitles'], 'shots': shots, 'demo': self.c['demo'],
                       'motion': self.c.get('motion', {}),
                       'images': [self.asset(s['asset']) for s in shots], 'voices': voices,
                       'layers': self.layer_assets(shots),
                       'music': [(m, self.asset(m['path'])) for m in self.c.get('music', [])],
                       'mix': self.c.get('mix', {}),
                       'runtime': {**self.c.get('runtime', {}), **self.runtime},
                       'renderer': [file_hash(__file__), file_hash(Path(__file__).with_name('runtime.py')),
                                    file_hash(Path(__file__).with_name('composition.py'))]})

    def gate(self, stage):
        self.require_preflight()
        record = self.state.get('script', {})
        require(record.get('fingerprint') == self.script_key(), 'Script approval missing or stale; obtain user approval and record it')
        if stage in ('demo', 'full'):
            record = self.state.get('storyboard', {})
            require(record.get('fingerprint') == self.storyboard_key(),
                    'Storyboard approval missing or stale; review the production brief and full shot plan with the user')
        if stage == 'full':
            require(self.state.get('demo', {}).get('fingerprint') == self.demo_key(), 'Demo approval missing or stale; render and approve a new Demo')

    def record(self, stage, quote, skip=False):
        self.require_preflight()
        require(quote.strip(), 'Record the actual user reply')
        if stage == 'script':
            key = self.script_key()
        elif stage == 'storyboard':
            self.gate('storyboard')
            key = self.storyboard_key()
        else:
            self.gate('demo')
            key = self.demo_key()
            if not skip:
                artifact = self.state.get('demo_render', {})
                require(artifact.get('fingerprint') == key, 'Render the current Demo before recording approval')
                p = self.root / 'deliverables' / 'demo.mp4'
                require(p.is_file() and file_hash(p) == artifact.get('sha256'), 'Demo artifact missing or changed')
        self.state[stage] = {'fingerprint': key, 'user_reply': quote, 'explicit_skip': skip,
                             'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        write_json(self.state_path, self.state)

    def ff(self, args, cwd=None):
        require(self.ffmpeg, 'FFmpeg not found; pass --ffmpeg, configure/remember-runtime, or set FFMPEG. No automatic installation.')
        return run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *args], cwd)

    def cache_slot(self, kind, inputs, suffix):
        key = digest({'kind': kind, 'inputs': inputs,
                      'runtime': {**self.c.get('runtime', {}), **self.runtime}, 'ffmpeg': self.ffmpeg,
                      'renderer': [file_hash(__file__), file_hash(Path(__file__).with_name('runtime.py')),
                                   file_hash(Path(__file__).with_name('composition.py'))]})
        target = self.cache / (key + suffix)
        stamp = self.cache / (key + '.json')
        temporary = self.cache / (key + '.partial' + suffix)
        return target, stamp, temporary

    @staticmethod
    def cache_valid(target, stamp):
        return (target.is_file() and stamp.is_file() and
                read_json(stamp).get('sha256') == file_hash(target))

    def cached(self, kind, inputs, suffix, producer):
        target, stamp, temporary = self.cache_slot(kind, inputs, suffix)
        self.cache.mkdir(parents=True, exist_ok=True)
        if self.cache_valid(target, stamp):
            self.stats['reused'] += 1
            return target
        producer(temporary)
        require(temporary.is_file() and temporary.stat().st_size > 0, 'Empty cache output')
        temporary.replace(target)
        write_json(stamp, {'sha256': file_hash(target), 'inputs': inputs})
        self.stats['rendered'] += 1
        return target

    def cosyvoice_batch(self, selected_ids, config):
        """Generate all uncached CosyVoice sentences with one model process."""
        batch_command = config.get('batch_command')
        if not batch_command:
            return {}
        self.cache.mkdir(parents=True, exist_ok=True)
        result = {}
        misses = []
        for sid in selected_ids:
            sentence = self.sentences[sid]
            if sentence.get('audio'):
                continue
            inputs = {'text': tts_input(sentence), 'subtitle_text': sentence['text'],
                      'pronunciation': sentence.get('pronunciation', []), 'voice': config}
            target, stamp, temporary = self.cache_slot('tts', inputs, '.wav')
            if self.cache_valid(target, stamp):
                self.stats['reused'] += 1
                result[sid] = target
                continue
            misses.append({'id': sid, 'text': tts_input(sentence), 'output': str(temporary),
                           'target': target, 'stamp': stamp, 'temporary': temporary, 'inputs': inputs})
        if not misses:
            return result

        jobs_key = digest([{'id': item['id'], 'text': item['text'],
                            'output': str(item['temporary'])} for item in misses])[:20]
        jobs_file = self.cache / ('.cosyvoice-' + jobs_key + '.partial.json')
        effective_runtime = {**self.c.get('runtime', {}), **self.runtime}
        write_json(jobs_file, {'version': 1, 'offline': bool(effective_runtime.get('offline', False)),
                               'jobs': [{'id': item['id'], 'text': item['text'],
                                         'output': str(item['temporary'])} for item in misses]})
        argv = []
        for arg in batch_command:
            value = str(arg).replace('{jobs_file}', str(jobs_file))
            value = value.replace('{model_path}', str(self.path_for(config['model_path'])))
            value = value.replace('{speaker}', str(config.get('speaker', '中文男')))
            value = value.replace('{speed}', str(config.get('speed', 1)))
            if '{ffmpeg}' in value:
                require(self.ffmpeg, 'CosyVoice batch_command uses {ffmpeg}, but FFmpeg is unavailable')
                value = value.replace('{ffmpeg}', str(self.ffmpeg))
            argv.append(value)
        try:
            run(argv, cwd=str(self.root))
        finally:
            jobs_file.unlink(missing_ok=True)

        # Validate the complete batch before promoting any partial output.  A
        # failed or incomplete batch therefore cannot become a cache hit.
        for item in misses:
            temporary = item['temporary']
            require(temporary.is_file() and temporary.stat().st_size > 0,
                    'CosyVoice batch command did not create a WAV for ' + item['id'])
            with wave.open(str(temporary), 'rb') as audio:
                require(audio.getnframes() > 0 and audio.getcomptype() == 'NONE',
                        'CosyVoice batch command requires nonempty PCM WAV for ' + item['id'])
        for item in misses:
            item['temporary'].replace(item['target'])
            write_json(item['stamp'], {'sha256': file_hash(item['target']), 'inputs': item['inputs']})
            self.stats['rendered'] += 1
            result[item['id']] = item['target']
        return result

    def voices(self, stage):
        self.gate(stage)
        selected_ids = [sid for shot in self.selected(stage) for sid in shot['narration']]
        result = {}
        model = None
        config = self.c['voice']
        pacing = self.c.get('pacing', {})
        pacing_enabled = bool(pacing) and pacing.get('pause_policy', 'semantic') not in ('none', 'off')
        shot_last = {sid for shot in self.selected(stage) for sid in shot['narration'][-1:]}
        final_sid = selected_ids[-1] if selected_ids else None
        batch_raw = (self.cosyvoice_batch(selected_ids, config)
                     if config['engine'] == 'cosyvoice' and config.get('batch_command') else {})
        for sid in selected_ids:
            sentence = self.sentences[sid]
            if sentence.get('audio'):
                p = self.path_for(sentence['audio'])
                require(p.is_file(), 'Missing audio: ' + str(p))
            elif sid in batch_raw:
                p = batch_raw[sid]
            else:
                require(self.c['voice']['engine'] in ('melotts', 'cosyvoice'), 'Missing per-sentence WAV for ' + sid)
                def synthesize(target):
                    nonlocal model
                    if config['engine'] == 'cosyvoice':
                        text_file = target.with_suffix('.txt')
                        text_file.write_text(tts_input(sentence), encoding='utf-8')
                        argv = []
                        for arg in config['command']:
                            value = str(arg)
                            value = value.replace('{text_file}', str(text_file)).replace('{output}', str(target))
                            value = value.replace('{model_path}', str(self.path_for(config['model_path'])))
                            value = value.replace('{text}', tts_input(sentence))
                            argv.append(value)
                        try:
                            run(argv, cwd=str(self.root))
                        finally:
                            text_file.unlink(missing_ok=True)
                        require(target.is_file() and target.stat().st_size > 0,
                                'CosyVoice command did not create a WAV: ' + str(target))
                        return
                    if model is None:
                        try:
                            # g2p_en imports may otherwise attempt implicit NLTK downloads.
                            import nltk
                            missing = []
                            for resource in ('corpora/cmudict.zip', 'taggers/averaged_perceptron_tagger.zip'):
                                try:
                                    nltk.data.find(resource)
                                except LookupError:
                                    missing.append(resource)
                            require(not missing, 'MeloTTS cannot locate NLTK resources: ' + ', '.join(missing) +
                                    '. Search paths: ' + str(nltk.data.path) +
                                    '. Select runtime.nltk_data for existing resources; this does not prove they are absent from the computer. No automatic download.')
                            from melo.api import TTS
                        except ImportError as error:
                            raise ValueError('Run with an existing MeloTTS Python environment; do not install automatically') from error
                        model = TTS(language=config.get('language', 'ZH'), device=config.get('device', 'cpu'))
                    speaker = config.get('speaker', 'ZH')
                    require(speaker in model.hps.data.spk2id, 'Unknown MeloTTS speaker: ' + speaker)
                    model.tts_to_file(tts_input(sentence), model.hps.data.spk2id[speaker], str(target),
                                      speed=config.get('speed', 1), quiet=True)
                p = self.cached('tts', {'text': tts_input(sentence), 'subtitle_text': sentence['text'], 'pronunciation': sentence.get('pronunciation', []), 'voice': config}, '.wav', synthesize)
            source = p
            normalize_inputs = {'source': self.asset(source), 'target_lufs': -20, 'true_peak': -2,
                                'dynamic_normalization': 'dynaudnorm:f=20:g=3:p=0.98:m=30'}
            p = self.cached('voice-normalize', normalize_inputs, '.wav',
                            lambda target, source=source: self.ff(
                                ['-i', source, '-af', 'loudnorm=I=-20:TP=-2:LRA=7:linear=false,dynaudnorm=f=20:g=3:p=0.98:m=30',
                                 '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', target]))
            with wave.open(str(p), 'rb') as w:
                speech_frames = w.getnframes()
                speech_rate = w.getframerate()
                duration = speech_frames / speech_rate
                require(duration > 0 and w.getcomptype() == 'NONE', 'Use nonempty PCM WAV files')
            target_pause = pause_seconds(sentence, pacing, sid == final_sid, sid in shot_last) if pacing_enabled else 0.0
            existing_tail = trailing_silence_seconds(p) if pacing_enabled and pacing.get('respect_existing_tail', True) else 0.0
            added_pause = max(0.0, target_pause - existing_tail)
            output = p
            if added_pause > 1e-4:
                pause_inputs = {'source': self.asset(p), 'target_pause': round(target_pause, 6),
                                'existing_tail': round(existing_tail, 6), 'pacing': pacing}
                total_duration = duration + added_pause
                output = self.cached('voice-pause', pause_inputs, '.wav',
                                     lambda target, source=p, added_pause=added_pause, total_duration=total_duration:
                                     self.ff(['-i', source, '-af', f'apad=pad_dur={added_pause:.6f},atrim=duration={total_duration:.6f}',
                                              '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', target]))
            with wave.open(str(output), 'rb') as w:
                total_frames = w.getnframes()
                total_rate = w.getframerate()
                total_duration = total_frames / total_rate
            frames = math.ceil(total_duration * self.fps - 1e-8)
            speech_duration = max(0.0, duration - existing_tail) if pacing_enabled and pacing.get('respect_existing_tail', True) else duration
            speech_video_frames = math.ceil(speech_duration * self.fps - 1e-8)
            result[sid] = {'path': output, 'duration': total_duration, 'frames': frames,
                           'speech_duration': speech_duration,
                           'speech_frames': speech_video_frames,
                           'pause_seconds': max(0.0, total_duration - speech_duration),
                           'sha256': file_hash(output)}
        return result

    def render(self, stage):
        self.gate(stage)
        selected = self.selected(stage)
        for shot in selected:
            for media in [shot, *shot.get('layers', [])]:
                require(self.path_for(media['asset']).is_file(), 'Missing media: ' + media['asset'])
        for m in self.c.get('music', []):
            require(self.path_for(m['path']).is_file(), 'Missing music: ' + m['path'])
        if any(s['type'] == 'video' or s.get('layers') for s in selected):
            available = self.ff(['-filters']).stdout
            for name in ('overlay', 'scale', 'pad', 'rotate', 'geq', 'tpad', 'fps'):
                require(re.search(r'\b' + name + r'\b', available), 'FFmpeg lacks composition filter: ' + name)
            checked = set()
            for shot in selected:
                for media in [shot, *shot.get('layers', [])]:
                    if media['type'] != 'video':
                        continue
                    source = self.path_for(media['asset'])
                    offset = media.get('source_start', 0)
                    if (source, offset) in checked:
                        continue
                    probe = self.ff(['-ss', offset, '-i', source, '-map', '0:v:0', '-frames:v', 1,
                                     '-progress', 'pipe:1', '-f', 'null', '-'])
                    require(any(int(n) > 0 for n in re.findall(r'^frame=(\d+)', probe.stdout, re.MULTILINE)),
                            'No decodable video frame at source_start: ' + str(source))
                    checked.add((source, offset))
        voices = self.voices(stage)
        w, h, fps = self.output['width'], self.output['height'], self.fps
        durations = [sum(voices[s]['frames'] for s in shot['narration']) for shot in selected]
        tails = [round(s.get('transition', 0.3) * fps) if i + 1 < len(selected) else 0 for i, s in enumerate(selected)]
        for i, t in enumerate(tails[:-1]):
            require(t < min(durations[i], durations[i + 1]), 'Transition must be shorter than both neighboring shots')
        raw = []
        for i, shot in enumerate(selected):
            validate_layers(shot, durations[i] / fps)
            image = self.path_for(shot['asset'])
            n = durations[i] + tails[i]
            motion_cfg = self.c.get('motion', {})
            motion = shot.get('motion', 'push')
            vf = motion_filter(w, h, n, motion,
                               motion_cfg.get('easing', 'smoothstep'),
                               float(motion_cfg.get('max_zoom', 0.06)))
            if shot['type'] == 'video' or shot.get('layers'):
                args = render_args(shot, self.path_for, w, h, fps, n, vf)
                raw.append(self.cached('composition', [self.asset(shot['asset']), shot,
                                       self.layer_assets([shot]), w, h, fps, n, vf], '.mp4',
                                       lambda p, args=args: self.ff([*args, p])))
            else:
                raw.append(self.cached('image-motion', [file_hash(image), vf, fps, n], '.mp4',
                                       lambda p, image=image, vf=vf, n=n: self.ff(['-loop', '1', '-framerate', str(fps), '-i', image, '-vf', vf, '-frames:v', n, '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', p])))
        clips = []
        timeline = []
        cursor = 0
        for i, shot in enumerate(selected):
            n = durations[i]
            inputs = [file_hash(raw[i]), n, [voices[s]['sha256'] for s in shot['narration']]]
            transition = tails[i - 1] if i else 0
            if transition:
                inputs.extend([file_hash(raw[i - 1]), transition])
            def segment(target, i=i, shot=shot, n=n, transition=transition):
                args = ['-filter_complex_threads', '1', '-i', raw[i]]
                filters = []
                if transition:
                    args += ['-ss', durations[i-1] / fps, '-i', raw[i-1]]
                    filters += [f'[1:v]settb=AVTB,setpts=PTS-STARTPTS[prev]', '[0:v]settb=AVTB,setpts=PTS-STARTPTS[cur]',
                                f'[prev][cur]xfade=transition=fade:duration={transition/fps}:offset=0,trim=duration={n/fps},setpts=PTS-STARTPTS[v]']
                else:
                    filters += [f'[0:v]trim=duration={n/fps},setpts=PTS-STARTPTS[v]']
                audio_indices = []
                base = 2 if transition else 1
                for j, sid in enumerate(shot['narration']):
                    info = voices[sid]
                    args += ['-i', info['path']]
                    filters += [f'[{base+j}:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={info["frames"]/fps},asetpts=PTS-STARTPTS[a{j}]']
                    audio_indices.append(f'[a{j}]')
                filters += [''.join(audio_indices) + f'concat=n={len(audio_indices)}:v=0:a=1[a]']
                self.ff(args + ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-t', n/fps,
                                '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', '-c:a', 'pcm_s16le', target])
            clips.append(self.cached('segment', inputs, '.mkv', segment))
            for sid in shot['narration']:
                info = voices[sid]
                timeline.append({'id': sid, 'shot': shot['id'], 'text': self.sentences[sid]['text'],
                                 'start_frame': cursor, 'end_frame': cursor + info['frames'],
                                 'subtitle_end_frame': cursor + info.get('speech_frames', info['frames']),
                                 'audio_duration': info['duration'],
                                 'speech_duration': info.get('speech_duration', info['duration']),
                                 'pause_seconds': info.get('pause_seconds', 0.0)})
                cursor += info['frames']
        # Cache paths contain only hashes, avoiding concat-demuxer path escaping.
        listing = self.cache / 'assembly.txt'
        listing.write_text('\n'.join("file '" + p.name + "'" for p in clips) + '\n', encoding='utf-8')
        joined = self.cached('assembly', [file_hash(p) for p in clips], '.mkv',
                             lambda p: self.ff(['-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', p]))
        destination = self.root / 'deliverables'
        destination.mkdir(exist_ok=True)
        srt = destination / (stage + '.srt')
        srt.write_text(self.subtitles(timeline), encoding='utf-8')
        shutil.copyfile(srt, self.cache / 'captions.srt')
        total = cursor / fps
        # Music is indexed on the full timeline, including a Demo from the middle.
        offset = 0
        if stage == 'demo' and selected[0]['id'] != self.c['shots'][0]['id']:
            require('start_seconds' in self.c['demo'], 'Middle Demo requires demo.start_seconds for music placement')
            offset = self.c['demo']['start_seconds']
        args = ['-filter_complex_threads', '1', '-i', joined]
        sub = self.c['subtitles']
        mix = self.c.get('mix', {})
        size = self._subtitle_effective_size * h / 720
        # SRT rendering uses libass PlayResY=288; convert pixel target to ASS units.
        vf = f"subtitles=filename=captions.srt:force_style='FontName={sub['font']},FontSize={size*288/h},Outline=1,Shadow=0,Alignment=2,MarginV={sub.get('margin', 28)*288/720}'" if sub.get('enabled', True) else 'null'
        filters = [f'[0:v]{vf}[v]', '[0:a]loudnorm=I=-18:TP=-2:LRA=7,aresample=48000,asplit=2[voice][key]']
        music_labels = []
        for m in self.c.get('music', []):
            start, end = max(m['start'], offset), min(m['end'], offset + total)
            if end <= start:
                continue
            idx = len(music_labels) + 1
            args += ['-stream_loop', '-1', '-i', self.path_for(m['path'])]
            length = m['end'] - m['start']
            fi, fo = min(m.get('fade_in', 1), length), min(m.get('fade_out', 1), length)
            track_volume = float(m.get('volume', .22))
            if mix.get('music_adaptive', True):
                track_volume *= 10 ** ((float(mix.get('music_relative_db', -12)) + 12) / 20)
            track_volume = min(max(track_volume, 0.0), 1.0)
            filters += [f'[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={length},asetpts=PTS-STARTPTS,volume={track_volume},afade=t=in:d={fi},afade=t=out:st={length-fo}:d={fo},atrim=start={start-m["start"]}:end={end-m["start"]},asetpts=PTS-STARTPTS,adelay={round((start-offset)*1000)}:all=1,apad,atrim=duration={total}[m{idx}]']
            music_labels.append(f'[m{idx}]')
        if music_labels:
            filters += [''.join(music_labels) + f'amix=inputs={len(music_labels)}:normalize=0[music]',
                        '[music][key]sidechaincompress=threshold=0.06:ratio=2:attack=15:release=400[duck]',
                        '[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false:latency=true[a]']
        else:
            filters += ['[key]anullsink', '[voice]anull[a]']
        final = self.cached('final', [file_hash(joined), file_hash(srt), self.c['music'], self.c.get('mix', {}),
                                    [self.asset(m['path']) for m in self.c['music']], self.c['subtitles'], offset], '.mp4',
                            lambda p: self.ff(args + ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]',
                                                     '-t', total, '-r', fps, '-c:v', 'libx264', '-preset', 'fast', '-crf', '19',
                                                     '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', p], self.cache))
        artifact = destination / (stage + '.mp4')
        shutil.copyfile(final, artifact)
        write_json(destination / (stage + '-timeline.json'), {'fps': fps, 'total_frames': cursor, 'sentences': timeline})
        write_json(destination / (stage + '-manifest.json'), {'images': [{**s, **self.asset(s['asset'])} for s in selected],
                                                             'layers': self.layer_assets(selected),
                                                             'audio': {sid: {**v, 'path': str(v['path'])} for sid, v in voices.items()},
                                                             'music': [{**m, **self.asset(m['path'])} for m in self.c['music']]})
        shutil.copyfile(self.path, destination / 'project.json')
        storyboard_copy = destination / 'storyboard.json'
        if self.storyboard_path.resolve() != storyboard_copy.resolve():
            shutil.copyfile(self.storyboard_path, storyboard_copy)
        write_json(destination / 'approvals.json', {k: self.state.get(k) for k in ('script', 'storyboard', 'demo')})
        self.state[stage + '_render'] = {'fingerprint': self.demo_key() if stage == 'demo' else
                                        digest({'config': self.c, 'storyboard': self.storyboard_key()}),
                                        'sha256': file_hash(artifact), 'frames': cursor, 'cache': self.stats}
        write_json(self.state_path, self.state)
        report = self.verify(stage)
        print(json.dumps({'artifact': str(artifact), 'cache': self.stats, 'verification': report}, ensure_ascii=False))

    def subtitles(self, timeline):
        def stamp(frame):
            ms = round(frame * 1000 / self.fps)
            return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
        entries = []
        limit = self.c['subtitles'].get('max_chars', 24)
        # max_chars remains a user-facing 720p readability target; wrapping uses
        # approximate glyph width so mixed CJK/Latin text does not split blindly.
        max_units = limit * 2
        max_line_units = 0
        for i, row in enumerate(timeline, 1):
            text = re.sub(r'\s+', ' ', row['text']).strip()
            require(len(text) <= limit * 2, f'{row["id"]}: subtitle exceeds two lines; split narration at real spoken boundaries and reapprove')
            # Both lines retain the same native sentence interval; no guessed word times.
            wrapped = wrap_caption(text, max_units)
            max_line_units = max(max_line_units, *(sum(char_units(ch) for ch in line) for line in wrapped))
            lines = '\n'.join(wrapped)
            subtitle_end = row.get('end_frame', 0)
            if not self.c.get('pacing', {}).get('subtitle_during_pause', False):
                subtitle_end = row.get('subtitle_end_frame', subtitle_end)
            require(subtitle_end >= row['start_frame'], f'{row["id"]}: subtitle interval is negative')
            entries.append(f'{i}\n{stamp(row["start_frame"])} --> {stamp(subtitle_end)}\n{lines}\n')
        sub = self.c['subtitles']
        base_size = float(sub.get('size', 48))
        width_ratio = float(sub.get('max_width_ratio', 0.88))
        safe_width = self.output['width'] * max(0.6, min(width_ratio, 0.95))
        fitted = base_size if not max_line_units else (safe_width * 2 / max_line_units)
        self._subtitle_effective_size = max(float(sub.get('min_size', 28)), min(base_size, fitted))
        return '\n'.join(entries)

    def verify(self, stage):
        self.gate(stage)
        destination = self.root / 'deliverables'
        artifact = destination / (stage + '.mp4')
        timeline = read_json(destination / (stage + '-timeline.json'))
        require(self.state.get(stage + '_render', {}).get('sha256') == file_hash(artifact), 'Artifact changed after render')
        result = self.ff(['-xerror', '-i', artifact, '-map', '0:v:0', '-map', '0:a:0', '-progress', 'pipe:1', '-f', 'null', '-'])
        frames = [int(n) for n in re.findall(r'^frame=(\d+)', result.stdout, re.MULTILINE)]
        require(frames and frames[-1] == timeline['total_frames'], 'Decoded frame count does not match timeline')
        rows = timeline['sentences']
        require(rows[0]['start_frame'] == 0 and all(a['end_frame'] == b['start_frame'] for a,b in zip(rows, rows[1:])), 'Timeline gaps or overlaps')
        require(all(0 <= row.get('subtitle_end_frame', row['end_frame']) <= row['end_frame'] for row in rows),
                'Subtitle interval exceeds its audio interval')
        samples = []
        for i, frame in enumerate(sorted(set([0, timeline['total_frames']//2, timeline['total_frames']-1]))):
            p = destination / f'{stage}-check-{i+1}.png'
            self.ff(['-ss', frame/self.fps, '-i', artifact, '-frames:v', '1', '-update', '1', p])
            require(p.is_file(), 'Failed to extract verification frame')
            samples.append(str(p))
        music_checks = []
        for m in self.c.get('music', []):
            mp = self.path_for(m['path'])
            # volumedetect reports mean level at info verbosity; the regular ff
            # wrapper intentionally hides it, so probe this read-only check directly.
            probe = run([self.ffmpeg, '-hide_banner', '-loglevel', 'info', '-nostdin', '-i', mp,
                         '-af', 'volumedetect', '-f', 'null', '-'])
            match = re.search(r'mean_volume:\s*(-?[0-9.]+) dB', probe.stderr)
            mean_db = float(match.group(1)) if match else None
            music_checks.append({'path': str(mp), 'configured_volume': m.get('volume', .22),
                                 'source_mean_db': mean_db,
                                 'audibility_warning': m.get('volume', .22) < .15})
        report = {'decode_passed': True, 'decoded_frames': frames[-1], 'duration_seconds': frames[-1]/self.fps,
                  'timeline_contiguous': True, 'sample_frames': samples, 'visual_review': 'pending agent/user review',
                  'listening_review': 'pending agent/user review', 'music_checks': music_checks, 'cache': self.stats}
        write_json(destination / (stage + '-verification.json'), report)
        return report


def initialize(path, source):
    path = Path(path).resolve()
    require(not path.exists(), 'Project already exists; refusing to overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    storyboard_path = path.parent / 'storyboard.json'
    require(not storyboard_path.exists(), 'Storyboard already exists; refusing to overwrite')
    if source:
        source = Path(source).resolve()
        if source.is_dir():
            candidates = [p for p in source.iterdir() if p.suffix.lower() in ('.md', '.txt') and p.is_file()]
            require(len(candidates) == 1, 'Source directory needs exactly one .txt/.md; otherwise select a file explicitly')
            source = candidates[0]
        text = source.read_text(encoding='utf-8-sig')
        saved = path.parent / ('source' + source.suffix)
        require(not saved.exists(), 'Saved source already exists')
        saved.write_text(text, encoding='utf-8')
    write_json(storyboard_path, {'version': 1,
                                 'creative_brief': {'audience': '', 'platform': '', 'purpose': '',
                                                    'target_duration_seconds': 60, 'narrative_arc': '',
                                                    'visual_style': '', 'pacing': '', 'voice_direction': '',
                                                    'music_direction': '', 'continuity_anchors': [], 'constraints': []},
                                 'shots': [],
                                 'demo': {'shots': [], 'selection_reason': '', 'validation_goals': []}})
    write_json(path, {'version': 1, 'title': path.parent.name, 'script': 'approved-script.txt',
                      'storyboard': 'storyboard.json',
                      'runtime': {'offline': True},
                      'style': {'name': 'custom', 'visual': '', 'tone': ''},
                      'output': {'width': 1280, 'height': 720, 'fps': 30},
                      'voice': {'engine': 'melotts', 'language': 'ZH', 'speaker': 'ZH', 'device': 'cpu', 'speed': 1, 'revision': '1'},
                      'subtitles': {'enabled': True, 'font': 'Microsoft YaHei', 'size': 48, 'min_size': 28, 'max_width_ratio': 0.88, 'margin': 30, 'max_chars': 24},
                      'motion': {'easing': 'smoothstep', 'max_zoom': 0.06},
                      'narration': [], 'shots': [], 'demo': {'shots': []}, 'music': []})
    print('Created ' + str(path) + '; run preflight before drafting the spoken script or production plan.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'paths', 'configure', 'remember-runtime', 'doctor', 'preflight', 'check', 'record', 'tts', 'render', 'verify'])
    parser.add_argument('project', help='Project JSON path')
    parser.add_argument('--source', help='Input .txt/.md or directory (init only)')
    parser.add_argument('--stage', choices=['script', 'storyboard', 'demo', 'full'], default='demo')
    parser.add_argument('--quote', help='Actual user approval reply (record only)')
    parser.add_argument('--skip', action='store_true', help='Record an explicitly authorized stage skip')
    parser.add_argument('--ffmpeg', help='Existing FFmpeg executable path')
    for option in ('python', 'nltk-data', 'hf-home', 'hf-hub-cache', 'transformers-cache'):
        parser.add_argument('--' + option, help='User-selected path (configure only)')
    parser.add_argument('--offline', choices=['true', 'false'], help='Model cache offline mode (configure only)')
    args = parser.parse_args()
    if args.command == 'init':
        initialize(args.project, args.source)
        return
    config = read_json(args.project)
    runtime_config = config.get('runtime', {})
    if args.command == 'paths':
        print(json.dumps(path_report(args.project, runtime_config), ensure_ascii=False, indent=2))
        return
    if args.command == 'configure':
        selected = {key: getattr(args, key) for key in ('python', 'ffmpeg', 'nltk_data', 'hf_home', 'hf_hub_cache', 'transformers_cache') if getattr(args, key)}
        updated = update_config(runtime_config, selected)
        if args.offline is not None:
            updated['offline'] = args.offline == 'true'
        validate_paths(resolve_paths(args.project, updated))
        config['runtime'] = updated
        write_json(args.project, config)
        print('Saved user-selected runtime paths. Run preflight before drafting script or production plans.')
        return
    if args.command == 'remember-runtime':
        selected = {key: runtime_config[key] for key in ('python', 'ffmpeg', 'nltk_data', 'hf_home',
                                                         'hf_hub_cache', 'transformers_cache')
                    if key in runtime_config}
        if not selected:
            raise ValueError('Project runtime has no paths to remember; run configure first')
        selected = resolve_paths(args.project, selected, include_global=False, include_environment=False)
        validate_paths(selected)
        readiness = read_json(preflight_path(args.project)) if preflight_path(args.project).is_file() else {}
        require(readiness.get('ok') and readiness.get('fingerprint') == preflight_fingerprint(args.project, config, args.ffmpeg),
                'Run a successful current preflight before remember-runtime')
        profile, _ = write_global_runtime(selected)
        print('Saved validated runtime paths to ' + str(profile))
        return
    relaunch(args.project, runtime_config, args.ffmpeg)
    if args.command in ('doctor', 'preflight'):
        report = doctor(args.project, runtime_config, config.get('voice', {}), args.ffmpeg,
                        deep=args.command == 'preflight')
        if args.command == 'preflight':
            report['fingerprint'] = preflight_fingerprint(args.project, config, args.ffmpeg)
            report['checked_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            write_json(preflight_path(args.project), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report['ok']:
            raise SystemExit(1)
        return
    validation_stage = 'script' if args.stage == 'script' and args.command in ('check', 'record') else 'production'
    project = Project(args.project, args.ffmpeg, validation_stage)
    if args.command == 'check':
        project.require_preflight()
        audit = pronunciation_audit(config.get('narration', []))
        report = {'schema': 'passed', 'pronunciation_audit': audit,
                  'note': 'Polyphone hits require listening confirmation; use sentence.pronunciation for pronunciation-only correction, or tts_text for an engine-specific override.'}
        if validation_stage == 'production':
            report.update({'narration_coverage': 'passed', 'storyboard': project.storyboard_report()})
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == 'record':
        require(args.stage in ('script', 'storyboard', 'demo'), 'Only script, storyboard and demo have approval records')
        project.record(args.stage, args.quote or '', args.skip)
        print('Recorded actual user reply for ' + args.stage)
    else:
        require(args.stage not in ('script', 'storyboard'), 'Use demo or full for media commands')
        if args.command == 'tts':
            print(json.dumps({k: {**v, 'path': str(v['path'])} for k,v in project.voices(args.stage).items()}, ensure_ascii=False))
        elif args.command == 'render':
            project.render(args.stage)
        else:
            print(json.dumps(project.verify(args.stage), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, LookupError, OSError, RuntimeError, wave.Error) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
