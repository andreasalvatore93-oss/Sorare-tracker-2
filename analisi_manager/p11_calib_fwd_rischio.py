"""P11 -- rischio-panchina delle carte scambiate da R (refit) vs A (produzione)
sui FWD. Riusa lo stesso impianto/gioco di p11_calib_fwd_confronto.py, ma in
piu' registra slug+ruolo+reale di ogni carta schierata in A e in R per calco-
lare, sulle carte AGGIUNTE (in R non in A) e SFRATTATE (in A non in R), il
tasso di reale==0 (non ha giocato / panchina) per ruolo.

Nessuna modifica a file di produzione, nessun commit.
"""
import os, sys, io, json, collections
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import p11_calib_fwd_confronto as m

SCRATCH = m.SCRATCH
ESCLUSI = m.ESCLUSI

aggiunte = collections.defaultdict(list)   # ruolo -> lista di reale (carte in R non in A)
sfrattate = collections.defaultdict(list)  # ruolo -> lista di reale (carte in A non in R)

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)


def esegui_con_tracking(manager_file):
    manager, giornate = m.carica_manager(manager_file)
    n_arene = 0
    for gw_target, info in sorted(giornate.items(), key=lambda kv: kv[1]['data']):
        slots_righe = [r for r in info['righe'] if r.get('tipo_arena') in m.TIPI_VALIDI]
        if not slots_righe:
            continue
        tipo_bfg_list, tipo_label_list = [], []
        for r in slots_righe:
            tb, lab = m.tipo_bfg_di(r)
            if tb:
                tipo_bfg_list.append(tb); tipo_label_list.append(lab)
        if not tipo_bfg_list:
            continue
        base_pool, sa, sr = m.prepara_gw_base(giornate, gw_target)
        if len(base_pool) < 5:
            continue

        m.bfg.CALIB_PER_RUOLO['FWD'] = m.FWD_PROD
        pool_a = m.applica_calib(base_pool)
        fa = m.gioca(pool_a, tipo_bfg_list)

        m.bfg.CALIB_PER_RUOLO['FWD'] = m.FWD_REFIT
        pool_r = m.applica_calib(base_pool)
        fr = m.gioca(pool_r, tipo_bfg_list)

        m.bfg.CALIB_PER_RUOLO['FWD'] = m.FWD_PROD

        for la, lr in zip(fa, fr):
            if la is None or lr is None:
                continue
            set_a = {(r['slug'], r['role_key']): r['reale'] for _x, r, _t in la}
            set_r = {(r['slug'], r['role_key']): r['reale'] for _x, r, _t in lr}
            for key, reale in set_r.items():
                if key not in set_a:
                    aggiunte[key[1]].append(reale)
            for key, reale in set_a.items():
                if key not in set_r:
                    sfrattate[key[1]].append(reale)
            n_arene += 1
    return n_arene


def main():
    tutti = sorted(f for f in os.listdir(SCRATCH) if f.startswith('manager_') and f.endswith('.json'))
    tutti = [f for f in tutti if f not in ESCLUSI]
    p('Tracking rischio-panchina su %d mazzi' % len(tutti))
    tot_arene = 0
    for i, fname in enumerate(tutti):
        try:
            n = esegui_con_tracking(fname)
            tot_arene += n
        except Exception as ex:
            p('  ERRORE %s: %r -- saltato' % (fname, ex))
    p('arene processate: %d' % tot_arene)

    p('\n=== TASSO reale==0 (non ha giocato/zero) per ruolo, carte AGGIUNTE da R (in R non in A) ===')
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        v = aggiunte.get(ruolo, [])
        if not v:
            p('  %s: nessuna carta aggiunta' % ruolo)
            continue
        n0 = sum(1 for x in v if x == 0)
        p('  %-4s n=%5d  tasso_zero=%.1f%%  media_reale(tutte)=%.2f  media_reale(solo>0)=%.2f'
          % (ruolo, len(v), 100*n0/len(v), sum(v)/len(v),
             (sum(x for x in v if x>0)/max(1,sum(1 for x in v if x>0)))))

    p('\n=== TASSO reale==0 per ruolo, carte SFRATTATE (in A non in R) ===')
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        v = sfrattate.get(ruolo, [])
        if not v:
            p('  %s: nessuna carta sfrattata' % ruolo)
            continue
        n0 = sum(1 for x in v if x == 0)
        p('  %-4s n=%5d  tasso_zero=%.1f%%  media_reale(tutte)=%.2f  media_reale(solo>0)=%.2f'
          % (ruolo, len(v), 100*n0/len(v), sum(v)/len(v),
             (sum(x for x in v if x>0)/max(1,sum(1 for x in v if x>0)))))

    fwd_add = aggiunte.get('FWD', [])
    mid_off = sfrattate.get('MID', [])
    if fwd_add and mid_off:
        p0_fwd = sum(1 for x in fwd_add if x == 0) / len(fwd_add)
        p0_mid = sum(1 for x in mid_off if x == 0) / len(mid_off)
        p('\nGAP RISCHIO-PANCHINA: FWD aggiunti tasso_zero=%.1f%%  vs  MID sfrattati tasso_zero=%.1f%%  gap=%+.1fpt'
          % (100*p0_fwd, 100*p0_mid, 100*(p0_fwd-p0_mid)))

    with open(os.path.join(os.path.dirname(__file__), 'p11_calib_fwd_rischio_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    p('\nsalvato in analisi_manager/p11_calib_fwd_rischio_out.txt')


if __name__ == '__main__':
    main()
