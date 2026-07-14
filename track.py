import json
import os
import time
import smtplib
import re
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Configurazione
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')

def send_email(subject, body):
    if not EMAIL_USER or not EMAIL_PASS: return
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = NOTIFY_EMAIL
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Errore invio email: {e}")

def get_price_via_browser(url):
    """Apre il browser e legge il prezzo minimo direttamente dalla pagina"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Usiamo un user agent realistico per non essere bloccati
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        
        try:
            # Navighiamo alla pagina
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Diamo 2 secondi extra per caricare il contenuto dinamico (le carte)
            page.wait_for_timeout(2000)
            
            content = page.content()
            # Cerchiamo tutti i prezzi nel formato "eurCents" nel sorgente della pagina renderizzata
            prices = re.findall(r'"eurCents":(\d+)', content)
            
            browser.close()
            
            if prices:
                valid_prices = [int(p) for p in prices if int(p) > 0]
                if valid_prices:
                    return min(valid_prices) / 100
        except Exception as e:
            print(f"Errore navigazione: {e}")
            browser.close()
    return None

def check_player(player_data, state):
    p_id = player_data['id']
    slug = player_data['slug']
    url = f"https://sorare.com/it/football/players/{slug}"
    
    print(f"Analisi {p_id}...")
    price = get_price_via_browser(url)
    
    if price:
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"Variazione {p_id}: {old_price}€ -> {price}€")
            send_email(f"Notifica Sorare: {p_id}", f"Il prezzo minimo per {p_id} è ora {price}€")
            state[p_id] = price
        else:
            print(f"{p_id}: {price}€ (nessuna variazione)")
    else:
        print(f"{p_id}: Nessun prezzo trovato.")

# Esecuzione
with open('players_registry.json', 'r') as f:
    players = json.load(f)

try:
    with open('state.json', 'r') as f:
        state = json.load(f)
except:
    state = {}

for p in players:
    check_player(p, state)
    time.sleep(5) # Delay tra un giocatore e l'altro per sicurezza

with open('state.json', 'w') as f:
    json.dump(state, f)
