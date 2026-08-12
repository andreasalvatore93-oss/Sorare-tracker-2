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
import os
import subprocess

import requests

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()


def _ref():
    """Il commit ESATTO che contiene l'HTML, non 'main': raw.githack.com cacha
    l'URL di un branch e servirebbe la copia VECCHIA del report. Lo SHA e'
    immutabile. Il notify gira dopo il push dell'HTML, quindi HEAD e' giusto."""
    try:
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        if sha:
            return sha
    except Exception:
        pass
    return os.environ.get('GIT_REF', 'main').strip() or 'main'

def _report_di_questa_run():
    """Il file che build_formazione_globale.py dichiara di aver scritto IN
    QUESTA RUN (_ultimo_report.txt). NON piu' un criterio per mtime (bug
    reale 12/08/2026: nel job 'formazione' i candidati non sono i file di
    questa run, sono i 132 HTML che actions/checkout ha appena ripristinato
    tutti insieme, con la stessa data -- 'il piu' recente per mtime' su file
    scritti nello stesso istante e' una lotteria: la notifica ha linkato
    run97 del 01/08 mentre su main c'era gia' run178 del 12/08). Se il file
    manca, il generatore non ha prodotto nulla in questa run: NON si
    notifica, invece di indovinare guardando il filesystem."""
    try:
        with open('_ultimo_report.txt', encoding='utf-8') as f:
            p = f.read().strip()
    except OSError:
        return None
    if os.path.isabs(p):
        # Difesa (12/08/2026): un sentinella con path ASSOLUTO produrrebbe un
        # URL rotto (.../<sha>//home/runner/...). Lo si riporta alla radice
        # del repo, che nel job e' la directory di lavoro.
        try:
            p = os.path.relpath(p, os.getcwd())
        except ValueError:
            return None
        if p.startswith('..'):
            return None
    return p if p and os.path.exists(p) else None


def _viewer_url(path):
    path_url = path.replace(os.sep, '/')
    return f"https://raw.githack.com/{REPO_SLUG}/{_ref()}/{path_url}"


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[formazione_telegram_notify] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID mancanti, salto la notifica.")
        return

    path = _report_di_questa_run()
    if not path:
        print("[formazione_telegram_notify] nessun report generato in questa run, salto la notifica.")
        return

    run_number = os.environ.get('GITHUB_RUN_NUMBER', '').strip()
    titolo = f"run completata (#{run_number})" if run_number else "run completata"
    message = f"⚽ <b>Formazione giornata -- {titolo}</b>\n<a href=\"{_viewer_url(path)}\">Apri il report</a>"
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
