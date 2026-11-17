import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('qemu_plan',Path(__file__).resolve().parents[1]/'uefi/qemu_test.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)


class QemuPlanTests(unittest.TestCase):
    def test_public_run_uses_only_generated_mocks_and_records_omissions(self):
        cases,skipped=q.select_cases()
        self.assertEqual(len(cases),11)
        self.assertTrue(all(1<=c[1]<=9 for c in cases))
        self.assertEqual({c['case'] for c in skipped},{'no-gpu','one-shot-chain'})

    def test_missing_external_case_is_not_a_silent_pass(self):
        for case in ('no-gpu','one-shot-chain','typo'):
            with self.assertRaises(ValueError):q.select_cases(selected=case)

    def test_explicit_external_inputs_enable_only_their_cases(self):
        cases,skipped=q.select_cases(real_successor=True)
        self.assertIn(('no-gpu',0,'target_selection'),cases)
        self.assertEqual([c['case'] for c in skipped],['one-shot-chain'])
        cases,skipped=q.select_cases(True,True,'one-shot-chain')
        self.assertEqual(cases,[('one-shot-chain',1,None)]);self.assertEqual(skipped,[])


if __name__=='__main__':unittest.main()
