"""Stable helpers for the local BYD scoring workflow; no customer conclusions."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
RUNTIME=Path(r'C:/Users/no02/Documents/Codex/byd-scoring-runtime')
RULE='6.0-G-HB-2026-09-14-r3'; PRICE='HB-2026-10-13-DH-EV'
CST=timezone(timedelta(hours=8))
def now(): return datetime.now(CST).isoformat()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.partial');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
 return h.hexdigest().upper()
def stat(path):
 p=Path(path);s=p.stat();return {'path':str(p.resolve()),'size':s.st_size,'mtime_ns':s.st_mtime_ns}
def config(): return read(RUNTIME/'runtime-config.json')
def policy_hashes():
 paths=[ROOT/'SKILL.md',*sorted((ROOT/'references').glob('*.md'))]
 return {str(p.relative_to(ROOT)):sha(p) for p in paths}
def code_hashes(): return {p.name:sha(p) for p in sorted((ROOT/'scripts').glob('*.py'))}
def preflight():
 c=config(); assets={k:stat(c[k]) for k in ('python','ffmpeg','ffprobe','primary_model','review_model','adjudication_model','vad_model')}
 assets['transcriber']=stat(RUNTIME/'transcribe_incremental.py');assets['quality']=stat(RUNTIME/'transcription_quality.py')
 assets['config']=sha(RUNTIME/'runtime-config.json')
 assets['dependency_modules']=[stat(x) for x in [RUNTIME/'deps/pywhispercpp/model.py',RUNTIME/'deps/numpy/__init__.py',*sorted((RUNTIME/'deps').glob('*.pyd'))]]
 key=digest(assets);p=RUNTIME/'preflight.json'
 if p.exists() and read(p).get('key')==key:return {**read(p),'reused':True}
 env={**os.environ,'PYTHONPATH':str(RUNTIME/'deps'),'PYTHONIOENCODING':'utf-8'}
 subprocess.run([c['python'],'-c','import pywhispercpp.model,numpy;from PIL import Image;import openpyxl'],env=env,check=True)
 result={'key':key,'checked_at':now(),'assets':assets,'status':'ok','threads':8,'reused':False};save(p,result);return result

def import_source(audio,job_dir,day,probe=None,hash_file=sha):
 p=Path(audio).resolve();j=Path(job_dir).resolve();m=j/'source-manifest.json';identity=stat(p)
 if m.exists():
  old=read(m)
  if str(Path(old['source']).resolve())!=str(p):raise ValueError('Job directory already belongs to another reception')
  if old.get('file_identity')==identity:return old,True
  actual=hash_file(p)
  if actual!=old['sha256']:raise ValueError('Original audio changed; create a new independent reception directory')
  old['file_identity']=identity;old['identity_checked_at']=now();save(m,old);return old,False
 if probe is None:
  probe=json.loads(subprocess.check_output([config()['ffprobe'],'-v','error','-show_entries','stream=codec_type,sample_rate,channels:format=duration','-of','json',str(p)],text=True,encoding='utf-8'))
 stream=next(x for x in probe['streams'] if x.get('codec_type')=='audio')
 value={'source':str(p),'sha256':hash_file(p),'sample_rate':int(stream['sample_rate']),'channels':int(stream['channels']),'duration_seconds':float(probe['format']['duration']),'file_identity':identity,'task_date':day,'rule_version':RULE,'price_policy_version':PRICE,'result_mode':'local_codex_test','imported_at':now(),'price_policy_extension':'大汉EV按2026-10-13增量；其他车型沿用2026-09-17已确认口径'}
 save(m,value);return value,False

def rule_snapshot(directory,acknowledge=False):
 import shutil
 directory=Path(directory);hashes=policy_hashes();p=directory/'rules-read-manifest.json'
 previous=read(p) if p.exists() else {}
 same=previous.get('hashes')==hashes
 if not same:
  for rel in hashes:
   dst=directory/'rule-snapshot'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,dst)
  previous={'hashes':hashes,'created_at':now(),'full_read_completed':False};save(p,previous)
 if acknowledge:
  previous.update(full_read_completed=True,full_read_completed_at=now());save(p,previous)
 return {'same_version_snapshot':same,'full_read_required':not previous.get('full_read_completed',False),'manifest':str(p),'hashes':hashes}

def merge_windows(candidates,max_seconds=180):
 merged=[]
 for s,t in sorted((c['start_ticks']/100,c['end_ticks']/100) for c in candidates):
  if merged and s<=merged[-1][1]:merged[-1][1]=max(t,merged[-1][1])
  else:merged.append([s,t])
 windows=[]
 for start,end in merged:
  while start<end:
   stop=min(start+max_seconds,end);windows.append({'label':f'W{len(windows)+1:03d}','start':start,'end':stop,'channel':'mix'})
   if stop==end:break
   start=stop-2
 return windows

def review_key(manifest,window,model_path,parameters):
 return digest({'source':manifest['sha256'],'channel':window['channel'],'start':float(window['start']),'end':float(window['end']),'model':stat(model_path),'parameters':parameters,'runtime':sha(RUNTIME/'transcribe_incremental.py'),'quality_guard':sha(RUNTIME/'transcription_quality.py'),'semantic_guard':sha(ROOT/'scripts/feedback_policy.py')})

def assemble_audit(raw,decisions,transcript):
 import evidence_candidates as e
 original={c['id']:c for c in raw['candidates']};chosen={}
 for c in original.values():
  if c.get('review_status') in {'scope_excluded','semantic_context'}:chosen[c['id']]={'id':c['id'],'disposition':'rejected','conclusion':c['adopted_conclusion'],'rationale':c['rationale']}
 if isinstance(decisions,dict):
  items=list(decisions.get('items',[]))
  for group in decisions.get('context_groups',[]):
   if group.get('disposition')!='rejected':raise ValueError('Grouped decisions may only reject contextual candidates')
   for cid in group['ids']:items.append({k:v for k,v in group.items() if k!='ids'}|{'id':cid})
  decisions=items
 for d in decisions:
  if d['id'] in chosen and original[d['id']].get('review_status') not in {'scope_excluded','semantic_context'}:raise ValueError('Duplicate candidate decision '+d['id'])
  if d.get('disposition') not in {'confirmed','rejected','unresolved'}:raise ValueError('Invalid disposition '+d['id'])
  if not d.get('rationale') or not d.get('conclusion'):raise ValueError('Decision requires conclusion and rationale '+d['id'])
  chosen[d['id']]=d
 if set(original)!=set(chosen):raise ValueError('Every candidate requires its own explicit decision; missing='+str(sorted(set(original)-set(chosen))))
 result=[]
 for cid,c in original.items():
  d=chosen[cid];x={**c,'automatic_comparison':{k:c.get(k) for k in ('status','rationale','review_signals','adopted_conclusion')},'original_category':c['category'],'review_status':'complete','fact_status':d['disposition'],'adjudicated_at':now(),'rationale':d['rationale'],'adopted_conclusion':d['conclusion']}
  x.update({k:d[k] for k in ('review_signals','review_channel','review_model','introduced_to_customer','review_sources') if k in d})
  if d.get('quote_components') is not None:
   if d['disposition']!='confirmed' or not (x.get('review_transcript') or x.get('review_sources')):raise ValueError('Explicit quote components need confirmed original-audio evidence')
   allowed={'vehicle_or_price','payment_or_finance','fees','gifts','delivery','interior_color'}
   if set(d['quote_components'])-allowed or any(type(v) is not bool for v in d['quote_components'].values()):raise ValueError('Invalid quote components')
   x.setdefault('review_signals',{}).setdefault('quote_components',{}).update(d['quote_components'])
  if d['disposition']=='unresolved':
   x['status']='unresolved';x['adopted_conclusion']=''
   if d.get('review_closed') is True:
    if not d.get('closure_reason') or 'affected_rows' not in d or not x.get('review_sources'):raise ValueError('Closed pending decision needs attempts, affected rows and closure reason')
    x.update(review_closed=True,qualifies_for_scoring=False,closure_reason=d['closure_reason'],affected_rows=d['affected_rows'])
  elif d['disposition']=='rejected':x.update(status='confirmed',category='reviewed_context',qualifies_for_scoring=False,review_signals={'trial':[],'quote_components':{}})
  else:
   x['status']='confirmed'
   if c.get('review_status')=='supplemental_pending':
    if not (x.get('review_sources') and x.get('review_transcript') and x.get('review_channel') and x.get('review_model')):raise ValueError('Confirmed supplement lacks reviewed original-audio provenance: '+cid)
    if c.get('decision_source'):
     from service_policy import original_reviews_valid
     if not original_reviews_valid(d.get('review_sources')) or any(source.get('source_ref') not in c.get('review_window_ids',[]) for source in d['review_sources']):raise ValueError('Manual supplement needs independent original-audio review tied to selected window: '+cid)
    for source in x['review_sources']:
     if isinstance(source,dict) and source.get('conclusion')=='待独立裁决':source['conclusion']=d['conclusion']
    x['qualifies_for_scoring']=True
  result.append(x)
 out={**raw,**e.build_audit(Path(transcript),result)}
 from feedback_policy import quote_sources
 out['derived']['quote_completeness']=quote_sources(result,out['derived']['quote_completeness'])
 out['adjudication_schema']='review-fact-separate-v1';return out


def assemble_publication_contract(job_dir,job,audit):
 """Mirror existing reviewed facts into the publication contract without inventing positive evidence."""
 import copy
 from service_policy import VERSION
 j=Path(job_dir);job=copy.deepcopy(job);audit=copy.deepcopy(audit);missing=[]
 policy=j/'service-policy.json'
 snapshot=read(policy).get('service_policy_version') if policy.exists() else job.get('service_policy_version')
 if snapshot==VERSION:
  for document in (job,audit):
   if document.get('service_policy_version',VERSION)!=VERSION:raise ValueError('Conflicting service_policy_version')
   document['service_policy_version']=VERSION
 for key in ('trial_safety_policy_version','row_assessments','starbucks_service'):
  left,right=job.get(key),audit.get(key)
  if left is not None and right is not None and left!=right:raise ValueError('job/audit '+key+' conflict')
  if left is not None:audit[key]=copy.deepcopy(left)
  elif right is not None:job[key]=copy.deepcopy(right)
  else:missing.append(key)
 if 'starbucks_introduction' not in job and isinstance(audit.get('starbucks_introduction'),dict):
  record=audit['starbucks_introduction'];reviews=record.get('reviews') or []
  if record.get('status') in {'已介绍','未介绍','待核实'} and reviews and reviews[0].get('window'):
   job['starbucks_introduction']={'status':record['status'],'evidence':reviews[0]['window']+' '+str(reviews[0].get('conclusion',''))}
 if 'starbucks_introduction' not in job:missing.append('starbucks_introduction.job')
 if 'starbucks_introduction' not in audit:missing.append('starbucks_introduction.audit')
 return job,audit,missing

def derive_score(job):
 import copy
 from validate_score_job import final_score,negative_incentive,CANONICAL_MAX
 value=copy.deepcopy(job);rows=value.get('rows',[]);extras={'A3','B8','B8coffee'};modules=[]
 from service_policy import active as service_active
 if service_active(value):extras|={'C5bonus','D8bonus'}
 for label,oldmax,oldgot in value['modules']:
  letter=str(label)[0];part=[r for r in rows if r[0]==letter and r[1] not in extras]
  if not part:raise ValueError('No scoring rows for '+letter)
  if sum(int(r[3]) for r in part)!=CANONICAL_MAX[letter]:raise ValueError('Scoring rows must include the full canonical module; NA must be explicit: '+letter)
  modules.append([label,sum(int(r[3]) for r in part if r[4]!='NA'),sum(int(r[4]) for r in part if r[4]!='NA')])
 bonus=sum(int(r[4]) for r in rows if r[1] in extras)
 if sum(int(r[4]) for r in rows if r[1] in {'B8','B8coffee'})>6:raise ValueError('B8 bonus exceeds 6')
 if value.get('bonus',0)>0 and not any(r[1] in extras for r in rows):raise ValueError('Bonus requires its own scoring row')
 value.update(modules=modules,base=sum(r[2] for r in modules),na=100-sum(r[1] for r in modules),bonus=bonus)
 if value.get('h_veto',{}).get('triggered') and (value['base']!=0 or value['bonus']!=0):raise ValueError('Confirmed H veto requires explicit zero score rows')
 value['final_score']=final_score(value['base'],value['na'],bonus);value['negative_incentive']=negative_incentive(value['final_score']);return value

def validate_once(job,audit,path):
 from validate_score_job import validate
 key=digest({'job':job,'audit':audit,'rules':policy_hashes(),'code':code_hashes()});p=Path(path)
 if p.exists():
  prior=read(p)
  if prior.get('input_fingerprint')==key and prior.get('valid') is True:return prior,True
 result=validate(job,audit);result.update(input_fingerprint=key,validated_at=now());save(p,result)
 if not result['valid']:raise ValueError('Score/evidence validation failed: '+str(result['errors']))
 return result,False
