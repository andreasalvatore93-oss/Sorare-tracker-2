import json

# Leggiamo il tuo attuale players.json
with open('players.json', 'r') as f:
    old_players = json.load(f)

# Prepariamo la nuova struttura per il registro
new_registry = []

for p in old_players:
    # Aggiungiamo i campi base. Il campo 'sorare_id' lo riempiremo nel prossimo step
    entry = {
        "id": p['id'],            # Il tuo ID interno (es. 'mbappe')
        "slug": p['slug'],        # Lo slug che stiamo usando
        "sorare_id": None         # Questo sarà l'ID univoco che cercheremo al passo 2
    }
    new_registry.append(entry)

# Salviamo il nuovo file
with open('players_registry.json', 'w') as f:
    json.dump(new_registry, f, indent=4)

print("Passo 1 completato: 'players_registry.json' creato correttamente.")
