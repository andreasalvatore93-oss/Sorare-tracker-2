# -*- coding: utf-8 -*-
"""Chi viene da una striscia d'oro: lo stiamo sovrastimando? (14/08/2026)

DA DOVE NASCE. Misurando il correttivo di lega (HANDOFF_UNIFICATO
Â§8terdecies) e' saltato fuori che chi cambia campionato passa in media da 64
a 52 punti, ma ~7 di quei 12 li perde ANCHE chi non si e' mosso: e' il
trattamento di chiunque arrivi da un periodo eccezionale, non un problema di
campionati. Quel ~7 pero' e' un numero GREZZO (media prima meta' contro
seconda meta' dello storico), non un errore del modello: il modello ha gia'
mezzi per assorbirlo (media pesata esponenziale con half-life corto +
shrinkage SHRINK_K_OUTLIER verso il prior di ruolo). La domanda vera, e
questo script risponde solo a questa, e':

  il RESIDUO (reale - previsto) e' sistematicamente negativo per chi arriva
  da una striscia sopra la propria media?

Se la risposta e' no, il filone si chiude qui: il modello regredisce gia'
abbastanza. Se e' si', si sapra' anche DOVE (quale fascia di striscia, quale
ruolo, quanto storico) prima di scegliere una cura.

COME. Nessuna query di rete: stesso banco ufficiale della taratura
(`taratura_confronto_parametri.raccogli` sulla cache game-log condivisa) e
stessa previsione di produzione (`prev.calcola`, con --con-avversario per
stare dentro la formula vera).

  striscia = media pesata esponenziale (le stesse funzioni del modulo di
             ruolo, half-life di produzione) - media semplice della finestra

Positiva = il giocatore viene da partite recenti sopra la sua media di
periodo. La finestra e' quella di produzione (max 30 partite / 365 giorni),
quindi "media di periodo" vuol dire "dell'ultimo anno", non "di carriera".

NIENTE LEAKAGE: la striscia si calcola solo sulle partite PRIMA del cutoff
(le stesse che il modello usa per prevedere), il residuo sulla partita dopo.
Non c'e' il rimbalzo automatico della regressione verso la media misurata
sullo stesso campione: qui il test e' fuori campione per costruzione.

Incertezza: bootstrap sui GIOCATORI (non sulle righe), 200 ricampionamenti,
intervallo al 90%. Righe dello stesso giocatore non sono indipendenti.

Uso:  python taratura_striscia_oro.py --ruoli fwd,mid,def,gk --con-avversario
      python taratura_striscia_oro.py --ruoli fwd --max 300   (prova rapida)
"""
import argparse
import collections
import json
import os
import random
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_halflife_trend import RUOLI
from taratura_confronto_parametri import (raccogli, RUOLO_CODICE, _metriche,
                                          _carica_grade, _con_grade)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'analisi_manager'))
import p36_lift_rumore as P36

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# DUE letture di "striscia d'oro", misurate tutte e due perche' sono domande
# diverse e il §8terdecies ne cita solo la prima:
#  LIVELLO  = quanto vale il periodo recente in assoluto (media pesata). E' il
#             bucket del "chi sta sopra 60 cala di 6,83": regressione verso la
#             media della POPOLAZIONE.
#  STRISCIA = quanto il periodo recente sta sopra la media dell'anno DELLO
#             STESSO giocatore: regressione verso SE STESSO.
TAGLI_LIV = [35.0, 45.0, 55.0, 65.0, 75.0]
ETICHETTE_LIV = ['< 35', '35..45', '45..55', '55..65', '65..75', '> 75']

TAGLI = [-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0]
ETICHETTE = ['< -6', '-6..-4', '-4..-2', '-2..0', '0..+2', '+2..+4', '+4..+6', '> +6']

FASCE_N = [(3, 9, 'corto 3-9'), (10, 19, 'medio 10-19'), (20, 99, 'lungo 20+')]


def _bucket(x, tagli):
    for i, t in enumerate(tagli):
        if x < t:
            return i
    return len(tagli)


