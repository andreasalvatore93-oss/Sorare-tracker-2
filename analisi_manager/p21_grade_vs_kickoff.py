"""Il voto (grade) c'e' solo per le carte la cui PROSSIMA partita cade
dentro la giornata gia' APERTA? Incrocia il grade salvato nei
player_card_counts.json (scritti dalla discovery) con la data di KICKOFF
letta dal consiglio_*.txt piu' recente della stessa lega/ruolo.

Nato il 09/08/2026 per verificare la diagnosi del buco grade (§10bis.13
di docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md): l'utente ha detto che al
momento della discovery le sue carte K League e MLS AVEVANO GIA' GIOCATO.
SOLO LETTURA, zero query, zero modifiche alla produzione.

Rilancio: python analisi_manager/p21_grade_vs_kickoff.py  (~2s)
"""
import json, glob, os, re, collections, sys, io

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def kickoff_map(lega, ruolo):
    """slug -> data kickoff, dal consiglio_*.txt piu' recente."""
    d = f'formazione_{lega}/output/{lega}_{ruolo}_all'
    files = sorted(glob.glob(os.path.join(d, 'consiglio_*.txt')))
    if not files:
        return {}, None
    p = files[-1]
    out, slug = {}, None
    for riga in open(p, encoding='utf-8', errors='replace'):
        m = re.match(r'\s*\d+\)\s*([a-z0-9\-]+):', riga)
        if m:
            slug = m.group(1)
            continue
        m2 = re.search(r'KICKOFF:\s*([0-9T:\-]+)', riga)
        if m2 and slug:
            out[slug] = m2.group(1)
            slug = None
    return out, os.path.basename(p)


def main():
    per_giorno = collections.defaultdict(lambda: [0, 0])
    righe = []
    for p in glob.glob('formazione_*/output/*_discovery/player_card_counts.json'):
        pp = p.replace(os.sep, '/')
        m = re.search(r'formazione_([a-z0-9_]+)/output/[a-z0-9_]+_(gk|def|mid|fwd)_discovery', pp)
        if not m:
            continue
        lega, ruolo = m.group(1), m.group(2)
        counts = json.load(open(p, encoding='utf-8'))
        if not counts:
            continue
        kmap, _f = kickoff_map(lega, ruolo)
        for slug, v in counts.items():
            if not isinstance(v, dict):
                continue
            giorno = (kmap.get(slug) or 'NESSUN_KICKOFF')[:16]
            giorno = giorno[:10] if giorno != 'NESSUN_KICKOFF' else giorno
            per_giorno[giorno][0] += 1
            if v.get('grade'):
                per_giorno[giorno][1] += 1
            righe.append({'lega': lega, 'ruolo': ruolo, 'slug': slug,
                          'grade': v.get('grade'), 'kickoff': kmap.get(slug)})

    print('KICKOFF prossima partita | carte | con voto | %')
    for giorno in sorted(per_giorno):
        n, ng = per_giorno[giorno]
        print(f'  {giorno:16s} {n:4d}  {ng:4d}  {100.0 * ng / n:5.1f}%')

    out = {'per_giorno_kickoff': {k: {'carte': v[0], 'con_grade': v[1]} for k, v in per_giorno.items()},
           'righe': righe}
    with open('analisi_manager/dati/grade_vs_kickoff_20260809.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('\nsalvato analisi_manager/dati/grade_vs_kickoff_20260809.json')


if __name__ == '__main__':
    main()
