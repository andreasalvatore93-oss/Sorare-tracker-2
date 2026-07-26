"""
simulate_cap260_tradeoff.py (26/07, seconda sessione)

Backtest walk-forward EMPIRICO (non solo teoria) per rispondere alla domanda:
quanto conviene, in pratica, sacrificare punteggio ATTESO (scegliendo
giocatori con L10 piu' bassa) per rientrare sotto il cap 260 In Season e
ottenere il +4% di bonus Sorare (verificato dall'utente con screenshot reali
della UI: se la somma della L10 -- LAST_TEN_PLAYED_SO5_AVERAGE_SCORE, media
delle ultime 10 partite GIOCATE -- dei 5 titolari e' <= 260, +4% su tutte le
carte della formazione)?

Il calcolo "break-even = 4% del totale capped" e' vero matematicamente ma non
dice NULLA su quanto spesso/di quanto si perde in pratica scegliendo
giocatori diversi dal pool disponibile in un dato momento -- questo script
misura esattamente quello, su dati REALI (nessuna nuova chiamata API, solo le
cache di calibrazione gia' su disco).

METODO (stesso approccio walk-forward rigoroso di
formazione_mls/diagnostics/validate_team_defense_strength.py::run_role -- che
ha gia' stabilito che la formula di produzione ATTUALE, senza
fattore_forza_avversario ne' correzioni granulari Stadio D, e' quella da
riprodurre qui per un confronto onesto "stessa formula usata in produzione"):

1. Per ogni ruolo (GK/DEF/MID/FWD) scansiona le cache di calibrazione
   (formazione_mls/output/mls_<ruolo>_calibration/.cache/*_detail_cache.json)
   e ricostruisce, per ogni giocatore, la serie storica cronologica reale
   (data, score, casa/trasferta).
2. Per ogni partita di un giocatore con almeno MIN_HISTORY=6 partite
   precedenti, calcola SENZA LOOKAHEAD:
   - score_atteso = media_pesata_esponenziale(storico) x fattore_casa_trasferta
     x fattore_trend -- STESSE funzioni (weighted_mean, exponential_weights,
     compute_split_factor, compute_trend_factor) e STESSE costanti
     (HALF_LIFE_GAMES, TREND_INTENSITY) del modulo test_<ruolo>.py del ruolo,
     importate via importlib (nessuna duplicazione della logica).
   - L10 reale = media semplice (non pesata, come LAST_TEN_PLAYED_SO5_
     AVERAGE_SCORE di Sorare) delle ultime 10 partite storiche precedenti.
   - reale = lo score EFFETTIVAMENTE ottenuto in quella partita (il target,
     mai usato nel calcolo di score_atteso/L10).
3. Raggruppa tutti questi "candidati" per settimana solare (ISO year/week)
   della partita target -- proxy di "giornata simulata": un momento nel
   tempo in cui e' disponibile un pool di giocatori con storico sufficiente,
   ciascuno con la propria prossima partita reale nella stessa finestra.
   Le cache di calibrazione contengono giocatori/competizioni eterogenee (non
   solo MLS in senso stretto), quindi raggruppare per singola data esatta
   sarebbe troppo restrittivo -- la settimana e' un compromesso ragionevole
   che comunque garantisce nessun lookahead (score_atteso/L10 di ciascun
   candidato usano solo dati precedenti alla SUA partita specifica).
4. Tiene solo le settimane con pool sufficiente per una scelta reale:
   MIN_CANDIDATES = {GK: 3, DEF: 8, MID: 8, FWD: 8}.
5. Per ciascuna settimana qualificata, costruisce DUE formazioni In Season
   (1 GK, 1 DEF, 1 MID, 1 FWD, 1 EXTRA tra DEF/MID/FWD, stessa struttura di
   FORMATION_SHAPES['IN_SEASON'] in build_formazione_finale.py) dallo stesso
   pool:
   (a) LIBERA: miglior score_atteso per ogni slot, poi il miglior EXTRA tra i
       rimanenti -- stessa euristica "greedy, un giocatore per slot" di
       build_one_lineup, senza vincolo L10.
   (b) VINCOLATA (L10 <= 260): stessa euristica ma con budget L10 residuo
       (stesso algoritmo greedy di build_one_lineup/pick(): filtra ai
       candidati entro budget residuo, se nessuno rientra prende il piu'
       economico e segnala "budget non rispettato").
6. Confronta il risultato REALE (non predetto): somma degli score REALI dei
   5 titolari, con (b) che riceve +4% sul totale (bonus Sorare) e (a) nessun
   bonus. Aggrega su tutte le settimane simulate.

NESSUN lookahead, NESSUNA nuova query API (solo le cache gia' su disco),
NESSUNA modifica ai file di produzione.

Uso: python formazione_mls/diagnostics/simulate_cap260_tradeoff.py
"""
import os
import sys
import glob
import json
import statistics
import importlib
import datetime
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
CAP260 = 260.0
CAP_BONUS = 0.04
MIN_CANDIDATES = {'GK': 3, 'DEF': 8, 'MID': 8, 'FWD': 8}
EXTRA_ROLES = ('DEF', 'MID', 'FWD')
ROLE_SLOTS = ('GK', 'DEF', 'MID', 'FWD')

