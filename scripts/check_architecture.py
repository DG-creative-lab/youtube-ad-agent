#!/usr/bin/env python3
"""Offline Python import/layer guard. No call, value or runtime-effect analysis."""
from __future__ import annotations

import argparse
import hashlib
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

POLICY = 'docs/architecture-policy.json'
BASELINE = 'docs/architecture-baseline.json'
INITIAL_BASE = '7c139e19bfbf0d829b31f8d09320e912e5561f6b'
OWNED = {
    'scripts/check_architecture.py', 'tests/test_architecture_boundaries.py',
    POLICY, BASELINE, '.github/workflows/checks.yml', 'AGENTS.md',
    'docs/hexagonal-architecture.md', 'docs/architecture-plan.md',
    'docs/engineering-workflow.md', 'docs/build-plan.md', 'docs/source-map.md',
    'docs/factory/launch.md',
}
DIRECTIONS = {
    'domain': {'domain', 'marker'},
    'port': {'domain', 'port', 'marker'},
    'application': {'domain', 'application', 'port', 'marker'},
    'outbound': {'domain', 'port', 'outbound', 'marker'},
    'inbound': {'domain', 'application', 'port', 'marker'},
    'bootstrap': {'domain', 'application', 'port', 'inbound', 'outbound', 'bootstrap', 'marker'},
}
ROLES = set(DIRECTIONS) | {'bootstrap', 'support', 'developer_tool', 'marker'}
CORE = {'domain', 'application', 'port'}
# Import permission only: datetime.now(), for example, is NOT proven pure.
CORE_EXTERNAL = {
    '__future__', 'abc', 'bisect', 'collections', 'contextlib', 'copy', 'csv',
    'dataclasses', 'datetime', 'decimal', 'enum', 'fractions', 'functools',
    'hashlib', 'heapq', 'hmac', 'html', 'io', 'itertools', 'json', 'math',
    'operator', 're', 'statistics', 'string', 'struct', 'types', 'typing',
    'unicodedata', 'urllib.parse',
}
INBOUND_DENIED = {'sqlite3'}

# One reviewed relocation. The base remains responsible for authorizing debt.
CAMPAIGN_OLD = 'scripts/campaign_drafts.py'
CAMPAIGN_NEW = 'campaign_agent/application/campaigns.py'
CAMPAIGN_SOURCE_SHA256 = '4b04b7b29ad01f3d48156df252d3bec30fff75864e1a159a8024a3ccd79d1be3'
CAMPAIGN_EDGES = {('direction', 'campaign_agent/adapters/local_access.py'),
                  ('direction', 'campaign_agent/adapters/sqlite_drafts.py'),
                  ('external', 'pathlib'), ('external', 'sqlite3'), ('external', 'uuid')}
CAMPAIGN_DEFAULT = 'DEFAULT_DRAFT_PATH = Path(__file__).resolve().parents[1] / ".local/campaign-drafts.sqlite3"'


class ArchitectureError(Exception):
    """Invalid configuration, source or selected Git base."""


def require(condition, message):
    if not condition:
        raise ArchitectureError(message)


def git(root, *args, check=True):
    result = subprocess.run(['git', '-C', str(root), *args], text=True,
                            capture_output=True)
    if check:
        require(result.returncode == 0, 'Git failed: ' + ' '.join(args[:2]))
    return result.stdout if result.returncode == 0 else None


def unique_keys(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def parse_json(text):
    try:
        return json.loads(text, object_pairs_hook=unique_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ArchitectureError('nonfinite JSON value')))
    except (ValueError, RecursionError) as exc:
        raise ArchitectureError('invalid JSON') from exc


def safe_path(path):
    return (isinstance(path, str) and bool(path) and '\\' not in path
            and not path.startswith('/')
            and all(part not in {'', '.', '..'} for part in path.split('/')))


class Tree:
    def __init__(self, root, ref=None):
        self.root, self.ref = Path(root).resolve(), ref
        self.paths = set(git(root, 'ls-tree', '-r', '--name-only', ref).splitlines()
                         if ref else git(root, 'ls-files', '--cached', '--others',
                                         '--exclude-standard').splitlines())

    def text(self, path):
        require(safe_path(path) and path in self.paths, 'missing/unsafe path: ' + str(path))
        if self.ref:
            entry = git(self.root, 'ls-tree', self.ref, '--', path).split()
            require(entry[:2] in (['100644', 'blob'], ['100755', 'blob'])
                    and (path not in {POLICY, BASELINE} or entry[0] == '100644'),
                    'not a regular Git source/config blob: ' + path)
            return git(self.root, 'show', self.ref + ':' + path)
        target = self.root / path
        require(not any(parent.is_symlink() for parent in [target, *target.parents]
                        if parent != self.root.parent), 'symlink source/config: ' + path)
        require(target.is_file(), 'not a regular source/config file: ' + path)
        staged = git(self.root, 'ls-files', '--stage', '--', path).split()
        require(not staged or staged[0] in {'100644', '100755'}, 'invalid index source/config mode: ' + path)
        if path in {POLICY, BASELINE}:
            require(not target.stat().st_mode & 0o111 and (not staged or staged[0] == '100644'),
                    'config must have mode 100644: ' + path)
        try:
            return target.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            raise ArchitectureError('unreadable UTF-8 source/config: ' + path) from exc


