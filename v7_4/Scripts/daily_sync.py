"""Automatic Darvas sync: weekday 4–5 PM America/Chicago, no catch-up."""
import json
import os
import sys
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('America/Chicago')

def in_window():
    now = datetime.now(ZONE)
    return now.weekday() < 5 and now.hour == 16 and now.minute < 50

def main():
    now = datetime.now(ZONE)
    print(f'Started: {now.isoformat()} (Central); weekday={now.weekday()}')
    if not in_window():
        print('SKIPPED: Outside 4:00–4:50 PM Central weekday start window; no catch-up.')
        return 0
    base = os.environ['DARVAS_APP_URL'].rstrip('/')
    token = os.environ['DARVAS_SYNC_TOKEN']
    count = 0
    successes = 0
    # API checkpoints last_attempt by Central date, so multiple scheduled triggers
    # do not download the same symbol twice on the same day.
    while in_window():
        req = Request(base + '/api/sync/batch?limit=6', data=b'', method='POST',
                      headers={'X-Darvas-Sync-Token': token})
        try:
            with urlopen(req, timeout=165) as resp:
                result = json.load(resp)
        except HTTPError as exc:
            print('Sync HTTP status:', exc.code)
            if exc.code == 409:
                # Could be busy, or the server's window closed. Recheck time.
                if not in_window():
                    break
                time.sleep(10)
                continue
            return 1
        except (URLError, TimeoutError) as exc:
            print('Sync request failed:', type(exc).__name__)
            return 1
        count += result.get('attempted', 0)
        successes += result.get('succeeded', 0)
        print(json.dumps({k:v for k,v in result.items() if k != 'report'}, default=str), flush=True)
        if result.get('done'):
            print(f'COMPLETED daily eligible queue: attempted={count}, succeeded={successes}')
            return 0
        if result.get('attempted', 0) == 0:
            print('No symbols attempted; stopping to avoid a busy loop.')
            return 0
        time.sleep(2)
    print(f'WINDOW ENDED: attempted={count}, succeeded={successes}. Remaining symbols await next weekday.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
