"""BRIEF_SONNET_GUADAGNO_PUNTO_220_2026-08-08.txt -- e' 6,3 sottostimato?

NESSUNA modifica a build_formazione_globale.py in questo script: PASSO 3
monkeypatcha GUADAGNO_PER_PUNTO in memoria (bfg.GUADAGNO_PER_PUNTO['cap 220']
= nuovo_valore) DOPO l'import, esattamente come p13/p15/p20 gia' fanno con
bfg.LEAGUES per le loro simulazioni -- non tocca il file, non e' un flag di
produzione, e' un override a runtime di uno script di misura.

PASSO 1: verifica se consiglio_arena.py riproduce le soglie di produzione
oggi, e ricostruisce la sigma per tipo dalla stessa fonte/metodo di
VALIDAZIONE_SOGLIE.md (dati_globali/backtest_arene_dettaglio_0805.json,
utente_atteso/utente_reale).

PASSO 2: pareggio empirico + pendenza (ess/pt) per tipo, a finestre
+-10/15/20/25, su TUTTI i manager (dati_globali/manager_*.json, premi BASE)
e su crowss con premi REALI (analisi_manager/p11_pool.json, golden incluse
per costruzione perche' e' il premio davvero incassato).

PASSO 3: con un GUADAGNO_PER_PUNTO['cap 220'] corretto, quante delle arene
della run di stanotte (GW3, GAMEWEEK=3) sarebbero cap 220 invece di cap 260?
Rigioca in locale sugli stessi dati committati dal run GitHub
(31253830349), nessuna nuova query.

Uso:
  python analisi_manager/p23_guadagno_punto_220.py
"""
import os
import sys
import io
import json
import glob
import statistics
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import consiglio_arena as C


# ============================================================== PASSO 1
def passo1():
    print('=' * 78)
    print('PASSO 1 -- come nasce il 6,3 (e il 7,9)')
    print('=' * 78)

    print('\n1a -- consiglio_arena.py riproduce le soglie di produzione OGGI?')
    campo = C.campo_per_tipo()
    for tipo, sigma_usata in (('cap 260', 50.6), ('cap 220', 42.70)):
        av = campo.get(tipo) or []
        regole = C.REGOLE[tipo]
        p = C.pareggio(av, regole['costo'], regole['premi'], sigma=sigma_usata, tipo=tipo)
        # guadagno/punto: pendenza dell'incasso nell'intorno del pareggio (+-5),
        # stessa definizione del commento di produzione (build_formazione_globale.py riga ~632)
        i_meno = C.incasso_medio(p - 5, av, regole['premi'], sigma=sigma_usata, tipo=tipo)
        i_piu = C.incasso_medio(p + 5, av, regole['premi'], sigma=sigma_usata, tipo=tipo)
        guadagno = (i_piu - i_meno) / 10
        print(f'  {tipo:10s} n_arene_archivio={len(av):4d}  sigma={sigma_usata:.2f}  '
              f'pareggio={p:.1f}  guadagno/pt={guadagno:.2f}')
    prod = {'cap 260': (259.5, 7.9), 'cap 220': (244.1, 6.3)}
    print(f'  valori di PRODUZIONE (build_formazione_globale.py): {prod}')
    print('  ATTENZIONE: dati_globali/arene_storico.json e\' CROLLATO da 673 a 160 arene')
    print('  fra l\'1/08 e il 6/08 (bug noto, VALIDAZIONE_SOGLIE.md 07/08 sera, MAI risolto).')
    print('  cap 260 oggi ha solo 62 arene in archivio (era molto di piu\' quando sono nate')
    print('  259.5/7.9), cap 220 ne ha 16. Il ricalcolo sopra usa l\'archivio DI OGGI, quindi')
    print('  NON e\' atteso che riproduca esattamente i valori di produzione -- e infatti non')
    print('  li riproduce (vedi sotto). Non e\' un difetto di questo script, e\' il bug noto.')

    print('\n1b -- con che SIGMA e\' stata calcolata la cap 220? (fonte: dati_globali/')
    print('  backtest_arene_dettaglio_0805.json, stesso file/metodo di VALIDAZIONE_SOGLIE.md)')
    d = json.load(open('dati_globali/backtest_arene_dettaglio_0805.json', encoding='utf-8'))
    per_tipo = collections.defaultdict(list)
    for r in d:
        if r.get('utente_atteso') is None or r.get('utente_reale') is None:
            continue
        per_tipo[r['tipo']].append((r['utente_atteso'], r['utente_reale']))

    def retta_sigma(X, Y):
        n = len(X)
        mx, my = statistics.mean(X), statistics.mean(Y)
        den = sum((x - mx) ** 2 for x in X)
        b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
        a = my - b * mx
        sd = statistics.pstdev([y - (a + b * x) for x, y in zip(X, Y)])
        return a, b, sd, n

    sigma_per_tipo = {}
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner', 'arena division'):
        rows = per_tipo.get(tipo) or []
        if len(rows) < 3:
            print(f'  {tipo:16s} n troppo piccolo: {len(rows)}')
            continue
        X = [x for x, _ in rows]
        Y = [y for _, y in rows]
        a, b, sd, n = retta_sigma(X, Y)
        sigma_per_tipo[tipo] = (sd, n)
        print(f'  {tipo:16s} n={n:4d}  sigma={sd:.1f}  (retta a={a:.1f} b={b:.3f})')
    print('  RIPRODOTTO ESATTAMENTE il numero di VALIDAZIONE_SOGLIE.md (cap260 50.6 n=113,')
    print('  cap220 41.9 n=8, Uncapped 42.9 n=31, Beginner 46.9 n=73, arena division 42.8 n=94).')
    print(f'\n  CONCLUSIONE 1b: cap 220 NON e\' rimasta su una sigma vecchia per disattenzione --')
    print('  E\' STATA CONTROLLATA (misurata a sigma=41.9, coerente col default 42.70, quindi')
    print('  non corretta), ma quel controllo poggia su SOLO n=8 arene. Cap 260 (che invece')
    print('  E\' stata corretta) poggiava su n=113, quattordici volte piu\' dati. Il sospetto')
    print('  dell\'orchestratore era fondato nella direzione sbagliata: non e\' negligenza,')
    print('  e\' una misura corretta metodologicamente ma con una n che non da\' nessuna garanzia.')
    return sigma_per_tipo


