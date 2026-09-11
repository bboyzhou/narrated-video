#!/usr/bin/env python3
"""Validate external MP4 results and import them as ordinary type=video shots."""
import argparse
import hashlib
import json
import shutil
import subprocess
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
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def probe(path, ffprobe):
    result = subprocess.run([ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams',
                             '-show_format', str(path)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', check=False)
    require(result.returncode == 0, 'ffprobe failed for ' + str(path) + ': ' + result.stderr[-500:])
    data = json.loads(result.stdout)
    streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
    require(streams, 'No video stream in ' + str(path))
    stream = streams[0]
    width, height = int(stream.get('width', 0)), int(stream.get('height', 0))
    duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0)
    require(width > 0 and height > 0 and duration > 0, 'Invalid video dimensions/duration: ' + str(path))
    return {'width': width, 'height': height, 'duration': duration, 'codec': stream.get('codec_name')}


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        require(target == destination or destination in target.parents,
                'ZIP entry escapes temporary directory: ' + member.filename)
    archive.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='project.json to update')
    parser.add_argument('results', help='Colab output directory or ZIP')
    parser.add_argument('--ffprobe', default='ffprobe', help='ffprobe executable')
    parser.add_argument('--jobs', help='video_jobs.json; defaults to a file beside results')
    parser.add_argument('--output-dir', default='assets/generated-video')
    args = parser.parse_args()
    project_path = Path(args.project).resolve()
    root = project_path.parent
    config = read_json(project_path)
    shots = {shot['id']: shot for shot in config.get('shots', [])}
    results = Path(args.results).resolve()
    jobs_path = Path(args.jobs).resolve() if args.jobs else results.with_name('video_jobs.json')
    jobs = read_json(jobs_path).get('jobs', []) if jobs_path.is_file() else []
    ids = [job['id'] for job in jobs] if jobs else list(shots)
    job_by_id = {job['id']: job for job in jobs}
    temporary = tempfile.TemporaryDirectory(prefix='narrated-video-import-')
    try:
        result_root = Path(temporary.name)
        if results.suffix.lower() == '.zip':
            with zipfile.ZipFile(results) as archive:
                safe_extract(archive, result_root)
            search_root = result_root
        else:
            search_root = results
        destination = (root / args.output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        imported = []
        for shot_id in ids:
            require(shot_id in shots, 'Unknown shot ID in generated results: ' + shot_id)
            candidates = list(search_root.rglob(shot_id + '.mp4'))
            require(len(candidates) == 1, 'Expected exactly one MP4 for ' + shot_id)
            source = candidates[0]
            info = probe(source, args.ffprobe)
            target = destination / (shot_id + '.mp4')
            temporary_target = target.with_suffix('.mp4.partial')
            shutil.copyfile(source, temporary_target)
            temporary_target.replace(target)
            shot = shots[shot_id]
            shot.update({'type': 'video', 'asset': str(target.relative_to(root)).replace('\\', '/'),
                         'motion': 'still', 'generated_from': 'cogvideox_colab',
                         'generated_video': {'source': str(source), **info}})
            imported.append({'id': shot_id, 'asset': shot['asset'], 'sha256': sha256(target),
                             'job': job_by_id.get(shot_id), **info})
        write_json(project_path, config)
        report = root / '.narrated-video' / 'generated-video-import.json'
        write_json(report, {'version': 1, 'provider': 'cogvideox_colab', 'imported': imported})
        print(json.dumps({'project': str(project_path), 'imported': imported, 'report': str(report)}, ensure_ascii=False))
    finally:
        temporary.cleanup()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        raise SystemExit('ERROR: ' + str(error))
