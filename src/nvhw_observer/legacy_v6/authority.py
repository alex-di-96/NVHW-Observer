#!/usr/bin/env python3
"""V6 passive authority log: separate completeness, validity and hypotheses."""
import argparse
import json
from pathlib import Path
import re
from .core import analyze as analyze_core, boolean, number, valid

ADDRESSES = [
    0x110100,0x110040,0x110044,0x1100d0,0x110104,0x110108,
    0x11010c,0x110118,0x11014c,0x1101c0,0x110240,0x1103c0,
    0x110624,0x110610,
    0x12e0,0x118c50,0x118234,0x21378,0x1fa824,0x1fa828,
    0x1430,0x1448,0x409650,0x409668,0x110100,0x11010c,
]
PHASES = ['entry','pre_fwsec_reset','post_fwsec_reset',
          'post_fwsec_dma_setup','post_fwsec_descriptor','post_fwsec','post_compute']
PREFIX = 'HWT_AUTH_V1 '


def analyze(text, expected_efi=None, expected_source=None):
    core = analyze_core(text, expected_efi, expected_source)
    r = dict(core=core, errors=[], protocol_complete=False, diagnostics_complete=False,
             phases={}, fwsec_path=None, changes=[], diagnostic_gpu_mmio_writes=0,
             diagnostic_data_port_reads=0, host_writable_proven=False,
             secure_mode_cause_proven=False, codecs_unlocked=False, rt_unlocked=False)
    active = None
    ended = []
    last_end = None
    header = core.get('run', {})
    try:
        for lineno, line in enumerate(text.splitlines(), 1):
            if PREFIX not in line:
                continue
            kind, _, body = line.split(PREFIX, 1)[1].partition(' ')
            pairs = re.findall(r'([a-z_][a-z0-9_]*)=([^\s;]+)', body)
            f = dict(pairs)
            if len(f) != len(pairs):
                raise ValueError('duplicate field')
            if f.get('run') != header.get('run'):
                raise ValueError('mixed or absent run')
            if kind == 'PATH':
                if active or ended != ['entry'] or r['fwsec_path'] is not None:
                    raise ValueError('PATH ordering/duplicate')
                if f['fwsec'] not in ('ran', 'skipped'):
                    raise ValueError('unknown FWSEC path')
                r['fwsec_path'] = f['fwsec']
            elif kind == 'BEGIN':
                seq = PHASES if r['fwsec_path'] != 'skipped' else [PHASES[i] for i in (0,5,6)]
                phase = f['phase']
                if active or len(ended) >= len(seq) or phase != seq[len(ended)]:
                    raise ValueError('snapshot ordering/duplicate')
                if ended and r['fwsec_path'] is None:
                    raise ValueError('missing PATH')
                if number(f['words']) != len(ADDRESSES) or not boolean(f['sequential']):
                    raise ValueError('wrong schema')
                command, status = number(f['command'],16), number(f['command_status'])
                if not boolean(f['command_ok']) or status or command == 0xffff or not command & 2:
                    raise ValueError('PCI memory decode unavailable')
                begin, end = number(f['begin_us']), number(f['end_us'])
                clock = boolean(f['clock_ok'])
                if clock and (end < begin or (last_end is not None and begin < last_end)):
                    raise ValueError('clock backwards')
                r['phases'][phase] = dict(words=[], begin_us=begin, end_us=end,
                                          clock_ok=clock, command=command)
                active = phase
            elif kind == 'WORD':
                if not active or f['phase'] != active:
                    raise ValueError('word outside phase')
                words = r['phases'][active]['words']
                i = number(f['index'])
                if i != len(words) or i >= len(ADDRESSES) or number(f['address'],32) != ADDRESSES[i]:
                    raise ValueError('word address/index')
                value, status = number(f['value'],32), number(f['status'])
                usable = valid(ADDRESSES[i],value,status)
                if boolean(f['usable']) != usable:
                    raise ValueError('wrong validity')
                words.append(dict(address=hex(ADDRESSES[i]),value=value,status=status,usable=usable))
            elif kind == 'END':
                if not active or f['phase'] != active:
                    raise ValueError('END outside phase')
                p = r['phases'][active]
                w = p['words']
                if len(w) != len(ADDRESSES) or number(f['words']) != len(w):
                    raise ValueError('truncated snapshot')
                usable = sum(x['usable'] for x in w)
                if number(f['usable_words']) != usable:
                    raise ValueError('wrong usable count')
                brackets = None if not all(w[i]['usable'] for i in (0,6,24,25)) else (
                    w[0]['value'] == w[24]['value'] and w[6]['value'] == w[25]['value'])
                expected = {None:'None', True:'Some(true)', False:'Some(false)'}[brackets]
                if f['brackets_unchanged'] != expected:
                    raise ValueError('wrong bracket summary')
                for k in ('diagnostic_gpu_mmio_writes','diagnostic_data_port_reads'):
                    if number(f[k]) != 0:
                        raise ValueError('unexpected diagnostic access')
                if boolean(f['atomic_snapshot']) or boolean(f['host_writable_proven']):
                    raise ValueError('unsupported claim')
                def value(i):
                    return w[i]['value'] if w[i]['usable'] else None
                p.update(usable_words=usable, brackets_unchanged=brackets,
                         raw=dict(cpuctl=value(0),dmactl=value(6),sctl_candidate=value(10),
                                  exci=value(3),dmemc=value(9),nvdec_mask=value(17),gate=value(15)),
                         dmactl_bit7=None if value(6) is None else (value(6)>>7)&1,
                         sctl_low2_candidate=None if value(10) is None else value(10)&3)
                last_end = p['end_us'] if p['clock_ok'] else None
                ended.append(active)
                active = None
            else:
                raise ValueError('unknown authority record '+kind)
        if core['errors']:
            raise ValueError('core protocol failed')
        if core.get('outcome') in ('operator_cancelled','no_target','ambiguous_target'):
            if ended or active or r['fwsec_path']:
                raise ValueError('observations in negative control')
            return r
        seq = PHASES if r['fwsec_path'] == 'ran' else [PHASES[i] for i in (0,5,6)]
        if active or ended != seq or not r['fwsec_path'] or not core['record_complete']:
            raise ValueError('incomplete authority protocol')
        # Do not accept a rearranged log with valid per-stream ordering.
        markers = [
            'HWT_VBIOS_V6 OBSERVED run='+header['run']+' phase=entry_after_decode_before_claim',
            PREFIX+'BEGIN run='+header['run']+' phase=entry ',
            'HWT_VBIOS_V6 ASSETS run=',
            PREFIX+'PATH run=',
            PREFIX+'BEGIN run='+header['run']+' phase=post_fwsec ',
            'HWT_VBIOS_V6 TX_RESULT run=',
            'HWT_VBIOS_V6 OBSERVED run='+header['run']+' phase=post_compute_before_handoff',
            PREFIX+'BEGIN run='+header['run']+' phase=post_compute ',
            'HWT_VBIOS_V6 RESULT run=',
        ]
        positions = [text.index(m) for m in markers]
        if positions != sorted(positions):
            raise ValueError('cross-stream ordering')
        r['protocol_complete'] = True
        r['diagnostics_complete'] = core['diagnostics_complete'] and all(
            p['usable_words'] == len(ADDRESSES) and p['brackets_unchanged'] is True for p in r['phases'].values())
        for a,b in zip(ended,ended[1:]):
            changes=[]
            for i,(x,y) in enumerate(zip(r['phases'][a]['words'],r['phases'][b]['words'])):
                if x['usable'] and y['usable'] and x['value'] != y['value']:
                    changes.append(dict(index=i,address=x['address'],before=x['value'],after=y['value']))
            r['changes'].append(dict(before_phase=a,after_phase=b,words=changes))
    except (ValueError,KeyError,TypeError,IndexError) as e:
        r['errors'].append(f'line {locals().get("lineno",0)}: {e}')
    return r


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('log',type=Path);p.add_argument('--manifest',type=Path,required=True)
    a=p.parse_args();m=json.loads(a.manifest.read_text())
    print(json.dumps(analyze(a.log.read_text(errors='replace'),m['efi_sha256'],m['source_sha256']),indent=2))
