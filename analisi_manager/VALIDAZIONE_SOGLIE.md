# VALIDAZIONE SOGLIE ARENA — sono corrette?

## AGGIORNAMENTO 08/08/2026 notte — riparato l'archivio, sigma su campione vero
Esito completo: `docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt`.
In breve, SOLO MISURA, nulla applicato:
- L'archivio (crollato a 160 arene, bug sotto) e' stato RICOSTRUITO a 673
  arene da `analisi_manager/p11_pool.json` -> `dati_globali/
  arene_storico_full.json` (file nuovo, non sovrascrive l'originale). Con
  l'archivio pieno e le sigma di produzione, cap260/cap220 tornano
  riproducibili entro 1-2 punti (258.1/244.3 contro 259.5/244.1).
- La sigma della cap 220 non poggia piu' su n=8: rimisurata su n=251
  (walk-forward su TUTTI i manager, 7.720 arene candidate). Anche gli
  altri tipi sono su campioni molto piu' larghi: cap260 n=1356, Beginner
  n=1472, Uncapped n=288.
- Soglie nuove (vecchio -> nuovo): cap260 259.5->258.3 (guad 7.9->7.51),
  cap220 244.1->241.0 (guad 6.3->5.46), Uncapped 288.3->281.9 (guad
  8.0->6.82), Beginner n/d->259.4 (guad n/d->2.78, mai avuta prima).
- Sul mazzo GW3 gia' generato: con le soglie nuove il mix passa da 23
  arene (22x260+1x220) a 26 (23x260+3x220). La Beginner non puo' entrare
  nel mix: il generatore non ha un tipo ARENA_ALLSTARS_BEGINNER.
- Bias non spiegato: l'Uncapped ha un residuo medio +9.4 (l'atteso
  sottostima il realizzato), non indagato oltre.

## AGGIORNAMENTO 07/08/2026 sera — bug piu' grave del previsto, non risolto
Esito completo: `docs/handoff/BRIEF_SONNET_SOGLIE_ARENA_2026-08-07.txt`
(sezione "ESITO"). In breve:
- `dati_globali/arene_storico.json` e' CROLLATO da 673 a 160 arene fra
  l'1/08 e il 6/08 (cap260 194→62, cap220 53→16, arena division 191→0,
  zero arene nuove nella versione attuale). E' questo che spiega lo scarto
  267.9/259.5 visto oggi, non un errore di scala. **Bug da investigare
  prima di toccare qualunque soglia.**
- Rivalidato con `dati_globali/manager_*.json` (9.889 partecipazioni): il
  pool di avversari e' molto piu' solido, ma i PREMI restano campionati
  solo dall'archivio (ora ancora piu' piccolo) perche' i file manager non
  registrano `premio_essenze`. cap220 e Uncapped restano sotto misura.
- A sigma=42.70 (stessa ipotesi di produzione): cap260 265.0→272.2 (+7.2),
  cap220 244.1→249.7 (+5.6). Salgono insieme, nessun segno di ribaltamento
  cap260/cap220. **Non applicare**: campione premi troppo debole.

Sessione **05/08/2026, ore ~04:30 (Roma, CEST)**. Domanda dell'utente: le
soglie di produzione (`PAREGGIO_ARENA`, `GUADAGNO_PER_PUNTO`, tarate su
σ=42.70) sono corrette, o vanno riviste? Usare TUTTI i dati.

Script: `analisi_manager/valida_soglie.py` (442 manager) e
`analisi_manager/valida_soglie_utente.py` (306 arene utente). Pure Python.

## Verdetto in una riga (AGGIORNATO col modello attuale)
**Una sola correzione solida: la σ della cap 260.** Rigenerato il backtest col
modello attuale (`backtest_arene_dettaglio_0805.json`, n=323) la σ è **~51 solo
per cap 260** (arena concentrata), mentre uncapped/cap220 sono ~43 = coerenti
con il 42.70 di produzione. Correggendo cap 260 a σ=51 via `consiglio_arena.py`:
**pareggio 265.0 → 259.0** e **guadagno/punto 8.8 → 7.9**. Gli altri tipi
restano invariati.

RETTIFICA di una mia stima precedente: avevo scritto "GUADAGNO sovrastimato
8.8 → ~5.4" regredendo l'incasso REALE sull'atteso. È SBAGLIATO: dentro cap 260
l'atteso non discrimina (corr +0.04) → quel 5.4 è attenuazione/rumore, non il
guadagno per punto vero. La catena giusta (consiglio_arena con σ corretta) dà
7.9. Il numero da usare è 7.9.

---

## Cronistoria: come sono nate le soglie (mancava nel riassunto)

1. **282.9 "se il punteggio fosse certo"** — primo pareggio, calcolato come
   punteggio a cui l'incasso medio (9 avversari da arene vere + premi reali)
   uguaglia il costo, MA assumendo di conoscere il punteggio.