MODULE_BY_ROLE = {
    'GK': 'formazione_mls.predict.test_gk',
    'DEF': 'formazione_mls.predict.test_def',
    'MID': 'formazione_mls.predict.test_mid',
    'FWD': 'formazione_mls.predict.test_mls_fwd_all',
}

CACHE_DIR_BY_ROLE = {role: f'formazione_mls/output/mls_{role.lower()}_calibration/.cache'
                      for role in MODULE_BY_ROLE}


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    """Euristica maggioranza gia' usata in validate_team_defense_strength.py:
    la squadra piu' frequente tra home/away di tutte le partite cachate."""
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def load_role_series(role):
    """Ritorna lista di dict {slug, games:[{date, score, is_home}, ...]}
    ordinata cronologicamente per ciascun giocatore del ruolo, dalle cache di
    calibrazione. Nessuna nuova chiamata API -- solo dati gia' su disco."""
    cache_dir = CACHE_DIR_BY_ROLE[role]
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    players = []
    for fpath in files:
        with open(fpath, encoding='utf-8') as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                continue
        if not cache:
            continue
        entries = [e for e in cache.values()
                   if e.get('anyGame') and e.get('detailedScore') and e.get('score') is not None]
        if len(entries) < MIN_HISTORY + 1:
            continue
        games_raw = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games_raw)
        if not team_slug:
            continue

        slug = os.path.basename(fpath).replace('_detail_cache.json', '')
        rows = []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            dt = parse_date(g.get('date'))
            if dt is None:
                continue
            rows.append({'date': dt, 'score': e.get('score') or 0.0, 'is_home': is_home})
        rows.sort(key=lambda r: r['date'])
        if len(rows) < MIN_HISTORY + 1:
            continue
        players.append({'slug': slug, 'games': rows})
    return players


def build_candidates_by_week(role, players, mod):
    """Per ogni giocatore/partita con storico sufficiente, calcola
    score_atteso (STESSA formula/costanti del modulo di produzione test_<ruolo>.py,
    senza fattore_forza_avversario ne' correzioni granulari Stadio D -- vedi
    docstring del modulo per la motivazione, stesso approccio gia' validato
    in validate_team_defense_strength.py) e L10 reale, SENZA lookahead
    (usa solo le partite precedenti a quella target). Raggruppa i candidati
    per settimana ISO della partita target. Ritorna (by_week, n_record)."""
    weighted_mean = mod.weighted_mean
    exponential_weights = mod.exponential_weights
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    TREND_INTENSITY = mod.TREND_INTENSITY

    by_week = defaultdict(dict)  # week_key -> {slug: record} (dedup per giocatore/settimana)
    n_record = 0

    for p in players:
        games = p['games']
        n = len(games)
        for i in range(MIN_HISTORY, n):
            hist_scores = [g['score'] for g in games[:i]]
            hist_home = [g['is_home'] for g in games[:i]]
            target_is_home = games[i]['is_home']

            weights = exponential_weights(len(hist_scores), HALF_LIFE_GAMES)
            media = weighted_mean(hist_scores, weights)
            fattore_ct = compute_split_factor(hist_scores, hist_home, target_is_home)
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)
            atteso = media * fattore_ct * fattore_trend

            l10_hist = hist_scores[-10:]
            l10 = sum(l10_hist) / len(l10_hist)

            reale = games[i]['score']
            test_date = games[i]['date']
            iso = test_date.isocalendar()
            week_key = (iso[0], iso[1])

            by_week[week_key][p['slug']] = {
                'slug': p['slug'], 'atteso': atteso, 'l10': l10, 'reale': reale,
            }
            n_record += 1

    return by_week, n_record


