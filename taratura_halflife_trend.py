"""taratura_halflife_trend — half_life e trend_intensity, sulla formula vera.

PERCHE' NON SI RIUSA IL GRID GIA' ESISTENTE.
`formazione_mls/diagnostics/validate_halflife_trend_grid2d.py` misura

    pred = media_pesata x fattore_casa_trasferta x fattore_trend

che e' la formula moltiplicativa abbandonata il 26/07: niente level_score da
tassi di Poisson, niente shrinkage verso il prior di ruolo, niente Stadio D.
Tarare li' significa scegliere i parametri di un modello che non e' quello che
schiera -- l'errore gia' pagato piu' volte in questo progetto. Qui si chiama
`compute_score_atteso_*`, la stessa funzione della produzione, tramite
`backtest_arene_previsioni.calcola`.

PERCHE' ADESSO. Il 03/08 `compute_trend_factor` e' stato corretto: confrontava
le ultime 5 partite con le ultime 10, ma le 5 sono DENTRO le 10, quindi
misurava (a-b)/(a+b) invece di (a-b)/b -- circa meta' del segnale. Con lo
stimatore rotto la taratura aveva spinto TREND_INTENSITY a 0.0 su GK e DEF
(l'intensita' ottima di uno stimatore rotto e' zero) e HALF_LIFE_GAMES a 25-30
su una finestra di 30 partite, cioe' pesi quasi piatti. Entrambi i valori vanno
rimessi in discussione ora che il segnale c'e'.

COME. Walk-forward sullo storico gia' in cache: per ogni (giocatore, partita
conclusa) si ricostruisce la finestra storica precedente UNA VOLTA
(`contesto`), poi si valuta l'intera griglia su quegli stessi ingressi. Senza
questa separazione una griglia da 40 combinazioni costerebbe venti ore.

Il criterio e' il MAE, ma si stampa anche la tenuta FUORI CAMPIONE: il pool
viene diviso a meta' per giocatore, e si guarda se il vincitore di una meta'
regge sull'altra. Un minimo che non regge e' rumore, non un parametro.

Uso:  python taratura_halflife_trend.py                # tutti i ruoli
      python taratura_halflife_trend.py --ruoli gk,def
      python taratura_halflife_trend.py --max 300      # prova rapida
"""
import argparse
import collections
import datetime
import json
import random
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLI = {'gk': 'Goalkeeper', 'def': 'Defender', 'mid': 'Midfielder', 'fwd': 'Forward'}
MIN_STORICO = 5

# Griglia. half_life arriva fino a 40 (oltre, su una finestra di 30 partite, i
# pesi sono ormai indistinguibili da una media piatta) e scende fino a 4 (il
# portiere oggi sta a 6). trend_intensity va oltre 0.5 perche' con le finestre
# disgiunte il delta e' circa il doppio di prima: quello che prima era 0.3 ora
# vale ~0.15, quindi la zona interessante si e' spostata.
HL_GRID = [4.0, 6.0, 9.0, 12.0, 16.0, 20.0, 25.0, 30.0, 40.0]
TI_GRID = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5]


def _data(nodo):
    return ((nodo.get('anyGame') or {}).get('date') or '')[:10]


def _ruolo_di(cache, slug):
    conteggi = collections.Counter()
    for nodo in cache.gamelog(slug):
        p = nodo.get('positionTyped') or nodo.get('position')
        if p in RUOLI.values():
            conteggi[p] += 1
    return conteggi.most_common(1)[0][0] if conteggi else None


