"""Script standalone per l'analisi pattern-mining sniping su un manager Sorare qualsiasi
(backlog "pattern-mining sniping manager", richiesta esplicita dell'utente, 17/07). Riusa le
funzioni gia' scritte in track.py (graphql_query, eur_price_from_amounts, get_eth_rate,
fetch_user_recent_cards, fetch_player_recent_direct_buys, diagnostic_snipe_pattern_report)
senza toccare il flusso principale del bot -- gira da un workflow GitHub Actions separato e
dedicato (snipe_pattern.yml), solo su richiesta manuale (workflow_dispatch), mai
automaticamente.

Rinominato il 17/07 (era satonio_snipe_analysis.py) -- il nome "satonio" faceva confusione
dato che i primi test sono stati fatti su ZenLock, non su Satonio: il manager da analizzare e'
sempre configurabile via SNIPE_USER_SLUG, il nome del file/script non ha piu' un manager
specifico nel nome.

Parametri configurabili via variabili d'ambiente (passate dal workflow):
- SNIPE_USER_SLUG: manager Sorare da analizzare (default "zenlock")
- SNIPE_WINDOW_DAYS: quanti giorni indietro (default "7")
- SNIPE_MAX_PAGES: quante pagine da 20 carte scansionare (default "10")
"""
import track

if __name__ == "__main__":
    eth_rate = track.get_eth_rate()
    track.log(f"Tasso ETH/EUR: {eth_rate}")
    track.diagnostic_snipe_pattern_report(eth_rate)
