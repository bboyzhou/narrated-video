from pathlib import Path
import tempfile
import unittest

from build_skill import validate_skill
from sync_skill import install


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.source = self.root / 'skill' / 'narrated-video'

    def test_curated_skill_is_small_and_self_contained(self):
        report = validate_skill(self.source)
        self.assertLess(report['bytes'], 1024 * 1024)
        self.assertNotIn('README.md', report['files'])
        self.assertFalse(any('node_modules' in name or '.bundle-cache' in name
                             for name in report['files']))

    def test_sync_replaces_junk_but_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'installed' / 'narrated-video'
            backup = root / 'backups'
            junk = target / 'renderers' / 'remotion' / 'node_modules'
            junk.mkdir(parents=True)
            (junk / 'junk.js').write_text('junk', encoding='utf-8')
            result = install(self.source, target, backup)
            self.assertFalse((target / 'renderers').exists())
            self.assertTrue((Path(result['backup']) / 'renderers' / 'remotion' /
                             'node_modules' / 'junk.js').is_file())
            self.assertTrue((target / 'SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main()
