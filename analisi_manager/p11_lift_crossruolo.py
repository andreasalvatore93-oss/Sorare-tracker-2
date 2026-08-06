import json, statistics, random, collections, bisect, sys, io
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

coppie = json.load(open('dati_globali/taratura_coppie.json', encoding='utf-8'))
mapa = {'Goalkeeper':'GK','Defender':'DEF','Midfielder':'MID','Forward':'FWD'}
for c in coppie:
    c['cod'] = mapa.get(c.get('ruolo'))
coppie = [c for c in coppie if c['cod']]

PROD = {'GK':(35.78,0.264),'DEF':(7.28,0.831),'MID':(11.61,0.740),'FWD':(8.40,0.789)}

def retta(X,Y):
    n=len(X); mx=statistics.mean(X); my=statistics.mean(Y)
    den=sum((x-mx)**2 for x in X)
    b=sum((x-mx)*(y-my) for x,y in zip(X,Y))/den if den else 0.0
    a=my-b*mx
    return a,b

REFIT_LIN = {}
for cod in ('GK','DEF','MID','FWD'):
    sub = [c for c in coppie if c['cod']==cod]
    X=[c['previsto'] for c in sub]; Y=[c['reale'] for c in sub]
    REFIT_LIN[cod] = retta(X,Y)
print('refit lineare per ruolo (fresco):', REFIT_LIN)

fwd = sorted([c for c in coppie if c['cod']=='FWD'], key=lambda c: c['previsto'])
n = len(fwd)
NBIN = 10
nodi_x, nodi_y = [], []
for i in range(NBIN):
    lo = n*i//NBIN; hi = n*(i+1)//NBIN
    sub = fwd[lo:hi]
    nodi_x.append(statistics.mean(c['previsto'] for c in sub))
    nodi_y.append(statistics.mean(c['reale'] for c in sub))
print('nodi piecewise FWD (previsto->reale):')
for x,y in zip(nodi_x, nodi_y):
    print(f'  {x:.2f} -> {y:.2f}')

def calib_fwd_piecewise(x):
    if x <= nodi_x[0]:
        slope = (nodi_y[1]-nodi_y[0])/(nodi_x[1]-nodi_x[0])
        return nodi_y[0] + slope*(x-nodi_x[0])
    if x >= nodi_x[-1]:
        slope = (nodi_y[-1]-nodi_y[-2])/(nodi_x[-1]-nodi_x[-2])
        return nodi_y[-1] + slope*(x-nodi_x[-1])
    i = bisect.bisect_right(nodi_x, x) - 1
    x0,x1 = nodi_x[i], nodi_x[i+1]
    y0,y1 = nodi_y[i], nodi_y[i+1]
    t = (x-x0)/(x1-x0)
    return y0 + t*(y1-y0)

def calibra_prod(x, cod):
    a,b = PROD[cod]
    return a + b*x

def calibra_refit(x, cod):
    if cod == 'FWD':
        return calib_fwd_piecewise(x)
    a,b = REFIT_LIN[cod]
    return a + b*x

for c in coppie:
    c['cal_prod'] = calibra_prod(c['previsto'], c['cod'])
    c['cal_refit'] = calibra_refit(c['previsto'], c['cod'])

def rank(v):
    idx = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0]*len(v)
    i = 0
    while i < len(idx):
        j = i
        while j+1 < len(idx) and v[idx[j+1]] == v[idx[i]]:
            j += 1
        avg_rank = (i+j)/2 + 1
        for k in range(i, j+1):
            r[idx[k]] = avg_rank
        i = j+1
    return r

def spearman_from_ranks(rx, ry, n):
    d2 = sum((a-b)**2 for a,b in zip(rx,ry))
    return 1 - 6*d2/(n*(n**2-1))

reale_all = [c['reale'] for c in coppie]
prod_all = [c['cal_prod'] for c in coppie]
refit_all = [c['cal_refit'] for c in coppie]
n_tot = len(coppie)

