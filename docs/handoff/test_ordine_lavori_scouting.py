"""L'ordine con cui si scrivono i predict da fare.

Il workflow tiene solo i primi 256: chi finisce in cima e' chi verra'
davvero predetto. Prima decideva l'alfabeto della cartella, ora la forza
del candidato (L10, e a parita' il voto A-F).
"""
import os, sys, json, importlib.util, collections

REPO = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
os.chdir(REPO); sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location('sgw', os.path.join(REPO, 'scouting_gw.py'))
s = importlib.util.module_from_spec(spec); sys.modules['sgw'] = s
spec.loader.exec_module(s)

# Pool finto: tre leghe, l'alfabeto in un ordine, la forza nell'altro.
# 'turchia' ha i giocatori piu' forti ma e' ultima in alfabeto: e' il caso
# che prima veniva buttato via per intero.
giocatori = []
for lega, base in (('argentina', 30.0), ('mls', 45.0), ('turchia', 70.0)):
    for i in range(4):
        giocatori.append({'slug': f'{lega}-g{i}', 'ruoli': ['MID'], 'cartella': lega,
                          'l10': base + i, 'grade': 'BCDE'[i % 4]})
pool = {'giocatori': giocatori}

per_gruppo = collections.defaultdict(list)
for g in sorted(pool['giocatori'], key=lambda x: -(x.get('l10') or 0)):
    per_gruppo[(g['cartella'], 'MID')].append(g['slug'])

# _predizioni_gia_fatte legge il disco: qui non deve escludere nessuno.
s._predizioni_gia_fatte = lambda coppie: (list(coppie), [])
letto = {}
def _finta_scrittura(dest, righe):
    letto['righe'] = righe


def esegui(pool_arg):
    dest = os.path.join(REPO, 'dati_globali', 'scouting_lavori.txt')
    prima = open(dest, encoding='utf-8').read() if os.path.exists(dest) else None
    try:
        out = s._scrivi_lavori(per_gruppo, None, pool_arg)
    finally:
        if prima is not None:
            open(dest, 'w', encoding='utf-8', newline='').write(prima)
    return out


print("=== SENZA pool (comportamento di prima) ===")
vecchio = esegui(None)
print("   primi 6:", [f"{l}|{r}|{sl}" for l, r, sl in vecchio[:6]])

print("\n=== CON pool (ordine per forza) ===")
nuovo = esegui(pool)
print("   primi 6:", [f"{l}|{r}|{sl}" for l, r, sl in nuovo[:6]])

l10 = {g['slug']: g['l10'] for g in giocatori}
print("\n   L10 nell'ordine nuovo:", [l10[sl] for _l, _r, sl in nuovo])

assert [c[0] for c in vecchio[:4]] == ['argentina'] * 4, "l'ordine vecchio non e' alfabetico?"
assert [c[0] for c in nuovo[:4]] == ['turchia'] * 4, f"i piu' forti non sono in cima: {nuovo[:4]}"
valori = [l10[sl] for _l, _r, sl in nuovo]
assert valori == sorted(valori, reverse=True), "L10 non decrescente"
assert sorted(vecchio) == sorted(nuovo), "cambia l'ordine, non l'insieme dei lavori"
print("\nOK: stesso insieme di lavori, ordinati per forza invece che per alfabeto.")

# Taglio a 256 simulato su un caso grande: chi resta fuori?
grandi = {'giocatori': [{'slug': f'x{i}', 'ruoli': ['MID'], 'cartella': 'zeta' if i < 300 else 'alfa',
                         'l10': float(i), 'grade': 'C'} for i in range(600)]}
pg = collections.defaultdict(list)
for g in sorted(grandi['giocatori'], key=lambda x: -(x.get('l10') or 0)):
    pg[(g['cartella'], 'MID')].append(g['slug'])
s_per_gruppo, per_gruppo = per_gruppo, pg
tagliato = esegui(grandi)[:256]
per_gruppo = s_per_gruppo
tenuti = [float(sl[1:]) for _l, _r, sl in tagliato]
print(f"taglio a 256 su 600: L10 minimo tenuto = {min(tenuti)}, massimo scartato = "
      f"{max(set(range(600)) - set(int(t) for t in tenuti))}")
assert min(tenuti) == 344.0, min(tenuti)
print("OK: il taglio butta via i piu' deboli, non una lega intera.")
