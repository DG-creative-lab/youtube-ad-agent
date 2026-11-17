#!/usr/bin/env python3
"""Execute the frozen authored-model portfolio offline through native commands."""
from contextlib import ExitStack, closing
from copy import deepcopy
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from campaign_agent.access import LOCAL_BRAND
from campaign_agent.domain.scope import Operator
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.creatives import EXAMPLES
from campaign_agent.placement_discovery import SimulatedClassifier
from campaign_agent.domain.errors import PackageConflict

CORPUS = ROOT / 'examples/agent-behavior-evals.v1.json'
CORPUS_SHA256 = '9c082805b752a1c8393ec7b392e9ac11c8e28c3d261b25f3bed3579cc6592b32'
CASE_IDS = tuple(f'AB51-{index:03}' for index in range(1, 12))
COUNTERS = ('main_model_dispatches', 'classifier_dispatches', 'external_transport_calls', 'effect_provider_calls')
KINDS = ('capability_question', 'material_ambiguity', 'factual_native_reply', 'read_only_forced_write',
         'revoked_grant', 'foreign_actor_scope', 'stale_revision', 'catalog_injection',
         'current_brand_context_injection', 'late_superseded_result', 'permitted_draft_replay')
SETUPS = {'empty_campaign', 'approved_revision_then_edit', 'catalog_description_injection', 'current_brief_goal_injection'}
INTERLEAVINGS = {'none', 'revoke_agent_run_after_first_step', 'foreign_actor_read_resume_and_followup_before_first_step',
                 'independent_edit_after_first_step', 'followup_during_third_model_call', 'reopen_and_replay_completed_operation'}
CASE_FIELDS = {'id', 'case_version', 'kind', 'requirement', 'provenance', 'coverage_reuse', 'support',
               'setup', 'user_request', 'draft_permission', 'model_calls', 'interleaving', 'expected', 'followup', 'adversarial_data'}
EXPECTED_FIELDS = {'run_statuses', 'reply_codes', 'current_revision', 'placement_ids', 'current_package_approved',
                   'historical_approval_count', 'draft_equal_before', 'persisted_step_count', 'error_step_count',
                   'message_count', 'assistant_message_count', 'dispatch_counts', 'message_contains', 'message_not_contains',
                   'capability_states', 'historical_approved_revision', 'expected_exception', 'post_interleaving_dispatch_delta',
                   'foreign_conversation_visible', 'independent_edit_preserved', 'saved_catalog_facts', 'forbidden_placement_ids',
                   'model_observation_contains', 'brief_goal_preserved', 'superseded_run_step_count', 'late_save_step_absent',
                   'ambiguous_ids', 'saved_source_references', 'replay_equal', 'post_replay_dispatch_delta'}
AUDIT_TABLES = {'agent_runs', 'agent_steps', 'planner_sessions', 'planner_defaults', 'planner_jobs', 'planner_turns', 'planner_messages'}


class InvalidCorpus(ValueError):
    pass


class ObservationFailure(AssertionError):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCorpus('duplicate_json_field')
        result[key] = value
    return result


