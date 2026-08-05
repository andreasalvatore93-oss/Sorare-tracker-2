# VALIDAZIONE SOGLIE ARENA — sono corrette?

Sessione **05/08/2026, ore ~04:30 (Roma, CEST)**. Domanda dell'utente: le
soglie di produzione (`PAREGGIO_ARENA`, `GUADAGNO_PER_PUNTO`, tarate su
σ=42.70) sono corrette, o vanno riviste? Usare TUTTI i dati.

Script: `analisi_manager/valida_soglie.py` (442 manager) e
`analisi_manager/valida_soglie_utente.py` (306 arene utente). Pure Python.

## Verdetto in una riga
**Vanno riviste.** Due tarature model-dipendenti sono sbagliate nello stesso
verso su DUE popolazioni indipendenti: **σ sottostimata** (42.70 vs reale
~51 utente / ~62 manager) e **GUADAGNO_PER_PUNTO sovrastimato** (8.8 vs reale
~5.4 utente / 3.77 manager, cap 260). Il resto conferma scelte già prese.

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
- **ess/punto reale ~5.4** contro 8.8 di produzione: il generatore SOVRASTIMA
  di ~60% il valore in essenze di ogni punto di margine.

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

Da rivedere (due input model-dipendenti, sbagliati su 2 popolazioni):
- **σ: 42.70 → ~51** (reale a decisione). Con σ più alta il pareggio vero
  SCENDE ancora (convessità): il generatore è un filo troppo conservativo.
- **GUADAGNO_PER_PUNTO: 8.8 → ~5.4** (cap 260). Sovrastima il valore del
  margine → lo scouting sovravaluta le carte ad alto atteso in assoluto (il
  ranking €/EssGW è un rapporto, si salva; il "conviene/non conviene" e i
  confronti fra tipi no).

**Caveat**: i dati utente sono in scala 2 ago → σ e ordinamento validi, i
valori ASSOLUTI di pareggio/ess-punto sono direzionali. Per fissare i NUMERI
nuovi di produzione serve rigenerare l'atteso in scala attuale.

## Prossimo passo proposto
Rigenerare `backtest_arene.py` col modello ATTUALE (verificato: legge le
costanti dai moduli di produzione, `GK_TEAM_CS_WEIGHT=0.5`, nessuna rete;
cache 133 gamelog → ~306 arene) su un file NUOVO (non sovrascrivere il 2 ago)
→ ricalcolare σ e GUADAGNO_PER_PUNTO in scala attuale → proporre
PAREGGIO/GUADAGNO aggiornati → poi riverificare lo scouting (catena §1bis).
