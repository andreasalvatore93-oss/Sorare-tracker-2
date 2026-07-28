"""Notifica Telegram di fine run Formazione giornata con link cliccabile
all'HTML generato -- richiesta esplicita utente 28/07 (evitare di scaricare
il file o passare da GitHub per aprirlo).

Lanciato come step separato del workflow DOPO il job `formazione` (che ha gia'
pushato l'HTML su main a quel punto), cosi' il link punta a un file
effettivamente presente su GitHub.

Stesso schema di scanners/bot_profit_telegram_notify.py: TELEGRAM_TOKEN/
TELEGRAM_CHAT_ID da env, link via raw.githack.com (CDN che serve
raw.githubusercontent.com con Content-Type text/html, cosi' il browser
lo RENDE invece di scaricarlo -- funziona solo su repo pubblici, questo lo e').
"""
import glob
import os

import requests

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GIT_REF = os.environ.get('GIT_REF', 'main').strip() or 'main'
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()

OUTPUT_DIR = 'generatore_formazioni/output'


def _latest_html():
    """Il file PIU' RECENTE per data di modifica -- NON un sort alfabetico del
    nome file (bug reale 28/07: 'run9' viene lessicograficamente DOPO 'run21'
    perche' '9' > '2' come carattere, quindi sorted() prendeva un run vecchio
    invece dell'ultimo generato -- scoperto dall'utente, notifica arrivata con
    un report di ore prima)."""
    candidates = glob.glob(os.path.join(OUTPUT_DIR, 'generatore_formazioni_run*.html'))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _viewer_url(path):
    path_url = path.replace(os.sep, '/')
    return f"https://raw.githack.com/{REPO_SLUG}/{GIT_REF}/{path_url}"


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[formazione_telegram_notify] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID mancanti, salto la notifica.")
        return

    path = _latest_html()
    if not path:
        print("[formazione_telegram_notify] nessun HTML trovato in questa run, salto la notifica.")
        return

    message = f"⚽ <b>Formazione giornata -- run completata</b>\n<a href=\"{_viewer_url(path)}\">Apri il report</a>"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"[formazione_telegram_notify] errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        print(f"[formazione_telegram_notify] errore invio Telegram: {e}")


if __name__ == '__main__':
    main()
