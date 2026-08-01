"""Conviene mettere portiere e difensore della STESSA squadra?

E' la coppia con la correlazione same-team piu' forte di tutte (+0.341,
misurata su 3084 coppie): condividono il clean sheet, quindi vanno su e giu'
insieme. La domanda pratica dell'utente: vale la pena rinunciare a qualche
punto atteso pur di accoppiarli?

Come per lo stack, la media non basta: la correlazione alza la VARIANZA del
totale, quindi va misurata la P(superare soglia). E si misura anche QUANTO
punteggio atteso si puo' sacrificare restando in pari.

Metodo: dai detail cache si ricostruiscono le partite; per ogni squadra-partita
si prende un GK e un DEF veri di quella squadra (coppia correlata) e li si
confronta con un GK e un DEF presi da partite DIVERSE (nessuna correlazione),
a parita' di livello medio.

Uso:  python formazione_mls/diagnostics/misura_coppia_gk_def.py
"""
import collections
import glob
import json
import os
import random
import statistics

N_TRIALS = int(os.environ.get('N_TRIALS', '40000'))


def carica():
    """(data, casa, fuori) -> {ruolo: [(slug, score)]}"""
    per_partita = collections.defaultdict(lambda: collections.defaultdict(list))
    club_viste = collections.defaultdict(collections.Counter)
    righe = []
    for ruolo in ('gk', 'def'):
        for path in glob.glob(f'dati_globali/detail_cache/*/{ruolo}/*_detail_cache.json'):
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
                g = v.get('anyGame') or {}
                data = (g.get('date') or '')[:10]
                h = (g.get('homeTeam') or {}).get('slug')
                a = (g.get('awayTeam') or {}).get('slug')
                if not (data and h and a) or v.get('score') is None:
                    continue
                club_viste[slug][h] += 1
                club_viste[slug][a] += 1
                righe.append((ruolo, slug, (data, h, a), v['score']))
    club_di = {s: c.most_common(1)[0][0] for s, c in club_viste.items() if c}
    for ruolo, slug, chiave, score in righe:
        club = club_di.get(slug)
        if club in (chiave[1], chiave[2]):
            per_partita[(chiave, club)][ruolo].append((slug, score))
    return per_partita


def main():
    dati = carica()
    coppie, gk_soli, altri = [], [], []
    for v in dati.values():
        if v.get('gk') and v.get('def'):
            coppie.append((v['gk'][0][1], v['def'][0][1]))
        if v.get('gk'):
            gk_soli.append(v['gk'][0][1])
        for r in ('def',):
            for _s, sc in v.get(r, []):
                altri.append(sc)
    if len(coppie) < 100 or len(altri) < 100:
        print('dati insufficienti')
        return
    print(f'coppie GK+DEF stessa squadra: {len(coppie)} | GK {len(gk_soli)} | DEF {len(altri)}')

    random.seed(11)
    # Formazione da 5: GK + DEF + 3 altri. Nella variante ACCOPPIATA il GK e il
    # primo DEF vengono dalla STESSA squadra-partita; negli altri casi tutti da
    # partite diverse. Gli altri 3 slot sono identici fra le due varianti, cosi'
    # l'unica differenza e' l'accoppiamento.
    acc, sep = [], []
    for _ in range(N_TRIALS):
        resto = sum(random.choice(altri) for _ in range(3))
        g, d = random.choice(coppie)
        acc.append(g + d + resto)
        sep.append(random.choice(gk_soli) + random.choice(altri) + resto)

    m_a, m_s = statistics.mean(acc), statistics.mean(sep)
    print(f'\n  accoppiati  media {m_a:6.1f}  dev.std {statistics.pstdev(acc):5.1f}')
    print(f'  separati    media {m_s:6.1f}  dev.std {statistics.pstdev(sep):5.1f}')

    rif = sorted(sep)
    print()
    for q in (0.5, 0.75, 0.9, 0.95):
        soglia = rif[int(q * len(rif)) - 1]
        pa = sum(1 for x in acc if x > soglia) / len(acc) * 100
        ps = sum(1 for x in sep if x > soglia) / len(sep) * 100
        margine = 0.0
        while margine < 20:
            p = sum(1 for x in acc if x - margine > soglia) / len(acc) * 100
            if p < ps:
                break
            margine += 0.5
        print(f'  soglia {soglia:6.1f} (top {100-q*100:.0f}%): accoppiati {pa:5.1f}% '
              f'vs separati {ps:5.1f}%   sacrificio sostenibile {margine:.1f} pt')


if __name__ == '__main__':
    main()
