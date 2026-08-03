# Sessione 3 agosto 2026 — SCOPERTA: i test delle arene sono falsati

## Verdetto
I backtest (`backtest_arene.py`) usati per calibrare le soglie di pareggio delle arene hanno un **data leak critico**: le partite della giornata stessa (prima della partita-bersaglio del giocatore) finiscono nell'L10 e nella previsione. Su football-1-5-may-2026: 17 carte su 166 contaminate. **Le soglie attuali sono sospette e vanno ricallibrate col cutoff corretto.**

## Lavori committati
- **Modello unico su 53 leghe** (commit `4272e98aab`): canonico in `formazione_mls/predict/*.py`, propagato con `propaga_modello.py`. Prima ogni lega aveva copie divergenti — ora un cambio vale per tutte.
- **GK blend porta inviolata** (stesso commit): `GK_TEAM_CS_WEIGHT=0.5` applicato (lift selezione 0.3%→9.4%, corr ×3). Vale su tutte le leghe e nello scouting.
- **Scouting riparato**: odds bulk, report riusa pool, link Telegram con SHA immutabile.

## Cosa serve subito
1. Correggere il cutoff in `backtest_arene_previsioni.py`: usare il **blocco della giornata** (primo kickoff), non la data della partita-bersaglio del giocatore.
2. Rilanciare i test completi e ricalcolare le soglie.
3. Verificare che il leak sparisca: 17 carte → 0 carte contaminate sulla giornata di test.

Handoff dettagliato: `HANDOFF_LEAK_ARENE_test_da_rifare.txt` (scaricato).

## Non committato
- Parametro `--fixture` in `backtest_arene.py` per girare una sola giornata (ivi aggiunto ma non su main).
- Allocatore di produzione nel backtest (da fare dopo il fix del leak).

## Note
- La **produzione** NON è rotta: prevede giornate future, nessun leak. Il leak riguarda solo il backtest (rigioca il passato).
- L'agente precedente ha dichiarato "nessun leak" senza verificare → scoperta più tardi → furore giustificato.
