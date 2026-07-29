"""
Bot Profit -- export dati grezzi per analisi pattern "momento migliore per
comprare" (richiesta esplicita utente 29/07, sessione pomeridiana).

Script SEPARATO e READ-ONLY rispetto a bot_profit.py (nessuna modifica al file
di produzione, zero rischio di rompere la run stabile -- richiesta esplicita
dell'utente di poter tornare indietro facilmente). Riusa pero' le stesse
funzioni gia' testate di bot_profit.py (fetch_player_combined_snapshot,
filtri in_season/classic, throttle, credenziali) via import, invece di
riscrivere la logica di fetch da zero.

Ambito (richiesta esplicita utente): SOLO i giocatori attualmente presenti nei
3 CSV di classifica gia' prodotti da bot_profit.py (top 50 per gruppo:
mlspa, k-league-1, eredivisie_belgio) -- non l'intero roster scansionato.
Per ciascuno, richiede lo stesso identico snapshot combinato (prezzo/live
offers non serve qui, ma la query e' unica e gia' ottimizzata) e scrive UNA
RIGA per ogni transazione conteggiabile nella finestra TRANSACTIONS_WINDOW_DAYS
(7 giorni), con il relativo offset in giorni dalla partita piu' vicina --
dato grezzo per l'analisi pattern che viene fatta DOPO, in locale, senza altre
chiamate di rete (richiesta esplicita utente).

Output: bot_profit_output/pattern_raw_transactions_<timestamp_utc>.csv
"""
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import bot_profit as bp  # noqa: E402


OUTPUT_PATH_PREFIX = os.path.join(bp.OUTPUT_DIR, 'pattern_raw_transactions')


def _players_from_group_csv(group_name):
    """Legge il CSV di classifica piu' recente per un gruppo (stesso file gia'
    prodotto da bot_profit.py, nessuna nuova query) e ritorna la lista di
    (player_slug, league_slug, tipo_carta)."""
    prefix = bp._output_csv_prefix_for_group(group_name)
    path = bp._find_latest_output_csv(prefix)
    if not path:
        bp.log(f"[pattern export] nessun CSV trovato per il gruppo {group_name} (prefix {prefix})")
        return []
    out = []
    with open(path, 'r', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            slug = row.get('player_slug')
            league_slug = row.get('league_slug')
            tipo_carta = row.get('tipo_carta')
            if slug and league_slug:
                out.append((slug, league_slug, tipo_carta))
    bp.log(f"[pattern export] gruppo {group_name}: {len(out)} giocatori letti da {path}")
    return out


def _is_in_season_for_row(league_slug, tipo_carta):
    if bp.is_excluded_league(league_slug):
        return tipo_carta == 'in season'
    return None  # non rilevante, mercato unico (misto)


def export_raw_transactions():
    eth_rate = bp.get_eth_rate()
    seen_keys = set()
    rows_out = []

    for group_name in bp.OUTPUT_GROUPS:
        for player_slug, league_slug, tipo_carta in _players_from_group_csv(group_name):
            key = (player_slug, league_slug, tipo_carta)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            is_in_season = _is_in_season_for_row(league_slug, tipo_carta)
            (live_nodes, next_game_date_str, prossimo_avversario, ultima_partita_score,
             past_game_dates, tx_nodes, tx_cutoff, errored) = bp.fetch_player_combined_snapshot(player_slug)
            if errored:
                bp.log(f"[pattern export] errore/rate-limit su {player_slug}, saltato")
                continue

            match_dates = past_game_dates + ([next_game_date_str] if next_game_date_str else [])
            tx_con_date = bp._countable_transactions_from_nodes(
                tx_nodes, tx_cutoff, bool(is_in_season), league_slug, eth_rate)

            for dt, price in tx_con_date:
                offset = bp.giorni_da_partita_piu_vicina(dt, match_dates)
                rows_out.append({
                    'player_slug': player_slug,
                    'league_slug': league_slug,
                    'league_group': group_name,
                    'tipo_carta': tipo_carta,
                    'tx_datetime_utc': dt.isoformat(),
                    'price_eur': round(price, 4),
                    'giorni_da_partita': round(offset, 3) if offset is not None else '',
                })

            bp.log(f"[pattern export] {player_slug} ({league_slug}/{tipo_carta}): "
                    f"{len(tx_con_date)} transazioni nella finestra {bp.TRANSACTIONS_WINDOW_DAYS}gg")

    if not os.path.exists(bp.OUTPUT_DIR):
        os.makedirs(bp.OUTPUT_DIR)
    timestamp = bp._run_timestamp_utc()
    path = f"{OUTPUT_PATH_PREFIX}_{timestamp}.csv"
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'player_slug', 'league_slug', 'league_group', 'tipo_carta',
            'tx_datetime_utc', 'price_eur', 'giorni_da_partita',
        ])
        writer.writeheader()
        writer.writerows(rows_out)
    bp.log(f"[pattern export] scritte {len(rows_out)} transazioni grezze ({len(seen_keys)} giocatori) in {path}")
    return path


if __name__ == '__main__':
    export_raw_transactions()
