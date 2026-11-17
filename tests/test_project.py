import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from nvhw_observer.__main__ import main
from nvhw_observer.inventory import collect
from nvhw_observer.profiles import CATALOG, identify
from nvhw_observer.report import envelope, validate
from test_authority import fixture
from test_observer import EFI, SOURCE


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def card(self, bdf='0000:03:00.0', **replace):
        path = self.root / bdf
        path.mkdir()
        fields = dict(vendor='0x10de', device='0x1e09', subsystem_vendor='0x10de',
                      subsystem_device='0x1554', revision='0xa1', **{'class': '0x030200'})
        fields.update(replace)
        for name, value in fields.items():
            if value is not None:
                (path / name).write_text(value + '\n')
        return path

    def test_inventory_is_not_fixed_to_original_bus_and_ignores_mmio_and_rom(self):
        path = self.card()
        for name in ('config', 'rom', 'resource0'):
            (path / name).mkdir()  # Opening these as files would fail the test.
        (path / 'driver').symlink_to('/unneeded/private/path/nvidia')
        report = collect(self.root)
        self.assertEqual(report['devices'][0]['bdf'], '0000:03:00.0')
        self.assertEqual(report['devices'][0]['driver'], 'nvidia')
        profile = report['devices'][0]['profile']
        self.assertEqual(profile['pci_candidates'], ['cmp50hx-tu102-reference'])
        self.assertFalse(profile['board_and_rom_verified'])
        self.assertFalse(profile['register_profile_enabled'])
        self.assertNotIn('/unneeded/private', json.dumps(report))
        validate(report)

    def test_same_device_different_board_does_not_inherit_profile(self):
        self.card(subsystem_device='0x9999')
        self.assertEqual(collect(self.root)['devices'][0]['profile']['pci_candidates'], [])

    def test_read_error_is_unknown_not_zero_or_missing_device(self):
        self.card(device=None, revision='invalid')
        device = collect(self.root)['devices'][0]
        self.assertIsNone(device['identity']['device'])
        self.assertIsNone(device['identity']['revision'])
        self.assertIn('device', device['identity_errors'])
        self.assertEqual(device['profile']['pci_candidates'], [])

    def test_unknown_vendor_read_failure_is_reported(self):
        self.card(vendor=None)
        result = collect(self.root)
        self.assertFalse(result['devices'])
        self.assertEqual(len(result['enumeration_errors']), 1)

    def test_several_devices_remain_separate_and_other_vendor_is_ignored(self):
        self.card('0000:03:00.0')
        self.card('0000:04:00.0', device='0x9999')
        self.card('0000:05:00.0', vendor='0x8086')
        rows = collect(self.root)['devices']
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]['profile']['pci_candidates'])
        self.assertFalse(rows[1]['profile']['pci_candidates'])

    def test_pending_cards_cannot_match_or_enable_registers(self):
        for profile in CATALOG[1:]:
            self.assertIsNone(profile['pci_identity'])
            self.assertFalse(profile['register_profile_enabled'])
        self.assertFalse(identify({})['register_profile_enabled'])

    def test_inventory_cannot_be_promoted_to_functional_unlock(self):
        report = envelope('pci_inventory')
        report['devices'] = []
        report['functional_results']['nvdec'] = {'status': 'pass', 'evidence': []}
        with self.assertRaises(ValueError):
            validate(report)
        report['functional_results'].pop('hardware_rt')
        with self.assertRaises(ValueError):
            validate(report)

    def parse_cli(self, text):
        log = self.root / 'input.log'
        log.write_text(text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['analyze-v6', str(log), '--efi-sha256', EFI,
                         '--source-sha256', SOURCE])
        return code, json.loads(out.getvalue())

    def test_cli_complete_capture_never_claims_functional_codec_or_rt(self):
        code, result = self.parse_cli(fixture())
        self.assertEqual(code, 0)
        self.assertTrue(result['analysis']['protocol_complete'])
        self.assertTrue(result['analysis']['core']['compute_readback_confirmed'])
        self.assertTrue(all(r['status'] == 'not_measured'
                            for r in result['functional_results'].values()))

    def test_cli_truncation_and_build_mismatch_fail(self):
        for text in (fixture()[:1000], fixture().replace('source_sha256=' + SOURCE,
                                                       'source_sha256=' + 'c' * 64)):
            code, result = self.parse_cli(text)
            self.assertEqual(code, 2)
            self.assertTrue(result['analysis']['errors'])

    def test_cli_preserves_existing_report(self):
        target = self.root / 'existing.json'
        target.write_text('original evidence')
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(['profiles', '--output', str(target)])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(), 'original evidence')


if __name__ == '__main__':
    unittest.main()
