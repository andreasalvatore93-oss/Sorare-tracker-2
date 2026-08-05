# VALIDAZIONE SOGLIE ARENA — sono corrette?

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
σ per tipo su `backtest_arene_dettaglio_0805.json` (n=323, modello attuale):
cap 260 **50.6**, arena division 42.8, Uncapped 42.9, Beginner 46.9,
cap 220 41.9. Confermato su 2 dataset in più (utente 2 ago: cap 260 54.1;
manager: cap 260 54.1). → σ=42.70 va bene per tutti TRANNE cap 260 (~51).

`consiglio_arena.py` con SIGMA=42.70 ristampa ESATTAMENTE le soglie di
produzione (cap 260 265.0, cap 220 244.1, uncapped 288.3, elite 342.7,
guadagno/punto 8.83): catena intatta. Con la σ corretta della cap 260:

    cap 260   sigma 42.70 -> pareggio 265.0  guadagno/punto 8.83  (ATTUALE)
    cap 260   sigma 51.0  -> pareggio 259.0  guadagno/punto 7.92  (PROPOSTO)
    cap 260   sigma 55.0  -> pareggio 256.1  guadagno/punto 7.41  (sensibilità)

Effetto pratico: la cap 260 (arena +37.6% ROI) diventa conveniente a partire da
259 invece di 265 → poche formazioni marginali in più schierate lì invece che
nelle competizioni gratuite. Modesto ma +EV e ben fondato.

## Decisione aperta + catena §1bis
Applicare in `build_formazione_globale.py`: PAREGGIO_ARENA['ARENA_ALLSTARS_260']
265.0→259.0 e GUADAGNO_PER_PUNTO['ARENA_ALLSTARS_260'] 8.8→7.9. Poi, per la
catena di produzione, riverificare che lo scouting (colonne margine/Ess-GW,
soglie cap 260) resti coerente. NON applicato: da decidere con l'utente.
