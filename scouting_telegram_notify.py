"""Notifica Telegram del report di scouting, con link cliccabile all'HTML.

Stesso schema di generatore_formazioni/formazione_telegram_notify.py: il file
e' gia' su main quando questo parte, e il link passa da raw.githack.com (CDN
che serve raw.githubusercontent.com con Content-Type text/html, cosi' il
browser lo RENDE invece di scaricarlo -- funziona solo su repo pubblici).
"""
import os
import re

import requests

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GIT_REF = os.environ.get('GIT_REF', 'main').strip() or 'main'
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()

REPORT = os.environ.get('SCOUTING_REPORT',
                        'generatore_formazioni/output/scouting_ultimo.html')


def _riassunto(path):
    """Giornata e numero di candidati, letti dall'HTML stesso: cosi' il
    messaggio dice qualcosa di vero anche se il report cambia forma."""
    try:
        with open(path, encoding='utf-8') as f:
            testo = f.read(4000)
    except OSError:
        return '', ''
    fixture = re.search(r'<h1>Scouting -- ([^<]+)</h1>', testo)
    quanti = re.search(r'&middot; (\d+) candidati', testo)
    return (fixture.group(1) if fixture else ''), (quanti.group(1) if quanti else '')


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[scouting_telegram_notify] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID mancanti, salto.")
        return
    if not os.path.exists(REPORT):
        print(f"[scouting_telegram_notify] nessun report in {REPORT}, salto.")
        return

    fixture, quanti = _riassunto(REPORT)
    url_report = f"https://raw.githack.com/{REPO_SLUG}/{GIT_REF}/{REPORT}"
    testa = f"🔎 <b>Scouting acquisti{' -- ' + fixture if fixture else ''}</b>"
    corpo = f"\n{quanti} candidati" if quanti else ''
    message = f"{testa}{corpo}\n<a href=\"{url_report}\">Apri il report</a>"

    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={'chat_id': TELEGRAM_CHAT_ID, 'text': message,
                                'parse_mode': 'HTML', 'disable_web_page_preview': True},
                          timeout=10)
        if not r.ok:
            print(f"[scouting_telegram_notify] errore Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        print(f"[scouting_telegram_notify] errore Telegram: {e}")


if __name__ == '__main__':
    main()