def _boot_media(righe, prove=200, seme=7):
    """righe: [(slug, valore)] -> (media, ic_basso, ic_alto) ricampionando i
    GIOCATORI con reimmissione. Serve perche' un giocatore con 40 partite in
    cache pesa 40 righe che si somigliano fra loro: contarle come 40
    osservazioni indipendenti stringerebbe l'intervallo a torto."""
    per_slug = collections.defaultdict(list)
    for slug, v in righe:
        per_slug[slug].append(v)
    slugs = list(per_slug)
    if not slugs:
        return None, None, None
    vero = statistics.mean(v for vs in per_slug.values() for v in vs)
    rnd = random.Random(seme)
    medie = []
    for _ in range(prove):
        camp = [per_slug[rnd.choice(slugs)] for _ in slugs]
        piatto = [v for vs in camp for v in vs]
        if piatto:
            medie.append(statistics.mean(piatto))
    medie.sort()
    if not medie:
        return vero, None, None
    lo = medie[int(0.05 * len(medie))]
    hi = medie[min(len(medie) - 1, int(0.95 * len(medie)))]
    return vero, lo, hi


def _corr(xs, ys):
    if len(xs) < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs) / (sx * sy)


def misura(punti, usa_avversario):
    """[(codice_ruolo, slug, data, striscia, previsto, reale, n_storico, livello)]"""
    fuori = []
    errori = collections.Counter()
    for ruolo, slug, data, ctx, reale in punti:
        try:
            p = prev.calcola(ctx, usa_avversario=usa_avversario)
        except Exception as exc:
            errori[type(exc).__name__] += 1
            continue
        modulo, scores = ctx['modulo'], ctx['s']['scores']
        n = len(scores)
        if n < 3:
            continue
        w = modulo.exponential_weights(n, modulo.HALF_LIFE_GAMES)
        recente = modulo.weighted_mean(scores, w)
        lungo = statistics.mean(scores)
        fuori.append((RUOLO_CODICE.get(ruolo, ruolo), slug, data,
                      recente - lungo, p, reale, n, recente))
    if errori:
        # mai far sparire righe in silenzio (e' il bug GK del 13/08)
        print('  righe saltate da prev.calcola: %s' % dict(errori))
    return fuori


def tabella(righe, titolo, modo='livello'):
    """modo='livello' -> bucket sulla media pesata (regressione verso la
    popolazione). modo='striscia' -> bucket su recente-meno-propria-media.

    La colonna 'residuo centrato' toglie il residuo medio di TUTTO il
    campione: serve a distinguere uno sbilanciamento generale del modello
    (che non c'entra con la striscia e si vedrebbe uguale in ogni riga) da
    una PENDENZA vera fra le fasce, che e' l'unica cosa che questo filone
    sta cercando."""
    idx = 7 if modo == 'livello' else 3
    tagli = TAGLI_LIV if modo == 'livello' else TAGLI
    etich = ETICHETTE_LIV if modo == 'livello' else ETICHETTE
    residuo_tutti = statistics.mean(r[5] - r[4] for r in righe) if righe else 0.0
    print('\n' + '=' * 104)
    print('[%s] %s  (n=%d righe, %d giocatori, residuo medio del campione %+.2f)'
          % (modo.upper(), titolo, len(righe), len({r[1] for r in righe}), residuo_tutti))
    print('=' * 104)
    print('%-9s %7s %9s %9s %9s %9s %9s  %-22s' %
          (modo[:9], 'n', modo[:6], 'previsto', 'reale', 'residuo', 'centrato',
           'IC 90% del residuo'))
    per_b = collections.defaultdict(list)
    for r in righe:
        per_b[_bucket(r[idx], tagli)].append(r)
    esito = []
    for i, et in enumerate(etich):
        v = per_b.get(i, [])
        if not v:
            continue
        res = [(r[1], r[5] - r[4]) for r in v]
        media, lo, hi = _boot_media(res)
        riga = {'bucket': et, 'n': len(v), 'giocatori': len({r[1] for r in v}),
                'x_media': statistics.mean(r[idx] for r in v),
                'previsto': statistics.mean(r[4] for r in v),
                'reale': statistics.mean(r[5] for r in v),
                'residuo': media, 'residuo_centrato': media - residuo_tutti,
                'ic_basso': lo, 'ic_alto': hi}
        esito.append(riga)
        print('%-9s %7d %+9.2f %9.2f %9.2f %+9.2f %+9.2f  [%+.2f ; %+.2f]' %
              (et, riga['n'], riga['x_media'], riga['previsto'], riga['reale'],
               riga['residuo'], riga['residuo_centrato'], lo, hi))
    c = _corr([r[idx] for r in righe], [r[5] - r[4] for r in righe])
    print('correlazione %s/residuo: %+.4f' % (modo, c))
    return {'modo': modo, 'righe': esito, 'corr': c, 'residuo_medio': residuo_tutti,
            'n': len(righe), 'giocatori': len({r[1] for r in righe})}


