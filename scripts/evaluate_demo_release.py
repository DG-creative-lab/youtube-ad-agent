#!/usr/bin/env python3
"""Run the deterministic demo gate; publish only authored, sanitized evidence."""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import compare_instruction_policies as comparison
from scripts import evaluate_agent_behavior as behavior
from campaign_agent.access import BrandScope, Operator, WorkspaceContext
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.bootstrap.runtime import create_runtime, provision_workspace
from campaign_agent.creatives import EXAMPLES
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.agent.run import DEMO_REQUEST

MANIFEST = ROOT / 'examples/demo-release-evals.v1.json'
MANIFEST_SHA256 = '0aa7679392fa55b6b4d0f4e7c78a53425a749d7d34da98e122a5b99f9b5a4dbf'
LEARNING_IDS = tuple(f'LR123-{index:03}' for index in range(1, 7))


@contextmanager
def offline_guard():
    """Count attempted IO even when the application catches the raised error."""
    attempts = {'external_transport_calls': 0, 'effect_provider_calls': 0}

    def deny(kind):
        def blocked(*args, **kwargs):
            attempts[kind] += 1
            raise behavior.ObservationFailure('offline_io_forbidden')
        return blocked

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'campaign_agent.adapters.openrouter_reviews.send_request'):
            stack.enter_context(patch(target, deny('external_transport_calls')))
        for name in ('prepare', 'validate', 'create_paused', 'readback'):
            stack.enter_context(patch.object(SimulatedCampaignSetup, name, deny('effect_provider_calls')))
        yield attempts


def guarded(execute):
    with offline_guard() as attempts:
        try:
            result = execute()
        except Exception:
            # Exception text may contain ambient paths, provider text or credentials.
            result = {'status': 'failed', 'error': 'suite_execution_failed'}
        result['outbound_attempts'] = attempts.copy()
        if any(attempts.values()):
            result.update(status='failed', error='offline_io_attempted')
        return result


def policy_evaluation(spec, reference):
    report = comparison.compare(spec)
    runs = report['runs']
    scenarios = {row['id']: row for row in spec['scenarios']}
    for run in runs:
        run['keep'] = comparison.score(spec, scenarios[run['scenario']], {
            'action': 'keep', 'collected_batch': False, 'extra_visits': 0, 'trace': [],
        })
    metrics = {name: comparison.summary([run[name] for run in runs]) for name in ('bayesian', 'fixed', 'keep')}
    wins = dict(Counter(run['winner'] for run in runs))
    mismatches = []
    if len(runs) != reference['runs']:
        mismatches.append('run_count')
    if wins != reference['paired_wins']:
        mismatches.append('paired_wins')
    for name, values in metrics.items():
        if any(values.get(key) != value for key, value in reference[name].items()):
            mismatches.append(name + '_reference_metrics')
    cases = []
    for scenario in spec['scenarios']:
        selected = [run for run in runs if run['scenario'] == scenario['id']]
        failures = []
        if [row['seed'] for row in selected] != list(range(spec['seed_start'], spec['seed_start'] + spec['repetitions'])):
            failures.append('missing_or_duplicate_seed')
        for row in selected:
            for name in ('bayesian', 'fixed', 'keep'):
                result = row[name]
                worthwhile = scenario['probabilities'][1] - scenario['probabilities'][0] > spec['bayesian_policy']['minimum_lift'] + 1e-12
                payoff = (spec['bayesian_policy']['reuse_if_worthwhile' if worthwhile else 'reuse_otherwise']
                          if result['action'] == 'reuse' else 0)
                expected_value = payoff - spec['bayesian_policy']['batch_cost'] * int(result['collected_batch'])
                if (abs(result['net_value'] - expected_value) > 1e-12
                        or result['mistaken_reuse'] != (result['action'] == 'reuse' and not worthwhile)
                        or result['worthwhile_not_reused'] != (worthwhile and result['action'] != 'reuse')):
                    failures.append('fixture_truth_scoring')
                collects = sum(step['action'] == 'collect' for step in result['trace'])
                if collects != int(result['collected_batch']) or collects > 1 or result['extra_visits'] > spec['batch_visits']:
                    failures.append('collection_limit')
                collecting = False
                for step in result['trace']:
                    if step['action'] in ('reuse', 'keep', 'collect'):
                        counts = step['counts']
                        target = spec['sample_cap'] if collecting else spec['initial_visits']
                        if any(count['unresolved'] or not count['mature_arrivals'] for count in counts) or sum(count['mature_arrivals'] for count in counts) != target:
                            failures.append('unresolved_or_sparse_decision')
                    collecting |= step['action'] == 'collect'
            if scenario['id'] in ('sparse', 'absent', 'missing-time'):
                if any(row[name]['action'] != 'wait_for_evidence' for name in ('bayesian', 'fixed')):
                    failures.append('unresolved_final_wait')
        cases.append({'id': 'POL123-' + scenario['id'], 'status': 'failed' if failures else 'pass',
                      'mismatches': sorted(set(failures)), 'runs': selected})
    control = {row['seed']: row for row in runs if row['scenario'] == 'no-effect'}
    for case in cases:
        if case['id'] in ('POL123-cohort-conflict', 'POL123-late-conflict'):
            if any(row[name]['trace'] != control[row['seed']][name]['trace'] for row in case['runs'] for name in ('bayesian', 'fixed')):
                case.update(status='failed', mismatches=[*case['mismatches'], 'nonparticipant_or_late_evidence_changed_decision'])
    if any(case['status'] != 'pass' for case in cases):
        mismatches.append('scenario_invariants')
    return {'status': 'failed' if mismatches else 'pass', 'mismatches': mismatches,
            'specification_sha256': report['specification_sha256'], 'source_sha256': report['source_sha256'],
            'policies': metrics, 'paired_wins': wins, 'run_count': len(runs), 'cases': cases,
            'claim': 'Authored paired simulation under frozen costs and probabilities; no campaign lift or policy superiority claim.'}