def pick_best(candidates, used, budget):
    """Sceglie il candidato con miglior score_atteso tra quelli non ancora
    usati in questa formazione, rispettando (se budget non e' None) il
    budget L10 residuo -- stessa euristica greedy di build_one_lineup/pick()
    in build_formazione_finale.py: se nessun candidato rientra nel budget,
    ripiega sul piu' economico disponibile e segnala budget non rispettato."""
    disponibili = [c for c in candidates if c['slug'] not in used]
    if not disponibili:
        return None, True
    if budget is None:
        return max(disponibili, key=lambda c: c['atteso']), True

    entro_budget = [c for c in disponibili if c['l10'] <= budget[0]]
    if entro_budget:
        scelto = max(entro_budget, key=lambda c: c['atteso'])
        rispettato = True
    else:
        scelto = min(disponibili, key=lambda c: c['l10'])
        rispettato = False
    return scelto, rispettato


def build_lineup(pools, l10_cap=None):
    """Costruisce una formazione In Season (GK, DEF, MID, FWD, EXTRA tra
    DEF/MID/FWD) dal pool disponibile in quella settimana, massimizzando
    score_atteso slot per slot (stessa logica di build_one_lineup). Se
    l10_cap e' impostato, applica il budget greedy residuo. Ritorna
    (picks, cap_rispettato) oppure (None, False) se il pool si esaurisce."""
    used = set()
    picks = []
    budget = [l10_cap] if l10_cap is not None else None
    cap_rispettato = True

    for role in ROLE_SLOTS:
        scelto, ok = pick_best(pools[role], used, budget)
        if scelto is None:
            return None, False
        if not ok:
            cap_rispettato = False
        used.add(scelto['slug'])
        picks.append(scelto)
        if budget is not None:
            budget[0] -= scelto['l10']

    combined = [c for r in EXTRA_ROLES for c in pools[r]]
    extra, ok = pick_best(combined, used, budget)
    if extra is None:
        return None, False
    if not ok:
        cap_rispettato = False
    picks.append(extra)

    return picks, cap_rispettato


def simulate():
    print("Ricostruzione serie storiche per ruolo dalle cache di calibrazione...")
    by_week_role = {}
    for role in ROLE_SLOTS:
        mod = importlib.import_module(MODULE_BY_ROLE[role])
        players = load_role_series(role)
        by_week, n_record = build_candidates_by_week(role, players, mod)
        by_week_role[role] = by_week
        print(f"  {role}: {len(players)} giocatori con storico sufficiente, {n_record} punti di test")

    all_weeks = set()
    for role in ROLE_SLOTS:
        all_weeks |= set(by_week_role[role].keys())

    risultati = []
    for week_key in sorted(all_weeks):
        pools = {}
        qualificata = True
        for role in ROLE_SLOTS:
            candidati = list(by_week_role[role].get(week_key, {}).values())
            if len(candidati) < MIN_CANDIDATES[role]:
                qualificata = False
                break
            pools[role] = candidati
        if not qualificata:
            continue

        picks_free, _ = build_lineup(pools, l10_cap=None)
        if picks_free is None:
            continue
        picks_capped, l10_ok = build_lineup(pools, l10_cap=CAP260)
        if picks_capped is None:
            continue

        tot_atteso_free = sum(c['atteso'] for c in picks_free)
        tot_reale_free = sum(c['reale'] for c in picks_free)
        tot_atteso_capped = sum(c['atteso'] for c in picks_capped)
        tot_reale_capped = sum(c['reale'] for c in picks_capped)
        tot_l10_capped = sum(c['l10'] for c in picks_capped)
        # Il bonus +4% e' REALE solo se la somma L10 EFFETTIVA della
        # formazione (b) e' davvero <= 260 -- 'l10_ok' (flag del greedy)
        # indica solo che l'euristica ha trovato un candidato entro il
        # budget RESIDUO ad ogni singolo slot, non garantisce il totale
        # finale (il fallback "piu' economico disponibile" quando nessun
        # candidato rientra puo' comunque sforare il cap complessivo). Qui
        # verifichiamo il vincolo REALE sul totale, come farebbe Sorare.
        cap_effettivamente_raggiunto = tot_l10_capped <= CAP260
        bonus_multiplier = (1.0 + CAP_BONUS) if cap_effettivamente_raggiunto else 1.0
        tot_reale_capped_bonus = tot_reale_capped * bonus_multiplier

        slugs_free = {c['slug'] for c in picks_free}
        slugs_capped = {c['slug'] for c in picks_capped}
        differ = slugs_free != slugs_capped

        risultati.append({
            'week': week_key,
            'l10_cap_rispettato': l10_ok,
            'cap_effettivamente_raggiunto': cap_effettivamente_raggiunto,
            'tot_l10_capped': tot_l10_capped,
            'tot_atteso_free': tot_atteso_free,
            'tot_atteso_capped': tot_atteso_capped,
            'tot_reale_free': tot_reale_free,
            'tot_reale_capped': tot_reale_capped,
            'tot_reale_capped_bonus': tot_reale_capped_bonus,
            'cap_conviene': tot_reale_capped_bonus > tot_reale_free,
            'differ': differ,
            'sacrificio_atteso': tot_atteso_free - tot_atteso_capped,
            'break_even_teorico': CAP_BONUS * tot_atteso_capped,
            'guadagno_reale': tot_reale_capped_bonus - tot_reale_free,
        })

    return risultati


