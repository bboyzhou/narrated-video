"""Compile authoring data into the renderer-neutral, derived RenderPlan v1."""

import copy
import json
import re
import subprocess

from alignment import resolve_cue, validate_alignment


def _media_duration(ffmpeg, path, media_type):
    if media_type != 'video':
        return None
    result = subprocess.run(
        [ffmpeg, '-hide_banner', '-i', str(path)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=30,
    )
    match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', result.stderr)
    if not match:
        raise ValueError('Cannot determine video duration: ' + str(path))
    hours, minutes, seconds = map(float, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def compile_render_plan(project, stage, selected, voices, timeline):
    """Compile only realized assets and frame-exact timing; never persist runtime state."""
    fps = project.fps
    durations = [sum(voices[sid]['frames'] for sid in shot['narration']) for shot in selected]
    tails = [round(shot.get('transition', 0.3) * fps) if index + 1 < len(selected) else 0
             for index, shot in enumerate(selected)]
    shots = []
    cursor = 0
    for index, shot in enumerate(selected):
        item = {
            'id': shot['id'],
            'start_frame': cursor,
            'duration_frames': durations[index] + tails[index],
            'spoken_frames': durations[index],
            'transition_frames': tails[index],
            'incoming_transition_frames': tails[index - 1] if index else 0,
            'type': shot['type'],
            'asset': str(project.path_for(shot['asset']).resolve()),
            'source_start': shot.get('source_start', 0),
            'loop': shot.get('loop', False),
            'motion': shot.get('motion', 'push'),
            'layers': [],
            'graphics': copy.deepcopy(shot.get('graphics', [])),
            'effects': copy.deepcopy(shot.get('effects', {})),
        }
        source_duration = _media_duration(getattr(project, 'ffmpeg', None), item['asset'], item['type'])
        if source_duration is not None:
            item['source_duration'] = source_duration
        for graphic in item['graphics']:
            for state in graphic.get('states', []):
                cue = state.get('cue')
                if not cue:
                    if state.get('timing_source') != 'manual':
                        raise ValueError('Explicit frame states require timing_source=manual')
                    continue
                sentence_id = cue['sentence']
                if sentence_id not in shot['narration']:
                    raise ValueError('Cue sentence must belong to its shot: ' + sentence_id)
                sentence = project.sentences[sentence_id]
                if not sentence.get('alignment'):
                    raise ValueError('Attach validated narration.alignment for ' + sentence_id)
                row = next(value for value in timeline
                           if value['id'] == sentence_id and value['shot'] == shot['id'])
                alignment = json.loads(
                    project.path_for(sentence['alignment']).read_text(encoding='utf-8'))
                validate_alignment(alignment, sentence['text'], voices[sentence_id]['sha256'],
                                   voices[sentence_id]['duration'])
                state['frame'] = resolve_cue(
                    cue, alignment, sentence['text'], fps, row['start_frame'], cursor)
                state['alignment_provider'] = alignment['provider']
                state['alignment_revision'] = alignment['revision']
                state['alignment_methods'] = sorted({
                    span['method'] for span in alignment['spans']
                    if cue['char_start'] <= span['char_start'] < cue['char_end']
                })
                state['timing_source'] = (
                    'manual' if 'manual' in state['alignment_methods'] else 'aligned')
                state['audio_sha256'] = voices[sentence_id]['sha256']
        for layer in shot.get('layers', []):
            value = copy.deepcopy(layer)
            value['asset'] = str(project.path_for(layer['asset']).resolve())
            source_duration = _media_duration(getattr(project, 'ffmpeg', None), value['asset'], value['type'])
            if source_duration is not None:
                value['source_duration'] = source_duration
            item['layers'].append(value)
        shots.append(item)
        cursor += durations[index]
    return {
        'kind': 'RenderPlan',
        'version': 1,
        'source_project': {
            'kind': 'NarratedProject',
            'version': 1,
            'id': (getattr(getattr(project, 'document', None), 'data', {})
                   .get('project', {}).get('id', 'legacy-project')),
        },
        'stage': stage,
        'fps': fps,
        'width': project.output['width'],
        'height': project.output['height'],
        'total_frames': cursor,
        'motion': copy.deepcopy(project.c.get('motion', {})),
        'shots': shots,
        'captions': copy.deepcopy(timeline),
        'subtitles': copy.deepcopy(project.c.get('subtitles', {})),
        'audio': {
            sid: {
                'path': str(info['path'].resolve()),
                'sha256': info['sha256'],
                'frames': info['frames'],
            }
            for sid, info in voices.items()
            if info.get('path') is not None and info.get('sha256') is not None
        },
        'music': [
            {**copy.deepcopy(row), 'path': str(project.path_for(row['path']).resolve())}
            for row in project.c.get('music', [])
        ],
    }
