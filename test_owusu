"""
Tool_formazione_owusu (prototipo v1)

Prototipo di predizione punteggio Sorare per UN SOLO giocatore (Prince Osei Owusu),
prima di estendere la logica a tutte le carte MLS possedute.

Formula v1:
  score_atteso = P(gioca) x media_pesata_esponenziale(14 partite)
                 x fattore_casa_trasferta x fattore_forza_avversario
  range_confidenza = +/- deviazione_standard_pesata_esponenziale(stesse 14 partite)

Note:
- Finestra: ultime 14 partite con punteggio registrato (FINAL o REVIEWING),
  le DID_NOT_PLAY sono escluse dalla media ma contano per il tasso di presenza storico.
- Include TUTTE le competizioni (MLS, Leagues Cup, amichevoli nazionale) nella
  finestra delle 14, senza esclusioni.
- Il dettaglio granulare (PlayerGameScoreDialogQuery) viene scaricato per ogni
  partita della finestra e cachato su disco (partite passate/FINAL non cambiano
  più, quindi non serve rifare la query se già presente in cache).
"""
import os
import json
import math
import time
import datetime
import requests

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/graphql'
PLAYER_SLUG = 'prince-osei-owusu'
PLAYER_POSITION = 'Forward'
WINDOW_SIZE = 14
HALF_LIFE_GAMES = 6.5  # decadimento esponenziale: peso si dimezza ogni ~6.5 partite indietro

OUTPUT_DIR = 'test_owusu'
CACHE_DIR = os.path.join(OUTPUT_DIR, '.cache')

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [test_owusu] {msg}")


def graphql_query(query, variables=None, operation_name=None):
    """Esegue una query GraphQL contro l'API Sorare, con retry/backoff su 429.
    Stesso schema di throttling/retry usato negli altri bot del repo."""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if COOKIES:
        headers['Cookie'] = COOKIES

    payload = {'query': query, 'variables': variables or {}}
    if operation_name:
        payload['operationName'] = operation_name

    backoff = 1.0
    for attempt in range(5):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                sleep_s = float(retry_after) if retry_after else backoff
                log(f"[429] tentativo {attempt+1}/5, attesa {sleep_s:.1f}s")
                time.sleep(sleep_s)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log(f"[Errore GraphQL] {e}")
            time.sleep(backoff)
            backoff *= 2

    log("[Errore GraphQL] Esauriti i tentativi")
    return {}


