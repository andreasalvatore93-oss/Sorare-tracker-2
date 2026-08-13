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
import intralega_segnale

# Stesso alias del badge "nuovo campionato" e di p33: la J1 100 Year Vision e'
# la stessa lega della J1 pur avendo una cartella propria nel repo.
_ALIAS_LEGA = {'giappone100': 'giappone'}

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


def diagnostica_staleness_cache(cache, slug_list, fine_giornata, giorni_finestra=6):
    """Difetto D3 (freschezza cache game-log). partita_target() torna None se la
    cache non contiene una partita del giocatore nella finestra della giornata;
    i chiamanti (backtest) SCARTANO quella carta IN SILENZIO. Se la cache non e'
    stata aggiornata dopo la GW che si sta testando, si scartano carte che in
    produzione ci sarebbero state -> il test misura un campione mutilato senza
    dirlo (viola CLAUDE.md D1: "mai scartare in silenzio").

    Questa funzione NON modifica partita_target ne' il flusso: e' una diagnosi
    da chiamare PRIMA di un backtest e stampare in chiaro. Dato l'elenco degli
    slug che verranno testati e il cutoff della GW, ritorna un dict con:
      - n_slug, n_target_trovato, n_target_mancante (tornerebbero None)
      - slug_mancanti (lista)
      - ultima_partita_in_cache (max data su TUTTA la cache degli slug dati)
      - cache_piu_vecchia_della_gw (bool): True se la partita piu' recente in
        cache e' PRECEDENTE alla fine giornata -> forte sospetto di staleness,
        non di semplice "giocatore fermo".
    Regola d'uso: se cache_piu_vecchia_della_gw e' True O n_target_mancante e'
    una quota non trascurabile, FERMARSI e aggiornare la cache prima di fidarsi
    dei numeri. Non e' Claude a decidere la soglia: si riporta il numero grezzo.
    """
    n_trovato = 0
    mancanti = []
    ultima_globale = None
    for slug in slug_list:
        # data piu' recente in assoluto per questo slug (serve a distinguere
        # "cache stale" da "giocatore che non gioca da un po'")
        for n in cache.gamelog(slug):
            d = _data(n)
            if d is not None and (ultima_globale is None or d > ultima_globale):
                ultima_globale = d
        if partita_target(cache, slug, fine_giornata, giorni_finestra) is not None:
            n_trovato += 1
        else:
            mancanti.append(slug)
    return {
        'n_slug': len(slug_list),
        'n_target_trovato': n_trovato,
        'n_target_mancante': len(mancanti),
        'slug_mancanti': mancanti,
        'ultima_partita_in_cache': ultima_globale.isoformat() if ultima_globale else None,
        'cache_piu_vecchia_della_gw': (
            ultima_globale is not None and ultima_globale < fine_giornata),
    }


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


_LEAGUE_DIR_CACHE = {}


def _cartella_lega(competizione):
    """competizione Sorare -> cartella del repo ('laliga-es' -> 'spagna').

    Serve perche' i predict di produzione identificano la lega con la
    CARTELLA (`league='spagna'` nella firma di formazione_spagna/predict/),
    e le tabelle per-lega sono chiavate cosi'. La mappa si legge da
    LEAGUE_DIR in discovery_fixture.py con una regex invece di importare quel
    modulo: qui serve un dizionario, non le sue dipendenze."""
    if not _LEAGUE_DIR_CACHE:
        import re as _re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'discovery_fixture.py')
        try:
            with open(path, encoding='utf-8') as f:
                blocco = _re.search(r'LEAGUE_DIR\s*=\s*\{(.*?)\n\}', f.read(), _re.S)
            _LEAGUE_DIR_CACHE.update(
                _re.findall(r"'([a-z0-9\-]+)'\s*:\s*'([a-z0-9_]+)'", blocco.group(1)))
        except Exception:
            _LEAGUE_DIR_CACHE['__vuota__'] = ''
    return _LEAGUE_DIR_CACHE.get(competizione)


