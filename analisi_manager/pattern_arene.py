# -*- coding: utf-8 -*-
"""Analisi 3 filoni sulle 442 arene reali (analisi_manager/dati).
1) Metrica di selezione: quale indice ex-ante predice il rank?
2) Modellare il boom: e' predicibile l'evento reale>=75 oltre la media?
3) Partire dalla partita: i boom sono correlati fra compagni di squadra?
Pure Python (no numpy)."""
import json, glob, math, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import Counter, defaultdict

BOOM = 75.0
FLOP = 25.0
def homeval(c):
    v=c.get('in_casa')
    return 0.5 if v is None else (1.0 if v else 0.0)

# ---------- stat helpers ----------
def avg_ranks(vals):
    # returns average ranks (1-based) handling ties
    idx = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0]*len(vals)
    i = 0
    while i < len(idx):
        j = i
        while j+1 < len(idx) and vals[idx[j+1]] == vals[idx[i]]:
            j += 1
        r = (i+1 + j+1)/2.0
        for k in range(i, j+1):
            ranks[idx[k]] = r
        i = j+1
    return ranks

def pearson(x, y):
    n = len(x)
    if n < 3: return float('nan')
    mx = sum(x)/n; my = sum(y)/n
    sx = sum((a-mx)**2 for a in x); sy = sum((b-my)**2 for b in y)
    if sx == 0 or sy == 0: return float('nan')
    sxy = sum((a-mx)*(b-my) for a,b in zip(x,y))
    return sxy/math.sqrt(sx*sy)

def spearman(x, y):
    return pearson(avg_ranks(x), avg_ranks(y))

def auc(scores, labels):
    # AUC via average ranks (Mann-Whitney)
    npos = sum(labels); nneg = len(labels)-npos
    if npos == 0 or nneg == 0: return float('nan')
    r = avg_ranks(scores)
    sum_pos = sum(r[i] for i in range(len(labels)) if labels[i]==1)
    return (sum_pos - npos*(npos+1)/2.0)/(npos*nneg)

def stdev(v):
    n=len(v); m=sum(v)/n
    return math.sqrt(sum((a-m)**2 for a in v)/n) if n>1 else 0.0

# ---------- logistic regression (pure python) ----------
def fit_logistic(X, y, iters=3000, lr=0.2, l2=1.0):
    n = len(X); d = len(X[0])
    # standardize
    means=[sum(row[j] for row in X)/n for j in range(d)]
    sds=[ (stdev([row[j] for row in X]) or 1.0) for j in range(d)]
    Xs=[[(row[j]-means[j])/sds[j] for j in range(d)] for row in X]
    w=[0.0]*d; b=0.0
    for _ in range(iters):
        gw=[0.0]*d; gb=0.0
        for i in range(n):
            z=b+sum(w[j]*Xs[i][j] for j in range(d))
            p=1.0/(1.0+math.exp(-z)) if z>-700 else 0.0
            err=p-y[i]
            for j in range(d): gw[j]+=err*Xs[i][j]
            gb+=err
        for j in range(d): w[j]=w[j]-lr*(gw[j]/n + l2*w[j]/n)
        b=b-lr*gb/n
    def predict(row):
        z=b+sum(w[j]*((row[j]-means[j])/sds[j]) for j in range(d))
        return 1.0/(1.0+math.exp(-z)) if z>-700 else 0.0
    return predict, w, means, sds

# ---------- load ----------
files=sorted(glob.glob('analisi_manager/dati/formazioni_*.json'))
forms=[]  # list of formations, each with 'gw'
for fn in files:
    gw=os.path.basename(fn)[len('formazioni_'):-len('.json')]
    for f in json.load(open(fn,encoding='utf-8')):
        f['gw']=gw
        forms.append(f)

# all cards flat with gw
cards=[]
for f in forms:
    for c in f['carte']:
        c2=dict(c); c2['gw']=f['gw']
        cards.append(c2)

# de-dup cards on (gw, slug) -> unique player-match
uniq={}
for c in cards:
    k=(c['gw'],c['slug'])
    if k not in uniq: uniq[k]=c
ucards_all=list(uniq.values())            # tutte (reale sempre presente) -> filone 3
ucards=[c for c in ucards_all if c.get('atteso') is not None]  # con predizione -> filone 2 + fit pboom
# formazioni con tutte le carte predette -> filone 1
forms_ok=[f for f in forms if all(c.get('atteso') is not None for c in f['carte'])]

