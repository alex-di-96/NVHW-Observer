"""Common envelope keeps measurements, unsupported calls and unknowns distinct."""
from datetime import datetime, timezone
from . import __version__

FEATURES = ('compute', 'nvdec', 'nvenc', 'hardware_rt')
SCHEMA = 'hwt.observation.v1'


def envelope(kind):
    return {'schema': SCHEMA, 'tool_version': __version__, 'kind': kind,
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'functional_results': {
                feature: {'status': 'not_measured', 'evidence': []} for feature in FEATURES}}


def validate(report):
    """Validate this initial inventory/log format; functional probes are future work."""
    if not isinstance(report, dict) or report.get('schema') != SCHEMA:
        raise ValueError('unsupported report schema')
    if report.get('kind') not in ('pci_inventory', 'uefi_v6_log', 'uefi_passive_m1'):
        raise ValueError('unsupported report kind')
    if set(report.get('functional_results', {})) != set(FEATURES):
        raise ValueError('all four functional result fields are required')
    # Neither inventory nor log parsing proves a functional GPU workload.
    for value in report['functional_results'].values():
        if value != {'status': 'not_measured', 'evidence': []}:
            raise ValueError('inventory/log parsing cannot claim functional acceleration')
    required = 'devices' if report['kind'] == 'pci_inventory' else 'analysis'
    expected = list if required == 'devices' else dict
    if not isinstance(report.get(required), expected):
        raise ValueError('missing or invalid ' + required)
    return report