def contesto(cache, slug, ruolo, fine_giornata, cutoff_giornata=None):
    """Tutti gli ingressi della previsione, senza ancora calcolarla.

    Estratto da score_atteso (03/08) perche' la taratura di half_life e
    trend_intensity deve valutare DECINE di combinazioni sullo stesso
    giocatore-partita: ricostruire la finestra storica e le serie granulari
    una volta per combinazione costerebbe ore, e sarebbe anche l'occasione
    perfetta per farle divergere. Qui si costruiscono una volta sola e si
    ricalcola solo la formula.

    `cutoff_giornata`, se passato, e' il momento di BLOCCO della giornata
    (primo calcio d'inizio) e sostituisce la data della partita-bersaglio
    del singolo giocatore come taglio per storia/L10. Senza, un giocatore con
    piu' partite dentro la stessa finestra-giornata vede nella sua storia
    risultati che sono in realta' della giornata stessa (leak, 03/08)."""
    modulo = _MODULO.get(ruolo)
    if modulo is None:
        return None
    target = partita_target(cache, slug, fine_giornata)
    if target is None:
        return None
    cutoff = cutoff_giornata if cutoff_giornata is not None else _data(target)
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
            # FIX (04/08, bug 5.5 verifica_canale_avversario): era sempre
            # None, che fa cadere opponent_strength sulla serie GLOBALE
            # pooled invece che su quella MLS -- build_prediction passa
            # sempre 'mls' letterale (vedi test_{def,gk,mid,mls_fwd_all}.py,
            # opponent_lambda_multiplier). Questo modulo importa solo i 4
            # file predict/ di MLS (_MODULO sopra), quindi la lega vera per
            # QUALUNQUE chiamata qui dentro e' sempre 'mls'.
            'lega': 'mls',
            # LA LEGA VERA della partita-bersaglio (13/08/2026), separata da
            # 'lega' apposta. 'lega' sopra resta 'mls' perche' su quella sono
            # tarati i coefficienti di opponent_strength usati qui: cambiarla
            # sposterebbe misure che non c'entrano niente con questo filone.
            # Questa invece serve a tutto cio' che dipende dal CAMPIONATO in
            # cui si gioca davvero (PRIOR_LEGA). Senza, ogni giocatore del
            # mondo veniva calcolato come se fosse in MLS e qualunque misura
            # per-lega sarebbe uscita piatta -- cioe' "non serve" -- per un
            # difetto del banco, non per un fatto sul modello.
            'lega_vera': _cartella_lega(competizione),
            # Quota dello storico giocata in una competizione DIVERSA da
            # quella della partita bersaglio: e' il segnale "questo viene da
            # un'altra lega", su cui PRIOR_LEGA decide se correggere. Si
            # calcola sulla stessa finestra che il modello usa davvero
            # (`usable`), non su tutto il game-log.
            'quota_altra_lega': _quota_altra_competizione(usable, competizione),
            # La lega DA CUI viene lo storico: la competizione piu' frequente
            # nella finestra. Serve alla modalita' 'diretto' di PRIOR_LEGA,
            # che deve sapere rispetto a quale livello il giocatore era
            # sopra o sotto.
            'lega_storico': _lega_dominante_storico(usable)}


def _lega_dominante_storico(usable):
    """La cartella della competizione piu' frequente nella finestra storica.
    None se nessuna di quelle partite e' di un campionato noto: in quel caso
    non si corregge (non si sa da dove viene)."""
    if not usable:
        return None
    conta = {}
    for n in usable:
        slug = (n.get('anyGame', {}).get('competition') or {}).get('slug')
        cart = _cartella_lega(slug) if slug else None
        if cart:
            conta[cart] = conta.get(cart, 0) + 1
    if not conta:
        return None
    return max(conta.items(), key=lambda kv: kv[1])[0]


def _quota_altra_competizione(usable, competizione):
    """Quante delle partite della finestra storica sono state giocate in
    un'altra competizione. None se non si puo' dire (nessuna partita, o
    competizione bersaglio ignota): chi legge tratta None come 'non
    correggere', mai come zero."""
    if not usable or not competizione:
        return None
    altre = sum(1 for n in usable
                if ((n.get('anyGame', {}).get('competition') or {}).get('slug')
                    != competizione))
    return altre / len(usable)


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


# Blend porta inviolata squadra per i GK (03/08). Il peso si LEGGE da
# test_gk.GK_TEAM_CS_WEIGHT, non si duplica qui: cosi' calibrazione e backtest
# misurano per forza il modello VERO. Il numero era duplicato a 0.5 con un
# commento che lo dichiarava "come produzione": falso da P9-ter (05/08), che
# l'ha portato a 22/35 -- chiunque lanciasse una misura senza esportare la
# variabile d'ambiente girava su un modello che non esiste piu' (trovato in
# P11). Il fallback 22/35 vale solo se l'attributo sparisse da test_gk.
# test_gk legge a sua volta la stessa variabile d'ambiente, quindi
# GK_TEAM_CS_WEIGHT=0 continua a spegnere il blend per l'A/B acceso-spento.
_GK_CS_WEIGHT = float(getattr(test_gk, 'GK_TEAM_CS_WEIGHT', 22.0 / 35.0) or 0)
_FORZE_CS = None   # (checkpoint settimanali, forze) del modello_partita, pigro