def read_pair(tree):
    p, b = parse_json(tree.text(POLICY)), parse_json(tree.text(BASELINE))
    require(isinstance(p, dict) and set(p) == {'schema_version', 'roles'}
            and type(p['schema_version']) is int and p['schema_version'] == 1,
            'invalid policy schema')
    require(isinstance(p['roles'], dict), 'roles must be an object')
    for path, role in p['roles'].items():
        require(safe_path(path) and path.endswith('.py') and not path.startswith('tests/')
                and isinstance(role, str) and role in ROLES,
                'invalid source role: ' + str(path))
    require(isinstance(b, dict) and set(b) == {'schema_version', 'exceptions'}
            and type(b['schema_version']) is int and b['schema_version'] == 1
            and isinstance(b['exceptions'], list), 'invalid baseline schema')
    rows = {}
    for row in b['exceptions']:
        require(isinstance(row, dict) and set(row) == {
            'rule', 'source', 'target', 'owner_issue', 'removal_milestone', 'reason'},
            'invalid exception fields')
        require(isinstance(row['rule'], str) and row['rule'] in {'external', 'direction', 'cycle'}
                and safe_path(row['source']) and row['source'].endswith('.py')
                and isinstance(row['target'], str) and bool(row['target'])
                and type(row['owner_issue']) is int and row['owner_issue'] > 0
                and isinstance(row['removal_milestone'], str)
                and re.fullmatch(str(row['owner_issue']) + r'-[a-z][a-z0-9-]*', row['removal_milestone'])
                and isinstance(row['reason'], str) and bool(row['reason'].strip()),
                'invalid exception metadata')
        key = (row['rule'], row['source'], row['target'])
        require(key not in rows, 'duplicate exception edge: ' + str(key))
        rows[key] = row
    return p, rows


def module_name(path):
    return path[:-3].replace('/', '.').removesuffix('.__init__')


def matches(module, prefixes):
    return any(module == prefix or module.startswith(prefix + '.') for prefix in prefixes)


