"""PASSO 5 (BRIEF_SONNET_PREMI_ARENE_2026-08-08): ricalcola pareggio e
guadagno/pt con i PREMI VERI (dati_globali/premi_arene_2026-08-08.json,
1.677 arene, jackpot inclusi, letti da rewardsConfig -- vedi
docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt §11) al posto dei
199/141 premi_osservati() di consiglio_arena.py (che valgono solo dove il
NOSTRO manager era arrivato fra i primi tre).

STESSO METODO del giro precedente (§5 HANDOFF_SOGLIE_DEFINITIVE):
  - archivio avversari: arene_storico_full_v2.json (2.125 arene)
  - sigma per tipo: RIUSATA dal Passo 2 precedente (non rifatta, come da
    brief): cap260 50.52 (n=1356), cap220 46.70 (n=251), Uncapped 53.72
    (n=288), Beginner 50.18 (n=1472)
  - guadagno/pt = pendenza dell'incasso medio nell'intorno del pareggio
    (+-5 punti)
SOLO MISURA. Nessun file di produzione toccato.
"""
import os
import sys
import json
import collections
import random
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ['ARCHIVIO_ARENE'] = 'dati_globali/arene_storico_full_v2.json'
import consiglio_arena as C

SIGMA_PER_TIPO = {'cap 260': 50.52, 'cap 220': 46.70, 'Uncapped': 53.72, 'Beginner': 50.18}
N_SIGMA = {'cap 260': 1356, 'cap 220': 251, 'Uncapped': 288, 'Beginner': 1472}
NORMALIZZA_TIPO = {'Cap 260': 'cap 260', 'Cap 220': 'cap 220', 'Uncapped': 'Uncapped', 'Beginner': 'Beginner'}

PRODUZIONE = {'cap 260': (259.5, 7.9), 'cap 220': (244.1, 6.3), 'Uncapped': (288.3, 8.0), 'Beginner': (None, None)}
GIRO2125_VECCHI = {'cap 260': (260.2, 6.93), 'cap 220': (243.2, 5.42), 'Uncapped': (282.4, 5.95), 'Beginner': (259.2, 2.34)}


def carica_premi_nuovi():
    """(tipo_norm, rank) -> [premio,...], da TUTTE le 1.677 arene scaricate,
    non solo dove il nostro manager era a podio. Solo CardShardRewardConfig
    (le fasce InGameCurrencyRewardConfig, oltre il 3o posto, non ci servono:
    REGOLE tiene solo la terna dei primi tre)."""
    d = json.load(open('dati_globali/premi_arene_2026-08-08.json', encoding='utf-8'))
    out = collections.defaultdict(list)
    n_arene_per_tipo = collections.Counter()
    for a in d['arene']:
        tipo_norm = NORMALIZZA_TIPO.get(a['tipo'])
        if tipo_norm is None:
            continue
        n_arene_per_tipo[tipo_norm] += 1
        for pos, q in a['premi_per_posizione']:
            if pos <= 3 and q is not None:
                out[(tipo_norm, pos)].append(q)
    return out, n_arene_per_tipo


def guadagno_per_punto(pareggio_val, avversari, premi, sigma, tipo):
    i_meno = C.incasso_medio(pareggio_val - 5, avversari, premi, sigma=sigma, tipo=tipo)
    i_piu = C.incasso_medio(pareggio_val + 5, avversari, premi, sigma=sigma, tipo=tipo)
    return (i_piu - i_meno) / 10


def main():
    premi_nuovi, n_arene_premi = carica_premi_nuovi()
    print('n arene con premi letti (fonte nuova), per tipo:', dict(n_arene_premi))
    print('n OSSERVAZIONI premio per (tipo, rank<=3):')
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner'):
        for rank in (1, 2, 3):
            print(f'  {tipo:10s} rank {rank}: n={len(premi_nuovi.get((tipo, rank), []))}')

    # monkeypatch: consiglio_arena pesca i premi osservati da qui invece
    # che da premi_osservati() (che legge rank_premiato/premio_essenze
    # dall'ARCHIVIO, n=141 utili)
    C._PREMI_OSS = premi_nuovi

    campo = C.campo_per_tipo()

    print('\n=== TABELLA A TRE COLONNE: pareggio (produzione -> giro2125-premi-vecchi -> giro2125-premi-nuovi) ===')
    risultati = {}
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner'):
        regole = C.REGOLE[tipo]
        av = campo.get(tipo) or []
        sigma = SIGMA_PER_TIPO[tipo]
        p_nuovo = C.pareggio(av, regole['costo'], regole['premi'], sigma=sigma, tipo=tipo)
        g_nuovo = guadagno_per_punto(p_nuovo, av, regole['premi'], sigma, tipo)
        p_prod, g_prod = PRODUZIONE[tipo]
        p_v2v, g_v2v = GIRO2125_VECCHI[tipo]
        n_premi_nuovi_top3 = sum(len(premi_nuovi.get((tipo, r), [])) for r in (1, 2, 3))
        risultati[tipo] = (p_nuovo, g_nuovo)
        print(f'{tipo:10s} n_arene={len(av):5d} n_premi_nuovi(rank1-3)={n_premi_nuovi_top3:5d} sigma={sigma}')
        print(f'  pareggio:    produzione={p_prod}  giro2125-vecchi={p_v2v}  giro2125-NUOVI={p_nuovo:.1f}')
        print(f'  guadagno/pt: produzione={g_prod}  giro2125-vecchi={g_v2v}  giro2125-NUOVI={g_nuovo:.2f}')

    print('\n=== SPLIT-HALF (seme 42) ===')
    rnd = random.Random(42)
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner'):
        av = list(campo.get(tipo) or [])
        rnd.shuffle(av)
        meta = len(av) // 2
        a1, a2 = av[:meta], av[meta:]
        regole = C.REGOLE[tipo]
        sigma = SIGMA_PER_TIPO[tipo]
        p1 = C.pareggio(a1, regole['costo'], regole['premi'], sigma=sigma, tipo=tipo)
        p2 = C.pareggio(a2, regole['costo'], regole['premi'], sigma=sigma, tipo=tipo)
        print(f'{tipo:10s} meta1(n={len(a1)})={p1:.1f}  meta2(n={len(a2)})={p2:.1f}  scarto={abs(p1-p2):.1f}')

    print('\n=== SENSIBILITA\' SIGMA +-10% ===')
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner'):
        av = campo.get(tipo) or []
        regole = C.REGOLE[tipo]
        sigma = SIGMA_PER_TIPO[tipo]
        p_meno = C.pareggio(av, regole['costo'], regole['premi'], sigma=sigma * 0.9, tipo=tipo)
        p_piu = C.pareggio(av, regole['costo'], regole['premi'], sigma=sigma * 1.1, tipo=tipo)
        g_meno = guadagno_per_punto(p_meno, av, regole['premi'], sigma * 0.9, tipo)
        g_piu = guadagno_per_punto(p_piu, av, regole['premi'], sigma * 1.1, tipo)
        print(f'{tipo:10s} pareggio -10%/+10%: {p_meno:.1f} / {p_piu:.1f}   '
              f'guadagno/pt -10%/+10%: {g_meno:.2f} / {g_piu:.2f}')

    with open('analisi_manager/p27_risultato.json', 'w', encoding='utf-8') as f:
        json.dump({t: {'pareggio': p, 'guadagno_pt': g} for t, (p, g) in risultati.items()},
                   f, ensure_ascii=False, indent=1)
    print('\nscritto analisi_manager/p27_risultato.json')


if __name__ == '__main__':
    main()