def _pcs_squadra(ctx):
    """P(porta inviolata) della squadra del GK per QUESTA partita, dal
    modello_partita (walk-forward: forza stimata sul solo passato rispetto al
    cutoff). None se squadra/avversario non abbastanza noti."""
    import math as _m, bisect as _b
    global _FORZE_CS
    A, B, cutoff = ctx.get('squadra'), ctx.get('opp_slug'), ctx.get('cutoff')
    if not A or not B or not cutoff:
        return None
    if _FORZE_CS is None:
        import modello_partita as mp
        oss = mp.osservazioni(mp.partite_da_cache())
        oss.sort(key=lambda o: o['data'])
        darr = [o['data'] for o in oss]
        cps, fz = [], []
        if oss:
            d = oss[0]['data']
            while d <= oss[-1]['data'] + datetime.timedelta(days=7):
                lo = _b.bisect_left(darr, d)
                if lo >= 400:
                    cps.append(d)
                    fz.append(mp.stima(oss[:lo], riferimento=d,
                                       regolarizzazione=0.30, emivita=120.0))
                d += datetime.timedelta(days=7)
        _FORZE_CS = (cps, fz)
    cps, fz = _FORZE_CS
    if not cps:
        return None
    try:
        co = datetime.datetime.strptime(str(cutoff)[:10], '%Y-%m-%d')
    except ValueError:
        return None
    i = _b.bisect_right(cps, co) - 1
    if i < 0:
        return None
    f = fz[i]
    if not (f.conosciuta(A) and f.conosciuta(B)):
        return None
    # gol attesi di B (avversario) contro A = quanti A ne subisce; B in casa se A fuori
    lam = f.lambda_atteso(B, A, in_casa=not ctx.get('casa'))
    return _m.exp(-lam)


def _forze_partita():
    """Checkpoint settimanali di ForzaSquadre, condivisi da tutti gli usi.

    Estratto da `_pcs_squadra` (04/08) quando il differenziale di gol attesi
    e' diventato un secondo cliente: la stima costa minuti, va fatta una volta
    sola per processo."""
    import bisect as _b
    global _FORZE_CS
    if _FORZE_CS is None:
        import modello_partita as mp
        oss = mp.osservazioni(mp.partite_da_cache())
        oss.sort(key=lambda o: o['data'])
        darr = [o['data'] for o in oss]
        cps, fz = [], []
        if oss:
            d = oss[0]['data']
            while d <= oss[-1]['data'] + datetime.timedelta(days=7):
                lo = _b.bisect_left(darr, d)
                if lo >= 400:
                    cps.append(d)
                    fz.append(mp.stima(oss[:lo], riferimento=d,
                                       regolarizzazione=0.30, emivita=120.0))
                d += datetime.timedelta(days=7)
        _FORZE_CS = (cps, fz)
    return _FORZE_CS


def _forza_a(quando):
    """Le forze stimate col solo passato rispetto a `quando`."""
    import bisect as _b
    cps, fz = _forze_partita()
    if not cps or not quando:
        return None
    try:
        co = datetime.datetime.strptime(str(quando)[:10], '%Y-%m-%d')
    except ValueError:
        return None
    i = _b.bisect_right(cps, co) - 1
    return fz[i] if i >= 0 else None


def _favorito(squadra, avversario, quando, in_casa):
    """Gol attesi della squadra meno gol attesi dell'avversario.

    E' la misura di quanto quella partita e' facile: `segnale_dentro_giocatore`
    l'ha trovata l'unico predittore dello scarto di un giocatore dalla propria
    media (corr +0.133, IC a grappoli [+0.088,+0.179], +8.8 pt fra il quinto
    piu' favorevole e il meno favorevole). Il fattore campo non serve a parte:
    in regressione congiunta e' interamente assorbito da qui."""
    f = _forza_a(quando)
    if f is None or not squadra or not avversario:
        return None
    if not (f.conosciuta(squadra) and f.conosciuta(avversario)):
        return None
    return (f.lambda_atteso(squadra, avversario, in_casa=in_casa)
            - f.lambda_atteso(avversario, squadra, in_casa=not in_casa))


