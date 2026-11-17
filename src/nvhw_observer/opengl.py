"""Linux NVIDIA EGLDevice OpenGL test. Run through the bounded public CLI.

No X connection, GPU index assumption, driver changes or register access.
Only DRM/sysfs identity determines the EGLDevice used to create the context.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import sys

from .functional import new_report

I, U, P, S = C.c_int, C.c_uint, C.c_void_p, C.c_char_p
IP, PP = C.POINTER(I), C.POINTER(P)
WIDTH, HEIGHT = 64, 64
SEEDS = (11, 83)
VERTEX = b'''#version 330 core
void main() {
    vec2 p[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
    gl_Position = vec4(p[gl_VertexID], 0, 1);
}
'''
FRAGMENT = b'''#version 330 core
uniform int seed;
out vec4 color;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec3 rgb = ivec3((p.x * 3 + seed) & 255,
                      (p.y * 5 + seed * 2) & 255,
                      ((p.x ^ p.y) + seed * 7) & 255);
    color = vec4(vec3(rgb) / 255.0, 1.0);
}
'''


class Unsupported(RuntimeError):
    pass


def decode(value):
    return value.decode('utf-8', 'replace') if value else ''


def node_identity(node, drm_root=Path('/sys/class/drm')):
    """Use only an actual DRM primary/render node mapped to a PCI device."""
    if not re.fullmatch(r'/dev/dri/(card[0-9]+|renderD[0-9]+)', node):
        raise ValueError('invalid DRM device node')
    device = (drm_root / Path(node).name / 'device').resolve(strict=True)
    from .functional import bdf_arg
    bdf = bdf_arg(device.name)
    return {'bdf': bdf, 'vendor': (device / 'vendor').read_text().strip().lower(),
            'device': (device / 'device').read_text().strip().lower(), 'drm_node': node}


def select_device(rows, bdf):
    matches = [r for r in rows if r.get('identity', {}).get('bdf') == bdf]
    if len(matches) > 1:
        # GLVND may enumerate one physical PCI device through several drivers.
        # EXT_device_persistent_id explicitly defines this disambiguation.
        matches = [r for r in matches if r.get('driver_name') == 'nvidia']
    if len(matches) != 1:
        raise Unsupported(f'expected one EGLDevice mapped to requested BDF; found {len(matches)}')
    row = matches[0]
    if (row['identity']['vendor'] != '0x10de' or row.get('software')
            or row.get('driver_name') not in (None, '', 'nvidia')):
        raise Unsupported('target is not a verified NVIDIA hardware EGLDevice')
    return row


def verify_pixels(raw, seed):
    if len(raw) != WIDTH * HEIGHT * 4:
        raise ValueError('incomplete RGBA readback')
    expected = bytes(c for y in range(HEIGHT) for x in range(WIDTH)
                     for c in ((3*x+seed) % 256, (5*y+2*seed) % 256,
                               ((x ^ y)+7*seed) % 256, 255))
    mismatches = sum(raw[i:i+4] != expected[i:i+4] for i in range(0, len(raw), 4))
    return {'seed': seed, 'pixels_checked': WIDTH * HEIGHT,
            'mismatched_pixels': mismatches,
            'max_channel_error': max(abs(a-b) for a, b in zip(raw, expected)),
            'rgba_sha256': hashlib.sha256(raw).hexdigest(),
            'expected_sha256': hashlib.sha256(expected).hexdigest()}


class EGL:
    def __init__(self):
        self.lib = C.CDLL('libEGL.so.1')
        self.bind('eglGetProcAddress', P, S)
        self.bind('eglGetError', I)
        self.bind('eglQueryString', S, P, I)
        self.bind('eglInitialize', U, P, IP, IP)
        self.bind('eglBindAPI', U, U)
        self.bind('eglChooseConfig', U, P, IP, PP, I, IP)
        self.bind('eglGetConfigAttrib', U, P, P, I, IP)
        self.bind('eglCreatePbufferSurface', P, P, P, IP)
        self.bind('eglCreateContext', P, P, P, P, IP)
        self.bind('eglMakeCurrent', U, P, P, P, P)
        self.bind('eglDestroyContext', U, P, P)
        self.bind('eglDestroySurface', U, P, P)
        self.bind('eglTerminate', U, P)

    def bind(self, name, result, *args):
        fn = getattr(self.lib, name)
        fn.restype, fn.argtypes = result, args
        setattr(self, name, fn)

    def proc(self, name, result, *args):
        address = self.eglGetProcAddress(name.encode('ascii'))
        if not address:
            raise Unsupported('missing entry point ' + name)
        return C.CFUNCTYPE(result, *args)(address)

    def check(self, value, name):
        if not value:
            raise RuntimeError(f'{name} failed: EGL error 0x{self.eglGetError():04x}')
        return value


def render(egl, report, checkpoint):
    def gl(name, result, *args):
        return egl.proc(name, result, *args)
    get_string = gl('glGetString', S, U)
    get_error = gl('glGetError', U)
    report['gl'] = {name: decode(get_string(enum)) for name, enum in
                    [('vendor', 0x1F00), ('renderer', 0x1F01), ('version', 0x1F02),
                     ('shading_language_version', 0x8B8C)]}
    if ('nvidia' not in report['gl']['vendor'].lower() or
            any(s in report['gl']['renderer'].lower() for s in
                ('llvmpipe', 'softpipe', 'swrast', 'software', 'swiftshader'))):
        raise RuntimeError('GL renderer is not verified NVIDIA hardware')
    def check_gl(where):
        error = get_error()
        if error:
            raise RuntimeError(f'{where}: GL error 0x{error:04x}')

    create_shader = gl('glCreateShader', U, U)
    shader_source = gl('glShaderSource', None, U, I, C.POINTER(S), IP)
    compile_shader = gl('glCompileShader', None, U)
    get_shader = gl('glGetShaderiv', None, U, U, IP)
    get_shader_log = gl('glGetShaderInfoLog', None, U, I, IP, P)
    shaders = []
    program, vao = 0, U(0)
    try:
        for kind, source in ((0x8B31, VERTEX), (0x8B30, FRAGMENT)):
            shader = create_shader(kind)
            shaders.append(shader)
            text = S(source)
            shader_source(shader, 1, C.byref(text), None)
            compile_shader(shader)
            status = I()
            get_shader(shader, 0x8B81, C.byref(status))
            if not status.value:
                log = C.create_string_buffer(4096)
                get_shader_log(shader, len(log), None, log)
                raise RuntimeError('shader compilation failed: ' + decode(log.value))
        program = gl('glCreateProgram', U)()
        attach = gl('glAttachShader', None, U, U)
        for shader in shaders:
            attach(program, shader)
        gl('glLinkProgram', None, U)(program)
        status = I()
        gl('glGetProgramiv', None, U, U, IP)(program, 0x8B82, C.byref(status))
        if not status.value:
            log = C.create_string_buffer(4096)
            gl('glGetProgramInfoLog', None, U, I, IP, P)(program, len(log), None, log)
            raise RuntimeError('shader link failed: ' + decode(log.value))
        check_gl('shader creation')
        report['boundaries']['shader_linked'] = True
        checkpoint()
        gl('glUseProgram', None, U)(program)
        location = gl('glGetUniformLocation', I, U, S)(program, b'seed')
        if location < 0:
            raise RuntimeError('seed uniform missing')
        gl('glGenVertexArrays', None, I, C.POINTER(U))(1, C.byref(vao))
        gl('glBindVertexArray', None, U)(vao.value)
        gl('glViewport', None, I, I, I, I)(0, 0, WIDTH, HEIGHT)
        disable = gl('glDisable', None, U)
        for flag in (0x0BD0, 0x0BE2, 0x8DB9):  # dither, blend, framebuffer sRGB
            disable(flag)
        gl('glPixelStorei', None, U, I)(0x0D05, 1)  # PACK_ALIGNMENT
        report['frames'] = []
        for seed in SEEDS:
            gl('glUniform1i', None, I, I)(location, seed)
            gl('glDrawArrays', None, U, I, I)(0x0004, 0, 3)
            check_gl('draw')
            report['boundaries']['work_submitted'] = True
            checkpoint()
            pixels = (C.c_ubyte * (WIDTH * HEIGHT * 4))()
            # Client-memory glReadPixels synchronizes the result of the draw.
            gl('glReadPixels', None, I, I, I, I, U, U, P)(
                0, 0, WIDTH, HEIGHT, 0x1908, 0x1401, pixels)
            check_gl('readback')
            report['frames'].append(verify_pixels(bytes(pixels), seed))
            checkpoint()
        report['boundaries']['readback_completed'] = True
        report['boundaries']['output_validated'] = all(
            frame['mismatched_pixels'] == 0 for frame in report['frames'])
        if not report['boundaries']['output_validated']:
            raise RuntimeError('rendered pixels differ from CPU reference')
        checkpoint()
    finally:
        if vao.value:
            gl('glDeleteVertexArrays', None, I, C.POINTER(U))(1, C.byref(vao))
        if program:
            gl('glDeleteProgram', None, U)(program)
        for shader in shaders:
            gl('glDeleteShader', None, U)(shader)


def probe(bdf, emit):
    report = new_report(bdf)
    report['test'] = {'size': [WIDTH, HEIGHT], 'seeds': list(SEEDS),
                      'vertex_sha256': hashlib.sha256(VERTEX).hexdigest(),
                      'fragment_sha256': hashlib.sha256(FRAGMENT).hexdigest(),
                      'pixel_tolerance': 0}
    report['source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name('functional.py'))}
    checkpoint = lambda: emit(report, False)
    egl = None
    display = surface = context = None
    initialized = False
    checkpoint()
    try:
        egl = EGL()
        extensions = decode(egl.eglQueryString(None, 0x3055)).split()
        if not ('EGL_EXT_platform_device' in extensions and
                'EGL_EXT_platform_base' in extensions and
                ('EGL_EXT_device_base' in extensions or
                 {'EGL_EXT_device_enumeration', 'EGL_EXT_device_query'} <= set(extensions))):
            raise Unsupported('required EGL client extensions unavailable')
        query_devices = egl.proc('eglQueryDevicesEXT', U, I, PP, IP)
        query_device = egl.proc('eglQueryDeviceStringEXT', S, P, I)
        count = I()
        egl.check(query_devices(0, None, C.byref(count)), 'query device count')
        if not 0 < count.value <= 256:
            raise Unsupported('EGLDevice count outside supported range')
        devices = (P * count.value)()
        capacity = count.value
        egl.check(query_devices(capacity, devices, C.byref(count)), 'query devices')
        if not 0 <= count.value <= capacity:
            raise RuntimeError('EGLDevice enumeration changed unexpectedly')
        rows = []
        for index in range(count.value):
            devext = decode(query_device(devices[index], 0x3055)).split()
            row = {'index': index, 'software': 'EGL_MESA_device_software' in devext}
            if 'EGL_EXT_device_persistent_id' in devext:
                row['driver_name'] = decode(query_device(devices[index], 0x335E))
            if 'EGL_EXT_device_query_name' in devext:
                row['renderer_name'] = decode(query_device(devices[index], 0x335F))
            row['mapping_errors'] = []
            for ext, enum in [('EGL_EXT_device_drm_render_node', 0x3377),
                              ('EGL_EXT_device_drm', 0x3233)]:
                if ext not in devext:
                    continue
                node = decode(query_device(devices[index], enum))
                if not node:
                    continue
                try:
                    row['identity'] = node_identity(node)
                    break
                except (ValueError, OSError) as exc:
                    row['mapping_errors'].append(str(exc))
            rows.append(row)
        report['egl_devices'] = rows
        selected = select_device(rows, bdf)
        report['target'] = selected['identity']
        report['boundaries']['target_verified'] = True
        checkpoint()
        platform_display = egl.proc('eglGetPlatformDisplayEXT', P, U, P, IP)
        display = egl.check(platform_display(0x313F, devices[selected['index']], None),
                            'get device display')
        major, minor = I(), I()
        egl.check(egl.eglInitialize(display, C.byref(major), C.byref(minor)), 'initialize')
        initialized = True
        report['egl'] = {'version': f'{major.value}.{minor.value}',
                         'vendor': decode(egl.eglQueryString(display, 0x3053)),
                         'platform': 'EGL_PLATFORM_DEVICE_EXT', 'surface': 'pbuffer',
                         'window_system_connection': False}
        if (major.value, minor.value) < (1, 5) and 'EGL_KHR_create_context' not in decode(
                egl.eglQueryString(display, 0x3055)).split():
            raise Unsupported('OpenGL core context creation extension unavailable')
        egl.check(egl.eglBindAPI(0x30A2), 'bind OpenGL API')
        # RGBA8 pbuffer, OPENGL_BIT, no multisampling/depth required.
        attrs = (I * 17)(0x3033, 1, 0x3040, 8, 0x3024, 8, 0x3023, 8,
                         0x3022, 8, 0x3021, 8, 0x3031, 0, 0x3032, 0, 0x3038)
        config, found = P(), I()
        egl.check(egl.eglChooseConfig(display, attrs, C.byref(config), 1, C.byref(found)),
                  'choose config')
        if found.value != 1:
            raise Unsupported('no RGBA8 OpenGL pbuffer config')
        bits = {}
        for name, enum in [('red', 0x3024), ('green', 0x3023), ('blue', 0x3022),
                           ('alpha', 0x3021), ('samples', 0x3031)]:
            value = I()
            egl.check(egl.eglGetConfigAttrib(display, config, enum, C.byref(value)),
                      'query config')
            bits[name] = value.value
        report['egl']['config'] = bits
        if bits != dict(red=8, green=8, blue=8, alpha=8, samples=0):
            raise Unsupported('selected config is not exact non-multisampled RGBA8')
        surface = egl.check(egl.eglCreatePbufferSurface(
            display, config, (I * 5)(0x3057, WIDTH, 0x3056, HEIGHT, 0x3038)), 'pbuffer')
        context = egl.check(egl.eglCreateContext(
            display, config, None, (I * 7)(0x3098, 3, 0x30FB, 3, 0x30FD, 1, 0x3038)),
            'OpenGL 3.3 core context')
        egl.check(egl.eglMakeCurrent(display, surface, surface, context), 'make current')
        report['boundaries']['context_created'] = True
        checkpoint()
        render(egl, report, checkpoint)
        report['functional_results']['opengl'] = {'status': 'pass', 'frames': len(SEEDS),
                                                  'pixels_checked': WIDTH * HEIGHT * len(SEEDS)}
    except Unsupported as exc:
        report['functional_results']['opengl'] = {'status': 'unsupported'}
        report['errors'].append(str(exc))
    except (OSError, ValueError, RuntimeError) as exc:
        report['functional_results']['opengl'] = {'status': 'error'}
        report['errors'].append(str(exc))
    finally:
        cleanup = []
        if initialized:
            for name, args in [('eglMakeCurrent', (display, None, None, None)),
                               ('eglDestroyContext', (display, context)) if context else (None, ()),
                               ('eglDestroySurface', (display, surface)) if surface else (None, ()),
                               ('eglTerminate', (display,))]:
                if name and not getattr(egl, name)(*args):
                    cleanup.append(f'{name}: 0x{egl.eglGetError():04x}')
        report['cleanup_errors'] = cleanup
        if cleanup:
            report['errors'].extend(cleanup)
            report['functional_results']['opengl']['status'] = 'error'
    emit(report, True)
    return report


if __name__ == '__main__':
    probe(sys.argv[1], lambda report, final: print(
        json.dumps({'report': report, 'final': final}), flush=True))
