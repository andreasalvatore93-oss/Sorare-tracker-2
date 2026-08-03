# Sessione 4 agosto 2026 — fix leak, generatore vero nel backtest, bilancio pulito, capitano

## FILONE CAPITANO DEF/MID/FWD — fatto il primo test, PROSSIMO PASSO sotto

L'utente è già convinto di **escludere il portiere** dalla scelta capitano
(non solo penalizzarlo col margine GK_CAPTAIN_MARGIN=6.7,
`formazione_mls/build_formazione_finale.py:1445-1467`). Restava da capire se
tra i 4 slot rimanenti (oggi `pick_captain()` sceglie DEF/MID/FWD solo per
atteso grezzo più alto, nessuna correzione di ruolo) uno dei tre ruoli
sovra/sottostimi il reale piu' degli altri nella "zona capitano" (atteso≥55),
come succede per GK.

**Test fatto**: `formazione_mls/diagnostics/analyze_captain_bias_outfield.py`
(nuovo file, committato), riusa la raccolta dati di `analyze_gk_captain_value.py`
(nessuna nuova query, parametri ufficiali di produzione). Esteso anche
`analyze_gk_captain_value.py` per scoprire automaticamente TUTTE le 53 leghe
(prima ne usava solo 10 su una lista fissa — buco scoperto dall'utente,
mancavano Francia/Germania/Inghilterra/Italia/Giappone/Turchia e altre 17).

**Risultato (53 leghe, zona capitano atteso≥55)**:
  DEF n=2294 bias=-8.37  MID n=2213 bias=-6.00  FWD n=1552 bias=-7.37
  Gap DEF vs MID: -2.37pt (per confronto, il gap GK-vs-movimento che ha
  giustificato GK_CAPTAIN_MARGIN era +6.69pt — qui e' circa 1/3).

**COSA DICE E COSA NON DICE QUESTO TEST (richiesta esplicita dell'utente,
non equivocare)**: dice solo che, IN MEDIA, il DEF non è il ruolo migliore
da capitanare rispetto a MID/FWD — un bias osservato su tutte le partite
della fascia, non una regola operativa. NON dice:
- se un margine/correzione applicato davvero a `pick_captain()` migliori il
  risultato reale (serve un backtest della POLICY, non solo il bias astratto);
- se il gap sia stabile per singola lega/periodo o sia una media che nasconde
  variazione forte (es. potrebbe essere trascinato da poche leghe/giocatori);
- cosa succeda ai casi non-DEF/MID/FWD-puri (es. formazioni dove il migliore
  per atteso NON è comunque un DEF/MID/FWD "tipico" della zona capitano).

**PROSSIMO PASSO**: backtest della policy vera (capitanare MID a parità
quasi-di-atteso invece di DEF/FWD) e verificare con la regola del CLAUDE.md
(MAE + correlazione + lift di selezione insieme, mai il MAE da solo) prima
di toccare `pick_captain()`. Nessuna nuova query: tutto già in cache.

## Cosa è stato fatto oggi (tutto committato su main salvo dove indicato)

### 1) Fix del data leak nel backtest arene
`backtest_arene_previsioni.py`/`backtest_arene.py`: il cutoff per L10/storico
usava la data della partita-bersaglio del singolo giocatore invece
dell'inizio-giornata (primo kickoff fra tutte le carte usate quel giorno) —
un giocatore con 2+ partite nella stessa finestra-giornata vedeva risultati
della giornata stessa nella propria storia. Verificato: 17→0 carte
contaminate su football-1-5-may-2026.

### 2) Nuovo backtest agganciato al generatore VERO
`backtest_arene_produzione.py` (nuovo file). Prima versione (build_one_lineup
grezzo, priorità fissa inventata) bocciata dall'utente. Versione corretta:
chiama `generatore_formazioni/build_formazione_globale.py` per davvero —
calibrazione per ruolo (`calibra_riga`), struttura multi-lega (pool dedicato
per-lega + pool misto), `genera_arene_efficienti` chiamata una volta sola con
tutti i tipi insieme (decide da sola tipo/quantità in base alla resa attesa).
Beginner registrata come tipo economico a sé (`ARENA_BEGINNER`, soglia 264.1,
guadagno/punto 2.85, costo 100 — dati reali da `backtest_arene_economia.py`,
non inventati): senza questo, veniva confusa con cap260 (soglia simile,
guadagno molto diverso) e il confronto risultava falsato.

### 3) Bug di dati scoperto: arene multi-ingresso
Alcune arene vengono giocate più volte lo stesso giorno (stesso slug in
`arene_storico.json`, righe diverse con punteggi diversi), ma
`arene_formazioni.json` ne registra spesso **una sola**, e in almeno un caso
reale con `mio_score` disallineato dalla somma delle carte elencate
(363.88 dichiarato, carte che sommano 221.66 — probabile bug di scraping,
score abbinato al lineup sbagliato). `bilancio_stesse_carte()` scarta questi
casi con un controllo di integrità (somma carte vs mio_score, tolleranza
0.5pt) invece di fidarsi ciecamente.

### 4) Metodo di confronto definitivo: "stesse carte"
Deciso con l'utente dopo diversi tentativi scartati (riallocazione libera del
pool = troppo sporco, arbitrario quale carta va in quale arena). Metodo
finale, in `backtest_arene_produzione.bilancio_stesse_carte()`:
- Arene division (Korea/Belgio/Olanda/Turchia/MLS dedicate) **escluse del
  tutto**: quelle carte non esistono per il bot.