def delta_favorito(ctx):
    """Quanto QUESTA partita e' piu' facile della media di quelle che il
    giocatore ha gia' giocato — ed e' l'unica forma utilizzabile.

    Il valore assoluto non va sommato: chi gioca in una squadra forte ha gia'
    uno storico di punteggi alti, quindi il modello lo sa gia' e sommarglielo
    di nuovo sarebbe un doppio conteggio. Quello che il modello NON sa e' che
    domenica quel giocatore incontra un avversario piu' debole del suo solito:
    e' la differenza rispetto alla propria media storica."""
    squadra, opp, cutoff, casa = (ctx.get('squadra'), ctx.get('opp_slug'),
                                  ctx.get('cutoff'), ctx.get('casa'))
    ora = _favorito(squadra, opp, cutoff, bool(casa))
    if ora is None:
        return None
    s = ctx['s']
    storici = []
    for opp_h, data_h, casa_h in zip(s.get('opp_slug') or [], s.get('date') or [],
                                     s.get('is_home') or []):
        # ogni partita storica pesata con le forze note ALLORA: usare quelle di
        # oggi sarebbe informazione dal futuro dentro la media di riferimento
        v = _favorito(squadra, opp_h, data_h, bool(casa_h))
        if v is not None:
            storici.append(v)
    if len(storici) < 5:
        return None
    return ora - (sum(storici) / len(storici))


def delta_ranking(ctx):
    """Quanto l'avversario di QUESTA partita e' piu' debole del solito, in
    posizioni di classifica.

    Stessa forma di `delta_favorito` (scarto dalla media degli avversari gia'
    affrontati, mai il livello assoluto: quello sta gia' dentro lo storico dei
    punteggi e sommarlo sarebbe doppio conteggio) ma con la variabile che sul
    pool grande batte il Poisson: 74.515 coppie, ranking grezzo corr +0.074
    contro +0.057 del differenziale di gol attesi, e in regressione congiunta
    il lambda non aggiunge piu' niente (IC [-0.300, +0.565], R2 +0.001%)
    mentre il ranking tiene (+0.236, IC [+0.203, +0.275]).

    Ranking ALTO = squadra messa peggio in classifica, quindi delta positivo
    = avversario piu' debole del solito = k positivo alza la previsione.

    Il taglio temporale e' automatico: `s['opp_rank']` contiene solo le
    partite precedenti al cutoff, e il ranking e' quello del blocco anyGame di
    allora, non quello di oggi.

    NIENTE doppio conteggio con fattore_forza_avversario (verificato 04/08,
    seconda verifica indipendente): quella variabile e' calcolata dentro
    build_prediction di tutti e quattro i ruoli ma NON entra in score_atteso --
    finisce solo nel dict diagnostico. Misurato: muovendo OPPONENT_SENSITIVITY
    fra 1.0, 29.0 e 1e9 su tutto il campione (n=75.474) MAE, correlazione e
    lift restano identici a sei decimali in tutti e quattro i ruoli. La
    versione precedente di questo commento diceva il contrario ed e' stata la
    premessa falsa del punto 5.2 di B.4.

    Il doppio conteggio REALE da tenere d'occhio e' un altro: DEF e MID
    condizionano gia' i granulari su "avversario forte/debole" dentro lo
    Stadio D (media_condizionata), e quando lo slug squadra non e' passato quel
    condizionamento ricade proprio su domesticLeagueRanking -- vedi
    docs/BUG_MISURA_STADIO_D_FALLBACK_RANKING.md."""
    ora = ctx.get('opp_rank')
    if ora is None:
        return None
    storici = [r for r in (ctx['s'].get('opp_rank') or []) if r is not None]
    if len(storici) < 5:
        return None
    return float(ora) - sum(storici) / len(storici)


def delta_casa(ctx):
    """Casa/trasferta come scarto dalla quota di partite in casa gia' giocate.

    PERCHE' ESISTE, visto che il modello uno split casa/trasferta ce l'ha gia'
    (compute_split_factor): sul pool grande il residuo dentro-giocatore correla
    ancora +0.056 col flag grezzo DOPO quello split, e in regressione congiunta
    col ranking il fattore campo NON viene assorbito (+1.868 punti,
    IC [+1.423, +2.265], R2 +0.208%). Questo termine misura quanto e' rimasto
    sul tavolo: e' un TETTO, non la correzione giusta.

    LA CORREZIONE GIUSTA sarebbe ritarare lo split che c'e' gia' (SPLIT_SHRINK_K,
    alzato 5->20 il 30/07) invece di sommarne un secondo sulla stessa cosa. Non
    e' stato possibile qui: quella costante e' una variabile LOCALE dentro
    compute_split_factor, non si puo' ne' passare ne' sostituire da fuori, e
    toccare formazione_mls/predict/* era escluso in questa sessione."""
    casa = ctx.get('casa')
    if casa is None:
        return None
    storici = [c for c in (ctx['s'].get('is_home') or []) if c is not None]
    if len(storici) < 5:
        return None
    return (1.0 if casa else 0.0) - sum(1.0 for c in storici if c) / len(storici)


_ODDS_1X2_PATH = os.path.join(_ROOT, 'dati_globali', 'odds_1x2_index.json')
_odds_1x2_index = None


