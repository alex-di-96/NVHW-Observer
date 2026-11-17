"""NVIDIA GLX pbuffer probe and optional GL/CUDA buffer round trip.

Uses the existing X server. No X configuration, mode or window changes.
CUDA's current-GL-context device query verifies the exact PCI GPU before drawing.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

from .functional import bdf_arg, new_report
from .opengl import I, U, P, S, IP, PP, WIDTH, HEIGHT, SEEDS, VERTEX, FRAGMENT
from .opengl import Unsupported, decode, render

L = C.c_ulong


class XError(C.Structure):
    _fields_ = [('type', I), ('display', P), ('resourceid', L), ('serial', L),
                ('error_code', C.c_ubyte), ('request_code', C.c_ubyte), ('minor_code', C.c_ubyte)]


class GLX:
    def __init__(self):
        self.x = C.CDLL('libX11.so.6')
        self.lib = C.CDLL('libGLX.so.0')
        for name, ret, args in [
            ('XOpenDisplay', P, (S,)), ('XDefaultScreen', I, (P,)),
            ('XCloseDisplay', I, (P,)), ('XFree', I, (P,)),
            ('XSync', I, (P, I)), ('XSetErrorHandler', P, (P,))]:
            fn = getattr(self.x, name); fn.restype, fn.argtypes = ret, args
        for name, ret, args in [
            ('glXGetProcAddressARB', P, (S,)), ('glXQueryVersion', I, (P, IP, IP)),
            ('glXQueryExtensionsString', S, (P, I)),
            ('glXChooseFBConfig', PP, (P, I, IP, IP)),
            ('glXGetFBConfigAttrib', I, (P, P, I, IP)),
            ('glXCreatePbuffer', L, (P, P, IP)), ('glXDestroyPbuffer', None, (P, L)),
            ('glXMakeContextCurrent', I, (P, L, L, P)),
            ('glXDestroyContext', None, (P, P)), ('glXIsDirect', I, (P, P))]:
            fn = getattr(self.lib, name); fn.restype, fn.argtypes = ret, args

    def proc(self, name, result, *args):
        address = self.lib.glXGetProcAddressARB(name.encode())
        if not address:
            raise Unsupported('missing GLX/GL entry point ' + name)
        return C.CFUNCTYPE(result, *args)(address)


class CUDA:
    def __init__(self):
        self.lib = C.CDLL('libcuda.so.1')

    def call(self, name, args, *values):
        fn = getattr(self.lib, name)
        fn.argtypes, fn.restype = args, I
        status = fn(*values)
        if status:
            raise RuntimeError(f'{name}: CUDA status {status}')

    def gl_devices(self):
        self.call('cuInit', [U], 0)
        count, devices = U(), (I * 32)()
        self.call('cuGLGetDevices', [C.POINTER(U), IP, U, U], C.byref(count), devices, 32, 1)
        if not 0 < count.value <= 32:
            raise Unsupported('current GL context has no unambiguous CUDA device mapping')
        rows = []
        for ordinal in devices[:count.value]:
            bdf = C.create_string_buffer(32)
            self.call('cuDeviceGetPCIBusId', [S, I, I], bdf, len(bdf), ordinal)
            rows.append({'cuda_device': ordinal, 'bdf': bdf_arg(decode(bdf.value))})
        return rows


def select_gl_device(rows, bdf):
    # A multi-GPU context is not evidence for rendering solely on one requested GPU.
    if len(rows) != 1 or rows[0].get('bdf') != bdf:
        raise Unsupported('current GL context does not map exclusively to requested PCI GPU')
    return rows[0]


def valid_framebuffer(bits):
    return (all(bits.get(name) == 8 for name in ('red', 'green', 'blue', 'alpha'))
            and bits.get('doublebuffer') in (0, 1) and bits.get('samples') == 0)


def roundtrip(glx, cuda, device, report, checkpoint):
    """64 KiB GL upload -> CUDA read/write -> GL readback, with proper ownership."""
    result = {'status': 'not_measured', 'bytes': 65536, 'registered': False,
              'mapped': False, 'cuda_read_verified': False, 'gl_read_verified': False,
              'errors': [], 'cleanup_errors': []}
    report['gl_cuda_interop'] = result
    gl = glx.proc
    buffer, context, resource = U(), P(), P()
    mapped = False
    def check_gl(where):
        error = gl('glGetError', U)()
        if error:
            raise RuntimeError(f'{where}: GL error 0x{error:04x}')
    try:
        initial = bytes((i*17+29) & 255 for i in range(result['bytes']))
        upload = (C.c_ubyte * len(initial)).from_buffer_copy(initial)
        gl('glGenBuffers', None, I, C.POINTER(U))(1, C.byref(buffer))
        gl('glBindBuffer', None, U, U)(0x8892, buffer.value)
        gl('glBufferData', None, U, C.c_ssize_t, P, U)(0x8892, len(initial), upload, 0x88E8)
        check_gl('GL buffer upload')
        cuda.call('cuCtxCreate_v2', [PP, U, I], C.byref(context), 0, device)
        cuda.call('cuGraphicsGLRegisterBuffer', [PP, U, U], C.byref(resource), buffer.value, 0)
        result['registered'] = True
        checkpoint()
        cuda.call('cuGraphicsMapResources', [U, PP, P], 1, C.byref(resource), None)
        mapped = True; result['mapped'] = True
        pointer, size = C.c_ulonglong(), C.c_size_t()
        cuda.call('cuGraphicsResourceGetMappedPointer_v2', [C.POINTER(C.c_ulonglong), C.POINTER(C.c_size_t), P],
                  C.byref(pointer), C.byref(size), resource)
        if size.value != len(initial):
            raise RuntimeError('mapped GL buffer size mismatch')
        copied = (C.c_ubyte * len(initial))()
        cuda.call('cuMemcpyDtoH_v2', [P, C.c_ulonglong, C.c_size_t], copied, pointer, len(initial))
        result['cuda_read_verified'] = bytes(copied) == initial
        if not result['cuda_read_verified']:
            raise RuntimeError('CUDA read differs from GL upload')
        cuda.call('cuMemsetD8_v2', [C.c_ulonglong, C.c_ubyte, C.c_size_t], pointer, 0xA5, len(initial))
        cuda.call('cuCtxSynchronize', [])
        cuda.call('cuGraphicsUnmapResources', [U, PP, P], 1, C.byref(resource), None)
        mapped = False
        gl('glGetBufferSubData', None, U, C.c_ssize_t, C.c_ssize_t, P)(0x8892, 0, len(initial), copied)
        check_gl('GL interop readback')
        result['gl_read_verified'] = bytes(copied) == bytes([0xA5]) * len(initial)
        result['initial_sha256'] = hashlib.sha256(initial).hexdigest()
        result['final_sha256'] = hashlib.sha256(copied).hexdigest()
        if not result['gl_read_verified']:
            raise RuntimeError('GL read differs from CUDA write')
        result['status'] = 'pass'
        checkpoint()
    except (OSError, RuntimeError, AttributeError) as exc:
        result['status'] = 'error'; result['errors'].append(str(exc))
    finally:
        steps = []
        if mapped:
            steps.append(('cuGraphicsUnmapResources', [U, PP, P], (1, C.byref(resource), None)))
        if resource.value:
            steps.append(('cuGraphicsUnregisterResource', [P], (resource,)))
        if context.value:
            steps.append(('cuCtxDestroy_v2', [P], (context,)))
        for name, types, values in steps:
            try:
                cuda.call(name, types, *values)
            except RuntimeError as exc:
                result['cleanup_errors'].append(str(exc))
        if buffer.value:
            gl('glDeleteBuffers', None, I, C.POINTER(U))(1, C.byref(buffer))
        if result['cleanup_errors']:
            result['status'] = 'error'


def probe(bdf, display_name, interop, emit):
    report = new_report(bdf, 'opengl_glx')
    report['test'] = {'size': [WIDTH, HEIGHT], 'seeds': list(SEEDS), 'pixel_tolerance': 0,
                      'vertex_sha256': hashlib.sha256(VERTEX).hexdigest(),
                      'fragment_sha256': hashlib.sha256(FRAGMENT).hexdigest()}
    report['source_sha256'] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ('glx.py', 'opengl.py', 'functional.py')}
    checkpoint = lambda: emit(report, False)
    glx = None
    display = configs = context = None
    pbuffer = 0
    previous_handler = None
    installed_handler = False
    xerrors = []
    error_handler_type = C.CFUNCTYPE(I, P, C.POINTER(XError))
    @error_handler_type
    def handler(_display, event):
        e = event.contents
        xerrors.append({'code': int(e.error_code), 'request': int(e.request_code),
                        'minor': int(e.minor_code)})
        return 0
    def sync(where):
        glx.x.XSync(display, 0)
        if xerrors:
            raise RuntimeError('X error during ' + where)
    checkpoint()
    try:
        glx = GLX()
        display = glx.x.XOpenDisplay(display_name.encode())
        if not display:
            raise Unsupported('cannot open requested X display (check DISPLAY/XAUTHORITY)')
        previous_handler = glx.x.XSetErrorHandler(C.cast(handler, P)); installed_handler = True
        screen = glx.x.XDefaultScreen(display)
        major, minor = I(), I()
        if not glx.lib.glXQueryVersion(display, C.byref(major), C.byref(minor)):
            raise Unsupported('GLX unavailable on requested display')
        extensions = decode(glx.lib.glXQueryExtensionsString(display, screen)).split()
        if (major.value, minor.value) < (1, 4) or not {
                'GLX_ARB_create_context', 'GLX_ARB_create_context_profile'} <= set(extensions):
            raise Unsupported('required GLX version/context extensions unavailable')
        attributes = (I * 17)(0x8010, 4, 0x8011, 1,
                              8, 8, 9, 8, 10, 8, 11, 8, 5, -1, 100001, 0, 0)
        count = I()
        configs = glx.lib.glXChooseFBConfig(display, screen, attributes, C.byref(count))
        if not configs or count.value < 1:
            raise Unsupported('no GLX RGBA8 pbuffer config')
        config = configs[0]
        bits = {}
        for name, enum in [('red', 8), ('green', 9), ('blue', 10), ('alpha', 11),
                           ('doublebuffer', 5), ('samples', 100001)]:
            value = I()
            if glx.lib.glXGetFBConfigAttrib(display, config, enum, C.byref(value)):
                raise RuntimeError('GLX framebuffer attribute query failed')
            bits[name] = value.value
        if not valid_framebuffer(bits):
            raise Unsupported('selected GLX framebuffer is not exact non-multisampled RGBA8')
        pbuffer = glx.lib.glXCreatePbuffer(display, config, (I * 5)(0x8041, WIDTH, 0x8040, HEIGHT, 0))
        sync('create pbuffer')
        if not pbuffer:
            raise RuntimeError('GLX pbuffer creation failed')
        create = glx.proc('glXCreateContextAttribsARB', P, P, P, P, I, IP)
        context = create(display, config, None, 1, (I * 7)(0x2091, 3, 0x2092, 3, 0x9126, 1, 0))
        sync('create context')
        if not context or not glx.lib.glXMakeContextCurrent(display, pbuffer, pbuffer, context):
            raise RuntimeError('cannot make GLX context current')
        sync('make current')
        direct = bool(glx.lib.glXIsDirect(display, context))
        report['glx'] = {'version': f'{major.value}.{minor.value}', 'surface': 'pbuffer',
                         'screen': screen, 'direct': direct, 'config': bits,
                         'window_system_connection': True, 'new_x_server': False}
        report['boundaries']['context_created'] = True
        checkpoint()
        if not direct:
            raise Unsupported('indirect GLX rendering is not accepted as GPU evidence')
        cuda = CUDA()
        rows = cuda.gl_devices()
        report['gl_cuda_devices'] = rows
        selected = select_gl_device(rows, bdf)
        pci = Path('/sys/bus/pci/devices')/bdf
        report['target'] = {'bdf': bdf, 'vendor': (pci/'vendor').read_text().strip(),
                            'device': (pci/'device').read_text().strip(),
                            'mapping': 'cuGLGetDevices(CU_GL_DEVICE_LIST_ALL) -> cuDeviceGetPCIBusId'}
        if report['target']['vendor'] != '0x10de':
            raise Unsupported('target PCI vendor is not NVIDIA')
        report['boundaries']['target_verified'] = True
        checkpoint()
        # PRIME may expose only double-buffered configs; no swap/presentation needed.
        color_buffer = 0x0405 if bits['doublebuffer'] else 0x0404  # BACK / FRONT
        glx.proc('glDrawBuffer', None, U)(color_buffer)
        glx.proc('glReadBuffer', None, U)(color_buffer)
        render(glx, report, checkpoint)
        report['functional_results']['opengl'] = {'status': 'pass', 'frames': len(SEEDS),
                                                 'pixels_checked': WIDTH * HEIGHT * len(SEEDS)}
        if interop:
            roundtrip(glx, cuda, selected['cuda_device'], report, checkpoint)
    except Unsupported as exc:
        report['functional_results']['opengl'] = {'status': 'unsupported'}
        report['errors'].append(str(exc))
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        report['functional_results']['opengl'] = {'status': 'error'}
        report['errors'].append(str(exc))
    finally:
        cleanup = []
        if display:
            if context:
                if not glx.lib.glXMakeContextCurrent(display, 0, 0, None):
                    cleanup.append('GLX release current context failed')
                glx.lib.glXDestroyContext(display, context)
            if pbuffer:
                glx.lib.glXDestroyPbuffer(display, pbuffer)
            if configs:
                glx.x.XFree(configs)
            glx.x.XSync(display, 0)
            if installed_handler:
                glx.x.XSetErrorHandler(previous_handler)
            glx.x.XCloseDisplay(display)
        report['x_errors'] = xerrors
        report['cleanup_errors'] = cleanup
        if xerrors or cleanup:
            report['functional_results']['opengl']['status'] = 'error'
            report['errors'].extend(cleanup)
    emit(report, True)
    return report


if __name__ == '__main__':
    probe(sys.argv[1], sys.argv[2], sys.argv[3] == 'interop', lambda report, final: print(
        json.dumps({'report': report, 'final': final}), flush=True))
