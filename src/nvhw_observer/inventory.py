"""Read only documented PCI identity attributes in sysfs; no config/BAR/ROM IO."""
import os
from pathlib import Path
import platform
import re
from .profiles import identify
from .report import envelope

BDF = re.compile(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]')
FIELDS = {'vendor': 4, 'device': 4, 'subsystem_vendor': 4,
          'subsystem_device': 4, 'class': 6, 'revision': 2}


def read_identity(path):
    result, errors = {}, {}
    for name, width in FIELDS.items():
        try:
            text = (path / name).read_text(encoding='ascii').strip()
            if not re.fullmatch(r'0x[0-9a-fA-F]{1,' + str(width) + '}', text):
                raise ValueError('invalid PCI hex attribute')
            result[name] = f'{int(text, 16):0{width}x}'
        except (OSError, UnicodeError, ValueError) as exc:
            result[name] = None
            errors[name] = type(exc).__name__
    return result, errors


def collect(pci_root=Path('/sys/bus/pci/devices')):
    pci_root = Path(pci_root)
    report = envelope('pci_inventory')
    report.update(kernel=platform.release(), devices=[], enumeration_errors=[],
                  access={'sysfs_identity': True, 'pci_config': False,
                          'gpu_mmio': False, 'rom': False, 'gpu_api': False})
    for path in sorted(pci_root.iterdir()):
        if not BDF.fullmatch(path.name):
            continue
        identity, errors = read_identity(path)
        if identity['vendor'] != '10de':
            if identity['vendor'] is None:
                report['enumeration_errors'].append({'bdf': path.name,
                                                      'vendor': errors['vendor']})
            continue
        driver, driver_error = None, None
        try:
            driver = Path(os.readlink(path / 'driver')).name
        except FileNotFoundError:
            pass
        except OSError as exc:
            driver_error = type(exc).__name__
        report['devices'].append({'bdf': path.name, 'identity': identity,
                                  'identity_errors': errors, 'driver': driver,
                                  'driver_error': driver_error,
                                  'profile': identify(identity)})
    return report
