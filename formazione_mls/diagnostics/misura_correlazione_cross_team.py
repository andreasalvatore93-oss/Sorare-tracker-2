"""Quanto sono davvero anti-correlati due giocatori AVVERSARI nella stessa
partita? (31/07)

PERCHE'. `CROSS_TEAM_PENALTY_BY_PAIR` (DEF-FWD 4, DEF-MID 3, MID-MID 2) nasce
dalla convenzione "correlazione misurata x 20". La correlazione era stata
misurata, ma il 30/07 solo su una parte delle coppie e con campioni disomogenei
(MID-MID e' segnata come "non riconfermata"). Qui si rimisura tutto sullo
stesso dataset, per verificare segno e dimensione.

METODO. Dai detail cache si ricostruisce ogni partita giocata (data + le due
squadre) e i punteggi di tutti i giocatori presenti. Per ogni partita si
formano tutte le coppie AVVERSARIO-AVVERSARIO e si registra la coppia di
punteggi, etichettata con la coppia di ruoli. Alla fine si calcola la
correlazione di Pearson per ogni coppia di ruoli.

IMPORTANTE, il confronto che conta: la correlazione grezza fra due giocatori
qualsiasi non e' zero nemmeno per caso, perche' i punteggi hanno medie e
dispersioni diverse per ruolo. Per questo si riporta anche un CONTROLLO: le
stesse coppie di ruoli ma fra giocatori che NON si sono affrontati (partite
diverse). Se la correlazione fra avversari e' piu' negativa di quella di
controllo, l'effetto e' reale.

Uso:  python formazione_mls/diagnostics/misura_correlazione_cross_team.py
"""
import glob
import json
import math
import os
import random
import statistics
from collections import defaultdict

random.seed(20260731)
MIN_COPPIE = 30


def carica():
    """(partite, ruolo_di) dove partite[(data, squadre)] = [(slug, score), ...]"""
    sep = chr(92)
    per_partita = defaultdict(dict)
    ruolo_di = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        ruolo = path.replace(sep, '/').split('/')[-2].upper()
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        if slug in ruolo_di:
            continue
        ruolo_di[slug] = ruolo
        try:
            cache = json.load(open(path, encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        for v in cache.values():
            if not isinstance(v, dict) or v.get('score') is None:
                continue
            g = v.get('anyGame') or {}
            casa = (g.get('homeTeam') or {}).get('slug')
            fuori = (g.get('awayTeam') or {}).get('slug')
            data = (g.get('date') or '')[:10]
            if not (casa and fuori and data):
                continue
            per_partita[(data, frozenset((casa, fuori)))][slug] = (float(v['score']), casa, fuori)
    return per_partita, ruolo_di


def squadra_di(slug, partite):
    """Squadra piu' frequente del giocatore, per sapere da che lato sta."""
    conteggi = defaultdict(int)
    for giocatori in partite.values():
        if slug in giocatori:
            _sc, casa, fuori = giocatori[slug]
            conteggi[casa] += 1
            conteggi[fuori] += 1
    return max(conteggi, key=conteggi.get) if conteggi else None


def pearson(coppie):
    xs = [a for a, _b in coppie]
    ys = [b for _a, b in coppie]
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in coppie)
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def main():
    print("Ricostruisco le partite dai detail cache...")
    partite, ruolo_di = carica()
    print(f"Partite ricostruite: {len(partite)}")

    # squadra abituale di ogni giocatore (una volta sola)
    squadra = {}
    for giocatori in partite.values():
        for slug, (_sc, casa, fuori) in giocatori.items():
            if slug not in squadra:
                squadra[slug] = defaultdict(int)
            squadra[slug][casa] += 1
            squadra[slug][fuori] += 1
    squadra = {s: max(c, key=c.get) for s, c in squadra.items()}

    avversari = defaultdict(list)
    compagni = defaultdict(list)
    per_ruolo_punteggi = defaultdict(list)

    for (_data, _sq), giocatori in partite.items():
        elenco = list(giocatori.items())
        for slug, (score, _c, _f) in elenco:
            per_ruolo_punteggi[ruolo_di.get(slug, '?')].append(score)
        for i in range(len(elenco)):
            for j in range(i + 1, len(elenco)):
                s1, (v1, _c1, _f1) = elenco[i]
                s2, (v2, _c2, _f2) = elenco[j]
                r1, r2 = ruolo_di.get(s1), ruolo_di.get(s2)
                if not r1 or not r2:
                    continue
                chiave = frozenset((r1, r2))
                if squadra.get(s1) == squadra.get(s2):
                    compagni[chiave].append((v1, v2))
                else:
                    avversari[chiave].append((v1, v2))

    # controllo: stesse coppie di ruoli ma giocatori mai incontrati
    controllo = {}
    for chiave in avversari:
        r1, r2 = tuple(chiave) if len(chiave) == 2 else (tuple(chiave)[0],) * 2
        a, b = per_ruolo_punteggi.get(r1, []), per_ruolo_punteggi.get(r2, [])
        if len(a) > 50 and len(b) > 50:
            n = min(len(avversari[chiave]), 5000)
            controllo[chiave] = pearson([(random.choice(a), random.choice(b)) for _ in range(n)])

    ATTUALI = {frozenset(('DEF', 'FWD')): 4, frozenset(('MID', 'MID')): 2,
               frozenset(('DEF', 'MID')): 3}

    print(f"\n{'coppia ruoli':<14}{'n coppie':>10}{'corr AVVERSARI':>17}"
          f"{'corr controllo':>17}{'penalita oggi':>15}{'x20 implicito':>15}")
    for chiave in sorted(avversari, key=lambda k: -len(avversari[k])):
        dati = avversari[chiave]
        if len(dati) < MIN_COPPIE:
            continue
        r = pearson(dati)
        if r is None:
            continue
        etichetta = '-'.join(sorted(chiave)) if len(chiave) == 2 else f"{tuple(chiave)[0]}-{tuple(chiave)[0]}"
        ctrl = controllo.get(chiave)
        pen = ATTUALI.get(chiave)
        print(f"  {etichetta:<12}{len(dati):>10}{r:>+17.4f}"
              f"{(f'{ctrl:+.4f}' if ctrl is not None else 'n/d'):>17}"
              f"{(str(pen) if pen else '-'):>15}{-r * 20:>+15.1f}")

    print("\n(la colonna 'x20 implicito' e' la penalita' che la convenzione")
    print(" 'correlazione x 20' produrrebbe con la correlazione misurata ORA)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
