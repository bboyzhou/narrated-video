#!/usr/bin/env python3
"""Prepare an offline input bundle for an external image-to-video provider."""
import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def safe_id(value):
    require(isinstance(value, str) and value and all(c.isalnum() or c in '_-' for c in value),
            'Shot IDs must use letters, digits, _ or -')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('storyboard', help='Approved storyboard.json')
    parser.add_argument('--project', help='Optional project.json for demo selection and fallback assets')
    parser.add_argument('--stage', choices=('demo', 'full'), default='demo')
    parser.add_argument('--output', required=True, help='video_jobs.json output path')
    parser.add_argument('--bundle', help='ZIP bundle for Colab; defaults beside --output')
    args = parser.parse_args()

    storyboard_path = Path(args.storyboard).resolve()
    storyboard = read_json(storyboard_path)
    require(storyboard.get('version') == 1, 'Unsupported storyboard version')
    project = read_json(args.project) if args.project else None
    project_root = Path(args.project).resolve().parent if args.project else storyboard_path.parent
    project_shots = {s['id']: s for s in (project or {}).get('shots', [])}
    selected_ids = None
    if args.stage == 'demo':
        selected_ids = set((project or {}).get('demo', {}).get('shots', storyboard.get('demo', {}).get('shots', [])))

    jobs = []
    with tempfile.TemporaryDirectory(prefix='narrated-video-jobs-') as temporary:
        bundle_root = Path(temporary)
        input_dir = bundle_root / 'input'
        input_dir.mkdir()
        for plan in storyboard.get('shots', []):
            shot_id = safe_id(plan.get('id'))
            if selected_ids is not None and shot_id not in selected_ids:
                continue
            if plan.get('asset_strategy') != 'generated_video':
                continue
            source = plan.get('source_image')
            if not source and shot_id in project_shots:
                source = project_shots[shot_id].get('asset')
            require(source, shot_id + ': generated_video needs source_image or project fallback asset')
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = (project_root / source_path).resolve()
            require(source_path.is_file(), shot_id + ': source image missing: ' + str(source_path))
            suffix = source_path.suffix.lower() or '.png'
            archive_image = Path('input') / (shot_id + suffix)
            shutil.copyfile(source_path, bundle_root / archive_image)
            generation = plan['generation']
            jobs.append({
                'id': shot_id,
                'image': archive_image.as_posix(),
                'prompt': plan['motion_prompt'],
                'constraints': plan['motion_constraints'],
                'seed': generation['seed'],
                'duration_target': generation['duration_target'],
                'provider': generation['provider'],
                'mode': generation['mode'],
                'output': ('output/' + shot_id + '.mp4'),
                'fallback_asset': project_shots.get(shot_id, {}).get('asset'),
            })
        require(jobs, 'No generated_video shots selected')
        payload = {'version': 1, 'provider': 'cogvideox_colab', 'mode': 'i2v',
                   'stage': args.stage, 'jobs': jobs}
        output = Path(args.output).resolve()
        write_json(output, payload)
        bundle = Path(args.bundle).resolve() if args.bundle else output.with_suffix('.zip')
        bundle.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(output, 'video_jobs.json')
            for path in input_dir.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_root).as_posix())
    print(json.dumps({'jobs': len(jobs), 'manifest': str(output), 'bundle': str(bundle)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit('ERROR: ' + str(error))
