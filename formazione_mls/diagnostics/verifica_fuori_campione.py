"""Un candidato migliore vale davvero, o e' rumore scelto sugli stessi dati?

Serve a decidere se applicare miglioramenti PICCOLI (0.05-0.2% di MAE). Il
guadagno misurato sul campione su cui si e' scelto e' sempre ottimista: il
candidato vince anche solo perche' quella era la sua giornata fortunata.

METODO. Si divide il pool di giocatori a caso in meta': su una si sceglie
NIENTE (i due candidati sono dati), sull'altra si misura. Ripetuto molte volte,
si conta quante volte il candidato batte la produzione sui giocatori NON usati
per sceglierlo. Sotto il 95% non e' un miglioramento dimostrato.

Uso:
  RUOLO=mid CANDIDATO="90,0.1,1.1" PRODUZIONE="25,0.2,1.1" \
      python formazione_mls/diagnostics/verifica_fuori_campione.py
"""
import collections
import glob
import json
import os
import random
import sys

RUOLO = os.environ.get('RUOLO', (sys.argv[1] if len(sys.argv) > 1 else 'mid')).lower()
COMBO_ATTESE = {'gk': 240, 'def': 168, 'mid': 210, 'fwd': 210}
N_BOOT = int(os.environ.get('N_BOOT', '500'))


def _combo(nome, default):
    raw = os.environ.get(nome, default)
    p = [float(x) for x in raw.split(',')]
    return (p[0], p[1], p[2])


def carica():
    """[(slug, {combo: (mae, n_test)})] solo dai file con la griglia corrente."""
    out = []
    for f in glob.glob(f'formazione_*/output/*_{RUOLO}_calibration/grid_search/*_grid.json'):
        try:
            righe = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        if len(righe) != COMBO_ATTESE[RUOLO]:
            continue
        d = {}
        for r in righe:
            if r.get('mae') is None or (r.get('n_test') or 0) < 3:
                continue
            d[(r['half_life'], r['trend_intensity'], r['range_multiplier'])] = (
                r['mae'], r['n_test'])
        if d:
            out.append((os.path.basename(f)[:-10], d))
    return out


def mae(campione, combo):
    num = den = 0.0
    for _s, d in campione:
        v = d.get(combo)
        if v:
            num += v[0] * v[1]
            den += v[1]
    return (num / den) if den else None


def main():
    cand = _combo('CANDIDATO', '90,0.1,1.1')
    prod = _combo('PRODUZIONE', '25,0.2,1.1')
    campione = carica()
    m_c, m_p = mae(campione, cand), mae(campione, prod)
    if m_c is None or m_p is None:
        print(f'{RUOLO}: una delle due combinazioni non e\' nella griglia '
              f'(candidato {cand} -> {m_c}, produzione {prod} -> {m_p})')
        return
    print(f'{RUOLO.upper()}  giocatori {len(campione)}')
    print(f'  candidato  {cand}  MAE {m_c:.4f}')
    print(f'  produzione {prod}  MAE {m_p:.4f}   ({(m_c/m_p-1)*100:+.3f}%)')

    vinte = 0
    for _ in range(N_BOOT):
        random.shuffle(campione)
        meta = campione[len(campione) // 2:]
        a, b = mae(meta, cand), mae(meta, prod)
        if a is not None and b is not None and a < b:
            vinte += 1
    q = vinte / N_BOOT * 100
    print(f'  il candidato batte la produzione nel {q:.1f}% delle meta\' casuali')
    print('  -> ' + ('MIGLIORAMENTO REALE, applicabile.' if q >= 95
                     else 'non dimostrato: differenza dentro il rumore.'))


if __name__ == '__main__':
    random.seed(7)
    main()