def griglia_shrink(punti, valori, usa_avversario, grade=None):
    """La cura candidata, giudicata sul metro ufficiale (MAE + correlazione +
    lift INSIEME, mai il MAE da solo: comprimere verso la media abbassa il MAE
    e puo' distruggere l'ordinamento -- e' scritto nella docstring di
    taratura_confronto_parametri e vale esattamente qui).

    In piu' del metro: 'pendenza', cioe' il residuo centrato della fascia di
    livello 65-75 meno quello della fascia 35-45. E' il difetto che si sta
    provando a curare: se la cura funziona deve andare verso zero. Se il MAE
    migliora ma la pendenza resta, si sta solo schiacciando tutto."""
    print('\n%-8s %8s %8s %9s %8s %7s %10s' %
          ('shrink_k', 'MAE', 'corr', 'sd prev', 'bias', 'lift%', 'pendenza'))
    esito = []
    for k in valori:
        grezze = []
        for ruolo, slug, data, ctx, reale in punti:
            try:
                p = prev.calcola(ctx, shrink_k=k, usa_avversario=usa_avversario)
            except Exception:
                continue
            modulo, scores = ctx['modulo'], ctx['s']['scores']
            n = len(scores)
            if n < 3:
                continue
            w = modulo.exponential_weights(n, modulo.HALF_LIFE_GAMES)
            grezze.append((ruolo, slug, data, ctx, p, reale, n,
                           modulo.weighted_mean(scores, w)))
        if grade:
            # si giudica sull'atteso COMBINATO col voto, cioe' il numero che
            # entra nel knapsack in produzione. Senza questo si tara un pezzo
            # fuori dalla formula in cui vive -- stesso errore per cui il banco
            # ha --con-avversario.
            S21mod, idx_grade = grade
            grezze = [g for g in grezze
                      if S21mod.grade_in_finestra(idx_grade, g[1], g[2]) is not None]
            comb = _con_grade([(g[0], g[1], g[2], g[3], g[4], g[5]) for g in grezze],
                              S21mod, idx_grade)
            grezze = [(g[0], g[1], g[2], g[3], c, g[5], g[6], g[7])
                      for g, c in zip(grezze, comb)]
        righe = [(RUOLO_CODICE.get(g[0], g[0]), g[1], g[2], 0.0, g[4], g[5],
                  g[6], g[7]) for g in grezze]
        m = _metriche([r[4] for r in righe], [r[5] for r in righe],
                      [r[2] for r in righe])
        res_tutti = statistics.mean(r[5] - r[4] for r in righe)
        per_b = collections.defaultdict(list)
        for r in righe:
            per_b[_bucket(r[7], TAGLI_LIV)].append(r[5] - r[4])
        alto = per_b.get(4) or []          # 65..75
        basso = per_b.get(1) or []         # 35..45
        pend = ((statistics.mean(alto) - res_tutti) -
                (statistics.mean(basso) - res_tutti)) if alto and basso else None
        esito.append({'shrink_k': k, 'n': len(righe), **m, 'pendenza': pend})
        print('%-8s %8.3f %8.3f %9.2f %+8.2f %7s %10s' %
              (k, m['mae'], m['corr'], m['sd_prev'], m['bias'],
               ('%.1f' % m['lift']) if m['lift'] is not None else '--',
               ('%+.2f' % pend) if pend is not None else '--'))
    return esito


