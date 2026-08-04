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

## Cosa è cambiato il 04/08
Tre interventi, tutti sulla **velocità con cui Cerbero arriva a decidere se va in live**. Nessuno tocca il gate o le decisioni: il backtest resta identico (lift +12,4).

1. **Raccolta continua (cron ogni 6h) — TENTATA, ma il cron NON è mai scattato.** Prima ogni run partiva solo a mano: Cerbero imparava quando qualcuno si ricordava di cliccare. Ma per imparare la soglia di una lega servono **≥30 osservazioni per lega**, e dopo le prime run ce n'erano ~15 sparse su 23 leghe. È stato aggiunto al workflow un cron `0 */6 * * *` (5h di ascolto, sempre in diagnostica). **Verifica 04/08 (`gh run list --event=schedule`): zero run schedulate.** Config valida (blocco `on:` ok, file su `main`, Actions abilitate); la causa è che il cron è stato aggiunto solo il 04/08 alle 00:08 UTC e GitHub non attiva subito uno scheduled workflow appena introdotto. **Il regime reale resta manuale**: ogni run è una pressione umana.
2. **L'asse trasversale finisce nei dati.** Lo spread 1°/2° prezzo live era il **limite #1 dichiarato del progetto**: mai validato, perché non vive nelle transazioni storiche. Il bot lo calcolava già per decidere ma non lo registrava. Ora il CSV ha `prezzo_secondo_eur` e `margine_trasversale_pct` → il risolutore forward può misurare **anche quello**, non solo lo sconto temporale. Costo query zero.
   *In più*: il log osservazione stava **dopo** lo scarto "mercato troppo sottile", che fa `return False`. Quelle carte avevano già pagato la query e avevano media e sconto calcolati, e venivano buttate. Ora si registrano **prima dello scarto thin market e della decisione del gate**, con la colonna `scarto_thin_market` per poterle includere o escludere in fase di apprendimento. **Precisazione 04/08:** *non* è "prima di ogni scarto" — l'asse temporale richiede il fetch transazioni (pagato solo sopra la soglia MakeOffer), quindi gli scarti a monte, incluso **margine < soglia MakeOffer** (la maggioranza degli eventi), non producono riga. Effetto collaterale: l'asse **trasversale** resta censurato sui margini bassi (vedi handoff 04/08).
3. **Watchdog sul silenzio.** La run 30851298043 ha smesso di ricevere eventi alle 22:41 ed è rimasta **viva ma sorda per 94 minuti** (~44% della run) senza tentare una sola riconnessione. Il ciclo di riconnessione esistente non poteva vederlo: copre il caso in cui la connessione *cade*, ma qui il socket era aperto e i `ping` di ActionCable continuavano ad arrivare, quindi `ping_interval`/`ping_timeout` erano soddisfatti e `on_close` non scattava mai. **A morire era la sottoscrizione lato Sorare, non il TCP.** Ora un watchdog guarda gli *eventi* invece del socket: 10 minuti di zero eventi (ping esclusi) → chiude e risottoscrive. A regime arrivano ~3 eventi/secondo, quindi 10 minuti di silenzio assoluto non sono un mercato calmo.

**Schema del CSV**: le righe raccolte prima del 04/08 hanno 11 campi invece di 14. `cerbero_learn.py` legge con `csv.DictReader`, che le completa a `None` — nessuna migrazione, restano valide sull'asse temporale. L'intestazione si riallinea da sola alla prima scrittura.

## Stato e come si usa
- **Diagnostica-first**: acquisto/offerta reali **spenti** di default (impara senza rischiare soldi).
- **Va lanciata a mano** (il cron non è mai partito, vedi sopra): GitHub → **Actions → "Cerbero (diagnostica)" → Run workflow**, con `listen_seconds = 18000`; evita di annullarla a metà (quello che non ha ancora committato si perde). Servono i secret Sorare freschi (cookie/csrf).
- Lista nera **dedicata** (`sorare_lista_nera_cerbero.txt`), separata dagli altri bot.
- **Prossimo passo:** accumulare osservazioni per qualche giorno, poi far girare il risolutore per imparare le soglie di tutte le leghe; validare; solo dopo valutare il passaggio in live.

## Da verificare alla prossima sessione
1. **Il cron è scattato?** `gh run list --workflow=bot_cerbero.yml --event=schedule` — deve comparire almeno una riga con evento `schedule` invece di `workflow_dispatch`. GitHub fa partire i cron con 5-20 minuti di ritardo, ed è normale.
2. **Il watchdog ha funzionato?** Cercare `[watchdog]` nel log della prima run partita da cron. Se compare, ha fatto il suo lavoro; se il silenzio si ripete *senza* che il watchdog scriva nulla, la causa è un'altra e va cercata da capo.
3. **Fra 48h dalle osservazioni**, far girare il risolutore: `python bots/cerbero/cerbero_learn.py --osservazioni`. Prima non ha senso — misura il prezzo *48h dopo* ogni osservazione. È il momento in cui si scopre anche se l'asse trasversale predice davvero qualcosa.
4. Non ancora fatto per scelta: **schedulare anche `cerbero_learn`**. Prima va lanciato a mano una volta e visto che le soglie prodotte abbiano senso.

## File chiave
- `bots/cerbero/cerbero.py` — il bot (reattivo + gate + esecuzione, diagnostica-first).
- `bots/cerbero/motore_affare.py` — il gate temporale e le soglie per-lega.
- `bots/cerbero/cerbero_learn.py` — impara le soglie (dal dataset e dalle osservazioni live).
- `bots/cerbero/backtest_e_test.py` — test + backtest riproducibili (zero query).
- `cerbero_soglie_apprese.json` / `cerbero_osservazioni.csv` — soglie apprese / dati di apprendimento.
- `.github/workflows/bot_cerbero.yml` — workflow diagnostica 5h.
- `docs/BOT_CERBERO_PROGETTO.md` — dettaglio tecnico completo.
