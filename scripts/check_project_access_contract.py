#!/usr/bin/env python3
"""Offline artifact consistency checks. Never issues an execution permit.

Only the proposed profile, authored vectors and unchanged pinned local wire schema
are inputs. No service, storage, transport adapter or executable oracle is loaded.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / 'campaign_agent/contracts/youtube-project-v1.json'
FIXTURE_PATH = ROOT / 'examples/project-access-contract.v1.json'
WIRE_PATH = ROOT / 'campaign_agent/contracts/gateplane-v1.json'
PROFILE_SHA256 = '6662515e3ba653d113c4caf888277ba478150a5f15cf6f7cefdfb15dc20a9bb5'
WIRE_BLOB = '9bfc7650019f5fe9cb852cbcba088557e01366fd'
MAX_BYTES, MAX_INTEGER = 262144, 9007199254740991
POSITIVES = {'create-unicode': 'create', 'create-decomposed': 'create', 'list': 'list',
             'shared-resource-read': 'resource.read', 'recover-campaign': 'recover-campaign'}
# These fixed paths are data replacements, not an extensible mutation language.
NEGATIVES = {
    'wrong-owner': ('shared-resource-read', ['native_state', 'owner', 'brand_id'], 'binding_rejected'),
    'workspace-target-substitution': ('create-unicode', ['request', 'target', 'type'], 'binding_rejected'),
    'changed-input-hash': ('create-unicode', ['request', 'input_hash'], 'binding_rejected'),
    'changed-subject-hash': ('list', ['result', 'subject_hash'], 'binding_rejected'),
    'changed-native-hash': ('shared-resource-read', ['request', 'facts', 'attributes', 'youtube:native_state_hash'], 'binding_rejected'),
    'wrong-incarnation': ('shared-resource-read', ['native_state', 'store_incarnation'], 'binding_rejected'),
    'expired-wall': ('list', ['verification', 'wall_now'], 'binding_rejected'),
    'expired-monotonic': ('list', ['verification', 'monotonic_now_ms'], 'binding_rejected'),
    'unsupported-obligation': ('shared-resource-read', ['result', 'obligations'], 'binding_rejected'),
    'nonallow-no-authority': ('list', ['result'], 'binding_rejected'),
    'unknown-action': ('list', ['command', 'action'], 'schema_rejected'),
    'unknown-attribute': ('list', ['request', 'facts', 'attributes'], 'schema_rejected'),
    'counter-overflow': ('shared-resource-read', ['native_state', 'project_revision'], 'schema_rejected'),
}
GOLDEN_HASHES = {'create-unicode': {'input_hash': 'sha256:d47e195886fde497766daedfe908f2ee4010066cbc3d7d3b5e237e733650e337',
                    'native_state_hash': 'sha256:d7d4d4dfda44ce7aecdeee4468e0ef2f95a54d90a51f1c22a096e9d357189e4e',
                    'subject_hash': 'sha256:ca02b074677342b65ed6108ad2d4b70961ba966b145fb6abb05124c690501092'},
 'create-decomposed': {'input_hash': 'sha256:a58432e07a7b0c8d7e0637cddcaee03df214dde25ebe5a61be629f47e2f540c1',
                       'native_state_hash': 'sha256:d7d4d4dfda44ce7aecdeee4468e0ef2f95a54d90a51f1c22a096e9d357189e4e',
                       'subject_hash': 'sha256:a49f95d9de75a4a19e432698f7153d52c526f7c29ee230ab62d4d9ffbd0b0f23'},
 'list': {'input_hash': 'sha256:593ca34307c89dd9373ab783fbb37834295b06c08c1fc67b9cd00050e2a4693a',
          'native_state_hash': 'sha256:2b661653d26ca9dd7360757caac6589651c513508c0d8427ada2203f3f547baf',
          'subject_hash': 'sha256:c7bb18c15e87748e07b9717dec42966d7502def105c00a067c34fd99332fb4bd'},
 'shared-resource-read': {'input_hash': 'sha256:e7e06b71a9f26ce29498e434e8c9b8b0531561363ceee914a6165677f9722ed5',
                          'native_state_hash': 'sha256:394bb98a6b34a315a4be74ef8fd383aefe72f304eb8497d0d364832ee9ed0ea7',
                          'subject_hash': 'sha256:92f5d23ea504455f8bc314cb6e2148d259bd360b0dcc4ee6dd72cfbe1cf66c4a'},
 'recover-campaign': {'input_hash': 'sha256:03f20aa9af51834a4675171a0b9e23cf81f58cb505c84a5af589259b6eb24d60',
                      'native_state_hash': 'sha256:ce50e181ad570af12a4057ce792bb7f349cd84d32770e1423656cbf7d7ffe42f',
                      'subject_hash': 'sha256:cd0518264e0f4e371f48a24063e1f03b4c0761cb0e9a8d3d14fa3ff764010fb4'}}
NATIVE_PACKAGE_FINGERPRINT = 'd6f7083aa51b545378bd240346de14e30cb09e5c691505d9148c1ee6aa6ea5dc'
COUNTERS = {'workspace_revision', 'project_revision', 'security_epoch', 'intent_revision',
            'campaign_revision', 'resource_revision', 'projection_version', 'disclosure_revision',
            'expected_revision', 'expected_campaign_revision'}


class ContractError(ValueError):
    def __init__(self, category, message):
        self.category = category
        super().__init__(f'{category}: {message}')


def require(condition, message, category='binding_rejected'):
    if not condition:
        raise ContractError(category, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _bounded_integer(raw):
    require(len(raw) <= 17 and abs(int(raw)) <= MAX_INTEGER, 'integer bound', 'schema_rejected')
    return int(raw)


def _no_float(raw):
    raise ContractError('schema_rejected', 'floats and nonfinite numbers are unsupported')


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate object key', 'schema_rejected')
        result[key] = value
    return result


def _walk(value, depth=0):
    require(depth <= 32, 'nesting bound', 'schema_rejected')
    if isinstance(value, str):
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ContractError('schema_rejected', 'invalid Unicode scalar') from None
    elif isinstance(value, list):
        for item in value:
            _walk(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(key, depth + 1)
            _walk(item, depth + 1)


def parse(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'input byte bound', 'schema_rejected')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_int=_bounded_integer, parse_float=_no_float, parse_constant=_no_float)
        _walk(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ContractError('schema_rejected', 'malformed UTF-8 JSON') from None


def load(path):
    with Path(path).open('rb') as stream:
        return parse(stream.read(MAX_BYTES + 1))


def closed(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields), 'unknown or missing fields', 'schema_rejected')


def validate(schema, value):
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (ValidationError, TypeError):
        raise ContractError('schema_rejected', 'record does not match closed schema') from None


def local_refs(value):
    if isinstance(value, dict):
        require('$dynamicRef' not in value, 'dynamic schema loading forbidden', 'schema_rejected')
        if '$ref' in value:
            require(isinstance(value['$ref'], str) and value['$ref'].startswith('#/'), 'remote schema loading forbidden', 'schema_rejected')
        for item in value.values():
            local_refs(item)
    elif isinstance(value, list):
        for item in value:
            local_refs(item)


def profile_and_wire(profile_path):
    profile = load(profile_path)
    local_refs(profile)
    require(hashlib.sha256(canonical(profile)).hexdigest() == PROFILE_SHA256,
            'profile differs from frozen v1; reviewed version update required', 'schema_rejected')
    raw = WIRE_PATH.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    require(blob == WIRE_BLOB, 'pinned producer schema changed', 'schema_rejected')
    wire = parse(raw)
    local_refs(wire)
    return profile, wire


def encoded_fields(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in COUNTERS and item is not None:
                require(isinstance(item, str) and item.isascii() and item.isdecimal()
                        and not item.startswith('0') and 1 <= int(item) <= MAX_INTEGER,
                        'positive decimal counter bound', 'schema_rejected')
            if key == 'name':
                require(isinstance(item, str) and 1 <= len(item) <= 120
                        and len(item.encode('utf-8')) <= 480
                        and not any(unicodedata.category(char) == 'Cc' for char in item),
                        'name bound/control character', 'schema_rejected')
            if key in {'intents', 'resource_refs'}:
                require(item == sorted(set(item)), 'references/intents must be sorted unique', 'schema_rejected')
            encoded_fields(item)
    elif isinstance(value, list):
        for item in value:
            encoded_fields(item)


def golden(value, literal, expected):
    raw = canonical(value)
    # Compare a second implementation already used by the campaign consumer.
    from campaign_agent.adapters.gateplane import canonical as native_canonical
    require(raw == native_canonical(value) == literal.encode('utf-8'), 'literal canonical UTF-8 differs')
    require('sha256:' + hashlib.sha256(literal.encode('utf-8')).hexdigest() == expected,
            'literal golden digest differs')
    return expected


def seconds(value):
    try:
        return int(datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        raise ContractError('schema_rejected', 'invalid fixed clock') from None


def check_vector(v, profile, wire):
    closed(v, ['id', 'verified_context', 'command', 'reservation', 'native_state', 'request', 'result', 'verification', 'golden'])
    c, n, q, r, x, g = (v[k] for k in ['command', 'native_state', 'request', 'result', 'verified_context', 'golden'])
    require(v['id'] in POSITIVES, 'unknown positive ID', 'schema_rejected')
    require(isinstance(c, dict) and c.get('action') == POSITIVES[v['id']], 'unknown/wrong fixture action', 'schema_rejected')
    validate(profile['command_schemas'][c['action']], c)
    validate(profile['reservation_schema'], v['reservation'])
    validate(profile['native_state_schema'], n)
    encoded_fields(c); encoded_fields(n)
    closed(x, ['application_id', 'installation_id', 'tenant_id', 'brand_id', 'workspace_id', 'actor', 'session_id', 'external_identity'])
    for name, record in [('DecisionRequest', q), ('DecisionResult', r), ('Actor', x['actor'])]:
        validate({**wire, '$ref': '#/$defs/' + name}, record)
    validate(profile['native_state_schema']['properties']['owner'], {
        'client_id': x['tenant_id'], **{k: x[k] for k in ['brand_id', 'workspace_id', 'installation_id']}})
    validate(profile['reservation_schema']['anyOf'][0]['properties']['initial_manager_subject'], x['external_identity'])
    require(x['actor']['kind'] == 'human' and x['actor']['delegator_id'] is None
            and x['actor']['grant_id'] is None and x['actor']['principal_id'] == x['external_identity']['principal_id'], 'verified human binding')
    validate(profile['native_state_schema']['properties']['owner']['properties']['workspace_id'], x['session_id'])
    require(n['owner'] == {'client_id': x['tenant_id'], **{k: x[k] for k in ['brand_id', 'workspace_id', 'installation_id']}}, 'full native owner differs')
    row = next(row for row in profile['actions'] if c['action'] in row['actions'])
    tid = n['owner']['workspace_id'] if row['target_type'] == 'workspace' else n[row['target_id_field']]
    require(n['action'] == c['action'] and n['target'] == q['target'] == {
        'namespace': 'youtube', 'type': row['target_type'], 'id': tid}, 'native action/target differs')
    require((q['capability'], q['effect']) == (row['capability'], row['effect']), 'action row differs')
    for key in ['project_id', 'resource_ref', 'campaign_id']:
        if key in c:
            require(c[key] == n[key], 'command/native identity differs')
    if c['action'] == 'create':
        require(v['reservation'] is not None and n['reservation_id'] == v['reservation']['reservation_id']
                and v['reservation']['initial_manager_subject'] == x['external_identity'], 'create reservation binding')
    else:
        require(v['reservation'] is None and n['reservation_id'] is None, 'unexpected reservation')
    if c['action'] == 'recover-campaign':
        require(c['expected_store_incarnation'] == n['store_incarnation']
                and c['expected_campaign_revision'] == n['campaign_revision']
                and n['recovery_state'] == 'quarantined', 'recovery command binding')
        plan = c['plan']
        require(plan['classification'] == 'standalone' and all(plan[k] is None for k in ['project_id', 'link_generation', 'recipient_proof_hash'])
                and plan['resource_refs'] == [], 'fixed standalone recovery vector differs')
    closed(g, ['input_text', 'input_hash', 'native_state_text', 'native_state_hash', 'subject_text', 'subject_hash'])
    require({key: g[key] for key in GOLDEN_HASHES[v['id']]} == GOLDEN_HASHES[v['id']],
            'golden v1 changed; reviewed profile/vector version update required')
    ih = golden({'profile': 'youtube-project-input-v1', 'command': c, 'reservation': v['reservation']}, g['input_text'], g['input_hash'])
    nh = golden(n, g['native_state_text'], g['native_state_hash'])
    rv = 'yp1:' + nh[7:]
    subject = {'profile': 'youtube-project-subject-v1', **{k: x[k] for k in ['application_id', 'installation_id', 'tenant_id', 'brand_id', 'workspace_id', 'actor', 'session_id']},
               'target': n['target'], 'capability': q['capability'], 'effect': q['effect'], 'input_hash': ih, 'resource_version': rv, 'native_state_hash': nh}
    sh = golden(subject, g['subject_text'], g['subject_hash'])
    require(q['input_hash'] == ih and q['subject_hash'] == sh and q['idempotency_key'] == sh[7:], 'request hash binding')
    attrs = q['facts']['attributes']
    require(set(attrs) == set(profile['attribute_fields']), 'unknown/missing scalar attribute', 'schema_rejected')
    expected_attrs = {key: ('youtube-project-v1' if key == 'youtube:profile' else x['brand_id'] if key == 'youtube:brand_id'
                           else nh if key == 'youtube:native_state_hash' else n[key[8:]]) for key in profile['attribute_fields']}
    require(q['facts'] == {'attester_id': x['application_id'], 'source': profile['fact_source'], 'resource_version': rv,
                          'observed_at': r['checked_at'], 'owner_tenant_id': x['tenant_id'], 'workspace_id': x['workspace_id'], 'attributes': expected_attrs}, 'native facts binding')
    for key in ['application_id', 'installation_id', 'tenant_id', 'workspace_id']:
        require(q[key] == r[key] == x[key], 'request/result owner binding')
    for key in ['request_id', 'correlation_id', 'target', 'input_hash', 'subject_hash']:
        require(r[key] == q[key], 'result/request binding')
    require(q['actor_evidence']['kind'] == 'human' and q['run_id'] is None and r['actor'] == x['actor'], 'actor/run binding')
    require(r['outcome'] == 'allow', 'nonallow has no usable reference authority')
    require(r['obligations'] == profile['supported_obligations'], 'unsupported/missing obligation')
    versions = r['authority_versions']
    require(versions['tenant_membership'] is not None and versions['workspace_membership'] is not None
            and versions['grant'] is None and versions['parent_grants'] == {}, 'human membership versions')
    clock = v['verification']
    closed(clock, ['wall_now', 'credential_expires_at', 'session_expires_at', 'monotonic_start_ms', 'monotonic_now_ms'])
    require(type(clock['monotonic_start_ms']) is int and type(clock['monotonic_now_ms']) is int
            and 0 <= clock['monotonic_start_ms'] <= clock['monotonic_now_ms'] <= MAX_INTEGER,
            'invalid fixed monotonic clock', 'schema_rejected')
    checked, expiry, now = (seconds(t) for t in [r['checked_at'], r['valid_until'], clock['wall_now']])
    require(abs(now - checked) <= 60 and checked < expiry <= checked + 5
            and now < min(expiry, seconds(clock['credential_expires_at']), seconds(clock['session_expires_at']))
            and clock['monotonic_now_ms'] < clock['monotonic_start_ms'] + min(5000, r['valid_for_ms']), 'original decision deadline expired')


def reference_fence(ref):
    """Closed synthetic lookup; never reads a store or returns execution authority."""
    identity = {'type': 'string', 'minLength': 1, 'maxLength': 128,
                'pattern': '^[A-Za-z0-9][A-Za-z0-9._:-]*$'}
    def record(fields):
        return {'type': 'object', 'properties': fields, 'required': list(fields),
                'additionalProperties': False}
    classification = {'enum': ['standalone', 'project']}
    overlay = record({'store_incarnation': identity, 'campaign_id': identity,
                      'classification': classification, 'status': {'enum': ['quarantined', 'reconciled']}})
    validate(record({'current_incarnation': identity, 'campaign_id': identity,
                     'classification': classification,
                     'overlays': {'type': 'array', 'items': overlay, 'maxItems': 20}}), ref)
    require(isinstance(ref['overlays'], list), 'overlay shape', 'schema_rejected')
    keys = set()
    found = False
    for row in ref['overlays']:
        closed(row, ['store_incarnation', 'campaign_id', 'classification', 'status'])
        key = (row['store_incarnation'], row['campaign_id'])
        require(key not in keys, 'duplicate overlay key', 'schema_rejected')
        keys.add(key)
        if key == (ref['current_incarnation'], ref['campaign_id']):
            found = row['status'] == 'reconciled' and row['classification'] == ref['classification']
    require(found, 'no positive current-incarnation campaign reconciliation', 'reference_fence_rejected')


def rejected(call, expected):
    try:
        call()
    except ContractError as error:
        require(error.category == expected, f'negative rejected by unexpected layer: {error.category}')
        return
    raise ContractError('binding_rejected', 'negative was accepted')


def check(profile_path=PROFILE_PATH, fixture_path=FIXTURE_PATH):
    profile, wire = profile_and_wire(profile_path)
    fixtures = load(fixture_path)
    closed(fixtures, ['profile', 'version', 'status', 'positives', 'negatives', 'parser_negatives', 'recovery_reference', 'reference_negatives', 'native_package_example'])
    require(type(fixtures['version']) is int and (fixtures['profile'], fixtures['version'], fixtures['status']) == ('youtube-project-vectors-v1', 1, 'authored_synthetic_no_runtime_authority'), 'unknown fixture profile', 'schema_rejected')
    example = fixtures['native_package_example']
    closed(example, ['package', 'native_text', 'fingerprint'])
    require(example['package'] == {'campaign_id': 'campaign_demo', 'revision': 5, 'label': 'Café 東京'}
            and isinstance(example['native_text'], str), 'fixed native package example differs', 'schema_rejected')
    # Preserve the native historical identity, which predates this profile's
    # literal-Unicode hash recipe. Never recanonicalize a native fingerprint.
    from campaign_agent.handoff import package_fingerprint
    native_bytes = example['native_text'].encode('utf-8')
    require(json.dumps(example['package'], sort_keys=True, separators=(',', ':')).encode() == native_bytes
            and hashlib.sha256(native_bytes).hexdigest() == example['fingerprint'] == NATIVE_PACKAGE_FINGERPRINT
            and package_fingerprint(example['package']) == NATIVE_PACKAGE_FINGERPRINT,
            'native package fingerprint algorithm/identity differs')
    positives = fixtures['positives']
    require(isinstance(positives, list) and len(positives) == len(POSITIVES)
            and {v['id'] for v in positives} == set(POSITIVES), 'complete positive set required', 'schema_rejected')
    vectors = {v['id']: v for v in positives}
    for v in positives:
        check_vector(v, profile, wire)
    require(vectors['shared-resource-read']['native_state']['package_fingerprint'] == NATIVE_PACKAGE_FINGERPRINT,
            'shared vector must retain exact native package fingerprint')
    require(vectors['create-unicode']['command']['name'] == 'Café 東京'
            and vectors['create-decomposed']['command']['name'] == 'Cafe\u0301 東京'
            and vectors['create-unicode']['golden']['input_hash'] != vectors['create-decomposed']['golden']['input_hash'], 'literal Unicode distinction lost')
    negatives = fixtures['negatives']
    require(isinstance(negatives, list) and len(negatives) == len(NEGATIVES)
            and {n['id'] for n in negatives} == set(NEGATIVES), 'complete negative set required', 'schema_rejected')
    for case in negatives:
        closed(case, ['id', 'base', 'replace_path', 'value', 'expected'])
        require((case['base'], case['replace_path'], case['expected']) == NEGATIVES[case['id']], 'negative definition differs', 'schema_rejected')
        v = copy.deepcopy(vectors[case['base']]); dest = v
        for key in case['replace_path'][:-1]:
            dest = dest[key]
        dest[case['replace_path'][-1]] = case['value']
        rejected(lambda: check_vector(v, profile, wire), case['expected'])
    parser_cases = fixtures['parser_negatives']
    require(isinstance(parser_cases, list) and len(parser_cases) == 3
            and {c['id'] for c in parser_cases} == {'malformed-json', 'duplicate-key', 'unknown-profile'}, 'complete parser negatives required', 'schema_rejected')
    for case in parser_cases:
        closed(case, ['id', 'text', 'expected'])
        require(case['expected'] == 'schema_rejected' and isinstance(case['text'], str), 'parser outcome/input differs', 'schema_rejected')
        def parse_case():
            value = parse(case['text'].encode('utf-8'))
            require(isinstance(value, dict) and value.get('profile') == 'youtube-project-vectors-v1', 'unknown profile', 'schema_rejected')
        rejected(parse_case, case['expected'])
    reference = fixtures['recovery_reference']
    reference_fence(reference)
    recovery = vectors['recover-campaign']
    require(reference['current_incarnation'] == recovery['native_state']['store_incarnation']
            and reference['campaign_id'] == recovery['command']['campaign_id']
            and reference['classification'] == recovery['command']['plan']['classification'],
            'recovery reference/vector binding')
    refcases = fixtures['reference_negatives']
    require(isinstance(refcases, list) and len(refcases) == 3 and {c['id'] for c in refcases} == {
        'missing-link-is-not-standalone', 'old-incarnation-overlay', 'partial-recovery-other-campaign'}, 'complete reference negatives required', 'schema_rejected')
    for case in refcases:
        closed(case, ['id', 'reference', 'expected'])
        require(case['expected'] == 'reference_fence_rejected', 'reference outcome differs', 'schema_rejected')
        rejected(lambda: reference_fence(case['reference']), case['expected'])
    return {'positive_vectors': len(positives), 'binding_schema_negatives': len(negatives),
            'parser_negatives': len(parser_cases), 'reference_positives': 1, 'reference_negatives': len(refcases),
            'scope': 'offline artifact/reference checks; no runtime authorization or service conformance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=PROFILE_PATH)
    parser.add_argument('--fixtures', type=Path, default=FIXTURE_PATH)
    args = parser.parse_args()
    try:
        result = check(args.profile, args.fixtures)
    except (ContractError, OSError, KeyError, IndexError, AttributeError, TypeError, ValueError) as error:
        print(f'Artifact check failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
