"""Project and user-scoped runtime paths; no installation or downloads."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave

ENV_PATHS = {'nltk_data': 'NLTK_DATA', 'hf_home': 'HF_HOME',
             'hf_hub_cache': 'HF_HUB_CACHE', 'transformers_cache': 'TRANSFORMERS_CACHE'}
PATH_KEYS = ('python', 'ffmpeg', *ENV_PATHS)
PROFILE_KEYS = PATH_KEYS
ENV_CANDIDATES = {
    'python': ('NARRATED_VIDEO_MELOTTS_PYTHON',),
    'ffmpeg': ('NARRATED_VIDEO_FFMPEG', 'FFMPEG'),
    **{key: (variable,) for key, variable in ENV_PATHS.items()},
}


def global_runtime_path():
    """Return a per-user profile path shared by independent Agent sessions."""
    codex_home = os.environ.get('CODEX_HOME')
    root = Path(codex_home).expanduser() if codex_home else Path.home() / '.codex'
    return root / 'narrated-video' / 'runtime.json'


def read_global_runtime():
    path = global_runtime_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Global narrated-video runtime profile must be a JSON object: ' + str(path))
    return {key: value[key] for key in PROFILE_KEYS if key in value}


def environment_runtime():
    result = {}
    for key, names in ENV_CANDIDATES.items():
        for name in names:
            value = os.environ.get(name)
            if value:
                result[key] = value
                break
    return result


def write_global_runtime(selected):
    current = read_global_runtime()
    updated = update_config(current, selected)
    path = global_runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return path, updated


def resolve_paths(project, config, include_global=True, include_environment=True):
    root = Path(project).resolve().parent
    sources = []
    if include_environment:
        # Resource environment variables are inherited and injected below; do
        # not turn an unrelated stale cache variable into a strict path check.
        sources.append({key: value for key, value in environment_runtime().items()
                        if key in ('python', 'ffmpeg')})
    if include_global:
        sources.append(read_global_runtime())
    sources.append(config or {})
    merged = {}
    for source in sources:
        merged = update_config(merged, source)
    result = {}
    for key in PATH_KEYS:
        value = merged.get(key)
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
            'global_profile': {'path': str(global_runtime_path()), 'exists': global_runtime_path().exists(),
                               'values': read_global_runtime()},
            'candidates': {'current_python': sys.executable, 'path_python': shutil.which('python'),
                           'path_python3': shutil.which('python3'), 'path_ffmpeg': shutil.which('ffmpeg'),
                           **{name: os.environ.get(name) for names in ENV_CANDIDATES.values() for name in names}},
            'note': 'Candidates only. Ask the user to select paths before configuring or remembering a runtime; not a whole-disk search.'}


def doctor(project, config, voice, ffmpeg_override=None, deep=False):
    report = path_report(project, config)
    paths = resolve_paths(project, config)
    ffmpeg = ffmpeg_override or paths.get('ffmpeg') or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    if isinstance(voice, bool):
        voice = {'engine': 'melotts' if voice else 'files'}
    voice = voice or {'engine': 'files'}
    engine = voice.get('engine', 'files')
    checks = []
    def check(name, action):
        try:
            detail = action()
            checks.append({'name': name, 'ok': True, 'detail': detail})
        except Exception as error:
            checks.append({'name': name, 'ok': False, 'detail': str(error)})
    def ffmpeg_runtime():
        if not ffmpeg:
            raise ValueError('FFmpeg not found; select its executable')
        version = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=20, check=True).stdout.splitlines()[0]
        filters = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=20, check=True).stdout
        encoders = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=20, check=True).stdout
        required_filters = ('perspective', 'xfade', 'subtitles', 'loudnorm', 'dynaudnorm',
                            'sidechaincompress', 'alimiter')
        required_encoders = ('libx264', 'aac')
        missing_filters = [name for name in required_filters if not re.search(r'\b' + re.escape(name) + r'\b', filters)]
        missing_encoders = [name for name in required_encoders if not re.search(r'\b' + re.escape(name) + r'\b', encoders)]
        if missing_filters or missing_encoders:
            raise ValueError('FFmpeg lacks required capabilities: filters=' + str(missing_filters) +
                             ', encoders=' + str(missing_encoders))
        return {'version': version, 'filters': list(required_filters), 'encoders': list(required_encoders)}
    check('ffmpeg', ffmpeg_runtime)
    if engine == 'melotts':
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
        if deep:
            def melo_model_cache():
                language = str(voice.get('language', 'ZH'))
                device = str(voice.get('device', 'cpu'))
                speaker = str(voice.get('speaker', 'ZH'))
                code = (
                    "import json,sys\n"
                    "from melo.api import TTS\n"
                    "model=TTS(language=sys.argv[1], device=sys.argv[2])\n"
                    "speaker=sys.argv[3]\n"
                    "assert speaker in model.hps.data.spk2id, 'Unknown MeloTTS speaker: '+speaker\n"
                    "print(json.dumps({'language':sys.argv[1],'device':sys.argv[2],'speaker':speaker}))\n"
                )
                env = os.environ.copy()
                env['HF_HUB_OFFLINE'] = env['TRANSFORMERS_OFFLINE'] = '1'
                result = subprocess.run([sys.executable, '-c', code, language, device, speaker], env=env,
                                        capture_output=True, text=True, encoding='utf-8', errors='replace',
                                        timeout=180)
                if result.returncode:
                    raise ValueError('MeloTTS offline model load failed: ' +
                                     (result.stderr or result.stdout)[-4000:])
                return json.loads(result.stdout.splitlines()[-1])
            check('melotts_model_cache', melo_model_cache)
    elif engine == 'cosyvoice':
        def cosyvoice_configuration():
            command = voice.get('command')
            if not isinstance(command, list) or not command:
                raise ValueError('CosyVoice requires voice.command')
            if '{output}' not in command or ('{text_file}' not in command and '{text}' not in command):
                raise ValueError('CosyVoice command requires {output} and {text_file} or {text}')
            model_path = Path(str(voice.get('model_path', ''))).expanduser()
            if not model_path.is_absolute():
                model_path = Path(project).resolve().parent / model_path
            if not model_path.exists():
                raise ValueError('CosyVoice model_path unavailable: ' + str(model_path))
            return {'model_path': str(model_path.resolve()), 'command': [str(item) for item in command]}
        check('cosyvoice_configuration', cosyvoice_configuration)
        if deep and checks[-1]['ok']:
            def cosyvoice_sample():
                with tempfile.TemporaryDirectory(prefix='narrated-preflight-') as temporary:
                    root = Path(temporary)
                    text_file = root / 'input.txt'
                    output = root / 'output.wav'
                    text = '运行环境测试。'
                    text_file.write_text(text, encoding='utf-8')
                    model_path = Path(str(voice['model_path'])).expanduser()
                    if not model_path.is_absolute():
                        model_path = Path(project).resolve().parent / model_path
                    argv = []
                    for item in voice['command']:
                        value = str(item).replace('{text_file}', str(text_file)).replace('{output}', str(output))
                        value = value.replace('{model_path}', str(model_path.resolve())).replace('{text}', text)
                        argv.append(value)
                    env = os.environ.copy()
                    env['HF_HUB_OFFLINE'] = env['TRANSFORMERS_OFFLINE'] = '1'
                    result = subprocess.run(argv, cwd=str(Path(project).resolve().parent), env=env,
                                            capture_output=True, text=True, encoding='utf-8',
                                            errors='replace', timeout=180)
                    if result.returncode:
                        raise ValueError('CosyVoice preflight failed: ' +
                                         (result.stderr or result.stdout)[-4000:])
                    if not output.is_file() or output.stat().st_size == 0:
                        raise ValueError('CosyVoice preflight did not create a WAV')
                    with wave.open(str(output), 'rb') as audio:
                        if audio.getnframes() <= 0 or audio.getcomptype() != 'NONE':
                            raise ValueError('CosyVoice preflight requires nonempty PCM WAV output')
                    return {'sample': 'passed', 'format': 'PCM WAV'}
            check('cosyvoice_sample', cosyvoice_sample)
    elif engine != 'files':
        checks.append({'name': 'voice_engine', 'ok': False, 'detail': 'Unsupported voice.engine: ' + str(engine)})
    report.update({'checks': checks, 'ok': all(c['ok'] for c in checks),
                   'mode': 'preflight' if deep else 'doctor',
                   'limits': ('Offline model load/sample completed; no media assets were produced.' if deep else
                              'No TTS model import, model download or synthesis. Run preflight before creative planning.')})
    return report
