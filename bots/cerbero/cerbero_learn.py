"""
CERBERO LEARN -- il bot impara dal mercato e adatta le soglie PER CAMPIONATO.

Idea (richiesta esplicita utente): Cerbero gira a lungo in diagnostica, registra ogni
carta che vede (prezzo, sconto vs media recente, lega, ora) in cerbero_osservazioni.csv;
qui misuriamo cosa e' successo DAVVERO al prezzo nelle ore successive e impariamo, per
ogni campionato, la soglia di sconto che rende il flip positivo. Il risultato va in
cerbero_soglie_apprese.json, che motore_affare.py legge (VINCE sui default hardcoded) --
cosi' col tempo il bot copre anche il ~90% di leghe che offline non abbiamo mai visto.

DUE FONTI:
  1) dataset storico pattern_raw_transactions_*.csv (solo leghe di Profit) -- validazione
     e bootstrap, gia' disponibile offline, ZERO query. E' la modalita' di default.
  2) --osservazioni: dai log live di Cerbero (tutte le leghe). Per ogni osservazione
     recupera il prezzo reale successivo dalle transazioni della carta (usa le query di
     cerbero.py, servono credenziali Sorare) e impara da li'. Da lanciare dopo che la
     diagnostica ha accumulato osservazioni.

Regola di apprendimento: per ogni lega, tra le soglie candidate, scegli la PIU' BASSA
che su quella lega da' rendimento mediano a 48h >= MIN_RET e % positivi >= MIN_POS con
almeno MIN_N campioni. Se nessuna qualifica (o troppo pochi dati) -> default prudente.
"""
import os, sys, csv, json, glob, datetime, statistics, collections, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motore_affare as M

SOGLIE_CANDIDATE = [5.0, 8.0, 10.0, 12.0, 15.0, 20.0]
MIN_RET = float(os.environ.get('CERBERO_LEARN_MIN_RET', '3.0'))    # rendimento mediano minimo
MIN_POS = float(os.environ.get('CERBERO_LEARN_MIN_POS', '55.0'))   # % positivi minimo
MIN_N = int(os.environ.get('CERBERO_LEARN_MIN_N', '30'))           # campioni minimi per fidarsi
DEFAULT_PRUDENTE = float(os.environ.get('CERBERO_TEMP_DISC_MIN', '10.0'))

# La lega nel dataset e' un GRUPPO (eredivisie_belgio unisce due slug). Mappa gruppo ->
# slug reali usati dal bot (league_slug), cosi' il JSON e' consumabile dal gate.
GRUPPO_A_SLUG = {
    'mlspa': ['mlspa'],
    'k-league-1': ['k-league-1'],
    'eredivisie_belgio': ['eredivisie', 'jupiler-pro-league'],
}


def _pos(v):
    return 100.0 * sum(1 for x in v if x > 0) / len(v) if v else 0.0


def _med(v):
    return statistics.median(v) if v else float('nan')


def candidati_da_dataset():
    """Ritorna dict lega_dataset -> lista (sconto%, rendimento48h%) a lookback corrente."""
    os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root
    seen = set()
    rows = []
    for f in sorted(glob.glob("bot_profit_output/pattern_raw_transactions_*.csv")):
        for r in csv.DictReader(open(f, encoding='utf-8')):
            try:
                dt = datetime.datetime.fromisoformat(r['tx_datetime_utc']); p = float(r['price_eur'])
            except Exception:
                continue
            key = (r['player_slug'], r['tipo_carta'], r['league_group'])
            d = (key, r['tx_datetime_utc'], round(p, 4))
            if d in seen:
                continue
            seen.add(d); rows.append({'key': key, 'dt': dt, 'p': p, 'grp': r['league_group']})
    bk = collections.defaultdict(list)
    for x in rows:
        bk[x['key']].append(x)
    for k in bk:
        bk[k].sort(key=lambda z: z['dt'])
    W = M.LOOKBACK_DAYS
    per = collections.defaultdict(list)
    for seq in bk.values():
        for i in range(len(seq)):
            t = seq[i]['dt']; lo = t - datetime.timedelta(days=W)
            prior = [seq[j]['p'] for j in range(i) if lo <= seq[j]['dt'] < t]
            if len(prior) < 3:
                continue
            media = statistics.mean(prior)
            if media <= 0:
                continue
            flo, fhi = t + datetime.timedelta(hours=36), t + datetime.timedelta(hours=60)
            fut = [seq[j]['p'] for j in range(i + 1, len(seq)) if flo < seq[j]['dt'] <= fhi]
            if not fut:
                continue
            fwd = statistics.median(fut); p = seq[i]['p']
            per[seq[i]['grp']].append(((media - p) / media * 100.0, (fwd - p) / p * 100.0))
    return per


