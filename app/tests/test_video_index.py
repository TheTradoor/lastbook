"""Incremental video indexing with temporary files and a deterministic embedder."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import retrieval


def caption(word):
    return ('This is the ' + word + ' label on the container in this example. '
            'You can read the label and find the same words in the video.')


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        vectors = retrieval.np.zeros((len(texts), retrieval.DIM), dtype=retrieval.np.float32)
        for row, text in enumerate(texts):
            for column, word in enumerate(('amber', 'coral', 'ivory')):
                if word in text:
                    vectors[row, column] = 1
        return vectors


@unittest.skipUnless(hasattr(retrieval, 'np'), 'needs numpy, but no model')
class VideoIndex(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.record = {'id': 'video-example', 'kind': 'video', 'path': 'example.mp4',
                       'sha256': 'unchanged-video', 'captions': ['captions.vtt']}
        self.catalog = {'by_id': {self.record['id']: self.record}, 'video_tx': {}}
        self.embedder = FakeEmbedder()
        for name, value in (('LIB', self.root), ('IDX', self.root / 'index'),
                            ('AVAILABLE', True), ('Embedder', lambda: self.embedder)):
            p = patch.object(retrieval, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.indexes = []
        self.addCleanup(self.close_indexes)
        self.write_caption('amber')
        self.index = self.new_index()

    def new_index(self):
        index = retrieval.Index(lambda: self.catalog, lambda record: ('example', 1), self.root / 'search.sqlite')
        self.indexes.append(index)
        return index

    def close_indexes(self):
        for index in self.indexes:
            connection = getattr(index._tls, 'ro', None)
            if connection:
                connection.close()

    def write_caption(self, word, path='captions.vtt'):
        target = self.root / path
        target.write_text('WEBVTT\n\n00:20.000 --> 00:25.000\n' + caption(word) + '\n', encoding='utf-8')
        return target

    def results(self, word, index=None):
        return (index or self.index).semantic(word)

    def assert_only(self, word, index=None):
        index = index or self.index
        hits = self.results(word, index)
        self.assertEqual([(h['doc_id'], h['t'], h['text']) for h in hits],
                         [('video-example', 20, caption(word))])
        for other in {'amber', 'coral', 'ivory'} - {word}:
            self.assertEqual(self.results(other, index), [])

    def test_initial_index_returns_caption_with_timestamp(self):
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')

    def test_same_path_size_and_mtime_still_refreshes_search(self):
        self.assertEqual(self.index.update(), 1)
        path = self.root / 'captions.vtt'
        old = path.stat()
        self.write_caption('coral')
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertEqual(path.stat().st_size, old.st_size)
        processed = self.index.update()
        self.assert_only('coral')
        self.assertEqual(processed, 1)
        self.assert_only('coral', self.new_index())

    def test_unchanged_bytes_do_not_reembed_or_append_vectors(self):
        self.index.update()
        path = self.root / 'captions.vtt'
        old = path.stat()
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000_000))
        before = self.index.vec_path.read_bytes()
        calls = len(self.embedder.calls)
        self.assertEqual(self.index.update(), 0)
        self.assertEqual(self.new_index().update(), 0)
        self.assertEqual(len(self.embedder.calls), calls)
        self.assertEqual(self.index.vec_path.read_bytes(), before)

    def test_legacy_path_signature_is_refreshed_once(self):
        self.index.update()
        with sqlite3.connect(self.index.db_path) as db:
            db.execute('UPDATE docstate SET sig=?', ('vtt:captions.vtt',))
            db.execute('UPDATE chunk SET text=?', (caption('ivory'),))
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')
        self.assertEqual(self.index.update(), 0)

    def test_empty_caption_is_retried_after_text_is_added(self):
        (self.root / 'captions.vtt').write_text('WEBVTT\n\n', encoding='utf-8')
        self.assertEqual(self.index.update(), 1)
        self.assertEqual(self.results('amber'), [])
        self.write_caption('amber')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')
        self.assertEqual(self.index.gaps_for(['video-example']), {})

    def test_selected_transcript_caption_is_refreshed(self):
        self.write_caption('coral', 'transcribed.vtt')
        self.catalog['video_tx']['example.mp4'] = {'vtt_path': 'transcribed.vtt'}
        self.index.update()
        self.assert_only('coral')
        self.write_caption('ivory', 'transcribed.vtt')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('ivory')
        (self.root / 'transcribed.vtt').unlink()
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')

    def test_unused_caption_does_not_reembed_selected_track(self):
        self.record['captions'].append('unused.vtt')
        self.write_caption('coral', 'unused.vtt')
        self.index.update()
        self.write_caption('ivory', 'unused.vtt')
        self.assertEqual(self.index.update(), 0)
        self.assert_only('amber')

    def test_missing_caption_removes_passages_and_restoration_reindexes(self):
        self.index.update()
        (self.root / 'captions.vtt').unlink()
        self.index.update()
        self.assertEqual(self.results('amber'), [])
        self.write_caption('amber')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')

    def test_embedding_failure_keeps_previous_passages_and_retries(self):
        self.index.update()
        self.write_caption('coral')
        with patch.object(self.embedder, 'embed', side_effect=RuntimeError('embedding interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'embedding interrupted'):
                self.index.update()
        self.assert_only('amber')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('coral')

    def test_failed_transaction_is_retried_after_reopening_index(self):
        self.index.update()
        before = self.index.vec_path.read_bytes()
        self.write_caption('coral')
        transaction = retrieval.Index.tx

        def interrupt(db, write):
            def partial(connection):
                write(connection)
                raise RuntimeError('commit interrupted')
            return transaction(db, partial)

        with patch.object(retrieval.Index, 'tx', side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, 'commit interrupted'):
                self.index.update()
        self.assert_only('amber')
        reopened = self.new_index()
        self.assertEqual(reopened.vec_path.read_bytes(), before)
        self.assertEqual(reopened.update(), 1)
        self.assert_only('coral', reopened)

    def test_change_between_scan_and_load_records_the_loaded_caption(self):
        sources = self.index.sources

        def change_after_scan():
            found = sources()
            self.write_caption('coral')
            return found

        with patch.object(self.index, 'sources', side_effect=change_after_scan):
            self.assertEqual(self.index.update(), 1)
        self.assert_only('coral')
        self.assertEqual(self.index.update(), 0)

    def test_change_during_embedding_is_picked_up_on_next_pass(self):
        self.index.update()
        self.write_caption('coral')
        embed = self.embedder.embed

        def change_during_embedding(texts):
            self.write_caption('ivory')
            return embed(texts)

        with patch.object(self.embedder, 'embed', side_effect=change_during_embedding):
            self.assertEqual(self.index.update(), 1)
        self.assert_only('coral')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('ivory')

    def test_read_failure_after_scan_is_retried_when_caption_returns(self):
        sources = self.index.sources

        def remove_after_scan():
            found = sources()
            (self.root / 'captions.vtt').unlink()
            return found

        with patch.object(self.index, 'sources', side_effect=remove_after_scan):
            self.index.update()
        self.assertIn('unreadable:', self.index.gaps_for(['video-example'])['video-example'])
        self.write_caption('amber')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('amber')
        self.assertEqual(self.index.gaps_for(['video-example']), {})

    def test_unreadable_caption_does_not_mark_changed_text_as_indexed(self):
        self.index.update()
        self.write_caption('coral')
        read = Path.read_bytes

        def unreadable(path):
            if path == self.root / 'captions.vtt':
                raise PermissionError('caption unavailable')
            return read(path)

        with patch.object(Path, 'read_bytes', unreadable):
            with self.assertRaisesRegex(PermissionError, 'caption unavailable'):
                self.index.update()
        self.assert_only('amber')
        self.assertEqual(self.index.update(), 1)
        self.assert_only('coral')

    def test_rejected_video_is_not_read_or_returned(self):
        self.index.update()
        (self.root / 'video-exclusions.json').write_text('{"videos": {"video-example": {}}}', encoding='utf-8')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('read rejected captions')):
            self.index.update()
        self.assertEqual(self.results('amber'), [])
        with sqlite3.connect(self.index.db_path) as db:
            self.assertEqual(db.execute('SELECT text, active FROM chunk').fetchall(), [('', 0)])

    def test_plain_transcript_fallback_still_uses_catalog_checksum(self):
        (self.root / 'captions.vtt').unlink()
        path = self.root / 'transcript.txt'
        path.write_text(caption('amber'), encoding='utf-8')
        transcript = {'path': 'transcript.txt', 'sha256': 'first-transcript'}
        self.catalog['video_tx']['example.mp4'] = transcript
        self.assertEqual(self.index.update(), 1)
        self.assertEqual(self.results('amber')[0]['text'], caption('amber'))
        self.assertEqual(self.index.update(), 0)
        path.write_text(caption('coral'), encoding='utf-8')
        transcript['sha256'] = 'second-transcript'
        self.assertEqual(self.index.update(), 1)
        self.assertEqual(self.results('amber'), [])
        self.assertEqual(self.results('coral')[0]['text'], caption('coral'))


if __name__ == '__main__':
    unittest.main()
