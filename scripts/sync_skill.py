#!/usr/bin/env python3
"""Install the curated Skill as an exact, backed-up mirror."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from build_skill import sha256, validate_skill


def require_separate(source, target, backup_root):
    source = source.resolve()
    target = target.resolve()
    backup_root = backup_root.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and target must be separate directories')
    if backup_root == target or backup_root in target.parents or target in backup_root.parents:
        raise ValueError('Backup root and target must be separate directories')
    if target.parent == target or backup_root.parent == backup_root:
        raise ValueError('Refusing to operate on a filesystem root')


def install(source, target, backup_root):
    source = Path(source).resolve()
    target = Path(target).resolve()
    backup_root = Path(backup_root).resolve()
    require_separate(source, target, backup_root)
    report = validate_skill(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=target.name + '-staging-', dir=target.parent))
    staged_skill = staging / target.name
    shutil.copytree(source, staged_skill)
    validate_skill(staged_skill)

    backup = None
    try:
        if target.exists():
            stamp = time.strftime('%Y%m%d-%H%M%S')
            backup = backup_root / (target.name + '-' + stamp)
            if backup.exists():
                raise ValueError('Backup destination already exists: ' + str(backup))
            target.replace(backup)
        staged_skill.replace(target)
    except Exception:
        if not target.exists() and backup and backup.exists():
            backup.replace(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    installed = {
        path.relative_to(target).as_posix(): sha256(path)
        for path in target.rglob('*') if path.is_file()
    }
    if installed != report['files']:
        raise RuntimeError('Installed Skill hash manifest differs from source')
    return {
        'target': str(target),
        'backup': str(backup) if backup else None,
        'file_count': report['file_count'],
        'bytes': report['bytes'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--source', default=str(root / 'skill' / 'narrated-video'))
    parser.add_argument('--target', required=True)
    parser.add_argument('--backup-root', required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.source, args.target, args.backup_root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit('ERROR: ' + str(error))
