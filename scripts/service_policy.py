"""Explicit service-scoring supplement; old jobs retain the original contract."""
from __future__ import annotations
import copy,re
VERSION='service-policy-2026-10-10-v1'
E2_COMPONENTS={'vehicle_or_price':'车型/价格','payment_or_finance':'付款或金融方案','fees':'费用构成','gifts':'赠品','delivery':'明确预计交车周期','interior_color':'销售讲解内饰颜色'}
BONUS_ROWS={'A3','B8','B8coffee','C5bonus','D8bonus'}
BONUS_TOTALS={a+b+c+d for a in (0,3) for b in (0,3,6) for c in (0,2) for d in (0,2)}
NA_ALLOWED={'B6',*('C'+str(i) for i in range(2,9)),'D1','D2-D9','E2','E3','F2','F3'}
DIRECT_QUOTE_ROWS={'C2','C3','C4','C5','C6'}
FULL_STATIC_ROWS={'C2','C3','C4','C5','C7','C8'}
DEFAULT_DEDUCTIONS={'B5a':(0,4,'audio_B5a'),'G3':(0,2,'audio_G3'),'D2-D9':(15,5,'audio_trial_15')}
POLICY_NOTE='服务补充口径：湿纸巾提供、星巴克简单介绍各加3分，B8合计至多6分；C5、D8满分且讲解生动并打动客户时各可另加2分；NA逐项取证；黄色为默认扣分，仅作展示，不增加得分。'
TIME=re.compile(r'(?<!\d)\d{1,2}:\d{2}(?!\d)')
ROW_MAX={'A1':5,'A2':5,'A3':3,'B1':3,'B2':3,'B3':3,'B4':5,'B5a':4,'B5b':2,'B6':3,'B7':2,'B8':3,'B8coffee':3,'C2':2,'C3':3,'C4':3,'C5':4,'C6':2,'C7':3,'C8':3,'C5bonus':2,'D1':5,'D2-D9':20,'D2':0,'D3':0,'D4':2,'D5':2,'D6':2,'D7':3,'D8':9,'D9':2,'D8bonus':2,'E2':3,'E3':2,'F1':1,'F2':2,'F3':2,'G1':4,'G2':4,'G3':2}
BASE_ROW_KEYS={k for k in ROW_MAX if k not in BONUS_ROWS and not (k.startswith('D') and k not in {'D1','D2-D9'})}

def active(job):return job.get('service_policy_version')==VERSION

def confirmed_source(c):
 return (c.get('status')=='confirmed' and c.get('fact_status')=='confirmed' and c.get('category') not in {'reviewed_context','scope_excluded','semantic_context','inferred'} and c.get('review_status') not in {'scope_excluded','semantic_context'} and c.get('qualifies_for_scoring') is not False and bool(c.get('review_transcript') or c.get('review_sources')) and bool(TIME.search(str(c.get('timestamp','')))) and bool(c.get('review_channel')) and bool(c.get('review_model')))
def sources_valid(ids,audit):
 cs={c.get('id'):c for c in audit.get('candidates',[])}
 return isinstance(ids,list) and bool(ids) and len(ids)==len(set(ids)) and all(cid in cs and confirmed_source(cs[cid]) for cid in ids)
def original_reviews_valid(reviews):
 return isinstance(reviews,list) and bool(reviews) and all(isinstance(r,dict) and all(r.get(k) for k in ('window','channel','model','conclusion','source_ref')) and TIME.search(str(r['window'])) for r in reviews)
def missing_e2(audit):
 q=audit.get('derived',{}).get('quote_completeness',{});cs=q.get('components',{});refs=q.get('component_sources',{})
 return [k for k in E2_COMPONENTS if cs.get(k) is not True or not sources_valid(refs.get(k,[]),audit)]