- Per ogni arena reale rimasta, il bot valuta le **stesse identiche 5 carte**
  che l'utente ha usato lì (mai altre). Decide solo entra/non entra
  (resa attesa = (atteso_capitanato - soglia) × guadagno/punto del tipo,
  economia REALE per tipo). Se entra, il capitano è scelto sull'atteso (può
  differire dal capitano reale dell'utente — verificato che è l'unica causa
  possibile di punteggi diversi a parità di carte).
- Se entra, il punteggio/rank/premio è quello VERO sullo stesso campo reale
  di 10 punteggi — nessun abbinamento arbitrario, nessuna riallocazione.
- Se salta, si sa comunque cosa avrebbe fatto (stesse carte = risultato
  certo): "risparmiate" (avrebbe perso) vs "occasione persa" (avrebbe vinto).

Risultato su football-1-5-may-2026 (28 arene valide): utente netto +2000,
bot netto (solo giocate) +1750, risparmio +100, occasione persa -50 →
**bot netto totale +1900** vs utente +2000 — quasi pari, differenza quasi
tutta nella scelta del capitano.

Batch completo 71 giornate (76 secondi): 354/673 arene utilizzabili (113
division escluse, 119 dati incoerenti/mancanti, resto senza previsione
walk-forward). **ATTENZIONE**: l'utente ha detto di aver giocato 870 arene
reali in totale, ma `arene_storico.json` ne ha solo 673 — buco di ~197 MAI
SPIEGATO, non ignorarlo se si riprende questo filone. Totale sulle 354:
utente netto -5400, bot netto totale +5800 — ma **non è il vero P&L
dell'utente** (quello è +13% ROI su 870 arene secondo l'utente), è solo il
risultato sul sottoinsieme testabile, probabilmente non rappresentativo
(le arene division escluse potrebbero essere le più profittevoli).

### 5) Trovato `dati_globali/manager_forever-young.json`
Dataset scaricato in precedenti sessioni, mai usato: le arene REALI di un
altro manager Sorare (forever-young), 71 giornate, 3352 righe, 3326 con
carte+piazzamento. Corrisponde al backlog aperto "walk-forward su
forever-young" (l'unico test che dice se il modello batte un manager vero,
non solo l'utente). **Manca il campo con tutti e 10 i punteggi del campo**
(solo rank/punteggio del manager stesso) — niente rank/premio ricostruibile,
solo confronto in punti.

Filtrate le sue arene a Cap 260/Cap 220/Uncapped (395, 388 con carte —
escluse Beginner e le arene per-lega dedicate, altri filoni mai aperti:
Under 23, In-Season, Champion/Challenger/Hot Streak per lega...). Confronto
stesse-carte-solo-punti: 157/388 valutabili (231 scartate, carte senza
storico sufficiente in cache — verosimile, mai processate dal modello
prima). Bot entra in 143/157. Sulle giocate: forever-young media 265.7,
bot media 266.6 (+0.9 pt/arena) — sostanzialmente alla pari, leggero
vantaggio bot specialmente su Uncapped (293.0 vs 284.1). 46/96 su cap260
hanno scelto lo stesso identico capitano (punteggio identico al centesimo,
matematicamente possibile solo così); sulle altre 50 le differenze sono
ampie (-11.2/+14.3) e quasi si compensano (30 volte meglio forever-young,
20 volte meglio il bot) → da qui è partito il filone capitano.

## Non committato / da verificare
- Buco 673 vs 870 arene reali dell'utente (vedi sopra) — MAI spiegato.
- Script per il confronto forever-young: solo in temp, cancellato a fine
  sessione — da riscrivere se si riprende il filone (logica: vedi punto 5).
