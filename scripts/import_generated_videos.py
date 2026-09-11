#!/usr/bin/env python3
"""Validate generated MP4 files and register them without replacing fallbacks."""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from generators import build_video_job, file_sha256


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


def _duration_seconds(value):
    match = re.fullmatch(r'(\d+):(\d+):(\d+(?:\.\d+)?)', value.strip())
    return None if not match else (int(match.group(1)) * 3600 +
                                   int(match.group(2)) * 60 + float(match.group(3)))


def probe(path, ffprobe=None, ffmpeg=None):
    """Probe with ffprobe when present, otherwise decode one frame with FFmpeg."""
    ffprobe = ffprobe or shutil.which('ffprobe')
    if ffprobe:
        result = subprocess.run([ffprobe, '-v', 'error', '-print_format', 'json',
                                 '-show_streams', '-show_format', str(path)],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', check=False)
        require(result.returncode == 0,
                'ffprobe failed for ' + str(path) + ': ' + result.stderr[-500:])
        data = json.loads(result.stdout)
        streams = [stream for stream in data.get('streams', [])
                   if stream.get('codec_type') == 'video']
        require(streams, 'No video stream in ' + str(path))
        stream = streams[0]
        width, height = int(stream.get('width', 0)), int(stream.get('height', 0))
        duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0)
        require(width > 0 and height > 0 and duration > 0,
                'Invalid video dimensions/duration: ' + str(path))
        return {'width': width, 'height': height, 'duration': duration,
                'codec': stream.get('codec_name')}

    ffmpeg = ffmpeg or os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    require(ffmpeg, 'Neither ffprobe nor FFmpeg is available for generated-video validation')
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-i', str(path),
                             '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', check=False)
    require(result.returncode == 0,
            'FFmpeg failed to decode generated video ' + str(path) + ': ' + result.stderr[-500:])
    video = re.search(r'Video:\s*([^,]+).*?,\s*(\d{2,5})x(\d{2,5})(?:[\s,])', result.stderr)
    duration_match = re.search(r'Duration:\s*([0-9:.]+)', result.stderr)
    duration = _duration_seconds(duration_match.group(1)) if duration_match else None
    require(video and duration and duration > 0,
            'Could not determine generated-video dimensions/duration: ' + str(path))
    return {'width': int(video.group(2)), 'height': int(video.group(3)),
            'duration': duration, 'codec': video.group(1).strip()}


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        require(target == destination or destination in target.parents,
                'ZIP entry escapes temporary directory: ' + member.filename)
    archive.extractall(destination)


def _find_output(root, job):
    relative = Path(job.get('output') or ('output/' + job['id'] + '.mp4'))
    require(not relative.is_absolute() and '..' not in relative.parts,
            job['id'] + ': unsafe output path in job manifest')
    direct = root / relative
    if direct.is_file():
        return direct
    matches = list(root.rglob(job['id'] + '.mp4'))
    return matches[0] if len(matches) == 1 else None