2. **Scoperta dell'incertezza** — con previsione incerta la formazione può
   finire molto sopra la media e il premio cresce più che proporzionalmente
   (curva convessa): il pareggio VERO SCENDE. Backtest su 246/673 arene utente:
   `realizzato = 110 + 0.558·previsto`, previsioni ottimiste ~12 pt, σ~50,
   ordinamento monotono. Pareggio corretto ~259.6 reale (~268 grezzo).
3. **Rifatte via formazioni sintetiche (03/08)** — 40k formazioni da 5 col
   capitano da `taratura_coppie.json`: `realizzato = 63.43 + 0.736·previsto`,
   σ=42.70 → `consiglio_arena.py` con quella σ → soglie ATTUALI:
   PAREGGIO {cap260 265.0, cap220 244.1, uncapped 288.3, elite 342.7},
   GUADAGNO {8.8, 6.3, 8.0, 9.1}. Da qui è nato lo scouting: trovare carte con
   L10 basso ma atteso alto in quella GW per massimizzare il margine sul
   pareggio (→ essenze).

Il punto debole ereditato: le sintetiche sono 5 giocatori CASUALI dello stesso
giorno (quasi indipendenti); le arene vere sono CONCENTRATE (cap L10 → stessa
lega, spesso stesso club), e carte correlate = più dispersione. È il gancio col
Filone 3 (covarianza compagni +0.13 sul punteggio continuo).

---

## Prova 1 — 306 arene REALI dell'utente (popolazione giusta)

`backtest_arene_dettaglio.json`, atteso ricostruito. **Scala del 2 ago
(pre-ricalibrazione 3 ago)**: σ e ordinamento validi, il valore ASSOLUTO del
pareggio è solo indicativo. `terzo` = cutoff podio reale di ogni arena.

**LINK 1 — realizzato vs atteso** (n=306):
`realizzato = 21.34 + 0.884·atteso`, **σ=50.9** (produzione assume 42.70),
corr +0.217, bias +10.96 (atteso ottimista ~11, come nel 2018). sd atteso 12.8
vs sd realizzato 52.2 → l'atteso spiega r²=4.7%: a livello di decisione la
dispersione vera è ~51, non 42.70.

    tipo             n    sigma   corr(att,real)   bias
    cap 260        110    54.1      +0.021        +3.0
    arena division  74    43.5      +0.343       +11.8
    Uncapped        31    46.8      +0.513       +20.5
    Beginner        83    47.8      +0.020       +19.4
    cap 220          6    46.9      +0.267       +15.5

