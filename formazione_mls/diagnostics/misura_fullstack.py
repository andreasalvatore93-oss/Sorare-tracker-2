"""Quando conviene lo stack (3/4/5 giocatori della stessa squadra)?

IDEA. I compagni di squadra hanno punteggi correlati: se la squadra domina e
tiene la porta inviolata, GK e DEF prendono il bonus clean sheet insieme. Lo
stack alza la VARIANZA del totale: e' un danno se basta poco per superare la
soglia, e' un guadagno se serve un colpo grosso. La domanda vera non e' "lo
stack rende di piu' in media" (quasi sempre no), ma "in quali partite alza la
probabilita' di superare la soglia".

METODO. Dai detail cache si ricostruisce ogni partita (data + due squadre) e i
punteggi dei giocatori di ciascuna squadra. Per ogni squadra-partita:
  - `facile` = differenza di ranking in classifica fra la squadra e l'avversario
    (dato gia' nel game log: domesticLeagueRanking), quindi disponibile PRIMA
    della partita, che e' l'unico modo di usarlo in produzione;
  - si misura la correlazione media fra compagni e la P(somma > soglia) per uno
    stack di N, confrontata con N giocatori presi da partite DIVERSE (stesso
    livello atteso, nessuna correlazione).

Il confronto e' a parita' di punteggio atteso: si campionano gli N giocatori
indipendenti dalla stessa distribuzione di media, cosi' l'unica differenza e'
la correlazione.

Uso:  python formazione_mls/diagnostics/misura_fullstack.py
      N_STACK=3,4,5  SOGLIE=...  N_TRIALS=...
"""
import collections
import glob
import json
import os
import random
import statistics
import sys

N_STACK = [int(x) for x in os.environ.get('N_STACK', '3,4,5').split(',')]
N_TRIALS = int(os.environ.get('N_TRIALS', '20000'))
MIN_PER_SQUADRA = 3


def carica_partite():
    """(chiave partita, squadra) -> {slug: (score, ruolo, clean_sheet)} + contesto."""
    per_squadra = collections.defaultdict(dict)
    contesto = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
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
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            data = g.get('date')
            if not (data and home.get('slug') and away.get('slug')):
                continue
            score = v.get('score')
            if score is None:
                continue
            # la squadra del giocatore non e' nel record: si deduce dal fatto
            # che compare in una sola delle due (si prova con entrambe e si
            # tiene la coerenza piu' avanti). Qui si indicizza per partita.
            chiave = (data, home['slug'], away['slug'])
            contesto[chiave] = {
                'home': home['slug'], 'away': away['slug'],
                'rank_home': home.get('domesticLeagueRanking'),
                'rank_away': away.get('domesticLeagueRanking'),
            }
            gc = 0.0
            for riga in (v.get('detailedScore') or []):
                if riga.get('stat') == 'goals_conceded':
                    gc = riga.get('statValue') or 0.0
            per_squadra[chiave][slug] = (score, v.get('position'), gc)
    return per_squadra, contesto


def p_sopra(valori, soglia):
    return sum(1 for v in valori if v > soglia) / len(valori) if valori else 0.0


