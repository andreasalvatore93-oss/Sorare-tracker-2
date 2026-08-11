"""LEAKAGE GRADE: confronto DIRETTO pre-partita vs post-partita, zero query.

Il test diretto (HANDOFF_LETTERA_GRADE_2026-08-06.txt righe 645-670) non fu mai
completato perche' il 06/08 le partite non erano finite. Oggi si chiude senza
toccare la rete: gli snapshot PRE-partita sono in repo
(analisi_manager/dati/grade_snapshot_*.json, catturati prima del kickoff) e il
grade POST-partita e' gia' stato raccolto nell'indice storico
(analisi_manager/dati/storico_grade_*.json, rotta anyPlayer.playerGameScores).

Tre domande, in ordine:
  1. il grade cambia fra prima e dopo la partita? (quante righe, in che verso)
  2. il cambiamento e' correlato al PUNTEGGIO realizzato? (questo e' il
     leakage vero: se il voto si riscrive verso il risultato, ogni backtest
     che usa il grade storico e' gonfiato)
  3. quanto vale il grade POST rispetto al grade PRE come ordinatore del
     punteggio? La differenza fra i due e' la misura del leakage.

Dedup obbligatorio: le 5 catture del 4-7 ago contengono quasi gli stessi
giocatori. L'unita' e' (slug, data partita), non la riga di file.

Uso: python analisi_manager/p31_leakage_grade_pre_post.py
"""
import os
import sys
import io
import json
import glob
import math
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}


def carica_pre():
    """(slug, data) -> grade dell'ULTIMA cattura pre-partita disponibile."""
    pre = {}
    for f in sorted(glob.glob('analisi_manager/dati/grade_snapshot_*.json')):
        for r in json.load(open(f, encoding='utf-8')):
            g = r.get('grade')
            d = (r.get('game_date') or '')[:10]
            if g and d and r.get('slug'):
                pre[(r['slug'], d)] = {'grade': g, 'nome': r.get('nome'),
                                       'ruolo': r.get('ruolo'), 'file': os.path.basename(f),
                                       'odds': r.get('starter_odds_bp')}
    return pre


def carica_post():
    """(slug, data) -> grade letto DOPO la partita dalla rotta storica."""
    post = {}
    for f in glob.glob('analisi_manager/dati/storico_grade_*.json'):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, list):
            continue
        for r in d:
            if isinstance(r, dict) and r.get('slug') and r.get('game_date') and r.get('grade'):
                post[(r['slug'], r['game_date'][:10])] = r['grade']
    return post


def carica_punteggi():
    """(slug, data) -> (score, scoreStatus, minuti) dalla cache game-log condivisa."""
    sc = {}
    for root, dirs, files in os.walk('.'):
        if not root.endswith('.game_log_cache'):
            continue
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            slug = fn[:-len('_gamelog.json')]
            try:
                d = json.load(open(os.path.join(root, fn), encoding='utf-8'))
            except Exception:
                continue
            for v in (d or {}).values():
                g = (v or {}).get('anyGame') or {}
                data = (g.get('date') or '')[:10]
                if not data:
                    continue
                st = (v.get('anyPlayerGameStats') or {})
                sc[(slug, data)] = (v.get('score'), v.get('scoreStatus'), st.get('minsPlayed'))
    return sc


def spear(coppie):
    n = len(coppie)
    if n < 3:
        return None
    def rank(vals):
        order = sorted(range(n), key=lambda i: vals[i]); rk = [0]*n; i = 0
        while i < n:
            j = i
            while j+1 < n and vals[order[j+1]] == vals[order[i]]: j += 1
            avg = (i+j)/2 + 1
            for t in range(i, j+1): rk[order[t]] = avg
            i = j+1
        return rk
    a = rank([c[0] for c in coppie]); b = rank([c[1] for c in coppie])
    ma = sum(a)/n; mb = sum(b)/n
    sab = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    saa = sum((x-ma)**2 for x in a); sbb = sum((y-mb)**2 for y in b)
    if saa == 0 or sbb == 0:
        return None
    return sab/math.sqrt(saa*sbb)


def main():
    pre, post, punti = carica_pre(), carica_post(), carica_punteggi()
    print(f'PRE  (slug,data) distinti: {len(pre)}')
    print(f'POST (slug,data) distinti: {len(post)}')
    print(f'punteggi in cache game-log: {len(punti)}')

    comuni = sorted(set(pre) & set(post))
    print(f'\n--- 1. IL GRADE CAMBIA? --- unita\' confrontabili (dedup): {len(comuni)}')
    uguali = [k for k in comuni if pre[k]['grade'] == post[k]]
    print(f'  identici {len(uguali)}  diversi {len(comuni)-len(uguali)}  '
          f'({(len(comuni)-len(uguali))/max(len(comuni),1):.1%} riscritti)')
    mat = collections.Counter((pre[k]['grade'], post[k]) for k in comuni)
    print('  matrice pre -> post (solo le celle fuori diagonale, >=3 casi):')
    for (a, b), n in mat.most_common():
        if a != b and n >= 3:
            print(f'    {a} -> {b}: {n}')

    con_punti = [k for k in comuni if k in punti and punti[k][0] is not None]
    print(f'\n--- 2. IL CAMBIAMENTO SEGUE IL RISULTATO? --- con punteggio: {len(con_punti)}')
    if not con_punti:
        print('  nessuna unita con punteggio: impossibile rispondere')
        return
    gioc = [k for k in con_punti if (punti[k][2] or 0) > 0]
    dnp = [k for k in con_punti if not (punti[k][2] or 0) > 0]
    print(f'  di cui hanno giocato: {len(gioc)}   non giocanti (DNP): {len(dnp)}')

    for nome, ins in (('TUTTI', con_punti), ('SOLO CHI HA GIOCATO', gioc)):
        if len(ins) < 3:
            continue
        sp_pre = spear([(GRADE_NUM[pre[k]['grade']], punti[k][0]) for k in ins])
        sp_post = spear([(GRADE_NUM[post[k]], punti[k][0]) for k in ins])
        delta = [(GRADE_NUM[post[k]] - GRADE_NUM[pre[k]['grade']], punti[k][0]) for k in ins]
        sp_delta = spear(delta)
        print(f'  [{nome}] n={len(ins)}')
        print(f'    grade PRE  vs punteggio: Spearman {sp_pre:+.3f}' if sp_pre is not None else '    n/d')
        print(f'    grade POST vs punteggio: Spearman {sp_post:+.3f}' if sp_post is not None else '    n/d')
        print(f'    (POST-PRE) vs punteggio: Spearman {sp_delta:+.3f}' if sp_delta is not None else '    n/d')
        su = [d for d, _ in delta if d > 0]; giu = [d for d, _ in delta if d < 0]
        m_su = sum(punti[k][0] for k, (d, _) in zip(ins, delta) if d > 0)/len(su) if su else float('nan')
        m_giu = sum(punti[k][0] for k, (d, _) in zip(ins, delta) if d < 0)/len(giu) if giu else float('nan')
        m_ug = ([punti[k][0] for k, (d, _) in zip(ins, delta) if d == 0])
        print(f'    punteggio medio di chi e stato ALZATO  ({len(su)}): {m_su:.1f}')
        print(f'    punteggio medio di chi e rimasto UGUALE ({len(m_ug)}): '
              f'{sum(m_ug)/len(m_ug):.1f}' if m_ug else '    (nessuno)')
        print(f'    punteggio medio di chi e stato ABBASSATO ({len(giu)}): {m_giu:.1f}')


if __name__ == '__main__':
    main()
