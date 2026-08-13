# -*- coding: utf-8 -*-
"""SHRINKAGE: la prova sulla carta, prima di toccare la formula (14/08/2026)

DA DOVE NASCE. p67 ha mostrato che due terzi del valore del voto sono
"questo giocatore e' forte" -- cioe' un difetto nostro. p68 ha mostrato DOVE:
il voto ci batte il doppio sui giocatori con poche partite (corr +0,18 sotto
le 10 partite contro +0,07 sopra le 35), e di piu' su FWD e GK, che sono
esattamente i due ruoli in cui teniamo la memoria corta (half_life 6).
Diagnosi: la media pesata e' POCO ANCORATA quando il campione efficace e'
piccolo.

LA CURA DA PROVARE. Invece di fidarsi della media di un giocatore, tirarla
verso un livello di riferimento (media del suo ruolo in quella lega), tanto
piu' forte quanto meno l'abbiamo osservato:

    stima = ancora + w * (atteso - ancora),   w = n / (n + k)

k=0 -> w=1 -> nessuno shrinkage, cioe' la PRODUZIONE DI OGGI.
k grande -> tutti tirati sull'ancora.

AVVERTENZA SCRITTA PRIMA DI GUARDARE I NUMERI. Lo shrinkage riduce l'errore
medio quasi per costruzione (meno varianza in cambio di un po' di
distorsione). Ma qui non si vendono previsioni, si SCELGONO carte: vale solo
se migliora anche l'ORDINAMENTO. Per questo si guardano MAE, correlazione e
un lift di selezione INSIEME (regola del repo: il MAE da solo premia i
modelli che non distinguono niente).

L'ancora e' costruita sui soli ATTESI (nessun punteggio realizzato entra),
quindi non c'e' leakage: e' un livello, non un esito.

Uso: python analisi_manager/p69_shrinkage_prova.py
"""
import os
import sys
import io
import math
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p24_binario2_ga as B2  # noqa: E402
import backtest_arene_cache as CACHE  # noqa: E402
import backtest_arene_previsioni as P  # noqa: E402

FINESTRA_GIORNI = 365
KAPPA = [0, 1, 2, 5, 10, 20, 50]
cache = CACHE.CacheLocale()
_memo = {}


def partite_prima(slug, cutoff):
    k = (slug, cutoff.date().isoformat())
    if k in _memo:
        return _memo[k]
    inizio = cutoff - datetime.timedelta(days=FINESTRA_GIORNI)
    n = 0
    for nodo in cache.gamelog(slug) or []:
        d = P._dt((nodo.get('anyGame') or {}).get('date'))
        if d is None or not (inizio <= d < cutoff):
            continue
        if ((nodo.get('anyPlayerGameStats') or {}).get('minsPlayed') or 0) > 0:
            n += 1
    _memo[k] = n
    return n


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def metriche(righe, k, per_fixture):
    """MAE, correlazione e lift di selezione per un dato k."""
    err = []
    stime, reali = [], []
    for r in righe:
        w = r['n'] / (r['n'] + k) if (r['n'] + k) > 0 else 1.0
        s = r['ancora'] + w * (r['cal'] - r['ancora'])
        r['_s'] = s
        err.append(abs(r['reale'] - s))
        stime.append(s)
        reali.append(r['reale'])
    mae = sum(err) / len(err)
    c = corr(stime, reali)
    # LIFT: per ogni giornata prendo il decile alto secondo la stima e guardo
    # quanto ha reso davvero, contro la media di tutti quel giorno.
    sopra, media = [], []
    for fx, gruppo in per_fixture.items():
        if len(gruppo) < 20:
            continue
        ordinati = sorted(gruppo, key=lambda r: -r['_s'])
        top = ordinati[:max(1, len(ordinati) // 10)]
        sopra.append(sum(r['reale'] for r in top) / len(top))
        media.append(sum(r['reale'] for r in gruppo) / len(gruppo))
    lift = (sum(sopra) / len(sopra)) - (sum(media) / len(media)) if sopra else 0.0
    return mae, c, lift


def main():
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    visti = {}
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        cutoff = pre['primo_kickoff']
        for r in pre['pool_rows']:
            k = (r['slug'], fx)
            if k in visti or r.get('reale') is None or r.get('_cal') is None:
                continue
            visti[k] = {'slug': r['slug'], 'fixture': fx, 'codice': r['codice'],
                        'lega': r.get('lega'), 'cal': r['_cal'],
                        'reale': r['reale'], 'n': partite_prima(r['slug'], cutoff)}
    righe = list(visti.values())
    print('osservazioni deduplicate: %d' % len(righe))

    # ANCORA: media degli ATTESI nel gruppo (lega, ruolo). Nessun realizzato.
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[(r['lega'], r['codice'])].append(r['cal'])
    ancore = {g: sum(v) / len(v) for g, v in gruppi.items()}
    for r in righe:
        r['ancora'] = ancore[(r['lega'], r['codice'])]

    per_fixture = collections.defaultdict(list)
    for r in righe:
        per_fixture[r['fixture']].append(r)

    print()
    print('%-6s %10s %10s %10s   %s' % ('k', 'MAE', 'corr', 'lift', 'verso'))
    base = None
    for k in KAPPA:
        mae, c, lift = metriche(righe, k, per_fixture)
        if base is None:
            base = (mae, c, lift)
            print('%-6d %10.4f %10.4f %10.3f   <- PRODUZIONE (nessuno shrinkage)'
                  % (k, mae, c, lift))
            continue
        segni = []
        segni.append('MAE %s' % ('meglio' if mae < base[0] else 'peggio'))
        segni.append('corr %s' % ('meglio' if c > base[1] else 'peggio'))
        segni.append('lift %s' % ('meglio' if lift > base[2] else 'peggio'))
        tutti_meglio = mae < base[0] and c > base[1] and lift > base[2]
        print('%-6d %10.4f %10.4f %10.3f   %s%s'
              % (k, mae, c, lift, ', '.join(segni),
                 '   <== TUTTI E TRE MEGLIO' if tutti_meglio else ''))

    print()
    print('E DOVE aiuta: MAE per fascia di esperienza, k=0 contro il migliore')
    fasce = [(0, 10), (10, 20), (20, 35), (35, 999)]
    for lo, hi in fasce:
        sub = [r for r in righe if lo <= r['n'] < hi]
        if len(sub) < 100:
            continue
        pf = collections.defaultdict(list)
        for r in sub:
            pf[r['fixture']].append(r)
        riga = ['%-10s n=%5d' % ('%d-%d' % (lo, hi if hi < 999 else 99), len(sub))]
        for k in (0, 5, 20):
            mae, _c, _l = metriche(sub, k, pf)
            riga.append('k=%-2d MAE %.3f' % (k, mae))
        print('  ' + '   '.join(riga))

    print()
    print('REGOLA DEL REPO: si applica solo se MAE, correlazione e lift si')
    print('muovono TUTTI E TRE nello stesso verso. Se migliora solo il MAE,')
    print('abbiamo comprato precisione media vendendo capacita\' di scegliere,')
    print('che e\' esattamente il contrario di quello che ci serve.')


if __name__ == '__main__':
    main()
