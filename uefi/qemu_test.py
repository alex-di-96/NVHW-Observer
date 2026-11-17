#!/usr/bin/env python3
"""OVMF controls. Synthetic GPU only; no passthrough/network/physical devices."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'src'))
from nvhw_observer.passive_m1 import analyze


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):return subprocess.run(args,check=True,text=True,capture_output=True,timeout=20)


def select_cases(real_successor=False, outer_mock=False, selected=None):
    cases=[('complete',1,None),('boot0',2,'boot0'),('rom',3,'rom_identity'),
           ('read-failure',4,'snapshot_transport'),('restore-failure',5,'command_restore'),
           ('not-d0',6,'access_guards'),('ambiguous',7,'target_selection'),
           ('enable-error-after-write',8,'command_enable'),('memory-enabled',9,None),
           ('wrong-successor',1,'successor_identity'),('missing-log-dir',1,'log_create')]
    skipped=[]
    if real_successor:cases.append(('no-gpu',0,'target_selection'))
    else:skipped.append({'case':'no-gpu','reason':'requires independently pinned external successor'})
    if outer_mock:cases.append(('one-shot-chain',1,None))
    else:skipped.append({'case':'one-shot-chain','reason':'external frontend not supplied'})
    if selected:
        cases=[c for c in cases if c[0]==selected]
        if not cases:raise ValueError('unknown case or missing external input: '+selected)
    return cases,skipped


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--real-successor',type=Path,help='optional: enables mode0 no-GPU control')
    p.add_argument('--outer-mock',type=Path)
    p.add_argument('--ovmf-code',type=Path,default=Path('/usr/share/OVMF/OVMF_CODE_4M.fd'))
    p.add_argument('--ovmf-vars',type=Path,default=Path('/usr/share/OVMF/OVMF_VARS_4M.fd'))
    p.add_argument('--case');a=p.parse_args();build=a.build.resolve();out=a.out.resolve()
    cases,skipped=select_cases(a.real_successor is not None,a.outer_mock is not None,a.case)
    if out.exists() and any(out.iterdir()):raise ValueError('preserve existing test results')
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((build/'manifest.json').read_text())
    log_stem=manifest.get('log_stem','nvhw-m1')
    assert log_stem in ('nvhw-m1','nvhw-m2')
    if a.real_successor:
        assert sha(a.real_successor)==manifest['artifacts']['0']['successor_sha256']
    (out/'plan.json').write_text(json.dumps({'cases':[c[0] for c in cases],
        'skipped':skipped,'gpu_passthrough':False,'network':False},indent=2)+'\n')
    results=[]
    for name,mode,reason in cases:
        case=out/name;case.mkdir()
        with tempfile.TemporaryDirectory(prefix='nvhw-qemu-') as temp:
            tmp=Path(temp);fat=tmp/'fat';(fat/'EFI/BOOT').mkdir(parents=True);(fat/'EFI/HWT').mkdir()
            if name!='missing-log-dir':(fat/'HWT').mkdir()
            source=build/f'nvhw-observer-{mode}.efi'
            assert sha(source)==manifest['artifacts'][str(mode)]['sha256']
            outer=name=='one-shot-chain'
            shutil.copy2(a.outer_mock if outer else source,fat/'EFI/BOOT/BOOTX64.EFI')
            if outer:
                shutil.copy2(source,fat/'EFI/HWT/NVDEC.EFI')
                (fat/'HWT/NVDEC.ONCE').write_text('HWT-NVDEC-PROBE-1\n')
            successor=a.real_successor if mode==0 else build/'mock-successor.efi'
            shutil.copy2(successor,fat/'EFI/HWT/UNLOCK.EFI')
            if name=='wrong-successor':(fat/'EFI/HWT/UNLOCK.EFI').write_bytes(b'wrong build')
            (fat/'loader.log').write_text('PRESERVE_BASELINE_LOG\n')
            disk=tmp/'disk.img'
            with disk.open('wb') as f:f.truncate(128*1024*1024)
            run(['parted','-s',str(disk),'mklabel','gpt','mkpart','ESP','fat32','1MiB','127MiB','set','1','esp','on'])
            run(['mkfs.fat','-F','32','--offset=2048',str(disk),str(126*1024)])
            fsimg=str(disk)+'@@1048576'
            run(['mcopy','-i',fsimg,'-s',*[str(x) for x in fat.iterdir()],'::/'])
            repeats=2 if name in ('complete','one-shot-chain') else 1
            first=None
            for n in range(1,repeats+1):
                shutil.copy2(a.ovmf_vars,tmp/'vars.fd')
                serial=case/f'serial-{n}.log';debug=case/f'debug-{n}.log'
                cmd=['qemu-system-x86_64','-machine','q35,accel=tcg','-m','256','-display','none','-net','none',
                     '-drive','if=pflash,format=raw,readonly=on,file='+str(a.ovmf_code.resolve()),
                     '-drive','if=pflash,format=raw,file='+str(tmp/'vars.fd'),'-drive','format=raw,file='+str(disk),
                     '-serial','file:'+str(serial),'-debugcon','file:'+str(debug),'-global','isa-debugcon.iobase=0x402',
                     '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-no-reboot']
                started=time.monotonic()
                with (case/f'stderr-{n}.log').open('wb') as err:
                    proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=err)
                    try:
                        while proc.poll() is None and time.monotonic()-started<50:
                            if serial.exists() and 'NVHW STOP:' in serial.read_text(errors='replace'):break
                            time.sleep(.1)
                    finally:
                        if proc.poll() is None:proc.terminate()
                        proc.wait(timeout=10)
                handed=debug.exists() and 'NVHW_QEMU_SUCCESSOR_EXECUTED' in debug.read_text(errors='replace')
                result={'case':name,'run':n,'mode':mode,'efi_sha256':sha(source),
                        'successor_executed':handed,'seconds':round(time.monotonic()-started,3),'gpu_passthrough':False}
                if name=='missing-log-dir':
                    assert not handed and 'NVHW STOP: log_create' in serial.read_text(errors='replace')
                else:
                    log=case/f'observer-{n}.log'
                    seq=1 if outer else n
                    run(['mcopy','-o','-i',fsimg,f'::/HWT/{log_stem}-{seq:04d}.log',str(log)])
                    text=log.read_text();parsed=analyze(text,manifest,allow_mock=True)
                    (case/f'parsed-{n}.json').write_text(json.dumps(parsed,indent=2)+'\n')
                    assert not parsed['errors'],parsed['errors']
                    if reason:
                        assert not handed and parsed['outcome']=='stopped' and parsed['stop_reason']==reason,parsed
                        assert not parsed['capture_complete']
                        if name in ('boot0','rom','read-failure','enable-error-after-write'):assert parsed['pci_restored']
                        if name=='restore-failure':assert parsed['pci_restored'] is False
                    else:
                        assert handed and parsed['capture_complete'] and parsed['diagnostics_complete'],parsed
                        assert len(parsed['words'])==len(manifest['profile']['registers'])
                        assert all(w['value']==0 for w in parsed['words'] if 0x22700<=w['address']<0x22800)
                    if n==1:first=text
                    else:
                        old=case/'first-preserved.log';run(['mcopy','-o','-i',fsimg,f'::/HWT/{log_stem}-0001.log',str(old)])
                        assert old.read_text()==first
                        if outer:
                            missing=subprocess.run(['mcopy','-i',fsimg,f'::/HWT/{log_stem}-0002.log',str(case/'unexpected.log')],capture_output=True)
                            assert missing.returncode!=0,'one-shot unexpectedly reran observer'
                    if outer:
                        missing=subprocess.run(['mcopy','-i',fsimg,'::/HWT/NVDEC.ONCE',str(case/'unexpected.once')],capture_output=True)
                        assert missing.returncode!=0,'ticket was not consumed'
                preserved=case/f'baseline-{n}.log';run(['mcopy','-o','-i',fsimg,'::/loader.log',str(preserved)])
                assert preserved.read_text()=='PRESERVE_BASELINE_LOG\n'
                result['pass']=True;results.append(result)
                (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
                print(json.dumps(result),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