def analyze(tree, policy):
    sources = {path for path in tree.paths if path.endswith('.py') and not path.startswith('tests/')}
    roles = policy['roles']
    require(sources == set(roles), 'source classification mismatch; unclassified=' +
            ','.join(sorted(sources - set(roles))) + '; missing=' + ','.join(sorted(set(roles) - sources)))
    modules = {module_name(path): path for path in sources}
    require(len(modules) == len(sources), 'ambiguous module/package source names')
    namespaces = {name.rsplit('.', n)[0] for name in modules for n in range(1, name.count('.') + 1)}
    edges, facts = {}, {}

    def fact(rule, path, target, line):
        facts.setdefault((rule, path, target), set()).add(line)

    def dependency(path, target, line, from_import=False):
        # Tests are deliberately excluded consumers, never runtime dependencies.
        require(not (target == 'tests' or target.startswith('tests.')), 'runtime imports tests: ' + path)
        local_root = target.split('.')[0] in modules or target.split('.')[0] in namespaces
        if target in modules or target in namespaces or local_root:
            require(target in modules or target in namespaces, 'unresolved project import: ' + target)
            loaded = [modules[name] for name in modules
                      if name == target or (target.startswith(name + '.')
                                           and modules[name].endswith('/__init__.py'))]
            for destination in loaded:
                if destination == path:
                    # Implicit loading of one's own package is not an import cycle.
                    if module_name(path) != target or from_import:
                        continue
                edges.setdefault((path, destination), set()).add(line)
                permitted = DIRECTIONS.get(roles[path])
                if permitted is not None and roles[destination] not in permitted:
                    fact('direction', path, destination, line)
            return
        if roles[path] in CORE and not matches(target, CORE_EXTERNAL):
            fact('external', path, target, line)
        if roles[path] == 'inbound' and matches(target, INBOUND_DENIED):
            fact('external', path, target, line)

    for path in sorted(sources):
        try:
            source = ast.parse(tree.text(path), filename=path)
            compile(source, path, 'exec')  # Validate contextual syntax; never execute.
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise ArchitectureError('invalid Python source: ' + path) from exc
        if roles[path] == 'marker':
            require(all(isinstance(node, ast.Pass) or
                        (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                         and isinstance(node.value.value, str)) or
                        (isinstance(node, ast.ImportFrom) and node.module == '__future__' and not node.level)
                        for node in source.body), 'executable marker initializer: ' + path)
        for node in ast.walk(source):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependency(path, alias.name, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = module_name(path).split('.')
                    if not path.endswith('/__init__.py'):
                        package.pop()
                    require(node.level <= len(package), 'relative import escapes project: ' + path)
                    base = '.'.join(package[:len(package) - node.level + 1])
                    target = base + ('.' + node.module if node.module else '')
                else:
                    target = node.module or ''
                require(bool(target), 'empty import module: ' + path)
                implicit_parent = (path.endswith('/__init__.py') and any(
                    target + '.' + alias.name in modules or target + '.' + alias.name in namespaces
                    for alias in node.names))
                dependency(path, target, node.lineno, from_import=implicit_parent)
                for alias in node.names:
                    child = target + '.' + alias.name
                    if child in modules or child in namespaces:
                        dependency(path, child, node.lineno)

    # Tarjan's SCC algorithm; record cyclic edges rather than unstable cycle paths.
    graph = {path: set() for path in sources}
    for start, end in edges:
        graph[start].add(end)
    index, low, stack, active, components = {}, {}, [], set(), []

    def visit(start):
        index[start] = low[start] = len(index)
        stack.append(start)
        active.add(start)
        for end in sorted(graph[start]):
            if end not in index:
                visit(end)
                low[start] = min(low[start], low[end])
            elif end in active:
                low[start] = min(low[start], index[end])
        if low[start] == index[start]:
            component = set()
            while True:
                end = stack.pop()
                active.remove(end)
                component.add(end)
                if end == start:
                    break
            components.append(component)

    for path in sorted(graph):
        if path not in index:
            visit(path)
    component_of = {path: component for component in components for path in component}
    for (start, end), lines in edges.items():
        if component_of[start] is component_of[end] and (start == end or len(component_of[start]) > 1):
            for line in lines:
                fact('cycle', start, end, line)
    return facts, edges


def initial_seed_guard(current, base):
    require(base.ref == INITIAL_BASE, 'initial seed requires exact accepted base ' + INITIAL_BASE)
    require(git(current.root, 'diff', '--quiet', check=False) is not None
            and git(current.root, 'diff', '--cached', '--quiet', check=False) is not None,
            'initial seed requires clean committed index and worktree')
    parents = git(current.root, 'show', '-s', '--format=%P', 'HEAD').split()
    direct = parents == [base.ref]
    synthetic = (len(parents) == 2 and parents[0] == base.ref
                 and git(current.root, 'show', '-s', '--format=%P', parents[1]).split() == [base.ref]
                 and git(current.root, 'rev-parse', 'HEAD^{tree}') ==
                 git(current.root, 'rev-parse', parents[1] + '^{tree}'))
    require(direct or synthetic,
            'initial seed requires one direct-base commit or its identical-tree synthetic merge')
    require(current.paths - base.paths <= OWNED, 'initial seed adds protected paths')
    require(base.paths - current.paths <= OWNED, 'initial seed deletes protected paths')
    changed = set(git(current.root, 'diff', '--name-only', base.ref, '--').splitlines())
    require(changed <= OWNED, 'initial seed changes protected paths: ' + ','.join(sorted(changed - OWNED)))


def check_campaign_transfer(base, current, old_policy, policy, old_rows, rows, added):
    """Allow this exact source move; all other new exception keys remain forbidden."""
    old_keys = {(rule, CAMPAIGN_OLD, target) for rule, target in CAMPAIGN_EDGES}
    new_keys = {(rule, CAMPAIGN_NEW, target) for rule, target in CAMPAIGN_EDGES}
    require(added == new_keys and old_keys <= old_rows.keys() and not old_keys & rows.keys(),
            'baseline exception growth: invalid campaign transfer')
    require(old_policy['roles'].get(CAMPAIGN_OLD) == 'application'
            and policy['roles'].get(CAMPAIGN_OLD) == 'application'
            and policy['roles'].get(CAMPAIGN_NEW) == 'application'
            and CAMPAIGN_NEW not in base.paths, 'invalid campaign transfer roles')
    base.text(CAMPAIGN_OLD)  # Validate the trusted source is a regular Git blob.
    original = subprocess.run(['git', '-C', str(base.root), 'show', base.ref + ':' + CAMPAIGN_OLD],
                              capture_output=True, check=True).stdout
    anchor = CAMPAIGN_DEFAULT.encode('utf-8')
    require(hashlib.sha256(original).hexdigest() == CAMPAIGN_SOURCE_SHA256
            and original.count(anchor) == 1, 'invalid trusted campaign source')
    expected = original.replace(anchor, anchor.replace(b'parents[1]', b'parents[2]'), 1)
    current.text(CAMPAIGN_NEW)  # Validate the destination is a regular, non-symlink file.
    require((current.root / CAMPAIGN_NEW).read_bytes() == expected,
            'campaign transfer must preserve implementation bytes')
    mode = git(current.root, 'ls-files', '--stage', '--', CAMPAIGN_NEW).split()
    require(mode and mode[0] == '100644' and not (current.root / CAMPAIGN_NEW).stat().st_mode & 0o111,
            'invalid campaign transfer file mode')
    staged = subprocess.run(['git', '-C', str(current.root), 'show', ':' + CAMPAIGN_NEW],
                            capture_output=True, check=True).stdout
    require(staged == expected, 'staged campaign transfer bytes differ')
    for rule, target in CAMPAIGN_EDGES:
        old_key, new_key = (rule, CAMPAIGN_OLD, target), (rule, CAMPAIGN_NEW, target)
        require(rows[new_key] == {**old_rows[old_key], 'source': CAMPAIGN_NEW},
                'campaign transfer metadata changed')
    return old_keys, new_keys


def check(root, base_ref, strict=False, details=False):
    require(re.fullmatch(r'[0-9a-f]{40}', base_ref or '') is not None, '--base-ref requires a full commit SHA')
    require(git(root, 'cat-file', '-t', base_ref) == 'commit\n', 'base is not a commit')
    require(git(root, 'rev-parse', 'HEAD').strip() != base_ref, 'base cannot be candidate HEAD/self')
    require(git(root, 'merge-base', '--is-ancestor', base_ref, 'HEAD', check=False) is not None,
            'base must be an available ancestor')
    current, base = Tree(root), Tree(root, base_ref)
    policy, exceptions = read_pair(current)
    base_has = {name for name in (POLICY, BASELINE) if name in base.paths}
    transferred = None
    if not base_has:
        initial_seed_guard(current, base)
    else:
        require(base_has == {POLICY, BASELINE}, 'trusted base has incomplete config pair')
        old_policy, old_exceptions = read_pair(base)
        for path, role in old_policy['roles'].items():
            if path in current.paths:
                require(policy['roles'].get(path) == role, 'surviving source role changed: ' + path)
        added = exceptions.keys() - old_exceptions.keys()
        if added:
            transferred = check_campaign_transfer(base, current, old_policy, policy, old_exceptions, exceptions, added)
        require(all(row == old_exceptions[key] for key, row in exceptions.items() if key in old_exceptions),
                'exception metadata changed')
    facts, edges = analyze(current, policy)
    if transferred:
        old_keys, new_keys = transferred
        require(not old_keys & facts.keys() and new_keys <= facts.keys(), 'campaign transfer edges do not match source')
    stale = exceptions.keys() - facts.keys()
    require(not stale, 'stale exceptions must be removed: ' + str(sorted(stale)))
    violations = facts.keys() if strict else facts.keys() - exceptions.keys()
    diagnostics = [dict(rule=rule, source=source, target=target, lines=sorted(facts[(rule, source, target)]))
                   for rule, source, target in sorted(violations)]
    report = {'status': 'failed' if diagnostics else 'passed',
              'python_modules': len(policy['roles']), 'import_edges': len(edges),
              'active_debt': len(exceptions), 'diagnostics': diagnostics,
              'base_ref': base_ref, 'enforcement': 'static-python-imports-only'}
    if details:
        report['exceptions'] = [dict(row, lines=sorted(facts[key])) for key, row in sorted(exceptions.items())]
    return (1 if diagnostics else 0), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--base-ref', required=True, help='current accepted integration base, full SHA')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--format', choices=['text', 'json'], default='text')
    parser.add_argument('--details', action='store_true')
    args = parser.parse_args(argv)
    try:
        code, report = check(Path(args.root), args.base_ref, args.strict, args.details)
    except (ArchitectureError, OSError, UnicodeError, RecursionError) as exc:
        code, report = 2, {'status': 'invalid', 'error': str(exc)}
    if args.format == 'json':
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print('architecture:', report['status'])
        if code == 2:
            print(report['error'])
        else:
            print(f"{report['python_modules']} Python modules; {report['active_debt']} reviewed module-edge exceptions")
            for row in report['diagnostics']:
                print(f"{row['source']}:{','.join(map(str, row['lines']))}: {row['rule']} -> {row['target']}")
    return code


if __name__ == '__main__':
    sys.exit(main())
