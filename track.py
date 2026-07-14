import json
import urllib.request
import urllib.error
import os
import datetime

# Configurazione
TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

def log(message):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

url_msg = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {'chat_id': CHAT_ID, 'text': 'Test finale'}
data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url_msg, data=data, headers={'Content-Type': 'application/json'}, method='POST')

try:
    with urllib.request.urlopen(req, timeout=5) as response:
        log("INVIO RIUSCITO!")
except urllib.error.HTTPError as e:
    # Qui leggiamo la spiegazione dettagliata di Telegram
    error_body = e.read().decode()
    log(f"ERRORE SPECIFICO DA TELEGRAM: {error_body}")
except Exception as e:
    log(f"ERRORE GENERALE: {e}")