def _result_rows(root):
    matches = list(root.rglob('results.json'))
    if not matches:
        return {}
    require(len(matches) == 1, 'Expected at most one results.json')
    payload = read_json(matches[0])
    rows = payload.get('results', [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
            'results.json results must be a list of objects')
    require(len({row.get('id') for row in rows}) == len(rows),
            'results.json contains duplicate IDs')
    return {row.get('id'): row for row in rows}


def _upgrade_legacy_manifest(manifest, config, project_root):
    """Add deterministic cache keys to version 1 CogVideoX manifests."""
    jobs = manifest.get('jobs', [])
    if all(job.get('cache_key') for job in jobs):
        return manifest
    storyboard_value = config.get('storyboard')
    require(storyboard_value, 'Legacy video_jobs.json needs project.storyboard for migration')
    storyboard_path = Path(storyboard_value)
    if not storyboard_path.is_absolute():
        storyboard_path = (project_root / storyboard_path).resolve()
    require(storyboard_path.is_file(), 'Storyboard missing for legacy video job migration')
    plans = {plan['id']: plan for plan in read_json(storyboard_path).get('shots', [])}
    shots = {shot['id']: shot for shot in config.get('shots', [])}
    upgraded, backend = [], None
    for old in jobs:
        shot_id = old.get('id')
        require(shot_id in plans and shot_id in shots,
                'Legacy job references an unknown storyboard shot: ' + str(shot_id))
        plan = plans[shot_id]
        source = plan.get('source_image') or shots[shot_id].get('asset')
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = (project_root / source_path).resolve()
        require(source_path.is_file(), shot_id + ': source image missing for legacy job migration')
        current, current_backend = build_video_job(
            plan, old.get('image', 'input/' + shot_id + source_path.suffix.lower()),
            file_sha256(source_path), config)
        backend = backend or current_backend
        require(backend == current_backend, 'Legacy jobs do not share one backend configuration')
        upgraded.append({**old, **current, 'output': old.get('output', current['output'])})
    return {**manifest, 'version': 2, 'backend': backend, 'jobs': upgraded,
            'cache_hits': manifest.get('cache_hits', [])}


def import_generated_videos(project_path, results_path, jobs_path=None, ffprobe=None,
                            ffmpeg=None, output_dir='assets/generated-video'):
    project_path = Path(project_path).resolve()
    root = project_path.parent
    config = read_json(project_path)
    shots = {shot['id']: shot for shot in config.get('shots', [])}
    results_path = Path(results_path).resolve()
    jobs_path = Path(jobs_path).resolve() if jobs_path else results_path.with_name('video_jobs.json')
    require(jobs_path.is_file(), 'video_jobs.json is required for safe cache-aware import')
    manifest = _upgrade_legacy_manifest(read_json(jobs_path), config, root)
    jobs = manifest.get('jobs', [])
    require(isinstance(jobs, list), 'video_jobs.json jobs must be a list')
    provider = manifest.get('provider')
    require(isinstance(provider, str) and re.fullmatch(r'[A-Za-z0-9_-]+', provider),
            'video_jobs.json needs a safe provider ID')
    require(len({job.get('id') for job in jobs}) == len(jobs),
            'video_jobs.json contains duplicate IDs')

    temporary = tempfile.TemporaryDirectory(prefix='narrated-video-import-')
    try:
        if results_path.suffix.lower() == '.zip':
            result_root = Path(temporary.name)
            with zipfile.ZipFile(results_path) as archive:
                safe_extract(archive, result_root)
        else:
            result_root = results_path
        require(result_root.is_dir(), 'Generated-video results directory is missing')
        reported = _result_rows(result_root)
        imported, failed = [], []
        index_path = root / '.narrated-video' / 'generated-video-index.json'
        index = read_json(index_path) if index_path.is_file() else {'version': 1, 'entries': {}}
        index.setdefault('entries', {})
        for job in jobs:
            shot_id = job.get('id')
            require(shot_id in shots, 'Unknown shot ID in generated results: ' + str(shot_id))
            require(job.get('provider', provider) == provider,
                    str(shot_id) + ': job provider does not match manifest')
            result_row = reported.get(shot_id)
            if result_row and result_row.get('status') != 'completed':
                failed.append({'id': shot_id, 'reason': result_row.get('error', 'worker failed')})
                continue
            if result_row:
                require(result_row.get('cache_key') == job.get('cache_key'),
                        shot_id + ': results.json cache_key does not match submitted job')
            source = _find_output(result_root, job)
            if not source:
                failed.append({'id': shot_id, 'reason': 'output MP4 missing; fallback remains active'})
                continue
            info = probe(source, ffprobe, ffmpeg)
            expected = manifest.get('backend', {}).get('size')
            if expected and '*' in expected:
                width, height = [int(value) for value in expected.split('*')]
                require((info['width'], info['height']) == (width, height),
                        shot_id + ': output resolution does not match job backend')
            cache_key = job.get('cache_key')
            require(isinstance(cache_key, str) and re.fullmatch(r'[0-9a-f]{64}', cache_key),
                    shot_id + ': missing or invalid cache_key')
            output_hash = file_sha256(source)
            if result_row and result_row.get('sha256'):
                require(result_row['sha256'] == output_hash,
                        shot_id + ': output hash does not match results.json')
            asset_root = (root / output_dir).resolve()
            require(asset_root == root or root in asset_root.parents,
                    'Generated-video output directory must stay inside the project')
            destination = (asset_root / provider / cache_key).resolve()
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / (shot_id + '.mp4')
            partial = target.with_suffix('.mp4.partial')
            shutil.copyfile(source, partial)
            partial.replace(target)
            relative = target.relative_to(root).as_posix()
            require(file_sha256(target) == output_hash, shot_id + ': copied output hash mismatch')
            generated = {
                'provider': provider,
                'cache_key': cache_key,
                'asset': relative,
                'sha256': output_hash,
                'model': manifest.get('backend', {}).get('model'),
                'model_revision': manifest.get('backend', {}).get('model_revision'),
                'imported_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                **info,
            }
            # The declared image/video shot remains the approved fallback. Rendering
            # resolves this generated asset only while its exact cache key is current.
            shots[shot_id]['generated_video'] = generated
            index['entries'][cache_key] = {'id': shot_id, **generated}
            imported.append({'id': shot_id, **generated})
        write_json(project_path, config)
        write_json(index_path, index)
        report = root / '.narrated-video' / 'generated-video-import.json'
        write_json(report, {'version': 2, 'provider': provider, 'imported': imported,
                            'failed': failed, 'fallback_active': [row['id'] for row in failed]})
        return {'project': str(project_path), 'provider': provider, 'imported': imported,
                'failed': failed, 'report': str(report)}
    finally:
        temporary.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='project.json to update')
    parser.add_argument('results', help='Generated output directory or ZIP')
    parser.add_argument('--ffprobe', help='Optional ffprobe executable')
    parser.add_argument('--ffmpeg', help='FFmpeg fallback when ffprobe is unavailable')
    parser.add_argument('--jobs', help='video_jobs.json; defaults beside results')
    parser.add_argument('--output-dir', default='assets/generated-video')
    args = parser.parse_args()
    result = import_generated_videos(args.project, args.results, args.jobs,
                                     args.ffprobe, args.ffmpeg, args.output_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        raise SystemExit('ERROR: ' + str(error))
