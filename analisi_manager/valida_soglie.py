# -*- coding: utf-8 -*-
"""Valida le soglie di produzione (PAREGGIO_ARENA / GUADAGNO_PER_PUNTO) sulle
442 arene reali dei manager (atteso grezzo gia' ricostruito walk-forward).

Catena di produzione da riverificare:
  1) CALIBRAZIONE FORMAZIONE: realizzato = 63.43 + 0.736 x previsto, sigma 42.70
     (da taratura_formazioni_sintetiche.py, 40k formazioni sintetiche).
  2) SOGLIE: consiglio_arena.py usa quella sigma + campo/premi reali -> pareggio
     e guadagno_per_punto.
Qui rifittiamo la (1) sulle formazioni VERE e testiamo la (2) sull'incasso vero.
Pure Python."""
import json, glob, os, sys, io, math, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CAP = 0.2  # bonus capitano in arena

# produzione attuale
LINEA_PROD = (63.43, 0.736, 42.70)  # intercetta, pendenza, sigma
PAREGGIO = {'Cap 260':265.0,'Cap 220':244.1,'Uncapped':288.3,'Elite':342.7}
GUADAGNO = {'Cap 260':8.8,'Cap 220':6.3,'Uncapped':8.0,'Elite':9.1}
COSTO    = {'Cap 260':300,'Cap 220':200,'Uncapped':300,'Elite':800,'Beginner':100}
PREMI    = {'Cap 260':(1300,800,500),'Cap 220':(1000,500,300),
            'Uncapped':(1300,800,500),'Elite':(4000,2000,1000),'Beginner':(500,250,150)}

def retta(X, Y):
    mx, my = statistics.mean(X), statistics.mean(Y)
    den = sum((x-mx)**2 for x in X)
    b = sum((x-mx)*(y-my) for x,y in zip(X,Y))/den if den else 0.0
    a = my - b*mx
    sd = statistics.pstdev([y-(a+b*x) for x,y in zip(X,Y)])
    return a, b, sd

def pearson(X, Y):
    n=len(X); mx=sum(X)/n; my=sum(Y)/n
    sx=sum((x-mx)**2 for x in X); sy=sum((y-my)**2 for y in Y)
    if sx==0 or sy==0: return float('nan')
    return sum((x-mx)*(y-my) for x,y in zip(X,Y))/math.sqrt(sx*sy)

# ---- load formazioni ----
files=sorted(glob.glob('analisi_manager/dati/formazioni_*.json'))
forms=[]
for fn in files:
    for f in json.load(open(fn,encoding='utf-8')):
        forms.append(f)

rows=[]  # dict per formazione usabile
skip_noatt=skip_nocap=0
for f in forms:
    carte=f['carte']
    if any(c.get('atteso') is None for c in carte):
        skip_noatt+=1; continue
    # capitano
    cap_slug=f.get('capitano_slug')
    capc=next((c for c in carte if c['slug']==cap_slug), None)
    if capc is None:
        skip_nocap+=1; continue
    att_sum=sum(c['atteso'] for c in carte)
    reale_sum=sum(c['reale'] for c in carte)
    X = att_sum + CAP*capc['atteso']         # previsto con capitano (grezzo)
    Ycheck = reale_sum + CAP*capc['reale']    # realizzato con capitano (ricostruito)
    rows.append({'comp':f['competizione'],'X':X,'Y':f['punteggio_form'],
                 'Ycheck':Ycheck,'rank':f['rank'],'att_sum':att_sum})

out=[]
def p(*a): s=' '.join(str(x) for x in a); out.append(s); print(s)

p('='*72)
p('VALIDAZIONE SOGLIE su arene reali manager')
p('formazioni tot=%d  usabili=%d  (scartate: no-atteso %d, no-capitano %d)'%(
    len(forms),len(rows),skip_noatt,skip_nocap))

# check convenzione punteggio_form vs ricostruito
dd=[r['Y']-r['Ycheck'] for r in rows]
p('\n[check dato] punteggio_form vs (sum reale + 0.2*cap): diff media %+.2f  |diff| medio %.2f'%(
    statistics.mean(dd), statistics.mean(abs(x) for x in dd)))
p('  -> se ~0 la convenzione capitano nel dato e corretta')