def prevedi_appaiato(punti, k_a, k_b, usa_avversario, grade=None):
    """Le due previsioni sulla stessa riga nello stesso run: tutto il resto e'
    identico per costruzione. Separata dal giudizio perche' il taglio nel
    tempo deve riusare le STESSE previsioni, non ricalcolarle.

    `grade` = (S21mod, idx_grade) accende la colonna COL VOTO: al posto
    dell'atteso calibrato si giudica `atteso + GRADE_FATTORE_STORICO *
    sd_atteso * z`, cioe' il numero che in produzione entra davvero nel
    knapsack (GRADE_ENABLED e GRADE_GROUP_STORICA_ENABLED sono entrambi '1'
    di default in build_formazione_globale). Serve perche' due terzi del
    valore del voto sono "questo giocatore e' forte" (p67/p68): e' la STESSA
    dimensione su cui si misura qui il difetto, quindi il voto potrebbe gia'
    correggerlo -- o peggiorarlo. Il campione si restringe alle righe con voto
    in finestra (~30%, non casuale): vale come GATE, non come metro fine."""
    righe = []
    for ruolo, slug, data, ctx, reale in punti:
        try:
            pa = prev.calcola(ctx, shrink_k=k_a, usa_avversario=usa_avversario)
            pb = prev.calcola(ctx, shrink_k=k_b, usa_avversario=usa_avversario)
        except Exception:
            continue
        righe.append((ruolo, slug, data, ctx, pa, pb, reale))
    if not grade:
        return [(r[1], r[2], r[4], r[5], r[6]) for r in righe]

    S21mod, idx_grade = grade
    con_voto = [r for r in righe
                if S21mod.grade_in_finestra(idx_grade, r[1], r[2]) is not None]
    print('  col voto: %d righe su %d hanno il voto in finestra (%.1f%%)'
          % (len(con_voto), len(righe), 100.0 * len(con_voto) / max(1, len(righe))))
    if not con_voto:
        return []
    # una passata per colonna: la tabella sd_atteso si ricostruisce sul
    # proprio atteso, com'e' giusto (in produzione con quel modello sarebbe
    # quella)
    comb_a = _con_grade([(r[0], r[1], r[2], r[3], r[4], r[6]) for r in con_voto],
                        S21mod, idx_grade)
    comb_b = _con_grade([(r[0], r[1], r[2], r[3], r[5], r[6]) for r in con_voto],
                        S21mod, idx_grade)
    return [(r[1], r[2], ca, cb, r[6])
            for r, ca, cb in zip(con_voto, comb_a, comb_b)]


