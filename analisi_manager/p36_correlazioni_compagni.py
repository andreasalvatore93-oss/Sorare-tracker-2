"""Correlazioni fra compagni di squadra: la misura di base del filone
"correlazioni" (brief BRIEF_OPUS_CORRELAZIONI_2026-08-13_SERA.txt).

Una sola misura risponde alla domanda C (portiere/difensore, clean sheet) e
alla domanda E (fullstack): i RESIDUI (reale meno atteso) di due carte della
STESSA squadra nella STESSA giornata sono correlati?
  - se lo sono, l'errore del modello e' condiviso dalla squadra: schierare
    piu' compagni concentra il rischio invece di diversificarlo, e il
    meccanismo clean-sheet ha una traccia misurabile;
  - se non lo sono, entrambe le ipotesi cadono, quote alte o no.

La squadra non e' nel dump aggregato. NON serve rifare prepara_pool_rows
(costoso): la cache game-log condivisa contiene, per ogni partita di un
giocatore, le due squadre in campo. La squadra PROPRIA e' quella che compare
in TUTTE le sue partite (l'avversaria cambia ogni volta) -- si ricava con una
sola passata, zero query di rete.

Uso: python analisi_manager/p36_correlazioni_compagni.py
Produce: analisi_manager/dati/correlazioni_compagni_2026-08-13.json
"""
import os
import sys
import io
import json
import math
import random
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
CACHE_INDEX = os.path.join('analisi_manager', 'dati', '_cache_index_gamelog.json')


def finestra_fixture(fx):
    """(inizio, fine) di una fixture dal suo slug. Gestisce sia
    football-3-7-apr-2026 sia football-29-apr-1-may-2026."""
    p = fx.split('-')
    anno = int(p[-1])
    mesi = [(i, MESI[t]) for i, t in enumerate(p) if t in MESI]
    m_fine = mesi[-1][1]
    m_ini = mesi[0][1]
    numeri = [(i, int(t)) for i, t in enumerate(p) if t.isdigit() and len(t) <= 2]
    g_fine = [v for i, v in numeri if i < mesi[-1][0]][-1]
    g_ini = numeri[0][1]
    ini = datetime.date(anno, m_ini, g_ini)
    fine = datetime.date(anno, m_fine, g_fine)
    if fine < ini:            # a cavallo di fine anno, non dovrebbe capitare qui
        ini = datetime.date(anno - 1, m_ini, g_ini)
    return ini, fine


