"""Notifica Telegram di fine run Bot Profit con link cliccabili ai CSV di
output (uno per GRUPPO, vedi OUTPUT_GROUPS in bot_profit.py -- Eredivisie e
Belgio condividono lo stesso gruppo/file, MLS e K-League restano separate)
-- richiesta esplicita utente 29/07. Lanciato come step separato del workflow DOPO
bot_profit.py (which git ha gia' pushato in quel punto il commit finale coi
CSV), cosi' i link puntano a file effettivamente presenti su GitHub.

Riusa lo stesso schema Telegram di scanners/track.py (TELEGRAM_TOKEN/
TELEGRAM_CHAT_ID, non duplicato qui per non introdurre una dipendenza tra
moduli non correlati -- stesso pattern gia' usato altrove nel repo per script
standalone di notifica).

FIX 29/07 quinquies (richiesta esplicita utente: aprire direttamente il viewer
gia' organizzato invece di scaricare il CSV grezzo e aprirlo a mano col
viewer): il link ora punta a raw.githack.com (CDN che serve raw.githubusercontent.com
con Content-Type text/html corretto, cosi' il browser lo RENDE invece di
scaricarlo -- funziona solo per repo PUBBLICI, verificato che questo repo lo e'
tramite `gh repo view --json isPrivate`) con scanners/bot_profit_viewer.html
+ query param ?csv=<link raw del CSV>, che il viewer (vedi
autoLoadFromQueryParam in quel file) scarica e carica da solo appena la
pagina si apre -- un clic e la classifica e' gia' pronta, niente
download/drag&drop manuale.
"""
import glob
import os

import requests

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GIT_REF = os.environ.get('GIT_REF', 'main').strip() or 'main'
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()

OUTPUT_DIR = 'bot_profit_output'
GROUP_LABELS = {'mlspa': 'MLS', 'k-league-1': 'K-League', 'eredivisie_belgio': 'Eredivisie+Belgio'}
VIEWER_PATH = 'scanners/bot_profit_viewer.html'


def _latest_csv_for_group(group_name):
    candidates = sorted(glob.glob(os.path.join(OUTPUT_DIR, f'profit_tracking_{group_name}_*.csv')))
    return candidates[-1] if candidates else None


def _raw_url(path):
    path_url = path.replace(os.sep, '/')
    return f"https://raw.githubusercontent.com/{REPO_SLUG}/{GIT_REF}/{path_url}"


def _viewer_url(csv_path):
    viewer_base = f"https://raw.githack.com/{REPO_SLUG}/{GIT_REF}/{VIEWER_PATH}"
    return f"{viewer_base}?csv={_raw_url(csv_path)}"


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[bot_profit_telegram_notify] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID mancanti, salto la notifica.")
        return

    righe = []
    for group_name, label in GROUP_LABELS.items():
        path = _latest_csv_for_group(group_name)
        if path:
            righe.append(f"\U0001F4CA <a href=\"{_viewer_url(path)}\">{label}: apri viewer</a>")
        else:
            righe.append(f"⚠️ {label}: nessun CSV trovato in questa run.")

    message = "<b>Bot Profit -- run completata</b>\n" + "\n".join(righe)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"[bot_profit_telegram_notify] errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        print(f"[bot_profit_telegram_notify] errore invio Telegram: {e}")


if __name__ == '__main__':
    main()
