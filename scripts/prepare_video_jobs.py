#!/usr/bin/env python3
"""Prepare a cache-aware input bundle for an external video generator."""
import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from generators import (build_video_job, file_sha256, provider_for_plan,
                        validate_video_policy)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def safe_id(value):
    require(isinstance(value, str) and value and all(c.isalnum() or c in '_-' for c in value),
            'Shot IDs must use letters, digits, _ or -')
    return value


def _cache_index(project_root):
    path = project_root / '.narrated-video' / 'generated-video-index.json'
    if not path.is_file():
        return {}
    value = read_json(path)
    return value.get('entries', {}) if isinstance(value, dict) else {}


def _cache_hit(entry, project_root, provider, cache_key):
    if not isinstance(entry, dict) or entry.get('provider') != provider:
        return None
    asset = entry.get('asset')
    if not asset:
        return None
    path = Path(asset)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    if not path.is_file() or entry.get('sha256') != file_sha256(path):
        return None
    return {'cache_key': cache_key, 'provider': provider, 'asset': asset,
            'sha256': entry['sha256']}


def prepare_video_jobs(storyboard_path, project_path=None, stage='demo', output=None,
                       bundle=None, provider=None):
    storyboard_path = Path(storyboard_path).resolve()
    storyboard = read_json(storyboard_path)
    require(storyboard.get('version') == 1, 'Unsupported storyboard version')
    project_path = Path(project_path).resolve() if project_path else None
    project = read_json(project_path) if project_path else {}
    project_root = project_path.parent if project_path else storyboard_path.parent
    project_shots = {shot['id']: shot for shot in project.get('shots', [])}
    selected_ids = None
    if stage == 'demo':
        selected_ids = set(project.get('demo', {}).get(
            'shots', storyboard.get('demo', {}).get('shots', [])))

    plans = []
    for plan in storyboard.get('shots', []):
        shot_id = safe_id(plan.get('id'))
        if selected_ids is not None and shot_id not in selected_ids:
            continue
        if plan.get('asset_strategy') != 'generated_video':
            continue
        if provider and provider_for_plan(plan, project) != provider:
            continue
        plans.append(plan)
    require(plans, 'No generated_video shots selected')
    validate_video_policy(project, plans)
    providers = {provider_for_plan(plan, project) for plan in plans}
    require(len(providers) == 1,
            'A video job bundle must contain one provider; pass --provider to split the stage')
    selected_provider = next(iter(providers))

    output = Path(output).resolve() if output else (
        project_root / '.narrated-video' / ('video-jobs-' + stage + '.json'))
    bundle = Path(bundle).resolve() if bundle else output.with_suffix('.zip')
    index = _cache_index(project_root)
    jobs, hits, backend = [], [], None
    with tempfile.TemporaryDirectory(prefix='narrated-video-jobs-') as temporary:
        bundle_root = Path(temporary)
        input_dir = bundle_root / 'input'
        input_dir.mkdir()
        for plan in plans:
            shot_id = plan['id']
            source = plan.get('source_image') or project_shots.get(shot_id, {}).get('asset')
            require(source, shot_id + ': generated_video needs source_image or project fallback asset')
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = (project_root / source_path).resolve()
            require(source_path.is_file(), shot_id + ': source image missing: ' + str(source_path))
            suffix = source_path.suffix.lower() or '.png'
            archive_image = Path('input') / (shot_id + suffix)
            image_hash = file_sha256(source_path)
            job, job_backend = build_video_job(
                plan, archive_image.as_posix(), image_hash, project)
            backend = backend or job_backend
            require(backend == job_backend, 'All jobs in a bundle must share one backend configuration')
            job['fallback_asset'] = project_shots.get(shot_id, {}).get('asset')
            hit = _cache_hit(index.get(job['cache_key']), project_root,
                             selected_provider, job['cache_key'])
            if hit:
                hits.append({'id': shot_id, **hit})
                continue
            shutil.copyfile(source_path, bundle_root / archive_image)
            jobs.append(job)

        payload = {
            'version': 2,
            'project_id': project.get('title') or project_root.name,
            'provider': selected_provider,
            'mode': 'i2v',
            'stage': stage,
            'backend': backend,
            'jobs': jobs,
            'cache_hits': hits,
        }
        write_json(output, payload)
        bundle.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(output, 'video_jobs.json')
            for path in input_dir.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_root).as_posix())
    return {'provider': selected_provider, 'jobs': len(jobs), 'cache_hits': len(hits),
            'manifest': str(output), 'bundle': str(bundle)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('storyboard', help='Approved storyboard.json')
    parser.add_argument('--project', help='Optional project.json for policy, cache and fallback assets')
    parser.add_argument('--stage', choices=('demo', 'full'), default='demo')
    parser.add_argument('--output', help='video_jobs.json output path')
    parser.add_argument('--bundle', help='ZIP bundle; defaults beside --output')
    parser.add_argument('--provider', help='Prepare only one provider when a stage mixes providers')
    args = parser.parse_args()
    result = prepare_video_jobs(args.storyboard, args.project, args.stage,
                                args.output, args.bundle, args.provider)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit('ERROR: ' + str(error))
