# BOT TERZO — unificazione Bot Profit + Bot Definitivo (stato al 03/08/2026)

Documento per chi riprende da zero. Il terzo bot **non sostituisce** i due esistenti:
`scanners/bot_profit.py` e `bots/bot_definitivo.py` **restano intatti e funzionanti**.
Il terzo bot è una cosa a sé, con **lista nera dedicata** (`sorare_lista_nera_terzo.txt`).

## 1. Perché esiste

I due bot rispondono a domande diverse e non si parlano:

- **Bot Definitivo** compra/offre in automatico. Definisce "affare" come **spread tra 1° e
  2° prezzo LIVE** (`(2°−1°)/2°`): mispricing istantaneo tra venditori. Non guarda la
  storia della carta né la partita. Copre quasi tutto il mercato perché è **reattivo**
  (ascolta gli eventi), a costo query ~0.
- **Bot Profit** è solo uno scanner (non compra). Definisce "affare" come **sconto del
  minimo rispetto alla media recente** della carta, pesato per finestra-partita. È
  **proattivo** (scandaglia i roster) → costo query alto, poche leghe.

I due segnali sono **ortogonali, non ridondanti**: uno è trasversale (vs altri venditori
ora), l'altro temporale (vs la storia della carta). Il terzo bot li combina.

## 2. Architettura (decisa con l'utente)

**Motore REATTIVO di Definitivo** (esecuzione + query + firma crittografata: codice
**provato**, copiato verbatim) **+ GATE TEMPORALE di Profit** innestato.

Regola d'ingresso a **due assi in AND**:
1. **Asse trasversale** (Definitivo, resta nel bot): spread 1°/2° live sopra le curve di
   margine già calibrate sulle preferenze reali dell'utente → decide *se* comprare/offrire
   *adesso* e *a che prezzo*.
2. **Asse temporale** (Profit, `bots/bot_terzo/motore_affare.py`): la carta è davvero sotto
   la sua media recente? trend non in caduta? guadagno assoluto atteso ≥ soglia? → se no,
   **si scarta anche se lo spread live sembra un affare**. È il filtro che oggi manca a
   Definitivo (compra un annuncio basso senza sapere se la carta valga davvero di più).

**Costo query zero** per l'asse temporale: le medie recenti si calcolano dagli **stessi
nodi transazione** che Definitivo già scarica per la liquidità (`_medie_temporali_da_nodi`,
un solo fetch riusato per liquidità + ultimo prezzo + medie temporali).

**Diagnostica-first**: `AUTOBUY_LIVE_MODE`/`MAKEOFFER_LIVE_MODE` default **`no`**. Il bot è
autonomo (può comprare/offrire) ma non tocca soldi finché non li si attiva esplicitamente.

## 3. Cosa dicono i dati (backtest 03/08)

Backtest sull'asse temporale su `bot_profit_output/pattern_raw_transactions_*.csv`
(**6452 transazioni uniche, ~12 giorni, solo leghe di Profit**, zero query). Outcome =
prezzo mediano della stessa carta a 48h±12h; segnali solo su dati passati.
Script riproducibili: `bots/bot_terzo/backtest_e_test.py`.

- **Sconto vs media recente = segnale vero e monotono**: sovrapprezzo −6,2% (35% pos) →
  sconto ≥20% **+16,8% (71% pos)**. È la spina dorsale.
- **Finestra lookback: più corta è meglio.** Spearman 0,37 a 1gg → 0,33 a 10gg; 7gg (il
  default storico di Profit) è tra le peggiori. Default scelto **2gg** (robusto).
- **La finestra-partita NON amplifica**: lontano dalla partita +2,6%, "finestra ideale"
  −3,5/−2,5gg +2,6% (uguale), vicino/dopo il kickoff **negativo** (−6%). Premessa di
  Profit smentita → il gate **non** filtra sulla partita.
- **Profitto assoluto ↔ dati in tensione**: il vantaggio % vive nelle carte medio-basse
  (<3€ +13,2%, 3-5€ +8,5%), **≥20€ è edge morto** (+0,1%). Alzare la soglia € oltre ~0,50
  peggiora i risultati (spinge su carte care senza edge). Sweet spot **0,30–0,50€**.
- **Trend confermato**: a pari sconto ≥10%, up +14,4% / flat +12,7% / down +7,3%. 'down'
  penalizzato ma non escluso.

**Selettività del gate (default)**: passano il gate **+8,8% mediano, 64% positivi,
+0,88€/flip** contro scartati −1,8% / 46% → **lift +10,6 punti**. Agisce su ~9% dei
candidati.

## 4. Parametri (tutti override da env, PROVVISORI)

| Env | Default | Cosa |
|---|---|---|
| `CERBERO_LOOKBACK_DAYS` | 2 | finestra media recente della carta |
| `CERBERO_TEMP_DISC_MIN` | 5.0 | sconto% temporale minimo (sotto: non è cheap vs sé) |
| `CERBERO_MIN_ABS_GAIN_EUR` | 0.50 | guadagno assoluto atteso minimo (lordo) per flip |
| `CERBERO_TREND_FLAT_PCT` | 5.0 | soglia up/down del trend |
| `CERBERO_DOWN_OVERRIDE_DISC` | 12.0 | sconto oltre cui si accetta anche un trend down |
| `CERBERO_PREZZO_MIN/MAX_EUR` | 1 / 30 | fascia prezzo (storica di Definitivo) |
| `AUTOBUY_LIVE_MODE` / `MAKEOFFER_LIVE_MODE` | no / no | esecuzione reale (default OFF) |
| `LISTA_NERA_PATH` | sorare_lista_nera_terzo.txt | lista nera dedicata |

