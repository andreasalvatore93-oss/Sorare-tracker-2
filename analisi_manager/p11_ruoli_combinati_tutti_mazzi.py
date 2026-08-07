"""FASE 3 del BRIEF_ODDS_4RUOLI_2026-08-07.txt -- backtest di formazione
PULITO (script fixato D6), ruoli e combinazioni, su TUTTI i mazzi disponibili.

Riusa l'impianto di p11_bloccato_tutti_mazzi.py (gia' fixato D6: reale_da_
cache() sempre primario, mazzo ricostruito +/-30gg, walk-forward, carte non
clonate, stessa regola capitano) importandone le funzioni. Nessuna riga
riscritta per il pool/reale/gioca: solo nuove combinazioni di policy sopra
le stesse funzioni.

Policy (k presi dalla griglia pulita FASE 2, stesso file):
  A       = produzione (nessuna correzione)
  B       = DEF mult k=0.2 (l'unico ruolo che passa il criterio severo),
            COMPOSIZIONE LIBERA (i ruoli competono per lo slot extra)
  B_lock  = B ma con composizione bloccata identica ad A (isola la
            selezione dentro il ruolo dalla competizione fra ruoli --
            e' il test che nel passato faceva riemergere il guadagno DEF)
  GK_solo = GK add k=3 (il punto piu' vicino a passare per GK, MAI passa
            il criterio severo -- qui si misura comunque per completezza,
            dichiarato NON atteso muovere nulla)
  MID_solo= MID mult k=0.2 (stesso discorso, MAI passa)
  FWD_solo= FWD mult k=0.1 (l'UNICA variante FWD che passa, al limite)
  D       = tutti e 4 i ruoli insieme al proprio ottimo (DEF+GK+MID+FWD),
            composizione LIBERA

Policy E (ricentrata per ruolo/GW) NON implementata in questo giro: nel
giro storico aveva un limite noto sulle spezzature (si ricentra la media
del pool, non la selezione del knapsack) e la priorita' e' stata data alla
copertura di GK/MID/FWD singoli mai misurati puliti, non ancora fatta.
Dichiarato come limite, non nascosto.

Nessuna modifica a file di produzione, nessun commit di produzione.
"""
import os, sys, io, json, random, collections
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p11_bloccato_tutti_mazzi as M

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

POLICIES = {
    'A': None,
    'B': {'DEF': ('mult', 0.2)},
    'GK': {'GK': ('add', 3)},
    'MID': {'MID': ('mult', 0.2)},
    'FWD': {'FWD': ('mult', 0.1)},
    'D': {'DEF': ('mult', 0.2), 'GK': ('add', 3), 'MID': ('mult', 0.2), 'FWD': ('mult', 0.1)},
}
NOMI_POLICY = ['A', 'B', 'B_lock', 'GK', 'MID', 'FWD', 'D']


def esegui(manager_file, dump_manager=None, dump_gw=None):
    manager, giornate = M.carica_manager(manager_file)
    righe_out = []
    scartate_atteso_tot = scartate_reale_tot = fallback_raw_tot = 0
    pool_sizes = []
    dump = None
    for gw_target, info in sorted(giornate.items(), key=lambda kv: kv[1]['data']):
        slots_righe = [r for r in info['righe'] if r.get('tipo_arena') in M.TIPI_VALIDI]
        if not slots_righe:
            continue
        tipo_bfg_list, tipo_label_list = [], []
        for r in slots_righe:
            tb, lab = M.tipo_bfg_di(r)
            if tb:
                tipo_bfg_list.append(tb)
                tipo_label_list.append(lab)
        if not tipo_bfg_list:
            continue

        base_pool, sa, sr, fr = M.prepara_gw_base(giornate, gw_target)
        scartate_atteso_tot += sa; scartate_reale_tot += sr; fallback_raw_tot += fr
        pool_sizes.append(len(base_pool))
        if len(base_pool) < 5:
            continue

        pools = {nome: M.applica_policy(base_pool, spec) for nome, spec in POLICIES.items()}
        formazioni = {nome: M.gioca(pools[nome], tipo_bfg_list) for nome in POLICIES}
        formazioni['B_lock'] = M.gioca_bloccato(pools['B'], tipo_bfg_list, formazioni['A'])

        if dump_manager and manager == dump_manager and (dump_gw is None or gw_target == dump_gw) and dump is None:
            dump = {'manager': manager, 'gw': gw_target, 'pool_size': len(base_pool),
                    'pool': [{'slug': c['slug'], 'ruolo': c['ruolo_full'], 'atteso_base': round(c['base'], 2),
                              'reale': c['reale'], 'copie': c['copie']} for c in base_pool],
                    'arene': []}
            for i, lab in enumerate(tipo_label_list):
                arena = {'tipo': lab, 'formazioni': {}}
                for nome in NOMI_POLICY:
                    f = formazioni[nome][i]
                    if f is None:
                        arena['formazioni'][nome] = None
                        continue
                    cap = M.capitano_atteso(f)
                    righe_f = [{'slug': r['slug'], 'ruolo': r['role_key'], 'atteso': round(r['atteso_cal'], 2),
                                'reale': r['reale'], 'capitano': (r is cap)} for _s, r, _t in f]
                    arena['formazioni'][nome] = {'punti': round(M.realizzato(f, cap), 2), 'carte': righe_f}
                dump['arene'].append(arena)

        for i, lab in enumerate(tipo_label_list):
            riga = {'gw': gw_target, 'tipo': lab}
            ok = True
            for nome in NOMI_POLICY:
                f = formazioni[nome][i]
                if f is None:
                    ok = False
                    break
                cap = M.capitano_atteso(f)
                riga[nome + '_punti'] = M.realizzato(f, cap)
                riga[nome + '_comp'] = dict(collections.Counter(r['role_key'] for _x, r, _t in f))
            if not ok:
                continue
            fa_slugs = set(r['slug'] for _x, r, _t in formazioni['A'][i])
            fb_slugs = set(r['slug'] for _x, r, _t in formazioni['B_lock'][i])
            riga['overlap_B_lock'] = len(fa_slugs & fb_slugs)
            righe_out.append(riga)

    return manager, righe_out, scartate_atteso_tot, scartate_reale_tot, fallback_raw_tot, pool_sizes, dump