def foreign_target(path, media):
    scope = BrandScope('authored-eval-client', 'authored-other-brand')
    context = WorkspaceContext(scope, 'authored-eval-workspace', 'authored-eval-installation')
    operator = Operator('authored-eval-reviewer', frozenset({scope}))
    access = behavior.Decisions()
    provision_workspace(path, context, 'foreign-campaign', operator=operator, access=access)
    runtime = create_runtime(path, operator, context=context, campaign_id='foreign-campaign', access=access,
                             examples=tuple(replace(example, scope=scope) for example in EXAMPLES), media_dir=media)
    runtime.resume(runtime.start(DEMO_REQUEST))
    drafts = runtime.drafts
    package = drafts.review_package(drafts.campaign_id, 2)
    drafts.approve_package(drafts.campaign_id, 2, package['fingerprint'])
    draft = drafts.start_brief(drafts.campaign_id, 2, package['fingerprint'],
                              title='Authored foreign brief', goal='Review editing evidence.', context='video-editing')
    return runtime, (drafts.campaign_id, draft['revision'], drafts.review_package(drafts.campaign_id, draft['revision'])['fingerprint'])


def learning_case(case):
    observed = None
    try:
        with TemporaryDirectory(prefix='demo-learning-eval-') as directory:
            path, media = Path(directory) / 'campaign.sqlite3', Path(directory) / 'media'
            media.mkdir()
            for example in EXAMPLES:
                for name in {example.preview, *(take[2] for take in example.takes)}:
                    (media / name).write_bytes(name.encode())
            runtime, target, finding, test = comparison.prepare_walkthrough(path, media)
            source = runtime
            source_before = source.drafts.review_package(target[0], 3)
            correction = runtime.instruction_findings.read(*target)['correction']['id']
            intervention = case['intervention']
            if intervention == 'stale_participant':
                runtime.instruction_tests.open(test['id'], uuid4().hex)
            elif intervention == 'different_context':
                draft = runtime.drafts.start_brief(*target, title='Authored audiobook brief',
                                                   goal='Review audiobook wording.', context='audiobook')
                target = (target[0], draft['revision'], runtime.drafts.review_package(target[0], draft['revision'])['fingerprint'])
            elif intervention == 'retired':
                runtime.instruction_findings.retire(*target, finding_id=finding['id'])
                runtime = create_runtime(path, media_dir=media)
            elif intervention == 'foreign_brand':
                runtime, target = foreign_target(path, media)
            elif intervention not in ('compatible_restart', 'no_permission'):
                raise ValueError('unsupported_intervention')
            before = runtime.drafts.read()
            eligible = runtime.instruction_findings.read(*target)
            denial = None
            try:
                runtime.instruction_findings.apply(*target, finding_id=finding['id'], correction_id=correction,
                    draft_permission='none' if intervention == 'no_permission' else 'instruction_test')
            except (PermissionError, PackageConflict) as error:
                denial = type(error).__name__
            after = runtime.drafts.read()
            package = runtime.drafts.review_package(target[0], after['revision'])
            observed = {'eligible': eligible is not None, 'denial': denial,
                        'revision_delta': after['revision'] - before['revision'],
                        'exact_wording': package['package']['groups'][0]['content']['instruction'] == finding['after'],
                        'draft_unchanged': before == after, 'package_requires_approval': package['approval'] is None,
                        'placements_preserved': before['placements'] == after['placements'],
                        'source_approval_preserved': all(source.drafts.review_package(source.drafts.campaign_id, 3)[key] == source_before[key]
                                                         for key in ('package', 'approval', 'fingerprint'))}
            mismatches = [key for key, value in case['expected'].items() if observed.get(key) != value]
            for invariant in ('package_requires_approval', 'placements_preserved', 'source_approval_preserved'):
                if not observed[invariant]:
                    mismatches.append(invariant)
            if case['expected']['revision_delta'] == 0 and not observed['draft_unchanged']:
                mismatches.append('draft_unchanged')
            return {'id': case['id'], 'requirement': case['requirement'], 'status': 'failed' if mismatches else 'pass',
                    'mismatches': mismatches, 'observed': observed}
    except Exception:
        return {'id': case['id'], 'status': 'failed', 'error': 'learning_case_execution_failed', 'observed': observed}


