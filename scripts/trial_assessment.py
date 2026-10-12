"""Separate semantic trial adjudication from directly confirmed audio facts."""
from __future__ import annotations
import re

POLICY_VERSION = 'trial-semantic-2026-10-06-v1'
SCHEMA_VERSION = 'semantic-trial-v1'
TIME = re.compile(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)')


def is_inferred(item):
    return (item.get('fact_status') == 'inferred'
            or 'semantic_inference' in str(item.get('evidence_kind', ''))
            or 'semantic_inference' in str(item.get('actual_drive_chain_basis', '')))


def semantic_trial(job):
    return job.get('trial_assessment', {}).get('mode') == 'semantic_inference' or bool(job.get('semantic_trial_policy_override'))


def report_lines(job):
    if not semantic_trial(job):
        return []
    value = job.get('trial_assessment', {})
    labels = {'occurred': '有试驾或试乘', 'not_occurred': '未完成试驾或试乘', 'uncertain': '证据不足'}
    conclusion = labels.get(value.get('conclusion'), value.get('conclusion', '证据不足'))
    rationale = value.get('rationale') or value.get('inference_reason', '')
    trigger_label = {'signed_trial_agreement': '试驾协议已签署', 'trial_route_selected': '试驾路线已选定', 'context_chain': '接待上下文链'}.get(value.get('default_trigger'))
    lines = [f'试驾判断：{conclusion}（语义推断）；不代表直接音频确认客户本人驾车。',
             f'依据：{rationale}']
    if trigger_label:
        lines.insert(1, '采用口径：' + trigger_label + '；签协议或路线选择任一成立默认有试驾。')
    if value.get('confidence'):
        lines.append('推断把握：' + value['confidence'])
    alternatives = value.get('alternative_explanations', []) or job.get('observation_limits', [])
    if alternatives:
        lines.append('可能的其他解释：' + '；'.join(alternatives))
    return lines


def validate_semantic_trial(job, audit, errors):
    """Return scoring adoption, never a direct-confirmation flag."""
    value = job.get('trial_assessment', {})
    timeline = audit.get('trial_review', {}).get('timeline', {})
    inferred = semantic_trial(job) or is_inferred(timeline) or any(is_inferred(c) for c in audit.get('candidates', []))
    if not inferred:
        return False
    before = len(errors)
    if job.get('result_mode', 'local_codex_test') != 'local_codex_test':
        errors.append('Semantic trial policy is scoped to local daily scoring')
    if value.get('schema_version') != SCHEMA_VERSION:
        # Read-only compatibility for already published Oct 5 task overrides.
        override = job.get('semantic_trial_policy_override', {})
        candidate = next((c for c in audit.get('candidates', []) if c.get('id') == value.get('basis_candidate')), {})
        compatible = (job.get('report_date') == '2026-10-05'
                      and bool(override.get('user_instruction'))
                      and audit.get('semantic_trial_policy_override') == override
                      and override.get('does_not_claim_direct_audio_confirmation') is True
                      and value.get('direct_audio_completion_verified') is False
                      and bool(value.get('inference_reason'))
                      and candidate.get('category') == 'test_drive_semantic_inference'
                      and candidate.get('fact_status') == 'inferred'
                      and candidate.get('status') == 'confirmed'
                      and bool(candidate.get('review_sources'))
                      and timeline.get('actual_drive_chain_basis') == 'user_authorized_semantic_inference'
                      and timeline.get('direct_audio_completion_verified') is False)
        if not compatible:
            errors.append('Semantic trial requires an explicit semantic-trial-v1 assessment')
        return compatible and len(errors) == before
    if audit.get('trial_assessment') != value:
        errors.append('job/audit trial_assessment must match')
    if value.get('policy_version') != POLICY_VERSION or value.get('mode') != 'semantic_inference':
        errors.append('Unsupported semantic trial policy/mode')
    if value.get('direct_audio_completion_verified') is not False or value.get('fact_status') != 'inferred':
        errors.append('Semantic trial must remain fact_status=inferred, direct_audio_completion_verified=false')
    if not value.get('rationale') or not value.get('reviewed_at') or value.get('confidence') not in {'high', 'medium', 'low'}:
        errors.append('Semantic trial needs rationale, reviewed_at and confidence')
    if value.get('conclusion') not in {'occurred', 'not_occurred', 'uncertain'}:
        errors.append('Invalid semantic trial conclusion')
    if value.get('conclusion') == 'uncertain':
        errors.append('Unresolved semantic trial conclusion cannot publish a final score')
    if not isinstance(value.get('counter_evidence'), list) or not value.get('alternative_explanations'):
        errors.append('Semantic trial must record counter evidence and alternative explanations')
    refs = value.get('supporting_evidence', [])
    candidates = {c.get('id'): c for c in audit.get('candidates', [])}
    times, stages = [], set()
    for ref in refs:
        c = candidates.get(ref.get('candidate_id'), {})
        match = TIME.search(str(ref.get('window', '')))
        if (not match or not all(ref.get(k) for k in ('channel', 'model', 'summary', 'stage'))
                or c.get('status') != 'confirmed' or c.get('fact_status') in {'rejected', 'unresolved', 'inferred'}
                or c.get('category') == 'reviewed_context'
                or not (c.get('review_transcript') or c.get('review_sources'))):
            errors.append('Semantic trial supporting reference must cite a reviewed original-audio candidate')
        if match:
            times.append(int(match[1]) * 60 + int(match[2]))
        stages.add(ref.get('stage'))
    if not refs or times != sorted(times):
        errors.append('Semantic trial supporting timeline must be nonempty and ordered')
    trigger = value.get('default_trigger')
    if trigger not in {'signed_trial_agreement', 'trial_route_selected', 'context_chain'}:
        errors.append('Semantic trial requires a supported default_trigger')
    if value.get('conclusion') == 'occurred':
        if trigger == 'signed_trial_agreement' and 'agreement_signed' not in stages:
            errors.append('Agreement default requires reviewed completed signing, not invitation to sign')
        elif trigger == 'trial_route_selected' and 'route_selected' not in stages:
            errors.append('Route default requires reviewed selected route, not route introduction')
        elif trigger == 'context_chain' and (len(set(times)) < 2 or len(stages) < 2
                or not stages.intersection({'depart', 'dynamic', 'return', 'post_trial_feedback'})):
            errors.append('Invitation/paperwork/static seating alone cannot establish context-chain completion')
    if timeline.get('actual_drive_chain') is True or timeline.get('verified_actual_drive_chain') is True:
        errors.append('Semantic inference cannot be recorded as a directly verified actual-drive chain')
    for c in audit.get('candidates', []):
        if c.get('category') == 'test_drive_actual' and is_inferred(c):
            errors.append('Inferred trial candidate cannot masquerade as confirmed test_drive_actual')
    return len(errors) == before and value.get('conclusion') == 'occurred'

