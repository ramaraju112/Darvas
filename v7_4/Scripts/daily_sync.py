"""Scheduled runner: 6 PM CT on Nov 17 2026 only, otherwise 4 PM CT weekdays."""
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
    hour = 18 if now.date().isoformat() == '2026-11-17' else 16
    return now.weekday() < 5 and now.hour == hour

def main():
    if not in_window():
        print('Outside allowed Central weekday window; skipping (no catch-up)')
        return 0
    base = os.environ['DARVAS_APP_URL'].rstrip('/')
    token = os.environ['DARVAS_SYNC_TOKEN']
    count = 0
    # Upper bound for GitHub Actions: do not start a batch near the end of hour.
    while in_window() and datetime.now(ZONE).minute < 53:
        req = Request(base + '/api/sync/batch?limit=6', data=b'', method='POST',
                      headers={'X-Darvas-Sync-Token': token})
        try:
            with urlopen(req, timeout=165) as resp:
                result = json.load(resp)
        except HTTPError as exc:
            print('Sync HTTP status:', exc.code)
            # A busy server should not cause concurrent updates.
            if exc.code == 409:
                time.sleep(10)
                continue
            return 1
        except (URLError, TimeoutError) as exc:
            print('Sync request failed:', type(exc).__name__)
            return 1
        count += result.get('attempted', 0)
        print(json.dumps({k:v for k,v in result.items() if k not in ('report',)}, default=str))
        if result.get('done'):
            print('Completed eligible universe for today; processed:', count)
            return 0
        time.sleep(2)
    print('Scheduled window ending; saved checkpoints. Remaining symbols resume next scheduled day.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
