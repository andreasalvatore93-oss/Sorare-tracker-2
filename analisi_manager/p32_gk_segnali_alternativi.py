"""GK: esaurimento dei segnali alternativi a costo zero (13/08/2026, nessuna rete).

Priorita' A di RISPOSTA_OPUS_DOVE_CERCARE_SEGNALE_2026-08-13.txt: il portiere
non ordina niente (Spearman atteso/reale ~0 su n=1932, confermato 3 volte).
Prima di aprire un nuovo filone su dati nuovi, si esauriscono i segnali GIA'
in cache (nessuna query di rete):

  - quote di vittoria squadra (favorito_odds): GIA' testato il 07/08
    (taratura_confronto_parametri.py, script pulito): GK 0/9 varianti passano
    il criterio severo. Non ripetuto qui, solo richiamato.
  - clean sheet di squadra (pcs): GIA' il miglior segnale trovato, gia' in
    produzione (GK_TEAM_CS_WEIGHT). Non ripetuto qui.
  - L10 (media ultime 10): MAI isolato prima come criterio d'ordinamento.
    Testato qui.
  - casa/trasferta: MAI isolato prima come criterio autonomo (e' gia' dentro
    l'atteso via fattore_casa_trasferta, ma non testato da solo). Testato qui.

starter_odds INDIVIDUALE (prob. di titolarita' di quel portiere) NON e'
testabile a costo zero: non esiste uno storico cachato, servirebbe raccolta
nuova nel tempo (rete). Lasciato fuori, factory esplicito nel commit.

Uso: python analisi_manager/p32_gk_segnali_alternativi.py
"""
import os
import sys
import json
import math
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p24_binario2_ga as G

cache = CACHE.CacheLocale()


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def spearman(xs, ys):
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for pos, i in enumerate(idx):
            r[i] = pos
        return r
    return corr(rank(xs), rank(ys))


def raccogli():
    rows = []
    for manager, fx, path in G.elenca_fixture():
        righe = G.carica_formazioni(path)
        pool, _escluse = G.costruisci_pool_carte(righe)
        fine_giornata = G.fine_giornata_da_slug(fx)
        primo_kickoff = G.trova_primo_kickoff(pool, fine_giornata)
        if primo_kickoff is None:
            continue
        for cid, c in pool.items():
            if c['ruolo'] != 'Goalkeeper':
                continue
            ctx = P.contesto(cache, c['slug'], 'Goalkeeper', fine_giornata, cutoff_giornata=primo_kickoff)
            if ctx is None:
                continue
            res = P.score_atteso(cache, c['slug'], 'Goalkeeper', fine_giornata, cutoff_giornata=primo_kickoff)
            if res is None or res.get('atteso') is None or res.get('l10') is None:
                continue
            reale = G.grezzo_da_archivio(c)
            if reale is None:
                continue
            rows.append({'slug': c['slug'], 'fixture': fx, 'atteso': res['atteso'],
                        'l10': res['l10'], 'casa': ctx['casa'], 'reale': reale})
    visti = {}
    for r in rows:
        k = (r['slug'], r['fixture'])
        if k not in visti:
            visti[k] = r
    return list(visti.values())


def main():
    rows = raccogli()
    print(f'n dedup: {len(rows)}')
    ys = [r['reale'] for r in rows]

    print()
    print('--- L10 come criterio d\'ordinamento ---')
    print(f"  spearman(atteso, reale): {spearman([r['atteso'] for r in rows], ys):+.4f}")
    print(f"  spearman(l10, reale):    {spearman([r['l10'] for r in rows], ys):+.4f}")

    print()
    print('--- casa/trasferta come criterio autonomo ---')
    casa = [r['reale'] for r in rows if r['casa']]
    trasf = [r['reale'] for r in rows if not r['casa']]
    print(f"  in casa:    n={len(casa)}  media={sum(casa)/len(casa):.2f}")
    print(f"  trasferta:  n={len(trasf)}  media={sum(trasf)/len(trasf):.2f}")
    print(f"  differenza: {sum(casa)/len(casa) - sum(trasf)/len(trasf):+.2f}")

    print()
    print('--- gia\' testati altrove, non ripetuti qui ---')
    print('  quote vittoria squadra (favorito_odds): GK 0/9 (07/08, BRIEF_ODDS_4RUOLI_2026-08-07.txt)')
    print('  clean sheet squadra (pcs): gia\' il migliore, gia\' in produzione (GK_TEAM_CS_WEIGHT)')
    print()
    print('--- non testabile a costo zero ---')
    print('  starter_odds individuale: nessuno storico cachato, servirebbe raccolta nel tempo (rete)')

    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'gk_segnali_alternativi_2026-08-13.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    print()
    print('salvato:', out_path)


if __name__ == '__main__':
    main()
