"""taratura_confronto_parametri — il MAE non basta a scegliere i parametri.

PERCHE'. Un modello che predice tutti vicino alla mediana ha un MAE ottimo ed
e' inutile: per schierare non serve indovinare il punteggio, serve ORDINARE i
candidati. E' lo stesso motivo per cui nel 2026-07 lo shrinkage e' stato
riconosciuto come "minimizza il MAE ma comprime le differenze". Un half_life
molto corto ha lo stesso rischio: insegue l'ultima partita, il MAE scende, ma
la previsione puo' diventare rumore travestito da segnale.

Quindi ogni combinazione candidata viene giudicata su quattro numeri, non uno:

  MAE          quanto sbaglia il singolo punteggio (piu' basso e' meglio)
  correlazione previsto contro realizzato: se crolla, il modello non ordina
  sd previsto  dispersione delle previsioni: se collassa, il modello dice
               "tutti uguali" e non puo' scegliere nessuno
  lift         quanto del divario fra "scegliere a caso" e "oracolo" viene
               catturato scegliendo i primi cinque della giornata

Uso:  python taratura_confronto_parametri.py --ruoli fwd,mid
      python taratura_confronto_parametri.py --ruoli fwd --candidati 25:0.15,4:0,1.5:0
"""
import argparse
import collections
import datetime
import json
import os
import random
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_halflife_trend import RUOLI, MIN_STORICO, _data, _ruolo_di

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLO_CODICE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}


def _carica_grade():
    """Import lazy (solo con --con-grade): carica l'indice completo del
    voto e il modulo che sa applicarlo con la formula CORRENTE di
    produzione (GRADE_GROUP_STORICA). Riusa senza riscrivere -- stessa
    infrastruttura di analisi_manager/p62_soglie_dopo_gfisso.py e
    p37_halflife_con_grade.py."""
    _root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(_root, 'analisi_manager'))
    import p12_backtest_formazione_grade as S21
    idx_grade, _ = S21.carica_indice_grade()
    return S21, idx_grade


def _metriche(previsioni, reali, giorni):
    """MAE/corr/sd/bias/lift su una lista di previsioni appaiate a reali e
    giorni -- fattorizzato da valuta() cosi' lo stesso metro si applica
    identico alla colonna 'senza voto' e alla colonna 'con voto'."""
    mae = statistics.mean(abs(y - x) for x, y in zip(previsioni, reali))
    mx, my = statistics.mean(previsioni), statistics.mean(reali)
    sx, sy = statistics.pstdev(previsioni), statistics.pstdev(reali)
    corr = (sum((a - mx) * (b - my) for a, b in zip(previsioni, reali))
            / len(previsioni) / (sx * sy)) if sx > 0 and sy > 0 else 0.0
    finte = [(None, None, g, p, r) for g, p, r in zip(giorni, previsioni, reali)]
    lift, n_gg = lift_selezione(finte)
    return {'mae': mae, 'corr': corr, 'sd_prev': sx, 'sd_reale': sy,
            'bias': my - mx, 'lift': lift, 'giornate': n_gg, 'n': len(previsioni)}


def _con_grade(righe, S21mod, idx_grade):
    """righe: [(ruolo, slug, data, ctx, prevv, reale)], GIA' filtrate su
    quelle con voto in finestra -> lista di previsioni combinate con la
    formula CORRENTE di produzione (GRADE_GROUP_STORICA: tabelle storiche +
    GRADE_FATTORE_STORICO + ricentraggio per ruolo, S21.applica_gruppi_grade
    modo='storica_completa'). Stessa infrastruttura di p37_halflife_con_
    grade.py (14/08/2026, risposta al brief BRIEF_OPUS_METRO_CON_GRADE):
    niente qui viene reinventato, si riusa build_formazione_globale via S21.
    Tabella sd_atteso "righello contemporaneo": fresca sul campione di questa
    misura (nessun esito realizzato dentro, verificato -- vedi risposta di
    Opus in HANDOFF_UNIFICATO §10bis)."""
    rows = []
    for ruolo, slug, data, ctx, p, _reale in righe:
        gn = S21mod.grade_in_finestra(idx_grade, slug, data)
        rows.append({'lega': ctx.get('lega_vera') or '?',
                     'codice': RUOLO_CODICE.get(ruolo, ruolo),
                     '_cal': p, '_grade': gn})
    tab_sd = S21mod.costruisci_tabella_sd_atteso(rows)
    S21mod.applica_gruppi_grade(rows, modo='storica_completa',
                                tabella_sd_storica=tab_sd,
                                fattore_storico=S21mod.bfg.GRADE_FATTORE_STORICO)
    per_ruolo = collections.defaultdict(list)
    for r in rows:
        per_ruolo[r['codice']].append(r)
    for _codice, membri in per_ruolo.items():
        diffs = [r['_combinato'] - r['_cal'] for r in membri]
        media = sum(diffs) / len(diffs) if diffs else 0.0
        for r in membri:
            r['_combinato'] -= media
    return [r['_combinato'] for r in rows]


