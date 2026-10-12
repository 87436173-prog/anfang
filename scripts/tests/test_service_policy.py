"""Policy boundary regression: evidence isolation, exact NA scope, bonus and rendering."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import service_policy as p
import validate_score_job as v
import workflow_support as w

def candidate(cid='Q',category='na_basis'):
 return {'id':cid,'category':category,'status':'confirmed','fact_status':'confirmed','timestamp':'01:00-01:20','review_channel':'mix','review_model':'large-v3-turbo','review_transcript':'原音已核验','introduced_to_customer':True}
def base():
 rows=[['E','E2','报价',3,0,'01:00','待生成'],['B','B8','湿纸巾',3,0,'01:00','未确认'],['B','B8coffee','星巴克',3,0,'01:00','未确认']]
 service={k:{'status':'not_confirmed','evidence':'00:00-20:00未确认'} for k in ('introduction','provided','consumed')}
 assessment={'E2':{'kind':'evidence','rationale':'六要素逐一复核'}}
 audit={'service_policy_version':p.VERSION,'row_assessments':assessment,'candidates':[candidate()], 'starbucks_service':service,'derived':{'quote_completeness':{'components':{'vehicle_or_price':True},'component_sources':{'vehicle_or_price':['Q']}}}}
 job={'service_policy_version':p.VERSION,'row_assessments':assessment,'starbucks_service':service,'rows':rows}
 return p.prepare_report(job,audit),audit
class ServicePolicyTests(unittest.TestCase):
 def errors(self,job,audit):
  errors=[];p.validate(job,audit,errors);return errors
 def test_e2_deduction_names_only_unconfirmed_components(self):
  job,audit=base();self.assertEqual(self.errors(job,audit),[])
  self.assertNotIn('车型/价格',job['rows'][0][6]);self.assertIn('销售讲解内饰颜色',job['rows'][0][6])
  audit['candidates'][0]['fact_status']='unresolved'
  self.assertIn('vehicle_or_price',p.missing_e2(audit))
 def test_e2_full_points_do_not_accept_candidate_without_original_review(self):
  job,audit=base();job['rows'][0][4]=3
  audit['derived']['quote_completeness']={'components':{k:True for k in p.E2_COMPONENTS},'component_sources':{k:['Q'] for k in p.E2_COMPONENTS}}
  audit['candidates'][0].pop('review_channel')
  job=p.prepare_report(job,audit)
  self.assertTrue(any('six original-audio' in x for x in self.errors(job,audit)))
 def test_starbucks_introduction_awards_without_consumption(self):
  job,audit=base();job['rows'][2][4]=3
  job['starbucks_introduction']={'status':'已介绍'};job['starbucks_service']['introduction']['status']='confirmed';audit['starbucks_service']=copy.deepcopy(job['starbucks_service']);audit['candidates'].append(candidate('S','starbucks_introduction'))
  self.assertEqual(self.errors(job,audit),[])
  audit['candidates'][-1]['category']='bonus_starbucks'
  self.assertTrue(any('B8coffee bonus lacks' in x for x in self.errors(job,audit)))
 def test_two_distinct_b8_services_total_six_no_third_award(self):
  job,audit=base();job['rows'][1][4]=3;job['rows'][2][4]=3
  job['starbucks_introduction']={'status':'已介绍'};job['starbucks_service']['introduction']['status']='confirmed';audit['starbucks_service']=copy.deepcopy(job['starbucks_service']);audit['candidates'] += [candidate('W','bonus_wet_tissue'),candidate('S','starbucks_introduction')]
  self.assertEqual(self.errors(job,audit),[])
  job['rows'].append(copy.deepcopy(job['rows'][2]))
  self.assertTrue(any('unique' in x for x in self.errors(job,audit)))
 def test_exact_static_na_scope_needs_both_direct_quote_conditions(self):
  rows={k:['C',k,k,2,'NA','01:00','明确指定车型要求直接报价'] for k in p.DIRECT_QUOTE_ROWS}
  audit={'candidates':[candidate()]};a={'policy_rule':'direct_quote_request','evidence_ids':['Q'],'conditions':{'customer_model_explicit':True,'customer_requested_direct_quote':True}}
  errors=[];p.validate_na('C2',a,rows,audit,errors);self.assertEqual(errors,[])
  a['conditions']['customer_requested_direct_quote']=False
  errors=[];p.validate_na('C2',a,rows,audit,errors);self.assertTrue(errors)
  a['conditions']['customer_requested_direct_quote']=True;rows['C6'][4]=2
  errors=[];p.validate_na('C2',a,rows,audit,errors);self.assertTrue(errors)
 def test_whole_static_refusal_does_not_exempt_c6(self):
  rows={k:['C',k,k,2,'NA','01:00','拒绝全部讲解'] for k in p.FULL_STATIC_ROWS}
  a={'policy_rule':'full_static_declined','evidence_ids':['Q'],'conditions':{'refusal_scope':'whole_static','customer_refused_static_explanation':True}}
  errors=[];p.validate_na('C5',a,rows,{'candidates':[candidate()]},errors);self.assertEqual(errors,[])
  errors=[];p.validate_na('C6',a,rows,{'candidates':[candidate()]},errors);self.assertTrue(errors)
 def test_quote_refusal_is_not_inferred_from_missing_quote(self):
  a={'policy_rule':'quotation_refused','evidence_ids':['Q'],'conditions':{'sales_invited_quote':True,'customer_refused_quote':True}}
  errors=[];p.validate_na('E2',a,{}, {'candidates':[candidate()]},errors);self.assertEqual(errors,[])
  a['evidence_ids']=[];errors=[];p.validate_na('E2',a,{}, {'candidates':[candidate()]},errors);self.assertTrue(errors)
 def test_no_e3_consultation_requires_full_scan_and_specific_original_reviews(self):
  import feedback_policy as f
  a={'policy_rule':'no_in_scope_consultation'}
  scan={'full_transcript_read':True,'transcript_sha256':'H','targeted_reviews_complete':True,'rationale':'全量审读'}
  record={'status':'no_in_scope_consultation','full_transcript_scanned':True,'transcript_sha256':'H','scope':'price/gift/finance','rationale':'无可考核咨询','review_sources':[{'window':'01:00-02:00','channel':'mix','model':'large-v3-turbo','source_ref':'original-review.json','conclusion':'报价与权益上下文复核'}]}
  audit={'workflow_policy_version':f.VERSION,'semantic_scan':scan,'e3_consultation':record}
  errors=[];p.validate_na('E3',a,{},audit,errors);self.assertEqual(errors,[])
  record['review_sources']=[];errors=[];p.validate_na('E3',a,{},audit,errors);self.assertTrue(errors)
 def test_default_segments_do_not_change_numeric_score_or_hide_real_deduction(self):
  job={'service_policy_version':p.VERSION,'rows':[['B','B5a','眼里有客',4,0,'全程','默认'],['B','B3','礼仪',3,0,'01:00','默认一词不能隐藏实际缺项']],'row_assessments':{'B5a':{'kind':'audio_default','default_deduction_points':4,'policy_rule':'audio_B5a'},'B3':{'kind':'evidence'}}}
  self.assertEqual(p.module_segments(job,'B',25,18),{'awarded':18,'default_deduction':4,'other_deduction':3})
  before=copy.deepcopy(job);details=p.deduction_details(job)
  self.assertEqual(len(details),1);self.assertIn('B3',details[0][0]);self.assertEqual(job,before)
 def test_unapproved_default_cannot_hide_missing_evidence(self):
  job,audit=base();job['row_assessments']['E2']={'kind':'audio_default','rationale':'未确认','default_deduction_points':3,'policy_rule':'not_real'};audit['row_assessments']=copy.deepcopy(job['row_assessments'])
  self.assertTrue(any('not an authorized' in x for x in self.errors(job,audit)))
 def test_later_followup_absence_needs_external_evidence(self):
  a={'policy_rule':'customer_refused_contact_and_no_followup','evidence_ids':['Q'],'conditions':{'customer_refused_contact':True,'no_contact_via_business_card':True}}
  errors=[];p.validate_na('F3',a,{}, {'candidates':[candidate()]},errors);self.assertTrue(errors)
 def test_c5_excellence_needs_full_base_and_separate_customer_engagement(self):
  job,audit=base();job['rows'] += [['C','C5','卖点',4,4,'01:00','完整体验'],['C','C5bonus','超额表现',2,2,'01:00','另有生动讲解和客户喜爱证据']]
  job['row_assessments']['C5']={'kind':'evidence','rationale':'两项完整卖点体验'}
  audit['row_assessments']=copy.deepcopy(job['row_assessments'])
  item={'status':'confirmed','rationale':'生动讲解及客户喜爱原音','evidence_ids':['Q'],'customer_response_evidence_ids':['Q'],'conditions':{'base_full_score_confirmed':True,'presentation_vivid':True,'customer_engagement_confirmed':True}}
  job['service_bonuses']={'C5bonus':item};audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertEqual(self.errors(job,audit),[])
  job['rows'][-2][4]=2
  self.assertTrue(any('full base score' in x for x in self.errors(job,audit)))
  job['rows'][-2][4]=4;item['customer_response_evidence_ids']=[];audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertTrue(any('engagement' in x for x in self.errors(job,audit)))
 def test_default_trial_score_never_satisfies_d8_excellence(self):
  job,audit=base();job['rows'] += [['D','D2-D9','试驾',20,15,'01:00','默认'],['D','D8bonus','超额表现',2,2,'01:00','声称达标']]
  job['row_assessments']['D2-D9']={'kind':'audio_default','rationale':'原固定口径','policy_rule':'audio_trial_15','default_deduction_points':5};audit['row_assessments']=copy.deepcopy(job['row_assessments'])
  item={'status':'confirmed','rationale':'不能用合计分推出D8','evidence_ids':['Q'],'customer_response_evidence_ids':['Q'],'conditions':{'base_full_score_confirmed':True,'presentation_vivid':True,'customer_engagement_confirmed':True,'during_actual_trial':True}}
  job['service_bonuses']={'D8bonus':item};audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertTrue(any('D8bonus requires full base score' in x for x in self.errors(job,audit)))
 def test_phone_only_na_needs_full_scan_and_no_wechat_confirmation(self):
  import feedback_policy as f
  a={'policy_rule':'phone_only','evidence_ids':['Q'],'conditions':{'only_phone_retained':True,'no_wechat':True}}
  audit={'candidates':[candidate()],'workflow_policy_version':f.VERSION,'semantic_scan':{'full_transcript_read':True,'transcript_sha256':'H','targeted_reviews_complete':True,'rationale':'已全量审读留资方式'}}
  errors=[];p.validate_na('F2',a,{},audit,errors);self.assertEqual(errors,[])
  audit['semantic_scan']['full_transcript_read']=False
  errors=[];p.validate_na('F2',a,{},audit,errors);self.assertTrue(errors)
 def test_d8_aggregate_can_qualify_only_with_independent_three_feature_assessment(self):
  job,audit=base();job['rows'] += [['D','D2-D9','试驾',20,15,'01:00','默认'],['D','D8bonus','超额表现',2,2,'01:00','独立动态亮点评价']]
  job['row_assessments']['D2-D9']={'kind':'audio_default','rationale':'固定口径','policy_rule':'audio_trial_15','default_deduction_points':5};audit['row_assessments']=copy.deepcopy(job['row_assessments'])
  audit['candidates'] += [candidate('Q'+str(i),'test_drive_actual') for i in range(3)]
  item={'status':'confirmed','rationale':'生动动态展示并打动客户','evidence_ids':['Q'],'customer_response_evidence_ids':['Q'],'conditions':{'base_full_score_confirmed':True,'presentation_vivid':True,'customer_engagement_confirmed':True,'during_actual_trial':True},'base_assessment':{'score':9,'max_score':9,'features':[{'name':'亮点'+str(i),'score':3,'evidence_ids':['Q'+str(i)],'demonstration':'已确认实际动态演示','scenario_pain_point':'已确认具体场景痛点'} for i in range(3)]}}
  job['service_bonuses']={'D8bonus':item};audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertEqual(self.errors(job,audit),[]);self.assertEqual(job['rows'][-2][4],15)
  for feature in item['base_assessment']['features']:feature['evidence_ids']=['Q0']
  audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertEqual(self.errors(job,audit),[])  # One merged audio window may prove three distinct features.
  item['base_assessment']['features'][2]['name']=item['base_assessment']['features'][0]['name'];audit['service_bonuses']=copy.deepcopy(job['service_bonuses'])
  self.assertTrue(any('full base score' in x for x in self.errors(job,audit)))
 def test_context_candidates_and_legacy_unadjudicated_fact_cannot_authorize_na(self):
  for patch in ({'category':'reviewed_context'},{'review_status':'semantic_context'},{'fact_status':None},{'qualifies_for_scoring':False}):
   c=candidate();c.update(patch);self.assertFalse(p.sources_valid(['Q'],{'candidates':[c]}))
 def test_starbusks_three_statuses_must_agree_with_introduction_award(self):
  job,audit=base();job['rows'][2][4]=3;job['starbucks_introduction']={'status':'已介绍'};audit['candidates'].append(candidate('S','starbucks_introduction'))
  self.assertTrue(any('introduction status' in x for x in self.errors(job,audit)))
 def test_a1_refused_greeting_is_not_na_and_b6_specific_unassessable_scene_can_be_na(self):
  a={'policy_rule':'customer_refused_item','evidence_ids':['Q'],'conditions':{'customer_explicitly_refused':True,'refused_item':'A1'}}
  errors=[];p.validate_na('A1',a,{}, {'candidates':[candidate()]},errors);self.assertTrue(errors)
  a['conditions']['refused_item']='A2';errors=[];p.validate_na('A2',a,{}, {'candidates':[candidate()]},errors);self.assertTrue(errors)
  a={'policy_rule':'unassessable_hospitality','evidence_ids':['Q'],'policy_source_ref':'6.0-G F18','conditions':{'specific_scene_reason_confirmed':True,'reason':'已记录无法评价的具体接待场景'}}
  errors=[];p.validate_na('B6',a,{}, {'candidates':[candidate()]},errors);self.assertEqual(errors,[])
  a['conditions']['reason']='';errors=[];p.validate_na('B6',a,{}, {'candidates':[candidate()]},errors);self.assertTrue(errors)
 def test_canonical_row_weight_cannot_be_moved_to_na_item(self):
  job,audit=base();job['rows'][0][3]=5
  self.assertTrue(any('Canonical' in x for x in self.errors(job,audit)))
 def test_negative_scores_require_specific_misconduct_not_missing_elements(self):
  codes={'B5a':'refused_reasonable_assistance','B6':'food_drink_quality_problem','C8':'sales_negative_brand_remark','E2':'improper_quotation'}
  for key,score in p.NEGATIVE_SCORES.items():
   job,audit=base()
   if key=='E2':job['rows'][0][4]=score
   else:job['rows'].append([key[0],key,key,p.ROW_MAX[key],score,'01:00','原表具体失当行为'])
   code=codes[key];conditions={k:True for k in p.NEGATIVE_CONDITIONS[key][code]}
   if key=='E2':conditions['misconduct_type']='arbitrary_markup'
   a={'kind':'evidence','rationale':'原音具体失当行为','negative_ruling':{'clause':'原标准明确条款','behavior':'已确认的具体失当行为','behavior_code':code,'conditions':conditions,'evidence_ids':['Q']}}
   job['row_assessments'][key]=a;audit['row_assessments']=copy.deepcopy(job['row_assessments'])
   self.assertEqual(self.errors(job,audit),[],key)
   row_errors=[];v.validate_rows(job,row_errors);self.assertEqual(row_errors,[],key)
   a['negative_ruling']['conditions']={};audit['row_assessments']=copy.deepcopy(job['row_assessments'])
   self.assertTrue(any('negative score' in x for x in self.errors(job,audit)),key)
 def test_legacy_policy_is_unchanged(self):
  self.assertEqual(self.errors({'rows':[]},{'candidates':[]}),[])
  self.assertEqual(v.final_score(53,20,0),66)
  self.assertEqual(v.negative_incentive(66),'2万元折让/家')
if __name__=='__main__':unittest.main()
