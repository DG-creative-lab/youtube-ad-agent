import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from campaign_agent.application.planner_runtime import RetainedWorkflow
from campaign_agent.bootstrap.placement_router import PlacementRouter


def result(*, mode='simulated', execution='model', steps=()):
    return {'planner': {'settings': {'mode': mode}, 'execution': execution}, 'steps': list(steps)}


class PlacementRouterTests(unittest.TestCase):
    def setUp(self):
        self.legacy = Mock()
        self.typed = Mock()
        self.runtime = SimpleNamespace(foreground=None, delivery=SimpleNamespace(reporting=object(), demo_scenario=None))
        self.router = PlacementRouter(self.legacy, self.typed, self.runtime)
        self.typed.read.return_value = result()

    def test_start_uses_selected_simulated_and_retains_delivery_and_remote(self):
        self.router.start('Find suitable placements', 'simulated', 's', 'r', 'c')
        self.typed.start.assert_called_once()
        self.router.start('Review Google Ads delivery', 'simulated', 's', 'r', 'c')
        self.router.start('Find suitable placements', 'remote', 's', 'r', 'c')
        self.assertEqual(self.legacy.start.call_count, 2)

    def test_foreground_is_checked_each_time_and_interface_delegates(self):
        self.legacy.options.return_value = {'legacy': True}
        self.runtime.foreground = object()
        self.assertEqual(self.router.options(), {'legacy': True})
        self.router.start('Find placements', 'simulated', 's', 'r', 'c')
        self.router.resume('r')
        self.router.read('r')
        self.legacy.start.assert_called_once()
        self.legacy.resume.assert_called_once()
        self.legacy.read.assert_called_once()
        self.typed.read.assert_not_called()
        self.runtime.foreground = None
        self.router.read('r')
        self.typed.read.assert_called_once_with('r')

    def test_retained_successful_history_routes_legacy_but_errors_do_not(self):
        self.typed.read.return_value = result(steps=[{'tool': 'review_delivery', 'result': {'ok': True}}])
        self.router.resume('r', max_steps=2)
        self.legacy.resume.assert_called_once_with('r', max_steps=2)
        self.typed.resume.assert_not_called()
        self.typed.read.return_value = result(steps=[{'tool': 'review_delivery', 'result': {'error': 'denied'}}])
        self.router.resume('r')
        self.typed.resume.assert_called_once_with('r', max_steps=1)
        self.typed.read.return_value = result(steps=[{'tool': 'respond', 'result': {}, 'arguments': {'topic': 'experiment_review'}}])
        self.router.resume('r')
        self.assertEqual(self.legacy.resume.call_count, 2)

    def test_saved_unsupported_receipt_returns_to_legacy_without_new_start(self):
        self.typed.resume.side_effect = RetainedWorkflow('saved receipt')
        self.router.resume('r', max_steps=3)
        self.legacy.resume.assert_called_once_with('r', max_steps=3)
        self.legacy.start.assert_not_called()

    def test_local_dispatch_requires_exact_valid_placement_shape(self):
        request = {'request': 'Find placements', 'model': 'simulated',
                   'session_id': 'a'*32, 'run_id': 'b'*32, 'catalog_id': 'c'*32,
                   'draft_permission': 'placements'}
        self.assertTrue(self.router.can_dispatch_local('/api/agent/placements', request))
        for change in ({'provider_selection_id': None}, {'model': 'remote'},
                       {'run_id': 'invalid'}, {'draft_permission': 'invalid'},
                       {'request': 'Review Google Ads delivery'}):
            self.assertFalse(self.router.can_dispatch_local('/api/agent/placements', {**request, **change}))
        self.assertTrue(self.router.can_dispatch_local('/api/agent/run', {'run_id': 'b'*32}))
        self.typed.read.return_value = result(steps=[{'tool': 'review_delivery', 'result': {}}])
        self.assertFalse(self.router.can_dispatch_local('/api/agent/run', {'run_id': 'b'*32}))
        self.assertFalse(self.router.can_dispatch_local('/api/agent/run', {'run_id': 'b'*32, 'request': 'x'}))

    def test_remote_and_delivery_reads_use_legacy(self):
        for value in (result(mode='openrouter'), result(execution='application')):
            self.typed.read.return_value = value
            self.router.read('r')
        self.assertEqual(self.legacy.read.call_count, 2)


class LocalHttpJourneyTests(unittest.TestCase):
    def test_offline_placement_uses_typed_runtime_without_foreground(self):
        import io
        import json
        import socket
        import sqlite3
        from contextlib import redirect_stdout
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event
        from unittest.mock import patch
        from campaign_agent.application.planner_runtime import PlacementRuntime
        from campaign_agent.bootstrap.planner import create_local_planner
        from scripts import placement_review
        import campaign_agent.application.campaigns as campaigns
        import campaign_agent.agent.planner as legacy_planner

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'demo.sqlite3'
            create_local_planner(path)
            instances = []
            def factory(*args, **kwargs):
                instance = create_local_planner(*args, **kwargs)
                instances.append(instance)
                return instance
            stop = Event()
            responses = []
            original_start = PlacementRuntime.start
            starts = []
            def record_start(self, *args, **kwargs):
                starts.append(args)
                return original_start(self, *args, **kwargs)
            class Server:
                def __init__(self, address, handler):
                    self.server_port, self.handler = address[1], handler
                    self.viewer = self.server_port == 8766
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def shutdown(self): stop.set()
                def serve_forever(self):
                    if self.viewer:
                        stop.wait(10)
                        return
                    catalog = instances[0].planner.catalogs.list()[0]['id']
                    command = {'request': 'Find placements', 'model': 'simulated',
                               'session_id': 'a'*32, 'run_id': 'b'*32, 'catalog_id': catalog}
                    for route, data in [('/api/agent/placements', command),
                                        ('/api/agent/run', {'run_id': 'b'*32})]:
                        body = json.dumps(data).encode()
                        raw = (f'POST {route} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n'
                               f'Origin: http://127.0.0.1:8765\r\nX-Local-Operator: token\r\n'
                               f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
                        client, peer = socket.socketpair()
                        try:
                            client.sendall(raw)
                            client.shutdown(socket.SHUT_WR)
                            self.handler(peer, ('127.0.0.1', 1234), self)
                            peer.close()
                            chunks = []
                            while chunk := client.recv(65536): chunks.append(chunk)
                            responses.append(b''.join(chunks))
                        finally:
                            client.close()
                            peer.close()
            blocked = SimpleNamespace(connect=Mock(side_effect=AssertionError('application SQLite connection')), Error=sqlite3.Error)
            with (patch.object(placement_review, 'ThreadingHTTPServer', Server),
                  patch.object(placement_review.secrets, 'token_urlsafe', return_value='token'),
                  patch('campaign_agent.foreground_inference.ForegroundInference.attach', side_effect=AssertionError('foreground attached')),
                  patch.object(PlacementRuntime, 'start', record_start),
                  patch.object(campaigns, 'sqlite3', blocked), patch.object(legacy_planner, 'sqlite3', blocked),
                  redirect_stdout(io.StringIO())):
                placement_review.serve(8765, False, path, runtime_factory=factory, initialize=False)
            self.assertEqual(len(starts), 1)
            for response in responses:
                self.assertIn(b'200 OK', response)
                self.assertEqual(json.loads(response.split(b'\r\n\r\n', 1)[1])['run_id'], 'b'*32)
            self.assertEqual(len(responses), 2)
            self.assertTrue(json.loads(responses[1].split(b'\r\n\r\n', 1)[1])['steps'])


if __name__ == '__main__':
    unittest.main()
