"""Behavioral controls for the static import guard; no runtime-effect claims."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[1] / 'scripts/check_architecture.py'
POLICY = 'docs/architecture-policy.json'
BASELINE = 'docs/architecture-baseline.json'


def exception(rule='external', source='app.py', target='sqlite3'):
    return dict(rule=rule, source=source, target=target, owner_issue=86,
                removal_milestone='86-first-uow', reason='Existing native dependency; migrate to a typed port.')


class Repository:
    def __init__(self, sources, roles, exceptions=()):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources, self.roles = sources, roles
        self.policy = dict(schema_version=1, roles=roles)
        self.baseline = dict(schema_version=1, exceptions=list(exceptions))
        for path, text in sources.items():
            self.write(path, text)
        self.save()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Authored test')
        self.git('config', 'user.email', 'authored@example.invalid')
        self.base = self.commit('accepted fixture base')

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def save(self):
        self.write(POLICY, json.dumps(self.policy))
        self.write(BASELINE, json.dumps(self.baseline))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              text=True, capture_output=True).stdout.strip()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-qm', message, '--allow-empty')
        return self.git('rev-parse', 'HEAD')

    def run(self, *args, base=None, tool=CHECKER):
        self.commit('candidate fixture')
        result = subprocess.run([sys.executable, str(tool), '--root', str(self.root),
                                 '--base-ref', base or self.base, '--format', 'json', *args],
                                text=True, capture_output=True)
        return result.returncode, json.loads(result.stdout)


class ArchitectureBoundaries(unittest.TestCase):
    def repo(self, *args, **kwargs):
        r = Repository(*args, **kwargs)
        self.addCleanup(r.temp.cleanup)
        return r

    def assert_cli(self, r, code=0, *args, **kwargs):
        actual, report = r.run(*args, **kwargs)
        self.assertEqual(actual, code, report)
        return report

    def test_allowed_roles_pure_imports_and_no_source_execution(self):
        sources = {
            'domain.py': 'from dataclasses import dataclass\nimport urllib.parse\nraise RuntimeError("must never execute")\n',
            'port.py': 'import domain\n', 'app.py': 'import domain, port\n',
            'adapter.py': 'import port, sqlite3\n', 'http_entry.py': 'import app\nimport starlette.responses\n',
            'bootstrap.py': 'import adapter, http_entry\n', 'support.py': 'import bootstrap\n',
        }
        roles = dict(zip(sources, ['domain', 'port', 'application', 'outbound', 'inbound', 'bootstrap', 'support']))
        self.assert_cli(self.repo(sources, roles), 0, '--strict')

    def test_direct_dependencies_nested_alias_and_type_checking(self):
        for source in ('import sqlite3 as db\n', 'def f():\n import sqlite3\n',
                       'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n from sqlite3 import Connection as C\n',
                       'import google.ads\n', 'from pathlib import Path\n'):
            with self.subTest(source=source):
                report = self.assert_cli(self.repo({'app.py': source}, {'app.py': 'application'}), 1)
                self.assertEqual(report['diagnostics'][0]['rule'], 'external')
                self.assertTrue(report['diagnostics'][0]['lines'])

    def test_relative_package_children_and_loaded_initializers(self):
        r = self.repo({'pkg/__init__.py': 'import sqlite3\n', 'pkg/adapter.py': 'pass\n',
                       'pkg/app.py': 'from . import adapter\n'},
                      {'pkg/__init__.py': 'outbound', 'pkg/adapter.py': 'outbound', 'pkg/app.py': 'application'})
        report = self.assert_cli(r, 1)
        targets = {row['target'] for row in report['diagnostics'] if row['rule'] == 'direction'}
        self.assertEqual(targets, {'pkg/__init__.py', 'pkg/adapter.py'})
        r.write('pkg/app.py', 'from .. import outside\n')
        self.assertIn('relative import escapes', self.assert_cli(r, 2)['error'])

    def test_symbol_import_does_not_invent_a_child_module(self):
        r = self.repo({'core.py': 'Value = 1\n', 'app.py': 'from core import Value\n'},
                      {'core.py': 'domain', 'app.py': 'application'})
        self.assert_cli(r, 0, '--strict')

    def test_compatibility_wrapper_direction_and_local_stdlib_shadow(self):
        r = self.repo({'app.py': 'import wrapper\n', 'wrapper.py': 'import adapter\n',
                       'adapter.py': 'pass\n'},
                      {'app.py': 'application', 'wrapper.py': 'application', 'adapter.py': 'outbound'})
        report = self.assert_cli(r, 1)
        self.assertEqual(report['diagnostics'][0]['source'], 'wrapper.py')
        r = self.repo({'app.py': 'import json\n', 'json.py': 'pass\n'},
                      {'app.py': 'application', 'json.py': 'outbound'})
        self.assertEqual(self.assert_cli(r, 1)['diagnostics'][0]['target'], 'json.py')

    def test_unclassified_missing_source_tests_and_markers(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.write('extra.py', 'pass\n')
        self.assertIn('unclassified=extra.py', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'import tests.helper\n', 'tests/helper.py': 'pass\n'}, {'app.py': 'application'})
        self.assertIn('runtime imports tests', self.assert_cli(r, 2)['error'])
        r = self.repo({'pkg/__init__.py': 'x = 1\n'}, {'pkg/__init__.py': 'marker'})
        self.assertIn('executable marker', self.assert_cli(r, 2)['error'])
        r = self.repo({'pkg/__init__.py': '"""Package marker."""\npass\n'}, {'pkg/__init__.py': 'marker'})
        self.assert_cli(r, 0, '--strict')
        (r.root / 'pkg/__init__.py').unlink()
        self.assertIn('missing=pkg/__init__.py', self.assert_cli(r, 2)['error'])

    def test_cycles_and_self_cycle_are_actionable(self):
        r = self.repo({'a.py': 'import b\n', 'b.py': 'import a\n'},
                      {'a.py': 'application', 'b.py': 'application'})
        report = self.assert_cli(r, 1)
        self.assertEqual({(d['source'], d['target']) for d in report['diagnostics']},
                         {('a.py', 'b.py'), ('b.py', 'a.py')})
        r = self.repo({'a.py': 'import a\n'}, {'a.py': 'application'})
        self.assertEqual(self.assert_cli(r, 1)['diagnostics'][0]['rule'], 'cycle')

    def test_existing_edge_waiver_allows_repetition_but_not_another_module(self):
        r = self.repo({'app.py': 'import sqlite3\n'}, {'app.py': 'application'}, [exception()])
        report = self.assert_cli(r, 0, '--details')
        self.assertEqual(report['active_debt'], 1)
        self.assertEqual(self.assert_cli(r, 1, '--strict')['diagnostics'][0]['target'], 'sqlite3')
        r.write('app.py', 'import sqlite3 as db\ndef f():\n from sqlite3 import Connection\n')
        self.assert_cli(r)
        r.write('app.py', 'import sqlite3\nimport random\n')
        self.assertEqual(self.assert_cli(r, 1)['diagnostics'][0]['target'], 'random')

    def test_two_committed_shrinks_use_each_accepted_predecessor(self):
        rows = [exception(), exception(target='random')]
        r = self.repo({'app.py': 'import sqlite3\nimport random\n'}, {'app.py': 'application'}, rows)
        r.write('app.py', 'import random\n'); r.baseline['exceptions'] = [rows[1]]; r.save()
        self.assert_cli(r)
        accepted_first = r.git('rev-parse', 'HEAD')
        r.write('app.py', 'pass\n'); r.baseline['exceptions'] = []; r.save()
        self.assert_cli(r, 0, '--strict', base=accepted_first)
        accepted_second = r.git('rev-parse', 'HEAD')
        r.write('app.py', 'import sqlite3\n'); r.baseline['exceptions'] = [rows[0]]; r.save()
        self.assertIn('growth', self.assert_cli(r, 2, base=accepted_second)['error'])
        # An old ancestor alone cannot establish cumulative retirement. CI must select current base.
        self.assert_cli(r, 0, base=r.base)

    def test_baseline_metadata_growth_and_stale_waivers(self):
        r = self.repo({'app.py': 'import sqlite3\n'}, {'app.py': 'application'}, [exception()])
        r.baseline['exceptions'][0]['reason'] = 'silently changed'; r.save()
        self.assertIn('metadata changed', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.baseline['exceptions'] = [exception()]; r.save()
        self.assertIn('growth', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'import sqlite3\n'}, {'app.py': 'application'}, [exception()])
        r.write('app.py', 'pass\n')
        self.assertIn('stale', self.assert_cli(r, 2)['error'])

    def test_missing_renamed_empty_config_and_role_relabel_fail(self):
        for path in (POLICY, BASELINE):
            with self.subTest(path=path):
                r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
                (r.root / path).rename(r.root / (path + '.old'))
                self.assert_cli(r, 2)
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.policy['roles']['app.py'] = 'outbound'; r.save()
        self.assertIn('role changed', self.assert_cli(r, 2)['error'])

    def test_duplicate_json_duplicate_edges_bad_owner_and_unknown_role(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.write(POLICY, '{"schema_version":1,"roles":{},"roles":{}}')
        self.assertIn('duplicate JSON', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'import sqlite3\n'}, {'app.py': 'application'}, [exception()])
        r.baseline['exceptions'] *= 2; r.save()
        self.assertIn('duplicate exception', self.assert_cli(r, 2)['error'])
        for field, value in [('owner_issue', True), ('removal_milestone', '85-core'), ('rule', 'magic')]:
            r = self.repo({'app.py': 'import sqlite3\n'}, {'app.py': 'application'}, [exception()])
            r.baseline['exceptions'][0][field] = value; r.save()
            self.assertIn('invalid exception', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'magical'})
        self.assertIn('invalid source role', self.assert_cli(r, 2)['error'])

    def test_missing_self_nonancestor_base_and_no_rebootstrap(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        head = r.commit('candidate')
        result = subprocess.run([sys.executable, str(CHECKER), '--root', str(r.root),
                                 '--base-ref', head, '--format', 'json'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('self', json.loads(result.stdout)['error'])
        self.assert_cli(r, 2, base='0' * 40)
        r.git('checkout', '--orphan', 'other'); r.commit('unrelated')
        self.assertIn('ancestor', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.git('rm', POLICY, BASELINE); bare = r.commit('no config')
        r.save()
        self.assertIn('initial seed requires exact', self.assert_cli(r, 2, base=bare)['error'])

    def test_symlink_and_syntax_rejected_without_execution(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.write('app.py', 'def broken(\n')
        self.assertIn('invalid Python', self.assert_cli(r, 2)['error'])
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        (r.root / 'app.py').unlink(); (r.root / 'app.py').symlink_to('/tmp/never-read-architecture')
        self.assertIn('symlink', self.assert_cli(r, 2)['error'])

    def test_bootstrap_cannot_import_tools_and_own_initializer_can_import_child(self):
        r = self.repo({'boot.py': 'import tool\n', 'tool.py': 'pass\n'},
                      {'boot.py': 'bootstrap', 'tool.py': 'developer_tool'})
        self.assertEqual(self.assert_cli(r, 1)['diagnostics'][0]['rule'], 'direction')
        for statement in ('from . import child\n', 'from pkg import child\n'):
            r = self.repo({'pkg/__init__.py': statement, 'pkg/child.py': 'pass\n'},
                          {'pkg/__init__.py': 'application', 'pkg/child.py': 'domain'})
            self.assert_cli(r, 0, '--strict')
        r = self.repo({'entry.py': 'import requests\n'}, {'entry.py': 'inbound'})
        self.assert_cli(r, 0, '--strict')

    def test_absolute_relative_self_imports_and_contextual_syntax_fail(self):
        for statement in ('from pkg.a import value\n', 'from .a import value\n'):
            r = self.repo({'pkg/a.py': statement}, {'pkg/a.py': 'application'})
            self.assertEqual(self.assert_cli(r, 1)['diagnostics'][0]['rule'], 'cycle')
        r = self.repo({'app.py': 'return 1\n'}, {'app.py': 'application'})
        self.assertIn('invalid Python source', self.assert_cli(r, 2)['error'])

    def test_regular_config_mode_and_fifo_are_rejected(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        (r.root / BASELINE).chmod(0o755)
        self.assertIn('mode 100644', self.assert_cli(r, 2)['error'])
        import os
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        (r.root / 'app.py').unlink()
        os.mkfifo(r.root / 'app.py')
        # Do not stage a FIFO; directly exercise the CLI and ensure it cannot block on a read.
        result = subprocess.run([sys.executable, str(CHECKER), '--root', str(r.root),
                                 '--base-ref', r.base, '--format', 'json'],
                                text=True, capture_output=True, timeout=5)
        # HEAD is currently the base; make an empty candidate before checking the file type.
        self.assertEqual(result.returncode, 2)
        r.git('commit', '--allow-empty', '-qm', 'candidate without staging FIFO')
        result = subprocess.run([sys.executable, str(CHECKER), '--root', str(r.root),
                                 '--base-ref', r.base, '--format', 'json'],
                                text=True, capture_output=True, timeout=5)
        self.assertIn('not a regular', json.loads(result.stdout)['error'])

    def test_one_time_seed_direct_and_synthetic_topology_and_staged_protection(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.git('rm', POLICY, BASELINE)
        seed_base = r.commit('accepted source-only seed fixture')
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        tool = Path(temp.name) / 'fixture-checker.py'
        text = CHECKER.read_text().replace(
            "INITIAL_BASE = '7c139e19bfbf0d829b31f8d09320e912e5561f6b'",
            "INITIAL_BASE = '" + seed_base + "'")
        tool.write_text(text)
        r.save(); first = r.commit('initial seed')
        def invoke(expected):
            result = subprocess.run([sys.executable, str(tool), '--root', str(r.root),
                                     '--base-ref', seed_base, '--format', 'json'],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return json.loads(result.stdout)
        invoke(0)
        r.write('app.py', 'import sqlite3\n'); r.git('add', 'app.py'); r.write('app.py', 'pass\n')
        self.assertIn('clean committed', invoke(2)['error'])
        r.git('reset', '--hard', first)
        r.write('app.py', 'pass # protected change\n'); r.commit('protected modification')
        invoke(2)
        r.git('reset', '--hard', first)
        r.baseline['exceptions'] = [exception()]; r.write('app.py', 'import sqlite3\n'); r.save()
        replay = r.commit('later seed replay')
        invoke(2)
        tree = r.git('rev-parse', first + '^{tree}')
        synthetic = r.git('commit-tree', tree, '-p', seed_base, '-p', first, '-m', 'authored synthetic')
        r.git('reset', '--hard', synthetic); invoke(0)
        forged = r.git('commit-tree', tree, '-p', seed_base, '-p', replay, '-m', 'feature-side replay')
        r.git('reset', '--hard', forged); invoke(2)
        r.git('reset', '--hard', first); r.write('app.py', 'pass # changed merge tree\n')
        r.git('add', '-A'); changed_tree = r.git('write-tree')
        forged = r.git('commit-tree', changed_tree, '-p', seed_base, '-p', first, '-m', 'changed merge tree')
        r.git('reset', '--hard', forged); invoke(2)

    def test_only_named_provider_launchers_can_transition_to_bootstrap(self):
        launchers = {
            'campaign_agent/agent/__main__.py': 'inbound',
            'campaign_agent/hosted.py': 'application',
            'scripts/placement_review.py': 'inbound',
        }
        for path, role in launchers.items():
            with self.subTest(path=path):
                r = self.repo({path: 'pass\n', 'wire.py': 'pass\n'}, {path: role, 'wire.py': 'bootstrap'})
                r.policy['roles'][path] = 'bootstrap'
                r.write(path, 'import wire\n')
                r.save()
                self.assert_cli(r, 0, '--strict')

    def test_launcher_transition_does_not_allow_core_to_import_bootstrap(self):
        launcher = 'campaign_agent/hosted.py'
        r = self.repo({launcher: 'pass\n', 'app.py': 'import campaign_agent.hosted\n'},
                      {launcher: 'application', 'app.py': 'application'})
        r.policy['roles'][launcher] = 'bootstrap'
        r.save()
        self.assert_cli(r, 1)

    def test_launcher_permission_cannot_be_used_from_a_different_role(self):
        launcher = 'scripts/placement_review.py'
        r = self.repo({launcher: 'pass\n'}, {launcher: 'application'})
        r.policy['roles'][launcher] = 'bootstrap'
        r.save()
        self.assertIn('role changed', self.assert_cli(r, 2)['error'])

    def test_campaign_debt_transfer_is_exact_and_one_time(self):
        import hashlib
        old = 'scripts/campaign_drafts.py'
        new = 'campaign_agent/application/campaigns.py'
        before = ("from pathlib import Path\nimport sqlite3\nfrom uuid import uuid4\n"
                  "from campaign_agent.adapters import local_access, sqlite_drafts\n"
                  "DEFAULT_DRAFT_PATH = Path(__file__).resolve().parents[1] / \".local/campaign-drafts.sqlite3\"\n"
                  "class CampaignDrafts: pass\n")
        adapter_a = 'campaign_agent/adapters/local_access.py'
        adapter_b = 'campaign_agent/adapters/sqlite_drafts.py'
        edges = [('direction', adapter_a), ('direction', adapter_b),
                 ('external', 'pathlib'), ('external', 'sqlite3'), ('external', 'uuid')]
        roles = {old: 'application', adapter_a: 'outbound', adapter_b: 'outbound'}
        for scenario in ('valid', 'changed_body', 'wrong_role', 'partial', 'changed_metadata',
                         'extra_exception', 'old_edge_remains', 'wrong_mode', 'untrusted_original', 'changed_line_endings', 'staged_modified'):
            with self.subTest(scenario=scenario):
                rows = [exception(rule=rule, source=old, target=target) for rule, target in edges]
                r = self.repo({old: before, adapter_a: 'pass\n', adapter_b: 'pass\n'}, roles.copy(), rows)
                # A disposable authored vector exercises the production gate with its own pinned source.
                temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
                tool = Path(temp.name) / 'checker.py'
                original_pin = '4b04b7b29ad01f3d48156df252d3bec30fff75864e1a159a8024a3ccd79d1be3'
                pin = hashlib.sha256(before.encode()).hexdigest()
                tool.write_text(CHECKER.read_text().replace(original_pin, ('0' * 64 if scenario == 'untrusted_original' else pin)))
                r.write(new, before.replace('parents[1]', 'parents[2]'))
                r.write(old, 'from campaign_agent.application.campaigns import CampaignDrafts\n')
                r.policy['roles'][new] = 'application'
                r.baseline['exceptions'] = [{**row, 'source': new} for row in rows]
                if scenario == 'changed_body': r.write(new, before.replace('parents[1]', 'parents[2]') + 'x = 1\n')
                if scenario == 'wrong_role': r.policy['roles'][new] = 'bootstrap'
                if scenario == 'partial': r.baseline['exceptions'][0] = rows[0]
                if scenario == 'changed_metadata': r.baseline['exceptions'][0]['owner_issue'] = 88; r.baseline['exceptions'][0]['removal_milestone'] = '88-composition'
                if scenario == 'extra_exception': r.baseline['exceptions'].append(exception(source=new, target='socket'))
                if scenario == 'old_edge_remains': r.write(old, before)
                if scenario == 'wrong_mode': (r.root / new).chmod(0o755)
                if scenario == 'changed_line_endings': (r.root / new).write_bytes(before.replace('parents[1]', 'parents[2]').replace('\n', '\r\n').encode())
                r.save()
                if scenario == 'staged_modified':
                    r.git('add', '-A'); r.git('commit', '-qm', 'candidate')
                    r.write(new, before.replace('parents[1]', 'parents[2]') + 'x = 1\n')
                    r.git('add', new)
                    r.write(new, before.replace('parents[1]', 'parents[2]'))
                    result = subprocess.run([sys.executable, str(tool), '--root', str(r.root),
                                             '--base-ref', r.base, '--format', 'json'],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn('staged campaign transfer', json.loads(result.stdout)['error'])
                    continue
                if scenario == 'valid':
                    self.assert_cli(r, 0, tool=tool)
                    # On later changes the normal subset rule applies without freezing the moved file.
                    accepted = r.git('rev-parse', 'HEAD')
                    r.write(new, before.replace('parents[1]', 'parents[2]') + '\n# harmless later edit\n')
                    self.assert_cli(r, 0, base=accepted, tool=tool)
                    self.assert_cli(r, 1, '--strict', base=accepted, tool=tool)
                else:
                    code, _ = r.run(tool=tool)
                    self.assertNotEqual(code, 0)

    def test_trusted_checker_catches_a_weakened_candidate(self):
        r = self.repo({'app.py': 'pass\n'}, {'app.py': 'application'})
        r.write('app.py', 'import sqlite3\n')
        r.write('scripts/check_architecture.py', 'raise SystemExit(0)\n')
        r.policy['roles']['scripts/check_architecture.py'] = 'developer_tool'; r.save()
        # Mirrors CI extraction: this trusted executable is independent of candidate file contents.
        self.assert_cli(r, 1, tool=CHECKER)


if __name__ == '__main__':
    unittest.main()
