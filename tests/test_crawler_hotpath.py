import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import intranet_crawler as crawler


class LinkExtractionTests(unittest.TestCase):
    def test_single_pass_keeps_navigation_lazy_images_inline_styles_and_posters(self):
        extract = getattr(crawler, "extract_page_links", None)
        self.assertTrue(callable(extract), "single-pass dependency extraction is missing")
        html = '''
            <img src="/UploadFiles/photo.jpg?size=2#preview">
            <a href="../Item/7.aspx?x=1#part">page</a>
            <a href="../Item/7.aspx?x=2">duplicate</a>
            <a href="/UploadFiles/guide.zip">download</a>
            <section data-src="/UploadFiles/lazy.jpg"
                     style="background:url('/UploadFiles/background.png')"></section>
            <video poster="/UploadFiles/poster.jpg"></video>
            <script src="/assets/app.js"></script>
            <link href="/assets/main.css">
            <a href="javascript:alert(1)">ignored</a>
            <img src="https://other.test/UploadFiles/external.jpg">
        '''
        links = extract(html, "http://10.176.17.2/Category_1/Index.aspx")
        self.assertEqual(links.navigation, [
            "http://10.176.17.2/Item/7.aspx",
            "http://10.176.17.2/assets/app.js",
            "http://10.176.17.2/assets/main.css",
        ])
        self.assertEqual(links.attachments, [
            "http://10.176.17.2/UploadFiles/photo.jpg",
            "http://10.176.17.2/UploadFiles/guide.zip",
            "http://10.176.17.2/UploadFiles/lazy.jpg",
            "http://10.176.17.2/UploadFiles/background.png",
            "http://10.176.17.2/UploadFiles/poster.jpg",
        ])

    def test_extraction_handles_entities_duplicate_attributes_and_script_text(self):
        extract = getattr(crawler, "extract_page_links", None)
        self.assertTrue(callable(extract), "single-pass dependency extraction is missing")
        links = extract('''
            <!-- <img src="/UploadFiles/comment.jpg"> -->
            <script>const example = '<img src="/UploadFiles/script.jpg">';</script>
            <A HREF="/Item/2.aspx" href="/Item/3.aspx">last attribute</A>
            <a href="/notice&amp;info.aspx">entity</a>
            <a href="folder/">directory</a>
        ''', "http://10.176.17.2/")
        self.assertEqual(links.attachments, [])
        self.assertEqual(links.navigation, [
            "http://10.176.17.2/Item/3.aspx",
            "http://10.176.17.2/notice&info.aspx",
            "http://10.176.17.2/folder/",
        ])
        self.assertEqual(links.directory_links, [
            "/Item/3.aspx", "/notice&info.aspx", "folder/",
        ])


class FileSaveTests(unittest.TestCase):
    def test_unchanged_stream_keeps_file_without_allocating_a_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.bin"
            target.write_bytes(b"abcdef")
            before = target.stat()
            with mock.patch.object(
                crawler.tempfile, "NamedTemporaryFile",
                side_effect=AssertionError("unchanged downloads must not write scratch files"),
            ):
                self.assertTrue(crawler.save_chunks([b"", b"ab", b"cdef"], str(target), "http://example.test/asset"))
            self.assertEqual(target.read_bytes(), b"abcdef")
            self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)

    def test_stream_changes_preserve_the_complete_incoming_content(self):
        cases = [
            (b"abcdef", [b"ab", b"XY", b"ef"], b"abXYef"),
            (b"abcdef", [b"ab"], b"ab"),
            (b"ab", [b"ab", b"cdef"], b"abcdef"),
            (b"abcdef", [], b""),
            (None, [], b""),
            (None, [b"new"], b"new"),
            (b"a" * 1_500_000 + b"old", [b"a" * 1_500_000, b"new"], b"a" * 1_500_000 + b"new"),
        ]
        for old, chunks, expected in cases:
            with self.subTest(old_size=None if old is None else len(old)), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "asset.bin"
                if old is not None:
                    target.write_bytes(old)
                self.assertTrue(crawler.save_chunks(chunks, str(target), "http://example.test/asset"))
                self.assertEqual(target.read_bytes(), expected)
                self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_interrupted_download_keeps_old_file_and_removes_scratch_file(self):
        def chunks():
            yield b"changed"
            raise OSError("connection lost")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.bin"
            target.write_bytes(b"old content")
            with self.assertLogs(level="ERROR"):
                self.assertFalse(crawler.save_chunks(chunks(), str(target), "http://example.test/asset"))
            self.assertEqual(target.read_bytes(), b"old content")
            self.assertEqual(list(Path(tmp).iterdir()), [target])
