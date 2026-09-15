"""Small, deterministic bridge from the Python timeline to Remotion.

The adapter owns only visual rendering.  Audio mastering and final muxing stay in
the existing FFmpeg pipeline so that Remotion remains an optional renderer.
"""
import hashlib
import json
import shutil
import subprocess
import copy
from pathlib import Path


def preflight(runtime):
    root = Path(__file__).resolve().parents[1] / 'renderers' / 'remotion'
    try:
        if not all(runtime.get(k) and Path(runtime[k]).is_file() for k in ('node', 'browser')):
            raise ValueError('Select explicit existing runtime.node and runtime.browser')
        expected = json.loads((root / 'package.json').read_text(encoding='utf-8'))['dependencies']
        for name, version in expected.items():
            actual = json.loads((root / 'node_modules' / name / 'package.json').read_text(encoding='utf-8'))['version']
            if actual != version:
                raise ValueError('Installed package version differs from pin: ' + name)
        subprocess.run([runtime['node'], '--input-type=module', '-e',
                        "import '@remotion/bundler'; import '@remotion/renderer'; import 'remotion';"],
                       cwd=root, check=True, capture_output=True, timeout=30)
        return {'ok': True, 'detail': 'Local packages and executable paths available; actual browser rendering still requires smoke'}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {'ok': False, 'detail': str(error)}


def renderer_identity():
    root = Path(__file__).resolve().parents[1] / 'renderers' / 'remotion'
    paths = [Path(__file__), Path(__file__).with_name('alignment.py')]
    paths += [root / 'package-lock.json', *sorted((root / 'src').glob('*')), *sorted((root / 'scripts').glob('*.mjs'))]
    return hashlib.sha256(''.join(_hash(p) for p in paths if p.is_file()).encode()).hexdigest()


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _stage_asset(source, asset_root):
    source = Path(source)
    digest = _hash(source)
    target = asset_root / (digest + source.suffix.lower())
    if not target.is_file() or _hash(target) != digest:
        shutil.copyfile(source, target)
    return target.name


def prepare_plan(plan, context):
    """Translate renderer-neutral absolute assets into a Remotion-local plan."""
    value = copy.deepcopy(plan)
    asset_root = context.work / 'remotion-assets'
    asset_root.mkdir(parents=True, exist_ok=True)
    for shot in value['shots']:
        shot['asset'] = _stage_asset(shot['asset'], asset_root)
        for layer in shot.get('layers', []):
            layer['asset'] = _stage_asset(layer['asset'], asset_root)
    value['asset_root'] = str(asset_root)
    value['browser_executable'] = context.runtime.get('browser') or context.runtime.get('chrome')
    return value


def build_render_plan(project, stage, selected, voices, timeline):
    """Backward-compatible helper returning the Remotion-prepared derived plan."""
    from narrated_project.compiler import compile_render_plan
    return prepare_plan(compile_render_plan(project, stage, selected, voices, timeline), project)


def render(plan_path, output_path, node='node'):
    """Render one plan using the pinned local Remotion project."""
    adapter_root = Path(__file__).resolve().parents[1] / 'renderers' / 'remotion'
    package = adapter_root / 'package.json'
    node_modules = adapter_root / 'node_modules'
    if not package.is_file() or not node_modules.is_dir():
        raise RuntimeError('Remotion dependencies are not installed; run npm ci in renderers/remotion')
    script = adapter_root / 'scripts' / 'render.mjs'
    command = [node, str(script), '--plan', str(plan_path), '--output', str(output_path)]
    completed = subprocess.run(command, cwd=str(adapter_root), text=True,
                               capture_output=True, encoding='utf-8', timeout=1800)
    if completed.returncode:
        qa_path = Path(str(plan_path).removesuffix('.json') + '-qa.json')
        if qa_path.is_file():
            qa = json.loads(qa_path.read_text(encoding='utf-8'))
            if qa.get('status') == 'failed':
                raise ValueError('Render plan QA failed: ' + '; '.join(qa.get('errors', [])))
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError('Remotion render failed: ' + detail[-2000:])
    if not Path(output_path).is_file():
        raise RuntimeError('Remotion did not produce output: ' + str(output_path))
    return Path(output_path)


def validate_plan(plan_path, node='node'):
    """Regenerate the QA report even when visual media is a valid cache hit."""
    script = Path(__file__).resolve().parents[1] / 'renderers/remotion/scripts/render.mjs'
    result = subprocess.run([node, str(script), '--plan', str(plan_path), '--validate-only'],
                            capture_output=True, text=True, encoding='utf-8', timeout=120)
    if result.returncode:
        qa_path = Path(str(plan_path).removesuffix('.json') + '-qa.json')
        if qa_path.is_file():
            qa = json.loads(qa_path.read_text(encoding='utf-8'))
            if qa.get('status') == 'failed':
                raise ValueError('Render plan QA failed: ' + '; '.join(qa.get('errors', [])))
        raise RuntimeError('Remotion validation unavailable: ' + (result.stderr or result.stdout)[-2000:])
