"""ASGI staff/public composition over existing commands; no loopback HTTP wrapper."""
from contextlib import closing
from html import escape
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from campaign_agent.access import Operator
from campaign_agent.assets import AssetUnavailable
from campaign_agent.adapters.gateplane import GateplaneAccess
from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST
from campaign_agent.handoff import caption_bytes, media_sha256, read_media
from campaign_agent.instruction_policy import ADDITIONAL_BATCH_SIZE, INITIAL_SAMPLE_SIZE, POLICY_V1, SAMPLE_CAP
from campaign_agent.measurement import ViewerNotFound
from campaign_agent.ports.access import AccessUnavailable
from campaign_agent.publications import Publications
from campaign_agent.staff import SignInRequired
from scripts.campaign_drafts import PackageConflict, StaleDraft

ROOT = Path(__file__).resolve().parents[1]


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(result, dict):
        raise ValueError('Send a JSON object.')
    return result


def fields(data, required, optional=()):
    if not set(required) <= set(data) or set(data) - set(required) - set(optional):
        raise ValueError('Send the declared command fields.')


class HostedApplication:
    def __init__(self, path, sessions, client, assets, *, staff_origin, viewer_origin,
                 application_id='youtube', fixture_login=None):
        self.path, self.sessions, self.client, self.assets = path, sessions, client, assets
        self.staff_origin, self.viewer_origin, self.application_id = staff_origin, viewer_origin, application_id
        self.fixture_login = fixture_login
        self.fixture = fixture_login is not None
        for origin in (staff_origin, viewer_origin):
            url = urlsplit(origin)
            if self.fixture and url.hostname != '127.0.0.1':
                raise ValueError('Synthetic staff selection is restricted to loopback origins.')
            if url.path or url.query or url.fragment or url.username or not url.hostname:
                raise ValueError('Pin exact application origins without paths or credentials.')
            if url.scheme != 'https' and not (self.fixture and url.scheme == 'http' and url.hostname == '127.0.0.1'):
                raise ValueError('Hosted origins require HTTPS; fixture HTTP is loopback-only.')
        if staff_origin == viewer_origin:
            raise ValueError('Staff and viewer origins must be separate.')
        self.cookie = 'gp_fixture_session' if self.fixture else '__Host-gp_session'
        self.publications = Publications(path, assets)
        self.staff = self._app(False)
        self.viewer = self._app(True)

    def _app(self, public):
        async def endpoint(request: Request):
            origin = self.viewer_origin if public else self.staff_origin
            csrf = None
            try:
                if request.headers.get('host') != urlsplit(origin).netloc or request.url.scheme != urlsplit(origin).scheme:
                    return JSONResponse({'error': 'Use the registered application origin.'}, status_code=403)
                site = request.headers.get('sec-fetch-site')
                if site not in (None, 'same-origin', 'none') and not (
                        request.method in {'GET', 'HEAD'} and request.headers.get('sec-fetch-mode') == 'navigate'):
                    return JSONResponse({'error': 'Cross-origin request rejected.'}, status_code=403)
                if request.method == 'POST' and request.headers.get('origin') != origin:
                    raise PermissionError('Use the registered application origin.')
                if len(request.query_params.multi_items()) != len(request.query_params):
                    raise ValueError('Use each query field once.')
                raw = b''
                async for chunk in request.stream():
                    raw += chunk
                    if len(raw) > 800_000:
                        return JSONResponse({'error': 'Request is too large.'}, status_code=413)
                if request.method == 'POST':
                    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                        raise ValueError('Send JSON.')
                    data = strict_json(raw)
                else:
                    data = {}
                response, csrf = await run_in_threadpool(self._handle, request, data, public)
            except SignInRequired:
                response = JSONResponse({'error': 'Sign in to open this workspace.'}, status_code=401)
            except AccessUnavailable:
                response = JSONResponse({'error': 'Current staff authority is unavailable. Try again.'}, status_code=503)
            except PermissionError:
                response = JSONResponse({'error': 'This action is unavailable in this workspace.'}, status_code=403)
            except (PackageConflict, StaleDraft) as exc:
                response = JSONResponse({'error': str(exc)}, status_code=409)
            except (ViewerNotFound, LookupError, AssetUnavailable):
                response = JSONResponse({'error': 'Resource unavailable.'}, status_code=404)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                response = JSONResponse({'error': 'Invalid command or unsupported fields.'}, status_code=400)
            except Exception:
                response = JSONResponse({'error': 'Could not complete this action.'}, status_code=503)
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
                'Cross-Origin-Resource-Policy': 'same-origin', 'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
                'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
                'Content-Security-Policy': "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                'Vary': 'Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site'})
            if csrf:
                response.headers['X-CSRF-Token'] = csrf
            return response
        return Starlette(routes=[Route('/{path:path}', endpoint, methods=['GET', 'HEAD', 'POST'])])

    def runtime(self, token, campaign, command):
        access = GateplaneAccess(self.path, self.sessions, token, self.client,
                                 application_id=self.application_id, command=command)
        _, context, principal = access.principal(campaign)
        examples, media_dir = self.assets(context.scope.client_id, context.scope.brand_id)
        runtime = AgentRuntime(self.path, Operator(principal['actor']['principal_id'], frozenset({context.scope})),
                    context=context, campaign_id=campaign, access=access, examples=examples, media_dir=media_dir,
                    viewer_links=self.publications.approved_links)
        return runtime, principal

    def _handle(self, request, data, public):
        path, method = request.url.path, request.method
        if method in {'GET', 'HEAD'} and path in {'/brand/mark.svg', '/brand/tokens.css'}:
            return FileResponse(ROOT / 'web' / path.lstrip('/')), None
        if public:
            return self._public(request, data), None
        if self.fixture and path == '/fixture':
            if method in {'GET', 'HEAD'}:
                buttons = ''.join(f'<button name="profile" value="{escape(name)}">{escape(name)}</button>'
                                  for name in self.fixture_login.profiles)
                html = '<!doctype html><html lang="en"><title>Offline staff access fixture</title><link rel="stylesheet" href="/brand/tokens.css"><main><h1>Offline staff access fixture</h1><p>Synthetic people and access decisions. No real sign-in or provider calls.</p><div id="profiles">' + buttons + '</div><script src="/fixture.js"></script></main></html>'
                return HTMLResponse(html), None
            fields(data, {'profile'})
            reference, campaign = self.fixture_login.profile(data['profile'])
            token = self.sessions.establish(reference, campaign)
            self.runtime(token, campaign, {'path': path, 'method': method, 'body': {'profile': data['profile']}})
            response = JSONResponse({'path': '/campaign'})
            response.set_cookie(self.cookie, token, max_age=3600, secure=not self.fixture,
                                httponly=True, samesite='strict', path='/')
            return response, None
        if self.fixture and path == '/fixture.js' and method == 'GET':
            return Response("document.getElementById('profiles').addEventListener('click',async e=>{if(e.target.tagName!=='BUTTON')return;const r=await fetch('/fixture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:e.target.value})});if(r.ok)location.assign((await r.json()).path);else document.body.append(' Access unavailable.');});", media_type='application/javascript'), None
        token = request.cookies.get(self.cookie)
        if path == '/api/session/end' and method == 'POST':
            row = self.sessions.local(token, allow_expired=True)
            if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), row[5]):
                raise PermissionError('Refresh the session before submitting changes.')
            fields(data, set())
            self.sessions.end(token)
            response = JSONResponse({'signed_out': True}, headers={'Clear-Site-Data': '"cookies", "storage", "cache"'})
            response.delete_cookie(self.cookie, path='/', secure=not self.fixture, httponly=True, samesite='strict')
            return response, None
        identity, campaign, csrf = self.sessions.current(token)
        if method == 'POST' and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), csrf):
            raise PermissionError('Refresh the session before submitting changes.')
        command = {'method': method, 'path': path, 'query': dict(request.query_params), 'body': data}
        # Candidate IDs are resolved to native owners before Gateplane checks them.
        selected = data['campaign_id'] if path == '/api/session/context' and method == 'POST' else campaign
        runtime, principal = self.runtime(token, selected, command)
        if path == '/api/session/context' and method == 'POST':
            fields(data, {'campaign_id'})
            runtime.require('youtube:campaign.read')
            self.sessions.select(token, selected)
            return JSONResponse({'campaign_id': selected}), csrf
        if path == '/api/session' and method == 'GET':
            return JSONResponse({'actor_id': runtime.operator.id, 'campaign_id': selected,
                'client_id': runtime.scope.client_id, 'brand_id': runtime.scope.brand_id,
                'workspace_id': runtime.drafts.context.workspace_id}), csrf
        if method in {'GET', 'HEAD'}:
            result = self._get(runtime, request)
            return (result if isinstance(result, Response) else JSONResponse(result)), csrf
        return JSONResponse(self._post(runtime, path, data)), csrf

    def _get(self, r, request):
        path, q = request.url.path, dict(request.query_params)
        if path in {'/', '/campaign'}:
            file = ROOT / 'web/planner/dist/index.html'
            return FileResponse(file) if file.exists() else HTMLResponse('Build the planner: pnpm --dir web/planner build', status_code=503)
        if path.startswith('/assets/'):
            file = ROOT / 'web/planner/dist/assets' / path.removeprefix('/assets/')
            if file.parent != ROOT / 'web/planner/dist/assets' or not file.is_file():
                raise ViewerNotFound()
            return FileResponse(file)
        if path.startswith('/viewer/media/'):
            creative, ref, take = path.removeprefix('/viewer/media/').split('/')
            example = next((e for e in r.drafts.examples if e.creative_ref == creative and e.ref == ref), None)
            if example is None:
                raise ViewerNotFound()
            name = example.preview if take == 'preview' else next((name for key, _, name in example.takes if key == take), None)
            data = caption_bytes(example) if take == 'captions' else read_media(r.drafts.media_dir, name)
            fields(q, {'sha256'})
            if q['sha256'] != media_sha256(data):
                raise PackageConflict('The media changed.')
            r.require('youtube:campaign.read')
            return Response(data, media_type='text/vtt' if take == 'captions' else 'video/mp4' if name.endswith('.mp4') else 'audio/mpeg')
        if path in {'/api/config', '/api/mode'}:
            return {'live': False, 'demoRequest': DEMO_REQUEST, 'viewerOrigin': '', 'publicViewerOrigin': self.viewer_origin,
                'googleAdsReporting': False, 'openrouterReviewModels': [], 'openrouterDraftModels': [],
                'instructionTestLimits': {'initial': INITIAL_SAMPLE_SIZE, 'batch': ADDITIONAL_BATCH_SIZE,
                    'cap': SAMPLE_CAP, 'batchCost': POLICY_V1['batch_cost']},
                'agentPlanner': {**r.planner.options(), 'catalogs': r.planner.catalogs.list()},
                'examples': [{'creative': e.creative_ref, 'ref': e.ref, 'title': e.title} for e in r.drafts.examples],
                'workspace': {'actor': r.operator.id, **vars(r.scope), 'id': r.drafts.context.workspace_id,
                              'fixture': self.fixture}}
        if path == '/api/campaign':
            fields(q, set(), {'revision'})
            return r.drafts.read(int(q['revision']) if 'revision' in q else None)
        if path == '/api/agent/conversations':
            return r.planner.conversations.list()
        if path in {'/api/agent/conversation', '/api/agent/run'}:
            fields(q, {'id'})
            return r.planner.conversations.read(q['id']) if path.endswith('conversation') else r.read(q['id'])
        reads = {'/api/campaign/package': r.drafts.review_package,
            '/api/campaign/setup': r.setup.read, '/api/campaign/performance': r.performance.read,
            '/api/campaign/instruction-test': r.instruction_tests.read,
            '/api/campaign/instruction-finding': r.instruction_findings.read,
            '/api/campaign/google-ads-delivery': r.delivery.read}
        if path in reads:
            fields(q, {'revision'} if path.endswith('/package') else {'revision', 'fingerprint'},
                   {'approval'} if path.endswith('/package') else set())
            if 'approval' in q:
                return r.drafts.read_approved_package(r.drafts.campaign_id, int(q['revision']), q['approval'])
            result = reads[path](r.drafts.campaign_id, int(q['revision']), **({'fingerprint': q['fingerprint']} if 'fingerprint' in q else {}))
            if path == '/api/campaign/package':
                with closing(sqlite3.connect(self.path)) as db:
                    links = [{'creative_ref': creative, 'url': self.viewer_origin + '/viewer?attribution=' + token}
                             for token, creative in db.execute('SELECT id,creative_ref FROM public_comparisons '
                                 'WHERE campaign_id=? AND revision=? AND fingerprint=? AND active=1 AND expires_at>?',
                                 (r.drafts.campaign_id, int(q['revision']), result['fingerprint'], self.publications.clock()))]
                return {**result, 'public_comparisons': links}
            return result
        raise ViewerNotFound()

    def _post(self, r, path, data):
        if path == '/api/campaign':
            return r.drafts.save(data)
        if path == '/api/agent/catalog':
            fields(data, {'label', 'rows'})
            key = r.planner.catalogs.register(**data)
            return {'id': key, 'catalogs': r.planner.catalogs.list()}
        if path == '/api/agent/placements':
            fields(data, {'request', 'model', 'session_id', 'run_id', 'catalog_id'}, {'after_message', 'draft_permission'})
            if data['model'] not in {'simulated', 'simulated-inspect'}:
                raise ValueError('Only offline models are configured.')
            return r.read(r.planner.start(**data))
        if path == '/api/agent/run':
            fields(data, {'run_id'})
            return r.resume(data['run_id'], max_steps=1)
        agent_commands = {
            '/api/agent/next-test': (r.start_next_test, {'campaign_id', 'revision', 'fingerprint', 'review_id'}),
            '/api/agent/instruction-review': (r.start_instruction_review, {'test_id'}),
            '/api/agent/experiment-next-test': (r.start_experiment_next_test, {'test_id', 'review_id'}),
        }
        if path in agent_commands:
            command, required = agent_commands[path]
            fields(data, required, {'mode', 'operation_id'})
            if data.get('mode', 'offline') != 'offline':
                raise ValueError('Only offline inference is configured.')
            return r.read(command(**data))
        references = {'campaign_id', 'revision', 'fingerprint'}
        commands = {
            '/api/campaign/approve': (r.drafts.approve_package, set()),
            '/api/campaign/export': (r.drafts.export_setup, set()),
            '/api/campaign/setup/validate': (r.setup.validate, set()),
            '/api/campaign/setup/create': (r.setup.create, {'setup_id'}),
            '/api/campaign/setup/reconcile': (r.setup.reconcile, {'setup_id'}),
            '/api/campaign/performance': (r.performance.review, {'scenario'}),
            '/api/campaign/correction': (r.performance.save_correction, {'review_id', 'kind', 'note', 'operation_id'}),
            '/api/campaign/instruction-test': (r.instruction_tests.start, set()),
            '/api/campaign/instruction-test/evidence': (r.instruction_tests.save_evidence_snapshot, {'operation_id'}),
            '/api/campaign/instruction-finding/save': (r.instruction_findings.save, {'snapshot_id'}),
            '/api/campaign/instruction-finding/apply': (r.instruction_findings.apply, {'finding_id', 'correction_id', 'draft_permission'}),
            '/api/campaign/instruction-finding/retire': (r.instruction_findings.retire, {'finding_id'}),
            '/api/campaign/brief': (r.drafts.start_brief, {'title', 'goal', 'context'}),
            '/api/campaign/google-ads-delivery': (r.delivery.review, set()),
            '/api/campaign/google-ads-delivery/recommend': (r.delivery.recommend, {'report_id'}),
        }
        if path not in commands:
            raise ViewerNotFound()
        command, extra = commands[path]
        fields(data, references | extra, {'allow_additional_batch'} if path.endswith('/instruction-test') else set())
        result = command(**data)
        if path == '/api/campaign/export':
            links = self.publications.publish(r, **data)
            result = {**result, 'public_comparisons': [{**link, 'url': self.viewer_origin + link['path']} for link in links]}
        return result

    def _public(self, request, data):
        path, method = request.url.path, request.method
        if path == '/viewer' and method in {'GET', 'HEAD'}:
            self.publications.resolve(request.query_params.get('attribution'))
            return FileResponse(ROOT / 'web/viewer/index.html')
        if path.startswith('/published/') and method in {'GET', 'HEAD'}:
            token, take = path.removeprefix('/published/').split('/')
            content, content_type = self.publications.media(token, take)
            return Response(content, media_type=content_type)
        if path == '/api/viewer/open' and method == 'POST':
            fields(data, {'attribution', 'visit_id'}, {'rehearsal'})
            if type(data.get('rehearsal', False)) is not bool:
                raise ValueError('Choose a valid viewer source.')
            return JSONResponse(self.publications.open(data['attribution'], data['visit_id'], data.get('rehearsal', False)))
        if path == '/api/viewer/event' and method == 'POST':
            return JSONResponse(self.publications.event(data))
        raise ViewerNotFound()