out=[]
def p(*a):
    s=' '.join(str(x) for x in a)
    out.append(s); print(s)

p('='*70)
p('DATI: %d formazioni, %d card-slot, %d carte uniche (gw,slug)'%(len(forms),len(cards),len(ucards)))
p('boom(>=75): %d/%d = %.1f%% carte-slot'%(sum(1 for c in cards if c['reale']>=BOOM),len(cards),100*sum(1 for c in cards if c['reale']>=BOOM)/len(cards)))

# =====================================================================
# FILONE 1: METRICA DI SELEZIONE
# =====================================================================
p('\n'+'='*70)
p('FILONE 1 — METRICA DI SELEZIONE (indice ex-ante vs rank; rank basso=meglio)')
p('='*70)

# fit p_boom(atteso) on de-duped cards (leave-one-GW-out for the index)
gws=sorted(set(f['gw'] for f in forms))
# per-GW predictor of p_boom from atteso, trained on other GWs
pboom_pred={}
for hold in gws:
    Xtr=[[c['atteso']] for c in ucards if c['gw']!=hold]
    ytr=[1 if c['reale']>=BOOM else 0 for c in ucards if c['gw']!=hold]
    pred,_,_,_=fit_logistic(Xtr,ytr,iters=1500,lr=0.3,l2=1.0)
    pboom_pred[hold]=pred

def indices(f):
    at=[c['atteso'] for c in f['carte']]
    at_sorted=sorted(at,reverse=True)
    pred=pboom_pred[f['gw']]
    pb=[pred([c['atteso']]) for c in f['carte']]
    p_at_least_1 = 1.0 - math.prod(1.0-x for x in pb)
    return {
        'sum_atteso': sum(at),
        'max_atteso': max(at),
        'top2_atteso': sum(at_sorted[:2]),
        'pboom_1plus': p_at_least_1,
        'exp_nboom': sum(pb),   # numero atteso di boom
    }

for f in forms_ok:
    f['_idx']=indices(f)
FORMS=forms_ok
p('Filone 1 usa %d/%d formazioni (tutte le carte predette)'%(len(FORMS),len(forms)))

ranks=[f['rank'] for f in FORMS]
real_sum=[f['punteggio_form'] for f in FORMS]
p('\nCorrelazioni con rank (Spearman, atteso su TUTTE le formazioni):')
p('  reale_sum (mecc.)   : %+.3f'%spearman(real_sum,ranks))
for key in ['sum_atteso','max_atteso','top2_atteso','exp_nboom','pboom_1plus']:
    v=[f['_idx'][key] for f in FORMS]
    p('  %-18s: %+.3f'%(key,spearman(v,ranks)))

# range restriction: within competizione
p('\nRange-restriction test — std(sum_atteso) e corr(sum_atteso,rank) per competizione:')
bycomp=defaultdict(list)
for f in FORMS: bycomp[f['competizione']].append(f)
for comp,fs in sorted(bycomp.items(), key=lambda kv:-len(kv[1])):
    sa=[f['_idx']['sum_atteso'] for f in fs]
    rr=[f['rank'] for f in fs]
    p('  %-10s n=%3d  std(sum)=%5.1f  corr(sum,rank)=%+.3f  corr(pboom1+,rank)=%+.3f'%(
        comp,len(fs),stdev(sa),spearman(sa,rr) if len(fs)>3 else float('nan'),
        spearman([f['_idx']['pboom_1plus'] for f in fs],rr) if len(fs)>3 else float('nan')))

# podium prediction: does index rank predict top-3?
p('\nAUC di ciascun indice nel predire il PODIO (rank<=3):')
podio=[1 if f['rank']<=3 else 0 for f in FORMS]
for key in ['sum_atteso','max_atteso','top2_atteso','exp_nboom','pboom_1plus']:
    v=[f['_idx'][key] for f in FORMS]
    p('  %-18s AUC=%.3f'%(key,auc(v,podio)))
p('  (reale_sum          AUC=%.3f  <- tetto meccanico)'%auc(real_sum,podio))

# =====================================================================
# FILONE 2: MODELLARE IL BOOM
# =====================================================================
p('\n'+'='*70)
p('FILONE 2 — MODELLARE IL BOOM (target reale>=75, card-level de-dup, OOF per GW)')
p('='*70)
roles=sorted(set(c['ruolo'] for c in ucards))
def feats(c):
    r=[c['atteso'],c['l10'],homeval(c),min(c['partite_storiche'],40)]
    r+=[1.0 if c['ruolo']==rr else 0.0 for rr in roles[:-1]]  # role dummies
    return r

