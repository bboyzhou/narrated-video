#!/usr/bin/env python3
"""Thin launcher for an explicitly selected narrated-video runtime checkout."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Existing narrated-video runtime repository')
    parser.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    root = options.root or os.environ.get('NARRATED_VIDEO_ROOT')
    if not root:
        raise SystemExit('Select --root or NARRATED_VIDEO_ROOT; the Skill does not bundle a runtime')
    root = Path(root).resolve()
    pipeline = root / 'scripts' / 'pipeline.py'
    schema = root / 'schemas' / 'narrated-project-v1.schema.json'
    if not pipeline.is_file() or not schema.is_file():
        raise SystemExit('Selected runtime is missing pipeline.py or NarratedProject v1 Schema')
    forwarded = options.args[1:] if options.args[:1] == ['--'] else options.args
    return subprocess.call([sys.executable, str(pipeline), *forwarded], cwd=root)


if __name__ == '__main__':
    raise SystemExit(main())
