"""Script standalone per l'analisi pattern-mining sniping su un manager Sorare qualsiasi
(backlog "pattern-mining sniping manager", richiesta esplicita dell'utente, 17/07). Riusa le
funzioni gia' scritte in track.py senza toccare il flusso principale del bot -- gira da un
workflow GitHub Actions separato e dedicato (snipe_pattern.yml), solo su richiesta manuale
(workflow_dispatch), mai automaticamente.

Rinominato il 17/07 (era satonio_snipe_analysis.py) -- il nome "satonio" faceva confusione
dato che i primi test sono stati fatti su ZenLock, non su Satonio: il manager da analizzare e'
sempre configurabile via SNIPE_USER_SLUG, il nome del file/script non ha piu' un manager
specifico nel nome.

Aggiornato il 17/07 (stesso giorno, scoperta successiva): ora usa
diagnostic_manager_trades_report invece di diagnostic_snipe_pattern_report. La vecchia
pipeline (fetch_user_recent_cards + filter_recent_direct_buy_candidates +
fetch_player_recent_direct_buys) partiva dalle carte ATTUALMENTE possedute, quindi perdeva
gli acquisti gia' rivenduti. La nuova (fetch_user_trades, query diretta su user(slug).trades)
prende TUTTE le transazioni -- acquisti e vendite -- in un colpo solo, e in piu' ricostruisce
il ciclo compra-poi-rivendi. diagnostic_snipe_pattern_report resta in track.py (non
rimosso, nel dubbio) ma non e' piu' la funzione chiamata di default.

Aggiornato ancora il 17/07 (stesso giorno, "progettare un tracker sul suo modello"): aggiunta
SNIPE_REPORT_MODE per scegliere tra i due report senza servire un altro script/workflow --
"trades" (default, acquisti+vendite complete) o "margin_model" (solo snipe puri, arricchiti
con sconto% vs mediana di mercato e bucket in_season/classic, prima base per calibrare soglie
sul suo comportamento).

Parametri configurabili via variabili d'ambiente (passate dal workflow):
- SNIPE_USER_SLUG: manager Sorare da analizzare (default "zenlock")
- SNIPE_WINDOW_DAYS: quanti giorni indietro (default "7")
- SNIPE_MAX_PAGES: quante pagine di transazioni scansionare (default "10")
- SNIPE_REPORT_MODE: "trades" o "margin_model" (default "trades")
"""
import track

if __name__ == "__main__":
    eth_rate = track.get_eth_rate()
    track.log(f"Tasso ETH/EUR: {eth_rate}")
    mode = track.os.environ.get('SNIPE_REPORT_MODE', 'trades')
    if mode == 'margin_model':
        track.diagnostic_snipe_margin_model_report(eth_rate)
    else:
        track.diagnostic_manager_trades_report(eth_rate)
