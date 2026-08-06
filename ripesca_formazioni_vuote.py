"""Ripesca le formazioni salvate SENZA carte in dati_globali/manager_*.json.

Difetto trovato il 06/08/2026: in ricostruisci_manager.py, quando formazione()
fallisce (rete, 429, errore GraphQL) la riga resta nel file senza il campo
'carte'. Nessun controllo a valle se ne accorge: il pool risulta piu' piccolo
in silenzio. Su crowss sono 133 righe su 1899, su forever-young 26 su 3373.

Non riscarica nulla di gia' presente: tocca SOLO le righe senza carte.
Le formazioni sono pubbliche, quindi niente cookie e niente budget account.

Uso:
  python ripesca_formazioni_vuote.py                      # tutti i manager
  python ripesca_formazioni_vuote.py --manager crowss     # uno solo
  python ripesca_formazioni_vuote.py --gw football-21-24-jul-2026
  python ripesca_formazioni_vuote.py --dry-run            # conta e basta
"""
import os
import sys
import json
import glob
import argparse

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

import ricostruisci_manager as R


def righe_vuote(dati, gw_filtro=None):
    """(giornata, indice, riga) di ogni riga senza carte."""
    fuori = []
    for gw, righe in (dati.get('giornate') or {}).items():
        if gw_filtro and gw != gw_filtro:
            continue
        for i, r in enumerate(righe):
            if not r.get('carte') and r.get('contender'):
                fuori.append((gw, i, r))
    return fuori


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager')
    ap.add_argument('--gw')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    schema = os.path.join(REPO_ROOT, 'dati_globali',
                          f"manager_{args.manager}.json" if args.manager else 'manager_*.json')
    files = sorted(glob.glob(schema))
    if not files:
        print(f'Nessun file per {schema}')
        return 1

    tot_vuote = tot_ok = tot_ko = 0
    for path in files:
        with open(path, encoding='utf-8') as f:
            dati = json.load(f)
        if not isinstance(dati, dict) or 'giornate' not in dati:
            continue
        vuote = righe_vuote(dati, args.gw)
        if not vuote:
            continue
        man = dati.get('manager') or os.path.basename(path)
        tot_vuote += len(vuote)
        print(f'{man}: {len(vuote)} righe senza carte')
        if args.dry_run:
            for gw, _i, r in vuote[:5]:
                print(f'    {gw}  {r.get("competizione")}  ({r.get("tipo_arena")})')
            continue

        ok = ko = 0
        for gw, i, r in vuote:
            carte, chi, piazzamento = R.formazione(r['contender'])
            if carte is None:
                ko += 1
                print(f'    FALLITA ancora: {gw} {r.get("competizione")}')
                continue
            if chi and chi != man:
                ko += 1
                print(f'    ATTENZIONE, appartiene a {chi}: {r["contender"][:50]}')
                continue
            dati['giornate'][gw][i]['carte'] = carte
            dati['giornate'][gw][i]['piazzamento'] = piazzamento
            ok += 1
        tot_ok += ok
        tot_ko += ko
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(dati, f, ensure_ascii=False, indent=1)
        print(f'  -> recuperate {ok}, ancora fallite {ko}, salvato {os.path.basename(path)}')

    print(f'\nTOTALE righe senza carte: {tot_vuote}')
    if not args.dry_run:
        print(f'TOTALE recuperate: {tot_ok}   ancora fallite: {tot_ko}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
