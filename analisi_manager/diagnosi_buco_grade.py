"""BRIEF_SONNET_PERCHE_MANCA_LETTERA_2026-08-09: diagnosi a rete spenta del
perche' la maggior parte delle carte utente non ha il grade in produzione.
Legge SOLO file gia' su disco (player_card_counts.json + consiglio_*.txt),
zero query, nessuna modifica alla produzione.
"""
import json, glob, os, re, io, sys

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROLE_ALIASES = {
    'gk': 'Goalkeeper', 'def': 'Defender', 'mid': 'Midfielder', 'fwd': 'Forward',
}


def find_consiglio_slugs(lega, ruolo_alias):
    """Cerca il consiglio_*.txt piu' recente di formazione_<lega>/output/<lega>_<ruolo>_all/
    ed estrae gli slug citati (righe 'N) slug: XX pt')."""
    pattern = os.path.join(f'formazione_{lega}', 'output', f'{lega}_{ruolo_alias}_all', 'consiglio_*.txt')
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        return None, set()
    path = files[0]
    slugs = set()
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            m = re.match(r'\s*\d+\)\s*([a-z0-9\-]+):', line)
            if m:
                slugs.add(m.group(1))
    return path, slugs


def main():
    pattern = os.path.join('formazione_*', 'output', '*_discovery', 'player_card_counts.json')
    files = sorted(glob.glob(pattern))
    print(f'File player_card_counts.json trovati: {len(files)}')

    tabella = []
    dettaglio_esempio = None
    tot_carte = tot_odds = tot_grade = 0
    n_gruppi_con_ge2 = 0
    carte_ge2 = 0
    carte_con_grade_ge2 = 0
    gruppi_inerti = 0
    carte_in_gruppi_inerti = 0
    tot_senza_grade_ma_con_partita = 0
    tot_senza_grade = 0
    consiglio_non_trovato = 0

    for path in files:
        parts = path.replace('\\', '/').split('/')
        # formazione_<lega>/output/<lega>_<ruolo>_discovery/player_card_counts.json
        lega_dir = parts[0]
        lega = lega_dir[len('formazione_'):]
        disc_dir = parts[2]
        ruolo_alias = disc_dir[len(lega) + 1:-len('_discovery')]
        try:
            with open(path, encoding='utf-8') as fh:
                counts = json.load(fh)
        except Exception as e:
            print(f'ERRORE lettura {path}: {e}')
            continue
        n_tot = len(counts)
        if n_tot == 0:
            continue
        n_odds = sum(1 for v in counts.values() if v.get('starter_odds') is not None)
        n_grade = sum(1 for v in counts.values() if v.get('grade'))
        slugs_senza_grade = [s for s, v in counts.items() if not v.get('grade')]

        tot_carte += n_tot
        tot_odds += n_odds
        tot_grade += n_grade

        riga = {
            'lega': lega, 'ruolo': ruolo_alias, 'n_carte': n_tot,
            'n_odds': n_odds, 'n_grade': n_grade,
            'senza_grade': slugs_senza_grade,
        }

        if n_tot >= 2:
            n_gruppi_con_ge2 += 1
            carte_ge2 += n_tot
            carte_con_grade_ge2 += n_grade
            if n_grade < 2:
                gruppi_inerti += 1
                carte_in_gruppi_inerti += n_tot

        # incrocio col consiglio per gli slug senza grade
        cons_path, cons_slugs = find_consiglio_slugs(lega, ruolo_alias)
        riga['consiglio_path'] = cons_path
        if cons_path is None:
            consiglio_non_trovato += 1
            riga['senza_grade_con_partita'] = None
        else:
            con_partita = [s for s in slugs_senza_grade if s in cons_slugs]
            riga['senza_grade_con_partita'] = len(con_partita)
            riga['senza_grade_senza_partita'] = len(slugs_senza_grade) - len(con_partita)
            tot_senza_grade_ma_con_partita += len(con_partita)
        tot_senza_grade += len(slugs_senza_grade)

        tabella.append(riga)
        if lega == 'mls' and ruolo_alias == 'mid':
            dettaglio_esempio = (path, counts, cons_path, cons_slugs)

    print(f'\n=== TOTALI GREZZI (tutti i gruppi lega/ruolo con almeno 1 carta) ===')
    print(f'gruppi: {len(tabella)}  carte: {tot_carte}  con odds: {tot_odds}  con grade: {tot_grade} ({100*tot_grade/tot_carte:.1f}%)')

    print(f'\n=== RISCONTRO NUMERI DEL BRIEF (soglia >=2 carte per gruppo) ===')
    print(f'gruppi con >=2 carte: {n_gruppi_con_ge2} (brief: 41)')
    print(f'carte in quei gruppi: {carte_ge2} (brief: 243)')
    print(f'di cui con grade: {carte_con_grade_ge2} ({100*carte_con_grade_ge2/carte_ge2:.1f}%, brief: 82 = 33.7%)')
    print(f'gruppi inerti (grade<2 su quelli con >=2 carte): {gruppi_inerti} (brief: 20)')
    print(f'carte in gruppi inerti: {carte_in_gruppi_inerti} (brief: 104)')

    print(f'\n=== INCROCIO CON I CONSIGLIO_*.txt (partita in finestra?) ===')
    print(f'gruppi senza un consiglio_*.txt trovato: {consiglio_non_trovato} su {len(tabella)}')
    print(f'carte totali senza grade: {tot_senza_grade}')
    print(f'di cui compaiono nel consiglio (partita in finestra, ipotesi b ESCLUSA): {tot_senza_grade_ma_con_partita}')

    if dettaglio_esempio:
        path, counts, cons_path, cons_slugs = dettaglio_esempio
        print(f'\n=== DUMP DI ESEMPIO: {path} ===')
        print(f'consiglio usato per incrocio: {cons_path}')
        for slug, v in counts.items():
            in_cons = slug in cons_slugs
            print(f"  {slug:35s} odds={v.get('starter_odds')!r:6} grade={v.get('grade')!r:5} nel_consiglio={in_cons}")

    print(f'\n=== TABELLA PER LEGA/RUOLO (solo gruppi con almeno 1 carta senza grade) ===')
    for r in sorted(tabella, key=lambda x: (-len(x['senza_grade']), x['lega'], x['ruolo'])):
        if not r['senza_grade']:
            continue
        cp = r.get('senza_grade_con_partita')
        print(f"  {r['lega']:16s} {r['ruolo']:4s} carte={r['n_carte']:3d} odds={r['n_odds']:3d} "
              f"grade={r['n_grade']:3d} senza_grade={len(r['senza_grade']):3d} "
              f"(con_partita={cp})")

    with open('analisi_manager/dati/diagnosi_buco_grade_20260809.json', 'w', encoding='utf-8') as fh:
        json.dump({
            'totali': {'gruppi': len(tabella), 'carte': tot_carte, 'con_odds': tot_odds, 'con_grade': tot_grade},
            'riscontro_brief': {
                'gruppi_ge2': n_gruppi_con_ge2, 'carte_ge2': carte_ge2,
                'carte_con_grade_ge2': carte_con_grade_ge2,
                'gruppi_inerti': gruppi_inerti, 'carte_in_gruppi_inerti': carte_in_gruppi_inerti,
            },
            'incrocio_consiglio': {
                'gruppi_senza_consiglio': consiglio_non_trovato,
                'tot_senza_grade': tot_senza_grade,
                'tot_senza_grade_con_partita': tot_senza_grade_ma_con_partita,
            },
            'tabella': tabella,
        }, fh, ensure_ascii=False, indent=1)
    print('\nSalvato analisi_manager/dati/diagnosi_buco_grade_20260809.json')


if __name__ == '__main__':
    main()
