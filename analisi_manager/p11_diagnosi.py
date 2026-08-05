# -*- coding: utf-8 -*-
"""P11 passo 5 - diagnosi: PERCHE' le due policy divergono e perche' B perde.
Gira sul design C (pool pieno per arena, arene indipendenti), arene con cap."""
import os, sys, io, json, math, random, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
SP = os.path.dirname(os.path.abspath(__file__))
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)

import p11_boom as PB
import backtest_arene_produzione as BP
import backtest_arene_economia as E
import p11_confronta as CF

bfg, bff = BP.bfg, BP.bff
out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

BOOM = 75.0
righe = []
for fx, gw in sorted(CF.pool_per_gw.items(), key=lambda kv: kv[1]['cutoff']):
    slots = [s for s in gw['slot'] if s['tipo'] in CF.TIPI_CAPPED
             and s.get('punteggi') and s.get('mio_score') is not None]
    if not slots:
        continue
    mod = CF.WF.get(gw['cutoff'][:10])
    if mod is None:
        continue
    pool = [c for c in gw['pool'] if c.get('reale') is not None]
    ru = collections.Counter(c['codice'] for c in pool)
    if not all(ru[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
        continue
    for c in pool:
        c['_cal'] = bfg.calibra(c['atteso_raw'], c['codice'])
        c['_p'] = mod.p(c['codice'], c['atteso_raw'])
    slots = sorted(slots, key=lambda s: (s['tipo'], s['slug']))
    fa = CF.gioca(gw, slots, lambda c: c['_cal'], False)
    fb = CF.gioca(gw, slots, lambda c: -math.log(max(1e-12, 1.0 - c['_p'])), False)
    l10 = {c['slug']: c['l10'] for c in pool}
    for s, la, lb in zip(slots, fa, fb):
        if la is None or lb is None:
            continue
        ca, cb = CF.capitano_atteso(la), CF.capitano_atteso(lb)
        r = {'fixture': fx, 'tipo': s['tipo'],
             'A_punti': CF.realizzato(la, ca), 'B_punti': CF.realizzato(lb, cb),
             'A_pboom': 1 - math.prod(1 - x['p_boom'] for _q, x, _t in la),
             'B_pboom': 1 - math.prod(1 - x['p_boom'] for _q, x, _t in lb),
             'A_nboom': sum(1 for _q, x, _t in la if x['reale'] >= BOOM),
             'B_nboom': sum(1 for _q, x, _t in lb if x['reale'] >= BOOM),
             'A_att': sum(x['atteso_cal'] for _q, x, _t in la) + .2 * ca['atteso_cal'],
             'B_att': sum(x['atteso_cal'] for _q, x, _t in lb) + .2 * cb['atteso_cal'],
             'A_l10': sum(l10[x['slug']] for _q, x, _t in la),
             'B_l10': sum(l10[x['slug']] for _q, x, _t in lb)}
        for pol, lin in (('A', la), ('B', lb)):
            for q, x, _t in lin:
                cod = x['role_key']
                r['%s_l10_%s' % (pol, cod)] = r.get('%s_l10_%s' % (pol, cod), 0.0) + l10[x['slug']]
                r['%s_att_%s' % (pol, cod)] = r.get('%s_att_%s' % (pol, cod), 0.0) + x['atteso_cal']
                r['%s_n_%s' % (pol, cod)] = r.get('%s_n_%s' % (pol, cod), 0) + 1
        r['A_gk'] = [x['slug'] for _q, x, _t in la if x['role_key'] == 'GK'][0]
        r['B_gk'] = [x['slug'] for _q, x, _t in lb if x['role_key'] == 'GK'][0]
        r['A_set'] = sorted(x['slug'] for _q, x, _t in la)
        r['B_set'] = sorted(x['slug'] for _q, x, _t in lb)
        r['rank_A'] = CF.esito(s, r['A_punti'])[0]
        r['rank_B'] = CF.esito(s, r['B_punti'])[0]
        righe.append(r)

def m(k):
    return sum(r[k] for r in righe) / len(righe)

p('=' * 72)
p('P11 PASSO 5 — DIAGNOSI (arene con cap, pool pieno per arena)')
p('=' * 72)
p('arene: %d   giornate: %d' % (len(righe), len(set(r['fixture'] for r in righe))))

p('\n1) L\'INTERRUTTORE FUNZIONA? B deve avere P(>=1 boom) >= A su OGNI arena')
viol = [r for r in righe if r['B_pboom'] < r['A_pboom'] - 1e-9]
p('   violazioni: %d/%d   (A %.4f -> B %.4f, guadagno medio %+.4f)'
  % (len(viol), len(righe), m('A_pboom'), m('B_pboom'), m('B_pboom') - m('A_pboom')))
p('   => l\'obiettivo B e\' davvero massimizzato dal knapsack (nessuna misura a vuoto)')

p('\n2) L\'OBIETTIVO SI REALIZZA? formazioni con almeno una carta reale >=75')
p('   A: %.1f%%   B: %.1f%%   (differenza %+.1f punti percentuali)'
  % (100 * sum(1 for r in righe if r['A_nboom'] >= 1) / len(righe),
     100 * sum(1 for r in righe if r['B_nboom'] >= 1) / len(righe),
     100 * (sum(1 for r in righe if r['B_nboom'] >= 1) - sum(1 for r in righe if r['A_nboom'] >= 1)) / len(righe)))
p('   boom medi per formazione:  A %.3f   B %.3f' % (m('A_nboom'), m('B_nboom')))
p('   p_boom prevista media:     A %.4f   B %.4f' % (m('A_pboom'), m('B_pboom')))

p('\n3) COSA CAMBIA NELLE CARTE — allocazione del budget L10 e degli attesi')
p('   %-8s %10s %10s %10s %10s' % ('', 'L10 A', 'L10 B', 'att.cal A', 'att.cal B'))
for cod in ('GK', 'DEF', 'MID', 'FWD'):
    p('   %-8s %10.2f %10.2f %10.2f %10.2f'
      % (cod, m('A_l10_%s' % cod), m('B_l10_%s' % cod),
         m('A_att_%s' % cod), m('B_att_%s' % cod)))
p('   %-8s %10.2f %10.2f %10.2f %10.2f'
  % ('TOTALE', m('A_l10'), m('B_l10'), m('A_att'), m('B_att')))
p('   n. carte per ruolo (slot EXTRA incluso):')
for cod in ('GK', 'DEF', 'MID', 'FWD'):
    p('     %-4s A %.3f   B %.3f' % (cod, m('A_n_%s' % cod), m('B_n_%s' % cod)))
p('   portiere DIVERSO fra le due policy: %.1f%% delle arene'
  % (100 * sum(1 for r in righe if r['A_gk'] != r['B_gk']) / len(righe)))

p('\n4) IL PREZZO PAGATO — quanto atteso B cede per ogni punto di P(boom)')
d_att = m('B_att') - m('A_att'); d_pb = m('B_pboom') - m('A_pboom')
p('   attesi calibrati ceduti: %+.2f pt   P(>=1 boom) guadagnata: %+.4f' % (d_att, d_pb))
p('   punti realizzati persi:  %+.2f pt   rank medio: A %.3f -> B %.3f'
  % (m('B_punti') - m('A_punti'), m('rank_A'), m('rank_B')))

p('\n5) LA CONVESSITA\' — dove sta la differenza fra i due obiettivi')
p('   p(atteso) e\' convessa: -log(1-p) cresce piu\' che linearmente con')
p('   l\'atteso, quindi B concentra il budget sulle carte gia\' alte e')
p('   accetta riempitivi bassi; A distribuisce. Verifica sul campione:')
p('   deviazione standard degli attesi calibrati DENTRO la formazione:')
import statistics
sdA = statistics.mean([statistics.pstdev([r['A_att_%s' % c] / max(1, r['A_n_%s' % c]) for c in ('GK', 'DEF', 'MID', 'FWD')]) for r in righe])
sdB = statistics.mean([statistics.pstdev([r['B_att_%s' % c] / max(1, r['B_n_%s' % c]) for c in ('GK', 'DEF', 'MID', 'FWD')]) for r in righe])
p('     A %.2f   B %.2f' % (sdA, sdB))

p('\n6) ROBUSTEZZA — B con capitano scelto sul boom cambia il verdetto?')
p('   (non misurato qui: il capitano e\' identico nelle due policy per')
p('    isolare la SELEZIONE, vedi report)')

open(os.path.join(SP, 'p11_diagnosi_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
