"""Authorized feedback policy for the existing local scoring CLI."""
from __future__ import annotations
import copy, math, re
from pathlib import Path

VERSION = "workflow-feedback-2026-10-09-v1"
SCOPE = "price-scope-2026-10-09-v4"
DOMAINS = {"price", "gift", "finance"}
D_MAX = {"D1":5,"D2":0,"D3":0,"D4":2,"D5":2,"D6":2,"D7":3,"D8":9,"D9":2}
POLICY_NOTE = "合规仅按自律会标准检查价格、赠品及金融政策；专业知识、补贴及置换政策不核查，标准未规定的税险政策/金额不考核。"

def price_candidate_relevant(text):
    # Mixed statements with a real quote/finance/gift remain for semantic review.
    if re.search(r"裸车|成交价|车价|价格|报价|现金优惠|落地|开票|返息|返现|贷款|月供|免息|金融|首付|赠送|赠品|礼品|精品|保养|充电桩|服务费|上牌|交车|提车|到车|内饰",text):
        return True
    if re.search(r"补贴|厂补|省补|报废|置换|购置税|保险|电池|电机|能耗|油耗|续航|平台|架构|磁通",text):
        return False
    return True  # Unknown money context is not automatically discarded.

def scoped_candidates(candidates):
    result=copy.deepcopy(candidates)
    for c in result:
        if c["category"]=="price_policy" and not price_candidate_relevant(c.get("initial_transcript","")):
            c.update(original_category=c["category"],category="reviewed_context",
                     status="confirmed",fact_status="rejected",qualifies_for_scoring=False,
                     review_status="scope_excluded",rationale="用户v4排除专业知识、补贴/置换及表外税险核查",
                     adopted_conclusion="范围外上下文，不核实真实性",review_signals={"trial":[],"quote_components":{}})
    return result

def closed_pending(item,job):
    if not (item.get("fact_status")=="unresolved" and item.get("review_closed") is True
            and item.get("qualifies_for_scoring") is False and item.get("review_sources")
            and item.get("closure_reason") and job.get("workflow_policy_version")==VERSION):
        return False
    ids=item.get("affected_rows",[])
    rows={r[1]:r for r in job.get("rows",[]) if len(r)>=7}
    # A pending fact is not a refusal, veto, full score, or bonus.
    binding=next((x for x in job.get("pending_evidence",[]) if x.get("candidate_id")==item.get("id")
                  and x.get("affected_rows")==ids and x.get("award")==0),None)
    if not binding:return False
    if binding.get("role")=="compliance_only" and not ids:
        return any(x.get("candidate_id")==item.get("id") and x.get("type")=="待核实"
                   and x.get("domain") in DOMAINS and x.get("standard_ref") for x in job.get("compliance",[]))
    if binding.get("role")=="h_pending" and not ids:
        return item.get("category")=="h_veto" and job.get("h_veto",{}).get("triggered") is False
    return bool(ids) and all(k in rows and rows[k][4]==0 and re.search(r"待核|未确认|证据不足|无法确认|未核实",str(rows[k][6])) for k in ids)

def validate_workflow(job,audit,errors):
    if job.get("workflow_policy_version")!=VERSION:
        return
    if audit.get("workflow_policy_version")!=VERSION:
        errors.append("job/audit workflow_policy_version must match")
    if job.get("price_scope_policy_version")!=SCOPE or audit.get("price_scope_policy_version")!=SCOPE:
        errors.append("New workflow requires matching v4 scope in job/audit")
    for item in job.get("compliance",[]):
        if item.get("domain") not in DOMAINS or not str(item.get("standard_ref","")).strip():
            errors.append("Compliance requires price/gift/finance domain and self-discipline standard_ref")
        if item.get("excluded_topic") is True or not price_candidate_relevant(str(item.get("quote",""))):
            errors.append("Excluded professional/subsidy/exchange topics cannot enter compliance")
    if not any(POLICY_NOTE in str(x) for x in job.get("defaults",[])):
        errors.append("Report must declare current compliance scope")
    for item in audit.get("candidates",[]):
        if item.get("review_closed") and not closed_pending(item,job):
            errors.append("Closed pending evidence must stay unresolved, nonqualifying and mapped to zero rows")
    quote=audit.get("derived",{}).get("quote_completeness",{})
    if any(r[1]=="E2" and r[4]==3 for r in job.get("rows",[])):
        sources=quote.get("component_sources",{})
        candidates={c["id"]:c for c in audit.get("candidates",[])}
        for name in ("vehicle_or_price","payment_or_finance","fees","gifts","delivery","interior_color"):
            refs=sources.get(name,[])
            if not refs or any(cid not in candidates or candidates[cid].get("status")!="confirmed"
                               or candidates[cid].get("fact_status") in {"rejected","unresolved","inferred"}
                               or not (candidates[cid].get("review_transcript") or candidates[cid].get("review_sources"))
                               for cid in refs):
                errors.append("E2 component needs original-audio candidate source: "+name)
    validate_matched_trial(job,audit,errors)