def _carica_odds_1x2():
    global _odds_1x2_index
    if _odds_1x2_index is None:
        try:
            with open(_ODDS_1X2_PATH, encoding='utf-8') as fh:
                import json as _json
                _odds_1x2_index = _json.load(fh)
        except (OSError, ValueError):
            _odds_1x2_index = {}
    return _odds_1x2_index


def _p_own_opp_odds(squadra, avversario, quando):
    """(p_win_own, p_win_opp) dalle quote 1X2 pre-partita (SorareInside via
    `winOddsBasisPoints`), o None se la partita non e' nella finestra coperta
    (persistente da ~18/11/2025, vedi indagine 05/08) o e' eliteserien
    (esclusa in fase di costruzione dell'indice, sempre null misurato)."""
    if not squadra or not avversario or quando is None:
        return None
    idx = _carica_odds_1x2()
    if not idx:
        return None
    data = quando.strftime('%Y-%m-%d') if hasattr(quando, 'strftime') else str(quando)[:10]
    chiave = '|'.join(sorted([squadra, avversario]) + [data])
    riga = idx.get(chiave)
    if riga is None:
        return None
    if riga['home'] == squadra:
        return riga['p_home'], riga['p_away']
    elif riga['away'] == squadra:
        return riga['p_away'], riga['p_home']
    return None


def delta_favorito_odds(ctx):
    """Come `delta_favorito` (scarto dalla media storica del giocatore, mai il
    livello assoluto -- stesso motivo, evitare il doppio conteggio con lo
    storico dei punteggi) ma con favorito_odds = p_win_own - p_win_opp dalle
    quote 1X2 esterne invece del differenziale di gol attesi interno.

    MISURATO 05/08 (screening appaiato su 54.687 righe, finestra quote):
    corr singola +0.114 (IC[+0.106,+0.122]) contro +0.056 di `delta_favorito`
    sullo stesso campione; in regressione congiunta sopra
    rank_avversario+casa+favorito aggiunge R2 +0.58% e assorbe quasi tutto il
    segnale prima attribuito a rank_avversario e casa. INTERRUTTORE SPENTO
    di default (favorito_odds_k/favorito_odds_mult_k=None): nessuna variante
    e' stata ancora adottata in produzione, vedi taratura_confronto_odds.py."""
    squadra, opp, cutoff = ctx.get('squadra'), ctx.get('opp_slug'), ctx.get('cutoff')
    ora = _p_own_opp_odds(squadra, opp, cutoff)
    if ora is None:
        return None
    ora = ora[0] - ora[1]
    storici = []
    for opp_h, data_h in zip(ctx['s'].get('opp_slug') or [], ctx['s'].get('date') or []):
        v = _p_own_opp_odds(squadra, opp_h, data_h)
        if v is not None:
            storici.append(v[0] - v[1])
    if len(storici) < 5:
        return None
    return ora - (sum(storici) / len(storici))


def _p_draw_odds(squadra, avversario, quando):
    """p_draw dalle stesse quote 1X2 (10000 - home - away nell'indice, gia'
    salvato come p_home/p_away che sommano a <1: il resto e' il pareggio).
    None con le stesse condizioni di _p_own_opp_odds."""
    v = _p_own_opp_odds(squadra, avversario, quando)
    if v is None:
        return None
    return 1.0 - v[0] - v[1]


def delta_p_draw(ctx):
    """Come `delta_favorito_odds` (scarto dalla media storica del giocatore)
    ma su p_draw invece del differenziale p_win_own-p_win_opp. Ipotesi 06/08:
    favorito_odds scarta il pareggio (40-35-25 e 50-10-40 hanno differenziale
    simile ma sono partite opposte, chiusa vs aperta): p_draw alta e' il
    proxy di "partita bloccata", potenzialmente favorevole ai DEF/GK e
    sfavorevole ai FWD. INTERRUTTORE SPENTO di default (p_draw_k/
    p_draw_mult_k=None)."""
    squadra, opp, cutoff = ctx.get('squadra'), ctx.get('opp_slug'), ctx.get('cutoff')
    ora = _p_draw_odds(squadra, opp, cutoff)
    if ora is None:
        return None
    storici = []
    for opp_h, data_h in zip(ctx['s'].get('opp_slug') or [], ctx['s'].get('date') or []):
        v = _p_draw_odds(squadra, opp_h, data_h)
        if v is not None:
            storici.append(v)
    if len(storici) < 5:
        return None
    return ora - (sum(storici) / len(storici))