def costruisci_indice_cache():
    """slug -> {'squadra': slug_squadra, 'partite': {data: (score, mins, avversario)}}

    Salvato su disco: la passata su tutta la cache costa ~2 minuti, i consumer
    successivi la rileggono in un secondo.
    """
    if os.path.exists(CACHE_INDEX):
        return json.load(open(CACHE_INDEX, encoding='utf-8'))
    idx = {}
    for root, _dirs, files in os.walk('.'):
        if not root.endswith('.game_log_cache'):
            continue
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            slug = fn[:-len('_gamelog.json')]
            try:
                d = json.load(open(os.path.join(root, fn), encoding='utf-8'))
            except Exception:
                continue
            partite = idx.setdefault(slug, {}).setdefault('partite', {})
            conta = collections.Counter()
            for v in (d or {}).values():
                g = (v or {}).get('anyGame') or {}
                data = (g.get('date') or '')[:10]
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if not data or not casa or not fuori:
                    continue
                conta[casa] += 1
                conta[fuori] += 1
                st = v.get('anyPlayerGameStats') or {}
                partite[data] = [v.get('score'), st.get('minsPlayed'), casa, fuori]
            for t, n in conta.items():
                idx[slug].setdefault('_conta', {})[t] = idx[slug].get('_conta', {}).get(t, 0) + n
    # squadra propria = quella che compare nel maggior numero di sue partite
    for slug, v in idx.items():
        c = v.pop('_conta', {})
        v['squadra'] = max(c, key=c.get) if c else None
        v['n_partite'] = len(v['partite'])
    os.makedirs(os.path.dirname(CACHE_INDEX), exist_ok=True)
    json.dump(idx, open(CACHE_INDEX, 'w', encoding='utf-8'))
    return idx


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs); syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def boot_corr(coppie, cluster, B=1000, seed=20260813):
    """IC della correlazione ricampionando i CLUSTER (squadra-fixture), non le
    singole coppie: due coppie della stessa partita non sono indipendenti."""
    rnd = random.Random(seed)
    per_cluster = collections.defaultdict(list)
    for (x, y), k in zip(coppie, cluster):
        per_cluster[k].append((x, y))
    chiavi = list(per_cluster)
    if len(chiavi) < 5:
        return None
    out = []
    for _ in range(B):
        xs, ys = [], []
        for _ in range(len(chiavi)):
            for x, y in per_cluster[chiavi[rnd.randrange(len(chiavi))]]:
                xs.append(x); ys.append(y)
        r = pearson(xs, ys)
        if r is not None:
            out.append(r)
    if not out:
        return None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def main():
    print('costruisco/leggo indice cache game-log...')
    idx = costruisci_indice_cache()
    print(f'  giocatori in cache: {len(idx)}')

    rows = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json',
                          encoding='utf-8'))
    print(f'righe pool: {len(rows)}')

    # dedup carta->giocatore: la stessa persona puo' avere piu' carte nello
    # stesso pool. Per la correlazione fra compagni conta la PERSONA-giornata.
    per_slug_fx = {}
    for r in rows:
        k = (r['slug'], r['fixture'])
        if k not in per_slug_fx:
            per_slug_fx[k] = r
    print(f'unita\' (giocatore, giornata) distinte: {len(per_slug_fx)}')

    arricchite = []
    senza_squadra = senza_partita = 0
    for (slug, fx), r in per_slug_fx.items():
        info = idx.get(slug)
        if not info or not info.get('squadra'):
            senza_squadra += 1
            continue
        ini, fine = finestra_fixture(fx)
        trovate = [(d, v) for d, v in info['partite'].items()
                   if ini.isoformat() <= d <= fine.isoformat()]
        if len(trovate) != 1:
            senza_partita += 1
            continue
        data, (score, mins, casa, fuori) = trovate[0]
        arricchite.append({
            'slug': slug, 'fixture': fx, 'squadra': info['squadra'],
            'avversario': fuori if info['squadra'] == casa else casa,
            'in_casa': info['squadra'] == casa,
            'ruolo': r['codice'], 'atteso': r['_cal'], 'reale': r['reale'],
            'residuo': r['reale'] - r['_cal'], 'data': data,
            'minuti': mins, 'lega': r['lega'],
        })
    print(f'  arricchite {len(arricchite)}  (scartate: {senza_squadra} senza squadra, '
          f'{senza_partita} senza una partita unica nella finestra)')

    gruppi = collections.defaultdict(list)
    for a in arricchite:
        gruppi[(a['squadra'], a['fixture'])].append(a)
    multipli = {k: v for k, v in gruppi.items() if len(v) >= 2}
    print(f'gruppi squadra-giornata: {len(gruppi)}  di cui con >=2 compagni: {len(multipli)}')
    print(f'compagni per gruppo (fra quelli con >=2): '
          f'{sum(len(v) for v in multipli.values())/max(len(multipli),1):.2f}')

    def coppie_per(filtro=None, chiave='residuo'):
        xs, ys, cl = [], [], []
        for k, v in multipli.items():
            for i in range(len(v)):
                for j in range(len(v)):
                    if i == j:
                        continue
                    if filtro and not filtro(v[i], v[j]):
                        continue
                    xs.append(v[i][chiave]); ys.append(v[j][chiave]); cl.append(k)
        return xs, ys, cl

    risultati = {}
    print('\n=== CORRELAZIONE FRA RESIDUI DI COMPAGNI (stessa squadra, stessa giornata) ===')
    print('    (ogni coppia contata nei due versi: la correlazione e simmetrica)')
    casi = [
        ('TUTTE le coppie', None),
        ('GK con DEF', lambda a, b: a['ruolo'] == 'GK' and b['ruolo'] == 'DEF'),
        ('DEF con DEF', lambda a, b: a['ruolo'] == 'DEF' and b['ruolo'] == 'DEF'),
        ('MID con FWD', lambda a, b: a['ruolo'] == 'MID' and b['ruolo'] == 'FWD'),
        ('GK con MID/FWD', lambda a, b: a['ruolo'] == 'GK' and b['ruolo'] in ('MID', 'FWD')),
        ('difensivi (GK/DEF) fra loro', lambda a, b: a['ruolo'] in ('GK', 'DEF') and b['ruolo'] in ('GK', 'DEF')),
        ('offensivi (MID/FWD) fra loro', lambda a, b: a['ruolo'] in ('MID', 'FWD') and b['ruolo'] in ('MID', 'FWD')),
    ]
    for nome, filtro in casi:
        xs, ys, cl = coppie_per(filtro)
        r = pearson(xs, ys)
        if r is None:
            print(f'  {nome:30s} n coppie={len(xs):5d}  (troppo poche)')
            continue
        ic = boot_corr(list(zip(xs, ys)), cl)
        s_ic = f'IC95% [{ic[0]:+.3f}, {ic[1]:+.3f}]' if ic else 'IC n/d'
        print(f'  {nome:30s} n coppie={len(xs):5d}  r={r:+.3f}  {s_ic}')
        risultati[nome] = {'n_coppie': len(xs), 'r': r,
                           'ic': list(ic) if ic else None}

    # controllo placebo: stessa struttura, ma compagni FINTI (squadre diverse,
    # stessa giornata). Se esce lo stesso numero, la correlazione non e' della
    # squadra ma della giornata.
    print('\n=== PLACEBO: coppie della STESSA giornata ma di SQUADRE DIVERSE ===')
    per_fx = collections.defaultdict(list)
    for a in arricchite:
        per_fx[a['fixture']].append(a)
    rnd = random.Random(20260813)
    xs, ys, cl = [], [], []
    for fx, v in per_fx.items():
        if len(v) < 4:
            continue
        for _ in range(min(len(v) * 2, 400)):
            a, b = rnd.sample(v, 2)
            if a['squadra'] == b['squadra']:
                continue
            xs.append(a['residuo']); ys.append(b['residuo']); cl.append(fx)
    r = pearson(xs, ys)
    ic = boot_corr(list(zip(xs, ys)), cl)
    print(f'  {"coppie finte":30s} n coppie={len(xs):5d}  r={r:+.3f}  '
          + (f'IC95% [{ic[0]:+.3f}, {ic[1]:+.3f}]' if ic else 'IC n/d'))
    risultati['PLACEBO squadre diverse'] = {'n_coppie': len(xs), 'r': r,
                                            'ic': list(ic) if ic else None}

    out = os.path.join('analisi_manager', 'dati', 'correlazioni_compagni_2026-08-13.json')
    json.dump({'risultati': risultati,
               'n_unita': len(arricchite),
               'n_gruppi_multipli': len(multipli),
               'arricchite': arricchite},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