def scan_completed(audit):
    scan=audit.get("semantic_scan",{})
    return (audit.get("workflow_policy_version")==VERSION and scan.get("full_transcript_read") is True
            and bool(scan.get("transcript_sha256")) and scan.get("targeted_reviews_complete") is True
            and bool(scan.get("rationale")))

def deduction_details(job):
    rows=job.get("rows",[])
    if not rows:
        return job.get("deductions",[])
    return [[str(r[1])+" "+str(r[2]), str(r[5])+"｜"+str(r[6])]
            for r in rows if len(r)>=7 and r[1] not in {"A3","B8","B8coffee"}
            and r[4]!="NA" and int(r[4])<int(r[3])]

def detailed_trial(job):
    keys={r[1] for r in job.get("rows",[]) if len(r)>=7 and r[0]=="D"}
    return set(D_MAX)<=keys and bool(job.get("trial_score_reuse") or job.get("full_D_policy"))

def validate_matched_trial(job,audit,errors):
    value=job.get("trial_score_reuse")
    if not value:
        return False
    import workflow_support as w
    before=len(errors)
    if audit.get("trial_score_reuse")!=value or value.get("matching",{}).get("status")!="confirmed":
        errors.append("Matched trial requires matching job/audit source contract")
        return False
    match=value["matching"]
    if not all(match.get(k) for k in ("receipt_sha256","trial_sha256","evidence")):
        errors.append("Matched trial requires both source hashes and identity/context evidence")
    try:
        path=Path(value["source_job"])
        source=w.read(path)
        manifest=w.read(path.parent/"source-manifest.json")
        receipt_manifest=w.read(Path(audit["source_transcript"]).parent/"source-manifest.json")
        if w.sha(path)!=value["source_job_sha256"] or manifest["sha256"]!=match["trial_sha256"] or receipt_manifest["sha256"]!=match["receipt_sha256"]:
            raise ValueError("Matched trial source identity changed")
        if value["source_rows"]!=[r for r in source["rows"] if r[0]=="D" and r[1] in D_MAX]:
            raise ValueError("Trial source rows changed")
        actual=[r for r in job["rows"] if r[0]=="D" and r[1] in D_MAX]
        if actual!=value["adopted_rows"]:
            raise ValueError("Receipt D rows differ from adopted trial rows")
        source_by_key={r[1]:r for r in value["source_rows"]}
        for adopted_row in actual:
            if adopted_row[1] not in {"D1","D4","D5"} and adopted_row!=source_by_key[adopted_row[1]]:
                raise ValueError("Detailed trial item was not reused from its source")
            if adopted_row[1]=="D5" and not match.get("d5_duration_policy_applies") and adopted_row!=source_by_key["D5"]:
                raise ValueError("Old trial D5 cannot be changed by the new duration rule")
        if {r[1]:r[3] for r in actual}!=D_MAX:
            raise ValueError("Matched D1-D9 canonical maxima differ")
        for r in actual:
            allowed={0,r[3],"NA"} if r[1]!="D8" else {0,3,6,9,"NA"}
            if r[4] not in allowed:
                raise ValueError("Invalid detailed D score")
        if next(r[4] for r in actual if r[1]=="D1")!=5:
            raise ValueError("Matched trial requires D1=5")
    except (OSError,ValueError,KeyError,StopIteration) as exc:
        errors.append(str(exc))
    return len(errors)==before