def delta_reparto_avv(ctx):
    """FILONE INTRALEGA (13/08/2026): quanto e' forte il reparto AVVERSARIO
    che questo giocatore affronta, misurato in VOTI SORARE dei giocatori veri
    di quel reparto invece che in gol (che e' quello che guarda oggi
    opponent_lambda_multiplier).

    Reparto guardato = quello opposto al ruolo: l'attaccante affronta i
    difensori, il difensore affronta gli attaccanti. Ritorna lo z (positivo =
    reparto avversario FORTE), quindi il k che ci si aspetta utile e'
    NEGATIVO: piu' forte l'avversario, meno rende il giocatore. Nessun segno
    nascosto qui dentro -- la griglia esplora entrambi i versi.

    None (nessuna correzione) se manca lo storico: e' il caso indicato
    dall'utente del neopromosso senza passato in quella lega."""
    ruolo = ctx.get('ruolo')
    reparto = {'Forward': 'def', 'Defender': 'fwd'}.get(ruolo)
    if reparto is None:
        return None
    lega = ctx.get('lega_vera')
    opp = ctx.get('opp_slug')
    quando = ctx.get('cutoff')
    if not lega or not opp or quando is None:
        return None
    return intralega_segnale.z_reparto(_ALIAS_LEGA.get(lega, lega), opp,
                                       reparto, quando)


def delta_gol_fatti_avv(ctx):
    """FILONE INTRALEGA (13/08/2026): quanti gol FA di solito l'avversario.

    Nasce da una misura, non da un'intuizione: sul difensore questo termometro
    correla -0,083 col voto realizzato, contro -0,038 dei voti degli
    attaccanti avversari -- ed e' una grandezza che oggi la produzione per il
    DIFENSORE non guarda affatto (SIGN_BY_ROLE['def']=+1, cioe' condiziona il
    difensore sui gol SUBITI dall'avversario, non su quelli fatti).

    La serie NON e' ricostruita qui: e' la stessa che usa la produzione
    (`opponent_strength._build_series_for_league`), letta col medesimo filtro
    walk-forward. Normalizzata con le costanti globali gia' validate."""
    opp, quando = ctx.get('opp_slug'), ctx.get('cutoff')
    if not opp or quando is None:
        return None
    import opponent_strength as ops
    _conceded, scored = ops._build_series_for_league(None)
    passate = [v for dt, v in scored.get(opp, []) if dt < quando]
    if len(passate) < ops.MIN_PARTITE_AVVERSARIO:
        return None
    ultime = passate[-ops.N_GAMES_DEFAULT:]
    media = sum(ultime) / len(ultime)
    return (media - ops.GLOBAL_MEAN_CONCEDED) / ops.GLOBAL_STD_CONCEDED


def calcola(ctx, half_life=None, trend_intensity=None, shrink_k=None,
            usa_avversario=False, favorito_k=None, ranking_k=None, casa_k=None,
            favorito_odds_k=None, favorito_odds_mult_k=None,
            p_draw_k=None, p_draw_mult_k=None, reparto_avv_k=None,
            gol_fatti_avv_k=None,
            avversario_lambda=True, avversario_stadio_d=True, sensitivity_by_role=None):
    """La previsione di produzione dagli ingressi di `contesto`.

    half_life/trend_intensity servono SOLO alla taratura: lasciati a None si
    usano le costanti di produzione del modulo, cioe' il comportamento
    invariato. `favorito_k` (punti per gol di differenziale) accende la
    correzione di contesto partita: 0 o None la lascia spenta.
    `ranking_k` (punti per posizione di classifica) accende la stessa
    correzione presa dal ranking grezzo invece che dal Poisson -- sono
    alternative, si tarano una alla volta.

    `avversario_lambda`/`avversario_stadio_d` (04/08, BRIEF baseline_canale_
    fwd_split, Parte 1.2): scompongono il canale avversario di DEF nelle sue
    due leve quando usa_avversario=True, per capire quale delle due pesa sul
    peggioramento misurato in Parte 1.1. False forza quella leva a neutro
    (opponent_lambda_mult=1.0 / use_stadio_d=False) mentre l'altra resta
    attiva. Default True = comportamento INVARIATO (entrambe attive come
    prima). Solo DEF li usa per ora (unico ruolo richiesto dal brief).

    `sensitivity_by_role` (04/08, BRIEF taratura_sensitivity): dict
    {'gk':.., 'def':.., 'mid':.., 'fwd':..} che sovrascrive
    opponent_strength.SENSITIVITY_BY_ROLE per la taratura di
    opponent_lambda_multiplier. None (default) = comportamento INVARIATO."""
    base = _calcola_base(ctx, half_life, trend_intensity, shrink_k, usa_avversario,
                         avversario_lambda, avversario_stadio_d, sensitivity_by_role)
    if isinstance(favorito_k, dict):
        # il portiere ha gia' questo segnale per un'altra strada (il blend
        # P(porta inviolata) di squadra, GK_TEAM_CS_WEIGHT, stesso
        # modello_partita): sommarglielo di nuovo peggiora tutto, misurato.
        favorito_k = favorito_k.get(ctx['ruolo'], 0.0)
    if isinstance(ranking_k, dict):
        ranking_k = ranking_k.get(ctx['ruolo'], 0.0)
    if favorito_k:
        delta = delta_favorito(ctx)
        if delta is not None:
            base = base + favorito_k * delta
    if ranking_k:
        delta = delta_ranking(ctx)
        if delta is not None:
            base = base + ranking_k * delta
    if isinstance(casa_k, dict):
        casa_k = casa_k.get(ctx['ruolo'], 0.0)
    if casa_k:
        delta = delta_casa(ctx)
        if delta is not None:
            base = base + casa_k * delta
    if favorito_odds_k:
        delta = delta_favorito_odds(ctx)
        if delta is not None:
            base = base + favorito_odds_k * delta
    if favorito_odds_mult_k:
        delta = delta_favorito_odds(ctx)
        if delta is not None:
            base = base * (1.0 + favorito_odds_mult_k * delta)
    if p_draw_k:
        delta = delta_p_draw(ctx)
        if delta is not None:
            base = base + p_draw_k * delta
    if p_draw_mult_k:
        delta = delta_p_draw(ctx)
        if delta is not None:
            base = base * (1.0 + p_draw_mult_k * delta)
    if isinstance(reparto_avv_k, dict):
        reparto_avv_k = reparto_avv_k.get(ctx['ruolo'], 0.0)
    if reparto_avv_k:
        delta = delta_reparto_avv(ctx)
        if delta is not None:
            base = base + reparto_avv_k * delta
    if isinstance(gol_fatti_avv_k, dict):
        gol_fatti_avv_k = gol_fatti_avv_k.get(ctx['ruolo'], 0.0)
    if gol_fatti_avv_k:
        delta = delta_gol_fatti_avv(ctx)
        if delta is not None:
            base = base + gol_fatti_avv_k * delta
    return base


