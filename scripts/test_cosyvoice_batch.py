import json
from pathlib import Path
import sys
import tempfile
import unittest

from pipeline import Project


FAKE_BATCH = r'''
import json
from pathlib import Path
import sys
import wave

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
counter = Path(sys.argv[2])
count = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0
counter.write_text(str(count + 1), encoding='utf-8')
skip_last = len(sys.argv) > 3 and sys.argv[3] == 'skip-last'
jobs = manifest['jobs'][:-1] if skip_last else manifest['jobs']
for job in jobs:
    output = Path(job['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 800)
'''


class CosyVoiceBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cosyvoice-batch-test-')
        self.root = Path(self.temporary.name)
        self.model = self.root / 'model'
        self.model.mkdir()
        self.fake = self.root / 'fake_batch.py'
        self.fake.write_text(FAKE_BATCH, encoding='utf-8')
        self.counter = self.root / 'calls.txt'
        self.project = object.__new__(Project)
        self.project.root = self.root
        self.project.cache = self.root / 'cache'
        self.project.c = {'runtime': {'offline': True}}
        self.project.runtime = {}
        self.project.ffmpeg = None
        self.project.stats = {'rendered': 0, 'reused': 0}
        self.project.sentences = {
            'N1': {'id': 'N1', 'text': '第一句。'},
            'N2': {'id': 'N2', 'text': '第二句。'},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def config(self, extra=None):
        command = [sys.executable, str(self.fake), '{jobs_file}', str(self.counter)]
        if extra:
            command.append(extra)
        return {'engine': 'cosyvoice', 'provider': 'cosyvoice', 'model': 'test',
                'model_path': str(self.model), 'command': ['unused'],
                'batch_command': command, 'speaker': 'test', 'speed': 1,
                'revision': '1', 'license': 'test fixture'}

    def test_one_process_handles_all_misses_and_reuses_per_sentence_cache(self):
        first = self.project.cosyvoice_batch(['N1', 'N2'], self.config())
        self.assertEqual(set(first), {'N1', 'N2'})
        self.assertEqual(self.counter.read_text(encoding='utf-8'), '1')
        self.assertEqual(self.project.stats, {'rendered': 2, 'reused': 0})

        second = self.project.cosyvoice_batch(['N1', 'N2'], self.config())
        self.assertEqual(first, second)
        self.assertEqual(self.counter.read_text(encoding='utf-8'), '1')
        self.assertEqual(self.project.stats, {'rendered': 2, 'reused': 2})

        self.project.sentences['N2']['text'] = '修改后的第二句。'
        third = self.project.cosyvoice_batch(['N1', 'N2'], self.config())
        self.assertEqual(first['N1'], third['N1'])
        self.assertNotEqual(first['N2'], third['N2'])
        self.assertEqual(self.counter.read_text(encoding='utf-8'), '2')
        self.assertEqual(self.project.stats, {'rendered': 3, 'reused': 3})

    def test_incomplete_batch_does_not_promote_any_output(self):
        with self.assertRaisesRegex(ValueError, 'did not create a WAV for N2'):
            self.project.cosyvoice_batch(['N1', 'N2'], self.config('skip-last'))
        finalized = [path for path in self.project.cache.glob('*.wav') if '.partial.' not in path.name]
        self.assertEqual(finalized, [])
        self.assertEqual(self.project.stats, {'rendered': 0, 'reused': 0})


if __name__ == '__main__':
    unittest.main()
