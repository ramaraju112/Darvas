#!/usr/bin/env python3
import argparse,os
from pathlib import Path
import requests
p=argparse.ArgumentParser();p.add_argument('file');p.add_argument('--caption',default='Darvas V5 report');a=p.parse_args()
token=os.environ.get('TELEGRAM_BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
if not token or not chat:raise SystemExit('Telegram credentials missing')
f=Path(a.file)
if not f.is_file():raise SystemExit(f'File missing: {f}')
with f.open('rb') as data:
    r=requests.post(f'https://api.telegram.org/bot{token}/sendDocument',data={'chat_id':chat,'caption':a.caption[:1000]},files={'document':(f.name,data)},timeout=90)
r.raise_for_status()
if not r.json().get('ok'):raise SystemExit('Telegram rejected document')
print('Telegram document delivered')
