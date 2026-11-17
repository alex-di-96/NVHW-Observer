import unittest
from nvhw_observer.legacy_v6.core import ADDRESSES,COUNT,PHASES,analyze,valid

RUN='1234567890abcdef';EFI='a'*64;SOURCE='b'*64
def record(kind,**fields):
    return 'HWT_VBIOS_V6 '+kind+' '+' '.join(f'{k}={str(v).lower() if isinstance(v,bool) else v}' for k,v in fields.items())

def fixture(changes=None):
    """Synthetic protocol fixture, not a captured hardware success."""
    def access(phase,command,writes):
        return record('ACCESS',run=RUN,phase=phase,outcome='ok',facts_ok=True,
            saved_command=hex(command),active_ok=True,active_command=hex(command|2),
            final_ok=True,final_command=hex(command),writes=writes,restored=True,pmcsr='0x0',bar0='0xde000000')
    lines=[record('RUN',run=RUN,source_sha256=SOURCE,efi_file_sha256=EFI,words=86,stages=2,core_gpu_mmio_writes=0,pci_memory_scope=True,pre_gfw_proven=False,trace_enable_writes=0,app08_execution_proven=False),
           access(PHASES[0],0,2),
           record('IDENTITY',run=RUN,pci_id='0x1e0910de',subsystem='0x155410de',bdf='0000:01:00.0',rom_pinned=True)]
    for n,phase in enumerate(PHASES):
        if n:
            lines += [record('ASSETS',run=RUN,baseline_pinned=True,modified=False),record('TX_RESULT',run=RUN,outcome='ok'),access(phase,7,0)]
        lines += [record('BEGIN',run=RUN,phase=phase,begin_us=100+n*300,end_us=200+n*300,clock_ok=True,words=86,sequential=True)]
        transport=True;usable=0
        for i,address in enumerate(ADDRESSES):
            value={0x118128:1,0x118234:0x3ff,0x1180f8:0x17300000,0x12e0:0x20,
                   0x21378:7,0x409650:0xffffffff if n else 0xffffff8f,
                   0x409664:0x88888888 if n else 0,0x40966c:8 if n else 0}.get(address,0)
            value,status=(changes or {}).get((n,address),(value,0));ok=valid(address,value,status)
            transport &= status==0;usable+=ok
            lines.append(record('WORD',run=RUN,phase=phase,index=i,address=hex(address),value=hex(value),status=hex(status),usable=ok))
        lines += [record('END',run=RUN,phase=phase,words=86,transport_complete=transport,usable_words=usable,core_gpu_mmio_writes=0),
                  record('OBSERVED',run=RUN,phase=phase,gfw_completed='Some(true)',compute_readback='Some(true)' if n else 'Some(false)',no_codec_verdict=True,app08_execution_proven=False)]
    lines.append(record('RESULT',run=RUN,outcome='transaction_returned',hardware_decode_verified=False))
    return '\n'.join(lines)+'\n'


