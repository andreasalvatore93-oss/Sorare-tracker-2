"""Notifica Telegram di fine run Best Five con link cliccabile all'HTML
generato -- stesso schema di generatore_formazioni/formazione_telegram_notify.py
(TELEGRAM_TOKEN/TELEGRAM_CHAT_ID da env, link via raw.githack.com cosi' il
browser RENDE l'HTML invece di scaricarlo).

Lanciato come step separato del workflow best_five.yml DOPO lo step che ha
gia' pushato l'HTML su main, cosi' il link punta a un file effettivamente
presente su GitHub.
"""
import glob
import os

import requests

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GIT_REF = os.environ.get('GIT_REF', 'main').strip() or 'main'
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()
LEGA = os.environ.get('LEGA', 'kleague').strip()

OUTPUT_DIR = f'formazione_{LEGA}/output/best_five'


def _latest_html():
    """Il file HTML PIU' RECENTE per data di modifica, non per ordine
    alfabetico -- stesso bug gia' visto e fixato in formazione_telegram_notify.py
    (un timestamp come 'run9' puo' finire lessicograficamente dopo 'run21')."""
    candidates = glob.glob(os.path.join(OUTPUT_DIR, 'best_five_*.html'))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _viewer_url(path):
    path_url = path.replace(os.sep, '/')
    return f"https://raw.githack.com/{REPO_SLUG}/{GIT_REF}/{path_url}"


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[best_five_telegram_notify] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID mancanti, salto la notifica.")
        return

    path = _latest_html()
    if not path:
        print("[best_five_telegram_notify] nessun HTML trovato in questa run, salto la notifica.")
        return

    message = (f"⭐ <b>Best Five ({LEGA.upper()}) — run completata</b>\n"
               f"<a href=\"{_viewer_url(path)}\">Apri il report</a>")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"[best_five_telegram_notify] errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        print(f"[best_five_telegram_notify] errore invio Telegram: {e}")


if __name__ == '__main__':
    main()