r_reale = rank(reale_all)
r_prod = rank(prod_all)
r_refit = rank(refit_all)
sp_prod = spearman_from_ranks(r_prod, r_reale, n_tot)
sp_refit = spearman_from_ranks(r_refit, r_reale, n_tot)
print(f'\nSPEARMAN POOLED CROSS-RUOLO (n={n_tot}): prod={sp_prod:.4f}  refit={sp_refit:.4f}  delta={sp_refit-sp_prod:+.4f}')

def lift(cal, reale, frac):
    n = len(cal)
    order = sorted(range(n), key=lambda i: -cal[i])
    k = int(n*frac)
    top_idx = set(order[:k])
    top_reale = [reale[i] for i in range(n) if i in top_idx]
    resto_reale = [reale[i] for i in range(n) if i not in top_idx]
    return statistics.mean(top_reale), statistics.mean(resto_reale), statistics.mean(top_reale)-statistics.mean(resto_reale)

print('\nLIFT CROSS-RUOLO (top-K per atteso calibrato vs resto, media reale):')
lift_res = {}
for frac in (0.2, 0.4):
    tp, rp, lp = lift(prod_all, reale_all, frac)
    tr, rr, lr = lift(refit_all, reale_all, frac)
    lift_res[frac] = (lp, lr)
    print(f'  K={frac:.0%}: prod top={tp:.2f} resto={rp:.2f} lift={lp:.2f}  |  refit top={tr:.2f} resto={rr:.2f} lift={lr:.2f}  |  delta_lift={lr-lp:+.2f}')

print('\n(bootstrap in corso, B=300 righe...)', flush=True)
random.seed(7)
B = 300
deltas_sp = []
deltas_lift20 = []
deltas_lift40 = []
for b_i in range(B):
    idx = [random.randrange(n_tot) for _ in range(n_tot)]
    r_ = [reale_all[i] for i in idx]
    p_ = [prod_all[i] for i in idx]
    rf_ = [refit_all[i] for i in idx]
    rr_reale = rank(r_); rr_p = rank(p_); rr_rf = rank(rf_)
    sp_p = spearman_from_ranks(rr_p, rr_reale, n_tot)
    sp_rf = spearman_from_ranks(rr_rf, rr_reale, n_tot)
    deltas_sp.append(sp_rf - sp_p)
    _,_,lp20 = lift(p_, r_, 0.2); _,_,lr20 = lift(rf_, r_, 0.2)
    deltas_lift20.append(lr20-lp20)
    _,_,lp40 = lift(p_, r_, 0.4); _,_,lr40 = lift(rf_, r_, 0.4)
    deltas_lift40.append(lr40-lp40)
    if (b_i+1) % 50 == 0:
        print(f'  {b_i+1}/{B}', flush=True)

def ci(v):
    v = sorted(v)
    return v[int(.025*len(v))], v[int(.975*len(v))]

lo,hi = ci(deltas_sp)
print(f'\nIC95 bootstrap (B={B}, per riga, non clusterizzato):')
print(f'  delta Spearman pooled: {sp_refit-sp_prod:+.4f}  IC95 [{lo:+.4f}, {hi:+.4f}]')
lo,hi = ci(deltas_lift20)
print(f'  delta lift K=20%:      IC95 [{lo:+.2f}, {hi:+.2f}]')
lo,hi = ci(deltas_lift40)
print(f'  delta lift K=40%:      IC95 [{lo:+.2f}, {hi:+.2f}]')

with open('analisi_manager/p11_lift_crossruolo_result.json','w',encoding='utf-8') as fh:
    json.dump({'sp_prod':sp_prod,'sp_refit':sp_refit,'lift':lift_res,
                'deltas_sp':deltas_sp,'deltas_lift20':deltas_lift20,'deltas_lift40':deltas_lift40},
               fh)
