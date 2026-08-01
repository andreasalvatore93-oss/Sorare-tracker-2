"""I Duelli vanno condizionati per casa/avversario come le altre categorie?

Stadio D oggi condiziona SOLO efficacia offensiva, passaggio e gol subiti. Ma
sui dati di oggi (65k partite) i Duelli sono il gruppo granulare piu' pesante
per DEF/MID/FWD (17-23% del movimento di punteggio), e non sono condizionati.

La domanda non e' "quanto pesano" ma "il loro scarto dalla media personale
dipende dal contesto?". Se un giocatore fa piu' duelli in casa, o contro
avversari forti, allora condizionarli aggiunge segnale; se lo scarto e' casuale,
no -- e' lo stesso criterio con cui furono scelte le tre categorie attuali.

Metodo: per ogni partita si calcola il residuo del valore rispetto alla media
storica PRECEDENTE del giocatore (nessun lookahead), poi si confronta la media
dei residui in casa vs fuori e contro avversari forti vs deboli. Lo z-score
dice se la differenza e' credibile.

Uso:  python formazione_mls/diagnostics/test_duelli_stadio_d.py
"""
import collections
import glob
import json
import math
import os
import statistics

GRUPPI = {
    'duelli': ('duels_won', 'duel_won', 'duels', 'ground_duel_won', 'aerial_duel_won'),
    'efficacia_offensiva': ('shot_on_target', 'chance_created', 'assist', 'goal'),
    'passaggio': ('accurate_pass', 'key_pass', 'accurate_long_ball'),
}
RUOLI = ('def', 'mid', 'fwd')


def valore_gruppo(detail, stat_names):
    tot = 0.0
    for r in (detail.get('detailedScore') or []):
        if r.get('stat') in stat_names:
            tot += r.get('totalScore') or 0.0
    return tot


def carica(ruolo):
    """[(slug, data, valori_per_gruppo, is_home, rank_avv)] ordinate."""
    out = collections.defaultdict(list)
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
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if not data or not home.get('slug') or not away.get('slug'):
                continue
            vals = {k: valore_gruppo(v, names) for k, names in GRUPPI.items()}
            out[slug].append((data, vals, home.get('domesticLeagueRanking'),
                              away.get('domesticLeagueRanking')))
    for s in out:
        out[s].sort(key=lambda x: x[0])
    return out


def z(a, b):
    """z della differenza fra due medie indipendenti."""
    if len(a) < 20 or len(b) < 20:
        return None, None
    d = statistics.mean(a) - statistics.mean(b)
    se = math.sqrt(statistics.pvariance(a) / len(a) + statistics.pvariance(b) / len(b))
    return d, (d / se if se else None)


def main():
    for ruolo in RUOLI:
        dati = carica(ruolo)
        print(f'\n=== {ruolo.upper()} ({len(dati)} giocatori)')
        for gruppo in GRUPPI:
            forte, debole = [], []
            for _slug, partite in dati.items():
                storico = []
                for _data, vals, rh, ra in partite:
                    x = vals.get(gruppo)
                    if x is None:
                        continue
                    if len(storico) >= 5:
                        residuo = x - statistics.mean(storico)
                        if rh is not None and ra is not None:
                            (forte if ra < rh else debole).append(residuo)
                    storico.append(x)
            d, zz = z(forte, debole)
            if zz is None:
                print(f'  {gruppo:22s} dati insufficienti')
                continue
            stato = 'SEGNALE' if abs(zz) >= 2 else 'rumore'
            print(f'  {gruppo:22s} avv.forte-debole {d:+6.2f}  z={zz:+5.2f}  '
                  f'({len(forte)}/{len(debole)})  {stato}')


if __name__ == '__main__':
    main()
