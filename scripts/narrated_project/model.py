"""Canonical NarratedProject v1 model with lossless legacy normalization."""

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from .io import read_json, write_json
from .validate import validate_project


KIND = 'NarratedProject'
VERSION = 1
SCHEMA_URI = 'https://openai.local/narrated-video/narrated-project-v1.schema.json'


def is_narrated_project(value):
    return isinstance(value, dict) and value.get('kind') == KIND


def _project_id(title, root):
    value = re.sub(r'[^A-Za-z0-9_-]+', '-', str(title or root.name)).strip('-').lower()
    return value or 'narrated-project'


def _legacy_storyboard(path, config):
    value = config.get('storyboard')
    if not isinstance(value, str) or not value.strip():
        return {'version': 1, 'creative_brief': {}, 'shots': [], 'demo': {}}
    target = Path(value)
    if not target.is_absolute():
        target = path.parent / target
    return read_json(target) if target.is_file() else {
        'version': 1, 'creative_brief': {}, 'shots': [], 'demo': {},
    }


def _canonical_from_legacy(path, config):
    storyboard = _legacy_storyboard(path, config)
    planned = {row.get('id'): row for row in storyboard.get('shots', []) if isinstance(row, dict)}
    shots = []
    for execution in config.get('shots', []):
        row = copy.deepcopy(planned.get(execution.get('id'), {}))
        row.update(copy.deepcopy(execution))
        row['transition_seconds'] = row.pop(
            'transition', row.get('transition_seconds', 0.3))
        shots.append(row)
    demo = copy.deepcopy(storyboard.get('demo') or {})
    demo.update(copy.deepcopy(config.get('demo') or {}))
    demo.setdefault('selection_reason', '')
    demo.setdefault('validation_goals', [])
    video = copy.deepcopy(config.get('video_generation') or {})
    video.setdefault('enabled', False)
    video.setdefault('provider', 'skyreels_v2')
    video.setdefault('profile', 'balanced')
    video.setdefault('runtime', {'type': 'auto'})
    video.setdefault('policy', 'highlights')
    video.setdefault('providers', {})
    return {
        '$schema': SCHEMA_URI,
        'kind': KIND,
        'version': VERSION,
        'project': {
            'id': config.get('id') or _project_id(config.get('title'), path.parent),
            'title': config.get('title') or path.parent.name,
        },
        'sources': {'script': config.get('script', 'approved-script.txt')},
        'creative': {
            'brief': copy.deepcopy(storyboard.get('creative_brief') or {}),
            'style': copy.deepcopy(config.get('style') or {'name': 'custom', 'visual': '', 'tone': ''}),
        },
        'providers': {
            'image': copy.deepcopy(config.get('image_generation') or {'default': 'external', 'providers': {}}),
            'tts': copy.deepcopy(config.get('voice') or {'engine': 'files'}),
            'i2v': video,
        },
        'assets': {
            **({'library': config['asset_library']} if config.get('asset_library') else {}),
        },
        'timeline': {
            'narration': copy.deepcopy(config.get('narration') or []),
            'shots': shots,
            'demo': demo,
            'music': copy.deepcopy(config.get('music') or []),
        },
        'render': {
            'target': {
                'adapter': (config.get('renderer') or {}).get('engine', 'ffmpeg'),
                'fallback': (config.get('renderer') or {}).get('fallback', 'ffmpeg'),
            },
            'output': copy.deepcopy(config.get('output') or {'width': 1280, 'height': 720, 'fps': 30}),
            'pacing': copy.deepcopy(config.get('pacing') or {}),
            'subtitles': copy.deepcopy(config.get('subtitles') or {}),
            'motion': copy.deepcopy(config.get('motion') or {}),
            'mix': copy.deepcopy(config.get('mix') or {}),
        },
        **({'extensions': copy.deepcopy(config['extensions'])} if config.get('extensions') else {}),
    }


def runtime_config_for(path, raw=None):
    path = Path(path).resolve()
    raw = read_json(path) if raw is None else raw
    if not is_narrated_project(raw):
        return copy.deepcopy(raw.get('runtime') or {})
    sidecar = path.parent / '.narrated-video' / 'runtime.json'
    return read_json(sidecar) if sidecar.is_file() else {}