def prepare_report(job,audit):
 v=copy.deepcopy(job)
 if not active(v):return v
 q=audit.get('derived',{}).get('quote_completeness',{});components={k:k not in missing_e2(audit) for k in E2_COMPONENTS}
 if 'quote_components' in v and v['quote_components']!=components:raise ValueError('job.quote_components conflicts with confirmed audit quote components')
 if 'component_sources' in v and v['component_sources']!=q.get('component_sources',{}):raise ValueError('job.component_sources conflicts with confirmed audit sources')
 v['quote_components']=components;v['component_sources']=copy.deepcopy(q.get('component_sources',{}))
 missing=missing_e2(audit);v['e2_missing_components']=missing
 for r in v.get('rows',[]):
  if r[1]=='E2' and r[4]==0:r[6]='报价六要素中未确认：'+'、'.join(E2_COMPONENTS[k] for k in missing)+'；E2记0分。'
  elif r[1]=='B8coffee':r[2]='星巴克简单介绍加分'
  if r[1] in NEGATIVE_SCORES and r[4]==NEGATIVE_SCORES[r[1]]:
   ruling=v.get('row_assessments',{}).get(r[1],{}).get('negative_ruling',{})
   r[6]='原表负分档：'+str(ruling.get('behavior','具体失当行为待核实'))+'；依据'+str(ruling.get('clause','待核实'))+'，'+r[1]+'记'+str(r[4])+'分。'
 if POLICY_NOTE not in v.setdefault('defaults',[]):v['defaults'].append(POLICY_NOTE)
 v['deductions']=deduction_details(v)
 return v

def default_deduction(job,row):
 if not active(job) or row[4]=='NA':return 0
 a=job.get('row_assessments',{}).get(row[1],{})
 return int(a.get('default_deduction_points',0)) if a.get('kind')=='audio_default' else 0
def module_segments(job,letter,maximum,got):
 default=sum(default_deduction(job,r) for r in job.get('rows',[]) if r[0]==letter and r[1] not in BONUS_ROWS)
 return {'awarded':max(0,float(got)),'default_deduction':default,'other_deduction':max(0,float(maximum)-max(0,float(got))-default)}
def deduction_details(job):
 if not active(job):
  from feedback_policy import deduction_details as legacy
  return legacy(job)
 result=[]
 for r in job.get('rows',[]):
  if len(r)<7 or r[1] in BONUS_ROWS or r[4]=='NA' or int(r[4])>=int(r[3]):continue
  if default_deduction(job,r)==int(r[3])-int(r[4]):continue
  result.append([str(r[1])+' '+str(r[2]),str(r[5])+'｜'+str(r[6])])
 return result

