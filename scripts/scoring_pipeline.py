"""One fixed entry point for independent local audio jobs."""
from __future__ import annotations
import argparse,json,os,subprocess,sys,time
from pathlib import Path
import workflow_support as w
import feedback_policy as f
import service_policy as service
sys.path.insert(0,str(w.RUNTIME/'deps'))

def optional_statistics(j,callback):
 try:return callback()
 except Exception as exc:
  try:w.save(j/'statistics-warning.json',{'status':'deferred','error_type':type(exc).__name__,'does_not_block_report':True})
  except OSError:pass
  return None

def transcribe(j,shadow=False):
 import workflow_experiment as ex
 m=w.read(j/'source-manifest.json');c=w.config();wav=j/'source_mono16.wav'
 if not wav.exists():subprocess.run([c['ffmpeg'],'-hide_banner','-loglevel','error','-n','-i',m['source'],'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True)
 out=j/'shadow/turbo-main.jsonl' if shadow else j/'initial.jsonl';out.parent.mkdir(parents=True,exist_ok=True)
 key=w.digest({'source':m['sha256'],'wav':w.stat(wav),'primary':w.stat(c['review_model'] if shadow else c['primary_model']),'script':w.sha(w.RUNTIME/'transcribe_incremental.py'),'environment':w.preflight()['key']})
 stage=out.with_suffix('.stage.json')
 if stage.exists() and out.exists() and w.read(stage).get('key')==key and w.read(stage).get('status')=='complete':return {**w.read(stage),'reused':True}
 if shadow:optional_statistics(j,lambda:ex.record_case(m,j,b1_shadow_started=True))
 env={**os.environ,'PYTHONIOENCODING':'utf-8','BYD_SOURCE_HASH':m['sha256'],'WHISPER_MODEL':c['primary_model'],'WHISPER_FALLBACK_MODEL':c['review_model'],'WHISPER_ADJUDICATION_MODEL':c['adjudication_model'],'WHISPER_CHUNK_SECONDS':'300'}
 if shadow:env.update(WHISPER_MODEL=c['review_model'],WHISPER_FALLBACK_MODEL=c['adjudication_model'])
 start=time.perf_counter();subprocess.run([c['python'],str(w.RUNTIME/'transcribe_incremental.py'),str(wav),str(out)],env=env,check=True)
 seconds=time.perf_counter()-start;result={'key':key,'status':'complete','elapsed_seconds':seconds,'output':str(out),'variant':'turbo_shadow' if shadow else 'baseline','completed_at':w.now()};w.save(stage,result)
 optional_statistics(j,lambda:ex.record_case(m,j,**{'shadow_seconds' if shadow else 'baseline_seconds':seconds}) if ex.active(m['task_date']) else None)
 return result

def plan(j,selection=None):
 import evidence_candidates as e
 import workflow_experiment as ex
 m=w.read(j/'source-manifest.json');candidates=f.scoped_candidates(e.build_candidates(e.load_jsonl(j/'initial.jsonl'))) 
 if selection:
  sel=w.read(selection)
  if sel.get('full_transcript_read') is not True or sel.get('transcript_sha256')!=w.sha(j/'initial.jsonl') or not sel.get('rationale'):
   raise ValueError('Selection requires full transcript read with exact transcript hash and rationale')
  mapping={d['id']:d for d in sel['candidates']}
  if len(mapping)!=len(sel['candidates']) or set(mapping)!={c['id'] for c in candidates}:raise ValueError('Selection must account for every candidate once')
  for candidate in candidates:
   d=mapping[candidate['id']]
   if d.get('action') not in {'review','context'} or not d.get('rationale'):raise ValueError('Each selection needs action and rationale')
   if d['action']=='context' and candidate['category']!='reviewed_context':
    candidate.update(original_category=candidate['category'],category='reviewed_context',status='confirmed',fact_status='rejected',qualifies_for_scoring=False,review_status='semantic_context',rationale=d['rationale'],adopted_conclusion='全量上下文已审读，本候选不作为计分事实',review_signals={'trial':[],'quote_components':{}})
  w.save(j/'review/semantic-scan.json',{k:sel[k] for k in ('full_transcript_read','transcript_sha256','rationale')})
 windows=w.merge_windows([x for x in candidates if x['category']!='reviewed_context'])
 for x in windows:x['event_id']=x['label']
 for c in candidates:c['review_window_ids']=[x['label'] for x in windows if x['start']*100<c['end_ticks'] and x['end']*100>c['start_ticks']]
 # Mandatory B3 per native original channel; mix may reuse the identical Turbo window.
 b3=[{'label':'B3_'+ch,'event_id':'B3_'+ch,'start':0,'end':min(180,m['duration_seconds']),'channel':ch} for ch in ((['left','right']+['ch'+str(i) for i in range(2,m['channels'])]+['mix']) if m['channels']>=2 else ['mix'])]
 w.save(j/'review/candidate-plan.json',candidates);w.save(j/'review/windows.json',windows);w.save(j/'review/b3-windows.json',b3)
 totals={'candidate_count':len(candidates),'union_windows':len(windows),'naive_window_seconds':sum((x['end_ticks']-x['start_ticks'])/100 for x in candidates),'union_window_seconds':sum(x['end']-x['start'] for x in windows),'mandatory_b3_channels':[x['channel'] for x in b3]}
 optional_statistics(j,lambda:ex.observation(m,j,'B2',{'result':'unmeasured','quality_verified':False,'seconds_saved':None,'plan':totals,'audit_ref':str(j/'review/candidate-plan.json')}) if ex.active(m['task_date']) else None)
 return totals

def review(j,manifest,model_name):
 # Runs sequentially on this CPU, reusing only successful identical windows in this reception.
 c=w.config();m=w.read(j/'source-manifest.json');model_path=c['review_model'] if model_name=='turbo' else c['adjudication_model']
 requests=w.read(manifest);f.validate_windows(requests,m)
 if (j/'workflow-policy.json').exists() and any(not x.get('event_id') for x in requests):raise ValueError('New workflow review manifest requires stable event_id')
 sys.path.insert(0,str(w.RUNTIME));from transcribe_incremental import build_model,transcribe_chunk
 from pywhispercpp.model import Model
 model=None;outputs=[];parameters={'threads':c.get('threads',8),'language':'zh','vad':True,'no_context':True};cache=j/'review/cache';cache.mkdir(parents=True,exist_ok=True)
 def decode(window,label):
  nonlocal model
  key=w.review_key(m,window,model_path,parameters);saved=cache/(key+'.json')
  if saved.exists():
   try:
    prior=w.read(saved)
    if (prior.get('cache_key')==key and prior.get('source_sha256')==m['sha256'] and isinstance(prior.get('segments'),list)):
     # Failed same-input ASR is retained too. A different model/channel/shorter window gets a different key.
     return {**prior,**window,'cache_reused':True}
   except (ValueError,OSError):pass
  event_id=window.get('event_id',window['label'].split('_repair_')[0])
  budget=cache/'review-budget.json';ledger=w.read(budget) if budget.exists() else {}
  budget_key=w.digest({'source':m['sha256'],'event':event_id,'channel':window['channel'],'parameters':parameters,'guard':w.sha(Path(f.__file__))})
  attempts=ledger.setdefault(budget_key,[])
  if key not in attempts and len(attempts)>=2:raise ValueError('Two review rounds exhausted for event; close as pending, do not expand windows')
  if key not in attempts:attempts.append(key);w.save(budget,ledger)
  clip=cache/(key+'.wav');channel=window['channel'];extract_start=time.perf_counter();args=[c['ffmpeg'],'-hide_banner','-loglevel','error','-n','-ss',str(window['start']),'-t',str(window['end']-window['start']),'-i',m['source']]
  if channel=='mix':args+=['-ac','1']
  else:
   index={'left':0,'right':1}.get(channel)
   if index is None and channel.startswith('ch'):index=int(channel[2:])
   if index is None or not 0<=index<m['channels']:raise ValueError('Invalid original channel '+channel)
   args+=['-af','pan=mono|c0=c'+str(index)]
  if not clip.exists():subprocess.run(args+['-ar','16000','-c:a','pcm_s16le',str(clip)],check=True)
  extract_seconds=time.perf_counter()-extract_start
  load_start=time.perf_counter()
  if model is None:model=build_model(model_path)
  model_load_seconds=time.perf_counter()-load_start
  start=time.perf_counter();records,quality=transcribe_chunk(model,Model._load_audio(str(clip)),label)
  flags=f.semantic_flags(records,window['start'],window['end'],window.get('speech_expected',False))
  if quality=='ok' and any(x in flags for x in ('possible_media_hallucination','speech_expected_but_empty')):quality='requires_adjudication'
  result={**window,'extract_seconds':extract_seconds,'model_load_seconds':model_load_seconds,'semantic_flags':flags,'label':label,'quality':quality,'model':model_name,'model_path':model_path,'parameters':parameters,'source_sha256':m['sha256'],'cache_key':key,'reviewed_at':w.now(),'elapsed_seconds':time.perf_counter()-start,'segments':[{'t0':window['start']+x['t0']/100,'t1':window['start']+x['t1']/100,'text':x['text']} for x in records]};w.save(saved,result);return result
 for x in requests:
  r=decode(x,x['label'])
  if r['quality']!='ok' and float(x['end'])-float(x['start'])>60:
   failures=[r];pieces=[];s=x['start']
   while s<x['end']:
    stop=min(s+60,x['end']);part=decode({**x,'start':s,'end':stop,'event_id':x.get('event_id',x['label'])+'_repair_'+str(len(pieces)+1)},x['label']+'_repair_'+str(len(pieces)+1));pieces.append(part)
    if stop==x['end']:break
    s=stop-2
   r={**r,'failed_attempts':failures,'repair_reviews':pieces,'quality':'ok' if all(p['quality']=='ok' for p in pieces) else 'requires_adjudication','segments':[s for p in pieces if p['quality']=='ok' for s in p['segments']]}
  outputs.append(r);w.save(j/'review'/('results_'+Path(manifest).stem+'_'+model_name+'.json'),outputs);print(json.dumps({'window':x['label'],'channel':x['channel'],'quality':r['quality'],'cache_reused':r.get('cache_reused',False)}),flush=True)
 w.save(j/'review/pending-windows.json',[x for x in outputs if x['quality']!='ok'])
 w.save(j/'review'/('timing_'+Path(manifest).stem+'_'+model_name+'.json'),{'new_inference_seconds':sum(r.get('elapsed_seconds',0) for r in outputs if not r.get('cache_reused'))+sum(p.get('elapsed_seconds',0) for r in outputs for p in r.get('repair_reviews',[]) if not p.get('cache_reused')),'cache_hits':sum(r.get('cache_reused',False) for r in outputs),'quality_pending':sum(r['quality']!='ok' for r in outputs),'unmeasured_queue_seconds':None})
 return {'reviewed_windows':len(outputs),'cached_windows':sum(x.get('cache_reused',False) for x in outputs),'pending_windows':sum(x['quality']!='ok' for x in outputs),'next_action':'targeted second round or explicit unresolved closure; no full rerun'}

def raw_audit(j,results):
 import evidence_candidates as e
 candidates=w.read(j/'review/candidate-plan.json');reviews=w.read(results)
 expected={x['label'] for x in w.read(j/'review/windows.json')}
 if not expected<={x['label'] for x in reviews}:raise ValueError('Every planned window needs a recorded review result')
 for x in candidates:
  if x.get('review_status') in {'scope_excluded','semantic_context'}:continue
  segments=[s for r in reviews if r['label'] in x['review_window_ids'] for s in r['segments'] if s['t1']>=x['start_ticks']/100 and s['t0']<=x['end_ticks']/100];segments.sort(key=lambda s:s['t0']);text=' '.join(s['text'] for s in segments)
  status,rationale,initial,reviewed=e.compare_signals(x['category'],x['initial_transcript'],text)
  if any(r['quality']!='ok' for r in reviews if r['label'] in x['review_window_ids']):status='needs_manual_review';rationale='录音复核退化，不能把技术完成当事实已确认'
  x.update(status=status,rationale=rationale,initial_signals=initial,review_signals=reviewed,review_transcript=text,review_segments=segments,review_channel='mix',review_model=';'.join(sorted({r['model_path'] for r in reviews if r['label'] in x['review_window_ids']})),adopted_conclusion=text if status=='confirmed' else '')
 out=e.build_audit(j/'initial.jsonl',candidates);out['quality_review_results']=reviews
 if (j/'review/semantic-scan.json').exists():
  out.update(workflow_policy_version=f.VERSION,price_scope_policy_version=f.SCOPE,semantic_scan={**w.read(j/'review/semantic-scan.json'),'targeted_reviews_complete':expected<={r['label'] for r in reviews}})
 w.save(j/'review/evidence-audit.raw.json',out);return {'candidates':len(candidates),'needs_semantic_adjudication':sum(x['status']!='confirmed' for x in candidates)}

def publish(j,out_dir):
 from render_report import render,validate_review_fields
 job=w.read(j/'job.json');audit=w.read(j/'evidence-audit.json')
 if not service.active(job) or audit.get('service_policy_version')!=service.VERSION:raise ValueError('New publication requires matching current service_policy_version; historical validation remains available')
 job=w.derive_score(service.prepare_report(job,audit))
 if (j/'workflow-policy.json').exists():
  job.update(workflow_policy_version=f.VERSION,price_scope_policy_version=f.SCOPE)
  audit.update(workflow_policy_version=f.VERSION,price_scope_policy_version=f.SCOPE)
  if f.POLICY_NOTE not in job.setdefault('defaults',[]):job['defaults'].append(f.POLICY_NOTE)
 for candidate in audit.get('candidates',[]):
  if candidate.get('review_closed'):
   message='待核实：'+str(candidate.get('timestamp','录音对应窗口'))+'；'+str(candidate.get('closure_reason','复核仍含混'))+'。保留未确认事实，不据此认定行为未发生或触发否决。'
   if message not in job.setdefault('defaults',[]):job['defaults'].append(message)
 validate_review_fields(job)
 if any(x.get('fact_status')=='unresolved' and not f.closed_pending(x,job) for x in audit.get('candidates',[])):raise ValueError('Unresolved facts require explicit bounded closure and zero affected rows')
 target=Path(out_dir)/(job['slug']+'_6.0-G暗访评分.png');published=j/'published.json'
 if target.exists():
  fingerprint=w.digest({'job':job,'audit':audit,'rules':w.policy_hashes(),'code':w.code_hashes()})
  if published.exists() and w.read(published).get('validation_fingerprint')==fingerprint and w.read(published).get('png_sha256')==w.sha(target):return {**w.read(published),'reused':True}
  raise ValueError('Existing report is preserved. Choose a new revision slug.')
 result,reused=w.validate_once(job,audit,j/'validation.json');w.save(j/'job.json',job);w.save(j/'evidence-audit.json',audit)
 png,score,penalty=render(job,Path(out_dir));w.save(j/'publication-snapshots'/(job['slug']+'.job.json'),job);w.save(j/'publication-snapshots'/(job['slug']+'.audit.json'),audit);record={'job_snapshot_ref':str((j/'publication-snapshots'/(job['slug']+'.job.json')).resolve()),'audit_snapshot_ref':str((j/'publication-snapshots'/(job['slug']+'.audit.json')).resolve()),'png':str(png.resolve()),'png_sha256':w.sha(png),'score':score,'negative_incentive':penalty,'validation_fingerprint':result['input_fingerprint'],'validation_reused':reused,'published_at':w.now(),'visual_review_required':True};w.save(published,record);return record

def close(j):
 import workflow_experiment as ex
 m=w.read(j/'source-manifest.json');job=w.read(j/'job.json');audit=w.read(j/'evidence-audit.json');v=w.read(j/'validation.json')
 if not v['valid']:raise ValueError('Cannot close invalid score')
 result={'date':m['task_date'],'audio_sha256':m['sha256'],'rule_version':job['rule_version'],'price_policy_version':job['price_policy_version'],'score':v['calculated_score'],'negative_incentive':v['negative_incentive'],'audit_ref':str((j/'evidence-audit.json').resolve()),'report_ref':w.read(j/'published.json')['png'] if (j/'published.json').exists() else None,'unresolved':[x['id'] for x in audit['candidates'] if x['status']!='confirmed'],'observation_limits':job.get('observation_limits',[]),'workflow_policy_version':job.get('workflow_policy_version','legacy-before-2026-10-09'),'price_scope_policy_version':job.get('price_scope_policy_version'),'service_policy_version':job.get('service_policy_version')}
 from trial_assessment import semantic_trial
 result.update(trial_completion_basis='semantic_inference' if semantic_trial(job) else 'direct_evidence_policy',semantic_trial_inference=semantic_trial(job),direct_audio_trial_completion_verified=False if semantic_trial(job) else None,trial_inference_quality_verified=False if semantic_trial(job) else None)
 w.save(j/'case-summary.json',result)
 w.save(j/'experiment-pending.json',{'source_manifest':m,'official_result':result,'status':'pending_optional_statistics','does_not_block_report':True})
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['preflight','rules','init','transcribe','plan-review','review','raw-audit','adjudicate','merge-trial','publish','close']);p.add_argument('--job-dir',type=Path);p.add_argument('--audio',type=Path);p.add_argument('--date',default=w.now()[:10]);p.add_argument('--manifest','--windows',dest='manifest',type=Path);p.add_argument('--trial-job-dir',type=Path);p.add_argument('--model',choices=['turbo','large'],default='turbo');p.add_argument('--decisions',type=Path);p.add_argument('--out-dir',type=Path);p.add_argument('--baseline-only',action='store_true');p.add_argument('--shadow',action='store_true');p.add_argument('--ack-full-read',action='store_true');a=p.parse_args();j=a.job_dir.resolve() if a.job_dir else None
 if a.command!='preflight' and j is None:p.error('--job-dir is required')
 if a.command=='init' and a.audio is None:p.error('init requires --audio')
 if a.command=='publish' and a.out_dir is None:p.error('publish requires --out-dir')
 if a.command=='adjudicate' and a.decisions is None:p.error('adjudicate requires --decisions')
 if a.command=='merge-trial' and (a.trial_job_dir is None or a.decisions is None):p.error('merge-trial requires --trial-job-dir and --decisions matching JSON')
 if a.command=='preflight':r=w.preflight();r={k:r[k] for k in ('status','checked_at','threads','reused')}
 elif a.command=='rules':r=w.rule_snapshot(j,a.ack_full_read)
 elif a.command=='init':m,reused=w.import_source(a.audio,j,a.date);w.save(j/'workflow-policy.json',{'version':f.VERSION,'price_scope_policy_version':f.SCOPE,'review_round_limit':2,'shadow_default':False});w.save(j/'service-policy.json',{'service_policy_version':service.VERSION});r={'sha256':m['sha256'],'sample_rate':m['sample_rate'],'channels':m['channels'],'duration_seconds':m['duration_seconds'],'manifest_reused':reused}
 elif a.command=='transcribe':
  import workflow_experiment as ex
  r={'baseline':transcribe(j)};m=w.read(j/'source-manifest.json')
  if a.shadow and not a.baseline_only and ex.shadow_allowed(m['task_date'],m['sha256']):r['turbo_shadow']=transcribe(j,True)
 elif a.command=='plan-review':r=plan(j,a.decisions)
 elif a.command=='review':r=review(j,a.manifest or j/'review/windows.json',a.model)
 elif a.command=='raw-audit':r=raw_audit(j,a.manifest or j/'review/results_windows_turbo.json')
 elif a.command=='adjudicate':
  r=w.assemble_audit(w.read(j/'review/evidence-audit.raw.json'),w.read(a.decisions),j/'initial.jsonl');w.save(j/'evidence-audit.json',r);r={'candidate_count':len(r['candidates']),'unresolved':sum(x['fact_status']=='unresolved' for x in r['candidates'])}
 elif a.command=='merge-trial':r=f.merge_trial(j,a.trial_job_dir,w.read(a.decisions))
 elif a.command=='publish':r=publish(j,a.out_dir)
 else:r=close(j)
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
