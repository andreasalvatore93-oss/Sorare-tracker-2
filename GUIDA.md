# Sorare Price Tracker — guida passo-passo

Nessuna programmazione richiesta. Segui questi passaggi una volta sola,
poi il sistema lavora da solo 24/7 e ti scrive una email quando una
carta scende sotto la soglia che imposti.

**Non serve la password di Sorare**: i prezzi del transfer market sono
pubblici, quindi non devi inserire le tue credenziali da nessuna parte.

## 1. Crea un account GitHub (gratis)
Vai su https://github.com/signup e registrati con la tua email.

## 2. Crea un nuovo repository
- In alto a destra premi il "+" -> "New repository"
- Nome: `sorare-tracker` (o quello che vuoi)
- Deve essere **Public** (i workflow gratuiti richiedono repo pubblico, oppure privato con account gratuito comunque incluso, va bene entrambi)
- Premi "Create repository"

## 3. Carica i file
Nella pagina del repo appena creato, premi "uploading an existing file"
e trascina dentro TUTTI i file e le cartelle che trovi in questo pacchetto
(compresa la cartella `.github` con dentro `workflows/check.yml` —
GitHub la riconosce automaticamente anche caricandola trascinata).
Poi premi "Commit changes".

## 4. Crea una "app password" Gmail (per inviare le email)
Il tuo account Gmail normale non basta, serve una password dedicata:
1. Vai su https://myaccount.google.com/apppasswords
2. Se richiesto, attiva prima la verifica in 2 passaggi (obbligatoria per le app password)
3. Crea una nuova app password, dalle un nome tipo "sorare-tracker"
4. Copia la password di 16 caratteri che ti viene mostrata (senza spazi)

## 5. Inserisci i "secrets" su GitHub
Nel tuo repository: Settings -> Secrets and variables -> Actions -> "New repository secret"

Crea questi 3 secrets:
- `GMAIL_ADDRESS` = la tua email gmail (es. tuonome@gmail.com)
- `GMAIL_APP_PASSWORD` = la password di 16 caratteri del punto 4
- `NOTIFY_EMAIL` = l'email dove vuoi ricevere gli avvisi (può essere la stessa)

## 6. Avvia il primo test manuale
- Vai su "Actions" (in alto nel repo)
- Se richiesto, premi "I understand my workflows, go ahead and enable them"
- Clicca su "Sorare Price Check" a sinistra
- Premi "Run workflow" -> "Run workflow"
- Aspetta ~30 secondi, poi apri l'esecuzione e guarda i log

Se vedi righe tipo "prezzo piu' basso trovato: ..." ha funzionato.
Se vedi "ERRORE nella query", copiami il messaggio di errore esatto e
te lo sistemo subito.

Da questo momento in poi il controllo parte da solo ogni 15 minuti,
senza che tu debba fare nulla.

## 7. Come modificare i giocatori da monitorare
Apri il file `config.json` nel repository (icona matita per modificarlo
online, non serve scaricare nulla) e aggiungi una voce per ogni carta
che vuoi seguire, per esempio:

```json
{
  "trackers": [
    {
      "name": "Mbappe Limited In-Season",
      "player_slug": "kylian-mbappe",
      "rarity": "limited",
      "in_season_only": true,
      "max_price_eur": 100
    },
    {
      "name": "Haaland Rare In-Season",
      "player_slug": "erling-haaland",
      "rarity": "rare",
      "in_season_only": true,
      "max_price_eur": 300
    }
  ]
}
```

Note sui campi:
- `player_slug`: la parte finale dell'URL della pagina del giocatore su
  sorare.com, es. per `sorare.com/football/players/kylian-mbappe/description`
  lo slug e' `kylian-mbappe`
- `rarity`: uno tra `limited`, `rare`, `super_rare`, `unique`
- `in_season_only`: `true` se vuoi solo carte della stagione in corso,
  `false` per includere anche le stagioni passate
- `max_price_eur`: soglia di prezzo in euro

Dopo aver salvato la modifica su GitHub, il prossimo controllo (entro
15 minuti) usera' gia' la nuova configurazione.

## Note importanti
- Ricevi una email solo quando compare un prezzo piu' basso di quello
  gia' notificato in precedenza (niente spam ad ogni controllo).
- Se il prezzo risale sopra soglia e poi ridiscende, ricevi una nuova email.
- Tutto e' gratuito: GitHub Actions offre minuti gratuiti piu' che
  sufficienti per un controllo ogni 15 minuti.
