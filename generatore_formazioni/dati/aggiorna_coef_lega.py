# -*- coding: utf-8 -*-
"""Ricostruisce coef_lega.json: quanto rende un giocatore in ogni campionato.

PERCHE' (14/08/2026, richiesta dell'utente -- caso Vicente/Martin, promossi
dalla Segunda alla Liga). Un giocatore appena arrivato da un altro campionato
ha uno storico tarato sul campionato VECCHIO: il modello lo prevede come se
giocasse ancora li'. Fino a oggi c'era solo un badge cosmetico ("nuovo
campionato"), nessuna correzione.

COME SI MISURA (e i due modi sbagliati di farlo, entrambi provati e scartati).
Non si confrontano le medie dei campionati: in Liga giocano i piu' forti, si
misurerebbe la qualita' della gente e non la durezza del torneo. Si guardano
i giocatori che si sono TRASFERITI, prima e dopo: la loro bravura si semplifica
nel confronto.

  SBAGLIATO 1 -- usare tutte le partite. La media su TUTTI i passaggi viene
  +7,55 invece di ~0: impossibile per un effetto di lega (per ogni salita c'e'
  una discesa). Causa: chi scende va a giocare titolare, chi sale finisce in
  panchina. Confrontando solo TITOLARE->TITOLARE (>=60 minuti) la media su
  tutti i passaggi diventa +0,14 e il salto di categoria passa da ~16 punti a
  5-10. Gli 8-10 punti di differenza sono "gioca meno", che il modello sa gia'
  dalle starter odds: contarli qui li conterebbe DUE volte.

  SBAGLIATO 2 -- misurare la regressione verso la media come
  (media_dopo - media_prima) contro (media_prima). Esce una discesa anche
  quando non c'e', per artificio. Qui il livello si misura su META' delle
  partite di prima e la variazione sull'altra meta', e c'e' un gruppo di
  controllo (chi NON ha cambiato lega): la sua pendenza e' -0,011, cioe' chi
  resta non regredisce affatto. Quella di chi sale e' -0,097: la perdita e'
  causata dal salto, ed e' proporzionale a quanto eri sopra la media.

COSA PRODUCE
  coef_lega          punti per campionato (negativo = ci si segna meno)
  coppie_dirette     stima diretta A<->B dove ci sono almeno 8 trasferiti per
                     verso: piu' affidabile della stima in catena, che sulla
                     Spagna sottostimava (-2,7 contro -5,0 diretto)
  pendenza_sale / pendenza_resta / livello_medio   per il termine da outlier
  scala              0,75, il valore che massimizza MAE e correlazione sul
                     banco ufficiale (e coerente col +0,65 stimato fuori
                     campione, due strade indipendenti)

NON serve rilanciarlo ogni giornata: i coefficienti si muovono con i mercati,
non con le partite. Un giro ogni tanto (o dopo una finestra di trasferimenti)
basta e avanza. La parte che cambia ogni giornata -- quanto storico ha ancora
nella lega vecchia -- e' calcolata dal vivo dal generatore, non da qui.

Uso: python generatore_formazioni/dati/aggiorna_coef_lega.py
Zero query di rete: legge solo le cache game-log gia' in repo.
"""
import os
import sys
import json
import collections
import statistics

_QUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_QUI))
sys.path.insert(0, os.path.join(ROOT, 'generatore_formazioni'))
os.chdir(ROOT)

import build_formazione_globale as B  # noqa: E402

OUT = os.path.join(_QUI, 'coef_lega.json')

MIN_PARTITE = 5      # partite da titolare per considerare "vissuta" una lega
TRANSIZIONE = 2      # partite scartate a cavallo del trasferimento
MIN_MINUTI = 60      # sotto, non e' un confronto fra ruoli paragonabili
LAMBDA = 8.0         # tiratura verso lo zero per le leghe con poco materiale
MIN_COPPIA = 8       # trasferiti per verso per fidarsi della stima diretta
SCALA = 0.75         # dal banco ufficiale, vedi docstring


def _cache_dirs():
    for root, _dirs, files in os.walk('.'):
        if root.endswith('.game_log_cache') and 'formazione_' in root:
            yield root, files