def boot_delta(righe, campo, gw_key='gw', B=2000, seed=11):
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[r[gw_key]].append(r)
    unita = list(gruppi.values())
    n = len(unita)
    if n == 0:
        return None, None
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        num = 0.0; den = 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r[campo] - r['A_punti']; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if len(vals) < 30:
        return None, None
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def main():
    p('FASE 3 -- backtest formazione pulito, ruoli e combinazioni, TUTTI i mazzi')
    p('policy: A prod | B DEF libera | B_lock DEF composiz.bloccata | GK/MID/FWD singole | D combinata')

    tutti = sorted(f for f in os.listdir(M.SCRATCH) if f.startswith('manager_') and f.endswith('.json'))
    tutti = [f for f in tutti if f not in M.ESCLUSI]
    p('\nmazzi esclusi: %s' % sorted(M.ESCLUSI))
    p('mazzi da processare: %d' % len(tutti))

    risultati = []
    dump_fatto = [False]
    for i, fname in enumerate(tutti):
        p('\n[%d/%d] %s ...' % (i + 1, len(tutti), fname))
        dump_manager = None if dump_fatto[0] else fname.replace('manager_', '').replace('.json', '')
        try:
            manager, righe, sa, sr, fr, pool_sizes, dump = esegui(fname, dump_manager=dump_manager)
        except Exception as ex:
            p('  ERRORE: %r -- saltato' % ex)
            continue
        if dump and not dump_fatto[0]:
            with open(os.path.join(ROOT, 'analisi_manager', 'p11_ruoli_combinati_dump.json'), 'w', encoding='utf-8') as fh:
                json.dump(dump, fh, ensure_ascii=False, indent=1)
            p('  DUMP scritto: analisi_manager/p11_ruoli_combinati_dump.json (%s, %s)' % (dump['manager'], dump['gw']))
            dump_fatto[0] = True
        n_arene = len(righe)
        n_gw = len(set(r['gw'] for r in righe))
        if n_arene == 0:
            p('  0 arene valide -- saltato')
            continue
        overlap_medio = M.media(r['overlap_B_lock'] for r in righe)
        pool_medio = M.media(pool_sizes) if pool_sizes else float('nan')
        muto = overlap_medio >= 4.5
        deltas = {nome: M.media(r[nome + '_punti'] - r['A_punti'] for r in righe) for nome in NOMI_POLICY if nome != 'A'}
        p('  arene=%d giornate=%d pool_medio=%.1f overlap_Block=%.2f/5%s'
          % (n_arene, n_gw, pool_medio, overlap_medio, '  <- MUTO (escluso)' if muto else ''))
        p('  delta punti (vs A): ' + '  '.join('%s=%+.2f' % (k, v) for k, v in deltas.items()))
        risultati.append({'file': fname, 'manager': manager, 'righe': righe,
                           'n_arene': n_arene, 'n_gw': n_gw, 'pool_medio': pool_medio,
                           'overlap_medio': overlap_medio, 'deltas': deltas, 'muto': muto})

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_ruoli_combinati_righe.json'), 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False)

    utili = [r for r in risultati if not r['muto']]
    p('\nmazzi totali processati: %d | muti (overlap_Block>=4.5/5): %d | utili: %d'
      % (len(risultati), len(risultati) - len(utili), len(utili)))

    righe_tot = [r for mgr in utili for r in mgr['righe']]
    p('\n' + '=' * 100)
    p('RISULTATO AGGREGATO -- arene totali = %d, mazzi utili = %d' % (len(righe_tot), len(utili)))
    p('=' * 100)
    for nome in NOMI_POLICY:
        if nome == 'A':
            continue
        campo = nome + '_punti'
        pos = sum(1 for mgr in utili if mgr['deltas'][nome] > 1e-9)
        neg = sum(1 for mgr in utili if mgr['deltas'][nome] < -1e-9)
        zero = len(utili) - pos - neg
        pv = M.sign_test_p(pos, neg)
        d_pesato = M.media(r[campo] - r['A_punti'] for r in righe_tot)
        lo, hi = boot_delta(righe_tot, campo)
        p('\n%-8s segno: +%d/-%d/=%d mazzi (p=%.4f)  |  delta pesato per arena = %+.3f  IC95 [%s, %s]'
          % (nome, pos, neg, zero, pv, d_pesato,
             ('%+.3f' % lo) if lo is not None else 'n/a', ('%+.3f' % hi) if hi is not None else 'n/a'))

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_ruoli_combinati_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))


if __name__ == '__main__':
    main()
