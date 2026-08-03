"""
Backtest Captain Policy (04/08, seguito filone capitano)

Harness riusabile per confrontare policy di scelta capitano alternative
contro la regola attuale di produzione (`pick_captain()`: max atteso grezzo
tra i movimento, GK escluso). Riusa l'infrastruttura gia' scritta per
`backtest_arene_produzione.bilancio_stesse_carte` (P.score_atteso,
B.inizio_giornata, B.fine_giornate) invece di riscriverla -- generalizza la
logica gia' fatta (e poi cancellata) nella sessione precedente per il test
del bias di ruolo su 513 formazioni.

Fonti di formazioni REALI (stesso schema carte: slug/nome/ruolo/capitano/
punteggio), nessuna nuova query:
  - mie: dati_globali/arene_formazioni.json['formazioni'] (593 voci)
  - forever-young: dati_globali/manager_forever-young.json['giornate']
  - crowss: dati_globali/manager_crowss.json['giornate'] (mai usato prima)

Per ogni formazione valutabile: calcola l'atteso walk-forward (stessi
parametri di produzione, `P.score_atteso`) per ogni carta non-GK, poi
applica ciascuna policy e somma il bonus REALE catturato (0.2 * reale del
capitano scelto) su tutte le formazioni. Bootstrap sulle differenze
per-formazione (stesso approccio di `intervallo_media` in backtest_arene.py).

Uso: python formazione_mls/diagnostics/backtest_captain_policy.py
"""
import os
import sys
import glob
import random
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B
import backtest_arene_produzione as BP

MOLTIPLICATORE_CAPITANO = BP.MOLTIPLICATORE_CAPITANO
_RUOLO_TO_CODICE = BP._RUOLO_TO_CODICE

BIAS_RUOLO = {'DEF': -8.37, 'MID': -6.00, 'FWD': -7.37}  # gia' misurato, zona capitano


def carica(path):
    return BP.carica(path)


def _reale(g):
    p = g.get('punteggio')
    if p is None:
        return None
    return p / MOLTIPLICATORE_CAPITANO if g.get('capitano') else p


def raccogli_formazioni():
    """Ritorna lista di formazioni {fixture, giocatori, fonte}, dalle 3 fonti."""
    out = []
    mie = carica('dati_globali/arene_formazioni.json')['formazioni']
    for v in mie.values():
        if v.get('giocatori'):
            out.append({'fixture': v['fixture'], 'giocatori': v['giocatori'], 'fonte': 'mie'})

    for fonte, path in (('forever-young', 'dati_globali/manager_forever-young.json'),
                        ('crowss', 'dati_globali/manager_crowss.json')):
        d = carica(path)
        for fixture, arene in d['giornate'].items():
            for a in arene:
                carte = a.get('carte')
                if carte:
                    out.append({'fixture': fixture, 'giocatori': carte, 'fonte': fonte})
    return out


def calcola_previsioni(cache, fine, formazioni):
    """Per ogni formazione valutabile, ritorna {'candidati': [...], 'fonte':...}
    dove candidati = lista di dict {ruolo, atteso, reale, nome} per i soli
    movimento (GK escluso, la scelta GK-vs-movimento non e' in discussione
    qui -- gia' decisa e in produzione)."""
    risultati = []
    scartate_no_fd = 0
    scartate_no_pred = 0

    per_fixture_cutoff = {}
    for f in formazioni:
        fixture = f['fixture']
        fd = fine.get(fixture)
        if fd is None:
            scartate_no_fd += 1
            continue

        carte_uniche = sorted(set((g['slug'], g['ruolo']) for g in f['giocatori']))
        chiave = (fixture,) + tuple(carte_uniche)
        cutoff = per_fixture_cutoff.get(chiave)
        if cutoff is None and chiave not in per_fixture_cutoff:
            cutoff = B.inizio_giornata(cache, fd, carte_uniche)
            per_fixture_cutoff[chiave] = cutoff
        if cutoff is None:
            scartate_no_fd += 1
            continue

        candidati = []
        ok = True
        for g in f['giocatori']:
            if g['ruolo'] == 'Goalkeeper':
                continue
            r = _reale(g)
            if r is None:
                ok = False
                break
            pred = P.score_atteso(cache, g['slug'], g['ruolo'], fd, cutoff)
            if pred is None:
                ok = False
                break
            ctx = P.contesto(cache, g['slug'], g['ruolo'], fd, cutoff)
            opp_rank = ctx.get('opp_rank') if ctx else None
            candidati.append({'ruolo': _RUOLO_TO_CODICE[g['ruolo']], 'atteso': pred['atteso'],
                              'reale': r, 'nome': g['nome'], 'opp_rank': opp_rank})
        if not ok or len(candidati) < 2:
            scartate_no_pred += 1
            continue
        risultati.append({'candidati': candidati, 'fonte': f['fonte']})

    print(f"Formazioni raccolte: {len(formazioni)}  "
          f"scartate (fixture/cutoff mancante)={scartate_no_fd}  "
          f"scartate (previsione mancante)={scartate_no_pred}  "
          f"valutabili={len(risultati)}")
    return risultati


# --- POLICY ---

def policy_baseline(candidati):
    """Regola attuale di produzione: max atteso grezzo."""
    return max(candidati, key=lambda c: c['atteso'])


def policy_bias_ruolo(candidati):
    """Gia' testata (bocciata, lift ~0 su 513 formazioni): applica SEMPRE
    BIAS_RUOLO. Qui riproposta sul campione allargato (idea 3)."""
    return max(candidati, key=lambda c: c['atteso'] + BIAS_RUOLO.get(c['ruolo'], 0.0))


