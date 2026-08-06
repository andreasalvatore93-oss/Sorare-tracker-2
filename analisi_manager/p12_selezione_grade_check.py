"""Ultimo controllo DEF (chat 06/08 ~17:15 Roma): distingue "rumore da
campione piccolo" da "effetto di selezione" (le righe con grade disponibile
sono proprio quelle dove score_atteso ordina peggio?).

Riusa lo STESSO campione ampio di sez.19-ter (250 slug a caso dai roster
manager, storia intera, zero query) e le STESSE giornate/pool gia'
costruiti li' -- non ne fabbrica di nuovi apposta per favorire un esito.
Per ogni riga calcola il percentile dentro il SUO pool originale (che
mischia gia' naturalmente candidati con e senza grade disponibile, cosi'
com'e' in una giornata reale), poi divide le righe in due gruppi secondo se
(slug, data) compare con un grade non nullo nel file storico_grade_<ruolo>
di Haiku, e confronta il percentile medio SEPARATAMENTE sui due gruppi.

Ripetuto su DEF e MID.
"""
import os, sys, io, json, random, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import importlib.util
spec = importlib.util.spec_from_file_location('sanity', 'analisi_manager/p12_percentile_sanity_check.py')
sanity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sanity)

random.seed(20260806)


def carica_slug_grade_disponibile(path_storico):
    """Insieme di (slug, data[:10]) con grade NON nullo nel file Haiku."""
    with open(path_storico, encoding='utf-8') as fh:
        data = json.load(fh)
    disponibili = set()
    for r in data:
        if r.get('grade') is not None and r.get('game_date'):
            disponibili.add((r['slug'], r['game_date'][:10]))
    return disponibili


def raccogli_slug_ruolo(ruolo, n_campione=250):
    slugs = set()
    for f in __import__('glob').glob('dati_globali/manager_*.json'):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for gw, righe in (d.get('giornate') or {}).items():
            for riga in righe:
                for c in riga.get('carte') or []:
                    if c.get('ruolo') == ruolo:
                        slugs.add(c['slug'])
    slugs = sorted(slugs)
    random.shuffle(slugs)
    return slugs[:n_campione], len(slugs)


def esegui(ruolo, path_storico, n_campione=250):
    print(f'\n{"="*70}\n--- {ruolo} ---')
    slugs, n_totali = raccogli_slug_ruolo(ruolo, n_campione)
    print(f'  slug campionati: {len(slugs)} (da {n_totali} distinti nei roster manager)')

    righe, n_slug_ok = sanity.costruisci_righe(slugs)
    print(f'  righe con score_atteso calcolato: {len(righe)}  slug con almeno 1 riga utile: {n_slug_ok}')

    giornate, scartate = sanity.costruisci_giornate(righe)
    print(f'  giornate valide (>=3 candidati): {len(giornate)}  scartate (pool<3): {scartate}')

    disponibili = carica_slug_grade_disponibile(path_storico)
    print(f'  coppie (slug,data) con grade disponibile nel file Haiku: {len(disponibili)}')

    # CORRETTO: non il percentile di TUTTE le righe del pool (che per
    # costruzione media sempre ~50, e' la definizione stessa di percentile,
    # test inutile) -- il percentile del giocatore SCELTO da score_atteso
    # in ciascuna giornata (argmax atteso), esattamente come in sez.19/19-ter.
    # Ogni giornata contribuisce UNA riga (la scelta), classificata "con
    # grade" se il giocatore scelto quel giorno ha grade disponibile nel
    # file Haiku, "senza grade" altrimenti.
    con_grade = []
    senza_grade = []
    for day, rr in giornate:
        scores = [r['score'] for r in rr]
        idx = max(range(len(rr)), key=lambda i: rr[i]['atteso'])
        perc = sanity.percentile_rank(scores, idx)
        scelto = rr[idx]
        key = (scelto['slug'], scelto['date'][:10])
        riga = {'slug': scelto['slug'], 'perc': perc, 'day': day}
        if key in disponibili:
            con_grade.append(riga)
        else:
            senza_grade.append(riga)

    def riassumi(gruppo, nome):
        n_righe = len(gruppo)
        n_slug = len(set(r['slug'] for r in gruppo))
        perc_medio = sum(r['perc'] for r in gruppo) / n_righe if n_righe else None
        print(f'  {nome:15s} n_giornate/righe={n_righe:4d}  n_giocatori_distinti={n_slug:4d}  percentile_medio={perc_medio}')
        return {'n_righe': n_righe, 'n_giocatori': n_slug, 'percentile_medio': perc_medio}

    out_con = riassumi(con_grade, 'CON grade')
    out_senza = riassumi(senza_grade, 'SENZA grade')

    return {'ruolo': ruolo, 'n_giornate': len(giornate), 'n_scartate': scartate,
           'con_grade': out_con, 'senza_grade': out_senza}


def main():
    risultati = {}
    risultati['Defender'] = esegui('Defender', 'analisi_manager/dati/storico_grade_Defender_20260806.json')
    risultati['Midfielder'] = esegui('Midfielder', 'analisi_manager/dati/storico_grade_Midfielder_20260806.json')

    with open('analisi_manager/p12_selezione_grade_check_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