def main():
    per_partita, contesto = carica_partite()
    print(f'partite ricostruite: {len(per_partita)}')

    # Un giocatore appartiene alla squadra con cui condivide i gol subiti:
    # approssimazione robusta -- i compagni hanno lo STESSO goals_conceded.
    # Club del giocatore: la squadra presente in TUTTE le sue partite.
    squadre_viste = collections.defaultdict(collections.Counter)
    for chiave, giocatori in per_partita.items():
        ctx = contesto[chiave]
        for slug in giocatori:
            squadre_viste[slug][ctx['home']] += 1
            squadre_viste[slug][ctx['away']] += 1
    club_di = {s: c.most_common(1)[0][0] for s, c in squadre_viste.items() if c}

    # FORZA DELLA ROSA: punteggio medio storico dei giocatori di ogni squadra,
    # su tutte le partite disponibili. Sostituisce la posizione in classifica,
    # che alla prima giornata non esiste e nelle prime e' rumore su pochi
    # risultati. Questa e' stabile e attraversa le stagioni.
    punteggi_club = collections.defaultdict(list)
    for chiave, giocatori in per_partita.items():
        for slug, (score, _pos, _gc) in giocatori.items():
            club = club_di.get(slug)
            if club:
                punteggi_club[club].append(score)
    forza = {c: statistics.mean(v) for c, v in punteggi_club.items() if len(v) >= 30}

    gruppi = []   # (vantaggio_forza, gol_subiti, [score,...]) per squadra-partita
    for chiave, giocatori in per_partita.items():
        ctx = contesto[chiave]
        if ctx['home'] not in forza or ctx['away'] not in forza:
            continue
        per_team = collections.defaultdict(list)
        gc_team = {}
        for slug, (score, _pos, gc) in giocatori.items():
            club = club_di.get(slug)
            if club not in (ctx['home'], ctx['away']):
                continue
            per_team[club].append(score)
            gc_team[club] = gc
        for club, scores in per_team.items():
            if len(scores) < MIN_PER_SQUADRA:
                continue
            avv_club = ctx['away'] if club == ctx['home'] else ctx['home']
            gruppi.append((forza[club] - forza[avv_club], gc_team.get(club, 0.0), scores))

    print(f'squadra-partita utilizzabili (>= {MIN_PER_SQUADRA} giocatori): {len(gruppi)}')
    if not gruppi:
        return

    divari = sorted(g[0] for g in gruppi)
    d10 = divari[len(divari) // 10]
    q1, q3 = divari[len(divari) // 4], divari[3 * len(divari) // 4]
    d90 = divari[9 * len(divari) // 10]
    fasce = {
        'SFAVORITA (forza %+.1f o meno)' % q1: [g for g in gruppi if g[0] <= q1],
        'equilibrio': [g for g in gruppi if q1 < g[0] < q3],
        'FAVORITA (forza %+.1f o oltre)' % q3: [g for g in gruppi if g[0] >= q3],
        'STRAFAVORITA (top 10%%, forza %+.1f o oltre)' % d90: [g for g in gruppi if g[0] >= d90],
        'STRAFAVORITA + clean sheet': [g for g in gruppi if g[0] >= d90 and g[1] == 0],
    }

    for nome, gg in fasce.items():
        if len(gg) < 30:
            continue
        tutti = [s for _d, _gc, ss in gg for s in ss]
        media = statistics.mean(tutti)
        cs = [g for g in gg if g[1] == 0]
        print(f'\n=== {nome}: {len(gg)} squadra-partita, media {media:.1f} pt, '
              f'clean sheet {len(cs)/len(gg)*100:.0f}%')
        # Riferimento: 5 giocatori da 5 squadre diverse (nessuna correlazione).
        # Tutte le combo hanno lo stesso numero di slot, quindi sono
        # confrontabili fra loro e con questo.
        pool = [ss for _d, _gc, ss in gg if ss]
        rif = [sum(random.choice(random.choice(pool)) for _ in range(5))
               for _ in range(N_TRIALS)]
        soglie = [sorted(rif)[int(q * len(rif)) - 1] for q in (0.5, 0.75, 0.9)]
        print(f'  {"1+1+1+1+1":>9}: media {statistics.mean(rif):6.1f}  '
              f'dev.std {statistics.pstdev(rif):5.1f}   ' +
              ' | '.join(f'P>{s:.0f} {p_sopra(rif, s)*100:5.1f}%' for s in soglie))

        for pezzi in ((5,), (4, 1), (3, 2), (3, 1, 1), (2, 2, 1)):
            usabili = {k: [ss for _d, _gc, ss in gg if len(ss) >= k] for k in set(pezzi)}
            if any(len(v) < 20 for v in usabili.values()):
                continue
            tot = []
            for _ in range(N_TRIALS):
                s_ = 0.0
                for k in pezzi:
                    s_ += sum(random.sample(random.choice(usabili[k]), k))
                tot.append(s_)
            etichetta = '+'.join(str(x) for x in pezzi)
            print(f'  {etichetta:>9}: media {statistics.mean(tot):6.1f}  '
                  f'dev.std {statistics.pstdev(tot):5.1f}   ' +
                  ' | '.join(f'P>{s:.0f} {p_sopra(tot, s)*100:5.1f}%' for s in soglie))


if __name__ == '__main__':
    random.seed(3)
    main()
