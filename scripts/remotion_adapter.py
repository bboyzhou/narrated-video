"""Small, deterministic bridge from the Python timeline to Remotion.

The adapter owns only visual rendering.  Audio mastering and final muxing stay in
the existing FFmpeg pipeline so that Remotion remains an optional renderer.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


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


def build_render_plan(project, stage, selected, voices, timeline):
    """Build a renderer-neutral JSON plan and stage only referenced media."""
    asset_root = project.work / 'remotion-assets'
    asset_root.mkdir(parents=True, exist_ok=True)
    fps = project.fps
    durations = [sum(voices[s]['frames'] for s in shot['narration']) for shot in selected]
    tails = [round(shot.get('transition', 0.3) * fps) if i + 1 < len(selected) else 0
             for i, shot in enumerate(selected)]
    shots = []
    cursor = 0
    for i, shot in enumerate(selected):
        visual_duration = durations[i] + tails[i]
        item = {
            'id': shot['id'],
            'start_frame': cursor,
            'duration_frames': visual_duration,
            'spoken_frames': durations[i],
            'transition_frames': tails[i],
            'type': shot['type'],
            'asset': _stage_asset(project.path_for(shot['asset']), asset_root),
            'source_start': shot.get('source_start', 0),
            'loop': shot.get('loop', False),
            'motion': shot.get('motion', 'push'),
            'layers': [],
        }
        for layer in shot.get('layers', []):
            copy_layer = {k: layer[k] for k in ('id', 'type', 'start', 'end', 'width', 'height',
                                                 'easing', 'keyframes') if k in layer}
            copy_layer['asset'] = _stage_asset(project.path_for(layer['asset']), asset_root)
            copy_layer['source_start'] = layer.get('source_start', 0)
            copy_layer['loop'] = layer.get('loop', False)
            item['layers'].append(copy_layer)
        shots.append(item)
        cursor += durations[i]
    return {
        'version': 1,
        'stage': stage,
        'fps': fps,
        'width': project.output['width'],
        'height': project.output['height'],
        'total_frames': cursor,
        'asset_root': str(asset_root),
        'browser_executable': project.runtime.get('browser') or project.runtime.get('chrome'),
        'motion': project.c.get('motion', {}),
        'shots': shots,
        'captions': timeline,
        'subtitles': project.c.get('subtitles', {}),
    }


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
                               capture_output=True, encoding='utf-8')
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError('Remotion render failed: ' + detail[-2000:])
    if not Path(output_path).is_file():
        raise RuntimeError('Remotion did not produce output: ' + str(output_path))
    return Path(output_path)
