"""Regression tests for the authorized Oct 9 feedback changes; no audio/model inference."""
import contextlib, copy, io, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import workflow_support as w
import scoring_pipeline as pipeline
import feedback_policy as f
import service_policy as service
import render_report as renderer
import validate_score_job as validator
import evidence_candidates as evidence
import workflow_experiment as experiment
import test_evidence_pipeline as fixtures

class FeedbackRegressionTests(unittest.TestCase):
    def test_numeric_window_identity_and_channel_model_isolation(self):
        m={"sha256":"source"};a={"start":10,"end":20,"channel":"mix"}
        with patch.object(w,"stat",side_effect=lambda p:{"path":str(p)}),patch.object(w,"sha",return_value="HASH"):
            key=w.review_key(m,a,"turbo",{})
            self.assertEqual(key,w.review_key(m,{**a,"start":10.0,"end":20.0},"turbo",{}))
            self.assertNotEqual(key,w.review_key(m,{**a,"channel":"right"},"turbo",{}))
            self.assertNotEqual(key,w.review_key({"sha256":"other"},a,"turbo",{}))
            self.assertNotEqual(key,w.review_key(m,a,"large",{}))

    def test_default_transcribe_no_shadow_and_explicit_shadow(self):
        import workflow_experiment as ex
        for extra,expected in [([],1),(["--shadow"],2)]:
            with patch.object(sys,"argv",["entry","transcribe","--job-dir","test",*extra]),patch.object(pipeline,"transcribe",return_value={"complete":True}) as run,patch.object(w,"read",return_value={"task_date":"2026-10-09","sha256":"SOURCE"}),patch.object(ex,"shadow_allowed",return_value=True),contextlib.redirect_stdout(io.StringIO()):
                pipeline.main()
            self.assertEqual(run.call_count,expected)

    def test_excluded_subsidy_does_not_generate_quote_sweep(self):
        records=[{"t0":180000,"t1":180500,"text":"厂补3000，省补8%约10000，旧车过户申请"}]
        sweep=evidence.build_trial_sweep_candidates(records)
        self.assertFalse(any(c["sweep_reason"]=="around_quote" for c in sweep))
        scoped=f.scoped_candidates([{"id":"E1","category":"price_policy","initial_transcript":records[0]["text"]}])
        self.assertEqual(scoped[0]["category"],"reviewed_context")
        self.assertFalse(scoped[0]["qualifies_for_scoring"])

    def test_actual_price_finance_gifts_survive_mixed_subsidy(self):
        for text in ("裸车129900，省补不确定","厂补3000，贷款免息","赠送脚垫；电机类型一样"):
            self.assertTrue(f.price_candidate_relevant(text))

    def test_candidate_selection_requires_every_id_and_exact_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp);w.save(j/"source-manifest.json",{"sha256":"SOURCE","duration_seconds":1000,"channels":2,"task_date":"2026-11-01"})
            (j/"initial.jsonl").write_text(json.dumps({"t0":0,"t1":1000,"text":"贷款免息，赠送脚垫"},ensure_ascii=False)+"\n",encoding="utf-8")
            candidates=f.scoped_candidates(evidence.build_candidates(evidence.load_jsonl(j/"initial.jsonl")))
            selection={"full_transcript_read":True,"transcript_sha256":w.sha(j/"initial.jsonl"),"rationale":"完整审读，并逐候选决定是否需要计分复核","candidates":[{"id":c["id"],"action":"context","rationale":"不作为本次计分事实"} for c in candidates]}
            w.save(j/"selection.json",selection)
            with patch.object(experiment,"active",return_value=False):
                result=pipeline.plan(j,j/"selection.json")
            self.assertEqual(result["union_windows"],0)
            self.assertEqual(result["mandatory_b3_channels"],["left","right","mix"])
            selected=w.read(j/"review/selected-windows.json")
            self.assertEqual({x["label"] for x in selected},{"B3_left","B3_right","B3_mix"})
            self.assertTrue(all(x["source_sha256"]==w.read(j/"source-manifest.json").get("sha256") for x in selected))
            selection["candidates"]=selection["candidates"][:-1];w.save(j/"selection.json",selection)
            with self.assertRaises(ValueError),patch.object(experiment,"active",return_value=False):
                pipeline.plan(j,j/"selection.json")

    def test_raw_audit_accepts_only_selected_source_matched_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp);w.save(j/"source-manifest.json",{"sha256":"SOURCE"})
            w.save(j/"review/candidate-plan.json",[])
            w.save(j/"review/windows.json",[{"label":"unselected","start":0,"end":4,"channel":"mix"}])
            selected=[{"label":"B3_mix","start":0,"end":3,"channel":"mix","source_sha256":"SOURCE"}]
            w.save(j/"review/selected-windows.json",selected)
            (j/"initial.jsonl").write_text("",encoding="utf-8")
            result={**selected[0],"quality":"ok","model_path":"turbo","segments":[]}
            results=j/"review/results_selected-windows_turbo.json";w.save(results,[result])
            pipeline.raw_audit(j,results)
            self.assertEqual(len(w.read(j/"review/evidence-audit.raw.json")["quality_review_results"]),1)
            w.save(results,[])
            with self.assertRaisesRegex(ValueError,"B3_mix"):pipeline.raw_audit(j,results)
            w.save(results,[{**result,"channel":"left"}])
            with self.assertRaisesRegex(ValueError,"source/channel/time mismatch"):pipeline.raw_audit(j,results)

    def test_reviewed_wet_tissue_without_initial_candidate_becomes_pending_supplement(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp);w.save(j/"source-manifest.json",{"sha256":"SOURCE"})
            w.save(j/"review/candidate-plan.json",[])
            window={"label":"WET","start":10,"end":20,"channel":"mix","source_sha256":"SOURCE"}
            w.save(j/"review/selected-windows.json",[window])
            (j/"initial.jsonl").write_text("",encoding="utf-8")
            result={**window,"quality":"ok","model_path":"turbo","segments":[{"t0":12,"t1":14,"text":"给您拿湿纸巾"}]}
            results=j/"review/results_selected-windows_turbo.json";w.save(results,[result])
            summary=pipeline.raw_audit(j,results)
            self.assertEqual(len(summary["supplemental_candidates"]),1)
            raw=w.read(j/"review/evidence-audit.raw.json");candidate=raw["candidates"][0]
            self.assertEqual(candidate["category"],"bonus_wet_tissue")
            self.assertEqual(candidate["fact_status"],"unresolved")
            final=w.assemble_audit(raw,[{"id":candidate["id"],"disposition":"confirmed","rationale":"独立原音确认提供","conclusion":"已提供湿纸巾"}],j/"initial.jsonl")
            self.assertTrue(service.confirmed_source(final["candidates"][0]))
            manual=[{"id":"MAN_WET","category":"bonus_wet_tissue","source_sha256":"OTHER","window_label":"WET","start":10,"end":20,"channel":"mix","decision_source":"原音复核"}]
            w.save(j/"manual.json",manual)
            with self.assertRaisesRegex(ValueError,"source/window"):pipeline.raw_audit(j,results,j/"manual.json")
            manual[0]["source_sha256"]="SOURCE";w.save(j/"manual.json",manual)
            pipeline.raw_audit(j,results,j/"manual.json")
            raw=w.read(j/"review/evidence-audit.raw.json")
            decision={"id":"MAN_WET","disposition":"confirmed","rationale":"原音复核","conclusion":"确认提供湿纸巾"}
            with self.assertRaisesRegex(ValueError,"independent original-audio review"):
                w.assemble_audit(raw,[decision],j/"initial.jsonl")
            decision["review_sources"]=[{"window":"00:10-00:20","channel":"mix","model":"turbo","conclusion":"确认提供","source_ref":"WET"}]
            final=w.assemble_audit(raw,[decision],j/"initial.jsonl")
            self.assertTrue(service.confirmed_source(final["candidates"][0]))

    def test_supplemental_scan_merges_same_time_original_channels(self):
        reviews=[{"label":"B3_"+channel,"start":0,"end":180,"channel":channel,"quality":"ok","source_sha256":"SOURCE","model":"turbo",
                  "segments":[{"t0":10,"t1":12,"text":"这是高配版本"}]} for channel in ("left","right","mix")]
        additions=evidence.supplemental_from_reviews([],reviews,"SOURCE")
        self.assertEqual(len(additions),1)
        self.assertEqual(set(additions[0]["review_window_ids"]),{"B3_left","B3_right","B3_mix"})
        self.assertEqual(additions[0]["status"],"needs_manual_review")

    def test_publication_contract_mirrors_only_existing_verified_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp);w.save(j/"service-policy.json",{"service_policy_version":service.VERSION})
            service_states={k:{"status":"not_confirmed","evidence":"00:00-10:00原音未确认"} for k in ("introduction","provided","consumed")}
            job={"row_assessments":{"B3":{"kind":"evidence","rationale":"三项逐一核验"}},"starbucks_service":service_states,"trial_safety_policy_version":"trial-itemwise-2026-10-12-v1"}
            audit={"starbucks_introduction":{"status":"未介绍","reviews":[{"window":"00:00-10:00","conclusion":"未听到介绍"}]}}
            filled_job,filled_audit,missing=w.assemble_publication_contract(j,job,audit)
            self.assertEqual(missing,[])
            self.assertEqual(filled_audit["row_assessments"],job["row_assessments"])
            self.assertEqual(filled_audit["starbucks_service"],service_states)
            self.assertEqual(filled_job["starbucks_introduction"]["status"],"未介绍")
            self.assertEqual(filled_audit["service_policy_version"],service.VERSION)
            _,_,missing=w.assemble_publication_contract(j,{},audit)
            self.assertIn("starbucks_service",missing)
            self.assertIn("row_assessments",missing)

    def test_unknown_fact_cannot_close_into_points_or_na(self):
        c={"id":"E1","fact_status":"unresolved","review_closed":True,"qualifies_for_scoring":False,"review_sources":[{"window":"01:00-01:20","channel":"right","model":"large"}],"closure_reason":"两轮仍听不清","affected_rows":["B3"]}
        job={"workflow_policy_version":f.VERSION,"rows":[["B","B3","礼仪",3,0,"01:00","证据仍待核实，不认定没发生"]],"pending_evidence":[{"candidate_id":"E1","affected_rows":["B3"],"award":0}]}
        self.assertTrue(f.closed_pending(c,job))
        for value in (3,"NA"):
            bad=copy.deepcopy(job);bad["rows"][0][4]=value
            self.assertFalse(f.closed_pending(c,bad))

    def test_unclosed_pending_remains_blocked(self):
        fixture=fixtures.DeterministicScoreValidationTests();fixture.setUp()
        job,audit=fixture.valid_job_and_audit()
        audit["candidates"].append({"id":"E10","status":"unresolved","fact_status":"unresolved"})
        self.assertFalse(validator.validate(job,audit)["valid"])

    def test_explicit_delivery_override_keeps_original_candidate_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript=Path(tmp)/"initial.jsonl";transcript.write_text("",encoding="utf-8")
            c={"id":"E1","category":"price_policy","status":"needs_manual_review","timestamp":"02:28-02:51","start_ticks":14800,"end_ticks":17100,"initial_transcript":"预计二十天至一个月","review_transcript":"预计二十天至一个月","review_channel":"mix","review_model":"turbo","review_signals":{"quote_components":{"delivery":False}}}
            raw=evidence.build_audit(transcript,[c])
            final=w.assemble_audit(raw,[{"id":"E1","disposition":"confirmed","rationale":"原音解释交期","conclusion":"交期20天至一个月","quote_components":{"delivery":True}}],transcript)
            quote=final["derived"]["quote_completeness"]
            self.assertTrue(quote["components"]["delivery"])
            self.assertEqual(quote["component_sources"]["delivery"],["E1"])

    def test_empty_competitor_and_deductions_only(self):
        job={"models_of_interest":{"primary":"秦L","own_brand":["秦L"],"competitors":[],"evidence":"00:10秦L"},"intention":{"level":"C","reason":"考虑","evidence":"00:10继续考虑"},"strict_control":{"status":"否"},"compliance":[]}
        renderer.validate_review_fields(job)
        job["rows"]=[["A","A1","欢迎",5,5,"00:10","已完成"],["B","B3","礼仪",3,0,"00:10","未证实"],["E","E3","权益",2,"NA","00:10","无咨询场景"]]
        self.assertEqual(len(f.deduction_details(job)),1)
        self.assertIn("B3",f.deduction_details(job)[0][0])

    def test_review_inputs_and_semantic_hallucinations(self):
        manifest={"duration_seconds":60,"channels":2}
        with self.assertRaises(ValueError):f.validate_windows([{"label":"X","start":10,"end":20,"channel":"mix","review_round":3}],manifest)
        with self.assertRaises(ValueError):f.validate_windows([{"label":"X","start":10,"end":float("nan"),"channel":"mix"}],manifest)
        self.assertIn("possible_media_hallucination",f.semantic_flags([{"text":"感谢观看，字幕由社区提供"}],0,30))
        self.assertIn("sparse_or_silent_requires_context_read",f.semantic_flags([],0,60))
        self.assertNotIn("speech_expected_but_empty",f.semantic_flags([],0,60))

    def test_matched_trial_reuses_detailed_rows_and_duration_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp)/"receipt";t=Path(tmp)/"trial"
            receipt={"rows":[["D","D1","邀约",5,0,"00:01","旧"],["D","D2-D9","试驾",20,0,"00:01","旧"]],"modules":[["D试驾",25,0]],"bonus":0}
            trial={"independent_scoring_complete":True,"rows":[["D",k,k,m,0 if k in {"D5","D6","D9"} else m,"00:01","原音逐项裁决"] for k,m in f.D_MAX.items()]}
            w.save(j/"source-manifest.json",{"sha256":"RECEIPT"});w.save(t/"source-manifest.json",{"sha256":"TRIAL"})
            w.save(j/"job.json",receipt);w.save(j/"evidence-audit.json",{"source_transcript":str(j/"initial.jsonl")});w.save(t/"job.json",trial)
            matching={"status":"confirmed","receipt_sha256":"RECEIPT","trial_sha256":"TRIAL","evidence":"00:01确认客户销售车型与交接"}
            before=f.merge_trial(j,t,matching)
            self.assertEqual(before["D_score"],19)
            matching.update(d5_duration_policy_applies=True,trial_duration={"boarded_at_seconds":10,"disembarked_at_seconds":910,"mode":"ordinary","evidence":"00:10-15:10实际上下车"})
            after=f.merge_trial(j,t,matching)
            self.assertEqual(after["D_score"],21)
            errors=[];self.assertTrue(f.validate_matched_trial(w.read(j/"job.json"),w.read(j/"evidence-audit.json"),errors),errors)
            bonus_job=w.read(j/"job.json");bonus_job['rows'].append(['D','D8bonus','生动体验加分',2,2,'01:00','已独立评超额表现'])
            self.assertTrue(f.validate_matched_trial(bonus_job,w.read(j/"evidence-audit.json"),[]))
            changed=w.read(j/"job.json");changed["rows"][0][4]=0
            self.assertFalse(f.validate_matched_trial(changed,w.read(j/"evidence-audit.json"),[]))

    def test_experiment_unknown_counts_not_filled_zero(self):
        case={"features":{"B1":{"result":"unmeasured","quality_verified":False,"seconds_saved":None,"confirmed_misses":None,"confirmed_wrong_deductions":None}},"feedback":[],"date":"2026-10-09","audio_sha256":"source"}
        with tempfile.TemporaryDirectory() as tmp,patch.object(experiment,"STATE",Path(tmp)),patch.object(experiment,"cases",return_value=[case]):
            summary=experiment.summarize("2026-10-09")
        b1=summary["features"][0]
        self.assertEqual(b1["status"],"样本不足")
        self.assertIsNone(b1["mean_seconds_saved"])


    def test_review_replay_reuses_success_and_short_failure_without_loading_model(self):
        import types
        from unittest.mock import Mock
        for quality in ("ok","requires_adjudication"):
            with tempfile.TemporaryDirectory() as tmp:
                j=Path(tmp);model=j/"model.bin";model.write_bytes(b"fake weights")
                w.save(j/"source-manifest.json",{"source":str(j/"source.raw"),"sha256":"SOURCE","duration_seconds":60,"channels":2})
                first=[{"label":"event","event_id":"same-event","start":10,"end":20,"channel":"mix"}]
                second=[{**first[0],"label":"renamed","start":10.0,"end":20.0}]
                w.save(j/"first.json",first);w.save(j/"second.json",second)
                decode=Mock(return_value=([{"t0":0,"t1":100,"text":"裸车价格129900"}],quality));build=Mock(return_value=object())
                fake=types.SimpleNamespace(build_model=build,transcribe_chunk=decode)
                native=types.SimpleNamespace(Model=types.SimpleNamespace(_load_audio=lambda p:object()))
                config={"review_model":str(model),"adjudication_model":str(model),"threads":8,"ffmpeg":"unused"}
                with patch.object(w,"config",return_value=config),patch.dict(sys.modules,{"transcribe_incremental":fake,"pywhispercpp.model":native}),patch.object(pipeline.subprocess,"run"),contextlib.redirect_stdout(io.StringIO()):
                    pipeline.review(j,j/"first.json","turbo")
                    result=pipeline.review(j,j/"second.json","turbo")
                self.assertEqual(decode.call_count,1)
                self.assertEqual(build.call_count,1)
                self.assertEqual(result["cached_windows"],1)
                saved=w.read(j/"review/results_second_turbo.json")[0]
                self.assertEqual(saved["label"],"renamed")

    def test_two_event_windows_then_budget_stops_third_expansion(self):
        import types
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            j=Path(tmp);model=j/"model.bin";model.write_bytes(b"fake weights")
            w.save(j/"source-manifest.json",{"source":str(j/"source.raw"),"sha256":"SOURCE","duration_seconds":60,"channels":2})
            decode=Mock(return_value=([{"t0":0,"t1":100,"text":"含混待核"}],"requires_adjudication"))
            fake=types.SimpleNamespace(build_model=lambda p:object(),transcribe_chunk=decode)
            native=types.SimpleNamespace(Model=types.SimpleNamespace(_load_audio=lambda p:object()))
            config={"review_model":str(model),"adjudication_model":str(model),"threads":8,"ffmpeg":"unused"}
            with patch.object(w,"config",return_value=config),patch.dict(sys.modules,{"transcribe_incremental":fake,"pywhispercpp.model":native}),patch.object(pipeline.subprocess,"run"),contextlib.redirect_stdout(io.StringIO()):
                for end in (20,21):
                    w.save(j/"request.json",[{"label":"event","event_id":"stable","start":10,"end":end,"channel":"right"}])
                    pipeline.review(j,j/"request.json","large")
                w.save(j/"request.json",[{"label":"new-name","event_id":"stable","start":10,"end":22,"channel":"right"}])
                with self.assertRaisesRegex(ValueError,"Two review rounds exhausted"):pipeline.review(j,j/"request.json","large")
            self.assertEqual(decode.call_count,2)

    def test_optional_statistics_error_does_not_fail_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fail():raise OSError("Statistics file temporarily unavailable")
            self.assertIsNone(pipeline.optional_statistics(Path(tmp),fail))
            self.assertTrue(w.read(Path(tmp)/"statistics-warning.json")["does_not_block_report"])

    def test_scope_gate_blocks_technical_claim_mislabelled_as_price(self):
        job={"workflow_policy_version":f.VERSION,"price_scope_policy_version":f.SCOPE,"defaults":[f.POLICY_NOTE],"compliance":[{"domain":"price","standard_ref":"虚拟表条款","quote":"油冷永磁电机尚未下放元和宋"}]}
        audit={"workflow_policy_version":f.VERSION,"price_scope_policy_version":f.SCOPE}
        errors=[];f.validate_workflow(job,audit,errors)
        self.assertTrue(any("Excluded" in x for x in errors))

    def test_mixed_policy_statistics_dont_claim_combined_quality_pass(self):
        cases=[]
        for n in range(10):
            cases.append({"audio_sha256":str(n),"date":"2026-10-09","workflow_policy_version":"old" if n<5 else f.VERSION,"features":{"B1":{"result":"improved","quality_verified":True,"audit_ref":"independent","seconds_saved":2}},"feedback":[]})
        with tempfile.TemporaryDirectory() as tmp,patch.object(experiment,"STATE",Path(tmp)),patch.object(experiment,"cases",return_value=cases):
            result=experiment.summarize("2026-10-09")["features"][0]
        self.assertEqual(result["status"],"样本不足")
        self.assertTrue(result["mixed_policy_comparison"])
        self.assertIsNone(result["mean_seconds_saved"])
        self.assertIn("补齐配对",result["recommendation"])
        self.assertNotIn("提交采用",result["recommendation"])

    def test_experiment_advice_tracks_final_status_and_preserves_old_evaluation(self):
        verified={"result":"improved","quality_verified":True,"audit_ref":"independent"}
        for count,regression,expected in ((5,False,"样本不足"),(10,False,"通过"),(10,True,"有问题")):
            cases=[{"audio_sha256":str(n),"date":"2026-10-09","workflow_policy_version":f.VERSION,
                    "features":{"B8":{**verified,**({"result":"regression"} if regression and n==0 else {})}},"feedback":[]} for n in range(count)]
            with tempfile.TemporaryDirectory() as tmp,patch.object(experiment,"STATE",Path(tmp)),patch.object(experiment,"cases",return_value=cases):
                (Path(tmp)/"evaluation.json").write_text('{"historical":true}',encoding="utf-8")
                summary=experiment.summarize("2026-10-15")
                b8=summary["features"][-1]
                self.assertEqual(b8["status"],expected)
                self.assertEqual(b8["recommendation"],{"样本不足":"补齐配对录音/独立证据对照，不能按无反馈推定通过","通过":"满足质量门槛；提交采用建议","有问题":"保留现行正式要求，处理已确认问题"}[expected])
                self.assertEqual((Path(tmp)/"evaluation.json").read_text(encoding="utf-8"),'{"historical":true}')
                versioned=Path(tmp)/("evaluation-"+summary["input_fingerprint"][:12]+".md")
                self.assertIn(b8["recommendation"],versioned.read_text(encoding="utf-8"))


    def test_semantic_invitation_and_delivery_candidates_are_not_omitted(self):
        records=[{"t0":1000,"t1":1600,"text":"我再邀您体验一遍"},{"t0":4000,"t1":4600,"text":"预计二十天至一个月"}]
        candidates=evidence.build_candidates(records)
        self.assertTrue(any(c["category"]=="test_drive_invite" for c in candidates))
        self.assertTrue(any(c["category"]=="price_policy" for c in candidates))

    def test_no_in_scope_consultation_allows_e3_na_without_invented_refusal(self):
        fixture=fixtures.DeterministicScoreValidationTests();fixture.setUp()
        job,audit=fixture.valid_job_and_audit()
        job.update(workflow_policy_version=f.VERSION,price_scope_policy_version=f.SCOPE,defaults=[f.POLICY_NOTE],na=2)
        job["modules"][3]=["D试驾",25,0];job["modules"][4]=["E报价",3,0]
        job["base"]=sum(r[2] for r in job["modules"])
        job["rows"]=[["D","D1","邀约",5,0,"00:01","未核到邀请"],["D","D2-D9","试驾",20,0,"00:01","无完成"],["E","E2","报价",3,0,"00:01","要素不足"],["E","E3","权益",2,"NA","00:01","仅咨询范围外补贴"]]
        audit["candidates"]=[c for c in audit["candidates"] if c["category"]!="test_drive_invite"]
        audit.update(workflow_policy_version=f.VERSION,price_scope_policy_version=f.SCOPE,semantic_scan={"full_transcript_read":True,"transcript_sha256":"fixture","targeted_reviews_complete":True,"rationale":"完整审读"},e3_consultation={"status":"no_in_scope_consultation","rationale":"只问补贴"})
        result=validator.validate(job,audit)
        self.assertTrue(result["valid"],result["errors"])
        audit.pop("e3_consultation")
        self.assertFalse(validator.validate(job,audit)["valid"])

if __name__=="__main__":unittest.main()