def leggi_storico():
    """slug -> {lega: [(data, punteggio, titolare)]} dalle cache condivise."""
    ld = B._league_dir_map()
    fuori = {}
    for root, files in _cache_dirs():
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            slug = fn[:-len('_gamelog.json')]
            if slug in fuori:
                continue
            try:
                with open(os.path.join(root, fn), encoding='utf-8') as fh:
                    log = json.load(fh)
            except Exception:
                continue
            per = collections.defaultdict(list)
            for riga in log.values():
                g = riga.get('anyGame') or {}
                data = (g.get('date') or '')[:10]
                sc = riga.get('score')
                if len(data) != 10 or sc is None:
                    continue
                cart = ld.get(((g.get('competition') or {}).get('slug')) or '')
                if cart is None:
                    continue          # coppa/continentale: non dice nulla
                st = riga.get('anyPlayerGameStats') or {}
                tit = (int(st.get('gameStarted') or 0) == 1
                       and int(st.get('minsPlayed') or 0) >= MIN_MINUTI)
                per[B._cartella_lega(cart)].append((data, float(sc), tit))
            if per:
                fuori[slug] = dict(per)
    return fuori


def _blocchi(legs, minimo=MIN_PARTITE):
    """[(lega, [punteggi da titolare in ordine di data])], in ordine di tempo."""
    vv = []
    for lega, partite in legs.items():
        f = sorted((d, s) for d, s, tit in partite if tit)
        if len(f) >= minimo:
            vv.append((lega, f))
    vv.sort(key=lambda x: x[1][len(x[1]) // 2][0])
    return vv


def passaggi(storico, minimo=MIN_PARTITE):
    """(lega_da, lega_a, differenza, peso, meta_prima_a, meta_prima_b, dopo)."""
    fuori = []
    for _slug, legs in storico.items():
        vv = _blocchi(legs, minimo)
        for (la, ma), (lb, mb) in zip(vv, vv[1:]):
            a = [s for _d, s in (ma[:-TRANSIZIONE] if len(ma) > minimo + TRANSIZIONE else ma)]
            b = [s for _d, s in (mb[TRANSIZIONE:] if len(mb) > minimo + TRANSIZIONE else mb)]
            if len(a) < minimo or len(b) < minimo:
                continue
            fuori.append((la, lb, statistics.mean(b) - statistics.mean(a),
                          len(a) * len(b) / (len(a) + len(b)),
                          statistics.mean(a[0::2]), statistics.mean(a[1::2]),
                          statistics.mean(b)))
    return fuori


def coefficienti(pas, lam=LAMBDA):
    """Un numero per campionato, stimato su TUTTI i passaggi insieme: cosi'
    due leghe senza trasferiti diretti si agganciano in catena. Il termine
    `lam` tira verso zero chi ha poco materiale, invece di fidarsi di tre
    giocatori."""
    leghe = sorted({l for p in pas for l in p[:2]})
    idx = {l: i for i, l in enumerate(leghe)}
    n = len(leghe)
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    for la, lb, dd, w, *_ in pas:
        i, j = idx[la], idx[lb]
        A[i][i] += w
        A[j][j] += w
        A[i][j] -= w
        A[j][i] -= w
        b[i] -= w * dd
        b[j] += w * dd
    for i in range(n):
        A[i][i] += lam
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]
    media = sum(x) / n
    return {l: round(x[idx[l]] - media, 3) for l in leghe}


def _pendenza(righe):
    X = [a for a, _b, _c in righe]
    Y = [c - b for _a, b, c in righe]
    mx, my = statistics.mean(X), statistics.mean(Y)
    sx = statistics.pstdev(X)
    cov = sum((a - mx) * (b - my) for a, b in zip(X, Y)) / len(X)
    return cov / (sx * sx), mx


def pendenze(storico, coef):
    """Quanto pesa essere sopra la media, per chi SALE e per chi RESTA."""
    su, fermi = [], []
    for _slug, legs in storico.items():
        vv = _blocchi(legs, 6)
        for (la, ma), (lb, mb) in zip(vv, vv[1:]):
            a = [s for _d, s in (ma[:-TRANSIZIONE] if len(ma) > 6 + TRANSIZIONE else ma)]
            b = [s for _d, s in (mb[TRANSIZIONE:] if len(mb) > 6 + TRANSIZIONE else mb)]
            if len(a) < 6 or len(b) < 6:
                continue
            if coef.get(lb, 0.0) - coef.get(la, 0.0) < -1.5:
                su.append((statistics.mean(a[0::2]), statistics.mean(a[1::2]),
                           statistics.mean(b)))
        for _lega, f in vv:
            if len(f) < 2 * 6 + TRANSIZIONE:
                continue
            h = len(f) // 2
            a = [s for _d, s in f[:h]][:-TRANSIZIONE]
            b = [s for _d, s in f[h + TRANSIZIONE:]]
            if len(a) < 6 or len(b) < 6:
                continue
            fermi.append((statistics.mean(a[0::2]), statistics.mean(a[1::2]),
                          statistics.mean(b)))
    ps, livello = _pendenza(su)
    pf, _ = _pendenza(fermi)
    return ps, pf, livello, len(su), len(fermi)


def coppie_dirette(pas):
    """A->B stimato solo sui suoi trasferiti, nei due versi, quando ce n'e'
    abbastanza. La parte simmetrica ((andata+ritorno)/2, che sarebbe il
    "chiunque si muove migliora") si cancella: resta il solo effetto di lega."""
    per = collections.defaultdict(list)
    for la, lb, dd, *_ in pas:
        per[(la, lb)].append(dd)
    fuori = {}
    for (la, lb), v in per.items():
        w = per.get((lb, la))
        if not w or len(v) < MIN_COPPIA or len(w) < MIN_COPPIA:
            continue
        fuori[f'{la}|{lb}'] = round((statistics.mean(v) - statistics.mean(w)) / 2, 3)
    return fuori


def main():
    storico = leggi_storico()
    print(f"giocatori con storico di lega: {len(storico)}")
    pas = passaggi(storico)
    print(f"passaggi titolare->titolare usabili: {len(pas)}")
    media_tutti = statistics.mean(p[2] for p in pas)
    print(f"CONTROLLO media su TUTTI i passaggi: {media_tutti:+.2f} "
          f"(dev'essere vicina a zero: per ogni salita c'e' una discesa; "
          f"con tutte le partite invece delle sole da titolare veniva +7,55)")
    if abs(media_tutti) > 2.0:
        print("  ATTENZIONE: lontana da zero. Il filtro titolare->titolare non "
              "sta ripulendo il minutaggio: NON usare questa tabella.")

    coef = coefficienti(pas)
    dirette = coppie_dirette(pas)
    ps, pf, livello, n_su, n_fermi = pendenze(storico, coef)
    tocca = collections.Counter()
    for la, lb, *_ in pas:
        tocca[la] += 1
        tocca[lb] += 1

    print(f"\npendenza chi SALE {ps:+.3f} (n={n_su}) | chi RESTA {pf:+.3f} "
          f"(n={n_fermi}) | livello medio {livello:.1f}")
    print(f"coppie con stima diretta: {len(dirette)}")
    print(f"\n{'campionato':<15}{'coeff':>8}{'passaggi':>10}")
    for lega, c in sorted(coef.items(), key=lambda kv: kv[1]):
        print(f"{lega:<15}{c:>+8.2f}{tocca[lega]:>10}")

    dati = {
        'coef_lega': coef,
        'coppie_dirette': dirette,
        'passaggi_per_lega': dict(tocca),
        'pendenza_sale': round(ps, 4),
        'pendenza_resta': round(pf, 4),
        'livello_medio': round(livello, 2),
        'scala': SCALA,
        'meta': {
            'passaggi': len(pas),
            'giocatori': len(storico),
            'media_controllo': round(media_tutti, 3),
            'min_partite': MIN_PARTITE,
            'min_minuti': MIN_MINUTI,
            'transizione': TRANSIZIONE,
            'lambda': LAMBDA,
            'min_coppia': MIN_COPPIA,
        },
    }
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(dati, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\nsalvato: {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