Dentro **cap 260** (l'arena principale) l'atteso NON discrimina (corr +0.02):
è la restrizione di range del cap L10 (Filone 1). Il valore del modello è nel
SCEGLIERE il tipo di arena e nella soglia d'ingresso, non nell'ordinare le
formazioni dentro una cap.

**LINK 2 — più atteso → più ritorno?** (quintili di atteso):

    Q  atteso  realizzato  premio  netto   podio%
    1  263.6    251.8       111    -133     21
    2  271.7    262.1       118    -123     25
    3  277.2    268.7       337    +112     49
    4  282.5    272.8       234      -1     39
    5  297.9    282.6       298     +23     42

Realizzato **monotòno** con l'atteso (252→283): l'ordinamento funziona, il
cuore dello scouting è valido. Il netto è rumoroso (premio a jackpot) ma il
taglio è netto: sotto atteso ~272 si PERDE (netto −130, podio ~23%), sopra si
è ≈pari/positivi (podio 39-49%). corr(atteso,premio) +0.122; AUC(atteso→podio)
0.597; podio complessivo 35% (contro 30% medio: il +6.7 pt di vantaggio noto).

**LINK 3 — netto vs atteso per tipo** (ess/punto e break-even, scala vecchia):

    tipo             n    ROI      ess/punto (prod)   break-even atteso
    cap 260        110  +37.6%     5.42  (8.8)            ~257
    arena division  74  -73.2%     4.70  (—)              ~320
    Uncapped        31  -10.8%     5.72  (8.0)            ~309
    Beginner        83  -38.0%     0.65  (—)              ~336

- **cap 260 = la miniera** (+37.6%, coerente col +21.4% storico).
- **arena division −73.2%**: conferma che disattivarla di default (04/08) era
  giusto. **Beginner ess/punto 0.65 ≈ piatto e −38%**: l'atteso lì non si
  converte in essenze, non giocarle.
- ess/punto qui ~5.4, ma è ATTENUAZIONE (dentro cap l'atteso non discrimina),
  non il guadagno vero — vedi rettifica in cima: la catena giusta dà 7.9.

Side: modello vs utente su 291 arene diverse — modello 272.6 vs utente 268.1
(+4.5 pt medi) ma vince solo il 47%: alza la media, non il piazzamento (arene
decise dalla varianza, non dall'atteso-somma).

---

## Prova 2 — 442 arene di 10 manager (scala attuale, popolazione diversa)

Popolazione più rumorosa (mix leghe, manager più deboli, atteso walk-forward):
utile come CONTROLLO di direzione, non per fissare i numeri del mazzo utente.

**LINK 1**: `realizzato = 75.47 + 0.657·previsto`, **σ=62.1** (vs 42.70), corr
+0.156. Residuo vs linea di produzione: bias −9.85 (la produzione sovrastima il
realizzato di ~10). Per comp: σ cap260 54.1, cap220 49.5, uncapped 44.4,
elite 86.8, beginner 63.8.

**LINK 2 (incasso vs margine)**: ess/punto reale cap260 **3.77** (prod 8.8),
cap220 6.79 (6.3), uncapped 10.87 (8.0), elite 9.89 (9.1). corr(margine,
incasso) cap260 +0.09, cap220 +0.18, uncapped +0.41, elite +0.11. Direzione
"più margine → più incasso" c'è ovunque (tutte positive, bin crescenti) ma
debole; cap 260 rende metà di quanto assunto.

---

## Cosa è CONFERMATO e cosa VA CAMBIATO

Confermato (non toccare): cap 260 è la miniera; arena division e Beginner
vanno evitate; l'atteso ordina il realizzato → scouting valido; dentro una cap
l'atteso non discrimina (valore a livello di tipo-arena/soglia).

Da rivedere: **solo la σ della cap 260** (unica correzione solida).

## Ricalibrazione fatta (modello attuale, scala di produzione)
σ cap 260 su 3 dataset: **50.6** (utente scala attuale, n=113), 54.1 (utente
2 ago), 54.1 (manager, n=199). Sempre chiaramente > 42.70. Gli altri tipi in
scala attuale: arena division 42.8, Uncapped 42.9, Beginner 46.9, cap 220 41.9
→ σ=42.70 va bene per tutti TRANNE cap 260.

**Cache backtest COMPLETA** (`scarica_cache_backtest.py --elenco`: solo 6
giocatori mancanti su tutte le 673 arene) → nessuna run GitHub serve, il
campione cap 260 non è cache-limitato. (Correzione a una mia ipotesi
precedente: il gap 323/426 arene ricostruite è formazioni senza storico/
capitano/data, non cache.)

**σ per lega dentro cap 260** (n=199 manager, hanno la lega): σ NON uniforme —
MLS (il grosso, 117) 47.1, kleague (16) 58.4, brasile (15) 40.1, argentina
(9, rumore) 78.5. E σ CRESCE col numero di leghe distinte (1 lega 45.8 → 5
leghe 80.1), non con la concentrazione di club. **Ritratto** la spiegazione
"concentrazione→covarianza→σ alta (Filone 3)": è smentita, la σ alta è
ETEROGENEITÀ fra leghe, non correlazione fra compagni.

`consiglio_arena.py` a SIGMA=42.70 ristampa ESATTAMENTE le soglie di produzione
(catena intatta). Con la σ corretta della cap 260:

    cap 260   sigma 42.70 -> pareggio 265.0  guadagno/punto 8.83  (ATTUALE)
    cap 260   sigma 47.0  -> pareggio 262.0  guadagno/punto 7.82  (MLS, lega dominante)
    cap 260   sigma 50.6  -> pareggio 259.5  guadagno/punto 7.93  (tua pop. attuale)
    cap 260   sigma 54.0  -> pareggio 256.9  guadagno/punto 7.46  (manager)

## VERDETTO (per la revisione)
σ=42.70 è **dimostrabilmente troppo bassa per cap 260** (reale 47–54, tua ~50.6):
robusto su 3 dataset. La correzione (**pareggio 265→259.5, guadagno 8.83→7.9**,
a σ=50.6) è più accurata, a basso rischio e reversibile, MA il guadagno pratico
è **piccolo** (entri in cap 260 da 259.5 invece di 265: poche formazioni
marginali; il tuo cap 260 tipico è ~270, ben sopra entrambe). Il limite più
profondo NON si risolve con la σ: dentro una cap l'atteso non discrimina
(corr +0.04) → il valore del modello è nella scelta del TIPO arena e nella
decisione d'ingresso (che vale +10350 essenze risparmiate nel backtest), non
nell'ordinare le formazioni dentro la cap.

**Conviction: media.** La σ è oggettivamente sbagliata, ma la posta è modesta.

## Catena §1bis — pronta su branch (NON su main)
La modifica è preparata su branch `soglia-cap260-sigma`, non applicata a main
(scelta con l'utente). Cosa tocca (verificato):
- `build_formazione_globale.py`: PAREGGIO_ARENA['ARENA_ALLSTARS_260'] 265.0→259.5,
  GUADAGNO_PER_PUNTO['ARENA_ALLSTARS_260'] 8.8→7.9 (+ commento con derivazione).
- **Propagazione automatica**: `scouting_gw.py`, `ottimizza_portafoglio_arene.py`,
  `backtest_arene_produzione.py` leggono le costanti dal generatore via
  `getattr(gg,...)` → si aggiornano da sole.
- `best_five.py` (deprecato) ha una copia hardcoded `PAREGGIO_ARENA_260=265.0`
  → sincronizzata a 259.5 sul branch per coerenza.
Per applicare: merge del branch. Nessun'altra dipendenza scoperta.
