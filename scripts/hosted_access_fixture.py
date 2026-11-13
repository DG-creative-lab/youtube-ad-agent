#!/usr/bin/env python3
"""Run the explicit, loopback-only ASGI staff access fixture with zero provider calls."""
import argparse
from pathlib import Path
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import uvicorn
    from campaign_agent.adapters.fixture_access import offline_fixture
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / '.local/hosted-access-fixture.sqlite3')
    parser.add_argument('--port', type=int, default=18985)
    parser.add_argument('--viewer-port', type=int, default=18986)
    args = parser.parse_args()
    if args.port == args.viewer_port or not all(1 <= port <= 65535 for port in (args.port, args.viewer_port)):
        parser.error('Choose separate fixed ports from 1 to 65535.')
    app = offline_fixture(args.db, staff_origin=f'http://127.0.0.1:{args.port}', viewer_origin=f'http://127.0.0.1:{args.viewer_port}')
    config = dict(host='127.0.0.1', workers=1, proxy_headers=False, access_log=False, log_level='warning')
    viewer = uvicorn.Server(uvicorn.Config(app.viewer, port=args.viewer_port, **config))
    staff = uvicorn.Server(uvicorn.Config(app.staff, port=args.port, **config))
    thread = Thread(target=viewer.run)
    thread.start()
    print(f'Offline staff access fixture: http://127.0.0.1:{args.port}/fixture', flush=True)
    print('Synthetic identities/decisions only; no live authentication or provider calls.', flush=True)
    try:
        staff.run()
    except KeyboardInterrupt:
        pass
    finally:
        viewer.should_exit = True
        thread.join()


if __name__ == '__main__':
    main()
