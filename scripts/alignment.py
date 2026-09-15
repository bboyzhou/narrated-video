"""Versioned alignment contract: final dry PCM -> original-text spans -> events.

Providers receive request/output paths through argv placeholders. They must map
spoken text back to original display-text offsets; ASR spelling is not a script.
"""
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path


def prepare_requests(project, stage):
    from pipeline import tts_input
    voices = project.voices(stage)
    root = project.work / 'alignment-requests' / stage
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for sid, voice in voices.items():
        sentence = project.sentences[sid]
        request = {'audio': str(voice['path'].resolve()), 'text': sentence['text'],
                   'tts_text': tts_input(sentence), 'duration': voice['duration'],
                   'audio_sha256': voice['sha256'],
                   'text_sha256': hashlib.sha256(sentence['text'].encode('utf-8')).hexdigest()}
        path = root / (sid + '.json')
        path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
        paths.append(str(path))
    return {'requests': paths, 'next': 'Select a pinned local provider; assign validated output to narration[].alignment'}


def map_asr_words(words, text):
    """Strict full-sequence mapping; repeated words are matched by occurrence.

    Punctuation/case are ignored, but substitutions and missing words are not.
    No uniform character-time interpolation or guessed boundary is permitted.
    """
    normalize = lambda s: ''.join(c.lower() for c in s if c.isalnum())
    indices = [i for i,c in enumerate(text) if c.isalnum()]
    tokens = [(w,normalize(w['word'])) for w in words if normalize(w['word'])]
    if ''.join(t for _,t in tokens) != normalize(text):
        raise ValueError('ASR differs from approved text; use a forced-alignment provider or explicit reviewed mapping')
    spans, cursor = [], 0
    for word, token in tokens:
        spans.append({'char_start':indices[cursor], 'char_end':indices[cursor+len(token)-1]+1,
                      'start':word['start'], 'end':word['end'], 'confidence':word.get('probability',0), 'method':'asr_mapped'})
        cursor += len(token)
    return spans


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_alignment(data, text, audio_hash, duration):
    if data.get('version') != 1 or data.get('audio_sha256') != audio_hash:
        raise ValueError('Alignment stale: final audio hash mismatch')
    if data.get('text_sha256') != hashlib.sha256(text.encode('utf-8')).hexdigest():
        raise ValueError('Alignment stale: display text mismatch')
    if not data.get('provider') or not data.get('revision') or data['revision'] in ('main', 'latest'):
        raise ValueError('Alignment needs provider and pinned revision')
    last_char, last_end = 0, 0
    for span in data.get('spans', []):
        a, b = span['char_start'], span['char_end']
        start, end = span['start'], span['end']
        if not (type(a) is int and type(b) is int and last_char <= a < b <= len(text)):
            raise ValueError('Alignment invalid or overlapping text span')
        if not all(type(t) in (int, float) and math.isfinite(t) for t in (start, end)):
            raise ValueError('Alignment times must be finite')
        if not 0 <= last_end <= start < end <= duration:
            raise ValueError('Alignment invalid or overlapping time span')
        if span.get('method') not in ('forced', 'asr_mapped', 'manual'):
            raise ValueError('Alignment span needs measured/manual provenance')
        if not 0 <= span.get('confidence', -1) <= 1:
            raise ValueError('Alignment span confidence required')
        last_char, last_end = b, end
    if not data.get('spans'):
        raise ValueError('Empty alignment')
    return data


def resolve_cue(cue, data, text, fps, sentence_start, shot_start):
    a, b = cue['char_start'], cue['char_end']
    confidence = cue.get('min_confidence', .7)
    if type(confidence) not in (int,float) or not 0 <= confidence <= 1:
        raise ValueError('Cue min_confidence must be 0..1')
    if not (type(a) is int and type(b) is int and 0 <= a < b <= len(text)):
        raise ValueError('Invalid cue character interval')
    matches = [s for s in data['spans'] if s['char_start'] == a]
    if not matches or not any(s['char_end'] == b for s in data['spans']):
        raise ValueError('Cue must match measured token boundaries; no estimated fallback')
    spans = [s for s in data['spans'] if a <= s['char_start'] < b]
    if not spans or spans[-1]['char_end'] != b or any(s['confidence'] < cue.get('min_confidence', .7) for s in spans):
        raise ValueError('Cue missing or low-confidence alignment')
    if cue.get('text') != text[a:b]:
        raise ValueError('Cue text differs from approved text')
    covered = set(i for s in spans for i in range(s['char_start'], s['char_end']))
    if any(i not in covered and text[i].isalnum() for i in range(a,b)):
        raise ValueError('Cue contains unmapped text')
    if any(s['method'] == 'manual' for s in spans) and not cue.get('allow_manual', False):
        raise ValueError('Manual timestamps require cue.allow_manual=true')
    return round(matches[0]['start'] * fps) + sentence_start - shot_start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', help='UTF-8 request JSON: audio, text, tts_text, duration, command, revision')
    parser.add_argument('output')
    args = parser.parse_args()
    request_path, output = Path(args.request).resolve(), Path(args.output).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    audio = (request_path.parent / request['audio']).resolve()
    request['audio'] = str(audio)
    actual_hash = digest_file(audio)
    if request.get('audio_sha256', actual_hash) != actual_hash:
        raise ValueError('Prepared alignment request is stale: audio hash mismatch')
    request['audio_sha256'] = actual_hash
    request['text_sha256'] = hashlib.sha256(request['text'].encode('utf-8')).hexdigest()
    if not request.get('revision') or request['revision'] in ('main', 'latest'):
        raise ValueError('Pinned alignment provider revision required')
    command = request['command']
    if not isinstance(command, list) or not all(isinstance(x,str) for x in command) or not any('{request}' in x for x in command) or not any('{output}' in x for x in command):
        raise ValueError('Provider command requires request and output placeholders')
    prepared = output.with_suffix('.request.json')
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    partial = output.with_suffix('.partial.json')
    if partial.exists():
        raise ValueError('Previous partial exists; inspect it before retrying')
    subprocess.run([x.replace('{request}',str(prepared)).replace('{output}',str(partial)) for x in command],check=True,timeout=request.get('timeout',300))
    data=json.loads(partial.read_text(encoding='utf-8'))
    if digest_file(audio) != request['audio_sha256']:
        raise ValueError('Audio changed during alignment')
    validate_alignment(data,request['text'],request['audio_sha256'],request['duration'])
    if data['revision'] != request['revision']:
        raise ValueError('Provider result revision differs from request')
    partial.replace(output)


if __name__ == '__main__':
    main()
