"""Genera le formazioni con la configurazione di produzione e ne scrive slug e
punteggio in un JSON, per confrontare DUE VERSIONI DEL CODICE fra loro.

Serve quando la modifica da valutare non e' un solo numero (che si potrebbe
spegnere con un monkeypatch, come fa check_synergy_selection_impact.py) ma un
pezzo di logica: si lancia questo script sulla versione nuova, si torna alla
vecchia con git e lo si rilancia, poi si confrontano i due JSON. Cosi' il
confronto passa dal generatore VERO, non da una sua imitazione.

Uso:  python formazione_mls/diagnostics/dump_formazioni_per_confronto.py out.json
"""
import importlib
import json
import os
import sys

os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '4')
os.environ.setdefault('ARENA_ALLSTARS_220', '4')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '2')
os.environ.setdefault('ALLSTARS', '4')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('IN_SEASON', 'mls:6,kleague:6')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

TIPI = (('ARENA_ALLSTARS_260', 4), ('ARENA_ALLSTARS_220', 4),
        ('ARENA_ALLSTARS_UNCAPPED', 2), ('ALLSTARS', 4),
        ('MLS_IN_SEASON', 6), ('KLEAGUE_IN_SEASON', 6))


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else 'formazioni_dump.json'
    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff

    role_data, role_counts, player_names = g.load_league_role_data()
    role_data = g.filter_by_window(role_data)
    pools = g.build_quality_pools(role_data)
    merged_counts = {}
    for role in g.ROLES:
        acc = {}
        for lg in g.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged_counts[role] = acc

    out = {}
    for tipo, count in TIPI:
        try:
            card_pool = bff.CardPool(merged_counts, names=player_names)
            formazioni = g.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
        except Exception as exc:
            out[tipo] = [{'errore': f'{type(exc).__name__}: {exc}'}]
            continue
        righe = []
        for r in formazioni:
            if 'error' in r:
                righe.append({'errore': r['error']})
                continue
            righe.append({
                'slug': sorted(row['slug'] for _, row, _ in r['formazione']),
                'punti': round(sum(row['atteso'] for _, row, _ in r['formazione']), 2),
            })
        out[tipo] = righe

    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f'scritto {out_path}')


if __name__ == '__main__':
    main()
