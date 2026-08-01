"""Lo shrinkage deve essere piu' forte su chi ha poco storico?

Oggi k e' un numero solo per ruolo. Ma dai dati (validate_outlier_shrinkage,
01/08) emerge che il k migliore dipende da quante partite ha il giocatore: sul
FWD, k=30 migliora del 3.6% chi ha meno di 8 partite e PEGGIORA dell'1.7% chi
ne ha di piu'. Il k unico e' un compromesso fra due esigenze opposte.

Qui si testa un k a due valori: k_pochi per n < SOGLIA, k_molti sopra. Il
confronto e' contro il k unico di produzione, sugli STESSI punti di test.

Ha senso a priori: con poche partite la media personale e' rumorosa e conviene
tirarla verso il prior; con molte partite il prior aggiunge solo distorsione.

Uso:  python formazione_mls/diagnostics/validate_shrink_k_per_storico.py [ruolo]
"""
import collections
import glob
import json
import math
import os
import random
import statistics
import sys

RUOLO = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get('RUOLO', 'fwd')).lower()
SOGLIA = int(os.environ.get('SOGLIA_N', '8'))
MIN_STORICO = 3
HALF_LIFE = {'gk': 6.0, 'def': 20.0, 'mid': 25.0, 'fwd': 25.0}[RUOLO]
K_PROD = {'gk': 30.0, 'def': 15.0, 'mid': 5.0, 'fwd': 5.0}[RUOLO]


def carica():
    per_slug = collections.defaultdict(list)
    for path in glob.glob(f'dati_globali/detail_cache/*/{RUOLO}/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict) or v.get('scoreStatus') != 'FINAL':
                continue
            data = ((v.get('anyGame') or {}).get('date') or '')[:10]
            if data and v.get('score') is not None:
                per_slug[slug].append((data, v['score']))
    for s in per_slug:
        per_slug[s].sort()
    return per_slug


def media_pesata(scores):
    n = len(scores)
    pesi = [math.pow(0.5, (n - 1 - i) / HALF_LIFE) for i in range(n)]
    return sum(s * p for s, p in zip(scores, pesi)) / sum(pesi)


def errori(per_slug, k_pochi, k_molti, prior):
    """errore assoluto per ogni punto di test, walk-forward."""
    out = []
    for _slug, v in per_slug.items():
        scores = [s for _d, s in v]
        for i in range(MIN_STORICO, len(scores)):
            passato = scores[:i]
            n = len(passato)
            k = k_pochi if n < SOGLIA else k_molti
            grezzo = media_pesata(passato)
            atteso = (n / (n + k)) * grezzo + (k / (n + k)) * prior
            out.append((abs(scores[i] - atteso), _slug))
    return out


def mae(err):
    return statistics.mean([e for e, _s in err]) if err else None


def main():
    per_slug = carica()
    tutti = [s for v in per_slug.values() for _d, s in v]
    prior = statistics.mean(tutti)
    print(f'{RUOLO.upper()}: {len(per_slug)} giocatori, {len(tutti)} partite, '
          f'prior {prior:.2f}, k produzione {K_PROD}, soglia n<{SOGLIA}')

    base = errori(per_slug, K_PROD, K_PROD, prior)
    m_base = mae(base)
    print(f'  k unico {K_PROD}: MAE {m_base:.4f}  ({len(base)} punti)\n')

    migliori = []
    for kp in (5, 10, 15, 20, 30, 40):
        for km in (1, 2, 3, 5, 8, 15):
            m = mae(errori(per_slug, kp, km, prior))
            migliori.append((m, kp, km))
    migliori.sort()
    for m, kp, km in migliori[:5]:
        print(f'  k_pochi={kp:<3} k_molti={km:<3} MAE {m:.4f}  ({(m/m_base-1)*100:+.3f}%)')

    m, kp, km = migliori[0]
    if m >= m_base:
        print('\n  nessuna combinazione batte il k unico.')
        return

    # verifica fuori campione: si sceglie su meta' giocatori, si misura sull'altra
    slugs = list(per_slug)
    vinte = 0
    N = 200
    random.seed(5)
    for _ in range(N):
        random.shuffle(slugs)
        meta = {s: per_slug[s] for s in slugs[len(slugs) // 2:]}
        a = mae(errori(meta, kp, km, prior))
        b = mae(errori(meta, K_PROD, K_PROD, prior))
        if a is not None and b is not None and a < b:
            vinte += 1
    q = vinte / N * 100
    print(f'\n  fuori campione: k_pochi={kp}/k_molti={km} batte il k unico nel {q:.1f}% dei casi')
    print('  -> ' + ('MIGLIORAMENTO REALE.' if q >= 95 else 'non dimostrato.'))


if __name__ == '__main__':
    main()
