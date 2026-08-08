"""PASSO 1 (BRIEF_SONNET_SOGLIE_ARCHIVIO_NUOVO_2026-08-09): unisce
dati_globali/classifiche_arene_2026-08-08.json (1.677 arene, classifica
completa scaricata) con dati_globali/arene_storico_full.json (673 arene da
p11_pool, giro precedente), dedup sullo slug, e scrive
dati_globali/arene_storico_full_v2.json nel formato che consiglio_arena.py
si aspetta. NON sovrascrive nessuno dei due archivi esistenti.
"""
import os
import sys
import json
import glob
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'generatore_formazioni'))
import build_formazione_globale as bfg

TIPO_BFG_DI = {'Cap 260': 'ARENA_ALLSTARS_260', 'Cap 220': 'ARENA_ALLSTARS_220',
               'Uncapped': 'ARENA_ALLSTARS_UNCAPPED', 'Beginner': None}
# Beginner non ha una chiave in COSTO_INGRESSO del generatore (non e' un tipo
# generabile, vedi HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt sez.6, 4b): costo
# dichiarato dall'utente (consiglio_arena.REGOLE), 100.
COSTO_BEGINNER = 100

# normalizza 'Cap 260'/'Cap 220' (nuovo file) -> 'cap 260'/'cap 220' (chiavi
# di consiglio_arena.REGOLE, stesse dell'archivio vecchio). Uncapped/Beginner
# restano capitalizzate in entrambi i file.
NORMALIZZA_TIPO = {'Cap 260': 'cap 260', 'Cap 220': 'cap 220',
                    'Uncapped': 'Uncapped', 'Beginner': 'Beginner'}


def costo_per_tipo(tipo_norm):
    tipo_bfg = TIPO_BFG_DI.get({'cap 260': 'Cap 260', 'cap 220': 'Cap 220',
                                 'Uncapped': 'Uncapped', 'Beginner': 'Beginner'}[tipo_norm])
    if tipo_bfg is None:
        return COSTO_BEGINNER
    return bfg.COSTO_INGRESSO[tipo_bfg]


def carica_mio_score():
    """slug leaderboard -> (mio_score, mio_rank) dai file manager. Se piu' di
    un nostro manager era nella stessa arena, prende il primo trovato
    (dichiarato, non serve un criterio speciale: serve solo per togliersi dal
    campo avversario)."""
    out = {}
    for f in glob.glob('dati_globali/manager_*.json'):
        d = json.load(open(f, encoding='utf-8'))
        if 'giornate' not in d:
            continue
        for gw, righe in d['giornate'].items():
            for r in righe:
                slug = r.get('leaderboard')
                carte = r.get('carte')
                if not slug or not carte:
                    continue
                tot = sum(c.get('punteggio') or 0 for c in carte)
                if slug not in out:
                    out[slug] = (round(tot, 2), None)
    return out


def main():
    nuovo = json.load(open('dati_globali/classifiche_arene_2026-08-08.json', encoding='utf-8'))
    vecchio = json.load(open('dati_globali/arene_storico_full.json', encoding='utf-8'))

    mio_score_map = carica_mio_score()
    n_con_mio_score = 0
    n_senza_mio_score = 0

    arene_nuovo = {}
    for a in nuovo['arene']:
        tipo_norm = NORMALIZZA_TIPO.get(a['tipo'])
        if tipo_norm is None:
            continue
        punteggi = a.get('punteggi') or []
        if len(punteggi) < 5:
            continue
        mio = mio_score_map.get(a['slug'])
        mio_score = mio[0] if mio else None
        if mio_score is not None:
            n_con_mio_score += 1
        else:
            n_senza_mio_score += 1
        mio_rank = None
        if mio_score is not None:
            ordinati = sorted(punteggi, reverse=True)
            for i, p in enumerate(ordinati, 1):
                if abs(p - mio_score) <= 0.5:
                    mio_rank = i
                    break
        rank_premiati = a.get('rank_premiati') or {}
        rank_premiato, premio_essenze = None, None
        if rank_premiati:
            # rank_premiati e' un dict {"1": premio, ...}: prendo il piu' basso
            # (il premio del NOSTRO manager, se mio_rank e' fra i premiati)
            if mio_rank is not None and str(mio_rank) in rank_premiati:
                rank_premiato, premio_essenze = mio_rank, rank_premiati[str(mio_rank)]
        arene_nuovo[a['slug']] = {
            'slug': a['slug'], 'tipo': tipo_norm, 'costo': costo_per_tipo(tipo_norm),
            'partecipanti': a.get('partecipanti'), 'punteggi': punteggi,
            'mio_score': mio_score, 'mio_rank': mio_rank,
            'premio_essenze': premio_essenze, 'rank_premiato': rank_premiato,
        }

    print(f"mio_score: presente in {n_con_mio_score} arene, assente in {n_senza_mio_score}")

    n_premio_per_tipo = collections.Counter(
        a['tipo'] for a in arene_nuovo.values() if a.get('rank_premiato') and a.get('premio_essenze'))
    print(f"arene con premio osservato (file nuovo): {dict(n_premio_per_tipo)}")

    # merge, dedup su slug: se un'arena e' in entrambi, tiene la VECCHIA
    # (p11_pool) perche' ha il premio reale incassato (rank_premiato/
    # premio_essenze dal nostro manager, piu' affidabile del rank_premiati
    # ricostruito sopra che vale solo se il nostro manager era fra i premiati)
    # BUG FIXATO 09/08/2026 (HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt §11-12):
    # il file vecchio ha 61 slug duplicati al suo interno (stessa arena,
    # righe diverse per manager diversi). Prima si teneva indiscriminatamente
    # l'ULTIMA riga per slug, perdendo il premio in 36 casi su 61 (235->199).
    # Ora si tiene la riga CON il premio quando c'e' un duplicato.
    fonte = collections.Counter()
    finale = {}
    for a in vecchio['arene']:
        slug = a['slug']
        precedente = finale.get(slug)
        if precedente is not None and precedente.get('rank_premiato') and precedente.get('premio_essenze') \
                and not (a.get('rank_premiato') and a.get('premio_essenze')):
            continue  # la riga precedente aveva il premio, questa no: la teniamo
        finale[slug] = a
        fonte['vecchio (p11_pool)'] += 1
    aggiunte_nuovo = 0
    for slug, a in arene_nuovo.items():
        if slug not in finale:
            finale[slug] = a
            aggiunte_nuovo += 1
            fonte['nuovo (classifiche)'] += 1

    print(f"totale finale: {len(finale)}  (da vecchio: {len(vecchio['arene'])}, "
          f"aggiunte dal nuovo: {aggiunte_nuovo})")
    per_tipo = collections.Counter(a['tipo'] for a in finale.values())
    print(f"per tipo: {dict(per_tipo)}")

    out = {'aggiornato': 'p25_archivio_v2.py: unione arene_storico_full.json (673, p11_pool) '
                          '+ classifiche_arene_2026-08-08.json (1677, download diretto), dedup su slug',
           'arene': list(finale.values())}
    json.dump(out, open('dati_globali/arene_storico_full_v2.json', 'w', encoding='utf-8'),
               ensure_ascii=False, indent=1)
    print("scritto dati_globali/arene_storico_full_v2.json")


if __name__ == '__main__':
    main()
