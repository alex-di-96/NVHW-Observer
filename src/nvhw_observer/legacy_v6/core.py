#!/usr/bin/env python3
"""Strict VBIOS observer log parser. Structural completeness != usable data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

CORE=[0x12e0,0xa00,0x118c50,0x118034,0x118c54,0x118128,0x118234,0x1180f8,
      0x2240c,0x21378,0x21804,0x21824,0x21c04,0x21c24,0x409650,0x409664,
      0x40966c,0x409668,0x1fa824,0x1fa828,0x1430,0x1448]
ADDRESSES=CORE+list(range(0x22700,0x22800,4))
COUNT=len(ADDRESSES)
KNOWN_PLM={0xffffffff:'open',0xffffffef:'relocked_sticky_bits_5_6',0xffffff8f:'fully_relocked'}
PHASES=['entry_after_decode_before_claim','post_compute_before_handoff']
PREFIX='HWT_VBIOS_V6 '


def valid(address,value,status):
    return status==0 and value&0xffff0000!=0xbadf0000 and value not in (0xdec0ffee,0xdece30fb) and (value!=0xffffffff or address==0x409650)


def boolean(s):
    if s not in ('true','false'):raise ValueError('invalid boolean '+s)
    return s=='true'


def number(s,bits=64):
    n=int(s,0)
    if not 0<=n<1<<bits:raise ValueError('number outside unsigned range')
    return n


def analyze(text,expected_efi=None,expected_source=None):
    result=dict(errors=[],record_complete=False,diagnostics_complete=False,
                compute_readback_confirmed=None,compute_override_readback_confirmed=None,
                feat_plm_state=None,feat_l0_write_enabled=None,app08_execution_proven=False,
                block31_execution_proven=False,functional_decode_verified=False,
                pre_gfw_proven=False,phases={},pci_access={})
    header=None;identity=False;assets=False;assets_seen=False;tx=None;final=None;active=None
    observed=set();ended=[];last_end=None
    try:
        for lineno,line in enumerate(text.splitlines(),1):
            if PREFIX not in line:continue
            message=line.split(PREFIX,1)[1]
            kind,_,body=message.partition(' ')
            pairs=re.findall(r'([a-z_][a-z0-9_]*)=([^\s;]+)',body)
            fields=dict(pairs)
            if len(fields)!=len(pairs):raise ValueError('duplicate field')
            if kind=='STOP':
                raise ValueError('observer stopped: '+fields.get('reason','unknown'))
            if kind=='CHAIN_RETURN':continue
            if kind=='RUN':
                if header is not None:raise ValueError('multiple runs')
                if not re.fullmatch('[0-9a-f]{16}',fields['run']):raise ValueError('invalid run ID')
                for k in ('source_sha256','efi_file_sha256'):
                    if not re.fullmatch('[0-9a-f]{64}',fields[k]):raise ValueError('invalid hash')
                if expected_efi and fields['efi_file_sha256']!=expected_efi:raise ValueError('EFI hash mismatch')
                if expected_source and fields['source_sha256']!=expected_source:raise ValueError('source hash mismatch')
                if number(fields['words'])!=COUNT or number(fields['stages'])!=2:raise ValueError('unexpected schema size')
                if number(fields['trace_enable_writes'])!=0 or boolean(fields['app08_execution_proven']):raise ValueError('unexpected app08 claim or trace write')
                if number(fields['core_gpu_mmio_writes'])!=0 or boolean(fields['pre_gfw_proven']) or not boolean(fields['pci_memory_scope']):raise ValueError('unexpected plan')
                header=fields;result['run']=header
                continue
            if header is None:raise ValueError('record before RUN')
            if fields.get('run')!=header['run']:raise ValueError('mixed run IDs')
            if final is not None:raise ValueError('record after RESULT')
            if kind=='ACCESS':
                phase=fields['phase']
                if phase not in PHASES or phase in result['pci_access']:raise ValueError('duplicate/unknown access scope')
                if phase==PHASES[0] and (identity or result['phases'] or tx is not None):raise ValueError('entry access ordering')
                if phase==PHASES[1] and (tx!='ok' or active or ended!=PHASES[:1]):raise ValueError('post access ordering')
                outcome=fields['outcome'];writes=number(fields['writes'])
                if outcome not in ('ok','refused'):raise ValueError('PCI access/restore failure')
                if writes not in (0,2):raise ValueError('unbounded PCI writes')
                saved=number(fields['saved_command'],16);enabled=number(fields['active_command'],16);restored=number(fields['final_command'],16)
                flags={k:boolean(fields[k]) for k in ('facts_ok','active_ok','final_ok','restored')}
                if outcome=='ok':
                    if not all(flags.values()) or saved==0xffff or enabled!=saved|2 or restored!=saved:raise ValueError('unverified PCI access/restore')
                    if writes!=(0 if saved&2 else 2):raise ValueError('unexpected PCI write count')
                    pm=number(fields['pmcsr'],16);bar=number(fields['bar0'])
                    if pm==0xffff or pm&3 or not bar or bar&0xfff or bar>0x000f_ffff_ffbf_ffff:raise ValueError('invalid D0/BAR guard')
                result['pci_access'][phase]=dict(outcome=outcome,writes=writes,saved_command=saved,
                    active_command=enabled,final_command=restored,**flags)
            elif kind=='IDENTITY':
                if identity or result['phases']:raise ValueError('identity ordering')
                if result['pci_access'].get(PHASES[0],{}).get('outcome')!='ok':raise ValueError('identity before verified access')
                if (number(fields['pci_id'],32),number(fields['subsystem'],32),fields['bdf'])!=(0x1e0910de,0x155410de,'0000:01:00.0'):raise ValueError('wrong target')
                if not boolean(fields['rom_pinned']):raise ValueError('ROM not pinned')
                identity=True
            elif kind=='BEGIN':
                phase=fields['phase']
                if not identity or active is not None or len(ended)>=2 or phase!=PHASES[len(ended)]:raise ValueError('phase ordering')
                if result['pci_access'].get(phase,{}).get('outcome')!='ok':raise ValueError('snapshot before verified access')
                if phase==PHASES[1] and (tx!='ok' or not assets):raise ValueError('post snapshot without successful baseline transaction')
                if number(fields['words'])!=COUNT or not boolean(fields['sequential']):raise ValueError('snapshot schema mismatch')
                begin,end=number(fields['begin_us']),number(fields['end_us'])
                clock=boolean(fields['clock_ok'])
                if clock and (end<begin or (last_end is not None and begin<last_end)):raise ValueError('clock backwards')
                result['phases'][phase]=dict(begin_us=begin,end_us=end,clock_ok=clock,words=[])
                active=phase
            elif kind=='WORD':
                if active is None or fields['phase']!=active:raise ValueError('word outside active phase')
                words=result['phases'][active]['words'];index=number(fields['index'])
                if index!=len(words) or index>=COUNT:raise ValueError('duplicate/out-of-order word')
                address,value,status=number(fields['address'],32),number(fields['value'],32),number(fields['status'])
                if address!=ADDRESSES[index]:raise ValueError('wrong register address')
                usable=valid(address,value,status)
                if boolean(fields['usable'])!=usable:raise ValueError('incorrect validity flag')
                words.append(dict(address=hex(address),value=value,status=status,usable=usable))
            elif kind=='END':
                if active is None or fields['phase']!=active:raise ValueError('END outside phase')
                phase=result['phases'][active];words=phase['words']
                if number(fields['words'])!=COUNT or len(words)!=COUNT:raise ValueError('truncated snapshot')
                if number(fields['core_gpu_mmio_writes'])!=0:raise ValueError('unexpected diagnostic writes')
                transport=all(w['status']==0 for w in words);usable=sum(w['usable'] for w in words)
                if boolean(fields['transport_complete'])!=transport or number(fields['usable_words'])!=usable:raise ValueError('incorrect END summary')
                phase.update(transport_complete=transport,usable_words=usable)
                last_end=phase['end_us'] if phase['clock_ok'] else None
                ended.append(active);active=None
            elif kind=='OBSERVED':
                if not ended or fields['phase']!=ended[-1] or fields['phase'] in observed:raise ValueError('OBSERVED ordering')
                # Recompute derived values from WORD records, never trust prose.
                if boolean(fields['app08_execution_proven']):raise ValueError('unexpected app08 execution claim')
                if not boolean(fields['no_codec_verdict']):raise ValueError('unexpected codec claim')
                observed.add(fields['phase'])
            elif kind=='ASSETS':
                if assets_seen or ended!=PHASES[:1] or active or tx is not None:raise ValueError('asset ordering')
                if boolean(fields['modified']):raise ValueError('modified baseline assets')
                assets=boolean(fields['baseline_pinned'])
                assets_seen=True
            elif kind=='TX_RESULT':
                if tx is not None or not assets or active or ended!=PHASES[:1]:raise ValueError('transaction ordering')
                tx=fields['outcome']
                if tx not in ('ok','error'):raise ValueError('unknown transaction outcome')
            elif kind=='RESULT':
                if active:raise ValueError('RESULT inside snapshot')
                if boolean(fields['hardware_decode_verified']):raise ValueError('unexpected decode verdict')
                final=fields['outcome']
            else:raise ValueError('unknown observer record '+kind)
        if header is None or final is None:raise ValueError('missing RUN/RESULT')
        if final not in ('transaction_returned','preflight_refused','operator_cancelled','no_target','ambiguous_target'):raise ValueError('unknown final outcome')
        if final in ('operator_cancelled','no_target','ambiguous_target') and (identity or ended or tx):raise ValueError('negative-control contradiction')
        if final=='transaction_returned' and tx is None:raise ValueError('missing transaction outcome')
        if tx=='ok' and (ended!=PHASES or observed!=set(PHASES)):raise ValueError('missing post-transaction observation')
        result['outcome']=final;result['transaction_outcome']=tx
        result['record_complete']=tx=='ok' and ended==PHASES
        result['diagnostics_complete']=result['record_complete'] and all(p['usable_words']==COUNT and p['clock_ok'] for p in result['phases'].values())
    except (ValueError,KeyError) as e:
        result['errors'].append(f'line {locals().get("lineno",0)}: {e}')

    for phase,p in result['phases'].items():
        values={int(w['address'],16):w['value'] for w in p['words'] if w['usable']}
        def field(address,shift,mask):
            return (values[address]>>shift)&mask if address in values else None
        progress=field(0x118234,0,255) if field(0x118128,0,1)==1 else None
        p['derived']=dict(branch_bit0=field(0x12e0,0,1),gate_bit27=field(0x118c50,27,1),
            state_bits28_24=field(0x118034,24,31),gfw_progress=progress,
            gfw_completed=None if progress is None else progress==255,
            gfw_handoff_bit26=field(0x1180f8,26,1),devinit_bit1=field(0x2240c,1,1),
            nvdec_mask_raw=values.get(0x21378),
            app08_stage_raw=field(0x1430,0,15),app08_status_raw=field(0x1430,16,65535),
            app08_trace_enabled_raw=field(0x1448,31,1),app08_opcode_raw=field(0x1448,0,255),
            app08_pc_after_opcode_raw=field(0x1448,8,0x7fffff),
            app08_marker_provenance='unverified',app08_execution_proven=False,block31_execution_proven=False)
        top=[values.get(a) for a in ADDRESSES[len(CORE):]]
        p['top_sha256']=hashlib.sha256(struct.pack('<64I',*top)).hexdigest() if None not in top else None
        if phase==PHASES[1] and result['record_complete'] and not result['errors']:
            plm=values.get(0x409650)
            if plm is not None:
                result['feat_plm_state']=KNOWN_PLM.get(plm,'unrecognized')
                result['feat_l0_write_enabled']=bool(plm&0x10)
            needed=[0x409664,0x40966c,0x409668,0x1fa828]
            if all(a in values for a in needed):
                overrides=(values[needed[0]]==0x88888888 and values[needed[1]]==8 and
                    values[needed[2]]&0x07ffffff==0 and values[needed[3]]==0)
                result['compute_override_readback_confirmed']=overrides
                if plm in KNOWN_PLM:
                    result['compute_readback_confirmed']=overrides
    if result['record_complete'] and not result['errors']:
        a,b=[result['phases'][p] for p in PHASES]
        result['changed_valid_words']=[dict(address=x['address'],before=x['value'],after=y['value'])
            for x,y in zip(a['words'],b['words']) if x['usable'] and y['usable'] and x['value']!=y['value']]
    result['pci_config_write_count']=sum(p['writes'] for p in result['pci_access'].values())
    result['limits']=['Entry snapshot follows temporary PCI MEMORY enable; COMMAND is restored before baseline TX.',
        'External EFI entry is not proven pre-GFW.',
        'Scratch markers may be stale/reused; trace marks precede handlers and conditional stores.',
        'Trace enable is only read, never written; opcode af does not prove block31 execution.',
        'Late12e0=0 cannot recover the initial VBIOS branch.',
        'Register observations do not prove VBIOS execution or functional codec availability.',
        'Core snapshots add temporary PCI config writes. GSP residue DMEMC writes are accounted separately; baseline compute has writes.']
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('log',type=Path);p.add_argument('--manifest',type=Path);p.add_argument('--out',type=Path);a=p.parse_args()
    m=json.loads(a.manifest.read_text()) if a.manifest else {}
    result=analyze(a.log.read_text(errors='replace'),m.get('efi_sha256'),m.get('source_sha256'))
    result['log_sha256']=hashlib.sha256(a.log.read_bytes()).hexdigest()
    data=json.dumps(result,indent=2)+'\n'
    if a.out:a.out.write_text(data)
    else:print(data,end='')
    raise SystemExit(bool(result['errors']))
