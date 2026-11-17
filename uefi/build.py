#!/usr/bin/env python3
"""Reproducible GNU-EFI build to a NEW directory. No network/device/deploy IO."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_profile(name):
    """Only reviewed observation sets; no arbitrary MMIO address input."""
    if name not in ('m1', 'm2'):
        raise ValueError('unknown reviewed profile')
    baseline_path = HERE/'profiles/cmp50hx-tu102-reference-m1.json'
    if sha(baseline_path) != '4957516865e50bea790b7e3c9273c9fff9fc2cd7de7ea5ec30f3bdf7939d5e1e':
        raise ValueError('reviewed M1 baseline changed')
    baseline = json.loads(baseline_path.read_text())
    path = HERE/f'profiles/cmp50hx-tu102-reference-{name}.json'
    profile = json.loads(path.read_text())
    if name == 'm2':
        expected = dict(baseline, id='cmp50hx-tu102-reference-m2',
                        registers=baseline['registers'] + ['00021d68'],
                        provenance=baseline['provenance'] + [
                            'tu102-codec-register-bindings-20261116: TU102 MSENC+208 -> 5555568; '
                            'FUSE+160 -> 52f28ac; direct read 55555b0 -> BAR0+21d68'])
        if profile != expected:
            raise ValueError('M2 must differ only by its reviewed NVENC status read and provenance')
    return path, profile


def build(gnu_root, output, profile_name='m1'):
    profile_path, profile = load_profile(profile_name)
    if output.exists() and any(output.iterdir()):
        raise ValueError('output must be new or empty; preserve previous builds')
    output.mkdir(parents=True, exist_ok=True)
    inc, lib = gnu_root/'usr/include/efi', gnu_root/'usr/lib'
    required = [inc/'efi.h', inc/'efipciio.h', lib/'libefi.a', lib/'libgnuefi.a',
                lib/'crt0-efi-x86_64.o', lib/'elf_x86_64_efi.lds']
    if any(not p.is_file() for p in required):
        raise ValueError('GNU-EFI root incomplete')
    inputs = [HERE/n for n in ('build.py', 'observer.c', 'sha256.c', 'sha256.h', 'mock_successor.c')]
    inputs += sorted((HERE/'profiles').glob('*.json'))
    sources = {str(p.relative_to(HERE)): sha(p) for p in sorted(inputs)}
    source_sha = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    registers = [int(x, 16) for x in profile['registers']]
    count = 90 if profile_name == 'm1' else 91
    if len(registers) != count or len(set(registers)) != count or 0x625488 in registers:
        raise ValueError('unexpected observation set')
    flags = ['-O2', '-Wall', '-Wextra', '-Werror', '-fpic', '-ffreestanding',
             '-fno-stack-protector', '-fno-asynchronous-unwind-tables', '-fno-unwind-tables',
             '-fshort-wchar', '-mno-red-zone', '-maccumulate-outgoing-args', '-fno-builtin',
             '-DGNU_EFI_USE_MS_ABI', '-I', str(inc), '-I', str(inc/'x86_64'),
             '-I', str(output)]
    commands = []

    def run(command):
        commands.append(command)
        process = subprocess.run(command, cwd=HERE, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C', SOURCE_DATE_EPOCH='0'))
        with (output/'build.log').open('a') as log:
            log.write(process.stdout)
        if process.returncode:
            raise RuntimeError(process.stdout)

    def link(objects, name):
        shared, efi = output/(name+'.so'), output/(name+'.efi')
        run(['ld', '-nostdlib', '-znocombreloc', '--build-id=none', '-T',
             str(lib/'elf_x86_64_efi.lds'), '-shared', '-Bsymbolic',
             str(lib/'crt0-efi-x86_64.o'), *map(str, objects), '-L', str(lib),
             '-lefi', '-lgnuefi', '-o', str(shared)])
        run(['objcopy', *[arg for section in ('.text','.sdata','.data','.rodata','.dynamic',
             '.dynsym','.reloc','.rel','.rela','.rel.*','.rela.*') for arg in ('-j', section)],
             '--target=efi-app-x86_64', str(shared), str(efi)])
        return efi

    stub_obj = output/'mock-successor.o'
    run(['gcc', '-c', *flags, 'mock_successor.c', '-o', str(stub_obj)])
    stub = link([stub_obj], 'mock-successor')
    sha_obj = output/'sha256.o'
    run(['gcc', '-c', *flags, 'sha256.c', '-o', str(sha_obj)])
    artifacts = {}
    for mode in range(10):
        next_sha = profile['successor_sha256'] if mode == 0 else sha(stub)
        rom_sha = profile['rom']['sha256'] if mode == 0 else hashlib.sha256(bytes(65536)).hexdigest()
        header = '\n'.join([
            f'#define NVHW_TEST {mode}', f'#define NVHW_SOURCE_SHA "{source_sha}"',
            f'#define PROFILE_SHA "{sha(profile_path)}"',
            f'#define NVHW_LOG_STEM L"nvhw-{profile_name}"',
            f'#define PROFILE_PCI 0x{profile["pci_id"]}U',
            f'#define PROFILE_SUB 0x{profile["subsystem_id"]}U',
            f'#define PROFILE_BOOT0 0x{profile["boot0"]}U',
            f'#define NVHW_SUCCESSOR_SHA "{next_sha}"', f'#define NVHW_ROM_SHA "{rom_sha}"',
            f'#define PROFILE_WORDS {len(registers)}',
            'static const UINT32 profile_registers[]={' + ','.join(hex(x) for x in registers) + '};', ''])
        (output/'build_identity.h').write_text(header)
        (output/f'build_identity-{mode}.h').write_text(header)
        obj = output/f'observer-{mode}.o'
        run(['gcc', '-c', *flags, 'observer.c', '-o', str(obj)])
        efi = link([obj, sha_obj], f'nvhw-observer-{mode}')
        artifacts[str(mode)] = {'sha256': sha(efi), 'bytes': efi.stat().st_size,
                                'successor_sha256': next_sha, 'rom_sha256': rom_sha}
    manifest = {'source_sha256': source_sha, 'source_files': sources,
                'profile_sha256': sha(profile_path), 'profile': profile,
                'log_stem': f'nvhw-{profile_name}',
                'artifacts': artifacts, 'mock_successor_sha256': sha(stub),
                'gnu_efi_inputs': {str(p.relative_to(gnu_root)): sha(p) for p in required},
                'tools': {n: {'path': shutil.which(n), 'sha256': sha(Path(shutil.which(n)))}
                          for n in ('gcc', 'ld', 'objcopy')},
                'commands': commands, 'hardware_mode': 0, 'mock_modes': list(range(1, 10)),
                'gpu_mmio_writes': 0, 'deployed': False, 'armed': False}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gnu-efi-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', choices=('m1', 'm2'), default='m1')
    args = parser.parse_args()
    result = build(args.gnu_efi_root.resolve(), args.out.resolve(), args.profile)
    print(json.dumps({'source_sha256': result['source_sha256'], 'efi': result['artifacts']['0']}))
