"""Path resolution and process environment regression tests; no downloads."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import launch_environment, resolve_paths, validate_paths, path_report, update_config
from pipeline import Project


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='narrated-runtime-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project.json'
        for directory in ('nltk data', 'hf', 'hub', 'transformers'):
            (self.root / directory).mkdir()

    def test_relative_paths_use_project_directory(self):
        paths = resolve_paths(self.project, {'nltk_data': 'nltk data'})
        self.assertEqual(paths['nltk_data'], str(self.root / 'nltk data'))
        validate_paths(paths)

    def test_project_overrides_inherited_resources_without_mutating_parent(self):
        with patch.dict(os.environ, {'NLTK_DATA': 'old', 'HF_HUB_CACHE': 'old-hub', 'TRANSFORMERS_CACHE': 'old-transformers'}):
            _, env = launch_environment(self.project, {'nltk_data': 'nltk data', 'hf_home': 'hf', 'offline': True})
            self.assertEqual(env['NLTK_DATA'], str(self.root / 'nltk data'))
            self.assertEqual(env['HF_HUB_CACHE'], str(self.root / 'hf' / 'hub'))
            self.assertEqual(env['TRANSFORMERS_CACHE'], env['HF_HUB_CACHE'])
            self.assertEqual(env['HF_HUB_OFFLINE'], '1')
            self.assertEqual(os.environ['NLTK_DATA'], 'old')

    def test_separate_model_caches(self):
        _, env = launch_environment(self.project, {'hf_home': 'hf', 'hf_hub_cache': 'hub', 'transformers_cache': 'transformers'})
        self.assertEqual(env['HF_HUB_CACHE'], str(self.root / 'hub'))
        self.assertEqual(env['TRANSFORMERS_CACHE'], str(self.root / 'transformers'))

    def test_missing_explicit_path_does_not_fall_back(self):
        with self.assertRaisesRegex(ValueError, 'no automatic fallback'):
            launch_environment(self.project, {'python': 'missing-python.exe'})

    def test_file_and_directory_types_are_distinct(self):
        with self.assertRaises(ValueError):
            validate_paths({'python': str(self.root / 'hf')})

    def test_discovery_does_not_save_or_choose_paths(self):
        report = path_report(self.project, {})
        self.assertFalse(self.project.exists())
        self.assertEqual(report['configured'], {})

    def test_no_runtime_keeps_inherited_resources(self):
        with patch.dict(os.environ, {'NLTK_DATA': 'existing'}):
            _, env = launch_environment(self.project, {})
            self.assertEqual(env['NLTK_DATA'], 'existing')

    def test_unified_cache_selection_clears_old_split_overrides(self):
        updated = update_config({'hf_home': 'old', 'hf_hub_cache': 'old-hub', 'transformers_cache': 'old-transformers'}, {'hf_home': 'new'})
        self.assertEqual(updated, {'hf_home': 'new'})

    def test_valid_ffmpeg_override_survives_stale_saved_path(self):
        executable = self.root / 'ffmpeg.exe'
        executable.write_bytes(b'test')
        _, env = launch_environment(self.project, {'ffmpeg': 'missing.exe'}, str(executable))
        self.assertEqual(env['PYTHONUTF8'], '1')

    def test_audio_path_is_not_part_of_script_approval(self):
        project = object.__new__(Project)
        project.c = {'narration': [{'id': 'N1', 'text': '同一句', 'audio': 'a.wav'}]}
        first = project.script_key()
        project.c['narration'][0]['audio'] = 'b.wav'
        self.assertEqual(first, project.script_key())


if __name__ == '__main__':
    unittest.main()
