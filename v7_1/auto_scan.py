"""Load the GitHub-published scan bundled into the Render Docker image."""
from pathlib import Path
from core import import_signals

SCAN_PATH = Path(__file__).resolve().parent / 'data' / 'scan_all.csv'

def sync_bundled_scan(con):
    """Idempotently import the latest bundled market snapshot.

    The file is committed by GitHub Actions; Render rebuilds on each commit.
    Do not run network requests or the full scanner inside Streamlit.
    """
    if not SCAN_PATH.is_file():
        return 'Waiting for first automated market scan'
    data = SCAN_PATH.read_bytes()
    if not data.strip():
        return 'Market scan file is empty'
    count, state = import_signals(con, data, 'automated_scan_all.csv')
    return f'Automated market scan: {count} symbols {state}'
