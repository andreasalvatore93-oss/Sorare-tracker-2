"""backtest_arene_previsioni — la previsione di PRODUZIONE, rigiocata all'indietro.

Per ogni (giocatore, giornata) ricostruisce esattamente cio' che il modello
avrebbe visto a quella data e chiama le stesse funzioni condivise usate in
produzione (`compute_score_atteso_gk/def/mid/fwd`): nessuna formula
riscritta qui, altrimenti il backtest misurerebbe un modello che non esiste
(e' l'errore gia' costato caro in passato, vedi sezione 26 del riassunto).

Walk-forward stretto: si guardano solo le partite con data STRETTAMENTE
precedente a quella della partita target della giornata.

Due scostamenti noti dalla produzione, entrambi documentati e nella stessa
direzione della calibrazione (che li fa gia' cosi'):
  - `opponent_lambda_mult` / Stadio D restano ai default: dipendono da file
    di forza avversario costruiti sul dato ODIERNO, che in un backtest
    sarebbero informazione dal futuro.
  - `p_gioca` = 1.0: nel pool ci sono solo carte che l'utente ha davvero
    schierato, quindi giocatori che hanno giocato.
"""
import os
import sys
import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, 'formazione_mls', 'predict'))
sys.path.insert(0, _ROOT)

import test_gk
import test_def
import test_mid
import test_mls_fwd_all as test_fwd

MAX_HISTORY_DAYS = 365
MIN_SAME_COMPETITION = 20
MIN_USABLE_GAMES = 3
WINDOW_SIZE = test_def.WINDOW_SIZE

_MODULO = {
    'Goalkeeper': test_gk,
    'Defender': test_def,
    'Midfielder': test_mid,
    'Forward': test_fwd,
}


def _dt(iso):
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _data(nodo):
    return _dt((nodo.get('anyGame') or {}).get('date'))


def partita_target(cache, slug, fine_giornata, giorni_finestra=6):
    """L'ultima partita giocata dal giocatore dentro la finestra della giornata."""
    inizio = fine_giornata - datetime.timedelta(days=giorni_finestra)
    cand = [n for n in cache.gamelog(slug)
            if n.get('anyGame') and inizio <= (_data(n) or inizio) <= fine_giornata]
    return cand[-1] if cand else None


def _squadra(usable, target_competition):
    same = [n for n in usable
            if (n['anyGame'].get('competition') or {}).get('slug') == target_competition] \
        if target_competition else []
    fonte = same if same else usable
    recenti = fonte[-5:] if len(fonte) >= 5 else fonte
    conteggi = {}
    for n in recenti:
        g = n['anyGame']
        for lato in ('homeTeam', 'awayTeam'):
            t = (g.get(lato) or {}).get('slug')
            if t:
                conteggi[t] = conteggi.get(t, 0) + 1
    return max(conteggi, key=conteggi.get) if conteggi else None


def finestra_storica(cache, slug, cutoff, target_competition):
    """Le partite utilizzabili prima di `cutoff`, con gli stessi filtri di
    produzione. Ritorna (usable, presence_rate) oppure (None, None).

    In piu' rispetto alla produzione: si scartano le partite di cui NON
    abbiamo il dettaglio granulare in cache. In produzione il dettaglio si
    scarica sempre, qui manca per circa una partita su tre, e senza dettaglio
    `extract_level_score` torna 0.0 -- il che fa credere alla formula che
    l'INTERO punteggio sia "granulare", gonfiando la previsione (misurato:
    +10-15 punti). Meglio una finestra piu' corta ma con gli stessi ingressi
    che avrebbe avuto la produzione."""
    limite = cutoff - datetime.timedelta(days=MAX_HISTORY_DAYS)
    passate = [n for n in cache.gamelog(slug)
               if (_data(n) or limite) < cutoff and (_data(n) or limite) >= limite]
    if not passate:
        return None, None

    if target_competition:
        stessa = [n for n in passate
                  if (n.get('anyGame', {}).get('competition') or {}).get('slug') == target_competition]
        if len(stessa) >= MIN_SAME_COMPETITION:
            passate = stessa

    usable = []
    totale = 0
    for nodo in reversed(passate):  # dal piu' recente
        stato = nodo.get('scoreStatus')
        if stato == 'DID_NOT_PLAY':
            totale += 1
            continue
        if stato in ('FINAL', 'REVIEWING'):
            mins = (nodo.get('anyPlayerGameStats') or {}).get('minsPlayed')
            if mins is not None and mins < test_def.MIN_MINUTES_PLAYED:
                totale += 1
                continue
            if cache.dettaglio_partita(slug, nodo['id'].replace('So5Score:', '')) is None:
                # partita ignorata del tutto: non e' un'assenza, e' un buco di
                # cache -- non deve abbassare il tasso di presenza storico
                continue
            totale += 1
            usable.append(nodo)
        if len(usable) >= WINDOW_SIZE:
            break

    if len(usable) < MIN_USABLE_GAMES:
        return None, None
    usable.reverse()  # cronologico
    return usable, (len(usable) / totale if totale else 1.0)


