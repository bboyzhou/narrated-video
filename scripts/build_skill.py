#!/usr/bin/env python3
"""Validate and package the curated narrated-video Skill distribution."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


ALLOWED_TOP_LEVEL = {'SKILL.md', 'references', 'scripts', 'assets'}
FORBIDDEN_NAMES = {
    'README.md', 'node_modules', '.bundle-cache', '.test-output', '__pycache__',
    'deliverables', '.narrated-video', '.git', '.env',
}
MAX_FILES = 64
MAX_TOTAL_BYTES = 1024 * 1024
MAX_FILE_BYTES = 256 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_skill(source):
    source = Path(source).resolve()
    if not (source / 'SKILL.md').is_file():
        raise ValueError('Skill package requires SKILL.md')
    entries = list(source.iterdir())
    unknown = sorted(item.name for item in entries if item.name not in ALLOWED_TOP_LEVEL)
    if unknown:
        raise ValueError('Unexpected top-level Skill entries: ' + ', '.join(unknown))
    files = sorted(path for path in source.rglob('*') if path.is_file())
    if len(files) > MAX_FILES:
        raise ValueError('Skill package has too many files: ' + str(len(files)))
    total = 0
    manifest = {}
    for path in files:
        relative = path.relative_to(source)
        if any(part in FORBIDDEN_NAMES for part in relative.parts):
            raise ValueError('Forbidden Skill content: ' + relative.as_posix())
        if path.is_symlink():
            raise ValueError('Skill package must not contain symlinks: ' + relative.as_posix())
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError('Skill file exceeds size limit: ' + relative.as_posix())
        total += size
        manifest[relative.as_posix()] = sha256(path)
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Skill package exceeds 1 MiB: ' + str(total))

    content = (source / 'SKILL.md').read_text(encoding='utf-8')
    header = re.match(r'^---\s*\nname:\s*([^\n]+)\ndescription:\s*([^\n]+)\n---', content)
    if not header:
        raise ValueError('SKILL.md frontmatter must contain name and description')
    name, description = header.group(1).strip(), header.group(2).strip()
    if not re.fullmatch(r'[a-z0-9-]{1,64}', name):
        raise ValueError('Skill name must be lowercase kebab-case and <=64 characters')
    if not 1 <= len(description) <= 1024 or '<' in description or '>' in description:
        raise ValueError('Skill description must be 1..1024 characters without XML tags')
    for reference in re.findall(r'\]\((references/[^)]+)\)', content):
        if not (source / reference).is_file():
            raise ValueError('Missing referenced file: ' + reference)
    return {'name': name, 'files': manifest, 'file_count': len(files), 'bytes': total}


def package_skill(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    report = validate_skill(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative in report['files']:
            archive.write(source / relative, (Path(report['name']) / relative).as_posix())
        archive.writestr(
            (Path(report['name']) / 'installation-manifest.json').as_posix(),
            json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        )
    temporary.replace(output)
    return {**report, 'package': str(output), 'package_bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--source', default=str(root / 'skill' / 'narrated-video'))
    parser.add_argument('--output', default=str(root / 'dist' / 'narrated-video.skill.zip'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    report = validate_skill(args.source) if args.check else package_skill(args.source, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit('ERROR: ' + str(error))