def validate_na(key,item,rows,audit,errors):
 rule=item.get('policy_rule');ids=item.get('evidence_ids',[]);ok=sources_valid(ids,audit);c=item.get('conditions',{})
 if key not in NA_ALLOWED and key not in {'D'+str(i) for i in range(2,10)}:errors.append('NA is not allowed for '+key)
 if rule=='customer_refused_item':
  if key not in {'C'+str(i) for i in range(2,9)} or c.get('customer_explicitly_refused') is not True or c.get('refused_item')!=key or not ok:errors.append(key+' NA requires original-audio refusal of that specific item')
 elif rule in {'direct_quote_request','full_static_declined'}:
  scope=DIRECT_QUOTE_ROWS if rule=='direct_quote_request' else FULL_STATIC_ROWS
  conditions=(c.get('customer_model_explicit') is True and c.get('customer_requested_direct_quote') is True) if rule=='direct_quote_request' else (c.get('refusal_scope')=='whole_static' and c.get('customer_refused_static_explanation') is True)
  if key not in scope or not ok or not conditions:errors.append(key+' NA lacks the complete original-audio '+rule+' conditions')
  if any(rows.get(k,[None]*5)[4]!='NA' for k in scope):errors.append(rule+' requires its complete defined static NA scope')
 elif rule=='quotation_refused':
  if key!='E2' or not ok or c.get('sales_invited_quote') is not True or c.get('customer_refused_quote') is not True:errors.append('E2 NA requires sales quote invitation and explicit customer refusal')
 elif rule=='no_in_scope_consultation':
  from feedback_policy import scan_completed
  record=audit.get('e3_consultation',{})
  if key!='E3' or not scan_completed(audit) or record.get('status')!='no_in_scope_consultation' or record.get('full_transcript_scanned') is not True or record.get('transcript_sha256')!=audit.get('semantic_scan',{}).get('transcript_sha256') or not record.get('scope') or not record.get('rationale') or not original_reviews_valid(record.get('review_sources')):errors.append('E3 NA needs full semantic scan and original-audio reviews for absence of in-scope consultation')
 elif rule=='unassessable_hospitality':
  if key!='B6' or not ok or c.get('specific_scene_reason_confirmed') is not True or not c.get('reason') or not item.get('policy_source_ref'):errors.append('B6 NA requires a documented specific unassessable scene and original-audio evidence, not mere absence of audible service')
 elif rule=='phone_only':
  from feedback_policy import scan_completed
  if key!='F2' or not scan_completed(audit) or not ok or c.get('only_phone_retained') is not True or c.get('no_wechat') is not True:errors.append('F2 NA requires full semantic scan and confirmed phone-only contact without WeChat')
 elif rule=='customer_refused_contact_and_no_followup':
  external=item.get('external_evidence',{})
  if key!='F3' or c.get('assessment_mode')!='standard_on_site' or not ok or c.get('customer_refused_contact') is not True or c.get('no_contact_via_business_card') is not True or external.get('verified') is not True or not all(external.get(k) for k in ('source_ref','reviewed_at','conclusion')):errors.append('F3 NA requires contact refusal plus independently verified absence of later contact via business card')
 elif rule=='customer_initiated_trial':
  if key!='D1' or not ok or c.get('customer_initiated_trial') is not True:errors.append('D1 NA requires confirmed customer-initiated trial')
 elif rule=='d1_na_cascade':
  if key!='D2-D9' or rows.get('D1',[None]*5)[4]!='NA' or not ok:errors.append('D2-D9 NA cascade requires D1 NA and its original-audio basis')
 elif rule in {'two_trial_invites','scheduled_trial'}:
  if key!='D2-D9' or not ok:errors.append(key+' NA requires confirmed original-audio trial evidence')
 elif rule=='matched_trial_item':
  if not key.startswith('D') or not audit.get('trial_score_reuse') or not item.get('source_row_ref'):errors.append(key+' NA requires independently validated matched trial source row')
 else:errors.append('Unsupported NA reason for '+key+': '+str(rule))

NEGATIVE_SCORES={'B5a':-5,'B6':-2,'C8':-5,'E2':-3}
NEGATIVE_CONDITIONS={
 'B5a':{'refused_reasonable_assistance':('reasonable_request_confirmed','sales_refusal_or_evasion_confirmed')},
 'B6':{'food_drink_quality_problem':('obvious_quality_defect_confirmed',)},
 'C8':{'non_byd_material_logo':('physical_material_confirmed','external_brand_logo_confirmed'), 'sales_negative_brand_remark':('sales_speaker_confirmed','customer_exposed','potential_negative_perception_confirmed')},
 'E2':{'improper_quotation':('quotation_misconduct_confirmed','adverse_customer_impression_confirmed')},
}
def validate_negative(key,row,assessment,audit,errors):
 if key not in NEGATIVE_SCORES or row[4]!=NEGATIVE_SCORES[key]:return
 ruling=assessment.get('negative_ruling',{});code=ruling.get('behavior_code');conditions=ruling.get('conditions',{})
 required=NEGATIVE_CONDITIONS[key].get(code)
 if assessment.get('kind')!='evidence' or not all(ruling.get(k) for k in ('clause','behavior')) or not sources_valid(ruling.get('evidence_ids',[]),audit) or required is None or not all(conditions.get(k) is True for k in required):errors.append(key+' negative score requires its specific standard misconduct and independent original-audio ruling')
 if key=='E2' and conditions.get('misconduct_type') not in {'ambiguous_pricing','arbitrary_markup','overpromise','tied_sale','aggressive_selling'}:errors.append('E2 negative score requires a specific improper quotation behavior, not ordinary missing quote elements')

def module_score_allowed(job,letter,maximum,score):
 lower={'A':0,'B':-9,'C':-5,'E':-3,'F':0}
 return active(job) and letter in lower and lower[letter]<=score<=maximum