def confronto_appaiato(dati, k_a, k_b, prove=300, seme=11):
    """A contro B sulle STESSE righe, con l'incertezza del DELTA.

    Serve perche' la griglia da sola non basta a decidere: fra k=5 e k=10 il
    lift si muove di mezzo punto ma NON in modo monotono lungo la griglia
    (24.8 / 24.3 / 24.2 / 25.0 / 24.3 / 23.1), e un movimento non monotono e'
    il ritratto del rumore. Qui si misura quanto e' grande il tremolio:
      - MAE e correlazione: bootstrap sui GIOCATORI (righe dello stesso
        giocatore non sono indipendenti);
      - lift: bootstrap sulle GIORNATE, che sono l'unita' su cui il lift e'
        definito (si sceglie cinque carte per giornata).
    Le due previsioni sono calcolate sulla stessa riga nello stesso run:
    tutto il resto e' identico per costruzione."""
    print('\n%d righe appaiate, %d giocatori, %d giornate'
          % (len(dati), len({d[0] for d in dati}), len({d[1] for d in dati})))

    def _mae_corr(v):
        a = statistics.mean(abs(r - p) for _s, _d, p, _q, r in v)
        b = statistics.mean(abs(r - q) for _s, _d, _p, q, r in v)
        ca = _corr([p for _s, _d, p, _q, _r in v], [r for _s, _d, _p, _q, r in v])
        cb = _corr([q for _s, _d, _p, q, _r in v], [r for _s, _d, _p, _q, r in v])
        return b - a, cb - ca          # delta B meno A

    def _lift_per_giorno(v):
        """Il delta di lift giorno per giorno, con il 'caso' in forma ESATTA.

        Riusa `p36_lift_rumore.quote_per_giorno` (13/08, commit 6c9704e112):
        dei tre pezzi del lift solo 'scelto' dipende dalla previsione, quindi
        i due bracci condividono caso e oracolo e si confrontano sulle stesse
        giornate. Stimare il 'caso' con 200 sorteggi quando lo si sa in forma
        chiusa aggiunge solo rumore -- ed e' su quel rumore che il 13/08 stava
        per chiudersi un filone buono."""
        a = P36.quote_per_giorno([(None, None, d, p, r) for _s, d, p, _q, r in v])
        b = P36.quote_per_giorno([(None, None, d, q, r) for _s, d, _p, q, r in v])
        fuori = {}
        for data in set(a) & set(b):
            scelto_a, caso, oracolo = a[data]
            scelto_b = b[data][0]
            fuori[data] = (scelto_b - scelto_a) / (oracolo - caso) * 100
        return fuori

    d_mae, d_corr = _mae_corr(dati)
    per_giorno = _lift_per_giorno(dati)
    d_lift = statistics.mean(per_giorno.values()) if per_giorno else None
    # il lift si bootstrappa sulle GIORNATE, 2000 giri come p36 (costa poco:
    # si ricampionano numeri gia' calcolati, non previsioni)
    rnd_l = random.Random(seme)
    giornate = list(per_giorno)
    b_lift = [statistics.mean([per_giorno[rnd_l.choice(giornate)]
                               for _ in giornate]) for _ in range(2000)]
    per_slug = collections.defaultdict(list)
    for r in dati:
        per_slug[r[0]].append(r)
    rnd = random.Random(seme)
    b_mae, b_corr = [], []
    slugs = list(per_slug)
    for _ in range(prove):
        camp = [x for _ in slugs for x in per_slug[rnd.choice(slugs)]]
        m, c = _mae_corr(camp)
        b_mae.append(m)
        b_corr.append(c)
    print('  lift: %d giornate utili (almeno 15 candidati)' % len(giornate))

    def _ic(v):
        if not v:
            return None, None
        v = sorted(v)
        return v[int(0.05 * len(v))], v[min(len(v) - 1, int(0.95 * len(v)))]

    print('\nDELTA di shrink_k=%s contro shrink_k=%s (negativo = meglio su MAE,'
          ' positivo = meglio su corr e lift)' % (k_b, k_a))
    for et, val, boot, verso in (('MAE', d_mae, b_mae, 'giu'),
                                 ('corr', d_corr, b_corr, 'su'),
                                 ('lift%', d_lift, b_lift, 'su')):
        lo, hi = _ic(boot)
        quota = (sum(1 for x in boot if (x < 0 if verso == 'giu' else x > 0))
                 / len(boot) * 100) if boot else 0.0
        print('  %-6s %+8.4f   IC 90%% [%+.4f ; %+.4f]   va nel verso giusto nel %.1f%% dei ricampionamenti'
              % (et, val if val is not None else 0.0, lo or 0.0, hi or 0.0, quota))
    return {'k_a': k_a, 'k_b': k_b, 'n': len(dati),
            'delta_mae': d_mae, 'delta_corr': d_corr, 'delta_lift': d_lift,
            'ic_mae': _ic(b_mae), 'ic_corr': _ic(b_corr), 'ic_lift': _ic(b_lift)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='fwd,mid,def,gk')
    ap.add_argument('--con-grade', action='store_true', dest='con_grade',
                    help='giudica sull atteso COMBINATO col voto A-F, cioe il '
                         'numero che entra davvero nel knapsack in produzione. '
                         'Costoso (carica l indice voto completo) e ristretto '
                         'alle righe con voto in finestra (~30%%).')
    ap.add_argument('--per-periodo', action='store_true', dest='per_periodo',
                    help='ripete il confronto sulle due meta di calendario: '
                         'il verso del delta deve essere lo stesso in tutte e due')
    ap.add_argument('--confronto', default='',
                    help='due valori di shrink_k appaiati con incertezza sul '
                         'delta, es. 5,10 (il primo e la produzione)')
    ap.add_argument('--shrink', default='',
                    help='griglia di shrink_k, es. 5,10,20,40 (5 = produzione '
                         'su GK/MID/FWD, 0 su DEF). Salta la diagnosi e misura '
                         'solo la cura.')
    ap.add_argument('--max', type=int, default=0, help='limite di giocatori (prova rapida)')
    ap.add_argument('--con-avversario', action='store_true', dest='con_avversario',
                    help='accende gli aggiustamenti avversario di PRODUZIONE '
                         '(opponent_lambda_mult, Stadio D): la formula vera')
    ap.add_argument('--json', default='dati_globali/taratura_striscia_oro.json')
    args = ap.parse_args()

    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    voluti = {RUOLI[b] for b in brevi}
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache, ruoli: %s' % (len(slugs), ', '.join(brevi)))
    punti = raccogli(cache, slugs, voluti, args.max or None)
    print('%d punti di test' % len(punti))

    if args.confronto:
        k_a, k_b = [float(v) for v in args.confronto.split(',')]
        grade = _carica_grade() if args.con_grade else None
        esiti = {}
        for b in brevi:
            sotto = [p for p in punti if p[0] == RUOLI[b]]
            if not sotto:
                continue
            print('\n' + '=' * 104)
            print('CONFRONTO APPAIATO shrink_k -- RUOLO %s (%d punti)' % (b.upper(), len(sotto)))
            print('=' * 104)
            dati = prevedi_appaiato(sotto, k_a, k_b, args.con_avversario, grade)
            esiti[b] = confronto_appaiato(dati, k_a, k_b)
            if args.per_periodo:
                # FUORI CAMPIONE NEL TEMPO. Non c'e' niente da "ristimare"
                # (shrink_k e' scelto, non fittato), quindi la domanda giusta
                # non e' "regge su dati mai visti" ma "il verso del delta e' lo
                # stesso in due periodi diversi?". Se cambia segno fra prima e
                # seconda meta', il guadagno globale e' un accidente di
                # calendario, non una proprieta' del modello.
                date = sorted(d[1] for d in dati)
                mediana = date[len(date) // 2]
                for et, sel in (('PRIMA di %s' % mediana, lambda d: d[1] < mediana),
                                ('DAL %s in poi' % mediana, lambda d: d[1] >= mediana)):
                    parte = [d for d in dati if sel(d)]
                    print('\n--- %s ---' % et)
                    esiti['%s_%s' % (b, et[:5].strip())] = confronto_appaiato(
                        parte, k_a, k_b)
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(esiti, fh, ensure_ascii=False, indent=2)
        print('\nsalvato in %s' % args.json)
        return 0

    if args.shrink:
        valori = [float(v) for v in args.shrink.split(',')]
        grade = _carica_grade() if args.con_grade else None
        esiti = {}
        for b in brevi:
            sotto = [p for p in punti if p[0] == RUOLI[b]]
            if not sotto:
                continue
            print('\n' + '=' * 104)
            print('GRIGLIA shrink_k -- RUOLO %s (%d punti)%s'
                  % (b.upper(), len(sotto), ' COL VOTO' if grade else ''))
            print('=' * 104)
            esiti[b] = griglia_shrink(sotto, valori, args.con_avversario, grade)
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(esiti, fh, ensure_ascii=False, indent=2)
        print('\nsalvato in %s' % args.json)
        return 0

    righe = misura(punti, args.con_avversario)
    print('%d righe con previsione' % len(righe))

    esiti = {}
    for modo in ('livello', 'striscia'):
        esiti['tutti_' + modo] = tabella(righe, 'TUTTI I RUOLI INSIEME', modo)
    for b in brevi:
        cod = RUOLO_CODICE[RUOLI[b]]
        sotto = [r for r in righe if r[0] == cod]
        if sotto:
            esiti[cod] = tabella(sotto, 'RUOLO %s' % cod, 'livello')
            esiti[cod + '_striscia'] = tabella(sotto, 'RUOLO %s' % cod, 'striscia')

    # incrocio con la lunghezza dello storico: lo shrinkage di produzione
    # pesa k/(n+k), quindi su storico lungo e' quasi assente -- se il buco
    # c'e', qui dovrebbe vedersi piu' grosso
    for lo_n, hi_n, et in FASCE_N:
        sotto = [r for r in righe if lo_n <= r[6] <= hi_n]
        if sotto:
            esiti['storico_' + et.split()[0]] = tabella(
                sotto, 'STORICO %s partite (tutti i ruoli)' % et, 'livello')

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print('\nsalvato in %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
