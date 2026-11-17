"""Strict decoder for NVHW passive M1; parsing never establishes GPU features."""
import re

FIELDS = {
    'RUN': 'schema test source profile words seq', 'RTC': 'date timezone',
    'SELF': 'sha256', 'NEXT': 'sha256', 'TARGET': 'bdf pci subsystem',
    'GUARDS': 'pmcsr bar_base bar_size', 'ACCESS': 'original expected',
    'ACTIVE': 'value status', 'BOOT0': 'value status', 'ROM': 'sha256 bytes offset',
    'BEGIN': 'phase words ticks atomic gpu_mmio_writes',
    'WORD': 'index address value status valid',
    'END': 'words usable transport_errors ticks',
    'RESTORE': 'original final write_status read_status writes',
    'HANDOFF': 'sha256 confirmation',
}


def analyze(text, manifest, allow_mock=False):
    result = {'errors': [], 'capture_complete': False, 'diagnostics_complete': False,
              'pci_restored': None, 'outcome': None, 'words': [],
              'gpu_mmio_writes': 0, 'functional_tests': 'not_measured'}
    try:
        rows, run = [], None
        for line in text.splitlines():
            if not line.startswith('NVHW1 '):
                continue
            fields = line.split()
            if len(fields) < 3 or not re.fullmatch(r'run=[0-9a-fA-F]{16}', fields[1]):
                raise ValueError('malformed run identifier')
            current = fields[1][4:].lower()
            if run is not None and current != run:
                raise ValueError('mixed run identifiers')
            run = current
            values = {}
            for item in fields[3:]:
                key, sep, value = item.partition('=')
                if not sep or not value or key in values:
                    raise ValueError('malformed or duplicate field')
                values[key] = value
            rows.append((fields[2], values))
        if not rows or rows[0][0] != 'RUN':
            raise ValueError('missing RUN')
        single = {}
        known = ['RUN','RTC','SELF','NEXT','TARGET','GUARDS','ACCESS','ACTIVE','BOOT0',
                 'ROM','BEGIN','WORD','END','RESTORE','RESULT','HANDOFF']
        rank = -1
        for kind, values in rows:
            if kind not in known or known.index(kind) < rank:
                raise ValueError('unknown or out-of-order record')
            rank = known.index(kind)
            fields = FIELDS.get(kind)
            if kind == 'RESULT':
                fields = 'outcome usable words functional_tests' if values.get('outcome') == 'complete' else 'outcome reason status'
            if set(values) != set(fields.split()):
                raise ValueError('unexpected or missing fields in ' + kind)
            if kind != 'WORD':
                if kind in single:
                    raise ValueError('duplicate ' + kind)
                single[kind] = values
        header = single['RUN']
        mode = int(header['test'])
        if mode != 0 and not allow_mock:
            raise ValueError('mock evidence rejected')
        artifact = manifest['artifacts'][str(mode)]
        expected = [int(a,16) for a in manifest['profile']['registers']]
        if header['schema'] != '1' or header['source'] != manifest['source_sha256'] or header['profile'] != manifest['profile_sha256']:
            raise ValueError('wrong protocol/source/profile')
        if int(header['words']) != len(expected) or not 1 <= int(header['seq']) <= 9999:
            raise ValueError('wrong record count or file sequence')
        if 'SELF' in single and single['SELF']['sha256'] != artifact['sha256']:
            raise ValueError('wrong EFI identity')
        if 'NEXT' in single and single['NEXT']['sha256'] != artifact['successor_sha256']:
            raise ValueError('wrong successor identity')
        if 'TARGET' in single:
            target = single['TARGET']
            if int(target['pci'],16) != int(manifest['profile']['pci_id'],16) or int(target['subsystem'],16) != int(manifest['profile']['subsystem_id'],16):
                raise ValueError('wrong target identity')
            if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]', target['bdf']):
                raise ValueError('invalid BDF')
        if 'RESTORE' in single:
            row, access = single['RESTORE'], single['ACCESS']
            original = int(access['original'],16)
            if not 0 <= original < 65535 or int(access['expected'],16) != original | 2:
                raise ValueError('invalid COMMAND scope')
            if int(row['original'],16) != original:
                raise ValueError('restore original mismatch')
            writes = int(row['writes'])
            if writes != (0 if original & 2 else 2):
                raise ValueError('unexpected PCI write count')
            result['pci_restored'] = (int(row['final'],16) == original
                                     and int(row['write_status'],16) == 0
                                     and int(row['read_status'],16) == 0)
        for kind, row in rows:
            if kind != 'WORD':
                continue
            i = len(result['words'])
            if 'BEGIN' not in single or i >= len(expected) or int(row['index']) != i or int(row['address'],16) != expected[i]:
                raise ValueError('wrong, duplicate, missing or reordered word')
            value, status = int(row['value'],16), int(row['status'],16)
            if not 0 <= value < 2**32 or not 0 <= status < 2**64:
                raise ValueError('unsigned word/status overflow')
            valid = status == 0 and value & 0xffff0000 != 0xbadf0000 and value not in (0xdec0ffee,0xdece30fb) and (value != 0xffffffff or expected[i] == 0x409650)
            if row['valid'] not in ('0','1') or int(row['valid']) != int(valid):
                raise ValueError('word validity mismatch')
            result['words'].append({'address': expected[i], 'raw_value': value,
                                    'status': status, 'valid': valid,
                                    'value': value if valid else None})
        if 'END' in single:
            end = single['END']
            if int(end['words']) != len(expected) or len(result['words']) != len(expected):
                raise ValueError('incomplete snapshot')
            if int(end['usable']) != sum(w['valid'] for w in result['words']) or int(end['transport_errors']) != sum(w['status'] != 0 for w in result['words']):
                raise ValueError('incorrect snapshot summary')
            begin = single['BEGIN']
            if begin['phase'] != 'pre_compute' or begin['atomic'] != '0' or begin['gpu_mmio_writes'] != '0' or int(begin['words']) != len(expected):
                raise ValueError('invalid phase claims')
            if int(begin['ticks'],16) > int(end['ticks'],16):
                raise ValueError('backwards TSC bracket')
        outcome = single['RESULT']['outcome']
        result.update(run=run, test_mode=mode, outcome=outcome, records=len(rows))
        if outcome == 'stopped':
            if 'HANDOFF' in single or int(single['RESULT']['status'],16) == 0:
                raise ValueError('invalid stopped result')
            result['stop_reason'] = single['RESULT']['reason']
            return result
        if outcome != 'complete':
            raise ValueError('unknown result')
        for kind in known:
            if kind not in ('RTC','WORD') and kind not in single:
                raise ValueError('missing ' + kind)
        if not result['pci_restored']:
            raise ValueError('PCI not restored')
        active = single['ACTIVE']
        if int(active['status'],16) != 0 or int(active['value'],16) != int(single['ACCESS']['expected'],16):
            raise ValueError('active COMMAND not verified')
        guards = single['GUARDS']
        if int(guards['pmcsr'],16) & 3 or int(guards['bar_base'],16) == 0 or int(guards['bar_size'],16) < 0x310000:
            raise ValueError('invalid access guards')
        if int(single['BOOT0']['status'],16) or int(single['BOOT0']['value'],16) != int(manifest['profile']['boot0'],16):
            raise ValueError('BOOT0 not verified')
        rom = single['ROM']
        if rom['sha256'] != artifact['rom_sha256'] or rom['bytes'] != '65536' or rom['offset'] != '00300000':
            raise ValueError('ROM not verified')
        if int(single['END']['transport_errors']) != 0:
            raise ValueError('transport failure cannot complete')
        final = single['RESULT']
        if final['functional_tests'] != 'not_measured' or final['words'] != single['END']['words'] or final['usable'] != single['END']['usable']:
            raise ValueError('invalid final result')
        if single['HANDOFF'] != {'sha256': artifact['successor_sha256'], 'confirmation': 'successor'}:
            raise ValueError('invalid handoff')
        result['capture_complete'] = True
        result['diagnostics_complete'] = all(w['valid'] for w in result['words'])
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result['errors'].append(str(exc))
    return result