def learning_evaluation(manifest):
    cases = [learning_case(case) for case in manifest['learning_cases']]
    return {'status': 'pass' if all(case['status'] == 'pass' for case in cases) else 'failed', 'cases': cases,
            'claim': 'Actual application commands and reopened temporary SQLite; authored participant outcomes, no model-quality score.'}


def evaluate(manifest_path=MANIFEST):
    identity = behavior.source_identity()
    report = {'schema_version': 1, 'version': 'demo-release-evals-v1', 'code': identity,
              'status': 'blocked', 'offline_gate_passed': False, 'manifest_sha256': None,
              'hosted_smoke': {'status': 'not_run', 'reason': 'Separate deployed-revision browser verification is required.'},
              'live_model_quality': {'status': 'not_run', 'reason': 'Requires a separate reviewed corpus and authorized budget.'},
              'release_acceptance': 'pending_hosted_smoke_and_review', 'suites': {}}
    try:
        raw = Path(manifest_path).read_bytes()
        report['manifest_sha256'] = sha256(raw).hexdigest()
        if report['manifest_sha256'] != MANIFEST_SHA256:
            raise ValueError('noncanonical_manifest')
        manifest = json.loads(raw)
        policy_raw = comparison.SPEC_PATH.read_bytes()
        if sha256(policy_raw).hexdigest() != manifest['policy_specification_sha256']:
            raise ValueError('noncanonical_policy_specification')
        if sha256(behavior.CORPUS.read_bytes()).hexdigest() != manifest['behavior_corpus_sha256']:
            raise ValueError('noncanonical_behavior_corpus')
        spec = comparison.load_spec(policy_raw)
    except Exception:
        report['error'] = 'invalid_or_unavailable_specification'
        return report
    report.update(specified_from_commit=manifest['specified_from_commit'], provenance=manifest['provenance'], claim=manifest['claim'],
                  policy_specification_sha256=manifest['policy_specification_sha256'])
    report['suites'] = {
        'agent_behavior': guarded(behavior.evaluate),
        'policy_simulation': guarded(lambda: policy_evaluation(spec, manifest['policy_reference'])),
        'learning_reuse': guarded(lambda: learning_evaluation(manifest)),
    }
    # Never allow missing, partial, duplicate or dirty evidence to certify this gate.
    behavior_report = report['suites']['agent_behavior']
    learning_report = report['suites']['learning_reuse']
    policy_report = report['suites']['policy_simulation']
    complete = (behavior_report.get('full_acceptance') is True and behavior_report.get('partial') is False
                and tuple(case.get('id') for case in behavior_report.get('cases', [])) == behavior.CASE_IDS
                and tuple(case.get('id') for case in learning_report.get('cases', [])) == LEARNING_IDS
                and tuple(case.get('id') for case in policy_report.get('cases', [])) == tuple('POL123-' + row['id'] for row in spec['scenarios'])
                and policy_report.get('run_count') == manifest['policy_reference']['runs']
                and all(case.get('status') == 'pass' for suite in report['suites'].values() for case in suite.get('cases', []))
                and behavior_report.get('code') == identity)
    passed = complete and all(suite.get('status') == 'pass' for suite in report['suites'].values())
    if not complete:
        report['error'] = 'incomplete_or_mismatched_evidence'
    if identity['revision'] is None or identity['dirty'] is not False:
        report['error'] = 'clean_committed_revision_required'
        return report
    if behavior.source_identity() != identity:
        report['error'] = 'source_changed_during_evaluation'
        return report
    report.update(status='pass' if passed else 'failed', offline_gate_passed=passed)
    return report