def _calcola_base(ctx, half_life=None, trend_intensity=None, shrink_k=None,
                  usa_avversario=False, avversario_lambda=True, avversario_stadio_d=True,
                  sensitivity_by_role=None):
    """La previsione invariata, senza correzione di contesto partita."""
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
    # LA LEGA VA PASSATA SEMPRE (13/08/2026). Prima arrivava alle funzioni di
    # produzione solo dentro `if av:`, cioe' solo con usa_avversario acceso:
    # spento, ogni giocatore del mondo veniva calcolato con league='mls' (il
    # default della firma). Finche' `league` serviva solo a opponent_strength
    # -- gia' gated da next_opponent_team_slug -- non faceva danno, ma
    # qualunque misura su un parametro che dipende dalla lega (PRIOR_LEGA)
    # sarebbe stata falsata in silenzio: tutti MLS. Passarla e' innocuo a
    # correzioni spente (senza next_opponent_team_slug nessuna funzione la
    # legge) e necessario per misurare quelle nuove.
    # ...MA NON AL PORTIERE (bug reale, trovato il 13/08/2026 sera).
    # `compute_score_atteso_gk` NON ha il parametro `league` (gli altri tre
    # ruoli si'), quindi passarglielo alza TypeError. Il commento qui sopra
    # diceva "e' innocuo a correzioni spente": falso per il GK.
    # COME SI E' MANIFESTATO, ed e' il motivo per cui era rimasto nascosto:
    # `taratura_confronto_parametri.valuta` avvolge la chiamata in un
    # try/except che fa `continue`, quindi le righe GK sparivano IN SILENZIO
    # invece di far fallire la misura. Misurato: 957 punti GK su 1.068 (89,6%)
    # venivano buttati -- restavano solo quelli con la partita bersaglio in una
    # competizione fuori da LEAGUE_DIR (coppe), cioe' il campione peggiore
    # possibile. Le tabelle GK prodotte il 13/08 prima di questo fix sono da
    # rifare; DEF/MID/FWD non sono toccati.
    if ctx.get('lega_vera') and ruolo != 'Goalkeeper':
        extra.setdefault('league', ctx['lega_vera'])
    if ruolo == 'Forward':
        # solo FWD: e' l'unico ruolo in cui i parametri esistono finche' il
        # filone non e' deciso e propagato (propaga_modello.py)
        if ctx.get('quota_altra_lega') is not None:
            extra.setdefault('quota_altra_lega', ctx['quota_altra_lega'])
        if ctx.get('lega_storico'):
            extra.setdefault('lega_storico', ctx['lega_storico'])
    _sens = lambda ruolo_breve: (sensitivity_by_role.get(ruolo_breve) if sensitivity_by_role else None)

    if ruolo == 'Goalkeeper':
        if av:
            import opponent_strength as ops
            extra['opponent_lambda_mult'] = ops.opponent_lambda_multiplier(
                av['lega'], 'gk', av['opp_slug'], av['quando'], sensitivity=_sens('gk'))
            w = modulo.exponential_weights(
                len(s['scores']), extra.get('half_life', modulo.HALF_LIFE_GAMES))
            extra['pen_area_delta'] = ops.gk_def_pen_area_granular_delta(
                av['lega'], av['opp_slug'], av['quando'],
                modulo.weighted_mean(s['goalkeeping'], w))
        if _GK_CS_WEIGHT > 0:
            pcs = _pcs_squadra(ctx)
            if pcs is not None:
                extra['team_cs_prob'] = pcs
                extra['team_cs_weight'] = _GK_CS_WEIGHT
        return modulo.compute_score_atteso_gk(
            s['scores'], s['is_home'], s['granulari'], s['pos_dec'], s['neg_dec'],
            target_is_home=casa, presence_rate=presenza, **extra)
    if ruolo == 'Defender':
        if av:
            extra.update({'next_opponent_team_slug': av['opp_slug'],
                          'next_game_date': av['quando'], 'league': av['lega'],
                          'opponent_team_slugs_hist': av['hist_slug'],
                          'game_dates_hist': av['hist_date']})
            if not avversario_lambda:
                extra['opponent_lambda_mult'] = 1.0
            elif sensitivity_by_role is not None:
                import opponent_strength as ops
                extra['opponent_lambda_mult'] = ops.opponent_lambda_multiplier(
                    av['lega'], 'def', av['opp_slug'], av['quando'], sensitivity=_sens('def'))
            if not avversario_stadio_d:
                extra['use_stadio_d'] = False
        return modulo.compute_score_atteso_def(
            s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
            s['pos_dec'], s['neg_dec'], s['goals_conceded'], s['passing'], s['clean_sheet'],
            target_is_home=casa, target_opp_rank=opp_rank, presence_rate=presenza, **extra)
    if ruolo == 'Midfielder':
        if av:
            import opponent_strength as ops
            extra.update({'opponent_lambda_mult': ops.opponent_lambda_multiplier(
                              av['lega'], 'mid', av['opp_slug'], av['quando'], sensitivity=_sens('mid')),
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
        if sensitivity_by_role is not None:
            import opponent_strength as ops
            extra['opponent_lambda_mult'] = ops.opponent_lambda_multiplier(
                av['lega'], 'fwd', av['opp_slug'], av['quando'], sensitivity=_sens('fwd'))
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


def score_atteso(cache, slug, ruolo, fine_giornata, cutoff_giornata=None,
                 favorito_k=None, ranking_k=None, usa_avversario=False,
                 gol_fatti_avv_k=None):
    """Il punteggio atteso di produzione per quella giornata, o None.

    Ritorna un dizionario con previsione, L10 al momento della scelta e la
    partita target (serve per sapere in casa/fuori e per il taglio storico).
    `cutoff_giornata`: vedi contesto().

    `usa_avversario` (13/08/2026): default False = comportamento INVARIATO,
    cioe' come e' sempre stato -- ma va detto chiaro a chi legge, perche' non
    e' ovvio: questa funzione e' quella che alimenta il backtest in ESSENZE
    (p23/p24 sull'archivio ufficiale), quindi finora anche quel metro
    calcolava gli attesi con gli aggiustamenti avversario SPENTI. Per un
    confronto appaiato fra due bracci che condividono la stessa base (G vs A)
    si compensa in gran parte; per misurare una correzione che riguarda
    proprio l'AVVERSARIO no, e va acceso. Il default resta invariato per non
    riscrivere in silenzio i numeri delle misure gia' fatte.

    `gol_fatti_avv_k`: la correzione pre-registrata sul difensore (vedi
    test_def.GOL_FATTI_AVV_K). None = spenta."""
    ctx = contesto(cache, slug, ruolo, fine_giornata, cutoff_giornata)
    if ctx is None:
        return None
    s, casa, cutoff, squadra = ctx['s'], ctx['casa'], ctx['cutoff'], ctx['squadra']
    atteso = calcola(ctx, favorito_k=favorito_k, ranking_k=ranking_k,
                     usa_avversario=usa_avversario,
                     gol_fatti_avv_k=gol_fatti_avv_k)

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
            'squadra': squadra,
            # avversario della partita target: serve alla sinergia/anti-sinergia
            # GK vs movimento in build_formazione_finale.synergy_sort_key
            'opp_slug': ctx.get('opp_slug')}