def _serie(modulo, cache, slug, usable, squadra):
    """Ricostruisce gli array che build_prediction passa a compute_score_atteso."""
    s = {k: [] for k in ('scores', 'is_home', 'opp_rank', 'granulari', 'pos_dec',
                         'neg_dec', 'passing', 'offensive', 'goals_conceded',
                         'clean_sheet', 'residual', 'duels', 'fouls',
                         'defense_rare', 'defensive_actions', 'goalkeeping',
                         # avversario e data di OGNI partita storica (03/08):
                         # servono allo Stadio D di DEF/MID, che condiziona
                         # sull'avversario forte/debole a quella data
                         'opp_slug', 'date')}
    for nodo in usable:
        score = nodo.get('score') or 0.0
        det = cache.dettaglio_partita(slug, nodo['id'].replace('So5Score:', ''))
        gioco = nodo['anyGame']
        _own, opp, casa = modulo.team_ranking_from_game(gioco, squadra)
        if opp is None and det and det.get('anyGame'):
            _own, opp, casa = modulo.team_ranking_from_game(det['anyGame'], squadra)
        s['scores'].append(score)
        s['is_home'].append(casa)
        s['opp_rank'].append(opp)

        livello = modulo.extract_level_score(det)
        s['granulari'].append(score - livello)
        pos, neg = modulo.extract_decisive_rates(det)
        s['pos_dec'].append(pos)
        s['neg_dec'].append(neg)

        gruppo = lambda nome: (modulo.extract_group_score(det, getattr(modulo, nome))
                               if hasattr(modulo, nome) else 0.0)
        passing = gruppo('PASSING_STATS')
        offensive = gruppo('OFFENSIVE_STATS')
        subiti = gruppo('GOALS_CONCEDED_STATS')
        clean = gruppo('CLEAN_SHEET_STATS')
        duels = gruppo('DUELS_STATS')
        fouls = gruppo('FOULS_STATS')
        rare = gruppo('DEFENSE_RARE_STATS')
        azioni = gruppo('DEFENSIVE_ACTIONS_STATS')
        s['passing'].append(passing)
        s['offensive'].append(offensive)
        s['goals_conceded'].append(subiti)
        s['clean_sheet'].append(clean)
        s['duels'].append(duels)
        s['fouls'].append(fouls)
        s['defense_rare'].append(rare)
        s['defensive_actions'].append(azioni)
        s['goalkeeping'].append(gruppo('GOALKEEPING_STATS'))
        coperto = (fouls + duels + offensive + passing + rare + azioni + subiti + clean)
        s['residual'].append(score - coperto)
        casa_t, fuori_t = gioco.get('homeTeam') or {}, gioco.get('awayTeam') or {}
        if casa_t.get('slug') == squadra:
            s['opp_slug'].append(fuori_t.get('slug'))
        elif fuori_t.get('slug') == squadra:
            s['opp_slug'].append(casa_t.get('slug'))
        else:
            s['opp_slug'].append(None)
        s['date'].append(_data(nodo))
    return s


