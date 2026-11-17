import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('release_tool',Path(__file__).resolve().parents[1]/'tools/release.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.base=Path(t.name);self.root=self.base/'source';self.root.mkdir()
        (self.root/'README.md').write_text('Example project\n')
        (self.root/'public-files.txt').write_text('README.md\npublic-files.txt\n')

    def test_unlisted_capture_is_not_silently_exported(self):
        (self.root/'capture.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'unreviewed file'):r.export(self.root,self.base/'out')
        self.assertFalse((self.base/'out').exists())

    def test_secret_failure_reports_only_path_and_category(self):
        secret='ghp_'+'x'*36
        (self.root/'README.md').write_text(secret)
        with self.assertRaises(ValueError) as error:r.check(self.root)
        self.assertNotIn(secret,str(error.exception));self.assertIn('github-token',str(error.exception))

    def test_traversal_and_symlink_rejected(self):
        (self.root/'public-files.txt').write_text('../outside\n')
        with self.assertRaisesRegex(ValueError,'invalid public path'):r.check(self.root)
        (self.root/'public-files.txt').write_text('README.md\npublic-files.txt\n')
        (self.root/'README.md').unlink();(self.root/'README.md').symlink_to(self.base/'outside')
        with self.assertRaisesRegex(ValueError,'symlink'):r.check(self.root)

    def test_parent_private_history_and_cache_not_exported(self):
        (self.base/'private.json').write_text('private')
        for folder in ('.git','__pycache__'):
            (self.root/folder).mkdir();(self.root/folder/'private').write_text('private')
        output=self.base/'export';archive=self.base/'source.tar.gz'
        result=r.export(self.root,output,archive)
        self.assertEqual(result['files'],2);self.assertFalse(result['published'])
        r.check(output)
        with tarfile.open(archive) as t:
            self.assertEqual(t.getnames(),['NVHW-observer/README.md','NVHW-observer/SHA256SUMS','NVHW-observer/public-files.txt'])

    def test_exports_are_reproducible_and_refuse_overwrite(self):
        a=r.export(self.root,self.base/'a',self.base/'a.tar.gz')
        b=r.export(self.root,self.base/'b',self.base/'b.tar.gz')
        self.assertEqual(a,b)
        with self.assertRaises(ValueError):r.export(self.root,self.base/'a')
        (self.base/'a/README.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'SHA256SUMS mismatch'):r.check(self.base/'a')

    def test_local_links_must_be_public_and_present(self):
        (self.root/'README.md').write_text('[private](../archive/report.md)')
        with self.assertRaisesRegex(ValueError,'nonpublic link'):r.check(self.root)


if __name__=='__main__':unittest.main()