Le curve di margine/sconto trasversali (AutoBuy/MakeOffer) sono **quelle di Definitivo**,
non modificate.

## 5. Come si gira

Diagnostica locale (col cookie fresco), o su GitHub Actions con i secret Sorare:
```bash
AUTOBUY_LIVE_MODE=no MAKEOFFER_LIVE_MODE=no python bots/bot_terzo/bot_terzo.py
```
Test + backtest offline (zero query, zero credenziali):
```bash
python bots/bot_terzo/backtest_e_test.py
```

## 6. Validazione (piano concordato: backtest → diagnostica → live minimo)

- [x] **Backtest** dell'asse temporale: fatto, gate selettivo (lift +10,6).
- [ ] **Diagnostica**: girare `bot_terzo.py` in `LIVE_MODE=no` e rivedere i "avrei
  comprato/offerto", verificandone il prezzo a 48h sulle run successive.
- [ ] **Live minimo**: solo dopo, con budget piccolo.

**Serve rinfrescare i secret Sorare prima di qualunque run** (cookie/csrf/version/build):
il 03/08 l'export è fallito con HTTP 403 perché scaduti (poi rinfrescati).

## 7. Limiti noti e prossimi passi

1. **L'asse trasversale (spread live 1°/2°) NON è stato backtestato**: non vive nelle
   transazioni ma nelle offerte live. Serve una raccolta dedicata di snapshot delle offerte
   nel tempo per validarlo/tararlo. Oggi si fida delle curve di Definitivo (già validate
   sulle preferenze utente, ma su "compra/offri", non su "poi rivende in guadagno").
2. **Dati solo sulle leghe di Profit** (MLS/Korea/Eredivisie/Belgio), non su tutto il
   mercato che il motore reattivo tocca. Le soglie temporali vanno riconfermate quando si
   accende su altre leghe (basta toglierle dalla blacklist `campionato`, costo query ~0).
3. **≥20€**: nessun edge misurabile nei dati attuali; la fascia alta va rivista con più dati.
4. **Refinement opzionale (non innestato)**: saltare gli acquisti a <~1,5 giorni dal kickoff
   (rendimento chiaramente negativo nei dati) — costerebbe una query "prossima partita" per
   candidato, valutare se vale.
5. **Rivendita**: fuori scope per ora (gestita a mano). Facile da aggiungere: la firma
   crittografata di Definitivo è già lì.

## 8. Apprendimento automatico per campionato (03/08)

Cerbero **impara dal mercato e adatta le soglie da solo, per campionato** (richiesta
esplicita utente). Ciclo:
1. **Osserva** — girando in diagnostica registra ogni carta che vede (prezzo, sconto vs
   media recente, lega, trend, ora) in `cerbero_osservazioni.csv`. Essendo reattivo,
   copre **tutto il mercato**, non solo le 4 leghe del dataset storico.
2. **Impara** — `bots/cerbero/cerbero_learn.py` misura cosa succede al prezzo nelle ore
   successive e sceglie, per ogni lega, la soglia di sconto minima che rende il flip
   positivo (rend. mediano ≥3%, ≥55% positivi, ≥30 campioni). Scrive
   `cerbero_soglie_apprese.json`.
3. **Adatta** — `motore_affare.py` legge quel JSON: le soglie apprese **vincono** sui
   default. Leghe mai viste → default prudente (10%) finché non arrivano dati.

Soglie apprese al 03/08 (lookback 1gg, bootstrap dal dataset storico):
**MLS 15%** (edge debole, serve barra alta), **K-League / Eredivisie / Belgio 5%** (edge forte).
Più il bot gira, più leghe impara.

**Lookback = 1gg** (non 2): il backtest mostra che 1gg vince ovunque e su MLS **cambia
il segno** (a 2gg MLS era negativo, a 1gg positivo — il mercato MLS si muove veloce).

## 9. File

- `bots/cerbero/motore_affare.py` — gate temporale + soglie per-lega apprese/di default.
- `bots/cerbero/cerbero.py` — il bot (reattivo Definitivo + gate, diagnostica-first, log osservazioni).
- `bots/cerbero/cerbero_learn.py` — impara le soglie per-lega dai dati → JSON.
- `bots/cerbero/backtest_e_test.py` — unit test + backtest + taratura (riproducibile, zero query).
- `.github/workflows/bot_cerbero.yml` — workflow diagnostica-first.
- `cerbero_soglie_apprese.json` — soglie per-lega apprese (rigenerato da cerbero_learn.py).
- `cerbero_osservazioni.csv` — log osservazioni di mercato (dati di apprendimento).
- `sorare_lista_nera_cerbero.txt` — lista nera dedicata (creata alla prima run).
