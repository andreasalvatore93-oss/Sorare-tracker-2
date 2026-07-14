import json
import urllib.request
import os
import datetime

# Configurazione
TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

def log(message):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

# 1. TEST TOKEN
url_get_me = f"https://api.telegram.org/bot{TOKEN}/getMe"
try:
    with urllib.request.urlopen(url_get_me, timeout=5) as response:
        data = json.loads(response.read().decode())
        log(f"TOKEN VALIDO! Nome bot: {data['result']['first_name']}")
except Exception as e:
    log(f"ERRORE TOKEN: {e}. Controlla il TELEGRAM_TOKEN nei Secrets!")

# 2. TEST CHAT_ID
log(f"CHAT_ID in uso: '{CHAT_ID}'")
if not CHAT_ID:
    log("ERRORE: Il CHAT_ID è vuoto o non caricato!")
else:
    # Proviamo a mandare un messaggio di test ma catturiamo l'errore specifico
    url_msg = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': 'Test'}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url_msg, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            log("INVIO RIUSCITO!")
    except Exception as e:
        log(f"ERRORE INVIO FINALE: {e}")