def report(risultati):
    n = len(risultati)
    print(f"\n{'=' * 70}")
    print(f"GIORNATE SIMULATE (settimane qualificate): {n}")
    print(f"{'=' * 70}")
    if n == 0:
        print("Nessuna settimana con pool sufficiente in tutti i ruoli -- impossibile concludere.")
        return

    n_rispettato = sum(1 for r in risultati if r['l10_cap_rispettato'])
    n_raggiunto = sum(1 for r in risultati if r['cap_effettivamente_raggiunto'])
    n_differ = sum(1 for r in risultati if r['differ'])
    n_conviene = sum(1 for r in risultati if r['cap_conviene'])

    print(f"Budget L10<=260 rispettato slot-per-slot (euristica greedy):  {n_rispettato}/{n} "
          f"({n_rispettato / n * 100:.1f}%)")
    print(f"Cap 260 EFFETTIVAMENTE raggiunto (totale L10 reale <= 260):   {n_raggiunto}/{n} "
          f"({n_raggiunto / n * 100:.1f}%) -- SOLO in questo caso scatta davvero il +4%")
    print(f"Formazione (b) diversa dalla (a) libera:                     {n_differ}/{n} "
          f"({n_differ / n * 100:.1f}%)")
    print(f"Cap 260 CONVIENE (b*1.04 reale > a reale):                   {n_conviene}/{n} "
          f"({n_conviene / n * 100:.1f}%)")

    sacrifici = [r['sacrificio_atteso'] for r in risultati if r['differ']]
    guadagni_reali = [r['guadagno_reale'] for r in risultati if r['differ']]
    break_even = [r['break_even_teorico'] for r in risultati if r['differ']]

    if sacrifici:
        print(f"\nQuando (a) e (b) DIFFERISCONO ({len(sacrifici)} giornate):")
        print(f"  Sacrificio medio di score ATTESO (a - b):     {statistics.mean(sacrifici):.2f} pt "
              f"(mediana {statistics.median(sacrifici):.2f})")
        print(f"  Break-even teorico medio (4% del capped):     {statistics.mean(break_even):.2f} pt")
        print(f"  Guadagno/perdita REALE medio (b*1.04 - a):    {statistics.mean(guadagni_reali):+.2f} pt "
              f"(mediana {statistics.median(guadagni_reali):+.2f})")
        n_conviene_quando_differ = sum(1 for r in risultati if r['differ'] and r['cap_conviene'])
        print(f"  Conviene quando differiscono:                 {n_conviene_quando_differ}/{len(sacrifici)} "
              f"({n_conviene_quando_differ / len(sacrifici) * 100:.1f}%)")

    n_uguali = n - n_differ
    if n_uguali:
        guadagno_quando_uguali = [r['guadagno_reale'] for r in risultati if not r['differ']]
        print(f"\nQuando (a) e (b) COINCIDONO ({n_uguali} giornate, il cap non costa nulla): "
              f"guadagno reale medio (solo bonus 4%) = {statistics.mean(guadagno_quando_uguali):+.2f} pt")

    tutti_guadagni = [r['guadagno_reale'] for r in risultati]
    print(f"\nGuadagno/perdita REALE medio su TUTTE le giornate: {statistics.mean(tutti_guadagni):+.2f} pt "
          f"(dev.std {statistics.pstdev(tutti_guadagni):.2f})")
    print(f"{'=' * 70}")


def main():
    risultati = simulate()
    report(risultati)


if __name__ == '__main__':
    main()