# ---------------------------------------------------------------------------
# QUERY 4 equivalente: game log completo (allPlayerGameScores + anyFutureGames)
# ---------------------------------------------------------------------------
ALL_GAME_SCORES_QUERY = """
query AllPlayerGameScores($slug: String!, $first: Int!) {
  anyPlayer(slug: $slug) {
    allPlayerGameScores(first: $first) {
      nodes {
        id
        score
        scoreStatus
        positionTyped
        anyGame {
          id
          date
          status
          homeTeam { ... on Club { slug name code } }
          awayTeam { ... on Club { slug name code } }
          competition { slug }
        }
        anyPlayerGameStats {
          fieldStatus
          gameStarted
          minsPlayed
          yellowCard
          footballPlayingStatusOdds { starterOddsBasisPoints reliability }
        }
      }
    }
    anyFutureGames(first: 5) {
      nodes {
        id
        date
        playerGameScore {
          id
          positionTyped
          projectedScore
          anyGame {
            id
            date
            homeTeam { ... on Club { slug name code } }
            awayTeam { ... on Club { slug name code } }
            competition { slug }
          }
          anyPlayerGameStats {
            footballPlayingStatusOdds { starterOddsBasisPoints reliability }
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# QUERY 5 equivalente: dettaglio punto-per-punto di una partita (per score-id)
# ---------------------------------------------------------------------------
GAME_SCORE_DETAIL_QUERY = """
query PlayerGameScoreDetail($id: String!) {
  so5 {
    playerGameScore(id: $id) {
      id
      score
      scoreStatus
      position
      anyGame {
        date
        status
        homeTeam {
          ... on Club {
            slug name code domesticLeagueRanking domesticLeagueRankingRatioRange
          }
        }
        awayTeam {
          ... on Club {
            slug name code domesticLeagueRanking domesticLeagueRankingRatioRange
          }
        }
        competition { slug }
      }
      detailedScore { category stat statValue totalScore }
      decisiveScore { totalScore }
    }
  }
}
"""


def fetch_game_log(slug, first=50):
    """Recupera game log storico + prossime partite programmate per il giocatore."""
    log(f"Recupero game log per {slug} (ultime {first} richieste)...")
    data = graphql_query(ALL_GAME_SCORES_QUERY, {"slug": slug, "first": first},
                          operation_name="AllPlayerGameScores")
    if data.get('errors'):
        log(f"Errore nella query game log: {data['errors']}")
        return [], []

    player = data.get('data', {}).get('anyPlayer', {}) or {}
    past = (player.get('allPlayerGameScores', {}) or {}).get('nodes', []) or []
    future = (player.get('anyFutureGames', {}) or {}).get('nodes', []) or []
    log(f"Trovate {len(past)} partite passate, {len(future)} future.")
    return past, future


def load_cache():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    cache_file = os.path.join(CACHE_DIR, f'{PLAYER_SLUG}_detail_cache.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            try:
                return json.load(f), cache_file
            except json.JSONDecodeError:
                return {}, cache_file
    return {}, cache_file


def save_cache(cache, cache_file):
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def fetch_game_detail(score_id, cache, is_final):
    """Recupera il dettaglio granulare (detailedScore) di UNA partita.
    Usa la cache su disco per le partite gia' FINAL (non cambiano piu');
    le partite non-FINAL (REVIEWING/PENDING) vengono sempre riscaricate."""
    if is_final and score_id in cache:
        return cache[score_id]

    log(f"  -> Scarico dettaglio partita {score_id} (cache {'assente' if is_final else 'non applicabile, stato non finale'})...")
    data = graphql_query(GAME_SCORE_DETAIL_QUERY, {"id": score_id},
                          operation_name="PlayerGameScoreDetail")
    if data.get('errors'):
        log(f"  Errore dettaglio partita {score_id}: {data['errors']}")
        return None

    result = data.get('data', {}).get('so5', {}).get('playerGameScore')
    if result and is_final:
        cache[score_id] = result
    return result


# ---------------------------------------------------------------------------
# Logica di calcolo
# ---------------------------------------------------------------------------

def exponential_weights(n, half_life):
    """Genera n pesi con decadimento esponenziale: l'ultimo elemento (indice n-1,
    la partita piu' recente) ha peso massimo, il primo (piu' vecchio) il minimo.
    Il peso si dimezza ogni 'half_life' posizioni indietro."""
    decay = math.log(2) / half_life
    # indice 0 = partita piu' vecchia della finestra, n-1 = piu' recente
    weights = [math.exp(-decay * (n - 1 - i)) for i in range(n)]
    return weights


def weighted_mean(values, weights):
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_w


def weighted_stddev(values, weights, mean):
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total_w
    return math.sqrt(variance)


def team_ranking_from_game(game, player_team_slug):
    """Estrae ranking squadra giocatore e ranking avversario da un blocco anyGame
    (funziona sia per partite passate che future, stessa struttura)."""
    home = game.get('homeTeam') or {}
    away = game.get('awayTeam') or {}
    if home.get('slug') == player_team_slug:
        return home.get('domesticLeagueRanking'), away.get('domesticLeagueRanking'), True
    elif away.get('slug') == player_team_slug:
        return away.get('domesticLeagueRanking'), home.get('domesticLeagueRanking'), False
    return None, None, None


def build_prediction():
    past_games, future_games = fetch_game_log(PLAYER_SLUG, first=50)
    if not past_games:
        log("Nessuna partita trovata, impossibile procedere.")
        return None

    cache, cache_file = load_cache()

    # Filtra le partite con punteggio "utilizzabile" (esclude DID_NOT_PLAY) mantenendo
    # comunque un conteggio separato per il tasso di presenza storico.
    usable = []
    dnp_count = 0
    total_considered = 0

    for node in past_games:
        status = node.get('scoreStatus')
        total_considered += 1
        if status == 'DID_NOT_PLAY':
            dnp_count += 1
            continue
        if status in ('FINAL', 'REVIEWING'):
            usable.append(node)
        if len(usable) >= WINDOW_SIZE:
            break

    if not usable:
        log("Nessuna partita utilizzabile nella finestra.")
        return None

    # Ordine cronologico: allPlayerGameScores arriva dal piu' recente al piu' vecchio,
    # quindi invertiamo per avere indice 0 = piu' vecchia, ultimo = piu' recente
    usable = list(reversed(usable))

    log(f"Finestra di analisi: {len(usable)} partite utilizzabili (su {total_considered} esaminate, {dnp_count} DID_NOT_PLAY escluse).")

    # Scarica il dettaglio granulare per ogni partita della finestra (con cache)
    details = []
    for node in usable:
        score_id = node['id'].replace('So5Score:', '')
        is_final = node.get('scoreStatus') == 'FINAL'
        detail = fetch_game_detail(score_id, cache, is_final)
        details.append(detail)

    save_cache(cache, cache_file)

    # Determina la squadra del giocatore dalla partita piu' recente
    player_team_slug = None
    last_game = usable[-1]['anyGame']
    # Deduciamo la squadra del giocatore guardando quale delle due non cambia
    # tra le varie partite: usiamo l'euristica "squadra che compare in tutte le
    # partite casalinghe e in trasferta piu' di frequente" sui dati raccolti.
    team_counts = {}
    for node in usable:
        g = node['anyGame']
        for side in ('homeTeam', 'awayTeam'):
            t = (g.get(side) or {}).get('slug')
            if t:
                team_counts[t] = team_counts.get(t, 0) + 1
    if team_counts:
        player_team_slug = max(team_counts, key=team_counts.get)

    # Costruisce la serie di score utilizzabili + contesto casa/trasferta + ranking avversario
    scores = []
    is_home_flags = []
    opponent_rankings = []
    own_rankings = []

    for node, detail in zip(usable, details):
        scores.append(node.get('score', 0.0))
        game = node['anyGame']
        own_rank, opp_rank, is_home = team_ranking_from_game(game, player_team_slug)
        # fallback: se il ranking non e' nel game log base, prova dal dettaglio granulare
        if opp_rank is None and detail:
            own_rank, opp_rank, is_home = team_ranking_from_game(detail['anyGame'], player_team_slug)
        is_home_flags.append(is_home)
        opponent_rankings.append(opp_rank)
        own_rankings.append(own_rank)

    n = len(scores)
    weights = exponential_weights(n, HALF_LIFE_GAMES)

    media_pesata = weighted_mean(scores, weights)
    dev_std_pesata = weighted_stddev(scores, weights, media_pesata)

    # --- Fattore casa/trasferta ---
    home_scores = [s for s, h in zip(scores, is_home_flags) if h is True]
    away_scores = [s for s, h in zip(scores, is_home_flags) if h is False]
    home_avg = sum(home_scores) / len(home_scores) if home_scores else media_pesata
    away_avg = sum(away_scores) / len(away_scores) if away_scores else media_pesata
    overall_avg_for_factor = (home_avg + away_avg) / 2 if (home_scores and away_scores) else media_pesata

    # --- Prossima partita: contesto target ---
    if not future_games:
        log("Nessuna partita futura trovata.")
        return None
    next_node = future_games[0]['playerGameScore']
    next_game = next_node['anyGame']
    next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(next_game, player_team_slug)

    # se il ranking non e' nel blocco base, scarichiamo il dettaglio (funziona anche per future)
    if next_opp_rank is None:
        next_score_id = next_node['id'].replace('So5Score:', '')
        next_detail = fetch_game_detail(next_score_id, cache, is_final=False)
        if next_detail:
            next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(
                next_detail['anyGame'], player_team_slug)

    fattore_casa_trasferta = 1.0
    if overall_avg_for_factor > 0:
        if next_is_home:
            fattore_casa_trasferta = home_avg / overall_avg_for_factor
        else:
            fattore_casa_trasferta = away_avg / overall_avg_for_factor

    # --- Fattore forza avversario (lineare sul ranking assoluto) ---
    # Ranking medio delle 14 partite (tra gli avversari con dato disponibile)
    valid_opp_ranks = [r for r in opponent_rankings if r is not None]
    avg_opp_rank_hist = sum(valid_opp_ranks) / len(valid_opp_ranks) if valid_opp_ranks else None

    fattore_forza_avversario = 1.0
    if avg_opp_rank_hist and next_opp_rank:
        # rank piu' basso = squadra piu' forte. Se il prossimo avversario ha un
        # rank piu' basso (piu' forte) della media storica affrontata, penalizza.
        # Normalizzato su una scala approssimativa (assumendo ~29 squadre MLS).
        delta = (next_opp_rank - avg_opp_rank_hist) / 29.0
        fattore_forza_avversario = max(0.5, min(1.5, 1.0 + delta))

    # --- P(gioca) ---
    p_gioca = None
    p_source = None
    next_odds = ((next_node.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
    starter_odds = next_odds.get('starterOddsBasisPoints')
    if starter_odds is not None:
        p_gioca = starter_odds / 10000.0
        p_source = f"starterOddsBasisPoints ({starter_odds})"
    else:
        presence_rate = len(usable) / total_considered if total_considered else 1.0
        p_gioca = presence_rate
        p_source = f"tasso di presenza storico ({len(usable)}/{total_considered})"

    score_atteso = p_gioca * media_pesata * fattore_casa_trasferta * fattore_forza_avversario
    range_conf = dev_std_pesata  # stessa dev std pesata, non ri-scalata da P(gioca): scelta v1 semplice

    # --- Backtest: riapplica la stessa formula "a ritroso" sull'ultima partita nota ---
    last_real = usable[-1]
    last_real_score = last_real.get('score')
    backtest_prev = usable[:-1]
    backtest_scores = scores[:-1]
    backtest_weights = exponential_weights(len(backtest_scores), HALF_LIFE_GAMES) if backtest_scores else []
    backtest_media = weighted_mean(backtest_scores, backtest_weights) if backtest_scores else None

    result = {
        'player_slug': PLAYER_SLUG,
        'player_team_slug': player_team_slug,
        'window_size_used': n,
        'total_considered': total_considered,
        'dnp_excluded': dnp_count,
        'scores_used': scores,
        'weights_used': weights,
        'media_pesata': media_pesata,
        'dev_std_pesata': dev_std_pesata,
        'home_avg': home_avg,
        'away_avg': away_avg,
        'fattore_casa_trasferta': fattore_casa_trasferta,
        'avg_opp_rank_hist': avg_opp_rank_hist,
        'next_opp_rank': next_opp_rank,
        'next_own_rank': next_own_rank,
        'next_is_home': next_is_home,
        'fattore_forza_avversario': fattore_forza_avversario,
        'p_gioca': p_gioca,
        'p_source': p_source,
        'score_atteso': score_atteso,
        'range_conf': range_conf,
        'next_game': next_game,
        'backtest_last_real_score': last_real_score,
        'backtest_media_pesata_precedente': backtest_media,
        'usable_nodes': usable,
    }
    return result


def format_output(result):
    lines = []
    lines.append("=" * 70)
    lines.append(f"TOOL_FORMAZIONE_OWUSU - Prototipo v1")
    lines.append(f"Giocatore: {result['player_slug']} (squadra: {result['player_team_slug']})")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("=" * 70)

    lines.append("")
    lines.append("--- FINESTRA DI ANALISI ---")
    lines.append(f"Partite considerate: {result['total_considered']}")
    lines.append(f"Escluse (DID_NOT_PLAY): {result['dnp_excluded']}")
    lines.append(f"Partite usate nella media (dalla piu' vecchia alla piu' recente):")
    for node, s, w in zip(result['usable_nodes'], result['scores_used'], result['weights_used']):
        g = node['anyGame']
        date = (g.get('date') or '')[:10]
        home = (g.get('homeTeam') or {}).get('code', '?')
        away = (g.get('awayTeam') or {}).get('code', '?')
        comp = (g.get('competition') or {}).get('slug', '?')
        lines.append(f"  {date} | {home} vs {away} | {comp} | score={s:.1f} | peso={w:.3f}")

    lines.append("")
    lines.append("--- CALCOLO FATTORI ---")
    lines.append(f"Media pesata esponenziale (half-life {HALF_LIFE_GAMES} partite): {result['media_pesata']:.2f}")
    lines.append(f"Deviazione standard pesata: {result['dev_std_pesata']:.2f}")
    lines.append(f"Media score in casa: {result['home_avg']:.2f} | Media score fuori casa: {result['away_avg']:.2f}")
    lines.append(f"Fattore casa/trasferta applicato: {result['fattore_casa_trasferta']:.3f} "
                 f"({'CASA' if result['next_is_home'] else 'TRASFERTA'} nella prossima partita)")
    lines.append(f"Ranking medio avversari affrontati (storico): "
                 f"{result['avg_opp_rank_hist']:.1f}" if result['avg_opp_rank_hist'] else "N/D")
    lines.append(f"Ranking prossimo avversario: {result['next_opp_rank']}")
    lines.append(f"Fattore forza avversario applicato: {result['fattore_forza_avversario']:.3f}")
    lines.append(f"P(gioca): {result['p_gioca']:.2%} (fonte: {result['p_source']})")

    lines.append("")
    lines.append("--- PROSSIMA PARTITA ---")
    ng = result['next_game']
    lines.append(f"Data: {(ng.get('date') or '')[:16]}")
    lines.append(f"Casa: {(ng.get('homeTeam') or {}).get('name', '?')} | "
                 f"Trasferta: {(ng.get('awayTeam') or {}).get('name', '?')}")
    lines.append(f"Competizione: {(ng.get('competition') or {}).get('slug', '?')}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PREDIZIONE")
    lines.append("=" * 70)
    lines.append(f"Score atteso: {result['score_atteso']:.1f} +/- {result['range_conf']:.1f}")
    lines.append(f"  (range: {result['score_atteso'] - result['range_conf']:.1f} - "
                 f"{result['score_atteso'] + result['range_conf']:.1f})")

    lines.append("")
    lines.append("--- BACKTEST (verifica su ultima partita reale nota) ---")
    if result['backtest_media_pesata_precedente'] is not None:
        lines.append(f"Media pesata calcolata SENZA l'ultima partita: "
                     f"{result['backtest_media_pesata_precedente']:.2f}")
        lines.append(f"Punteggio REALE ottenuto in quella partita: "
                     f"{result['backtest_last_real_score']:.1f}")
        errore = result['backtest_last_real_score'] - result['backtest_media_pesata_precedente']
        lines.append(f"Errore (reale - predetto, solo componente media, senza fattori "
                     f"casa/trasferta/avversario applicati a ritroso): {errore:+.1f}")
        lines.append("NOTA: questo backtest confronta solo la componente 'media pesata' con "
                     "il punteggio reale, senza applicare P(gioca)/fattore avversario/casa-trasferta "
                     "storici a quella specifica partita passata. E' un primo controllo di sanita', "
                     "un backtest piu' rigoroso (che riapplica l'intera formula partita per partita "
                     "nel passato) va costruito come step successivo.")
    else:
        lines.append("Dati insufficienti per il backtest.")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    log("Avvio prototipo Tool_formazione_owusu...")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    result = build_prediction()
    if result is None:
        log("Impossibile generare la predizione, dati insufficienti.")
        return

    output_text = format_output(result)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join(OUTPUT_DIR, f'prediction_{PLAYER_SLUG}_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(output_text)

    log(f"Output scritto in: {out_path}")
    print("\n" + output_text)


if __name__ == '__main__':
    main()