def contesto(cache, slug, ruolo, fine_giornata):
    """Tutti gli ingressi della previsione, senza ancora calcolarla.

    Estratto da score_atteso (03/08) perche' la taratura di half_life e
    trend_intensity deve valutare DECINE di combinazioni sullo stesso
    giocatore-partita: ricostruire la finestra storica e le serie granulari
    una volta per combinazione costerebbe ore, e sarebbe anche l'occasione
    perfetta per farle divergere. Qui si costruiscono una volta sola e si
    ricalcola solo la formula."""
    modulo = _MODULO.get(ruolo)
    if modulo is None:
        return None
    target = partita_target(cache, slug, fine_giornata)
    if target is None:
        return None
    cutoff = _data(target)
    competizione = ((target['anyGame'].get('competition') or {}).get('slug'))
    usable, presenza = finestra_storica(cache, slug, cutoff, competizione)
    if not usable:
        return None
    squadra = _squadra(usable, competizione)
    _own, opp_rank, casa = modulo.team_ranking_from_game(target['anyGame'], squadra)
    s = _serie(modulo, cache, slug, usable, squadra)
    g = target['anyGame']
    casa_t, fuori_t = g.get('homeTeam') or {}, g.get('awayTeam') or {}
    if casa_t.get('slug') == squadra:
        opp_slug = fuori_t.get('slug')
    elif fuori_t.get('slug') == squadra:
        opp_slug = casa_t.get('slug')
    else:
        opp_slug = None
    return {'modulo': modulo, 'ruolo': ruolo, 's': s, 'casa': casa,
            'opp_rank': opp_rank, 'presenza': presenza, 'cutoff': cutoff,
            'squadra': squadra, 'opp_slug': opp_slug,
            'lega': None}


def _avversario(ctx):
    """Gli argomenti che accendono gli aggiustamenti avversario.

    Il banco li teneva spenti "perche' i file di forza avversario sono
    costruiti sul dato odierno, che in un backtest sarebbe informazione dal
    futuro". Non regge piu': ogni funzione di opponent_strength filtra su
    `dt < cutoff_dt`, quindi passando la data della partita storica si guarda
    solo il passato. Tenendoli spenti si finiva invece per tarare i loro
    coefficienti su un modello in cui quei coefficienti non agivano."""
    s = ctx['s']
    return {'opp_slug': ctx.get('opp_slug'), 'quando': ctx.get('cutoff'),
            'lega': ctx.get('lega'), 'hist_slug': s.get('opp_slug'),
            'hist_date': s.get('date')}


def calcola(ctx, half_life=None, trend_intensity=None, shrink_k=None,
            usa_avversario=False):
    """La previsione di produzione dagli ingressi di `contesto`.

    half_life/trend_intensity servono SOLO alla taratura: lasciati a None si
    usano le costanti di produzione del modulo, cioe' il comportamento
    invariato."""
    modulo, s, ruolo = ctx['modulo'], ctx['s'], ctx['ruolo']
    casa, opp_rank, presenza = ctx['casa'], ctx['opp_rank'], ctx['presenza']
    extra = {}
    if half_life is not None:
        extra['half_life'] = half_life
    if trend_intensity is not None:
        extra['trend_intensity'] = trend_intensity
    if shrink_k is not None:
        extra['shrink_k'] = shrink_k

    av = _avversario(ctx) if usa_avversario else None

    if ruolo == 'Goalkeeper':
        if av:
            import opponent_strength as ops
            extra['opponent_lambda_mult'] = ops.opponent_lambda_multiplier(
                av['lega'], 'gk', av['opp_slug'], av['quando'])
            w = modulo.exponential_weights(
                len(s['scores']), extra.get('half_life', modulo.HALF_LIFE_GAMES))
            extra['pen_area_delta'] = ops.gk_def_pen_area_granular_delta(
                av['lega'], av['opp_slug'], av['quando'],
                modulo.weighted_mean(s['goalkeeping'], w))
        return modulo.compute_score_atteso_gk(
            s['scores'], s['is_home'], s['granulari'], s['pos_dec'], s['neg_dec'],
            target_is_home=casa, presence_rate=presenza, **extra)
    if ruolo == 'Defender':
        if av:
            extra.update({'next_opponent_team_slug': av['opp_slug'],
                          'next_game_date': av['quando'], 'league': av['lega'],
                          'opponent_team_slugs_hist': av['hist_slug'],
                          'game_dates_hist': av['hist_date']})
        return modulo.compute_score_atteso_def(
            s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
            s['pos_dec'], s['neg_dec'], s['goals_conceded'], s['passing'], s['clean_sheet'],
            target_is_home=casa, target_opp_rank=opp_rank, presence_rate=presenza, **extra)
    if ruolo == 'Midfielder':
        if av:
            import opponent_strength as ops
            extra.update({'opponent_lambda_mult': ops.opponent_lambda_multiplier(
                              av['lega'], 'mid', av['opp_slug'], av['quando']),
                          'target_opponent_team_slug': av['opp_slug'],
                          'target_cutoff_dt': av['quando'], 'league': av['lega'],
                          'opponent_team_slugs': av['hist_slug'],
                          'game_dates': av['hist_date']})
        return modulo.compute_score_atteso_mid(
            s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
            s['pos_dec'], s['neg_dec'], s['offensive'], s['passing'], s['goals_conceded'],
            target_is_home=casa, target_opp_rank=opp_rank, presence_rate=presenza, **extra)
    if av:
        extra.update({'next_opponent_team_slug': av['opp_slug'],
                      'next_game_date': av['quando'], 'league': av['lega']})
    return modulo.compute_score_atteso_fwd(
        s['scores'], s['is_home'], s['residual'], s['granulari'],
        s['pos_dec'], s['neg_dec'], s['passing'],
        target_is_home=casa, presence_rate=presenza,
        offensive_values=s['offensive'], **extra)