y=[1 if c['reale']>=BOOM else 0 for c in ucards]
p('carte uniche=%d  boom=%d (%.1f%%)'%(len(ucards),sum(y),100*sum(y)/len(y)))

# single-feature AUC (in-sample, ordering power)
p('\nAUC single-feature (ordinamento del boom):')
for name,fn in [('atteso',lambda c:c['atteso']),('l10',lambda c:c['l10']),
                ('partite_storiche',lambda c:c['partite_storiche']),
                ('in_casa',lambda c:1.0 if c['in_casa'] else 0.0)]:
    p('  %-18s AUC=%.3f'%(name,auc([fn(c) for c in ucards],y)))

# OOF full model vs atteso-only, leave-one-GW-out
oof_full=[0.0]*len(ucards); oof_at=[0.0]*len(ucards)
idxbygw=defaultdict(list)
for i,c in enumerate(ucards): idxbygw[c['gw']].append(i)
for hold in gws:
    tr=[i for i in range(len(ucards)) if ucards[i]['gw']!=hold]
    te=idxbygw[hold]
    Xtr=[feats(ucards[i]) for i in tr]; ytr=[y[i] for i in tr]
    pred_full,_,_,_=fit_logistic(Xtr,ytr,iters=2500,lr=0.2,l2=1.0)
    Xtr_at=[[ucards[i]['atteso']] for i in tr]
    pred_at,_,_,_=fit_logistic(Xtr_at,ytr,iters=1500,lr=0.3,l2=1.0)
    for i in te:
        oof_full[i]=pred_full(feats(ucards[i]))
        oof_at[i]=pred_at([ucards[i]['atteso']])
p('\nOOF (leave-one-GW-out) AUC nel predire boom:')
p('  atteso-only  AUC=%.3f'%auc(oof_at,y))
p('  full model   AUC=%.3f'%auc(oof_full,y))
p('  delta        %+.3f  (>0 e non rumore => segnale boom oltre la media)'%(auc(oof_full,y)-auc(oof_at,y)))

# =====================================================================
# FILONE 3: PARTIRE DALLA PARTITA (covarianza boom fra compagni)
# =====================================================================
p('\n'+'='*70)
p('FILONE 3 — COVARIANZA BOOM (compagni stessa squadra stessa GW)')
p('='*70)
# group unique cards by (gw, squadra) — usa TUTTE le carte (reale sempre presente)
byteam=defaultdict(list)
for c in ucards_all: byteam[(c['gw'],c['squadra'])].append(c)
base_boom=sum(1 for c in ucards_all if c['reale']>=BOOM)/len(ucards_all)
# for teams with >=2 players: P(boom | almeno un compagno booma)
cond_num=cond_den=0
pair_same_boom=pair_same_tot=0
for k,cs in byteam.items():
    if len(cs)<2: continue
    booms=[1 if c['reale']>=BOOM else 0 for c in cs]
    for i in range(len(cs)):
        others=booms[:i]+booms[i+1:]
        if any(others):
            cond_den+=1
            cond_num+=booms[i]
    # pairwise co-boom
    for i in range(len(cs)):
        for j in range(i+1,len(cs)):
            pair_same_tot+=1
            if booms[i] and booms[j]: pair_same_boom+=1
p('boom marginale: %.1f%%'%(100*base_boom))
p('P(carta booma | un compagno stessa squadra/GW booma): %.1f%%  (n_cond=%d)'%(100*cond_num/cond_den if cond_den else 0,cond_den))
# expected co-boom se indipendenti vs osservato
p('coppie stesso team: %d  co-boom osservati: %d (%.1f%%)  attesi se indip.: %.1f%%'%(
    pair_same_tot,pair_same_boom,100*pair_same_boom/pair_same_tot if pair_same_tot else 0,100*base_boom**2))

# phi correlation of boom within-team pairs vs cross-team same-gw pairs (control sample)
def phi_pairs(pairlist):
    # pairlist: list of (b1,b2)
    a=[x[0] for x in pairlist]; b=[x[1] for x in pairlist]
    return pearson(a+b, b+a) if len(pairlist)>3 else float('nan')  # symmetric
