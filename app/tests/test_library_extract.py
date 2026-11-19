"""Video text extraction and cache migration in a temporary library."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import library

PROJECT = Path(__file__).resolve().parents[2]


class LibraryExtraction(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('text', 'videos', 'transcripts', 'manifests'):
            (self.root / name).mkdir()
        (self.root / 'videos/example.mp4').write_bytes(b'video fixture')
        self.record = {'id': 'video-example', 'path': 'videos/example.mp4', 'kind': 'video',
                       'title': 'Container labels', 'notes': 'An example recording.',
                       'sha256': 'a' * 64, 'collection': 'Examples', 'category': 'reference',
                       'captions': ['transcripts/example.vtt']}
        self.textpath = self.root / 'text/video-example.txt'
        self.metapath = self.textpath.with_suffix('.json')
        root_patch = patch.object(library, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def caption(self, text, path='transcripts/example.vtt'):
        dest = self.root / path
        dest.write_text('WEBVTT\n\n00:01.000 --> 00:05.000\n' + text + '\n', encoding='utf-8')
        return dest

    def extract(self, **changes):
        record, pages, error = library.extract({**self.record, **changes})
        self.assertIsNone(error)
        self.assertEqual(record['text_path'], 'text/video-example.txt')
        self.assertEqual(self.textpath.read_text(encoding='utf-8'), '\n\f\n'.join(pages))
        return pages

    def legacy_cache(self, text, **details):
        self.textpath.write_text(text, encoding='utf-8')
        self.metapath.write_text(json.dumps({'sha256': self.record['sha256'], 'details': details}), encoding='utf-8')

    def test_video_formats_keep_numeric_payload_and_skip_metadata(self):
        data = (b'\xef\xbb\xbfWEBVTT\r\nKind: captions\r\n\r\n'
                b'17\r\n00:01.000 --> 00:05.000\r\nThe label reads\r\n12\r\nlitres.\r\n\r\n'
                b'NOTE editor notes\r\nDo not include this comment.\r\n\r\n'
                b'chapter-two\r\n00:05.000 --> 00:08.000\r\n'
                b'<b>NOTE</b> this &amp; that are spoken.\r\n')
        (self.root / self.record['captions'][0]).write_bytes(data)
        for kind in ('video', 'mp4', 'webm', 'mkv'):
            with self.subTest(kind=kind):
                self.textpath.unlink(missing_ok=True)
                self.metapath.unlink(missing_ok=True)
                self.assertEqual(self.extract(kind=kind), ['The label reads\n12\nlitres.\nNOTE this & that are spoken.'])

    def test_legacy_cache_is_rebuilt_with_the_same_video_checksum(self):
        self.caption('The label reads\n12\nlitres.')
        self.legacy_cache('The label reads\nlitres.')
        self.assertEqual(self.extract(), ['The label reads\n12\nlitres.'])
        self.assertEqual(json.loads(self.metapath.read_text())['sha256'], self.record['sha256'])

    def test_unchanged_inputs_reuse_the_cached_text(self):
        self.caption('An unchanged caption.')
        expected = self.extract()
        with patch.object(Path, 'write_text', side_effect=AssertionError('rewrote unchanged extract')):
            self.assertEqual(self.extract(), expected)

    def test_caption_edit_invalidates_cache_even_with_same_size_and_mtime(self):
        path = self.caption('First caption.')
        self.assertEqual(self.extract(), ['First caption.'])
        stat = path.stat()
        self.caption('Other caption.')
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size, stat.st_size)
        self.assertEqual(self.extract(), ['Other caption.'])

    def test_added_reordered_and_removed_tracks_refresh_the_cache(self):
        first = self.record['captions'][0]
        second = 'transcripts/second.vtt'
        self.caption('First track.')
        self.caption('Deuxième piste.', second)
        self.assertEqual(self.extract(), ['First track.'])
        self.assertEqual(self.extract(captions=[first, second]), ['First track.\nDeuxième piste.'])
        self.assertEqual(self.extract(captions=[second, first]), ['Deuxième piste.\nFirst track.'])
        self.assertEqual(self.extract(captions=[second]), ['Deuxième piste.'])
        self.assertEqual(self.extract(captions=[]), ['Container labels\nAn example recording.'])

    def test_fallback_title_and_notes_are_not_stuck_in_cache(self):
        self.assertEqual(self.extract(captions=[]), ['Container labels\nAn example recording.'])
        self.assertEqual(self.extract(captions=[], title='Updated title', notes='Updated notes.'),
                         ['Updated title\nUpdated notes.'])

    def test_metadata_only_captions_use_the_record_fallback(self):
        (self.root / self.record['captions'][0]).write_text('WEBVTT\n\nNOTE\nEditor only.\n', encoding='utf-8')
        self.assertEqual(self.extract(), ['Container labels\nAn example recording.'])

    def test_missing_caption_reports_an_error_without_replacing_cache(self):
        path = self.caption('Previously available caption.')
        self.extract()
        before = (self.textpath.read_bytes(), self.metapath.read_bytes())
        path.unlink()
        _, pages, error = library.extract(dict(self.record))
        self.assertEqual(pages, [])
        self.assertIsNotNone(error)
        self.assertEqual((self.textpath.read_bytes(), self.metapath.read_bytes()), before)

    def test_missing_text_file_is_rebuilt(self):
        self.caption('A caption to restore.')
        self.extract()
        self.textpath.unlink()
        self.assertEqual(self.extract(), ['A caption to restore.'])

    def test_changed_video_checksum_still_invalidates_cache(self):
        self.caption('The current caption.')
        self.extract()
        self.textpath.write_text('A cached sentinel.', encoding='utf-8')
        self.assertEqual(self.extract(sha256='b' * 64), ['The current caption.'])

    def test_cached_pdf_text_and_details_are_unchanged(self):
        self.legacy_cache('First page\n\f\nSecond page', pages=2, searchability='text')
        with patch.object(Path, 'write_text', side_effect=AssertionError('rewrote cached PDF')):
            record, pages, error = library.extract({**self.record, 'kind': 'pdf', 'path': 'documents/absent.pdf'})
        self.assertIsNone(error)
        self.assertEqual(pages, ['First page', 'Second page'])
        self.assertEqual(record['pages'], 2)
        self.assertEqual(record['searchability'], 'text')

    def test_plain_text_extraction_is_unchanged(self):
        path = self.root / 'example.txt'
        path.write_text('Text with 12 and café.\nA second line.', encoding='utf-8')
        self.assertEqual(self.extract(kind='txt', path='example.txt'), ['Text with 12 and café.\nA second line.'])

    def test_direct_cli_build_refreshes_legacy_text_and_search_rows(self):
        self.caption('The label reads\n12\nlitres.')
        self.legacy_cache('The label reads\nlitres.')
        (self.root / 'manifests/examples.json').write_text(json.dumps([self.record]), encoding='utf-8')
        # A library's vendor directory must not supply the parser imported by the program.
        vendor = self.root / 'tools' / ('vendor-py312' if sys.version_info[:2] == (3, 12) else 'vendor')
        vendor.mkdir(parents=True)
        (vendor / 'saved_pages.py').write_text("raise AssertionError('loaded a helper from the data folder')\n", encoding='utf-8')
        env = {**os.environ, 'LASTBOOK_LIBRARY': str(self.root)}

        def run(*args):
            result = subprocess.run([sys.executable, '-B', str(PROJECT / 'engine/library.py'), *args],
                                    cwd=self.root, env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        run('build')
        self.assertEqual([r['doc_id'] for r in json.loads(run('search', '12'))], ['video-example'])
        self.caption('The label reads\n34\nlitres.')
        run('build')
        self.assertEqual(json.loads(run('search', '12')), [])
        self.assertEqual([r['doc_id'] for r in json.loads(run('search', '34'))], ['video-example'])
        self.assertEqual(json.loads((self.root / 'summary.json').read_text())['extraction_errors'], [])

    def test_module_cli_remains_available(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'engine.library', '--help'], cwd=PROJECT,
                                env={**os.environ, 'LASTBOOK_LIBRARY': str(self.root)}, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('build', result.stdout)


if __name__ == '__main__':
    unittest.main()
