"""Il criterio economico della tornata OPZIONALE.

Il pool vero di oggi e' ricco: ogni arena costruibile sta sopra il pareggio,
quindi una run reale non fa mai scattare il freno e non dimostra niente. Qui
si sostituiscono le tre funzioni che toccano il pool con delle finte, cosi'
si guarda SOLO la logica di scelta -- quella che e' cambiata.
"""
import os, sys, importlib.util

REPO = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
os.chdir(REPO); sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    'bfg', os.path.join(REPO, 'generatore_formazioni', 'build_formazione_globale.py'))
g = importlib.util.module_from_spec(spec); sys.modules['bfg'] = g
spec.loader.exec_module(g)

T1, T2 = 'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220'
print(f"pareggio {T1} = {g.PAREGGIO_ARENA[T1]} | {T2} = {g.PAREGGIO_ARENA[T2]}")

ATTESI = {}          # tipo -> atteso della prossima formazione costruibile
CHIAMATE = []        # tipo di ogni formazione davvero prodotta

g._istantanea_pool = lambda cp: None
g._ripristina_pool = lambda cp, s: None
g._atteso_con_capitano = lambda r: ATTESI[r['tipo']]


def _finta(tipo, count, role_data, pools, card_pool):
    if count <= 0:
        return []
    CHIAMATE.append(tipo)
    return [{'tipo': tipo, 'formazione': []}]


g.generate_lineups_for_type = _finta


def prova(nome, attesi, massimo, **kw):
    global ATTESI
    ATTESI = attesi
    del CHIAMATE[:]
    out = g.genera_arene_efficienti([T1, T2], massimo, None, None, None, **kw)
    prodotte = {}
    for r in out:
        prodotte[r['tipo']] = prodotte.get(r['tipo'], 0) + 1
    print(f"\n{nome}\n   formazioni tenute: {len(out)} {prodotte}")
    return out, prodotte


# A) Tutte SOTTO il pareggio: non se ne deve tenere nessuna.
_o, _p = prova("A) niente rende (attesi sotto il pareggio)",
               {T1: 200.0, T2: 200.0}, 10,
               cap_per_tipo={T1: 20, T2: 20}, gia_fatte={T1: 1, T2: 1})
assert len(_o) == 0, "il freno non ha fermato arene sotto il pareggio"
print("   OK: zero arene sotto il pareggio (prima ne avrebbe fatte 10)")

# B) Tetto per tipo: 2 gia' fatte su un tetto di 3 -> ne resta 1 a testa.
_o, _p = prova("B) tetto per tipo (cap 3, gia' fatte 2 per tipo)",
               {T1: 400.0, T2: 400.0}, 10,
               cap_per_tipo={T1: 3, T2: 3}, gia_fatte={T1: 2, T2: 2})
assert _p == {T1: 1, T2: 1}, f"tetto per tipo non rispettato: {_p}"
print("   OK: una per tipo, il tetto tiene")

# C) Senza i parametri nuovi = comportamento di prima (solo 'massimo').
_o, _p = prova("C) parametri nuovi assenti (tornata primaria, invariata)",
               {T1: 400.0, T2: 400.0}, 5)
assert len(_o) == 5, f"la tornata primaria non deve cambiare: {len(_o)}"
print("   OK: 5 richieste, 5 fatte -- nessun tetto per tipo, come prima")

# D) Sceglie il tipo che rende di piu', non a turno.
_o, _p = prova("D) sceglie il piu' redditizio, non round-robin",
               {T1: 400.0, T2: 285.0}, 4,
               cap_per_tipo={T1: 20, T2: 20}, gia_fatte={})
assert _p.get(T1) == 4 and T2 not in _p, f"non ha scelto il migliore: {_p}"
print("   OK: tutte e 4 sul tipo che rende di piu' (il round-robin ne avrebbe")
print("       date 2 al tipo peggiore)")

print("\nTUTTI I CONTROLLI PASSATI")