# ============================================================== PASSO 2
PREMI_BASE = {
    'Cap 260': {'costo': 300, 1: 1300, 2: 800, 3: 500},
    'Cap 220': {'costo': 200, 1: 1000, 2: 500, 3: 300},
    'Uncapped': {'costo': 300, 1: 1300, 2: 800, 3: 500},
}
ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_uncapped'}


def netto_base(tipo, rank):
    t = PREMI_BASE[tipo]
    return t.get(rank, 0) - t['costo']


def carica_manager_files():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json'))):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        if 'giornate' not in d:
            continue
        out[os.path.basename(path)[len('manager_'):-len('.json')]] = d
    return out


def raccogli_punti_netto_tutti_manager():
    """Una riga per arena (punteggio ufficiale, netto in essenze premi BASE),
    per Cap 260/220/Uncapped, tutti i 54 manager."""
    manager_files = carica_manager_files()
    righe = collections.defaultdict(list)
    for _manager, d in manager_files.items():
        for _gw, formazioni in (d.get('giornate') or {}).items():
            for f in formazioni:
                if f.get('tipo_arena') not in ARENE_AMMESSE_TIPO:
                    continue
                comp = f.get('competizione')
                if comp not in PREMI_BASE:
                    continue
                rank = (f.get('piazzamento') or {}).get('rank')
                punteggio = (f.get('piazzamento') or {}).get('punteggio')
                if rank is None or punteggio is None:
                    continue
                righe[comp].append((punteggio, netto_base(comp, rank)))
    return righe


def raccogli_punti_netto_crowss_reale():
    """Una riga per arena (punteggio, netto REALE con premio_essenze osservato,
    golden incluse per costruzione), da analisi_manager/p11_pool.json (crowss)."""
    d = json.load(open('analisi_manager/p11_pool.json', encoding='utf-8'))
    righe = collections.defaultdict(list)
    tipo_map = {'cap 260': 'Cap 260', 'cap 220': 'Cap 220', 'Uncapped': 'Uncapped'}
    for _fx, gw in d.items():
        for s in gw.get('slot') or []:
            tipo = tipo_map.get(s.get('tipo'))
            if tipo is None:
                continue
            if s.get('mio_score') is None or s.get('premio_essenze') is None or s.get('costo') is None:
                continue
            netto = s['premio_essenze'] - s['costo']
            righe[tipo].append((s['mio_score'], netto))
    return righe