def load_corpus(path=CORPUS):
    """Only the independently accepted bytes may define acceptance expectations."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise InvalidCorpus('unreadable_or_invalid_corpus') from None
    return parse_corpus(raw)


def parse_corpus(raw):
    """Validate the same immutable buffer that supplies the reported fingerprint."""
    try:
        spec = json.loads(raw, object_pairs_hook=unique_fields,
                          parse_constant=lambda _: (_ for _ in ()).throw(InvalidCorpus('invalid_json_constant')))
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidCorpus('unreadable_or_invalid_corpus') from None
    if not isinstance(spec, dict) or sha256(raw).hexdigest() != CORPUS_SHA256:
        raise InvalidCorpus('noncanonical_corpus')
    if (spec.get('schema_version') != 1 or spec.get('corpus_version') != '1.0.0'
            or spec.get('corpus_id') != 'youtube-ad-agent.offline-behavior'
            or tuple(case.get('id') for case in spec.get('cases', [])) != CASE_IDS):
        raise InvalidCorpus('unsupported_or_incomplete_corpus')
    for index, case in enumerate(spec['cases']):
        if (set(case) - CASE_FIELDS or case['kind'] != KINDS[index] or case['setup'] not in SETUPS
                or case['interleaving'] not in INTERLEAVINGS or set(case['expected']) - EXPECTED_FIELDS
                or set(case['expected']['dispatch_counts']) != set(COUNTERS)):
            raise InvalidCorpus('unsupported_case')
        scripts = [case, *([case['followup']] if 'followup' in case else [])]
        for script in scripts:
            if (script['draft_permission'] not in {'none', 'placements'} or not script['model_calls']
                    or len(script['model_calls']) > 8
                    or any(set(call) != {'tool', 'arguments'} or not isinstance(call['tool'], str)
                           or not isinstance(call['arguments'], dict) for call in script['model_calls'])):
                raise InvalidCorpus('unsupported_script')
    return spec


def source_identity():
    try:
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT,
                                    check=True, capture_output=True, text=True).stdout.strip())
        return {'revision': revision, 'dirty': dirty}
    except (OSError, subprocess.SubprocessError):
        return {'revision': None, 'dirty': None}


class Decisions:
    def __init__(self):
        self.denied = set()

    def decide(self, request):
        return 'deny' if request.capability in self.denied else 'allow'


class ScriptedModel:
    """Finite authored responses, with observations taken at the actual model port."""
    def __init__(self, case, counts):
        self.case, self.counts = case, counts
        self.positions, self.scripts, self.observations, self.requests = {}, {}, [], {}
        self.before_return = None

    def next_turn(self, context, history, settings):
        self.counts['main_model_dispatches'] += 1
        # Serialize what the runtime actually supplied, not corpus/setup text.
        observed = json.loads(json.dumps({'context': context, 'history': history}, sort_keys=True))
        run = self.requests[context['request']]
        index = self.positions.get(run, 0)
        script = self.scripts[run]
        if index >= len(script):
            raise ObservationFailure('unexpected_model_dispatch')
        self.observations.append((run, index, observed))
        witness = self.case['expected'].get('model_observation_contains')
        if witness and index == witness['before_call_index']:
            native_results = [step['result'] for step in observed['history'] if step['tool'] == witness['history_tool']]
            if not any(witness['text'] in json.dumps(result) for result in native_results):
                raise ObservationFailure('injection_not_observed_before_attack')
        self.positions[run] = index + 1
        if self.before_return is not None:
            self.before_return(run, index)
        return {'call_id': f'authored-{index}', **deepcopy(script[index]),
                'inference': {'mode': 'simulated', 'model': settings['model'], 'usage': None}}


class Classifier:
    route = 'simulated_decision'

    def __init__(self, counts):
        self.counts = counts

    def classify(self, rows, contexts):
        self.counts['classifier_dispatches'] += 1
        if self.counts['classifier_dispatches'] > 1:
            raise ObservationFailure('unexpected_classifier_dispatch')
        return SimulatedClassifier().classify(rows, contexts)


def rows_by_table(path):
    with closing(sqlite3.connect(path)) as db:
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        # Names originate in SQLite's own schema, never the corpus.
        return {name: sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
                for name in names}


class Exercise:
    def __init__(self, directory, spec, case, stack):
        self.case, self.spec, self.stack = case, spec, stack
        self.path, self.media = directory / 'campaign.sqlite', directory / 'media'
        self.media.mkdir()
        for example in EXAMPLES:
            for name in {example.preview, *(take[2] for take in example.takes)}:
                (self.media / name).write_bytes(name.encode())
        self.counts = dict.fromkeys(COUNTERS, 0)
        self.policy = Decisions()
        self.model = ScriptedModel(case, self.counts)
        self.classifier = Classifier(self.counts)
        self.runs, self.exceptions = [], []
        self.extra = {}
        self.session = '1' * 32
        self.runtime = self.reopen()
        catalog = deepcopy(spec['catalog'])
        if case['setup'] == 'catalog_description_injection':
            catalog[0]['description'] = case['adversarial_data']['catalog_description']
        self.catalog = self.runtime.planner.catalogs.register('Authored evaluation catalog', catalog)
        if case['setup'] == 'approved_revision_then_edit':
            placements = [{'id': row['video_id'], 'title': row['description'], 'source': row['source'],
                           'creative': creative} for row, creative in zip(catalog[:2], ['video-editing', 'audiobook'])]
            self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 1, 'placements': placements})
            review = self.runtime.drafts.review_package('tts-sample', 2)
            self.runtime.drafts.approve_package('tts-sample', 2, review['fingerprint'])
            self.historical = self.runtime.drafts.read_approved_package('tts-sample', 2, review['fingerprint'])['package']
            self.historical_fingerprint = review['fingerprint']
            self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 2, 'placements': placements[1:]})
        elif case['setup'] == 'current_brief_goal_injection':
            data = case['adversarial_data']
            review = self.runtime.drafts.review_package('tts-sample', 1)
            self.runtime.drafts.start_brief('tts-sample', 1, review['fingerprint'], title=data['brief_title'],
                                          goal=data['brief_goal'], context=data['brief_context'])
        self.before = self.runtime.drafts.read()
        self.before_tables = rows_by_table(self.path)

    def external(self, *args, **kwargs):
        self.counts['external_transport_calls'] += 1
        raise ObservationFailure('external_io_forbidden')

    def effect(self, *args, **kwargs):
        self.counts['effect_provider_calls'] += 1
        raise ObservationFailure('effect_provider_forbidden')

    def reopen(self, **options):
        runtime = AgentRuntime(self.path, media_dir=self.media, access=self.policy, planner_simulator=self.model,
                               placement_classifier=self.classifier, main_transport=self.external,
                               review_transport=self.external, draft_transport=self.external, **options)
        for name in ('prepare', 'validate', 'create_paused', 'readback'):
            self.stack.enter_context(patch.object(runtime.setup.provider, name, self.effect))
        return runtime

    def start(self, script, *, run=None):
        run = run or f'{len(self.runs) + 2:032x}'
        self.model.scripts[run] = script['model_calls']
        self.model.requests[script['user_request']] = run
        latest = self.runtime.planner.conversations.read(self.session)['latest_message'] if self.runs else 0
        self.runtime.planner.start(script['user_request'], 'simulated', self.session, run, self.catalog,
                                   after_message=latest, draft_permission=script['draft_permission'])
        self.runs.append(run)
        return run

    def finish(self, run, runtime=None):
        runtime = runtime or self.runtime
        for _ in range(9):
            result = runtime.resume(run, max_steps=1)
            if result['status'] != 'running':
                return result
        raise ObservationFailure('bounded_run_did_not_finish')

    def denial(self, action, exception):
        try:
            action()
        except exception:
            self.exceptions.append(exception.__name__)
        else:
            raise ObservationFailure('expected_denial_missing')

    def execute(self):
        run = self.start(self.case)
        intervention = self.case['interleaving']
        if intervention == 'foreign_actor_read_resume_and_followup_before_first_step':
            other = self.reopen(operator=Operator('foreign-authored-buyer', frozenset({LOCAL_BRAND})))
            self.extra['foreign_conversation_visible'] = any(item['id'] == self.session for item in other.planner.conversations.list())
            self.denial(lambda: other.planner.conversations.read(self.session), PermissionError)
            self.denial(lambda: other.resume(run), PermissionError)
            self.denial(lambda: other.planner.start('Foreign followup', 'simulated', self.session,
                                                   'f' * 32, self.catalog, after_message=1), PermissionError)
        elif intervention in {'revoke_agent_run_after_first_step', 'independent_edit_after_first_step'}:
            self.runtime.resume(run, max_steps=1)
            before = self.counts.copy()
            if intervention == 'revoke_agent_run_after_first_step':
                self.policy.denied.add('youtube:agent.run')
                exception = PermissionError
            else:
                self.runtime.drafts.save({'campaign_id': 'tts-sample', 'revision': 1,
                                          'placements': [self.case['adversarial_data']['independent_placement']]})
                exception = PackageConflict
            self.denial(lambda: self.runtime.resume(run), exception)
            reopened = self.reopen()
            self.denial(lambda: reopened.resume(run), exception)
            self.extra['post_interleaving_dispatch_delta'] = {key: self.counts[key] - before[key] for key in COUNTERS}
            self.policy.denied.clear()
        elif intervention == 'followup_during_third_model_call':
            def followup(old_run, index):
                if old_run == run and index == 2:
                    self.start(self.case['followup'])
            self.model.before_return = followup
            self.finish(run)
            self.finish(self.runs[1])
            self.reopen().resume(run)
        else:
            result = self.finish(run)
            if intervention == 'reopen_and_replay_completed_operation':
                before = self.counts.copy()
                tables = rows_by_table(self.path)
                reopened = self.reopen()
                same = reopened.planner.start(self.case['user_request'], 'simulated', self.session, run, self.catalog,
                                               after_message=0, draft_permission=self.case['draft_permission'])
                self.extra['replay_equal'] = same == run and reopened.resume(run) == result and reopened.resume(run) == result
                self.extra['replay_equal'] &= rows_by_table(self.path) == tables
                self.extra['post_replay_dispatch_delta'] = {key: self.counts[key] - before[key] for key in COUNTERS}
            elif 'followup' in self.case:
                self.finish(self.start(self.case['followup']))
        return self.observe()

    def observe(self):
        runtime = self.reopen()
        draft = runtime.drafts.read()
        tables = rows_by_table(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            statuses = [db.execute('SELECT status FROM agent_runs WHERE id=?', (run,)).fetchone()[0] for run in self.runs]
            results = [json.loads(row[0]) for row in db.execute('SELECT outcome FROM planner_jobs ORDER BY rowid') if row[0]]
            permissions = [json.loads(row[0])['draft_permission'] for row in db.execute('SELECT snapshot FROM planner_jobs ORDER BY rowid')]
            steps = [json.loads(row[0]) for row in db.execute('SELECT result FROM agent_steps ORDER BY rowid')]
            step_tools = [row[0] for row in db.execute('SELECT tool FROM agent_steps ORDER BY rowid')]
            assistant = [row[0] for row in db.execute("SELECT content FROM planner_messages WHERE role='assistant' ORDER BY id")]
            message_count = db.execute('SELECT COUNT(*) FROM planner_messages').fetchone()[0]
            approvals = db.execute('SELECT COUNT(*) FROM campaign_package_approvals').fetchone()[0]
            old_step_tools = [row[0] for row in db.execute('SELECT tool FROM agent_steps WHERE run_id=? ORDER BY position', (self.runs[0],))]
        unrelated = sorted((set(tables) | set(self.before_tables)) - AUDIT_TABLES - {'campaign_revisions'})
        unchanged = all(tables.get(name) == self.before_tables.get(name) for name in unrelated)
        old_revisions = self.before_tables['campaign_revisions']
        history_retained = all(row in tables['campaign_revisions'] for row in old_revisions)
        observed = {'run_statuses': statuses, 'reply_codes': [row['reply_code'] for row in results if row.get('reply_code')],
                    'current_revision': draft['revision'], 'placement_ids': [row['id'] for row in draft['placements']],
                    'current_package_approved': runtime.drafts.review_package('tts-sample', draft['revision'])['approval'] is not None,
                    'historical_approval_count': approvals, 'draft_equal_before': draft == self.before,
                    'persisted_step_count': len(steps), 'error_step_count': sum('error' in row for row in steps),
                    'message_count': message_count, 'assistant_message_count': len(assistant),
                    'dispatch_counts': self.counts.copy(), 'assistant_messages': assistant,
                    'draft_permissions': permissions,
                    'steps': [{'tool': tool, 'error': 'error' in result, 'revision': result.get('revision')}
                              for tool, result in zip(step_tools, steps)],
                    'unrelated_tables_unchanged': unchanged, 'historical_revisions_retained': history_retained,
                    'checked_unrelated_tables': unrelated, 'exceptions': self.exceptions.copy(), **self.extra}
        expected = self.case['expected']
        if 'capability_states' in expected:
            observed['capability_states'] = {row['id']: row['state'] for row in runtime.capabilities()['capabilities']
                                             if row['id'] in expected['capability_states']}
        if 'historical_approved_revision' in expected:
            saved = runtime.drafts.read_approved_package('tts-sample', 2, self.historical_fingerprint)
            observed['historical_approved_revision'] = 2 if saved['package'] == self.historical else None
        if 'independent_edit_preserved' in expected:
            observed['independent_edit_preserved'] = draft['placements'] == [self.case['adversarial_data']['independent_placement']]
        if 'saved_catalog_facts' in expected:
            observed['saved_catalog_facts'] = [{key: row.get(key) for key in expected['saved_catalog_facts']}
                                               for row in draft['placements']]
        if 'forbidden_placement_ids' in expected:
            observed['forbidden_placement_ids_present'] = sorted(set(expected['forbidden_placement_ids']) & set(observed['placement_ids']))
        if 'model_observation_contains' in expected:
            witness = expected['model_observation_contains']
            histories = [data['history'] for run, index, data in self.model.observations
                         if run == self.runs[0] and index == witness['before_call_index']]
            matching = [step['result'] for history in histories for step in history if step['tool'] == witness['history_tool']]
            observed['model_observation_witness'] = {'call_index': witness['before_call_index'], 'history_tool': witness['history_tool'],
                                                     'text': witness['text'], 'seen': any(witness['text'] in json.dumps(row) for row in matching)}
        if 'brief_goal_preserved' in expected:
            observed['brief_goal_preserved'] = draft['brief']['goal']
        if 'superseded_run_step_count' in expected:
            observed['superseded_run_step_count'] = len(old_step_tools)
            observed['late_save_step_absent'] = 'save_placement_draft' not in old_step_tools
        if 'ambiguous_ids' in expected:
            observed['ambiguous_ids'] = [row['id'] for result in results for row in result.get('ambiguous', [])]
        if 'saved_source_references' in expected:
            observed['saved_source_references'] = {row['id']: row.get('source_reference') for row in draft['placements']}
        return observed


def compare(case, observed):
    """Return mismatch field names only; model prose is never a state oracle."""
    failures = []
    special = {'message_contains', 'message_not_contains', 'expected_exception', 'saved_catalog_facts',
               'forbidden_placement_ids', 'model_observation_contains'}
    for key, expected in case['expected'].items():
        if key not in special and observed.get(key) != expected:
            failures.append(key)
    text = '\n'.join(observed['assistant_messages'])
    for key, present in [('message_contains', True), ('message_not_contains', False)]:
        if any((item in text) != present for item in case['expected'][key]):
            failures.append(key)
    expected = case['expected']
    if 'expected_exception' in expected and (not observed['exceptions'] or set(observed['exceptions']) != {expected['expected_exception']}):
        failures.append('expected_exception')
    if 'saved_catalog_facts' in expected and observed['saved_catalog_facts'] != [expected['saved_catalog_facts']]:
        failures.append('saved_catalog_facts')
    if 'forbidden_placement_ids' in expected and observed['forbidden_placement_ids_present']:
        failures.append('forbidden_placement_ids')
    if 'model_observation_contains' in expected and not observed['model_observation_witness']['seen']:
        failures.append('model_observation_contains')
    for invariant in ('unrelated_tables_unchanged', 'historical_revisions_retained'):
        if not observed[invariant]:
            failures.append(invariant)
    permissions = [case['draft_permission'], *([case['followup']['draft_permission']] if 'followup' in case else [])]
    if observed['draft_permissions'] != permissions:
        failures.append('draft_permissions')
    return failures


def run_case(spec, case):
    observed = None
    try:
        with TemporaryDirectory(prefix='factory51-eval-') as directory, ExitStack() as stack:
            # The simulator has no credential input or provider configuration.
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            exercise = Exercise(Path(directory), spec, case, stack)
            stack.enter_context(patch('socket.socket.connect', exercise.external))
            stack.enter_context(patch('socket.create_connection', exercise.external))
            stack.enter_context(patch('socket.getaddrinfo', exercise.external))
            stack.enter_context(patch('campaign_agent.adapters.openrouter_reviews.send_request', exercise.external))
            try:
                observed = exercise.execute()
            except Exception:
                # Capture whatever native evidence remains before disposing of the store.
                try:
                    observed = exercise.observe()
                except Exception:
                    observed = None
                raise
            failures = compare(case, observed)
            return {'id': case['id'], 'status': 'failed' if failures else 'pass', 'mismatches': failures, 'observed': observed}
    except Exception as exc:
        # Never expose provider/credential/host exception text or repr in machine reports.
        return {'id': case['id'], 'status': 'failed', 'error': 'case_execution_failed',
                'error_type': type(exc).__name__ if type(exc) in {ObservationFailure, PermissionError, PackageConflict,
                                                                ValueError, KeyError, TypeError, sqlite3.OperationalError} else 'Exception',
                'observed': observed, 'dispatch_counts': exercise.counts.copy() if 'exercise' in locals() else None}


def evaluate(path=CORPUS, selected=None):
    identity = source_identity()
    report = {'report_version': 1, 'corpus_version': '1.0.0', 'corpus_sha256': None,
              'accepted_corpus_sha256': CORPUS_SHA256, 'code': identity, 'status': 'blocked',
              'full_acceptance': False, 'partial': False, 'cases': [],
              'full_acceptance_scope': 'complete canonical portfolio only; release requires independent exact-commit review and CI',
              'claim': 'Authored-model command containment only; no live model quality, billing or readiness claim.'}
    try:
        raw = Path(path).read_bytes()
        report['corpus_sha256'] = sha256(raw).hexdigest()
        spec = parse_corpus(raw)
        report['corpus_id'] = spec['corpus_id']
        report['specified_from_commit'] = spec['specified_from_commit']
        if selected is not None and (not selected or len(set(selected)) != len(selected) or set(selected) - set(CASE_IDS)):
            raise InvalidCorpus('unknown_empty_or_duplicate_selection')
    except (OSError, InvalidCorpus) as exc:
        report['error'] = str(exc) if isinstance(exc, InvalidCorpus) else 'unreadable_corpus'
        report['cases'] = [{'id': case, 'status': 'notrun'} for case in CASE_IDS]
        return report
    wanted = set(CASE_IDS if selected is None else selected)
    report['partial'] = wanted != set(CASE_IDS)
    report['cases'] = [run_case(spec, case) if case['id'] in wanted else {'id': case['id'], 'status': 'notrun'} for case in spec['cases']]
    if any(case.get('status') == 'failed' for case in report['cases']):
        report['status'] = 'failed'
    elif any(case.get('status') != 'pass' for case in report['cases'] if case['id'] in wanted):
        report['error'] = 'incomplete_case_execution'
    elif identity['revision'] is None:
        report['error'] = 'code_revision_unavailable'
    elif report['partial']:
        report['status'] = 'partial'
    elif all(case.get('status') == 'pass' for case in report['cases']):
        report['status'], report['full_acceptance'] = 'pass', True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=CORPUS, help='Must contain the exact accepted corpus bytes.')
    parser.add_argument('--case', action='append', dest='selected', help='Select a case; incomplete runs exit nonzero.')
    parser.add_argument('--output', type=Path, help='Write JSON to a new report file; default is stdout.')
    args = parser.parse_args(argv)
    report = evaluate(args.corpus, args.selected)
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        try:
            with args.output.open('x') as output:
                output.write(rendered)
        except OSError:
            report.update(status='blocked', full_acceptance=False, error='report_output_unavailable')
            print(json.dumps(report, sort_keys=True))
            return 2
    else:
        print(rendered, end='')
    return 0 if report['status'] == 'pass' and report['full_acceptance'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
