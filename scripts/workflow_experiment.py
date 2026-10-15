"""Ten-calendar-day experiment ledger; never changes published scores."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import date
from workflow_support import RUNTIME,read,save,now,digest
STATE=RUNTIME/'experiment';FEATURES=tuple('B'+str(i) for i in range(1,9))
def setup():
 STATE.mkdir(parents=True,exist_ok=True);p=STATE/'config.json'
 if not p.exists():save(p,{'id':'workflow-2026-10-05','start_date':'2026-10-05','last_test_date':'2026-10-14','review_due':'2026-10-15T09:00:00+08:00','minimum_reviewed_cases':10,'features':list(FEATURES),'adoption':'evaluation_and_recommendations; scoring-evidence changes require user confirmation','official_chain':'small+Turbo evidence review','shadow_primary':'large-v3-turbo','daily_shadow_limit':1})
 return read(p)
def active(day):
 c=setup();return c['start_date']<=day<=c['last_test_date']
def cases():return [read(p) for p in sorted((STATE/'cases').glob('*.json'))] if (STATE/'cases').exists() else []
def shadow_allowed(day,source_hash):
 if not active(day):return False
 if any(c['date']!=day and c['audio_sha256']==source_hash and c.get('b1_shadow_started') for c in cases()):return False
 existing=[c for c in cases() if c['date']==day and c.get('b1_shadow_started')]
 return not existing or any(c['audio_sha256']==source_hash for c in existing)
def record_case(manifest,job_dir,**updates):
 setup();h=manifest['sha256'];p=STATE/'cases'/(manifest['task_date']+'_'+h[:16]+'.json')
 v=read(p) if p.exists() else {'date':manifest['task_date'],'audio_sha256':h,'job_dir':str(Path(job_dir).resolve()),'features':{},'feedback':[],'baseline_seconds':None,'shadow_seconds':None}
 if v['audio_sha256']!=h:raise ValueError('Case identity collision')
 policy=Path(job_dir)/'workflow-policy.json'
 v.setdefault('workflow_policy_version',read(policy)['version'] if policy.exists() else 'legacy-before-2026-10-09')
 v.update(updates);v['updated_at']=now();save(p,v);return v

def observation(manifest,job_dir,feature,value):
 if feature not in FEATURES:raise ValueError('Unknown feature')
 v=record_case(manifest,job_dir);v['features'][feature]=value;return record_case(manifest,job_dir,features=v['features'])

def feedback(manifest,job_dir,description,status='needs_manual_review',review=None):
 if status not in {'needs_manual_review','confirmed','rejected'}:raise ValueError('Invalid feedback status')
 if status!='needs_manual_review' and (not review or not all(review.get(k) for k in ('window','channel','model','conclusion','audit_ref'))):raise ValueError('Resolved user feedback requires independent original-audio review details')
 v=record_case(manifest,job_dir);v['feedback'].append({'reported_at':now(),'user_claim':description,'status':status,'original_audio_review':review});return record_case(manifest,job_dir,feedback=v['feedback'])

def independently_verified(case,value):
 if value.get('quality_verified') is not True or not value.get('audit_ref'):return False
 if value.get('verification_basis') in {'semantic_inference','user_authorized_semantic_inference'}:return False
 official=case.get('official_result',{})
 inferred=case.get('semantic_trial_inference') or official.get('semantic_trial_inference') or official.get('trial_completion_basis') in {'semantic_inference','user_authorized_semantic_inference'}
 return not inferred or value.get('independent_original_audio_comparison') is True

def summarize(day=None):
 c=setup();day=day or now()[:10];allcases=[x for x in cases() if c['start_date']<=x['date']<=c['last_test_date']]
 # Collect only known case directories after delivery, never search for new recordings.
 for case in allcases:
  pending=Path(case['job_dir'])/'experiment-pending.json' if case.get('job_dir') else None
  if pending and pending.exists():
   queued=read(pending);manifest=queued.get('source_manifest',{})
   if manifest.get('sha256')!=case['audio_sha256'] or manifest.get('task_date')!=case['date']:raise ValueError('Deferred statistics source identity mismatch')
   official=queued['official_result'];case.update(official_result=official,semantic_trial_inference=official.get('semantic_trial_inference',False))
 distinct={}
 for case in allcases:distinct[case['audio_sha256']]=case
 allcases=list(distinct.values())
 evaluated=[]
 for f in FEATURES:
  observed=[x['features'][f] for x in allcases if f in x.get('features',{})]
  verified=[case['features'][f] for case in allcases if f in case.get('features',{}) and independently_verified(case,case['features'][f])]
  regressions=[x for x in verified if x.get('result')=='regression' or any(isinstance(x.get(k),(int,float)) and x[k]>0 for k in ('confirmed_misses','confirmed_wrong_deductions'))]
  related=[fb for case in allcases for fb in case.get('feedback',[]) if f in (fb.get('original_audio_review') or {}).get('affected_features',FEATURES)]
  feedback_regressions=[fb for fb in related if fb['status']=='confirmed' and (fb.get('original_audio_review') or {}).get('impact') in ('regression','confirmed_miss','confirmed_wrong_deduction')]
  pending_feature=sum(fb['status']=='needs_manual_review' for fb in related)
  problem_count=len(regressions)+len(feedback_regressions)
  complete=len(verified)>=c['minimum_reviewed_cases'] and not pending_feature
  status='有问题' if problem_count else '通过' if complete else '样本不足'
  policy_groups={}
  for case in allcases:
   if f not in case.get('features',{}):continue
   version=case.get('workflow_policy_version','legacy-before-2026-10-09')
   group=policy_groups.setdefault(version,{'observations':0,'verified_cases':0,'seconds_saved':[]})
   group['observations']+=1
   item=case['features'][f]
   if independently_verified(case,item):
    group['verified_cases']+=1
    if isinstance(item.get('seconds_saved'),(int,float)):group['seconds_saved'].append(item['seconds_saved'])
  mixed=len(policy_groups)>1
  savings=[x['seconds_saved'] for x in verified if isinstance(x.get('seconds_saved'),(int,float))] if not mixed else []
  if mixed and status=='通过':status='样本不足'
  for group in policy_groups.values():
   values=group.pop('seconds_saved');group['mean_seconds_saved']=sum(values)/len(values) if values else None
  recommendation={'有问题':'保留现行正式要求，处理已确认问题','通过':'满足质量门槛；提交采用建议','样本不足':'补齐配对录音/独立证据对照，不能按无反馈推定通过'}[status]
  evaluated.append({'feature':f,'status':status,'workflow_policy_groups':policy_groups,'mixed_policy_comparison':mixed,'observations':len(observed),'verified_cases':len(verified),'regressions':problem_count,'pending_feedback':pending_feature,'mean_seconds_saved':round(sum(savings)/len(savings),2) if savings else None,'recommendation':recommendation})
 pending=[{'hash':x['audio_sha256'],'claim':f['user_claim']} for x in allcases for f in x.get('feedback',[]) if f['status']=='needs_manual_review']
 result={'experiment':c,'evaluated_at':now(),'as_of_date':day,'period_complete':day>c['last_test_date'],'case_count':len(allcases),'features':evaluated,'pending_feedback':pending,'automatic_adoption':False,'missing_data_policy':'未提供的录音、耗时及反馈不填0，不算通过','input_fingerprint':digest({'config':c,'cases':allcases})}
 prefix='evaluation' if result['period_complete'] else 'progress'
 if result['period_complete']:prefix+='-'+result['input_fingerprint'][:12]
 save(STATE/(prefix+'.json'),result)
 rows=['# 日常评分流程10天测试结果','',f"测试期：{c['start_date']} 至 {c['last_test_date']}；汇总时间：{result['evaluated_at']}",f"已记录录音：{len(allcases)}；待原音核验反馈：{len(pending)}",'','|项目|结论|独立验证样本|问题数|平均节省秒数|采用建议|','|---|---|---:|---:|---:|---|']
 for x in evaluated:rows.append(f"|{x['feature']}|{x['status']}|{x['verified_cases']}|{x['regressions']}|{x['mean_seconds_saved'] if x['mean_seconds_saved'] is not None else '缺失'}|{x['recommendation']}|")
 rows+=['','样本不足不视为通过。实际评分与原音证据要求继续执行；汇总产出采用建议。'];(STATE/(prefix+'.md')).write_text('\n'.join(rows)+'\n',encoding='utf-8');return result

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('setup');s=sub.add_parser('summarize');s.add_argument('--date')
 f=sub.add_parser('feedback');f.add_argument('--job-dir',type=Path,required=True);f.add_argument('--description',required=True);f.add_argument('--status',default='needs_manual_review');f.add_argument('--review-json',type=Path)
 o=sub.add_parser('observe');o.add_argument('--job-dir',type=Path,required=True);o.add_argument('--feature',choices=FEATURES,required=True);o.add_argument('--observation-json',type=Path,required=True)
 a=p.parse_args()
 if a.command=='setup':r=setup()
 elif a.command=='summarize':
  full=summarize(a.date);r={k:full[k] for k in ('as_of_date','period_complete','case_count','features','automatic_adoption')}
 elif a.command=='feedback':r=feedback(read(a.job_dir/'source-manifest.json'),a.job_dir,a.description,a.status,read(a.review_json) if a.review_json else None)
 else:r=observation(read(a.job_dir/'source-manifest.json'),a.job_dir,a.feature,read(a.observation_json))
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
