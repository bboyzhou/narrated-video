#!/usr/bin/env python3
"""Config-driven image narration pipeline. Python standard library + FFmpeg.

Run --help and read ../references/project.md. No dependency installation.
"""
import argparse
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
from runtime import resolve_paths, validate_paths, relaunch, path_report, doctor, update_config

VERSION = 1


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


class Project:
    def __init__(self, path, ffmpeg=None):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.c = read_json(self.path)
        self.work = self.root / '.narrated-video'
        self.cache = self.work / 'cache'
        self.state_path = self.work / 'state.json'
        self.state = read_json(self.state_path) if self.state_path.exists() else {}
        self.runtime = resolve_paths(self.path, self.c.get('runtime', {}))
        self.ffmpeg = str(Path(ffmpeg).resolve()) if ffmpeg else self.runtime.get('ffmpeg') or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
        self.stats = {'rendered': 0, 'reused': 0}
        self.validate()

    def path_for(self, value):
        p = Path(value)
        return p.resolve() if p.is_absolute() else (self.root / p).resolve()

    def validate(self):
        c = self.c
        require(c.get('version') == VERSION, 'Unsupported project version')
        self.output = c['output']
        self.fps = self.output['fps']
        require(type(self.fps) is int and 1 <= self.fps <= 60, 'fps must be an integer in 1..60')
        for k in ('width', 'height'):
            require(type(self.output[k]) is int and self.output[k] >= 64 and self.output[k] % 2 == 0, k + ' must be even and >=64')
        require(c['narration'] and c['shots'], 'Fill narration and shots first')
        self.sentences = {s['id']: s for s in c['narration']}
        self.shots = {s['id']: s for s in c['shots']}
        require(len(self.sentences) == len(c['narration']) and len(self.shots) == len(c['shots']), 'Duplicate IDs')
        for item in c['narration'] + c['shots']:
            require(re.fullmatch(r'[A-Za-z0-9_-]+', item['id']), 'IDs must use ASCII letters, digits, _ or -')
        for sentence in c['narration']:
            require(isinstance(sentence['text'], str) and compact(sentence['text']), 'Empty narration text')
        text = self.path_for(c['script']).read_text(encoding='utf-8-sig')
        require(compact(text) == compact(''.join(s['text'] for s in c['narration'])), 'Narration must match the approved plain spoken script exactly (except whitespace)')
        covered = []
        for shot in c['shots']:
            require(shot['type'] == 'image', 'Only image assets are implemented; video requires an adapter')
            require(shot['narration'], 'Each shot needs narration IDs')
            covered.extend(shot['narration'])
            require(shot.get('motion', 'push') in ('still', 'push', 'pull', 'pan-left', 'pan-right'), 'Unsupported motion')
            require(0 <= shot.get('transition', 0.3) <= 2, 'transition must be 0..2 seconds')
        require(covered == list(self.sentences), 'Shots must cover narration once, in order, without gaps')
        demo = c['demo']['shots']
        require(demo and all(s in self.shots for s in demo), 'Demo must reference existing shots')
        positions = [list(self.shots).index(s) for s in demo]
        require(positions == list(range(positions[0], positions[0] + len(positions))), 'Demo shots must be consecutive and ordered')
        voice = c['voice']
        require(voice['engine'] in ('files', 'melotts', 'cosyvoice'), 'voice.engine must be files, melotts or cosyvoice')
        if voice['engine'] == 'cosyvoice':
            require(voice.get('provider', 'cosyvoice').lower() == 'cosyvoice', 'cosyvoice engine requires provider=cosyvoice')
            require(isinstance(voice.get('command'), list) and voice['command'],
                    'CosyVoice requires voice.command: an argv list with {text_file} and {output} placeholders')
            require('{output}' in voice['command'] and ('{text_file}' in voice['command'] or '{text}' in voice['command']),
                    'CosyVoice command must include {output} and {text_file} or {text}')
            require(voice.get('model') and voice.get('model_path'), 'CosyVoice requires model and model_path')
            require(voice.get('license'), 'CosyVoice requires model license notes')
            require(self.path_for(voice['model_path']).exists(), 'CosyVoice model_path unavailable: ' + str(voice['model_path']))
        require(0.1 <= voice.get('speed', 1) <= 3, 'voice.speed must be 0.1..3')
        sub = c['subtitles']
        require(re.fullmatch(r'[\w -]+', sub['font'], re.UNICODE), 'Use a plain font family name')
        require(8 <= sub.get('size', 24) <= 120, 'Subtitle size must be 8..120 at 720p')
        require(5 <= sub.get('max_chars', 24) <= 60, 'Subtitle max_chars must be 5..60')
        for sentence in c['narration']:
            require(len(re.sub(r'\s+', ' ', sentence['text']).strip()) <= sub.get('max_chars', 24) * 2,
                    sentence['id'] + ': subtitle exceeds two lines; split at real spoken boundaries')
        require(c['demo'].get('start_seconds', 0) >= 0, 'Demo start_seconds cannot be negative')
        for music in c.get('music', []):
            require(music['end'] > music['start'] >= 0, 'Invalid music interval')
            require(0 <= music.get('volume', 0.15) <= 1, 'Music volume must be 0..1')
            require(music.get('fade_in', 1) >= 0 and music.get('fade_out', 1) >= 0, 'Negative music fade')
            require(music.get('source') and music.get('license'), 'Music needs source and license notes')
        mix = c.get('mix', {})
        require(-30 <= float(mix.get('music_relative_db', -12)) <= 0, 'music_relative_db must be -30..0 dB')

    def selected(self, stage):
        return [self.shots[s] for s in self.c['demo']['shots']] if stage == 'demo' else self.c['shots']

    def script_key(self):
        return digest([{'id': s['id'], 'text': s['text']} for s in self.c['narration']])

    def asset(self, value):
        p = self.path_for(value)
        return {'path': str(p), 'sha256': file_hash(p) if p.is_file() else None}

    def demo_key(self):
        shots = self.selected('demo')
        voices = []
        for shot in shots:
            for sid in shot['narration']:
                sentence = self.sentences[sid]
                if sentence.get('audio'):
                    voices.append(self.asset(sentence['audio']))
        return digest({'script': self.script_key(), 'style': self.c['style'], 'voice': self.c['voice'],
                       'output': self.output, 'subtitles': self.c['subtitles'], 'shots': shots, 'demo': self.c['demo'],
                       'images': [self.asset(s['asset']) for s in shots], 'voices': voices,
                       'music': [(m, self.asset(m['path'])) for m in self.c.get('music', [])],
                       'mix': self.c.get('mix', {}),
                       'runtime': self.c.get('runtime', {}),
                       'renderer': [file_hash(__file__), file_hash(Path(__file__).with_name('runtime.py'))]})

    def gate(self, stage):
        record = self.state.get('script', {})
        require(record.get('fingerprint') == self.script_key(), 'Script approval missing or stale; obtain user approval and record it')
        if stage == 'full':
            require(self.state.get('demo', {}).get('fingerprint') == self.demo_key(), 'Demo approval missing or stale; render and approve a new Demo')

    def record(self, stage, quote, skip=False):
        require(quote.strip(), 'Record the actual user reply')
        if stage == 'script':
            key = self.script_key()
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
        require(self.ffmpeg, 'FFmpeg not found; pass --ffmpeg or set FFMPEG. No automatic installation.')
        return run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *args], cwd)

    def cached(self, kind, inputs, suffix, producer):
        key = digest({'kind': kind, 'inputs': inputs, 'runtime': self.c.get('runtime', {}), 'ffmpeg': self.ffmpeg,
                      'renderer': [file_hash(__file__), file_hash(Path(__file__).with_name('runtime.py'))]})
        target = self.cache / (key + suffix)
        stamp = self.cache / (key + '.json')
        self.cache.mkdir(parents=True, exist_ok=True)
        if target.is_file() and stamp.is_file() and read_json(stamp).get('sha256') == file_hash(target):
            self.stats['reused'] += 1
            return target
        temporary = self.cache / (key + '.partial' + suffix)
        producer(temporary)
        require(temporary.is_file() and temporary.stat().st_size > 0, 'Empty cache output')
        temporary.replace(target)
        write_json(stamp, {'sha256': file_hash(target), 'inputs': inputs})
        self.stats['rendered'] += 1
        return target

    def voices(self, stage):
        self.gate(stage)
        selected_ids = [sid for shot in self.selected(stage) for sid in shot['narration']]
        result = {}
        model = None
        for sid in selected_ids:
            sentence = self.sentences[sid]
            if sentence.get('audio'):
                p = self.path_for(sentence['audio'])
                require(p.is_file(), 'Missing audio: ' + str(p))
            else:
                require(self.c['voice']['engine'] in ('melotts', 'cosyvoice'), 'Missing per-sentence WAV for ' + sid)
                config = self.c['voice']
                def synthesize(target):
                    nonlocal model
                    if config['engine'] == 'cosyvoice':
                        text_file = target.with_suffix('.txt')
                        text_file.write_text(sentence['text'], encoding='utf-8')
                        argv = []
                        for arg in config['command']:
                            value = str(arg)
                            value = value.replace('{text_file}', str(text_file)).replace('{output}', str(target))
                            value = value.replace('{model_path}', str(self.path_for(config['model_path'])))
                            value = value.replace('{text}', sentence['text'])
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
                    model.tts_to_file(sentence['text'], model.hps.data.spk2id[speaker], str(target),
                                      speed=config.get('speed', 1), quiet=True)
                p = self.cached('tts', {'text': sentence['text'], 'voice': config}, '.wav', synthesize)
            with wave.open(str(p), 'rb') as w:
                duration = w.getnframes() / w.getframerate()
                require(duration > 0 and w.getcomptype() == 'NONE', 'Use nonempty PCM WAV files')
            frames = math.ceil(duration * self.fps - 1e-8)
            result[sid] = {'path': p, 'duration': duration, 'frames': frames, 'sha256': file_hash(p)}
        return result

    def render(self, stage):
        self.gate(stage)
        selected = self.selected(stage)
        for shot in selected:
            require(self.path_for(shot['asset']).is_file(), 'Missing image: ' + shot['asset'])
        for m in self.c.get('music', []):
            require(self.path_for(m['path']).is_file(), 'Missing music: ' + m['path'])
        voices = self.voices(stage)
        w, h, fps = self.output['width'], self.output['height'], self.fps
        durations = [sum(voices[s]['frames'] for s in shot['narration']) for shot in selected]
        tails = [round(s.get('transition', 0.3) * fps) if i + 1 < len(selected) else 0 for i, s in enumerate(selected)]
        for i, t in enumerate(tails[:-1]):
            require(t < min(durations[i], durations[i + 1]), 'Transition must be shorter than both neighboring shots')
        raw = []
        for i, shot in enumerate(selected):
            image = self.path_for(shot['asset'])
            n = durations[i] + tails[i]
            motion = shot.get('motion', 'push')
            progress = f'on/{max(n-1, 1)}'
            z = {'still': '1', 'push': f'1+0.06*{progress}', 'pull': f'1.06-0.06*{progress}',
                 'pan-left': '1.06', 'pan-right': '1.06'}[motion]
            x = f'(iw-iw/zoom)*{progress}' if motion == 'pan-right' else f'(iw-iw/zoom)*(1-{progress})' if motion == 'pan-left' else 'iw/2-iw/zoom/2'
            vf = f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},zoompan=z='{z}':x='{x}':y='ih/2-ih/zoom/2':d={n}:s={w}x{h}:fps={fps},setsar=1"
            raw.append(self.cached('image-motion', [file_hash(image), vf], '.mp4',
                                   lambda p, image=image, vf=vf, n=n: self.ff(['-i', image, '-vf', vf, '-frames:v', n, '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', p])))
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
                                 'start_frame': cursor, 'end_frame': cursor + info['frames'], 'audio_duration': info['duration']})
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
                                                             'audio': {sid: {**v, 'path': str(v['path'])} for sid, v in voices.items()},
                                                             'music': [{**m, **self.asset(m['path'])} for m in self.c['music']]})
        shutil.copyfile(self.path, destination / 'project.json')
        write_json(destination / 'approvals.json', {k: self.state.get(k) for k in ('script', 'demo')})
        self.state[stage + '_render'] = {'fingerprint': self.demo_key() if stage == 'demo' else digest(self.c),
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
            entries.append(f'{i}\n{stamp(row["start_frame"])} --> {stamp(row["end_frame"])}\n{lines}\n')
        sub = self.c['subtitles']
        base_size = float(sub.get('size', 48))
        width_ratio = float(sub.get('max_width_ratio', 0.88))
        safe_width = self.output['width'] * max(0.6, min(width_ratio, 0.95))
        fitted = base_size if not max_line_units else (safe_width * 2 / max_line_units)
        self._subtitle_effective_size = max(float(sub.get('min_size', 28)), min(base_size, fitted))
        return '\n'.join(entries)

    def verify(self, stage):
        destination = self.root / 'deliverables'
        artifact = destination / (stage + '.mp4')
        timeline = read_json(destination / (stage + '-timeline.json'))
        require(self.state.get(stage + '_render', {}).get('sha256') == file_hash(artifact), 'Artifact changed after render')
        result = self.ff(['-xerror', '-i', artifact, '-map', '0:v:0', '-map', '0:a:0', '-progress', 'pipe:1', '-f', 'null', '-'])
        frames = [int(n) for n in re.findall(r'^frame=(\d+)', result.stdout, re.MULTILINE)]
        require(frames and frames[-1] == timeline['total_frames'], 'Decoded frame count does not match timeline')
        rows = timeline['sentences']
        require(rows[0]['start_frame'] == 0 and all(a['end_frame'] == b['start_frame'] for a,b in zip(rows, rows[1:])), 'Timeline gaps or overlaps')
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
    write_json(path, {'version': 1, 'title': path.parent.name, 'script': 'approved-script.txt',
                      'runtime': {'offline': True},
                      'style': {'name': 'custom', 'visual': '', 'tone': ''},
                      'output': {'width': 1280, 'height': 720, 'fps': 30},
                      'voice': {'engine': 'melotts', 'language': 'ZH', 'speaker': 'ZH', 'device': 'cpu', 'speed': 1, 'revision': '1'},
                      'subtitles': {'enabled': True, 'font': 'Microsoft YaHei', 'size': 48, 'min_size': 28, 'max_width_ratio': 0.88, 'margin': 30, 'max_chars': 24},
                      'narration': [], 'shots': [], 'demo': {'shots': []}, 'music': []})
    print('Created ' + str(path) + '; prepare and approve the spoken script before production.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'paths', 'configure', 'doctor', 'check', 'record', 'tts', 'render', 'verify'])
    parser.add_argument('project', help='Project JSON path')
    parser.add_argument('--source', help='Input .txt/.md or directory (init only)')
    parser.add_argument('--stage', choices=['script', 'demo', 'full'], default='demo')
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
        print('Saved user-selected runtime paths. Run doctor to verify availability.')
        return
    relaunch(args.project, runtime_config, args.ffmpeg)
    if args.command == 'doctor':
        report = doctor(args.project, runtime_config, config.get('voice', {}).get('engine') == 'melotts', args.ffmpeg)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report['ok']:
            raise SystemExit(1)
        return
    project = Project(args.project, args.ffmpeg)
    if args.command == 'check':
        print('Project schema and narration coverage passed; this does not imply approvals or media verification.')
    elif args.command == 'record':
        require(args.stage in ('script', 'demo'), 'Only script and demo have approval records')
        project.record(args.stage, args.quote or '', args.skip)
        print('Recorded actual user reply for ' + args.stage)
    else:
        require(args.stage != 'script', 'Use demo or full for media commands')
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
