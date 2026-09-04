"""Project-scoped runtime paths; no installation or persistent environment changes."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ENV_PATHS = {'nltk_data': 'NLTK_DATA', 'hf_home': 'HF_HOME',
             'hf_hub_cache': 'HF_HUB_CACHE', 'transformers_cache': 'TRANSFORMERS_CACHE'}
PATH_KEYS = ('python', 'ffmpeg', *ENV_PATHS)


def resolve_paths(project, config):
    root = Path(project).resolve().parent
    result = {}
    for key in PATH_KEYS:
        value = config.get(key)
        if value:
            if not isinstance(value, str):
                raise ValueError('runtime.' + key + ' must be a path string')
            path = Path(value).expanduser()
            result[key] = str((root / path).resolve() if not path.is_absolute() else path.resolve())
    return result


def validate_paths(paths):
    for key, value in paths.items():
        valid = Path(value).is_file() if key in ('python', 'ffmpeg') else Path(value).is_dir()
        if not valid:
            raise ValueError(f'runtime.{key} path unavailable: {value}; select an existing path, no automatic fallback')


def update_config(current, selected):
    updated = {**current, **selected}
    if 'hf_home' in selected:
        # Selecting a new unified root must not keep old split-cache overrides.
        for key in ('hf_hub_cache', 'transformers_cache'):
            if key not in selected:
                updated.pop(key, None)
    return updated


def launch_environment(project, config, ffmpeg_override=None):
    if ffmpeg_override:
        config = {**config, 'ffmpeg': str(Path(ffmpeg_override).resolve())}
    paths = resolve_paths(project, config)
    validate_paths(paths)
    env = os.environ.copy()
    for key, variable in ENV_PATHS.items():
        if key in paths:
            env[variable] = paths[key]
    # HF_HOME has to take effect even when the caller inherited another cache root.
    if 'hf_home' in paths and 'hf_hub_cache' not in paths:
        env['HF_HUB_CACHE'] = str(Path(paths['hf_home']) / 'hub')
    if 'hf_home' in paths and 'transformers_cache' not in paths:
        env['TRANSFORMERS_CACHE'] = env['HF_HUB_CACHE']
    if 'offline' in config:
        if not isinstance(config['offline'], bool):
            raise ValueError('runtime.offline must be true or false')
        env['HF_HUB_OFFLINE'] = env['TRANSFORMERS_OFFLINE'] = '1' if config['offline'] else '0'
    env['PYTHONUTF8'] = '1'
    return paths, env


def relaunch(project, config, ffmpeg_override=None):
    paths, env = launch_environment(project, config, ffmpeg_override)
    python = paths.get('python', sys.executable)
    if os.path.normcase(str(Path(python).resolve())) != os.path.normcase(str(Path(sys.executable).resolve())) or env != os.environ:
        # Child receives selected paths before NLTK/Transformers imports; no global settings.
        marker = json.dumps([str(Path(project).resolve()), paths], sort_keys=True)
        if os.environ.get('NARRATED_VIDEO_LAUNCH') == marker:
            raise ValueError('Selected Python does not resolve to the expected interpreter; check runtime.python')
        env['NARRATED_VIDEO_LAUNCH'] = marker
        raise SystemExit(subprocess.run([python, str(Path(__file__).with_name('pipeline.py')), *sys.argv[1:]], env=env).returncode)


def path_report(project, config):
    paths = resolve_paths(project, config)
    return {'configured': {k: {'path': p, 'exists': Path(p).exists()} for k,p in paths.items()},
            'candidates': {'current_python': sys.executable, 'path_python': shutil.which('python'),
                           'path_ffmpeg': shutil.which('ffmpeg'), 'FFMPEG': os.environ.get('FFMPEG'),
                           **{key: os.environ.get(variable) for key,variable in ENV_PATHS.items()}},
            'note': 'Candidates only. Ask the user to select paths before configuring a new project; not a whole-disk search.'}


def doctor(project, config, needs_tts, ffmpeg_override=None):
    report = path_report(project, config)
    paths = resolve_paths(project, config)
    ffmpeg = ffmpeg_override or paths.get('ffmpeg') or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    checks = []
    def check(name, action):
        try:
            detail = action()
            checks.append({'name': name, 'ok': True, 'detail': detail})
        except Exception as error:
            checks.append({'name': name, 'ok': False, 'detail': str(error)})
    def ff_version():
        if not ffmpeg:
            raise ValueError('FFmpeg not found; select its executable')
        result = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20, check=True)
        return result.stdout.splitlines()[0]
    check('ffmpeg', ff_version)
    if needs_tts:
        def melo_module():
            spec = importlib.util.find_spec('melo')
            if spec is None:
                raise ValueError('MeloTTS module not found in the selected Python')
            return spec.origin
        check('melotts_module', melo_module)
        def nltk_resources():
            import nltk
            from nltk.corpus import cmudict
            found = {name: str(nltk.data.find(name)) for name in ('corpora/cmudict.zip', 'taggers/averaged_perceptron_tagger.zip')}
            return {'paths': found, 'dictionary_entries': len(cmudict.entries())}
        check('nltk_resources', nltk_resources)
    report.update({'checks': checks, 'ok': all(c['ok'] for c in checks),
                   'limits': 'No TTS model import, model download or synthesis. Run an approved short sample to validate model loading and voice output.'})
    return report