def candidati_da_osservazioni(path, forward_lo_h=36.0, forward_hi_h=60.0, max_age_days=6.0):
    """RISOLUTORE FORWARD: per ogni osservazione (carta vista a un prezzo, con un dato
    sconto, in una data lega, a una certa ora) misura il prezzo REALE della stessa
    carta nelle ore successive (finestra forward_lo_h..forward_hi_h, tipicamente 48h)
    interrogando le transazioni tra manager (aste escluse) -> rendimento realizzato.
    Ritorna dict league_slug -> lista (sconto%, rendimento48h%). Servono credenziali
    Sorare (query). Le osservazioni troppo FRESCHE (finestra forward non ancora chiusa)
    o troppo VECCHIE (> max_age_days, fuori dalla finestra di fetch) vengono saltate.

    NB stagione: senza is_in_season nel log si usa un'euristica sull'anno nel card_slug
    per le leghe a doppio mercato (MLS/K-League/...); per le altre non serve (mercato unico).
    """
    import cerbero as C  # query gia' pronte e testate (lazy: serve il cookie)
    eth = C.get_eth_rate()
    now = datetime.datetime.now(datetime.timezone.utc)
    anno_corrente = now.year
    per = collections.defaultdict(list)
    risolte = saltate_fresche = saltate_vecchie = 0
    # cache per giocatore: una sola fetch transazioni per slug
    cache_nodi = {}
    with open(path, encoding='utf-8') as f:
        osservazioni = list(csv.DictReader(f))
    for r in osservazioni:
        try:
            ts = datetime.datetime.fromisoformat(r['ts_utc'])
            prezzo = float(r['prezzo_min_eur']); sconto = float(r['sconto_temporale_pct'])
        except (ValueError, KeyError, TypeError):
            continue
        eta_h = (now - ts).total_seconds() / 3600.0
        if eta_h < forward_hi_h:
            saltate_fresche += 1; continue
        if eta_h > max_age_days * 24:
            saltate_vecchie += 1; continue
        slug = r['player_slug']; league = r['league_slug']; card = r.get('card_slug', '')
        if slug not in cache_nodi:
            try:
                cache_nodi[slug] = C._fetch_paginated_transaction_nodes(slug)
            except Exception:
                cache_nodi[slug] = []
        nodi = cache_nodi[slug]
        excluded = C.is_asia_americas_excluded_league(league)
        is_season = None
        if excluded:  # euristica: anno nel card_slug == anno corrente -> in season
            is_season = (f"-{anno_corrente}-" in (card or ''))
        lo = ts + datetime.timedelta(hours=forward_lo_h); hi = ts + datetime.timedelta(hours=forward_hi_h)
        prezzi_fwd = []
        for n in nodi:
            if not (n.get('deal') or {}).get('type'):   # solo TokenOffer (no aste)
                continue
            if excluded and is_season is not None:
                if bool((n.get('card') or {}).get('inSeasonEligible')) != is_season:
                    continue
            try:
                dt = datetime.datetime.fromisoformat((n.get('date') or '').replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue
            if not (lo < dt <= hi):
                continue
            p = C.eur_price_from_amounts(n.get('amounts'), eth)
            if p is not None:
                prezzi_fwd.append(p)
        if not prezzi_fwd:
            continue
        fwd = statistics.median(prezzi_fwd)
        per[league].append((sconto, (fwd - prezzo) / prezzo * 100.0))
        risolte += 1
    print(f"[risolutore] osservazioni: {len(osservazioni)} | risolte {risolte} | "
          f"saltate troppo fresche {saltate_fresche} | troppo vecchie {saltate_vecchie}")
    return per


def impara(per_lega_cands):
    """Per ogni lega sceglie la soglia sconto minima che qualifica. Ritorna dict lega->info."""
    out = {}
    for lega, cs in per_lega_cands.items():
        scelta = None
        dettaglio = []
        for t in SOGLIE_CANDIDATE:
            rr = [ret for disc, ret in cs if disc >= t]
            info = {'soglia': t, 'n': len(rr), 'ret_med': round(_med(rr), 1) if rr else None,
                    'pos_pct': round(_pos(rr), 0) if rr else None}
            dettaglio.append(info)
            if scelta is None and len(rr) >= MIN_N and _med(rr) >= MIN_RET and _pos(rr) >= MIN_POS:
                scelta = t
        out[lega] = {'temp_disc_min': scelta if scelta is not None else DEFAULT_PRUDENTE,
                     'qualificata': scelta is not None, 'n_totale': len(cs), 'scan': dettaglio}
    return out


def scrivi_json(learned, fonte, path):
    per_lega_slug = {}
    for lega_ds, info in learned.items():
        for slug in GRUPPO_A_SLUG.get(lega_ds, [lega_ds]):
            per_lega_slug[slug] = {'temp_disc_min': info['temp_disc_min'],
                                    'qualificata': info['qualificata'], 'n': info['n_totale']}
    doc = {'updated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
           'fonte': fonte, 'lookback_days': M.LOOKBACK_DAYS,
           'criterio': {'min_ret': MIN_RET, 'min_pos': MIN_POS, 'min_n': MIN_N,
                        'default_prudente': DEFAULT_PRUDENTE},
           'per_lega': per_lega_slug}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--osservazioni', action='store_true',
                    help='impara dai log live cerbero_osservazioni.csv (richiede credenziali per il prezzo forward). Default: dataset storico.')
    ap.add_argument('--out', default='cerbero_soglie_apprese.json')
    args = ap.parse_args()

    if args.osservazioni:
        oss_path = os.environ.get('CERBERO_OSSERVAZIONI_PATH', 'cerbero_osservazioni.csv')
        if not os.path.exists(oss_path):
            print(f"Nessun file osservazioni ({oss_path}). Lancia prima la diagnostica.")
            return
        # dataset storico = bootstrap per le 4 leghe note; live = per TUTTE (anche nuove).
        learned_ds = impara(candidati_da_dataset())
        # espandi il dataset a slug reali
        base_slug = {}
        for lega_ds, info in learned_ds.items():
            for slug in GRUPPO_A_SLUG.get(lega_ds, [lega_ds]):
                base_slug[slug] = info
        learned_live = impara(candidati_da_osservazioni(oss_path))
        # merge: live VINCE se qualificata; altrimenti dataset; altrimenti prudente (gia' in impara).
        final = dict(base_slug)
        for slug, info in learned_live.items():
            if info['qualificata'] or slug not in final:
                final[slug] = info
        learned = final
        doc = scrivi_json(learned, 'osservazioni_live+dataset', args.out)
    else:
        learned = impara(candidati_da_dataset())
        doc = scrivi_json(learned, 'dataset_storico', args.out)
    print("=" * 70)
    print(f"SOGLIE APPRESE (lookback {M.LOOKBACK_DAYS:.0f}gg) scritte in {args.out}")
    for lega_ds, info in learned.items():
        stato = 'qualificata' if info['qualificata'] else 'NON qualificata -> default prudente'
        print(f"  {lega_ds:20s} soglia={info['temp_disc_min']:.0f}%  (n={info['n_totale']}, {stato})")
        for s in info['scan']:
            if s['n']:
                print(f"       sconto>={s['soglia']:.0f}%: n={s['n']:4d} ret_med={s['ret_med']} pos={s['pos_pct']}%")
    print("=" * 70)
    print("per_lega (slug reali usati dal bot):")
    for slug, v in doc['per_lega'].items():
        print(f"  {slug:22s} -> temp_disc_min {v['temp_disc_min']:.0f}% (n={v['n']})")


if __name__ == '__main__':
    main()
