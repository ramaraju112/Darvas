"""Authenticated batch sync; no wall-clock cutoff. Resume via daily DB checkpoints."""
import json
import os
import sys
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def main():
    print('Started:', datetime.now(ZoneInfo('America/Chicago')).isoformat(), flush=True)
    base = os.environ['DARVAS_APP_URL'].rstrip('/')
    token = os.environ.get('DARVAS_SYNC_TOKEN', '')
    if not token:
        print('ERROR: DARVAS_SYNC_TOKEN is missing', flush=True)
        return 1
    attempted = succeeded = failed = consecutive_errors = 0
    deadline = time.monotonic() + 330 * 60
    while time.monotonic() < deadline:
        req = Request(base + '/api/sync/batch?limit=6', data=b'', method='POST',
                      headers={'X-Darvas-Sync-Token': token})
        try:
            with urlopen(req, timeout=180) as resp:
                result = json.load(resp)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            code = getattr(exc, 'code', None)
            print('Request error:', type(exc).__name__, code, flush=True)
            if code in (400, 401, 403, 404, 422):
                return 1
            consecutive_errors += 1
            if consecutive_errors >= 8:
                return 1
            time.sleep(min(120, 10 * consecutive_errors))
            continue
        consecutive_errors = 0
        attempted += result.get('attempted', 0)
        succeeded += result.get('succeeded', 0)
        failed += result.get('failed', 0)
        print(json.dumps({k:v for k,v in result.items() if k != 'report'}), flush=True)
        if result.get('done'):
            coverage = result.get('coverage', {})
            print(f'QUEUE EXHAUSTED: attempted={attempted}, succeeded={succeeded}, failed={failed}; coverage={coverage}', flush=True)
            return 1 if failed or coverage.get('with_failures') or coverage.get('pending_initial') else 0
        if not result.get('attempted'):
            print('ERROR: no progress; queue not complete', flush=True)
            return 1
        time.sleep(2)
    print(f'INCOMPLETE: job time budget reached; resume using Run workflow. attempted={attempted}, succeeded={succeeded}', flush=True)
    return 1


if __name__ == '__main__':
    sys.exit(main())