# =====================================================================
p('\n'+'='*72)
p('LINK 1 — CALIBRAZIONE FORMAZIONE (realizzato vs previsto-con-capitano)')
p('='*72)
p('produzione: realizzato = %.2f + %.3f x previsto,  sigma %.2f'%LINEA_PROD)
X=[r['X'] for r in rows]; Y=[r['Y'] for r in rows]
a,b,sd=retta(X,Y)
p('\nREALE (tutte, n=%d): realizzato = %.2f + %.3f x previsto,  sigma %.2f'%(len(rows),a,b,sd))
p('  corr(previsto,realizzato) = %+.3f'%pearson(X,Y))
p('  range previsto: %.0f - %.0f  (media %.1f)'%(min(X),max(X),statistics.mean(X)))
# residuo rispetto alla LINEA DI PRODUZIONE
resid_prod=[y-(LINEA_PROD[0]+LINEA_PROD[1]*x) for x,y in zip(X,Y)]
p('\nResiduo vs LINEA DI PRODUZIONE (realizzato_vero - previsto_dalla_linea):')
p('  bias medio %+.2f  (>0: la produzione SOTTOSTIMA il realizzato)'%statistics.mean(resid_prod))
p('  sigma residuo %.2f  (produzione assume 42.70)'%statistics.pstdev(resid_prod))

p('\nPer competizione:')
by=lambda k: [r for r in rows if r['comp']==k]
for comp in ['Cap 260','Cap 220','Uncapped','Elite','Beginner']:
    rs=by(comp)
    if len(rs)<5: p('  %-9s n=%d (troppo pochi)'%(comp,len(rs))); continue
    xs=[r['X'] for r in rs]; ys=[r['Y'] for r in rs]
    aa,bb,ss=retta(xs,ys)
    rp=[y-(LINEA_PROD[0]+LINEA_PROD[1]*x) for x,y in zip(xs,ys)]
    p('  %-9s n=%3d  fit: %+.1f%+.3f*x sigma=%.1f | vs linea-prod: bias %+.1f sigma %.1f'%(
        comp,len(rs),aa,bb,ss,statistics.mean(rp),statistics.pstdev(rp)))

# =====================================================================
p('\n'+'='*72)
p('LINK 2 — INCASSO vs MARGINE SULLA SOGLIA (piu atteso -> piu essenze?)')
p('='*72)
def incasso(comp,rank):
    if comp not in PREMI: return None
    pr=PREMI[comp]; cost=COSTO[comp]
    win=pr[rank-1] if rank<=3 else 0
    return win-cost
for comp in ['Cap 260','Cap 220','Uncapped','Elite']:
    rs=[r for r in rows if r['comp']==comp and r['rank'] is not None]
    if len(rs)<5: p('  %-9s n=%d (pochi)'%(comp,len(rs))); continue
    marg=[r['X']-PAREGGIO[comp] for r in rs]
    inc=[incasso(comp,r['rank']) for r in rs]
    a2,b2,_=retta(marg,inc)  # inc = a2 + b2*margine  -> b2 = essenze per punto (reale)
    p('\n  %s  n=%d  incasso medio %+.0f ess (ROI %+.1f%%)'%(
        comp,len(rs),statistics.mean(inc),100*statistics.mean(inc)/COSTO[comp]))
    p('    corr(margine, incasso) = %+.3f'%pearson(marg,inc))
    p('    pendenza REALE: %.2f ess/punto  (produzione assume %.1f)'%(b2,GUADAGNO[comp]))
    # break-even reale: margine a cui incasso atteso = 0
    if b2!=0:
        be=-a2/b2
        p('    pareggio REALE (incasso=0) a margine %.1f -> atteso %.1f  (soglia prod %.1f)'%(
            be, PAREGGIO[comp]+be, PAREGGIO[comp]))
    # binning margine
    bins=[(-99,-5),(-5,0),(0,5),(5,15),(15,99)]
    p('    per fascia di margine:')
    for lo,hi in bins:
        sub=[inc[i] for i in range(len(rs)) if lo<=marg[i]<hi]
        if sub:
            p('      margine [%+d,%+d): n=%3d  incasso medio %+.0f ess  podio %.0f%%'%(
                lo,hi,len(sub),statistics.mean(sub),
                100*sum(1 for i in range(len(rs)) if lo<=marg[i]<hi and rs[i]['rank']<=3)/len(sub)))

open(r'C:\Users\Andrea\AppData\Local\Temp\claude\C--Users-Andrea-Documents-GitHub-Sorare-tracker-2\54aaf50b-ab0f-4b89-a64d-18cea1e95779\scratchpad\valida_soglie_out.txt','w',encoding='utf-8').write('\n'.join(out))