def raccogli_contesti(cache, slugs, ruoli_voluti, limite=None):
    """[(ruolo, slug, contesto, realizzato)] su tutto lo storico in cache."""
    fuori = []
    for i, slug in enumerate(slugs, 1):
        if limite and i > limite:
            break
        ruolo = _ruolo_di(cache, slug)
        if ruolo is None or ruolo not in ruoli_voluti:
            continue
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale = nodo.get('score')
            data = _data(nodo)
            if reale is None or not data:
                continue
            giorno = datetime.datetime.strptime(data, '%Y-%m-%d') + datetime.timedelta(days=1)
            try:
                ctx = prev.contesto(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < MIN_STORICO:
                continue
            fuori.append((ruolo, slug, ctx, reale))
        if i % 100 == 0:
            print('  [%d/%d] %d punti di test' % (i, len(slugs), len(fuori)), flush=True)
    return fuori


def mae(punti, hl, ti):
    tot, n = 0.0, 0
    for _ruolo, _slug, ctx, reale in punti:
        try:
            p = prev.calcola(ctx, half_life=hl, trend_intensity=ti)
        except Exception:
            continue
        tot += abs(reale - p)
        n += 1
    return (tot / n if n else None), n


def valuta_ruolo(nome_breve, punti, modulo):
    hl_prod = modulo.HALF_LIFE_GAMES
    ti_prod = getattr(modulo, 'TREND_INTENSITY', 0.0)
    mae_prod, n = mae(punti, hl_prod, ti_prod)
    slugs = sorted({s for _r, s, _c, _v in punti})
    print('\n' + '=' * 92)
    print('%s -- %d giocatori, %d punti di test | PRODUZIONE half_life=%s trend=%s -> MAE %.4f'
          % (nome_breve.upper(), len(slugs), n, hl_prod, ti_prod, mae_prod))
    print('=' * 92)

    griglia = {}
    print('hl \\ ti  ' + '  '.join('%6.2f' % t for t in TI_GRID))
    migliore = None
    for hl in HL_GRID:
        riga = []
        for ti in TI_GRID:
            m, _ = mae(punti, hl, ti)
            griglia[(hl, ti)] = m
            riga.append(m)
            if migliore is None or m < migliore[0]:
                migliore = (m, hl, ti)
        print('%6.1f   ' % hl + '  '.join('%6.3f' % v for v in riga))

    m_best, hl_best, ti_best = migliore
    delta = (m_best - mae_prod) / mae_prod * 100
    print('\nMIGLIORE: half_life=%s trend_intensity=%s  MAE=%.4f  (%+.3f%% vs produzione)'
          % (hl_best, ti_best, m_best, delta))

    # --- tenuta fuori campione: meta' giocatori contro l'altra meta' ---
    rnd = random.Random(11)
    mescolati = list(slugs)
    rnd.shuffle(mescolati)
    meta = set(mescolati[:len(mescolati) // 2])
    A = [p for p in punti if p[1] in meta]
    B = [p for p in punti if p[1] not in meta]
    reggi = None
    if A and B:
        def vincitore(sotto):
            best = None
            for hl in HL_GRID:
                for ti in TI_GRID:
                    m, _ = mae(sotto, hl, ti)
                    if m is not None and (best is None or m < best[0]):
                        best = (m, hl, ti)
            return best
        _mA, hlA, tiA = vincitore(A)
        _mB, hlB, tiB = vincitore(B)
        mB_conA, _ = mae(B, hlA, tiA)
        mB_prod, _ = mae(B, hl_prod, ti_prod)
        reggi = mB_conA < mB_prod
        print('  fuori campione: meta' + "' A sceglie half_life=%s trend=%s; sull'altra meta' fa "
              'MAE %.4f contro %.4f della produzione -> %s'
              % (hlA, tiA, mB_conA, mB_prod, 'REGGE' if reggi else 'NON regge'))
        print("  (la meta' B, da sola, avrebbe scelto half_life=%s trend=%s)" % (hlB, tiB))

    return {'ruolo': nome_breve, 'prod': [hl_prod, ti_prod, mae_prod],
            'migliore': [hl_best, ti_best, m_best], 'delta_pct': delta,
            'regge_fuori_campione': reggi, 'n_test': n,
            'griglia': {'%s|%s' % k: v for k, v in griglia.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='gk,def,mid,fwd')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/taratura_halflife_trend.json')
    # Griglie personalizzabili: servono quando il vincitore cade sul BORDO
    # (successo il 03/08 con FWD a half_life=4.0, il valore piu' basso
    # provato) -- un minimo al bordo non e' un minimo, e' una griglia troppo
    # corta, e va riaperta prima di applicare qualunque cosa.
    ap.add_argument('--hl', help='griglia half_life, es. 1.5,2,3,4,6')
    ap.add_argument('--ti', help='griglia trend_intensity, es. 0,0.05')
    args = ap.parse_args()

    global HL_GRID, TI_GRID
    if args.hl:
        HL_GRID = [float(x) for x in args.hl.split(',')]
    if args.ti:
        TI_GRID = [float(x) for x in args.ti.split(',')]

    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    voluti = {RUOLI[b] for b in brevi}

    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache, ruoli: %s' % (len(slugs), ', '.join(brevi)))
    punti = raccogli_contesti(cache, slugs, voluti, args.max or None)
    print('%d punti di test raccolti' % len(punti))

    esiti = []
    for b in brevi:
        sotto = [p for p in punti if p[0] == RUOLI[b]]
        if len(sotto) < 200:
            print('\n%s: solo %d punti, salto' % (b.upper(), len(sotto)))
            continue
        esiti.append(valuta_ruolo(b, sotto, sotto[0][2]['modulo']))

    print('\n' + '=' * 92)
    print('RIEPILOGO')
    for e in esiti:
        stato = ('da applicare' if (e['delta_pct'] < -0.1 and e['regge_fuori_campione'])
                 else 'lasciare com/e')
        print('  %-4s produzione %s/%s -> migliore %s/%s  (%+.2f%%, fuori campione: %s)  %s'
              % (e['ruolo'], e['prod'][0], e['prod'][1], e['migliore'][0], e['migliore'][1],
                 e['delta_pct'], e['regge_fuori_campione'], stato))
    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print('\nsalvato in %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