def raccogli(cache, slugs, voluti, limite=None):
    """[(ruolo, slug, data, contesto, realizzato)]"""
    fuori = []
    for i, slug in enumerate(slugs, 1):
        if limite and i > limite:
            break
        ruolo = _ruolo_di(cache, slug)
        if ruolo is None or ruolo not in voluti:
            continue
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale, data = nodo.get('score'), _data(nodo)
            if reale is None or not data:
                continue
            giorno = datetime.datetime.strptime(data, '%Y-%m-%d') + datetime.timedelta(days=1)
            try:
                ctx = prev.contesto(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < MIN_STORICO:
                continue
            fuori.append((ruolo, slug, data, ctx, reale))
        if i % 200 == 0:
            print('  [%d/%d] %d punti' % (i, len(slugs), len(fuori)), flush=True)
    return fuori


def lift_selezione(righe, quanti=5, prove=200, seme=3):
    """Quanto del divario caso->oracolo cattura la scelta dei primi 'quanti'.

    Per ogni giornata con abbastanza candidati: si ordina per previsione, si
    prendono i primi 'quanti', si somma il REALIZZATO. Si confronta con la
    media di scelte casuali (0%) e con la scelta perfetta (100%)."""
    per_data = collections.defaultdict(list)
    for _r, _s, data, prevv, reale in righe:
        per_data[data].append((prevv, reale))
    rnd = random.Random(seme)
    quote = []
    for data, v in per_data.items():
        if len(v) < quanti * 3:
            continue
        scelto = sum(r for _p, r in sorted(v, key=lambda x: -x[0])[:quanti])
        oracolo = sum(sorted((r for _p, r in v), reverse=True)[:quanti])
        caso = statistics.mean(
            sum(r for _p, r in rnd.sample(v, quanti)) for _ in range(prove))
        if oracolo - caso <= 0:
            continue
        quote.append((scelto - caso) / (oracolo - caso))
    return (statistics.mean(quote) * 100 if quote else None), len(quote)


def valuta(punti, hl, ti, favorito_k=None, ranking_k=None, casa_k=None,
           reparto_avv_k=None, gol_fatti_avv_k=None, usa_avversario=False,
           usa_grade=False, idx_grade=None, S21mod=None):
    """`usa_avversario` (13/08/2026, filone intralega): accende gli
    aggiustamenti avversario che girano in PRODUZIONE (opponent_lambda_mult,
    Stadio D) mentre si tara una correzione nuova.

    Default False = comportamento INVARIATO, tutte le misure precedenti
    restano confrontabili. Ma per qualunque correzione che riguardi
    l'AVVERSARIO va acceso, altrimenti si misura il pezzo nuovo fuori dalla
    formula in cui dovrebbe vivere -- e' esattamente l'errore che aveva fatto
    accendere FWD_OFFENSE_SENSITIVITY a 3.0 per poi doverla spegnere a 0.0
    (opponent_strength.py:335-348: "il -0.38% di MAE che lo aveva
    giustificato veniva da un banco che teneva SPENTI gli aggiustamenti
    avversario").

    `usa_grade` (14/08/2026, risposta di Opus al brief BRIEF_OPUS_METRO_CON_
    GRADE, voce 5 di HANDOFF_UNIFICATO §10bis): NON sostituisce il metro,
    AGGIUNGE una colonna 'con_grade' -- confronto appaiato senza/con voto,
    ristretto al sottoinsieme con voto in finestra (~30% delle righe,
    campione non casuale: vale come GATE, non come metro fine). La
    decisione resta sulla colonna SENZA voto (risoluzione piena su tutto il
    campione); una candidata che migliora senza voto ma peggiora col voto va
    scartata (ridondante col voto, non rende in produzione). Richiede
    idx_grade/S21mod gia' caricati dal chiamante (_carica_grade(), una volta
    sola: caricare l'indice a ogni punto di griglia sarebbe lentissimo)."""
    righe = []
    for ruolo, slug, data, ctx, reale in punti:
        try:
            p = prev.calcola(ctx, half_life=hl, trend_intensity=ti,
                             favorito_k=favorito_k, ranking_k=ranking_k,
                             casa_k=casa_k, reparto_avv_k=reparto_avv_k,
                             gol_fatti_avv_k=gol_fatti_avv_k,
                             usa_avversario=usa_avversario)
        except Exception:
            continue
        righe.append((ruolo, slug, data, ctx, p, reale))
    X = [r[4] for r in righe]
    Y = [r[5] for r in righe]
    base = _metriche(X, Y, [r[2] for r in righe])
    if usa_grade:
        graded = [r for r in righe
                  if S21mod.grade_in_finestra(idx_grade, r[1], r[2]) is not None]
        if graded:
            con_prev = _con_grade(graded, S21mod, idx_grade)
            reali_g = [r[5] for r in graded]
            giorni_g = [r[2] for r in graded]
            senza_prev = [r[4] for r in graded]
            base['con_grade'] = {'n': len(graded),
                                 'senza': _metriche(senza_prev, reali_g, giorni_g),
                                 'con': _metriche(con_prev, reali_g, giorni_g)}
    return base


CORREZIONI = {
    'favorito': ('CONTESTO PARTITA (k punti per gol di differenziale atteso)',
                 'favorito_k'),
    # stessa forma, variabile diversa: il ranking grezzo dell'avversario come
    # scarto dalla media di quelli gia' affrontati. Sul pool grande batte il
    # differenziale di gol attesi (corr +0.074 contro +0.057) e in regressione
    # congiunta lo assorbe del tutto -- vedi docs/handoff del 04/08.
    'ranking': ('CONTESTO PARTITA (k punti per posizione di classifica)',
                'ranking_k'),
    # secondo termine casa/trasferta SOPRA lo split che il modello applica
    # gia': serve a misurare quanto e' rimasto fuori da quello split, non a
    # essere applicato cosi'. Vedi delta_casa in backtest_arene_previsioni.
    'casa': ('CASA/TRASFERTA residuo (k punti per quota di partite in casa)',
             'casa_k'),
    # FILONE INTRALEGA (13/08/2026). Due termometri per la forza del reparto
    # avversario, confrontati sullo stesso metro. Da tarare SEMPRE con
    # --con-avversario, vedi la docstring di valuta().
    # Segno atteso NEGATIVO in entrambi: piu' forte l'avversario, meno rende.
    'reparto_avv': ('REPARTO AVVERSARIO in voti Sorare (k punti per deviazione '
                    'standard) -- FWD contro i difensori, DEF contro gli attaccanti',
                    'reparto_avv_k'),
    'gol_fatti_avv': ('GOL FATTI dall\'avversario (k punti per deviazione '
                      'standard) -- grandezza che oggi il DEF non guarda',
                      'gol_fatti_avv_k'),
}


def griglia_favorito(breve, punti, prod, spec, quale='favorito', fissi=None,
                     usa_avversario=False, usa_grade=False, idx_grade=None,
                     S21mod=None):
    """La correzione di contesto partita, giudicata sullo stesso metro.

    Tiene half_life/trend di produzione e muove solo k: cosi' l'unica cosa che
    cambia fra le righe e' la correzione, e il confronto e' pulito. La riga
    k=0 e' il modello di oggi.

    `quale` sceglie la variabile su cui e' costruita la correzione
    (vedi CORREZIONI): la griglia, il campione e il metro restano gli stessi,
    cosi' le varianti si confrontano ad armi pari.

    `fissi` tiene accese altre correzioni mentre la griglia muove questa: e' il
    modo di chiedere "quanto aggiunge la seconda ALLA prima", non "quanto vale
    da sola".

    `usa_grade` (14/08/2026, vedi valuta()): stampa in coda la colonna
    'con voto' come GATE -- non cambia il verdetto PASSA/no (che resta sulla
    colonna senza voto, piena risoluzione), segnala solo se una candidata che
    passa senza voto peggiora quando il voto e' acceso: e' il caso in cui la
    correzione e' ridondante col voto e in produzione non rendera'."""
    titolo, chiave = CORREZIONI[quale]
    fissi = dict(fissi or {})
    ks = [float(x) for x in spec.split(',') if x.strip()]
    if 0.0 not in ks:
        ks.insert(0, 0.0)
    hl, ti = prod
    print('=' * 96)
    print('%s -- %d punti | %s' % (breve.upper(), len(punti), titolo))
    if fissi:
        print('sopra: ' + ', '.join('%s=%g' % kv for kv in sorted(fissi.items())))
    print('half_life=%s trend=%s tenuti a produzione' % (hl, ti))
    print('aggiustamenti avversario di produzione: %s' %
          ('ACCESI' if usa_avversario else 'spenti (default storico)'))
    print('=' * 96)
    print('%-16s %8s %8s %9s %8s %8s %7s' %
          ('k', 'MAE', 'corr', 'sd prev', 'sd real', 'bias', 'lift%'))
    risultati = []
    for k in ks:
        r = valuta(punti, hl, ti, usa_avversario=usa_avversario,
                   usa_grade=usa_grade, idx_grade=idx_grade, S21mod=S21mod,
                   **dict(fissi, **{chiave: k}))
        r['favorito_k'] = k
        r['correzione'] = quale
        if fissi:
            r['fissi'] = fissi
        r['produzione'] = (k == 0.0)
        risultati.append(r)
        print('%-16s %8.3f %8.3f %9.2f %8.2f %+8.2f %7s%s' %
              ('%g' % k, r['mae'], r['corr'], r['sd_prev'], r['sd_reale'], r['bias'],
               ('%.1f' % r['lift']) if r['lift'] is not None else '--',
               '   <- oggi (spento)' if r['produzione'] else ''))
    base = risultati[0]
    print('\nregola CLAUDE.md: si applica solo se MAE, correlazione e lift migliorano INSIEME')
    for r in risultati[1:]:
        segni = (r['mae'] < base['mae'], r['corr'] > base['corr'],
                 (r['lift'] or 0) > (base['lift'] or 0))
        esito = 'PASSA' if all(segni) else 'no'
        gate = ''
        if esito == 'PASSA' and usa_grade and 'con_grade' in r and 'con_grade' in base:
            cg, cg0 = r['con_grade']['con'], base['con_grade']['con']
            peggiora = cg['lift'] is not None and cg0['lift'] is not None \
                and cg['lift'] < cg0['lift']
            gate = '   [GATE col voto: %s, lift %+.1f]' % (
                'BOCCIA -- ridondante col voto' if peggiora else 'ok', cg['lift'] - cg0['lift'])
        print('  k=%-6g MAE %+6.3f  corr %+6.4f  lift %+5.1f   %s%s' %
              (r['favorito_k'], r['mae'] - base['mae'], r['corr'] - base['corr'],
               (r['lift'] or 0) - (base['lift'] or 0), esito, gate))
    if usa_grade:
        print('\ncolonna col voto (GATE, campione ~30% non casuale) -- senza voto vs con voto, stesso k:')
        print('%-16s | %7s %7s %7s | %7s %7s %7s' %
              ('k', 'MAE', 'corr', 'lift%', 'MAE', 'corr', 'lift%'))
        for r in risultati:
            if 'con_grade' not in r:
                continue
            s, c = r['con_grade']['senza'], r['con_grade']['con']
            print('%-16s | %7.3f %7.3f %7s | %7.3f %7.3f %7s' %
                  ('%g' % r['favorito_k'], s['mae'], s['corr'],
                   ('%.1f' % s['lift']) if s['lift'] is not None else '--',
                   c['mae'], c['corr'],
                   ('%.1f' % c['lift']) if c['lift'] is not None else '--'))
    print()
    return risultati


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='fwd,mid')
    ap.add_argument('--candidati', default='')
    ap.add_argument('--favorito', default='',
                    help='griglia di k per la correzione di contesto partita, '
                         'es. 0,1,2,4 (punti per gol di differenziale atteso). '
                         'Tiene half_life/trend di produzione e muove solo k.')
    ap.add_argument('--ranking', default='',
                    help='come --favorito ma sul ranking grezzo dell avversario '
                         '(punti per posizione di classifica), es. 0,0.1,0.2,0.5')
    ap.add_argument('--casa', default='',
                    help='griglia di k per un secondo termine casa/trasferta SOPRA '
                         'lo split gia applicato dal modello: misura quanto lo split '
                         'esistente lascia fuori')
    ap.add_argument('--con-ranking', default='', dest='con_ranking',
                    help='tiene acceso il ranking mentre la griglia --casa si muove, '
                         'per ruolo: es. fwd:0.3,mid:0.05,def:0.3,gk:0.5')
    ap.add_argument('--reparto-avv', default='', dest='reparto_avv',
                    help='griglia di k per la forza del reparto AVVERSARIO in '
                         'voti Sorare (filone intralega). Segno atteso negativo, '
                         'es. -3,-2,-1,1. Usare INSIEME a --con-avversario.')
    ap.add_argument('--gol-fatti-avv', default='', dest='gol_fatti_avv',
                    help='griglia di k per i gol FATTI dall avversario, es. '
                         '-3,-2,-1,1. Usare INSIEME a --con-avversario.')
    ap.add_argument('--con-avversario', action='store_true', dest='con_avversario',
                    help='accende gli aggiustamenti avversario di PRODUZIONE '
                         '(opponent_lambda_mult, Stadio D) durante la griglia. '
                         'OBBLIGATORIO per tarare qualunque correzione che '
                         'riguardi l avversario: senza, si misura il pezzo nuovo '
                         'fuori dalla formula in cui deve vivere (e come si '
                         'accese per sbaglio FWD_OFFENSE_SENSITIVITY).')
    ap.add_argument('--con-grade', action='store_true', dest='con_grade',
                    help='aggiunge la colonna GATE col voto (14/08/2026, '
                         'risposta di Opus al brief BRIEF_OPUS_METRO_CON_GRADE, '
                         'HANDOFF_UNIFICATO §10bis voce 5): non sostituisce il '
                         'metro, segnala solo le candidate che passano senza '
                         'voto ma peggiorano col voto (ridondanti, non rendono '
                         'in produzione). Costoso (carica l indice grade '
                         'completo): usare solo quando serve.')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/taratura_confronto_parametri.json')
    args = ap.parse_args()

    S21mod, idx_grade = (_carica_grade() if args.con_grade else (None, None))
    if args.con_grade:
        n_coppie = sum(len(v) for v in idx_grade.values())
        print('--con-grade: %d coppie (slug, giorno) nell indice voto\n' % n_coppie)

    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    voluti = {RUOLI[b] for b in brevi}
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache, ruoli: %s' % (len(slugs), ', '.join(brevi)))
    punti = raccogli(cache, slugs, voluti, args.max or None)
    print('%d punti di test\n' % len(punti))

    esiti = {}
    for b in brevi:
        sotto = [p for p in punti if p[0] == RUOLI[b]]
        if not sotto:
            continue
        modulo = sotto[0][3]['modulo']
        prod = (modulo.HALF_LIFE_GAMES, getattr(modulo, 'TREND_INTENSITY', 0.0))
        if args.favorito or args.ranking or args.casa or args.reparto_avv \
                or args.gol_fatti_avv:
            esiti[b] = []
            av = args.con_avversario
            g = dict(usa_grade=args.con_grade, idx_grade=idx_grade, S21mod=S21mod)
            if args.ranking:
                esiti[b] += griglia_favorito(b, sotto, prod, args.ranking, 'ranking',
                                             usa_avversario=av, **g)
            if args.favorito:
                esiti[b] += griglia_favorito(b, sotto, prod, args.favorito, 'favorito',
                                             usa_avversario=av, **g)
            if args.reparto_avv:
                esiti[b] += griglia_favorito(b, sotto, prod, args.reparto_avv,
                                             'reparto_avv', usa_avversario=av, **g)
            if args.gol_fatti_avv:
                esiti[b] += griglia_favorito(b, sotto, prod, args.gol_fatti_avv,
                                             'gol_fatti_avv', usa_avversario=av, **g)
            if args.casa:
                fissi = {}
                for pezzo in args.con_ranking.split(','):
                    if ':' in pezzo and pezzo.split(':')[0].strip() == b:
                        fissi['ranking_k'] = float(pezzo.split(':')[1])
                esiti[b] += griglia_favorito(b, sotto, prod, args.casa, 'casa', fissi,
                                             usa_avversario=av, **g)
            continue
        if args.candidati:
            cand = [tuple(float(x) for x in c.split(':')) for c in args.candidati.split(',')]
        else:
            cand = [prod, (12.0, 0.0), (6.0, 0.0), (4.0, 0.0), (2.0, 0.0), (1.5, 0.0)]
        if prod not in cand:
            cand.insert(0, prod)
        print('=' * 96)
        print('%s -- %d punti | produzione half_life=%s trend=%s' % (b.upper(), len(sotto), prod[0], prod[1]))
        print('=' * 96)
        print('%-16s %8s %8s %9s %8s %8s %7s' %
              ('half_life/trend', 'MAE', 'corr', 'sd prev', 'sd real', 'bias', 'lift%'))
        risultati = []
        for hl, ti in cand:
            # usa_avversario anche qui (13/08/2026): senza, il ramo
            # --candidati girava SEMPRE con gli aggiustamenti avversario
            # spenti, quindi `av` era None e alle funzioni di produzione non
            # arrivava nemmeno l'avversario. Un A/A su un flag che dipende
            # dall'avversario risultava percio' "identico" -- non perche' il
            # flag fosse inerte, ma perche' il banco non gli passava il dato.
            r = valuta(sotto, hl, ti, usa_avversario=args.con_avversario,
                      usa_grade=args.con_grade, idx_grade=idx_grade, S21mod=S21mod)
            r['half_life'], r['trend_intensity'] = hl, ti
            r['produzione'] = (hl, ti) == prod
            risultati.append(r)
            print('%-16s %8.3f %8.3f %9.2f %8.2f %+8.2f %7s%s' %
                  ('%s / %s' % (hl, ti), r['mae'], r['corr'], r['sd_prev'], r['sd_reale'],
                   r['bias'], ('%.1f' % r['lift']) if r['lift'] is not None else '--',
                   '   <- produzione' if r['produzione'] else ''))
        if args.con_grade:
            print('\ncolonna col voto (GATE, campione ~30% non casuale) -- '
                  'senza voto vs con voto, stesso half_life/trend:')
            print('%-16s | %7s %7s %7s | %7s %7s %7s' %
                  ('half_life/trend', 'MAE', 'corr', 'lift%', 'MAE', 'corr', 'lift%'))
            for r in risultati:
                if 'con_grade' not in r:
                    continue
                s, c = r['con_grade']['senza'], r['con_grade']['con']
                print('%-16s | %7.3f %7.3f %7s | %7.3f %7.3f %7s' %
                      ('%s / %s' % (r['half_life'], r['trend_intensity']),
                       s['mae'], s['corr'], ('%.1f' % s['lift']) if s['lift'] is not None else '--',
                       c['mae'], c['corr'], ('%.1f' % c['lift']) if c['lift'] is not None else '--'))
        esiti[b] = risultati
        print()

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print('salvato in %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
