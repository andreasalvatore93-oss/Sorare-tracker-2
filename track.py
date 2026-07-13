def check_player(player_data, state):
    slug = player_data['slug']
    p_id = player_data['id']
    
    url = 'https://api.sorare.com/graphql'
    # Questa query è più ampia e dovrebbe includere tutti i dati di mercato
    payload = {
        "operationName": "MarketplaceSearchQuery", 
        "variables": {"slugs": [slug], "rarities": ["limited"]},
        "extensions": {"operationId": "React/8651c890918738321287968531764014e854f4ba174c338"} 
    }
    
    headers = {
        'Content-Type': 'application/json', 
        'Cookie': COOKIES, 
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        
        # Estrattore dati Marketplace (logica diversa da AnyPlayer)
        results = data.get('data', {}).get('cards', {}).get('nodes', [])
        
        # Filtriamo le offerte attive (senza distinzione Classic/In-Season, prendiamo il minimo assoluto)
        prices = []
        for card in results:
            offer = card.get('liveSingleSaleOffer')
            if offer:
                cents = offer.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if cents: prices.append(cents)
        
        if not prices:
            print(f"{p_id}: Nessuna offerta attiva trovata.")
            return
            
        price = min(prices) / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"Variazione {p_id}: {old_price}€ -> {price}€")
            send_email(f"Notifica Sorare: {p_id}", f"Prezzo minimo {p_id} aggiornato: {price}€")
            state[p_id] = price
        else:
            print(f"{p_id}: {price}€ (nessuna variazione)")
            
    except Exception as e:
        print(f"Errore su {p_id}: {e}")