def make_policy_bias_margine(soglia):
    """Idea 1: applica BIAS_RUOLO solo se lo scarto fra i due migliori per
    atteso grezzo e' <= soglia (caso 'in bilico'); altrimenti baseline."""
    def policy(candidati):
        ordinati = sorted(candidati, key=lambda c: c['atteso'], reverse=True)
        if len(ordinati) < 2 or (ordinati[0]['atteso'] - ordinati[1]['atteso']) > soglia:
            return ordinati[0]
        return max(candidati, key=lambda c: c['atteso'] + BIAS_RUOLO.get(c['ruolo'], 0.0))
    policy.__name__ = f'bias_margine_{soglia}'
    return policy


def bonus_totale(risultati, policy):
    """Ritorna lista di bonus (0.2*reale del capitano scelto) per formazione."""
    return [(MOLTIPLICATORE_CAPITANO - 1.0) * policy(r['candidati'])['reale'] for r in risultati]


def intervallo_media(valori, seme=0, giri=2000):
    return B.intervallo_media(valori, seme=seme, giri=giri)


def confronta(risultati, nome, policy, base_bonus):
    bonus = bonus_totale(risultati, policy)
    diff = [b - a for b, a in zip(bonus, base_bonus)]
    tot_diff = sum(diff)
    ic = intervallo_media(diff)
    vince = sum(1 for d in diff if d > 1e-9)
    perde = sum(1 for d in diff if d < -1e-9)
    segnale = "" if ic[0] <= 0 <= ic[1] else ("  <-- IC esclude lo zero" if tot_diff > 0
                                               else "  <-- IC esclude lo zero (NEGATIVO)")
    print(f"  {nome:<28} tot diff={tot_diff:+8.2f}  media/formazione={statistics.mean(diff):+.4f}  "
          f"IC95%=[{ic[0]:+.4f}, {ic[1]:+.4f}]  vince/perde={vince}/{perde}{segnale}")


def main():
    print("Caricamento cache e formazioni reali (3 fonti)...\n")
    cache = C.CacheLocale()
    arene_storico = carica('dati_globali/arene_storico.json')['arene']
    fine = B.fine_giornate(arene_storico)

    formazioni = raccogli_formazioni()
    by_fonte = defaultdict(int)
    for f in formazioni:
        by_fonte[f['fonte']] += 1
    print("Formazioni per fonte:", dict(by_fonte))

    risultati = calcola_previsioni(cache, fine, formazioni)
    by_fonte_ok = defaultdict(int)
    for r in risultati:
        by_fonte_ok[r['fonte']] += 1
    print("Valutabili per fonte:", dict(by_fonte_ok))

    base_bonus = bonus_totale(risultati, policy_baseline)
    print(f"\nBaseline (atteso grezzo): bonus totale={sum(base_bonus):.2f}  "
          f"media/formazione={statistics.mean(base_bonus):.4f}\n")

    print("=== Idea 3: bias di ruolo SEMPRE applicato, campione allargato ===")
    confronta(risultati, 'bias_ruolo (sempre)', policy_bias_ruolo, base_bonus)

    print("\n=== Idea 1: bias di ruolo solo nei casi in bilico (grid soglie) ===")
    for soglia in (3, 5, 8, 12, 20):
        confronta(risultati, f'bias_margine<={soglia}', make_policy_bias_margine(soglia), base_bonus)

    print("\n=== Idea 4 (diagnostica): bias residuo per favorita/sfavorita, zona capitano (atteso>=55) ===")
    zona = [c for r in risultati for c in r['candidati'] if c['atteso'] >= 55 and c['opp_rank'] is not None]
    print(f"n candidati zona capitano con opp_rank noto: {len(zona)}")
    if zona:
        ranks = sorted(c['opp_rank'] for c in zona)
        n = len(ranks)
        t1, t2 = ranks[n // 3], ranks[2 * n // 3]
        # opp_rank: piu' basso = squadra avversaria piu' forte (rank 1 = migliore),
        # quindi rank BASSO = io sfavorito, rank ALTO = io favorito
        def bucket(rk):
            if rk <= t1:
                return 'SFAVORITO (avversario forte)'
            if rk <= t2:
                return 'NEUTRO'
            return 'FAVORITO (avversario debole)'
        per_bucket = defaultdict(list)
        for c in zona:
            per_bucket[bucket(c['opp_rank'])].append(c)
        for nome_b in ('SFAVORITO (avversario forte)', 'NEUTRO', 'FAVORITO (avversario debole)'):
            cs = per_bucket[nome_b]
            if not cs:
                continue
            mp = statistics.mean(c['atteso'] for c in cs)
            mr = statistics.mean(c['reale'] for c in cs)
            print(f"  {nome_b:<32} n={len(cs):>5}  atteso medio={mp:6.1f}  reale medio={mr:6.1f}  bias={mr-mp:+6.2f}")

        print("\n=== Idea 4 in policy: bonus se FAVORITO (opp_rank > terzile alto) ===")
        BONUS_FAVORITO = 2.17  # gap misurato sopra, FAVORITO vs resto

        def policy_favorita(candidati):
            def score(c):
                extra = BONUS_FAVORITO if (c.get('opp_rank') is not None and c['opp_rank'] > t2) else 0.0
                return c['atteso'] + extra
            return max(candidati, key=score)

        confronta(risultati, 'favorita (sempre)', policy_favorita, base_bonus)


if __name__ == '__main__':
    main()
