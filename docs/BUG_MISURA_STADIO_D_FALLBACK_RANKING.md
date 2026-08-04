# Bug di misura: "canale avversario spento" su DEF non voleva dire quello che pensavamo

Data: 2026-08-04. Trovato durante BRIEF_risolutivo_produzione, sezione 4.C
dell'handoff `docs/handoff/HANDOFF_risolutivo_produzione_2026-08-04.txt`.

## Il bug

In `formazione_mls/predict/test_def.py`, `compute_score_atteso_def()`, quando
`opponent_team_slugs_hist`/`next_opponent_team_slug` non sono passati, lo
Stadio D (condizionamento gol_subiti/passaggio/clean_sheet su "avversario
forte/debole") NON si disattiva: ricade su un fallback che usa
`domesticLeagueRanking` -- la variabile CONGELATA perché contaminata
(`docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md`, sez. 33.A, 29/07).

`backtest_arene_previsioni.py` (il banco di misura), quando chiamato con
`usa_avversario=False`, non passa quei due argomenti. Tre sessioni di fila
(`HANDOFF_banco_e_rimisura_2026-08-04.txt`,
`HANDOFF_griglia_estesa_e_split_2026-08-04.txt`,
`HANDOFF_baseline_canale_fwd_split_2026-08-04.txt`) hanno quindi misurato
"canale SPENTO" credendo di misurare "nessuna correzione Stadio D", mentre
in realtà misuravano "Stadio D sul ranking contaminato invece che sui gol
reali". La differenza è invisibile finché non si legge la funzione riga per
riga con questo sospetto specifico in mente.

## Perché è importante

Il numero che sembrava il miglior risultato della giornata (DEF, canale
"spento": MAE 14.9423, corr 0.1905, lift 16.91, tutte e tre migliori del
canale acceso) era quel fallback, non uno spegnimento vero. Misurato lo
spegnimento VERO (nessuna correzione Stadio D, né dal dato pulito né dal
fallback), il risultato contro la produzione attuale è MISTO (MAE e corr
leggermente peggio, lift meglio) e non passa il metro delle tre misure
insieme. Il DEF NON è stato toccato in produzione per questo motivo
(decisione presa, vedi handoff sopra).

## La regola da portarsi dietro

Quando un banco di misura testa "cosa succede se una correzione è spenta"
passando `None`/ometttendo un argomento invece di un flag esplicito
dedicato, verificare SEMPRE cosa succede internamente alla funzione quando
quell'argomento è `None` — potrebbe esserci un fallback silenzioso a un'altra
fonte di dati, non un vero "niente". Il modo pulito per testarlo: un
parametro booleano esplicito (`use_stadio_d`), non l'assenza di un dato.

Prima di fidarsi di una baseline "spento" misurata da un banco, riprodurla
chiamando la funzione di produzione direttamente con l'interruttore esplicito
e zero dati opzionali, e confrontare a piena precisione (non 3-4 decimali)
col numero del banco. Se non coincidono, il banco non sta misurando quello
che si crede.