def markdown(report):
    lines = ['# Demo eval release gate', '', f"Offline gate: **{report['status']}**",
             f"Source revision: `{report['code']['revision']}` · dirty: `{report['code']['dirty']}`",
             f"Manifest SHA-256: `{report['manifest_sha256']}`", '',
             'Authored simulations and application-command checks. Hosted smoke and live model quality are separate, not-run results.',
             'Final release acceptance remains pending hosted verification and review.', '']
    if report.get('error'):
        lines += [f"Gate diagnosis: `{report['error']}`", '']
    lines += ['| Suite | Status | Evidence |', '| --- | --- | --- |']
    for name, suite in report['suites'].items():
        lines.append(f"| {name} | {suite['status']} | [{name}.json]({name}.json) |")
    policy = report['suites'].get('policy_simulation', {})
    if 'policies' in policy:
        lines += ['', '| Policy | Wrong reuse | Worthwhile unreused | Extra visits | Mean value |', '| --- | ---: | ---: | ---: | ---: |']
        for name, values in policy['policies'].items():
            lines.append(f"| {name} | {values['mistaken_reuse']} | {values['worthwhile_not_reused']} | {values['extra_visits']} | {values['mean_value']:.4f} |")
        lines += ['', 'Keep is the zero-cost no-change reference. A passing gate reproduces the reviewed comparison; it does not require Bayesian superiority.', '']
    lines += ['', '| Case | Status | Diagnosis | Sanitized trace |', '| --- | --- | --- | --- |']
    for suite in report['suites'].values():
        for case in suite.get('cases', []):
            diagnosis = ', '.join(case.get('mismatches', [])) or case.get('error', '')
            lines.append(f"| {case['id']} | {case['status']} | {diagnosis} | [trace](traces/{case['id']}.json) |")
    return '\n'.join(lines) + '\n'


def write_report(directory, report):
    # A new directory prevents stale trace mixing and accidental overwrites.
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'traces').mkdir()

    def write(path, value):
        path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')

    write(directory / 'report.json', report)
    (directory / 'report.md').write_text(markdown(report))
    for name, suite in report['suites'].items():
        write(directory / (name + '.json'), suite)
        specification = {key: suite[key] for key in ('corpus_id', 'corpus_version', 'corpus_sha256',
                         'specification_sha256', 'specified_from_commit', 'claim') if key in suite}
        for case in suite.get('cases', []):
            write(directory / 'traces' / (case['id'] + '.json'), {
                'code': report['code'], 'manifest_sha256': report['manifest_sha256'],
                'provenance': report['provenance'], 'suite': name, 'specification': specification, 'case': case,
            })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='Create a new directory of JSON, Markdown and per-case traces.')
    args = parser.parse_args(argv)
    if args.output_dir and args.output_dir.exists():
        print(json.dumps({'status': 'blocked', 'error': 'report_output_already_exists'}))
        return 2
    report = evaluate()
    if args.output_dir:
        try:
            write_report(args.output_dir, report)
        except (OSError, ValueError):
            print(json.dumps({'status': 'blocked', 'error': 'report_output_unavailable'}))
            return 2
        print(json.dumps({'status': report['status'], 'offline_gate_passed': report['offline_gate_passed'],
                          'code': report['code'], 'error': report.get('error')}))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'pass' and report['offline_gate_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