def calcola_con_maschera(ctx, half_life=None, trend_intensity=None):
    """Come `calcola`, ma passando anche detail_ok_flags al modello.

    Serve a confronta_fix_dettaglio.py: `calcola` da solo non puo' esercitare
    la maschera, perche' `finestra_storica` scarta gia' le partite senza
    dettaglio e quindi la maschera non avrebbe niente da mascherare."""
    modulo, s, ruolo_ = ctx['modulo'], ctx['s'], ctx['ruolo']
    casa, opp_rank, presenza = ctx['casa'], ctx['opp_rank'], ctx['presenza']
    extra = {'detail_ok_flags': ctx.get('detail_ok_flags')}
    if half_life is not None:
        extra['half_life'] = half_life
    if trend_intensity is not None:
        extra['trend_intensity'] = trend_intensity

    if ruolo_ == 'Goalkeeper':
        return modulo.compute_score_atteso_gk(
            s['scores'], s['is_home'], s['granulari'], s['pos_dec'], s['neg_dec'],
            target_is_home=casa, presence_rate=presenza, **extra)
    if ruolo_ == 'Defender':
        return modulo.compute_score_atteso_def(
            s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
            s['pos_dec'], s['neg_dec'], s['goals_conceded'], s['passing'], s['clean_sheet'],
            target_is_home=casa, target_opp_rank=opp_rank, presence_rate=presenza, **extra)
    if ruolo_ == 'Midfielder':
        return modulo.compute_score_atteso_mid(
            s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
            s['pos_dec'], s['neg_dec'], s['offensive'], s['passing'], s['goals_conceded'],
            target_is_home=casa, target_opp_rank=opp_rank, presence_rate=presenza, **extra)
    return modulo.compute_score_atteso_fwd(
        s['scores'], s['is_home'], s['residual'], s['granulari'],
        s['pos_dec'], s['neg_dec'], s['passing'],
        target_is_home=casa, presence_rate=presenza,
        offensive_values=s['offensive'], **extra)


def score_atteso(cache, slug, ruolo, fine_giornata):
    """Il punteggio atteso di produzione per quella giornata, o None.

    Ritorna un dizionario con previsione, L10 al momento della scelta e la
    partita target (serve per sapere in casa/fuori e per il taglio storico)."""
    ctx = contesto(cache, slug, ruolo, fine_giornata)
    if ctx is None:
        return None
    s, casa, cutoff, squadra = ctx['s'], ctx['casa'], ctx['cutoff'], ctx['squadra']
    atteso = calcola(ctx)

    # L10 al momento della scelta: la stessa misura che Sorare usa per il cap
    # delle arene (media degli ultimi 10 punteggi validi prima della giornata).
    validi = [n for n in cache.gamelog(slug)
              if (_data(n) or cutoff) < cutoff and n.get('scoreStatus') in ('FINAL', 'REVIEWING')]
    ultimi = validi[-10:]
    l10 = (sum(n.get('score') or 0.0 for n in ultimi) / len(ultimi)) if len(ultimi) >= 3 else None

    return {'atteso': atteso, 'l10': l10, 'partite_storiche': len(s['scores']),
            'in_casa': casa, 'data_partita': cutoff,
            # la squadra del giocatore, dedotta dallo storico: serve a
            # raggruppare i COMPAGNI quando si misura la correlazione
            'squadra': squadra}
