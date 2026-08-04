# -*- coding: utf-8 -*-
"""analizza_gw — sviscera le formazioni-arena dei manager di UNA GW chiusa.

Vedi analisi_manager/METODOLOGIA.md. Riusa le funzioni di produzione per
l'`atteso` (walk-forward stretto). Scrive in analisi_manager/dati/:
  righe_<gw>.json, formazioni_<gw>.json, report_<gw>.md
e aggiorna analisi_manager/INDICE.md (verdetti che si accumulano su piu' GW).

Uso: python analisi_manager/analizza_gw.py
     python analisi_manager/analizza_gw.py --gw football-4-7-aug-2026 --fine 2026-08-07
"""
import argparse
import datetime
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import backtest_arene_cache
import backtest_arene_previsioni as P

CAPITANO_ARENA = 0.2
SLOT_MEDIO = 51.8
DEFAULT_GW = 'football-31-jul-4-aug-2026'
DEFAULT_FINE = datetime.datetime(2026, 8, 4, 23, 59)
# I 12 slug del campione smart-money (scelti a caso dall'utente, non bias).
# Solo questi: crowss (manager dell'utente) e forever-young (altro filone) NON
# fanno parte del campione e vanno esclusi.
MANAGER_SMART = {'eoghankelly', 'badamt', 'milkyfresht', 'lairdinho', 'bxl-spartak',
                 'spillo678', 'braddersfc', 'bryanmid', 'shirimimi', 'matangel716',
                 'fins49', 'ninoshooter'}
DATI = os.path.join(ROOT, 'analisi_manager', 'dati')


# ---- statistica minima -------------------------------------------------------
def media(x):
    return sum(x) / len(x) if x else None


def sd(x):
    if len(x) < 2:
        return 0.0
    m = media(x)
    return (sum((v - m) ** 2 for v in x) / len(x)) ** 0.5


def corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = media(x), media(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def blocco(righe):
    if not righe:
        return {'n': 0}
    a = [r['atteso'] for r in righe]
    re_ = [r['reale'] for r in righe]
    err = [r['reale'] - r['atteso'] for r in righe]
    return {'n': len(righe), 'bias': media(err), 'mae': media([abs(e) for e in err]),
            'corr': corr(a, re_), 'sd_prev': sd(a), 'sd_reale': sd(re_)}


def fascia(v, tagli):
    for i, t in enumerate(tagli):
        if v < t:
            return f'<{t:.0f}' if i == 0 else f'{tagli[i-1]:.0f}-{t:.0f}'
    return f'>={tagli[-1]:.0f}'


# ---- lega per slug dal percorso della cache (offline) ------------------------
def indice_lega():
    pat = re.compile(r'formazione_([^\\/]+)[\\/]output')
    out = {}
    for r, _, fs in os.walk(ROOT):
        for f in fs:
            if f.endswith('_gamelog.json'):
                sl = f[:-len('_gamelog.json')]
                m = pat.search(r)
                if m and sl not in out:
                    out[sl] = m.group(1)
    return out


# ---- estrazione righe/formazioni --------------------------------------------
def estrai(gw, fine, cache, lega_di):
    manager_files = [f for f in os.listdir(os.path.join(ROOT, 'dati_globali'))
                     if f.startswith('manager_') and f.endswith('.json')]
    righe, formazioni, saltate = [], [], {}

    def salta(k):
        saltate[k] = saltate.get(k, 0) + 1

    for mf in sorted(manager_files):
        man = mf[len('manager_'):-len('.json')]
        if man not in MANAGER_SMART:
            continue
        d = json.load(open(os.path.join(ROOT, 'dati_globali', mf), encoding='utf-8'))
        forms = (d.get('giornate') or {}).get(gw) or []
        if not forms:
            continue
        for f in forms:
            carte_out = []
            for c in f.get('carte') or []:
                slug, ruolo = c.get('slug'), c.get('ruolo')
                reale = c.get('punteggio')
                if not slug or not ruolo or reale is None:
                    salta('carta incompleta'); continue
                cap = bool(c.get('capitano'))
                reale_raw = reale / (1.0 + CAPITANO_ARENA) if cap else reale
                r = P.score_atteso(cache, slug, ruolo, fine)
                atteso = r.get('atteso') if r else None
                riga = {'manager': man, 'slug': slug, 'nome': c.get('nome'),
                        'ruolo': ruolo, 'lega': lega_di.get(slug, '?'),
                        'squadra': c.get('squadra'), 'capitano': cap,
                        'competizione': f.get('competizione'),
                        'tipo_arena': f.get('tipo_arena'),
                        'reale': reale_raw, 'reale_con_cap': reale,
                        'atteso': atteso, 'l10': (r or {}).get('l10'),
                        'in_casa': (r or {}).get('in_casa'),
                        'partite_storiche': (r or {}).get('partite_storiche'),
                        'giocata': reale_raw != 0}
                carte_out.append(riga)
                # righe per l'analisi: solo chi ha giocato e ha atteso
                if atteso is None:
                    salta('no atteso (storico/target)'); continue
                if reale_raw == 0:
                    salta('non ha giocato (0)'); continue
                righe.append(riga)
            piaz = f.get('piazzamento') or {}
            att = [x['atteso'] for x in carte_out if x['atteso'] is not None]
            formazioni.append({
                'manager': man, 'competizione': f.get('competizione'),
                'tipo_arena': f.get('tipo_arena'),
                'rank': piaz.get('rank'), 'punteggio_form': piaz.get('punteggio'),
                'atteso_sum': sum(att) if att else None,
                'n_atteso': len(att), 'n_carte': len(carte_out),
                'club_distinti': len({x['squadra'] for x in carte_out if x['squadra']}),
                'capitano_slug': next((x['slug'] for x in carte_out if x['capitano']), None),
                'carte': carte_out,
            })
    return righe, formazioni, saltate


# ---- report ------------------------------------------------------------------
def tab(out, titolo, gruppi, minimo=1):
    out.append(f"\n### {titolo}\n")
    out.append(f"| gruppo | n | bias | MAE | corr |")
    out.append(f"|---|--:|--:|--:|--:|")
    for nome, rr in sorted(gruppi.items(), key=lambda kv: -len(kv[1])):
        if len(rr) < minimo:
            continue
        s = blocco(rr)
        c = f"{s['corr']:+.2f}" if s['corr'] is not None else '-'
        out.append(f"| {nome} | {s['n']} | {s['bias']:+.1f} | {s['mae']:.1f} | {c} |")


def gruppi(righe, campo):
    g = {}
    for r in righe:
        g.setdefault(r.get(campo), []).append(r)
    return {str(k): v for k, v in g.items()}


def gruppi_fascia(righe, campo, tagli):
    g = {}
    for r in righe:
        if r.get(campo) is None:
            continue
        g.setdefault(fascia(r[campo], tagli), []).append(r)
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gw', default=DEFAULT_GW)
    ap.add_argument('--fine', default=None, help='YYYY-MM-DD fine finestra GW')
    args = ap.parse_args()
    fine = (datetime.datetime.strptime(args.fine, '%Y-%m-%d').replace(hour=23, minute=59)
            if args.fine else DEFAULT_FINE)
    gw = args.gw
    os.makedirs(DATI, exist_ok=True)

    cache = backtest_arene_cache.CacheLocale()
    lega_di = indice_lega()
    righe, formazioni, saltate = estrai(gw, fine, cache, lega_di)
    if not righe:
        print('nessuna riga utilizzabile'); return 1

    out = [f"# Report analisi manager — GW {gw}", '',
           f"Generato: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} (locale). "
           f"Metodologia: analisi_manager/METODOLOGIA.md"]

    # --- A. selezione ---
    s = blocco(righe)
    manager_attivi = len({r['manager'] for r in righe})
    out.append(f"\n## A. Selezione (residuo = realizzato - atteso)\n")
    out.append(f"- Osservazioni: **{s['n']}** su {manager_attivi} manager attivi. "
               f"Scarti: " + ', '.join(f"{v} {k}" for k, v in
                                       sorted(saltate.items(), key=lambda kv: -kv[1])) + '.')
    out.append(f"- **Residuo medio (bias) = {s['bias']:+.2f}**  "
               f"[>0 = battono il modello, ~0 = no segnale]")
    out.append(f"- Correlazione atteso/reale {s['corr']:+.3f}; MAE {s['mae']:.1f}; "
               f"dispersione previsto {s['sd_prev']:.1f} vs reale {s['sd_reale']:.1f} "
               f"({s['sd_reale']/s['sd_prev']:.1f}x compressione).")
    lift = media([r['atteso'] for r in righe]) - SLOT_MEDIO
    out.append(f"- Lift di selezione: atteso medio dei loro pick "
               f"{media([r['atteso'] for r in righe]):.1f} vs slot medio {SLOT_MEDIO} "
               f"= **{lift:+.1f}** punti.")
    tab(out, 'Per ruolo', gruppi(righe, 'ruolo'))
    tab(out, 'Per competizione', gruppi(righe, 'competizione'))
    tab(out, 'Per lega (n>=15)', gruppi(righe, 'lega'), minimo=15)
    tab(out, 'Per fascia di atteso', gruppi_fascia(righe, 'atteso', [45, 50, 55, 60]))
    tab(out, 'Per fascia di L10', gruppi_fascia(righe, 'l10', [40, 50, 60, 70]))
    tab(out, 'Casa/trasferta', gruppi(righe, 'in_casa'))

    # --- consenso ---
    per_slug = {}
    for r in righe:
        per_slug.setdefault(r['slug'], []).append(r)
    cons = {}
    for sl, rr in per_slug.items():
        n_man = len({r['manager'] for r in rr})
        cons.setdefault(f"{n_man} manager", []).append(rr[0])
    dedup = blocco([rr[0] for rr in per_slug.values()])
    out.append(f"\n## Consenso\n")
    out.append(f"- A giocatore unico: n {dedup['n']}, bias {dedup['bias']:+.2f}, "
               f"corr {dedup['corr']:+.3f}.")
    tab(out, 'Residuo per numero di manager che lo schierano', cons)

    # --- B. capitano ---
    cap_rows = [r for r in righe if r['capitano']]
    noncap = [r for r in righe if not r['capitano']]
    # il capitano e' la carta a piu' alto atteso della sua formazione?
    cap_top = cap_tot = cap_sopra = 0
    for f in formazioni:
        att = [(x['atteso'], x['slug']) for x in f['carte'] if x['atteso'] is not None]
        cap = f['capitano_slug']
        if not cap or not att:
            continue
        cap_tot += 1
        if max(att)[1] == cap:
            cap_top += 1
        reali = [x['reale'] for x in f['carte'] if x['giocata']]
        cr = next((x['reale'] for x in f['carte'] if x['slug'] == cap and x['giocata']), None)
        if cr is not None and reali and cr > media(reali):
            cap_sopra += 1
    out.append(f"\n## B. Capitano\n")
    out.append(f"- Formazioni con capitano valutabile: {cap_tot}.")
    if cap_tot:
        out.append(f"- Il loro capitano è la carta a **max atteso** della formazione: "
                   f"{cap_top}/{cap_tot} ({100*cap_top/cap_tot:.0f}%) "
                   f"= accordo col nostro criterio pick_captain.")
        out.append(f"- Capitano che rende **sopra la media** della sua formazione: "
                   f"{cap_sopra}/{cap_tot} ({100*cap_sopra/cap_tot:.0f}%).")
    bc, bn = blocco(cap_rows), blocco(noncap)
    out.append(f"- Residuo capitani {bc.get('bias'):+.2f} (n {bc['n']}) vs "
               f"non-capitani {bn.get('bias'):+.2f} (n {bn['n']}).")

    # --- D. esito arena ---
    val = [f for f in formazioni if f['atteso_sum'] is not None and f['rank'] is not None
           and f['n_atteso'] >= 4]
    out.append(f"\n## D. Esito arena (il nostro atteso-somma predice il piazzamento?)\n")
    if len(val) >= 3:
        c_rank = corr([f['atteso_sum'] for f in val], [f['rank'] for f in val])
        pf = [f for f in val if f['punteggio_form'] is not None]
        c_pun = corr([f['atteso_sum'] for f in pf], [f['punteggio_form'] for f in pf]) if len(pf) >= 3 else None
        out.append(f"- Formazioni complete valutabili: {len(val)}.")
        out.append(f"- Corr(atteso_somma, rank reale) = {c_rank:+.3f} "
                   f"(negativa attesa: più atteso → rank migliore).")
        if c_pun is not None:
            out.append(f"- Corr(atteso_somma, punteggio formazione reale) = {c_pun:+.3f}.")
    else:
        out.append(f"- Troppe poche formazioni complete ({len(val)}).")

    # --- correlazioni extra + code boom/flop ---
    res = [r['reale'] - r['atteso'] for r in righe]
    l10r = [(r['l10'], r['reale'] - r['atteso']) for r in righe if r.get('l10') is not None]
    stor = [(r['partite_storiche'], r['reale'] - r['atteso']) for r in righe
            if r.get('partite_storiche') is not None]
    boom = sum(1 for r in righe if r['reale'] > 75) / len(righe)
    flop = sum(1 for r in righe if r['reale'] < 25) / len(righe)
    out.append(f"\n## Correlazioni & code\n")
    out.append(f"- corr(residuo, atteso) = {corr([r['atteso'] for r in righe], res):+.3f} "
               f"(se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).")
    if len(l10r) >= 3:
        out.append(f"- corr(residuo, L10) = {corr([a for a, _ in l10r], [b for _, b in l10r]):+.3f}.")
    if len(stor) >= 3:
        out.append(f"- corr(residuo, profondità storico) = "
                   f"{corr([a for a, _ in stor], [b for _, b in stor]):+.3f} "
                   f"(se >0: giochiamo peggio con poco storico).")
    out.append(f"- boom (>75) osservati {100*boom:.1f}% | flop (<25) {100*flop:.1f}%.")

    # --- F. skill per manager ---
    tab(out, 'F. Skill per manager (residuo)', gruppi(righe, 'manager'))

    # --- G. coda positiva ---
    top = sorted(righe, key=lambda r: r['reale'] - r['atteso'], reverse=True)[:15]
    out.append(f"\n## G. Coda positiva (dove hanno battuto di più l'atteso)\n")
    out.append(f"| giocatore | ruolo | lega | atteso | reale | residuo |")
    out.append(f"|---|---|---|--:|--:|--:|")
    for r in top:
        out.append(f"| {r['nome']} | {r['ruolo']} | {r['lega']} | "
                   f"{r['atteso']:.0f} | {r['reale']:.0f} | {r['reale']-r['atteso']:+.0f} |")
    from collections import Counter
    out.append(f"\n- Ruoli nella coda: {dict(Counter(r['ruolo'] for r in top))}")
    out.append(f"- Leghe nella coda: {dict(Counter(r['lega'] for r in top))}")

    # --- salvataggi ---
    json.dump(righe, open(os.path.join(DATI, f'righe_{gw}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    json.dump(formazioni, open(os.path.join(DATI, f'formazioni_{gw}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    rep = os.path.join(DATI, f'report_{gw}.md')
    open(rep, 'w', encoding='utf-8').write('\n'.join(out) + '\n')

    # --- INDICE.md: una riga-verdetto per GW, idempotente ---
    arena_c = corr([f['atteso_sum'] for f in val], [f['rank'] for f in val]) if len(val) >= 3 else None
    riga_idx = (f"| {gw} | {s['n']} | {manager_attivi} | {s['bias']:+.2f} | "
                f"{dedup['bias']:+.2f} | {s['corr']:+.3f} | "
                f"{(100*cap_top/cap_tot):.0f}% | "
                f"{arena_c:+.3f} | {100*boom:.1f}/{100*flop:.1f} |")
    idx = os.path.join(ROOT, 'analisi_manager', 'INDICE.md')
    header = ("# INDICE verdetti per GW (si accumula)\n\n"
              "Campione: 12 slug smart-money. Una riga per GW. Segno stabile su "
              "più GW = azionabile; oscillante = rumore. Dettaglio in dati/report_<gw>.md.\n\n"
              "| GW | n | manager | bias | bias_dedup | corr | cap=max_att | arena_corr(sum,rank) | boom%/flop% |\n"
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|\n")
    righe_idx = {}
    if os.path.exists(idx):
        for ln in open(idx, encoding='utf-8'):
            m = re.match(r'\| (football-\S+) \|', ln)
            if m:
                righe_idx[m.group(1)] = ln.rstrip('\n')
    righe_idx[gw] = riga_idx
    with open(idx, 'w', encoding='utf-8') as fh:
        fh.write(header)
        for k in sorted(righe_idx):
            fh.write(righe_idx[k] + '\n')

    print('\n'.join(out))
    print(f"\n[salvati] {rep}, righe_{gw}.json, formazioni_{gw}.json, INDICE.md")
    return 0


if __name__ == '__main__':
    sys.exit(main())