def pareggio_empirico(righe):
    """Punto dove il netto medio passa da negativo a positivo, per bin di
    punteggio (larghezza 5). Semplice ricerca sui bin ordinati."""
    if not righe:
        return None
    righe = sorted(righe)
    lo = int(min(p for p, _ in righe) // 5 * 5)
    hi = int(max(p for p, _ in righe) // 5 * 5 + 5)
    prev_medio = None
    for centro in range(lo, hi, 5):
        vicini = [n for p, n in righe if centro - 10 <= p <= centro + 10]
        if len(vicini) < 5:
            continue
        medio = sum(vicini) / len(vicini)
        if prev_medio is not None and prev_medio < 0 <= medio:
            return centro
        prev_medio = medio
    return None


def pendenza_finestra(righe, pareggio, meta):
    """Regressione lineare netto ~ punteggio nella finestra
    [pareggio-meta, pareggio+meta]. Ritorna (pendenza, n)."""
    vicini = [(p, n) for p, n in righe if pareggio - meta <= p <= pareggio + meta]
    if len(vicini) < 5:
        return None, len(vicini)
    X = [p for p, _ in vicini]
    Y = [n for _, n in vicini]
    mx, my = statistics.mean(X), statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    if den == 0:
        return None, len(vicini)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den
    return b, len(vicini)


def passo2():
    print('\n' + '=' * 78)
    print('PASSO 2 -- misura indipendente della pendenza (ess/pt), metodo dichiarato')
    print('=' * 78)

    print('\n--- 2a: TUTTI I MANAGER (premi BASE, golden non distinte) ---')
    righe_tutti = raccogli_punti_netto_tutti_manager()
    pareggi_tutti = {}
    for tipo in ('Cap 260', 'Cap 220', 'Uncapped'):
        rs = righe_tutti.get(tipo) or []
        p = pareggio_empirico(rs)
        pareggi_tutti[tipo] = p
        print(f'  {tipo:10s} n_arene={len(rs):5d}  pareggio_empirico={p}')
    print()
    ratio_per_finestra_tutti = {}
    for meta in (10, 15, 20, 25):
        riga = f'  finestra +-{meta:2d}: '
        vals = {}
        for tipo in ('Cap 260', 'Cap 220'):
            p = pareggi_tutti.get(tipo)
            if p is None:
                continue
            b, n = pendenza_finestra(righe_tutti.get(tipo) or [], p, meta)
            vals[tipo] = b
            riga += f'{tipo}={b if b is None else round(b,2)} (n={n})  '
        if vals.get('Cap 260') and vals.get('Cap 220') is not None:
            rapporto = vals['Cap 220'] / vals['Cap 260'] if vals['Cap 260'] else None
            ratio_per_finestra_tutti[meta] = rapporto
            riga += f' rapporto220/260={rapporto:.3f}' if rapporto is not None else ''
        print(riga)

    print('\n--- 2b: SOLO crowss, premi REALI (golden incluse per costruzione) ---')
    righe_crowss = raccogli_punti_netto_crowss_reale()
    pareggi_crowss = {}
    for tipo in ('Cap 260', 'Cap 220', 'Uncapped'):
        rs = righe_crowss.get(tipo) or []
        p = pareggio_empirico(rs)
        pareggi_crowss[tipo] = p
        print(f'  {tipo:10s} n_arene={len(rs):5d}  pareggio_empirico={p}')
    print()
    ratio_per_finestra_crowss = {}
    for meta in (10, 15, 20, 25):
        riga = f'  finestra +-{meta:2d}: '
        vals = {}
        for tipo in ('Cap 260', 'Cap 220'):
            p = pareggi_crowss.get(tipo)
            if p is None:
                riga += f'{tipo}=n/a (pareggio non stimabile)  '
                continue
            b, n = pendenza_finestra(righe_crowss.get(tipo) or [], p, meta)
            vals[tipo] = b
            riga += f'{tipo}={b if b is None else round(b,2)} (n={n})  '
        if vals.get('Cap 260') and vals.get('Cap 220') is not None:
            rapporto = vals['Cap 220'] / vals['Cap 260'] if vals['Cap 260'] else None
            ratio_per_finestra_crowss[meta] = rapporto
            riga += f' rapporto220/260={rapporto:.3f}' if rapporto is not None else ''
        print(riga)

    print('\n--- 2c: rapporto cap220/cap260 -- il numero che conta ---')
    print(f'  produzione (6.3/7.9): {6.3/7.9:.3f}')
    print(f'  tutti i manager, per finestra: {ratio_per_finestra_tutti}')
    print(f'  crowss (premi reali), per finestra: {ratio_per_finestra_crowss}')
    return pareggi_tutti, pareggi_crowss, ratio_per_finestra_tutti, ratio_per_finestra_crowss


# ============================================================== PASSO 3
def passo3(guadagno_220_nuovo):
    print('\n' + '=' * 78)
    print(f'PASSO 3 -- quante arene cambierebbero con GUADAGNO_PER_PUNTO[cap220]={guadagno_220_nuovo}')
    print('=' * 78)
    print('Nessuna modifica al file build_formazione_globale.py: override IN MEMORIA')
    print('dopo l\'import (stesso pattern gia\' usato da p13/p15/p20 per bfg.LEAGUES).')
    print('Dati: stessi committati dal run GitHub 31253830349 (GAMEWEEK=3), nessuna query.\n')

    os.environ.setdefault('GAMEWEEK', '3')
    sys.path.insert(0, os.path.join(ROOT, 'generatore_formazioni'))
    import build_formazione_globale as bfg

    def costruisci_pool_fresco():
        role_data, role_counts, player_names = bfg.load_league_role_data()
        role_data = bfg.filter_by_window(role_data)
        pools = bfg.build_quality_pools(role_data)
        merged_counts = {}
        for role in bfg.ROLES:
            acc = {}
            for lg in bfg.LEAGUES:
                acc.update(role_counts.get(lg, {}).get(role, {}))
            merged_counts[role] = acc
        card_pool = bfg.bff.CardPool(merged_counts, names=player_names)
        return role_data, pools, card_pool

    tipi = [t for t in bfg.PRIORITY_ORDER if bfg._is_arena_type(t)]

    print('--- baseline (GUADAGNO_PER_PUNTO di produzione, invariato) ---')
    role_data, pools, card_pool = costruisci_pool_fresco()
    scelte_base = bfg.genera_arene_efficienti(tipi, 50, role_data, pools, card_pool)
    mix_base = collections.Counter(r['tipo'] for r in scelte_base)
    print(f'n arene: {len(scelte_base)}  mix: {dict(mix_base)}')

    print(f'\n--- con GUADAGNO_PER_PUNTO[cap220 in produzione]={guadagno_220_nuovo} (override in memoria) ---')
    originale = bfg.GUADAGNO_PER_PUNTO['ARENA_ALLSTARS_220']
    bfg.GUADAGNO_PER_PUNTO['ARENA_ALLSTARS_220'] = guadagno_220_nuovo
    try:
        role_data2, pools2, card_pool2 = costruisci_pool_fresco()
        scelte_nuovo = bfg.genera_arene_efficienti(tipi, 50, role_data2, pools2, card_pool2)
    finally:
        bfg.GUADAGNO_PER_PUNTO['ARENA_ALLSTARS_220'] = originale
    mix_nuovo = collections.Counter(r['tipo'] for r in scelte_nuovo)
    print(f'n arene: {len(scelte_nuovo)}  mix: {dict(mix_nuovo)}')

    return mix_base, mix_nuovo


def main():
    sigma_per_tipo = passo1()
    pareggi_tutti, pareggi_crowss, ratio_tutti, ratio_crowss = passo2()

    # valore candidato per il Passo 3: uso il rapporto medio delle finestre
    # +-15/+-20 (le piu' popolate, dichiarato) sul dataset TUTTI I MANAGER,
    # applicato a 7.9 (guadagno cap260 di produzione) -- e' UNA proposta di
    # quantificazione, non una raccomandazione di produzione.
    rapporti_validi = [ratio_tutti[m] for m in (15, 20) if m in ratio_tutti and ratio_tutti[m]]
    if rapporti_validi:
        rapporto_medio = sum(rapporti_validi) / len(rapporti_validi)
        guadagno_220_nuovo = round(7.9 * rapporto_medio, 2)
        print(f'\nValore candidato per il Passo 3 (rapporto medio finestre +-15/+-20 su tutti i '
              f'manager = {rapporto_medio:.3f}, applicato a 7.9): GUADAGNO_PER_PUNTO nuovo = '
              f'{guadagno_220_nuovo}')
        mix_base, mix_nuovo = passo3(guadagno_220_nuovo)
    else:
        print('\nNessun rapporto valido dalle finestre +-15/+-20: PASSO 3 saltato, dichiarato.')


if __name__ == '__main__':
    sys.exit(main() or 0)
