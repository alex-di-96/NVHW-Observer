import contextlib
import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from nvhw_observer.__main__ import main
from nvhw_observer.functional import new_report, run_opengl
from nvhw_observer.glx import select_gl_device, valid_framebuffer
from nvhw_observer.opengl import Unsupported


class GLXTests(unittest.TestCase):
    def test_prime_double_buffer_is_valid_but_msaa_or_missing_alpha_is_not(self):
        bits = dict(red=8, green=8, blue=8, alpha=8, doublebuffer=1, samples=0)
        self.assertTrue(valid_framebuffer(bits))
        self.assertTrue(valid_framebuffer(dict(bits, doublebuffer=0)))
        self.assertFalse(valid_framebuffer(dict(bits, alpha=0)))
        self.assertFalse(valid_framebuffer(dict(bits, samples=4)))

    def test_current_gl_device_must_be_exclusively_requested_pci_gpu(self):
        target = {'cuda_device': 4, 'bdf': '0000:09:00.0'}
        self.assertIs(select_gl_device([target], '0000:09:00.0'), target)
        for rows in ([], [dict(target, bdf='0000:02:00.0')], [target, target]):
            with self.assertRaises(Unsupported):
                select_gl_device(rows, '0000:09:00.0')

    def test_backend_options_rejected_before_native_calls(self):
        with patch('nvhw_observer.functional.subprocess.run') as native:
            for kwargs in ({'backend': 'unknown'}, {'interop': True}, {'display': ':0'},
                           {'provider': 'NVIDIA-G0'}):
                with self.assertRaises(ValueError):
                    run_opengl('0000:01:00.0', **kwargs)
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                run_opengl('0000:01:00.0', backend='glx')
            native.assert_not_called()

    def test_glx_routes_provider_without_changing_parent_environment(self):
        with patch.dict(os.environ, {'DISPLAY': ':7', '__NV_PRIME_RENDER_OFFLOAD_PROVIDER': 'old'}):
            before = os.environ.copy()
            with patch('nvhw_observer.functional.subprocess.run', return_value=
                       subprocess.CompletedProcess([], 0, b'', b'')) as native:
                run_opengl('0000:01:00.0', backend='glx', display=':0', provider='NVIDIA-G1', interop=True)
                command = native.call_args.args[0]
                env = native.call_args.kwargs['env']
                self.assertEqual(command[-3:], ['0000:01:00.0', ':0', 'interop'])
                self.assertIn('nvhw_observer.glx', command)
                self.assertEqual(env['__NV_PRIME_RENDER_OFFLOAD_PROVIDER'], 'NVIDIA-G1')
                self.assertEqual(env['__GLX_VENDOR_LIBRARY_NAME'], 'nvidia')
                self.assertEqual(env['DISPLAY'], ':0')
            self.assertEqual(dict(os.environ), before)

    def test_wrong_backend_report_is_not_accepted(self):
        wrong = new_report('0000:01:00.0')
        wrong['functional_results']['opengl']['status'] = 'pass'
        raw = json.dumps({'report': wrong, 'final': True}).encode()
        with patch('nvhw_observer.functional.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 0, raw, b'')):
            report = run_opengl('0000:01:00.0', backend='glx', display=':0')
        self.assertEqual(report['functional_results']['opengl']['status'], 'error')
        self.assertEqual(report['kind'], 'opengl_glx')

    def test_interop_failure_does_not_erase_render_success_but_cli_fails(self):
        result = new_report('0000:01:00.0', 'opengl_glx')
        result['functional_results']['opengl']['status'] = 'pass'
        result['gl_cuda_interop'] = {'status': 'error', 'errors': ['registration failed']}
        with patch('nvhw_observer.functional.run_opengl', return_value=result), \
                contextlib.redirect_stdout(io.StringIO()) as stream:
            code = main(['test-opengl', '--bdf', '0000:01:00.0', '--backend', 'glx',
                         '--display', ':0', '--interop'])
        self.assertEqual(code, 2)
        emitted = json.loads(stream.getvalue())
        self.assertEqual(emitted['functional_results']['opengl']['status'], 'pass')
        self.assertEqual(emitted['functional_results']['compute']['status'], 'not_measured')


if __name__ == '__main__':
    unittest.main()