def independent_d8_full_score(item,rows,audit):
 # This assessment only establishes eligibility for the extra 2; it never alters D base points.
 if 'D8' in rows:return rows['D8'][4]==9
 if rows.get('D2-D9',[None]*5)[4] not in {15,20}:return False
 base=item.get('base_assessment',{});features=base.get('features',[])
 if base.get('score')!=9 or base.get('max_score')!=9 or not isinstance(features,list) or len(features)<3:return False
 names=set()
 for feature in features:
  if not isinstance(feature,dict) or not feature.get('name') or feature.get('name') in names or feature.get('score')!=3 or not feature.get('demonstration') or not feature.get('scenario_pain_point') or not sources_valid(feature.get('evidence_ids',[]),audit):return False
  names.add(feature['name'])
 return True

def validate(job,audit,errors):
 version=job.get('service_policy_version')
 if version is None:
  if audit.get('service_policy_version') is not None:errors.append('job/audit service_policy_version must match')
  return
 if version!=VERSION or audit.get('service_policy_version')!=VERSION:
  errors.append('Unsupported or mismatched service_policy_version');return
 rl=job.get('rows',[]);rows={r[1]:r for r in rl if len(r)>=7}
 if len(rows)!=len(rl):errors.append('Every scoring row must be well-formed and have a unique item ID')
 for key,row in rows.items():
  if key not in ROW_MAX or row[0]!=key[0] or type(row[3]) is not int or row[3]!=ROW_MAX.get(key):errors.append('Canonical item/module/maximum mismatch: '+key)
 if job.get('modules'):
  required=BASE_ROW_KEYS if 'D2-D9' in rows else (BASE_ROW_KEYS-{'D2-D9'})|{'D'+str(i) for i in range(2,10)}
  if set(rows)-BONUS_ROWS!=required:errors.append('Current service policy requires every canonical base item exactly once')

 assessments=job.get('row_assessments',{})
 if not isinstance(assessments,dict) or audit.get('row_assessments')!=assessments:
  errors.append('job/audit row_assessments must match');return
 for key,row in rows.items():
  if key in BONUS_ROWS:continue
  a=assessments.get(key,{})
  if a.get('kind') not in {'evidence','audio_default','na'} or not a.get('rationale'):
   errors.append('Scoring row requires explicit assessment kind and rationale: '+key);continue
  if row[4]=='NA':
   if a.get('kind')!='na':errors.append(key+' NA row must use kind=na')
   validate_na(key,a,rows,audit,errors)
  elif a.get('kind')=='na':errors.append(key+' kind=na conflicts with numeric score')
  if a.get('kind')=='audio_default':
   if row[4]=='NA':errors.append(key+' NA cannot be an audio default');continue
   points=a.get('default_deduction_points');lost=int(row[3])-int(row[4])
   if type(points) is not int or points!=max(0,lost):errors.append(key+' default deduction must match actual lost points')
   if lost>0 and (key not in DEFAULT_DEDUCTIONS or (row[4],points,a.get('policy_rule'))!=DEFAULT_DEDUCTIONS[key]):errors.append(key+' is not an authorized audio-default deduction')
  elif a.get('default_deduction_points',0)!=0:errors.append(key+' evidence/NA rows cannot hide deductions as defaults')
  validate_negative(key,row,a,audit,errors)
 missing=missing_e2(audit)
 expected_components={k:k not in missing for k in E2_COMPONENTS}
 if job.get('quote_components')!=expected_components:errors.append('job.quote_components differs from confirmed audit quote components')
 if job.get('component_sources')!=audit.get('derived',{}).get('quote_completeness',{}).get('component_sources',{}):errors.append('job.component_sources differs from confirmed audit quote sources')
 q=audit.get('derived',{}).get('quote_completeness',{})
 if q.get('components',{})!=expected_components:errors.append('audit quote components differ from qualifying sources')
 if job.get('e2_missing_components')!=missing:errors.append('E2 missing-components list differs from independently reviewed component sources')
 e2=rows.get('E2')
 if e2 and e2[4]==0:
  if not missing:errors.append('E2=0 conflicts with all six confirmed quote components')
  if any(E2_COMPONENTS[k] not in str(e2[6]) for k in missing):errors.append('E2 deduction must name every unconfirmed quote component')
 if e2 and e2[4]==3 and missing:errors.append('E2=3 requires six original-audio confirmed component sources')
 for bonus_key,base_key,full_score in (('C5bonus','C5',4),('D8bonus','D8',9)):
  row=rows.get(bonus_key)
  if row is None:continue
  if row[4] not in {0,2}:errors.append(bonus_key+' must be 0 or 2, never NA');continue
  if row[4]==2:
   item=job.get('service_bonuses',{}).get(bonus_key,{})
   if item!=audit.get('service_bonuses',{}).get(bonus_key):errors.append(bonus_key+' job/audit excellence review must match')
   conditions=item.get('conditions',{})
   base_full = independent_d8_full_score(item,rows,audit) if bonus_key=='D8bonus' else rows.get(base_key,[None]*5)[4]==full_score
   if not base_full or item.get('status')!='confirmed' or not item.get('rationale') or not sources_valid(item.get('evidence_ids',[]),audit) or not sources_valid(item.get('customer_response_evidence_ids',[]),audit) or not all(conditions.get(k) is True for k in ('base_full_score_confirmed','presentation_vivid','customer_engagement_confirmed')):
    errors.append(bonus_key+' requires full base score, vivid explanation and independent original-audio customer engagement evidence')
   if bonus_key=='D8bonus' and conditions.get('during_actual_trial') is not True:errors.append('D8bonus requires the vivid demonstration and engagement during the actual trial')
 if job.get('modules'):
  try:
   from workflow_support import derive_score
   expected=derive_score(job)
   for field in ('modules','base','na','bonus','final_score','negative_incentive'):
    if job.get(field)!=expected.get(field):errors.append('Structured scoring rows conflict with derived '+field)
  except (ValueError,TypeError,KeyError) as exc:errors.append('Cannot derive structured scoring rows: '+str(exc))
 total=0
 for key,category in (('B8','bonus_wet_tissue'),('B8coffee','starbucks_introduction')):
  row=rows.get(key)
  if row is None:errors.append('B8 requires an explicit independent row: '+key);continue
  if row[4] not in {0,3}:errors.append(key+' bonus must be 0 or 3 and cannot be NA');continue
  total+=row[4]
  if row[4]==3:
   cs=[c for c in audit.get('candidates',[]) if c.get('category')==category and confirmed_source(c)]
   if key=='B8coffee':
    cs=[c for c in cs if c.get('introduced_to_customer') is True]
    if job.get('starbucks_introduction',{}).get('status')!='已介绍':errors.append('Starbucks bonus requires confirmed customer-directed introduction')
   if not cs:errors.append(key+' bonus lacks independent original-audio evidence')
 if total>6:errors.append('B8 combined bonus exceeds 6')
 service=job.get('starbucks_service',{})
 if not all(k in service for k in ('introduction','provided','consumed')) or service!=audit.get('starbucks_service'):errors.append('Starbucks introduction/provided/consumed must be separately recorded in matching job/audit fields')
 else:
  expected_intro={'已介绍':'confirmed','未介绍':'not_confirmed','待核实':'pending'}.get(job.get('starbucks_introduction',{}).get('status'))
  if expected_intro and service['introduction'].get('status')!=expected_intro:errors.append('Separate Starbucks introduction status conflicts with the customer-facing introduction ruling')
  if rows.get('B8coffee',[None]*5)[4]==3 and service['introduction'].get('status')!='confirmed':errors.append('B8coffee=3 requires separately confirmed introduction status')
  for field,item in service.items():
   if field not in {'introduction','provided','consumed'} or not isinstance(item,dict) or item.get('status') not in {'confirmed','not_confirmed','pending'} or not item.get('evidence'):errors.append('Invalid separate Starbucks service status: '+field)
 if POLICY_NOTE not in job.get('defaults',[]):errors.append('Report must declare the active service supplement')