def merge_trial(job_dir,trial_job_dir,matching):
    import workflow_support as w
    j=Path(job_dir); t=Path(trial_job_dir)
    job=w.read(j/"job.json");audit=w.read(j/"evidence-audit.json");source=w.read(t/"job.json")
    trial_manifest=w.read(t/"source-manifest.json");receipt_manifest=w.read(j/"source-manifest.json")
    if matching.get("status")!="confirmed" or not matching.get("evidence"):
        raise ValueError("Explicit original-audio matching decision is required")
    if matching.get("receipt_sha256")!=receipt_manifest["sha256"] or matching.get("trial_sha256")!=trial_manifest["sha256"]:
        raise ValueError("Source hashes do not match this reception/trial")
    if source.get('independent_scoring_complete') is not True:raise ValueError('Trial source scoring must be complete')
    if source.get('h_veto',{}).get('triggered'):
        raise ValueError('Independent H veto needs separate adjudication before trial reuse')
    if source.get('D_safety_veto'):
        raise ValueError('Legacy whole-D safety zero must be re-adjudicated item by item before trial reuse')
    original=[copy.deepcopy(r) for r in source["rows"] if r[0]=="D" and r[1] in D_MAX]
    if {r[1]:r[3] for r in original}!=D_MAX:
        raise ValueError("Trial source must contain canonical detailed D1-D9")
    adopted=copy.deepcopy(original)
    for r in adopted:
        if r[1]=="D1":r[4]=5;r[6]="已匹配对应试驾，依用户口径计5分；不重复评邀约。"
        if r[1]=="D4":
            complaint=matching.get("hygiene_complaint",{})
            if complaint.get("confirmed") is True:
                if not all(complaint.get(k) for k in ("customer_quote","timestamp","speaker","trial_vehicle")):
                    raise ValueError("D4 complaint needs customer's quote/time/speaker/current vehicle")
                r[4]=0;r[5]=complaint["timestamp"];r[6]="客户明确投诉当次试驾车卫生："+complaint["customer_quote"]
            else:r[4]=2;r[6]="已匹配对应试驾，按用户默认给2分；不代表物理卫生已经原音证实。"
        if r[1]=="D5" and matching.get("d5_duration_policy_applies") is True:
            duration=matching.get("trial_duration",{})
            if not all(k in duration for k in ("boarded_at_seconds","disembarked_at_seconds","mode","evidence")):
                raise ValueError("D5 needs actual boarding/disembarking times and evidence")
            seconds=float(duration["disembarked_at_seconds"])-float(duration["boarded_at_seconds"])
            if not math.isfinite(seconds) or seconds<0 or duration["mode"] not in {"ordinary","assisted"}:
                raise ValueError("Invalid actual trial duration/mode")
            threshold=1200 if duration["mode"]=="assisted" else 900
            exception=duration.get("customer_shortening_request")
            r[4]=2 if seconds>=threshold or (isinstance(exception,dict) and all(exception.get(k) for k in ("quote","timestamp"))) else 0
            r[5]=duration["evidence"];r[6]="按新收到录音时长口径；实际上下车区间"+str(seconds)+"秒；距离按用户确认默认。"
    value={"policy_version":"matched-trial-2026-10-09-v1","matching":matching,"source_job":str((t/"job.json").resolve()),
           "source_job_sha256":w.sha(t/"job.json"),"source_rows":original,"adopted_rows":adopted}
    job["rows"]=[r for r in job["rows"] if r[0]!="D" or r[1]=="D8bonus"]+adopted
    job["trial_score_reuse"]=value;audit["trial_score_reuse"]=value
    # The full source remains authoritative. A conflicting whole-D safety zero requires a fresh source adjudication.
    for field in ("trial_assessment","semantic_trial_policy_override"):
        job.pop(field,None);audit.pop(field,None)
    job=w.derive_score(job);w.save(j/"job.json",job);w.save(j/"evidence-audit.json",audit)
    return {"D_score":sum(r[4] for r in adopted if r[4]!="NA"),"source_job":value["source_job"],"final_score":job["final_score"]}

def quote_sources(candidates,quote):
    sources={}
    for c in candidates:
        if c.get("status")!="confirmed" or c.get("fact_status") in {"rejected","unresolved","inferred"}:
            continue
        for key,value in c.get("review_signals",{}).get("quote_components",{}).items():
            if value:sources.setdefault(key,[]).append(c["id"])
    return {**quote,"component_sources":sources}

def validate_windows(requests,manifest):
    if not isinstance(requests,list):
        raise ValueError("Review manifest must contain a list")
    for x in requests:
        if not isinstance(x,dict) or not all(k in x for k in ("label","start","end","channel")):
            raise ValueError("Each review window needs label/start/end/channel")
        start,end=float(x["start"]),float(x["end"])
        if not all(math.isfinite(n) for n in (start,end)) or not 0<=start<end<=float(manifest["duration_seconds"])+0.01:
            raise ValueError("Invalid original audio review interval")
        if x.get("review_round",1) not in {1,2}:
            raise ValueError("At most two review rounds; keep unresolved facts pending after that")
        if x["channel"]!="mix":
            index={"left":0,"right":1}.get(x["channel"])
            if index is None and re.fullmatch(r"ch\d+",x["channel"]):index=int(x["channel"][2:])
            if index is None or not 0<=index<manifest["channels"]:
                raise ValueError("Invalid original audio channel")

def semantic_flags(segments,start,end,expected_speech=False):
    text=" ".join(str(s.get("text","")) for s in segments)
    flags=[]
    if re.search(r"字幕.{0,12}(?:提供|制作|社区)|感谢(?:观看|收看)|本节目|subscribe|amara\.org",text,re.I):
        flags.append("possible_media_hallucination")
    if expected_speech and not text.strip():flags.append("speech_expected_but_empty")
    if len(re.sub(r"\s","",text))<4 and end-start>=30:
        flags.append("sparse_or_silent_requires_context_read")
    return flags
