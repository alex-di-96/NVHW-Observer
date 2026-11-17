"""M2 review boundary and transport controls, synthetic logs only."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nvhw_observer.passive_m1 import analyze
from test_m1 import fixture, MANIFEST, PROFILE

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('efi_builder', ROOT/'uefi/build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
M2 = json.loads((ROOT/'uefi/profiles/cmp50hx-tu102-reference-m2.json').read_text())


class M2Tests(unittest.TestCase):
    def manifest(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest['profile'] = M2
        return manifest

    def test_reviewed_delta_preserves_old_observations_and_identity(self):
        self.assertEqual(builder.load_profile('m1')[1], PROFILE)
        self.assertEqual(builder.load_profile('m2')[1], M2)
        self.assertEqual(M2['registers'], PROFILE['registers'] + ['00021d68'])
        for key in ('pci_id', 'subsystem_id', 'boot0', 'rom', 'successor_sha256'):
            self.assertEqual(M2[key], PROFILE[key])

    def test_unreviewed_address_or_identity_changes_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'profiles').mkdir()
            baseline = ROOT/'uefi/profiles/cmp50hx-tu102-reference-m1.json'
            (root/'profiles'/baseline.name).write_bytes(baseline.read_bytes())
            for key, value in [('registers', M2['registers'] + ['00021414']),
                               ('registers', M2['registers'][:-1] + ['00625488']),
                               ('pci_id', '220d10de'), ('successor_sha256', '0'*64)]:
                changed = dict(M2, **{key: value})
                (root/'profiles/cmp50hx-tu102-reference-m2.json').write_text(json.dumps(changed))
                with patch.object(builder, 'HERE', root), self.assertRaises(ValueError):
                    builder.load_profile('m2')
            (root/'profiles'/baseline.name).write_text('{}')
            with patch.object(builder, 'HERE', root), self.assertRaises(ValueError):
                builder.load_profile('m1')

    def test_new_word_is_observation_not_encoder_activation(self):
        result = analyze(fixture(profile=M2), self.manifest())
        self.assertFalse(result['errors'])
        self.assertTrue(result['capture_complete'])
        self.assertEqual(len(result['words']), 91)
        self.assertEqual(result['functional_tests'], 'not_measured')

    def test_poison_status_retains_unknown_and_raw(self):
        result = analyze(fixture(profile=M2, poison=True, poison_address='00021d68'), self.manifest())
        self.assertFalse(result['errors'])
        self.assertFalse(result['diagnostics_complete'])
        word = next(w for w in result['words'] if w['address'] == 0x21d68)
        self.assertIsNone(word['value'])
        self.assertEqual(word['raw_value'], 0xbadf1301)

    def test_m1_log_cannot_satisfy_m2_manifest(self):
        result = analyze(fixture(), self.manifest())
        self.assertTrue(result['errors'])
        self.assertFalse(result['capture_complete'])


if __name__ == '__main__':
    unittest.main()
