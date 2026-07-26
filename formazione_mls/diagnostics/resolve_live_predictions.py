"""
Resolve Live Predictions (26/07) -- monitoraggio MAE live per i 4 ruoli MLS.

Finora il modello viene validato SOLO con backtest walk-forward su dati
storici in cache (vedi gli altri validate_*.py in questa cartella). Non
c'e' nessun tracciamento di quanto le predizioni REALI di produzione si
rivelino accurate una volta giocata la partita -- utile sia per confermare
che le modifiche di oggi (rimozione di fattore_forza_avversario da
score_atteso) reggano anche live, sia per scoprire in futuro un eventuale
drift del modello.

Ogni predizione generata in produzione (formazione_mls/predict/test_gk.py,
test_def.py, test_mid.py, test_mls_fwd_all.py -- MAI in CALIBRATION_MODE)
viene loggata come entry "pending" in
formazione_mls/output/mls_<ruolo>_all/prediction_log.json (vedi
formazione_mls/predict/live_prediction_log.py). Questo script:

1. Legge le entry pending di ciascun ruolo.
2. Per ognuna, controlla la cache di produzione gia' presente
   (mls_<ruolo>_all/.cache/<slug>_detail_cache.json) per vedere se ora
   esiste un record con la STESSA data partita e uno score REALE registrato
   (cioe' la partita e' stata giocata e la cache si e' aggiornata dopo la
   predizione).
3. Se risolta: calcola errore = score_reale - score_atteso, sposta la entry
   (arricchita con score_reale/errore/resolved_at) in
   prediction_log_resolved.json e la rimuove dal pending.
4. Se non ancora risolta: la lascia intatta nel pending.
5. Stampa un riepilogo per ruolo: predizioni risolte, MAE live su tutto lo
   storico risolto, MAE live sulle ultime N (default 30) -- per rendere
   visibile un eventuale drift.

NESSUNA chiamata API: legge solo file JSON gia' presenti su disco (log di
predizione + cache di produzione gia' scritta dagli script predict).

Uso:
  python formazione_mls/diagnostics/resolve_live_predictions.py
  python formazione_mls/diagnostics/resolve_live_predictions.py --report-only
  python formazione_mls/diagnostics/resolve_live_predictions.py --last-n 20
"""
import os
import sys
import json
import glob
import argparse
import datetime
import statistics

sys.path.insert(0, os.getcwd())

DEFAULT_LAST_N = 30

OUTPUT_DIR_BY_ROLE = {
    'gk': 'formazione_mls/output/mls_gk_all',
    'def': 'formazione_mls/output/mls_def_all',
    'mid': 'formazione_mls/output/mls_mid_all',
    'fwd': 'formazione_mls/output/mls_fwd_all',
}

PENDING_FILENAME = 'prediction_log.json'
RESOLVED_FILENAME = 'prediction_log_resolved.json'


def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f) or {}


def _save_json(path, data):
    out_dir = os.path.dirname(path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_real_score(cache_dir, player_slug, game_date):
    """Cerca nella cache di produzione del giocatore (gia' scritta dagli
    script predict, ZERO chiamate API qui) una partita con la stessa data
    della predizione pending e uno score reale registrato. Ritorna lo score
    reale o None se non ancora trovato (partita non ancora giocata / cache
    non ancora aggiornata)."""
    cache_path = os.path.join(cache_dir, f'{player_slug}_detail_cache.json')
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding='utf-8') as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for entry in cache.values():
        game = entry.get('anyGame') or {}
        if game.get('date') != game_date:
            continue
        score = entry.get('score')
        if score is not None:
            return score
    return None


def resolve_role(ruolo):
    """Risolve le entry pending di un ruolo confrontandole con la cache
    gia' presente. Ritorna (n_risolte_ora, n_ancora_pending)."""
    output_dir = OUTPUT_DIR_BY_ROLE[ruolo]
    cache_dir = os.path.join(output_dir, '.cache')
    pending_path = os.path.join(output_dir, PENDING_FILENAME)
    resolved_path = os.path.join(output_dir, RESOLVED_FILENAME)

    pending = _load_json(pending_path)
    resolved = _load_json(resolved_path)

    if not pending:
        return 0, 0

    still_pending = {}
    n_resolved_now = 0
    for key, entry in pending.items():
        player_slug = entry.get('player_slug')
        game_date = entry.get('game_date')
        score_atteso = entry.get('score_atteso')
        score_reale = _find_real_score(cache_dir, player_slug, game_date) if player_slug and game_date else None

        if score_reale is None or score_atteso is None:
            still_pending[key] = entry
            continue

        resolved_entry = dict(entry)
        resolved_entry['score_reale'] = score_reale
        resolved_entry['errore'] = score_reale - score_atteso
        resolved_entry['resolved_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
        resolved[key] = resolved_entry
        n_resolved_now += 1

    if n_resolved_now:
        _save_json(pending_path, still_pending)
        _save_json(resolved_path, resolved)

    return n_resolved_now, len(still_pending)


def print_report(ruolo, last_n=DEFAULT_LAST_N):
    output_dir = OUTPUT_DIR_BY_ROLE[ruolo]
    resolved_path = os.path.join(output_dir, RESOLVED_FILENAME)
    resolved = _load_json(resolved_path)

    if not resolved:
        print(f"{ruolo.upper()}: nessuna predizione live risolta finora.")
        return

    # Ordiniamo per data partita (crescente) cosi' "ultime N" = piu' recenti
    # cronologicamente, non solo per ordine di inserimento nel JSON.
    entries = sorted(resolved.values(), key=lambda e: e.get('game_date') or '')
    errori_assoluti = [abs(e['errore']) for e in entries if e.get('errore') is not None]

    if not errori_assoluti:
        print(f"{ruolo.upper()}: entry risolte ma senza errore calcolabile (dati incompleti).")
        return

    mae_totale = statistics.mean(errori_assoluti)
    ultimi = errori_assoluti[-last_n:]
    mae_ultimi = statistics.mean(ultimi)

    print(f"{ruolo.upper()}: {len(errori_assoluti)} predizioni live risolte")
    print(f"  MAE live (tutto lo storico):      {mae_totale:.2f}")
    print(f"  MAE live (ultime {len(ultimi)} partite): {mae_ultimi:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Risolve le predizioni live pending e stampa il report MAE.")
    parser.add_argument('--report-only', action='store_true',
                         help="Salta la risoluzione, stampa solo il report sui dati gia' risolti.")
    parser.add_argument('--last-n', type=int, default=DEFAULT_LAST_N,
                         help=f"Quante partite recenti considerare per il MAE 'ultime N' (default {DEFAULT_LAST_N}).")
    args = parser.parse_args()

    if not args.report_only:
        print(f"{'='*70}\nRisoluzione predizioni live pending...\n{'='*70}")
        for ruolo in ('gk', 'def', 'mid', 'fwd'):
            n_ora, n_pending = resolve_role(ruolo)
            print(f"{ruolo.upper()}: {n_ora} nuove predizioni risolte ora, {n_pending} ancora pending "
                  f"(partita non ancora giocata / cache non aggiornata)")

    print(f"\n{'='*70}\nREPORT MAE LIVE PER RUOLO\n{'='*70}")
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        print_report(ruolo, last_n=args.last_n)
        print()


if __name__ == '__main__':
    main()
