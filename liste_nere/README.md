# Liste nere del repo — indice di orientamento

Solo documentazione, per orientarsi tra i file di blacklist sparsi nella root del
repo. **Nessun file è stato spostato**: ogni lista resta esattamente dove i bot
se l'aspettano, i percorsi letti dal codice non sono cambiati.

## Attive

| File (nella root del repo) | Letta da | Note |
|---|---|---|
| `sorare_lista_nera.txt` | `bots/bot_definitivo.py` | **La lista nera in uso**, unico file attivo per il bot in produzione. Sezioni: `manager`, `giocatore`, `cooldown_acquisto`, `thin_market`, `campionato`, `campionato_inseason_temp`, `forma_bassa_ultime_5`. |
| `sorare_lista_nera_profit.txt` | `scanners/bot_profit.py` | Lista nera separata per Bot Profit (tracking, no play). |

## Legacy — non più lette a runtime

Questi file esistevano prima che `bot_definitivo.py` unificasse tutto in
`sorare_lista_nera.txt`. Restano nel codice solo come **sorgente di migrazione
una tantum** (`_LEGACY_FILES_DA_MIGRARE` in `bot_definitivo.py`): vengono letti
SOLO se `sorare_lista_nera.txt` non esiste ancora. Dato che esiste già, questi
file non vengono più letti ad ogni run.

| File | Migrato in | Bot storico che lo usava |
|---|---|---|
| `sorare_blacklist.txt` | `sorare_lista_nera.txt` (`giocatore`) | `bots/autobuy_sorare.py` |
| `sorare_autobuy_blacklist.txt` | `sorare_lista_nera.txt` (`giocatore`) | `bots/autobuy_sorare.py` |
| `sorare_manager_blacklist.txt` | `sorare_lista_nera.txt` (`manager`) | -- |
| `sorare_autobuy_manager_blacklist.txt` | `sorare_lista_nera.txt` (`manager`) | `bots/autobuy_sorare.py` |
| `sorare_makeoffer_manager_blacklist.txt` | `sorare_lista_nera.txt` (`manager`) | `bots/makeoffer_sorare.py` |

## Orfana

| File | Stato |
|---|---|
| `sorare_lista_nera_aste.txt` | Usata da `bot_supremo_aste.py`, archiviato sul branch `archive/bot-supremo` (26/07) — nessuno script in `main` la legge più. Non cancellata per ora, solo segnalata qui. |

## Se serve pulizia vera in futuro

Questo indice non tocca nulla. Se un giorno si vuole davvero spostare/eliminare
i file legacy o quello orfano, farlo in una sessione dedicata (aggiornando i
riferimenti nel codice se serve), non come parte di questa organizzazione.
