import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nvhw_observer.__main__ import main
from nvhw_observer.functional import bdf_arg, new_report, run_opengl
from nvhw_observer.opengl import node_identity, select_device, Unsupported, verify_pixels


class OpenGLTests(unittest.TestCase):
    def test_full_target_identity_required(self):
        self.assertEqual(bdf_arg('0000:AB:1F.7'), '0000:ab:1f.7')
        for invalid in ('0', '01:00.0', '0000:01:20.0', '0000:01:00.8', '../../pci'):
            with self.assertRaises(ValueError):
                bdf_arg(invalid)

    def test_device_matching_rejects_wrong_unknown_software_and_ambiguous(self):
        target = {'identity': {'bdf': '0000:01:00.0', 'vendor': '0x10de'}}
        intel = {'identity': {'bdf': '0000:00:02.0', 'vendor': '0x8086'}}
        self.assertIs(select_device([intel, {}, target], '0000:01:00.0'), target)
        for rows in ([intel, {}], [target, target], [dict(target, software=True)]):
            with self.assertRaises(Unsupported):
                select_device(rows, '0000:01:00.0')
        with self.assertRaises(Unsupported):
            select_device([intel], '0000:00:02.0')

    def test_drm_identity_follows_device_symlink_without_gpu_index_assumption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pci = root / '0000:09:00.0'
            pci.mkdir()
            (pci / 'vendor').write_text('0x10de\n')
            (pci / 'device').write_text('0x1e09\n')
            node = root / 'renderD137'
            node.mkdir()
            (node / 'device').symlink_to(pci)
            self.assertEqual(node_identity('/dev/dri/renderD137', root)['bdf'], '0000:09:00.0')
            for invalid in ('/dev/dri/card2-HDMI-A-1', '/tmp/renderD137', '/dev/dri/../config'):
                with self.assertRaises(ValueError):
                    node_identity(invalid, root)

    def test_glvnd_duplicate_pci_devices_require_unique_nvidia_driver(self):
        base = {'identity': {'bdf': '0000:01:00.0', 'vendor': '0x10de'}}
        nvidia = dict(base, driver_name='nvidia')
        mesa = dict(base, driver_name='nouveau')
        self.assertIs(select_device([mesa, nvidia], '0000:01:00.0'), nvidia)
        for rows in ([mesa], [base, mesa], [nvidia, nvidia]):
            with self.assertRaises(Unsupported):
                select_device(rows, '0000:01:00.0')

    @staticmethod
    def reference(seed):
        # Separate incremental CPU construction; no call into the tested oracle.
        raw = bytearray()
        green = seed * 2
        for y in range(64):
            red = seed
            for x in range(64):
                raw.extend((red % 256, green % 256, ((x ^ y) + seed * 7) % 256, 255))
                red += 3
            green += 5
        return raw

    def test_oracle_checks_every_pixel_and_alpha(self):
        raw = self.reference(11)
        self.assertEqual(raw[:4], bytes((11, 22, 77, 255)))
        self.assertEqual(raw[-4:], bytes((200, 81, 77, 255)))
        self.assertEqual(verify_pixels(raw, 11)['mismatched_pixels'], 0)
        raw[4*1937+3] = 254
        result = verify_pixels(raw, 11)
        self.assertEqual(result['mismatched_pixels'], 1)
        self.assertEqual(result['max_channel_error'], 1)
        self.assertNotEqual(result['rgba_sha256'], result['expected_sha256'])

    def test_oracle_rejects_clear_only_stale_frame_and_truncation(self):
        self.assertEqual(verify_pixels(bytes(64*64*4), 11)['mismatched_pixels'], 4096)
        self.assertEqual(verify_pixels(self.reference(11), 83)['mismatched_pixels'], 4096)
        with self.assertRaises(ValueError):
            verify_pixels(bytes(64*64*4-1), 11)

    def test_timeout_preserves_boundary_and_never_infers_other_features(self):
        checkpoint = new_report('0000:01:00.0')
        checkpoint['boundaries']['context_created'] = True
        raw = json.dumps({'report': checkpoint, 'final': False}).encode() + b'\n{truncated'
        with patch('nvhw_observer.functional.subprocess.run', side_effect=
                   subprocess.TimeoutExpired('worker', 5, output=raw)):
            report = run_opengl('0000:01:00.0', 5)
        self.assertEqual(report['functional_results']['opengl']['status'], 'timeout')
        self.assertTrue(report['boundaries']['context_created'])
        self.assertFalse(report['boundaries']['output_validated'])
        for name in ('compute', 'nvdec', 'nvenc', 'hardware_rt'):
            self.assertEqual(report['functional_results'][name]['status'], 'not_measured')

    def test_worker_crash_and_missing_final_are_not_success(self):
        for returncode in (0, -11):
            with patch('nvhw_observer.functional.subprocess.run', return_value=
                       subprocess.CompletedProcess([], returncode, b'noise\n', b'')):
                report = run_opengl('0000:01:00.0')
            self.assertEqual(report['functional_results']['opengl']['status'], 'error')

    def test_existing_output_is_rejected_before_gpu_work(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'evidence.json'
            output.write_text('original')
            with patch('nvhw_observer.functional.run_opengl') as probe, \
                    contextlib.redirect_stderr(io.StringIO()):
                code = main(['test-opengl', '--bdf', '0000:01:00.0', '--output', str(output)])
            self.assertEqual(code, 2)
            probe.assert_not_called()
            self.assertEqual(output.read_text(), 'original')

    def test_timeout_is_bounded_before_native_calls(self):
        for timeout in (0, -1, 121, float('nan'), float('inf')):
            with patch('nvhw_observer.functional.subprocess.run') as native:
                with self.assertRaises(ValueError):
                    run_opengl('0000:01:00.0', timeout)
                native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
