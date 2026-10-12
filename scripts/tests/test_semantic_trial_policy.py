from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_evidence_pipeline as baseline
from validate_score_job import validate
from trial_assessment import POLICY_VERSION, SCHEMA_VERSION, report_lines
from workflow_experiment import independently_verified


class SemanticTrialPolicyTests(unittest.TestCase):
    def fixture(self, trigger='signed_trial_agreement', stage='agreement_signed'):
        old = baseline.DeterministicScoreValidationTests()
        old.setUp()
        job, audit = old.valid_job_and_audit()
        job.update(base=65, na=0)
        job['modules'][3] = ['D试驾',25,20]
        job['rows'] = [['D','D1','邀约',5,5,'04:29','有效邀约'],
                       ['D','D2-D9','体验',20,15,'09:53','按默认口径语义推断']]
        audit['candidates'] = [c for c in audit['candidates'] if c['id'] != 'E003']
        audit['candidates'].append({'id':'S001','category':'test_drive_response','status':'confirmed','fact_status':'confirmed',
                                    'timestamp':'09:53-10:25','review_transcript':'签完本次试驾协议','review_model':'large-v3-turbo',
                                    'review_channel':'mix'})
        value = {'schema_version':SCHEMA_VERSION,'policy_version':POLICY_VERSION,
                 'mode':'semantic_inference','fact_status':'inferred','direct_audio_completion_verified':False,
                 'conclusion':'occurred','default_trigger':trigger,'confidence':'medium',
                 'reviewed_at':'2026-10-06T11:00:00+08:00',
                 'supporting_evidence':[{'candidate_id':'S001','window':'09:53-10:25','channel':'mix','model':'large-v3-turbo',
                                       'stage':stage,'summary':'本次试驾协议签完或路线已选定'}],
                 'counter_evidence':[],'alternative_explanations':['仅手续不直接证明动态驾驶，采用用户默认'],
                 'rationale':'确认默认触发行为，按用户OR口径'}
        job['trial_assessment']=value
        audit['trial_assessment']=copy.deepcopy(value)
        return job,audit

    def mutate(self,job,audit,key,value):
        job['trial_assessment'][key]=value
        audit['trial_assessment']=copy.deepcopy(job['trial_assessment'])

    def test_agreement_and_route_phrases_become_review_candidates(self):
        from evidence_candidates import build_candidates,compare_signals
        records=[{'t0':90000,'t1':90200,'text':'试驾协议已经签好了'},
                 {'t0':180000,'t1':180200,'text':'我们就选这条短线试驾路线'}]
        candidates=build_candidates(records)
        default=[c for c in candidates if c['category']=='test_drive_default_basis']
        self.assertEqual(len(default),2)
        status,*_=compare_signals('test_drive_default_basis','试驾协议签好了','试驾协议签好了')
        self.assertEqual(status,'needs_manual_review')  # Main model semantic adjudication, not human listening.

    def test_score_row_cannot_hide_inference_basis(self):
        job,audit=self.fixture()
        job['rows'][1][6]='已音频证实实际试驾'
        self.assertFalse(validate(job,audit)['valid'])

    def test_signed_agreement_alone_defaults_to_trial(self):
        job,audit=self.fixture()
        result=validate(job,audit)
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['calculated_score'],65)
        self.assertEqual(result['trial_completion_basis'],'semantic_inference')
        self.assertFalse(audit['trial_review']['timeline']['actual_drive_chain'])

    def test_route_selection_alone_defaults_to_trial(self):
        job,audit=self.fixture('trial_route_selected','route_selected')
        audit['candidates'][-1]['review_transcript']='已经选择短线试驾路线'
        result=validate(job,audit)
        self.assertTrue(result['valid'],result['errors'])

    def test_inviting_to_sign_is_not_completed_signing(self):
        job,audit=self.fixture(stage='paperwork')
        audit['candidates'][-1]['review_transcript']='等会去签协议'
        result=validate(job,audit)
        self.assertFalse(result['valid'])
        self.assertTrue(any('completed signing' in x for x in result['errors']))

    def test_route_introduction_is_not_route_selection(self):
        job,audit=self.fixture('trial_route_selected','route_introduction')
        result=validate(job,audit)
        self.assertFalse(result['valid'])
        self.assertTrue(any('selected route' in x for x in result['errors']))

    def test_inference_must_not_be_directly_confirmed(self):
        job,audit=self.fixture()
        self.mutate(job,audit,'direct_audio_completion_verified',True)
        self.assertFalse(validate(job,audit)['valid'])
        job,audit=self.fixture()
        audit['trial_review']['timeline']['actual_drive_chain']=True
        self.assertFalse(validate(job,audit)['valid'])

    def test_context_chain_still_requires_completion_context(self):
        job,audit=self.fixture('context_chain','paperwork')
        self.assertFalse(validate(job,audit)['valid'])

    def test_d1_na_precedence_is_preserved(self):
        job,audit=self.fixture()
        job.update(base=45,na=25)
        job['modules'][3]=['D试驾',0,0]
        for row in job['rows']:row[4]='NA'
        audit['candidates'].append({'id':'N001','category':'na_basis','status':'confirmed','timestamp':'04:00'})
        result=validate(job,audit)
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['calculated_score'],60)

    def test_inferred_bonus_does_not_qualify(self):
        job,audit=self.fixture()
        job['bonus']=3
        audit['candidates'].append({'id':'W001','category':'bonus_wet_tissue','status':'confirmed',
                                   'fact_status':'inferred','timestamp':'30:00'})
        self.assertFalse(validate(job,audit)['valid'])

    def test_job_audit_disagreement_blocks_publication(self):
        job,audit=self.fixture()
        audit['trial_assessment']['default_trigger']='trial_route_selected'
        self.assertFalse(validate(job,audit)['valid'])

    def test_inference_is_not_experiment_ground_truth(self):
        case={'semantic_trial_inference':True}
        value={'quality_verified':True,'audit_ref':'audit.json'}
        self.assertFalse(independently_verified(case,value))
        value['independent_original_audio_comparison']=True
        self.assertTrue(independently_verified(case,value))
        value['verification_basis']='semantic_inference'
        self.assertFalse(independently_verified(case,value))

    def test_report_exposes_default_and_inference(self):
        job,audit=self.fixture()
        text='\n'.join(report_lines(job))
        self.assertIn('试驾协议已签署',text)
        self.assertIn('任一成立',text)
        self.assertIn('语义推断',text)



if __name__=='__main__':
    unittest.main()

