# Riassunto Cerbero

*Per chi legge senza contesto: questo spiega cos'è Cerbero, perché esiste, come funziona e come si usa.*

## Da dove nasce
Nel repo esistono due bot per il mercato carte **Sorare** (fantacalcio con carte digitali `limited` scambiabili):
- **Bot Profit** (`scanners/bot_profit.py`): uno **scanner**, non compra. Dice quali carte conviene comprare, misurando lo **sconto del prezzo minimo rispetto alla media delle vendite recenti** della carta.
- **Bot Definitivo** (`bots/bot_definitivo.py`): **compra e offre in automatico** (con firma crittografata del wallet). Decide in base allo **spread tra 1° e 2° prezzo live** (mispricing istantaneo tra venditori). Non guarda la storia della carta.

I due ragionano in modo diverso e non si parlano. **Cerbero** è un **terzo bot nuovo** che **unisce le due logiche**, senza toccare i due originali (che restano intatti e funzionanti). Obiettivo: **profitto assoluto in euro** comprando carte davvero sottoprezzo per rivenderle.

## Cosa fa e come ragiona (regola a DUE ASSI, in AND)
Cerbero è **reattivo**: ascolta il flusso di *tutti* gli eventi di mercato (tutte le leghe, costo query quasi nullo). Per ogni carta che diventa un candidato:
1. **Asse trasversale (da Bot Definitivo):** c'è uno spread sfruttabile tra 1° e 2° prezzo live? Decide *se* e *a che prezzo* comprare/offrire.
2. **Asse temporale (da Bot Profit):** il prezzo è davvero **sotto la media delle vendite recenti tra manager** (aste escluse), con trend non in caduta, e con **guadagno assoluto atteso** sopra una soglia minima? Se no, **scarta** — anche se lo spread sembra un affare.

Agisce **solo se entrambi gli assi concordano**. Questo chiude il buco di Definitivo, che comprava annunci bassi senza sapere se la carta valesse davvero di più (caso reale: Song Bumkeun, minimo sopra la media reale → scartato giusto; Griezmann a metà floor → colto, era un affare vero).

## Come è stato costruito
- Generato **da `bot_definitivo.py`** (riusa verbatim il motore provato: query, rate-limit, **firma/acquisto/offerta**, timer auto-annullo offerte, bid periodico) e ci è stato **innestato il gate temporale** (`bots/cerbero/motore_affare.py`).
- **Calibrato su dati reali**: backtest su `bot_profit_output/pattern_raw_transactions_*.csv` (~6500 transazioni, 12 giorni, aste già escluse). Il gate separa i vincenti dai perdenti con **lift +8-10 punti** di rendimento a 48h.
- Scelte tarate sui dati: **lookback 1 giorno** (la media a 7gg di Profit era arbitraria; 1gg è il migliore e su MLS cambia il segno); **soglia guadagno assoluto ~0,50€** (oltre peggiora: spinge su carte care senza edge); **trend** su finestra separata (1gg vs 1-3gg).
- **Soglie di sconto adattive PER CAMPIONATO** (`cerbero_soglie_apprese.json`): le leghe note dal backtest hanno la loro soglia; le leghe mai viste usano un **default prudente (10%)**.

## Come impara (auto-adattamento)
Cerbero deve migliorare da solo dal mercato:
1. Girando in **diagnostica** registra ogni candidato in `cerbero_osservazioni.csv` (prezzo, sconto, lega, ora), **commit automatico ogni 5 minuti** (se la run si interrompe, non perde nulla).
2. `bots/cerbero/cerbero_learn.py --osservazioni` è il **risolutore forward**: dopo ~2 giorni misura il **prezzo reale della carta nelle 48h successive** a ogni osservazione (aste escluse) → capisce se lo sconto è diventato profitto → **impara la soglia giusta per ogni lega** (anche quelle nuove) e la scrive nel JSON, che il gate rilegge alla run dopo. Auto-migliorante, su **tutto il mercato**.

## Stato e come si usa
- **Diagnostica-first**: acquisto/offerta reali **spenti** di default (impara senza rischiare soldi).
- Si lancia da GitHub → **Actions → "Cerbero (diagnostica)" → Run workflow** (default: **5 ore**, commit ogni 5 min, tutte le leghe). Servono i secret Sorare freschi (cookie/csrf).
- Lista nera **dedicata** (`sorare_lista_nera_cerbero.txt`), separata dagli altri bot.
- **Prossimo passo:** accumulare osservazioni per qualche giorno, poi far girare il risolutore per imparare le soglie di tutte le leghe; validare; solo dopo valutare il passaggio in live.

## File chiave
- `bots/cerbero/cerbero.py` — il bot (reattivo + gate + esecuzione, diagnostica-first).
- `bots/cerbero/motore_affare.py` — il gate temporale e le soglie per-lega.
- `bots/cerbero/cerbero_learn.py` — impara le soglie (dal dataset e dalle osservazioni live).
- `bots/cerbero/backtest_e_test.py` — test + backtest riproducibili (zero query).
- `cerbero_soglie_apprese.json` / `cerbero_osservazioni.csv` — soglie apprese / dati di apprendimento.
- `.github/workflows/bot_cerbero.yml` — workflow diagnostica 5h.
- `docs/BOT_CERBERO_PROGETTO.md` — dettaglio tecnico completo.