class ObserverTests(unittest.TestCase):
    def parse(self,text):return analyze(text,EFI,SOURCE)
    def test_valid_baseline_does_not_claim_codecs_or_pre_gfw(self):
        r=self.parse(fixture());self.assertFalse(r['errors']);self.assertTrue(r['record_complete']);self.assertTrue(r['diagnostics_complete'])
        self.assertTrue(r['compute_readback_confirmed']);self.assertFalse(r['functional_decode_verified']);self.assertFalse(r['pre_gfw_proven'])
        self.assertEqual(r['phases'][PHASES[0]]['top_sha256'],r['phases'][PHASES[1]]['top_sha256'])
    def test_optional_badf_keeps_compute_but_not_diagnostic_success(self):
        r=self.parse(fixture({(1,0x118c50):(0xbadf1301,0)}));self.assertFalse(r['errors'])
        self.assertTrue(r['record_complete']);self.assertFalse(r['diagnostics_complete']);self.assertTrue(r['compute_readback_confirmed'])
        self.assertIsNone(r['phases'][PHASES[1]]['derived']['gate_bit27'])
    def test_failed_zero_has_no_value_or_delta(self):
        r=self.parse(fixture({(1,0x21378):(0,0x8000000000000007)}));self.assertFalse(r['errors'])
        self.assertIsNone(r['phases'][PHASES[1]]['derived']['nvdec_mask_raw']);self.assertNotIn('0x21378',[x['address'] for x in r['changed_valid_words']])
    def test_gfw_progress_needs_plm(self):
        r=self.parse(fixture({(0,0x118128):(0,0)}));self.assertIsNone(r['phases'][PHASES[0]]['derived']['gfw_completed'])
    def test_gate_change_is_observation_not_vbios_execution(self):
        r=self.parse(fixture({(1,0x118c50):(0x8000000,0)}));self.assertEqual(r['phases'][PHASES[1]]['derived']['gate_bit27'],1)
        self.assertFalse(r['functional_decode_verified'])
    def test_incomplete_log_cannot_pass(self):
        lines=fixture().splitlines()
        for cut in (0,1,6,40,len(lines)-2,len(lines)-1):
            with self.subTest(cut=cut):self.assertTrue(self.parse('\n'.join(lines[:cut]))['errors'])
    def test_duplicate_and_out_of_order_words_rejected(self):
        lines=fixture().splitlines();i=next(i for i,l in enumerate(lines) if ' WORD ' in l)
        for bad in (lines[:i]+[lines[i]]+lines[i:],lines[:i]+[lines[i+1],lines[i]]+lines[i+2:]):self.assertTrue(self.parse('\n'.join(bad))['errors'])
    def test_mixed_run_or_wrong_build_rejected(self):
        for old,new in [('efi_file_sha256='+EFI,'efi_file_sha256='+'c'*64),('source_sha256='+SOURCE,'source_sha256='+'d'*64),('WORD run='+RUN,'WORD run=0000000000000000')]:
            self.assertTrue(self.parse(fixture().replace(old,new,1))['errors'])
    def test_bad_summary_validity_or_address_rejected(self):
        for old,new in [('usable_words=86','usable_words=85'),('index=0 address=0x12e0','index=0 address=0x625488'),('status=0x0 usable=true','status=0x1 usable=true'),('core_gpu_mmio_writes=0','core_gpu_mmio_writes=1')]:
            self.assertTrue(self.parse(fixture().replace(old,new,1))['errors'])
    def test_backwards_clock_rejected(self):
        self.assertTrue(self.parse(fixture().replace('begin_us=400','begin_us=50'))['errors'])
    def test_post_without_successful_transaction_rejected(self):
        self.assertTrue(self.parse(fixture().replace('outcome=ok','outcome=error'))['errors'])
    def test_unreadable_compute_is_not_confirmed(self):
        r=self.parse(fixture({(1,0x409664):(0xbadf1301,0)}));self.assertIsNone(r['compute_readback_confirmed'])
    def test_negative_control_is_not_successful_gpu_observation(self):
        text=fixture().splitlines()[0]+'\n'+record('RESULT',run=RUN,outcome='no_target',hardware_decode_verified=False)
        r=self.parse(text);self.assertFalse(r['errors']);self.assertFalse(r['record_complete']);self.assertIsNone(r['compute_readback_confirmed'])
    def test_duplicate_header_and_identity_rejected(self):
        for i in (0,2):
            lines=fixture().splitlines();lines.insert(i,lines[i]);self.assertTrue(self.parse('\n'.join(lines))['errors'])

    def test_missing_access_or_failed_restore_cannot_pass(self):
        lines=fixture().splitlines()
        for i,line in enumerate(lines):
            if ' ACCESS ' in line:
                self.assertTrue(self.parse('\n'.join(lines[:i]+lines[i+1:]))['errors'])
        for old,new in [('restored=true','restored=false'),('active_command=0x2','active_command=0x6'),
                        ('final_command=0x0','final_command=0x2'),('writes=2','writes=1'),
                        ('facts_ok=true','facts_ok=false'),('pmcsr=0x0','pmcsr=0x3')]:
            self.assertTrue(self.parse(fixture().replace(old,new,1))['errors'])

    def test_config_writes_accounted_separately_from_gpu_mmio(self):
        r=self.parse(fixture());self.assertFalse(r['errors']);self.assertEqual(r['pci_config_write_count'],2)
        self.assertTrue(all(v['restored'] for v in r['pci_access'].values()))


    def test_relock_states_confirm_override_without_open_write_gate(self):
        for plm in (0xffffffff,0xffffffef,0xffffff8f):
            r=self.parse(fixture({(1,0x409650):(plm,0)}))
            self.assertFalse(r['errors']);self.assertTrue(r['compute_readback_confirmed'])
            self.assertEqual(r['feat_l0_write_enabled'],plm==0xffffffff)
            for addr in (0x409664,0x40966c,0x409668,0x1fa828):
                bad=self.parse(fixture({(1,0x409650):(plm,0),(1,addr):(1,0)}))
                self.assertFalse(bad['compute_readback_confirmed'])

    def test_unknown_and_poison_plm_do_not_confirm_compute(self):
        for raw,status in ((0x12345678,0),(0xbadf5040,0),(0,1)):
            r=self.parse(fixture({(1,0x409650):(raw,status)}))
            self.assertTrue(r['compute_override_readback_confirmed'])
            self.assertIsNone(r['compute_readback_confirmed'])

    def test_new_markers_cannot_establish_handler_or_block_execution(self):
        trace=0x80000000|(0x7ec2<<8)|0xaf
        r=self.parse(fixture({(0,0x1430):(7,0),(0,0x1448):(trace,0)}))
        self.assertFalse(r['errors'])
        d=r['phases'][PHASES[0]]['derived']
        self.assertEqual(d['app08_stage_raw'],7);self.assertEqual(d['app08_opcode_raw'],0xaf)
        self.assertEqual(d['app08_pc_after_opcode_raw'],0x7ec2)
        self.assertFalse(d['app08_execution_proven']);self.assertFalse(d['block31_execution_proven'])
        for addr in (0x1430,0x1448):
            bad=self.parse(fixture({(0,addr):(0xbadf5040,0)}))
            self.assertFalse(bad['diagnostics_complete']);self.assertTrue(bad['compute_readback_confirmed'])
            self.assertEqual(bad['phases'][PHASES[0]]['top_sha256'],r['phases'][PHASES[0]]['top_sha256'])

    def test_trace_write_or_execution_claim_is_rejected(self):
        for old,new in [('trace_enable_writes=0','trace_enable_writes=1'),
                        ('app08_execution_proven=false','app08_execution_proven=true')]:
            self.assertTrue(self.parse(fixture().replace(old,new))['errors'])



if __name__=='__main__':unittest.main()
