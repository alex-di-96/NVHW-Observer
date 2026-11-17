import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from .inventory import collect
from .profiles import CATALOG
from .report import envelope, validate
from . import __version__


def sha_arg(value):
    if not re.fullmatch('[0-9a-fA-F]{64}', value):
        raise argparse.ArgumentTypeError('expected a SHA-256 digest')
    return value.lower()


def emit(value, output):
    text = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    if output:
        # Never overwrite a previous experiment's evidence.
        with output.open('x', encoding='utf-8') as stream:
            stream.write(text)
    else:
        print(text, end='')


def main(argv=None):
    parser = argparse.ArgumentParser(description='NVHW-observer research tools')
    parser.add_argument('--version', action='version', version='%(prog)s '+__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    inv = sub.add_parser('inventory', help='PCI identity only; no BAR/config/ROM access')
    inv.add_argument('--pci-root', type=Path, default=Path('/sys/bus/pci/devices'))
    inv.add_argument('--output', type=Path)
    profiles = sub.add_parser('profiles', help='planned boards and validation state')
    profiles.add_argument('--output', type=Path)
    gl = sub.add_parser('test-opengl', help='explicit NVIDIA EGLDevice shader/pixel test')
    gl.add_argument('--bdf', required=True, help='full PCI BDF, e.g. 0000:01:00.0')
    gl.add_argument('--timeout', type=float, default=30)
    gl.add_argument('--backend', choices=('egl', 'glx'), default='egl')
    gl.add_argument('--display', help='existing X display for GLX')
    gl.add_argument('--provider', help='NVIDIA PRIME provider, e.g. NVIDIA-G0')
    gl.add_argument('--interop', action='store_true', help='also validate GL/CUDA buffer round trip (GLX)')
    gl.add_argument('--output', type=Path)
    log = sub.add_parser('analyze-v6', help='offline archived TU102 v6 log analysis')
    log.add_argument('log', type=Path)
    log.add_argument('--efi-sha256', required=True, type=sha_arg)
    log.add_argument('--source-sha256', required=True, type=sha_arg)
    log.add_argument('--output', type=Path)
    passive = sub.add_parser('analyze-m1', help='offline NVHW passive M1 log analysis')
    passive.add_argument('log', type=Path)
    passive.add_argument('--manifest', required=True, type=Path)
    passive.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'test-opengl':
            from .functional import run_opengl
            # Reserve the output before any GPU work; refuse existing evidence.
            stream = args.output.open('x', encoding='utf-8') if args.output else None
            try:
                value = run_opengl(args.bdf, args.timeout, args.backend, args.display, args.provider, args.interop)
                if stream:
                    json.dump(value, stream, indent=2, ensure_ascii=False)
                    stream.write('\n')
                else:
                    emit(value, None)
                passed = value['functional_results']['opengl']['status'] == 'pass'
                if args.interop:
                    passed = passed and value.get('gl_cuda_interop', {}).get('status') == 'pass'
                return 0 if passed else 2
            finally:
                if stream:
                    stream.close()
        elif args.command == 'profiles':
            value = {'schema': 'hwt.profile-catalog.v1', 'profiles': CATALOG}
            code = 0
        elif args.command == 'inventory':
            value = collect(args.pci_root)
            validate(value)
            code = 0 if not value['enumeration_errors'] and all(
                not d['identity_errors'] and not d['driver_error'] for d in value['devices']) else 2
        elif args.command == 'analyze-m1':
            from .passive_m1 import analyze
            raw = args.log.read_bytes()
            manifest_bytes = args.manifest.read_bytes()
            value = envelope('uefi_passive_m1')
            value['input'] = {'log_sha256': hashlib.sha256(raw).hexdigest(),
                              'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}
            value['analysis'] = analyze(raw.decode('utf-8'), json.loads(manifest_bytes))
            validate(value)
            result = value['analysis']
            code = 0 if not result['errors'] and result['capture_complete'] and result['diagnostics_complete'] else 2
        else:
            from .legacy_v6.authority import analyze
            raw = args.log.read_bytes()
            value = envelope('uefi_v6_log')
            value['input'] = {'log_sha256': hashlib.sha256(raw).hexdigest(),
                              'expected_efi_sha256': args.efi_sha256,
                              'expected_source_sha256': args.source_sha256}
            value['analysis'] = analyze(raw.decode('utf-8'), args.efi_sha256, args.source_sha256)
            validate(value)
            result = value['analysis']
            # Cancellation/no-target is a valid negative control but not a complete capture.
            code = 0 if not result['errors'] and result['protocol_complete'] and result['diagnostics_complete'] else 2
        emit(value, args.output)
        return code
    except (OSError, UnicodeError, ValueError) as exc:
        print(f'nvhw-observer: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