def save_runtime_config(path, value):
    path = Path(path).resolve()
    raw = read_json(path)
    if is_narrated_project(raw):
        target = path.parent / '.narrated-video' / 'runtime.json'
        write_json(target, value)
        return target
    raw['runtime'] = value
    write_json(path, raw)
    return path


@dataclass
class NarratedProject:
    path: Path
    data: dict
    source_format: str
    legacy_raw: dict

    @classmethod
    def load(cls, path, validate_stage=None):
        path = Path(path).resolve()
        raw = read_json(path)
        if is_narrated_project(raw):
            data = copy.deepcopy(raw)
            source_format = 'v1'
        else:
            data = _canonical_from_legacy(path, raw)
            source_format = 'legacy'
        item = cls(path=path, data=data, source_format=source_format, legacy_raw=raw)
        if validate_stage:
            item.validate(validate_stage)
        return item

    @property
    def root(self):
        return self.path.parent

    def validate(self, stage='production'):
        return validate_project(self.data, stage)

    def legacy_view(self):
        """Return the temporary compatibility view consumed by the old pipeline."""
        data = self.data
        render = data['render']
        timeline = data['timeline']
        target = render['target']
        shots = []
        for row in timeline.get('shots', []):
            shot = copy.deepcopy(row)
            shot['transition'] = shot.pop('transition_seconds', 0.3)
            shots.append(shot)
        value = {
            'version': 1,
            'title': data['project']['title'],
            'script': data['sources']['script'],
            'storyboard': self.legacy_raw.get('storyboard', 'storyboard.json'),
            'runtime': runtime_config_for(self.path, self.legacy_raw),
            'style': copy.deepcopy(data['creative']['style']),
            'output': copy.deepcopy(render['output']),
            'voice': copy.deepcopy(data['providers']['tts']),
            'pacing': copy.deepcopy(render.get('pacing') or {}),
            'subtitles': copy.deepcopy(render.get('subtitles') or {}),
            'motion': copy.deepcopy(render.get('motion') or {}),
            'renderer': {'engine': target['adapter'], 'fallback': target.get('fallback', 'none')},
            'video_generation': copy.deepcopy(data['providers']['i2v']),
            'narration': copy.deepcopy(timeline.get('narration') or []),
            'shots': shots,
            'demo': copy.deepcopy(timeline.get('demo') or {}),
            'music': copy.deepcopy(timeline.get('music') or []),
            'mix': copy.deepcopy(render.get('mix') or {}),
        }
        if data.get('assets', {}).get('library'):
            value['asset_library'] = data['assets']['library']
        return value

    def storyboard_view(self):
        shots = []
        for row in self.data['timeline'].get('shots', []):
            shot = copy.deepcopy(row)
            shot.pop('asset', None)
            shot.pop('generated_video', None)
            shots.append(shot)
        return {
            'version': 1,
            'creative_brief': copy.deepcopy(self.data['creative']['brief']),
            'shots': shots,
            'demo': copy.deepcopy(self.data['timeline'].get('demo') or {}),
        }

    def save(self, path=None):
        target = Path(path).resolve() if path else self.path
        write_json(target, self.data)
        return target

    def set_generated_video(self, shot_id, result):
        for shot in self.data['timeline']['shots']:
            if shot.get('id') == shot_id:
                shot['generated_video'] = copy.deepcopy(result)
                return
        raise KeyError('Unknown shot: ' + shot_id)


def load_project(path, validate_stage=None):
    return NarratedProject.load(path, validate_stage)


def migrate_project(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Migration output already exists; refusing to overwrite: ' + str(output))
    if output.parent != source.parent:
        raise ValueError('Migration output must stay beside the source so relative assets remain valid')
    project = NarratedProject.load(source)
    if project.source_format == 'v1':
        raise ValueError('Project is already NarratedProject v1')
    project.validate('production')
    project.save(output)
    return NarratedProject.load(output)
