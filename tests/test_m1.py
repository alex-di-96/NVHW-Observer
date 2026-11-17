import copy
import json
from pathlib import Path
import unittest
from nvhw_observer.passive_m1 import analyze

PROFILE=json.loads((Path(__file__).resolve().parents[1]/'uefi/profiles/cmp50hx-tu102-reference-m1.json').read_text())
MANIFEST={'source_sha256':'a'*64,'profile_sha256':'b'*64,'profile':PROFILE,
          'artifacts':{'0':{'sha256':'c'*64,'successor_sha256':PROFILE['successor_sha256'],
                           'rom_sha256':PROFILE['rom']['sha256']}}}


def fixture(command=0, poison=False, profile=None, poison_address='00021378'):
    """Synthetic protocol input, not a measured GPU result."""
    profile=PROFILE if profile is None else profile
    count=len(profile['registers'])
    lines=[]
    def row(kind,**kw):lines.append('NVHW1 run=0123456789abcdef '+kind+' '+' '.join(f'{k}={v}' for k,v in kw.items()))
    row('RUN',schema=1,test=0,source='a'*64,profile='b'*64,words=count,seq=1)
    row('SELF',sha256='c'*64);row('NEXT',sha256=profile['successor_sha256'])
    row('TARGET',bdf='0000:03:00.0',pci=profile['pci_id'],subsystem=profile['subsystem_id'])
    row('GUARDS',pmcsr='00000000',bar_base='00000000de000000',bar_size='0000000001000000')
    row('ACCESS',original=f'{command:04x}',expected=f'{command|2:04x}')
    row('ACTIVE',value=f'{command|2:04x}',status='0000000000000000')
    row('BOOT0',value=profile['boot0'],status='0000000000000000')
    row('ROM',sha256=profile['rom']['sha256'],bytes=65536,offset='00300000')
    row('BEGIN',phase='pre_compute',words=count,ticks='100',atomic=0,gpu_mmio_writes=0)
    for i,address in enumerate(profile['registers']):
        bad=poison and address==poison_address
        row('WORD',index=i,address=address,value='badf1301' if bad else '00000000',status='0000000000000000',valid=int(not bad))
    row('END',words=count,usable=count-int(poison),transport_errors=0,ticks='200')
    row('RESTORE',original=f'{command:04x}',final=f'{command:04x}',write_status='0',read_status='0',writes=0 if command&2 else 2)
    row('RESULT',outcome='complete',usable=count-int(poison),words=count,functional_tests='not_measured')
    row('HANDOFF',sha256=profile['successor_sha256'],confirmation='successor')
    return '\n'.join(lines)+'\n'


class PassiveTests(unittest.TestCase):
    def parse(self,text):return analyze(text,MANIFEST)
    def test_complete_capture_does_not_measure_features(self):
        result=self.parse(fixture());self.assertFalse(result['errors']);self.assertTrue(result['capture_complete'])
        self.assertTrue(result['pci_restored']);self.assertEqual(result['functional_tests'],'not_measured')
    def test_already_enabled_memory_has_no_config_writes(self):
        self.assertTrue(self.parse(fixture(7))['capture_complete'])
        self.assertTrue(self.parse(fixture(7).replace('writes=0','writes=2'))['errors'])
    def test_poison_is_unknown_not_zero(self):
        result=self.parse(fixture(poison=True));self.assertFalse(result['errors']);self.assertFalse(result['diagnostics_complete'])
        word=next(w for w in result['words'] if w['address']==0x21378)
        self.assertIsNone(word['value']);self.assertEqual(word['raw_value'],0xbadf1301)
    def test_missing_duplicate_reordered_and_mixed_run(self):
        lines=fixture().splitlines();i=next(i for i,s in enumerate(lines) if ' WORD ' in s)
        for changed in [lines[:i]+lines[i+1:],lines[:i]+[lines[i]]+lines[i:],lines[:i]+[lines[i+1],lines[i]]+lines[i+2:]]:
            self.assertTrue(self.parse('\n'.join(changed))['errors'])
        self.assertTrue(self.parse(fixture().replace('run=0123456789abcdef WORD','run=2222222222222222 WORD',1))['errors'])
    def test_wrong_build_profile_rom_and_successor_are_rejected(self):
        for old,new in [('source='+'a'*64,'source='+'d'*64),('profile='+'b'*64,'profile='+'d'*64),
                        ('sha256='+'c'*64,'sha256='+'d'*64),(PROFILE['rom']['sha256'],'e'*64),
                        (PROFILE['successor_sha256'],'e'*64)]:
            self.assertTrue(self.parse(fixture().replace(old,new))['errors'])
    def test_claims_and_unrestored_state_cannot_pass(self):
        for old,new in [('atomic=0','atomic=1'),('gpu_mmio_writes=0','gpu_mmio_writes=1'),
                        ('final=0000','final=0002'),('write_status=0','write_status=7'),
                        ('functional_tests=not_measured','functional_tests=pass'),
                        ('schema=1','schema=1 unknown=1'),('original=0000','original=-1')]:
            self.assertTrue(self.parse(fixture().replace(old,new))['errors'])
    def test_truncation_never_looks_complete(self):
        lines=fixture().splitlines()
        for cut in (0,1,9,50,len(lines)-1):
            r=self.parse('\n'.join(lines[:cut]));self.assertTrue(r['errors']);self.assertFalse(r['capture_complete'])
    def test_mock_rejected_by_default(self):
        manifest=copy.deepcopy(MANIFEST);manifest['artifacts']['1']=manifest['artifacts']['0']
        text=fixture().replace('test=0','test=1')
        self.assertTrue(analyze(text,manifest)['errors'])
        self.assertTrue(analyze(text,manifest,allow_mock=True)['capture_complete'])
    def test_gnu_efi_uppercase_hex(self):
        text=fixture().replace('0123456789abcdef','0123456789ABCDEF').replace('1e0910de','1E0910DE').replace('155410de','155410DE').replace('162000a1','162000A1')
        self.assertTrue(self.parse(text)['capture_complete'])


if __name__=='__main__':unittest.main()
