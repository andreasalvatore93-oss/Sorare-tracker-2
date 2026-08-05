# -*- coding: utf-8 -*-
"""Validazione soglie sulle 306 arene REALI dell'utente (backtest_arene_dettaglio).
Scala atteso = 2 ago (pre-ricalibrazione): sigma/ordinamento validi, pareggio
assoluto solo indicativo. Usa 'terzo' = cutoff podio reale. Pure Python."""
import json, sys, io, math, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# costo ingresso per tipo (premi gia' nel dato come 'premio' lordo)
COSTO={'cap 260':300,'arena division':300,'Uncapped':300,'arena uncapped':300,
       'cap 220':200,'Beginner':100}
PROD_SIGMA=42.70
PROD_LINEA=(63.43,0.736)

def retta(X,Y):
    mx,my=statistics.mean(X),statistics.mean(Y)
    den=sum((x-mx)**2 for x in X)
    b=sum((x-mx)*(y-my) for x,y in zip(X,Y))/den if den else 0.0
    a=my-b*mx
    return a,b,statistics.pstdev([y-(a+b*x) for x,y in zip(X,Y)])
def pear(X,Y):
    n=len(X);mx=sum(X)/n;my=sum(Y)/n
    sx=sum((x-mx)**2 for x in X);sy=sum((y-my)**2 for y in Y)
    return sum((x-mx)*(y-my) for x,y in zip(X,Y))/math.sqrt(sx*sy) if sx and sy else float('nan')
def auc(sc,lb):
    npos=sum(lb);nneg=len(lb)-npos
    if not npos or not nneg: return float('nan')
    order=sorted(range(len(sc)),key=lambda i:sc[i])
    ranks=[0]*len(sc);i=0
    while i<len(order):
        j=i
        while j+1<len(order) and sc[order[j+1]]==sc[order[i]]: j+=1
        r=(i+1+j+1)/2
        for k in range(i,j+1): ranks[order[k]]=r
        i=j+1
    sp=sum(ranks[i] for i in range(len(lb)) if lb[i]==1)
    return (sp-npos*(npos+1)/2)/(npos*nneg)

PATH=sys.argv[1] if len(sys.argv)>1 else 'dati_globali/backtest_arene_dettaglio.json'
d=json.load(open(PATH,encoding='utf-8'))
rows=[r for r in d if r.get('utente_atteso') is not None and r.get('utente_reale') is not None]
out=[]
def p(*a): s=' '.join(str(x) for x in a);out.append(s);print(s)

p('='*72);p('VALIDAZIONE SOGLIE — 306 arene reali UTENTE (scala 2 ago)')
p('arene usabili=%d'%len(rows))
from collections import Counter
p('tipi:',dict(Counter(r['tipo'] for r in rows)))

# ---- LINK 1: calibrazione / sigma ----
p('\n'+'='*72);p('LINK 1 — realizzato vs atteso (sigma, bias, ordinamento)')
X=[r['utente_atteso'] for r in rows];Y=[r['utente_reale'] for r in rows]
a,b,sd=retta(X,Y)
p('produzione assume: realizzato=%.2f+%.3f*prev, sigma %.2f'%(PROD_LINEA[0],PROD_LINEA[1],PROD_SIGMA))
p('REALE (n=%d): realizzato=%.2f+%.3f*atteso, sigma=%.2f'%(len(rows),a,b,sd))
p('  corr(atteso,realizzato)=%+.3f | range atteso %.0f-%.0f media %.1f'%(pear(X,Y),min(X),max(X),statistics.mean(X)))
p('  bias medio (atteso-realizzato)=%+.2f (>0: atteso OTTIMISTA)'%statistics.mean(x-y for x,y in zip(X,Y)))
p('  sd atteso %.1f vs sd realizzato %.1f (schiacciamento)'%(statistics.pstdev(X),statistics.pstdev(Y)))
p('\nsigma per tipo:')
for t in ['cap 260','arena division','Uncapped','Beginner','cap 220']:
    rs=[r for r in rows if r['tipo']==t]
    if len(rs)<5: p('  %-15s n=%d (pochi)'%(t,len(rs)));continue
    xs=[r['utente_atteso'] for r in rs];ys=[r['utente_reale'] for r in rs]
    aa,bb,ss=retta(xs,ys)
    p('  %-15s n=%3d  sigma=%.1f  corr=%+.3f  bias=%+.1f'%(t,len(rs),ss,pear(xs,ys),statistics.mean(x-y for x,y in zip(xs,ys))))

# ---- LINK 2: piu atteso -> piu premio/podio (il cuore dello scouting) ----
p('\n'+'='*72);p('LINK 2 — piu atteso -> piu ritorno? (quintili di atteso)')
podio=[1 if r['utente_reale']>=r['terzo'] else 0 for r in rows]  # cutoff reale
net=[r['premio']-COSTO.get(r['tipo'],300) for r in rows]
p('corr(atteso, premio)=%+.3f | corr(atteso, netto)=%+.3f'%(pear(X,[r['premio'] for r in rows]),pear(X,net)))
p('AUC(atteso -> podio via terzo)=%.3f  (podio complessivo %.0f%%)'%(auc(X,podio),100*sum(podio)/len(podio)))
q=sorted(range(len(rows)),key=lambda i:X[i])
p('\nquintile atteso |  n | atteso medio | realizzato | premio medio | netto medio | podio%')
for k in range(5):
    idx=q[k*len(q)//5:(k+1)*len(q)//5]
    p('  Q%d            |%3d |   %6.1f     |  %6.1f    |   %6.0f     |   %+6.0f    | %.0f%%'%(
        k+1,len(idx),statistics.mean(X[i] for i in idx),statistics.mean(Y[i] for i in idx),
        statistics.mean(rows[i]['premio'] for i in idx),statistics.mean(net[i] for i in idx),
        100*sum(podio[i] for i in idx)/len(idx)))

# ---- LINK 3: incasso vs atteso per tipo + break-even ----
p('\n'+'='*72);p('LINK 3 — netto vs atteso per tipo (essenze/punto, break-even indicativo)')
for t in ['cap 260','arena division','Uncapped','Beginner']:
    rs=[r for r in rows if r['tipo']==t]
    if len(rs)<8: p('  %-15s n=%d (pochi)'%(t,len(rs)));continue
    xs=[r['utente_atteso'] for r in rs]
    ns=[r['premio']-COSTO[t] for r in rs]
    aa,bb,_=retta(xs,ns)
    roi=100*statistics.mean(ns)/COSTO[t]
    be=(-aa/bb) if bb else float('nan')
    p('  %-15s n=%3d ROI %+5.1f%%  ess/punto=%.2f  break-even atteso~%.0f'%(t,len(rs),roi,bb,be))

# ---- side: modello vs utente dove diverso ----
diff=[r for r in rows if not r.get('uguali',True)]
if diff:
    mw=sum(1 for r in diff if r['modello_reale']>r['utente_reale'])
    p('\n[side] modello vs utente su %d arene diverse: modello_reale medio %.1f vs utente %.1f, vince %d (%.0f%%)'%(
        len(diff),statistics.mean(r['modello_reale'] for r in diff),
        statistics.mean(r['utente_reale'] for r in diff),mw,100*mw/len(diff)))

open(r'C:\Users\Andrea\AppData\Local\Temp\claude\C--Users-Andrea-Documents-GitHub-Sorare-tracker-2\54aaf50b-ab0f-4b89-a64d-18cea1e95779\scratchpad\valida_utente_out.txt','w',encoding='utf-8').write('\n'.join(out))
