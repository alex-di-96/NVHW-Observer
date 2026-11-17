"""Explicit functional probes; inventory and historical log schemas stay unchanged."""
from datetime import datetime, timezone
import json
import math
import os
import re
import subprocess
import sys

from . import __version__

FEATURES = ('compute', 'nvdec', 'nvenc', 'hardware_rt', 'opengl')
BOUNDARIES = ('target_verified', 'context_created', 'shader_linked',
              'work_submitted', 'readback_completed', 'output_validated')


def bdf_arg(value):
    if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-1][0-9a-fA-F]\.[0-7]', value):
        raise ValueError('expected full PCI BDF, e.g. 0000:01:00.0')
    return value.lower()


def new_report(bdf, kind='opengl_egl_device'):
    return {'schema': 'nvhw.functional.v1', 'tool_version': __version__,
            'kind': kind, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'requested_bdf': bdf_arg(bdf),
            'functional_results': {
                name: {'status': 'not_measured'} for name in FEATURES},
            'boundaries': dict.fromkeys(BOUNDARIES, False), 'errors': [],
            'limitations': ['Small shader correctness test, not a performance benchmark.',
                            'No visible screen, remote input or scanout validation.',
                            'No codec, CUDA or hardware RT result inferred from OpenGL.']}


def run_opengl(bdf, timeout=30, backend='egl', display=None, provider=None, interop=False):
    bdf = bdf_arg(bdf)
    if not math.isfinite(timeout) or not 1 <= timeout <= 120:
        raise ValueError('timeout must be between 1 and 120 seconds')
    if backend not in ('egl', 'glx'):
        raise ValueError('backend must be egl or glx')
    if backend == 'egl' and (display is not None or provider is not None or interop):
        raise ValueError('display, provider and interop options require the glx backend')
    kind = 'opengl_glx' if backend == 'glx' else 'opengl_egl_device'
    result = new_report(bdf, kind)
    env = os.environ.copy()
    if backend == 'egl':
        for key in ('DISPLAY', 'WAYLAND_DISPLAY'):
            env.pop(key, None)
        command = [sys.executable, '-B', '-m', 'nvhw_observer.opengl', bdf]
    else:
        display = display or env.get('DISPLAY')
        if not display:
            raise ValueError('GLX requires --display or DISPLAY')
        env['DISPLAY'] = display
        env['__NV_PRIME_RENDER_OFFLOAD'] = '1'
        env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia'
        if provider:
            env['__NV_PRIME_RENDER_OFFLOAD_PROVIDER'] = provider
        else:
            env.pop('__NV_PRIME_RENDER_OFFLOAD_PROVIDER', None)
        command = [sys.executable, '-B', '-m', 'nvhw_observer.glx', bdf, display,
                   'interop' if interop else 'render']
    try:
        process = subprocess.run(command, env=env, capture_output=True, timeout=timeout)
        raw, err = process.stdout, process.stderr
        outcome = None if process.returncode == 0 else 'error'
        detail = None if outcome is None else f'worker exit {process.returncode}'
    except subprocess.TimeoutExpired as exc:
        raw, err = exc.stdout or b'', exc.stderr or b''
        outcome, detail = 'timeout', f'worker exceeded {timeout:g} seconds'
    # Each flushed line is a full boundary checkpoint, useful even after a crash.
    final_received = False
    for line in raw.decode('utf-8', 'replace').splitlines():
        try:
            event = json.loads(line)
            candidate = event['report']
            if (candidate.get('schema') == 'nvhw.functional.v1'
                    and candidate.get('requested_bdf') == bdf
                    and candidate.get('kind') == kind):
                result, final_received = candidate, event.get('final') is True
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if outcome is None and not final_received:
        outcome, detail = 'error', 'worker did not emit a final report'
    if outcome:
        result['functional_results']['opengl']['status'] = outcome
        result['errors'].append(detail)
    result['worker'] = {'final_received': final_received, 'timeout_seconds': timeout,
                        'stderr': err.decode('utf-8', 'replace')[-4096:]}
    return result