same_pairs=[]
for k,cs in byteam.items():
    if len(cs)<2: continue
    bs=[1 if c['reale']>=BOOM else 0 for c in cs]
    for i in range(len(cs)):
        for j in range(i+1,len(cs)):
            same_pairs.append((bs[i],bs[j]))
p('phi(boom_i,boom_j) coppie STESSO team: %+.3f (n=%d)'%(phi_pairs(same_pairs),len(same_pairs)))

# formation-level: club concentration vs P(>=1 boom) e rank
p('\nConcentrazione club nella formazione vs esito:')
bycl=defaultdict(list)
for f in forms:
    nb=sum(1 for c in f['carte'] if c['reale']>=BOOM)
    bycl[f['club_distinti']].append((nb,f['rank']))
for cl in sorted(bycl):
    v=bycl[cl]
    nb=[a for a,_ in v]; rk=[b for _,b in v]
    p1=sum(1 for a in nb if a>=1)/len(v)
    p('  club_distinti=%d n=%3d  P(>=1 boom)=%.0f%%  boom medi=%.2f  rank medio=%.2f'%(
        cl,len(v),100*p1,sum(nb)/len(v),sum(rk)/len(rk)))

# ---- 1b: correlazione within-competizione (rank e indice centrati per gruppo) ----
p('\n[1b] Spearman POOLED ma centrato per competizione (unita corretta):')
def within_group_spearman(key):
    xs=[];ys=[]
    for comp,fs in bycomp.items():
        if len(fs)<4: continue
        vi=[f['_idx'][key] for f in fs]; vr=[f['rank'] for f in fs]
        ri=avg_ranks(vi); rr=avg_ranks(vr)
        mi=sum(ri)/len(ri); mr=sum(rr)/len(rr)
        xs+=[a-mi for a in ri]; ys+=[b-mr for b in rr]
    return pearson(xs,ys)
for key in ['sum_atteso','max_atteso','top2_atteso','pboom_1plus']:
    p('  %-18s: %+.3f'%(key,within_group_spearman(key)))

# ---- 2b: boom per ruolo + AUC(atteso) dentro ruolo ----
p('\n[2b] Boom per ruolo (carte uniche) e potere di atteso dentro il ruolo:')
byrole=defaultdict(list)
for c in ucards: byrole[c['ruolo']].append(c)
for rr,cs in sorted(byrole.items(),key=lambda kv:-len(kv[1])):
    yb=[1 if c['reale']>=BOOM else 0 for c in cs]
    a=auc([c['atteso'] for c in cs],yb) if 0<sum(yb)<len(yb) else float('nan')
    p('  %-11s n=%4d  boom=%.1f%%  AUC(atteso)=%.3f'%(rr,len(cs),100*sum(yb)/len(cs),a))

# ---- 3b: covarianza sul PUNTEGGIO continuo fra compagni (non solo boom) ----
p('\n[3b] Covarianza sul punteggio CONTINUO reale fra compagni stessa squadra/GW:')
same_a=[];same_b=[]
for k,cs in byteam.items():
    if len(cs)<2: continue
    rv=[c['reale'] for c in cs]
    for i in range(len(cs)):
        for j in range(i+1,len(cs)):
            same_a.append(rv[i]); same_b.append(rv[j])
# simmetrizza
p('  pearson(reale_i,reale_j) STESSO team: %+.3f (n_coppie=%d)'%(pearson(same_a+same_b,same_b+same_a),len(same_a)))
# controllo: coppie casuali stessa GW ma squadre diverse
import random
random.seed(0)
bygw2=defaultdict(list)
for c in ucards_all: bygw2[c['gw']].append(c)
ca=[];cb=[]
for gw,cs in bygw2.items():
    diff=[(cs[i],cs[j]) for i in range(len(cs)) for j in range(i+1,len(cs)) if cs[i]['squadra']!=cs[j]['squadra']]
    random.shuffle(diff)
    for a2,b2 in diff[:400]:
        ca.append(a2['reale']); cb.append(b2['reale'])
p('  pearson controllo (stessa GW, squadre DIVERSE): %+.3f (n=%d)'%(pearson(ca+cb,cb+ca),len(ca)))

# save report
rep='\n'.join(out)
open(r'C:\Users\Andrea\AppData\Local\Temp\claude\C--Users-Andrea-Documents-GitHub-Sorare-tracker-2\54aaf50b-ab0f-4b89-a64d-18cea1e95779\scratchpad\arene_risultati.txt','w',encoding='utf-8').write(rep)
