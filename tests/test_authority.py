import unittest
from nvhw_observer.legacy_v6.authority import analyze, ADDRESSES, PHASES
from test_observer import fixture as core_fixture, RUN, EFI, SOURCE
from nvhw_observer.legacy_v6.core import valid


def record(kind,**fields):
    return 'HWT_AUTH_V1 '+kind+' '+' '.join(f'{k}={str(v).lower() if isinstance(v,bool) else v}' for k,v in fields.items())


def snapshot(phase,n,changes=None):
    lines=[record('BEGIN',run=RUN,phase=phase,begin_us=100+n*10,end_us=105+n*10,
                  clock_ok=True,command_ok=True,command='0x2',command_status='0x0',words=26,sequential=True)]
    values=[];usable=[]
    for i,a in enumerate(ADDRESSES):
        v,s=(changes or {}).get((phase,i),({0x110100:0x10,0x11010c:0x80,0x110240:2}.get(a,0),0))
        ok=valid(a,v,s);values.append(v);usable.append(ok)
        lines.append(record('WORD',run=RUN,phase=phase,index=i,address=hex(a),value=hex(v),status=hex(s),usable=ok))
    bracket=None if not all(usable[i] for i in (0,6,24,25)) else values[0]==values[24] and values[6]==values[25]
    lines.append(record('END',run=RUN,phase=phase,words=26,usable_words=sum(usable),
                        brackets_unchanged={None:'None',True:'Some(true)',False:'Some(false)'}[bracket],
                        diagnostic_gpu_mmio_writes=0,diagnostic_data_port_reads=0,atomic_snapshot=False,host_writable_proven=False))
    return lines


def fixture(path='ran',changes=None):
    """Synthetic success shape, not hardware evidence."""
    lines=[]
    for l in core_fixture().splitlines():
        lines.append(l)
        if 'OBSERVED' in l and 'phase=entry_' in l:
            lines+=snapshot('entry',0,changes)
        if ' ASSETS ' in l:
            lines.append(record('PATH',run=RUN,fwsec=path))
            for n,phase in enumerate(PHASES[1:6],1):
                if path=='ran' or phase=='post_fwsec':
                    lines+=snapshot(phase,n,changes)
        if 'OBSERVED' in l and 'phase=post_compute_' in l:
            lines+=snapshot('post_compute',6,changes)
    return '\n'.join(lines)+'\n'


class AuthorityTests(unittest.TestCase):
    def parse(self,t):return analyze(t,EFI,SOURCE)
    def test_complete_paths_are_not_unlock_or_write_access_proof(self):
        for path,count in [('ran',7),('skipped',3)]:
            r=self.parse(fixture(path));self.assertEqual(r['errors'],[])
            self.assertTrue(r['protocol_complete']);self.assertTrue(r['diagnostics_complete'])
            self.assertEqual(len(r['phases']),count)
            for k in ('codecs_unlocked','rt_unlocked','host_writable_proven','secure_mode_cause_proven'):
                self.assertFalse(r[k])
    def test_poison_and_status_do_not_become_security_mode_zero(self):
        for value,status in [(0xbadf1301,0),(0xffffffff,0),(0,7)]:
            r=self.parse(fixture(changes={('entry',10):(value,status)}))
            self.assertFalse(r['errors']);self.assertTrue(r['protocol_complete'])
            self.assertFalse(r['diagnostics_complete'])
            self.assertIsNone(r['phases']['entry']['sctl_low2_candidate'])
            self.assertIsNone(r['phases']['entry']['raw']['sctl_candidate'])
    def test_bracket_change_rejects_stability_but_preserves_raw_observation(self):
        r=self.parse(fixture(changes={('entry',24):(0x20,0)}))
        self.assertFalse(r['errors']);self.assertFalse(r['diagnostics_complete'])
        self.assertFalse(r['phases']['entry']['brackets_unchanged'])
    def test_no_retry_after_failed_bracket(self):
        r=self.parse(fixture(changes={('entry',24):(0,7)}))
        self.assertIsNone(r['phases']['entry']['brackets_unchanged'])
        self.assertEqual(len(r['phases']['entry']['words']),26)
    def test_missing_duplicate_reordered_and_mixed_words_rejected(self):
        lines=fixture().splitlines();i=next(i for i,l in enumerate(lines) if 'HWT_AUTH_V1 WORD' in l)
        for mutated in (lines[:i]+lines[i+1:],lines[:i]+[lines[i]]+lines[i:],lines[:i]+[lines[i+1],lines[i]]+lines[i+2:]):
            self.assertTrue(self.parse('\n'.join(mutated))['errors'])
        self.assertTrue(self.parse(fixture().replace('HWT_AUTH_V1 WORD run='+RUN,'HWT_AUTH_V1 WORD run=0000000000000000',1))['errors'])
    def test_wrong_addresses_counts_claims_or_memory_decode_rejected(self):
        for old,new in [('index=0 address=0x110100','index=0 address=0x625488'),('usable_words=26','usable_words=25'),
                        ('diagnostic_data_port_reads=0','diagnostic_data_port_reads=1'),
                        ('diagnostic_gpu_mmio_writes=0','diagnostic_gpu_mmio_writes=2'),
                        ('host_writable_proven=false','host_writable_proven=true'),
                        ('atomic_snapshot=false','atomic_snapshot=true'),('command=0x2','command=0x0')]:
            with self.subTest(new=new):self.assertTrue(self.parse(fixture().replace(old,new,1))['errors'])
    def test_path_skip_cannot_hide_missing_required_ran_phases(self):
        self.assertTrue(self.parse(fixture('skipped').replace('fwsec=skipped','fwsec=ran'))['errors'])
        self.assertTrue(self.parse(fixture().replace('fwsec=ran','fwsec=skipped'))['errors'])
    def test_core_failure_is_not_authority_success(self):
        r=self.parse(fixture().replace('baseline_pinned=true','baseline_pinned=false'))
        self.assertTrue(r['errors']);self.assertFalse(r['protocol_complete'])
    def test_negative_control_has_no_phantom_gpu_evidence(self):
        lines=core_fixture().splitlines()
        t=lines[0]+'\n'+f'HWT_VBIOS_V6 RESULT run={RUN} outcome=no_target hardware_decode_verified=false\n'
        r=self.parse(t);self.assertEqual(r['errors'],[]);self.assertFalse(r['protocol_complete'])
    def test_valid_delta_does_not_imply_execution_or_unlock(self):
        r=self.parse(fixture(changes={('post_fwsec_descriptor',9):(0x1000054,0)}))
        self.assertFalse(r['errors']);self.assertTrue(any(d['words'] for d in r['changes']))
        self.assertFalse(r['host_writable_proven']);self.assertFalse(r['codecs_unlocked'])
    def test_cross_stream_order_rejected(self):
        t=fixture();a=t.index('HWT_AUTH_V1 BEGIN run='+RUN+' phase=entry ')
        b=t.index('HWT_VBIOS_V6 ASSETS',a)
        block=t[a:b];t=t[:a]+t[b:]
        r=self.parse(t+block);self.assertTrue(r['errors'])
    def test_truncation_and_duplicate_path_rejected(self):
        t=fixture();lines=t.splitlines()
        for cut in (1,70,len(lines)-30,len(lines)-1):self.assertTrue(self.parse('\n'.join(lines[:cut]))['errors'])
        path=record('PATH',run=RUN,fwsec='ran')
        self.assertTrue(self.parse(t.replace(path,path+'\n'+path))['errors'])


if __name__=='__main__':unittest.main()
