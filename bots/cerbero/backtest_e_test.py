"""
Test + backtest del motore_affare sul dataset storico (zero query).
Esegui da root repo:  python bots/bot_terzo/backtest_e_test.py

Fa tre cose:
  1) UNIT TEST delle funzioni pure (casi noti).
  2) BACKTEST: applica il gate temporale a ogni transazione storica come candidato
     d'acquisto e misura il rendimento reale a 48h dei candidati PASSATI vs SCARTATI
     -> prova che il gate seleziona i vincenti.
  3) TARATURA prudente di MIN_ABS_GAIN_EUR: action-rate e rendimento realizzato al
     variare della soglia, per scegliere un default prudente.
"""
import os, sys, csv, datetime, statistics, collections, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motore_affare as M

DATASET_GLOB = "bot_profit_output/pattern_raw_transactions_*.csv"


def carica():
    files = sorted(glob.glob(DATASET_GLOB))
    seen = set()
    rows = []
    for f in files:
        with open(f, encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                try:
                    dt = datetime.datetime.fromisoformat(r['tx_datetime_utc'])
                    p = float(r['price_eur'])
                except Exception:
                    continue
                key = (r['player_slug'], r['tipo_carta'], r['league_group'])
                dedup = (key, r['tx_datetime_utc'], round(p, 4))
                if dedup in seen:
                    continue
                seen.add(dedup)
                rows.append({'key': key, 'dt': dt, 'p': p})
    print(f"   dataset: {len(files)} file, {len(rows)} transazioni uniche (dedup)")
    bykey = collections.defaultdict(list)
    for x in rows:
        bykey[x['key']].append(x)
    for k in bykey:
        bykey[k].sort(key=lambda z: z['dt'])
    return bykey


def media_finestra(seq, i, days, sub_lo=None, sub_hi=None):
    t = seq[i]['dt']
    lo = t - datetime.timedelta(days=days)
    vals = []
    for j in range(i):
        d = seq[j]['dt']
        if not (lo <= d < t):
            continue
        if sub_lo is not None and not (t - datetime.timedelta(days=sub_lo) <= d < t):
            continue
        if sub_hi is not None and not (lo <= d < t - datetime.timedelta(days=sub_hi)):
            continue
        vals.append(seq[j]['p'])
    return statistics.mean(vals) if vals else None, len(vals)


# Orizzonti forward misurabili sul dataset storico. "24h" (18-30) e' l'orizzonte di
# APPRENDIMENTO adottato il 04/08 (vedi confronto_orizzonti + cerbero_learn.FORWARD_*).
ORIZZONTI = {'12h': (6, 18), '24h': (18, 30), '48h': (36, 60)}


def forward_h(seq, i, lo_h, hi_h):
    """Prezzo mediano della carta nella finestra [t+lo_h, t+hi_h]. None se vuota."""
    t = seq[i]['dt']
    lo, hi = t + datetime.timedelta(hours=lo_h), t + datetime.timedelta(hours=hi_h)
    vals = [seq[j]['p'] for j in range(i + 1, len(seq)) if lo < seq[j]['dt'] <= hi]
    return statistics.median(vals) if vals else None


def forward_48h(seq, i):
    """Compat: orizzonte storico 48h (36-60h)."""
    return forward_h(seq, i, 36, 60)


def costruisci_candidati(bykey, min_prior=3):
    """Per ogni tx: media recente (LOOKBACK), trend, esito reale a 48h."""
    W = M.LOOKBACK_DAYS
    cands = []
    for seq in bykey.values():
        for i in range(len(seq)):
            media, n = media_finestra(seq, i, W)
            if media is None or n < min_prior:
                continue
            fwd = forward_48h(seq, i)
            if fwd is None:
                continue
            # trend: media ultima 1gg vs resto della finestra
            m_rec, _ = media_finestra(seq, i, W, sub_lo=1.0)
            m_old, _ = media_finestra(seq, i, W, sub_hi=1.0)
            trend = M.classifica_trend(m_rec, m_old)
            p = seq[i]['p']
            cands.append({'p': p, 'media': media, 'trend': trend,
                          'ret_reale': (fwd - p) / p * 100.0, 'gain_reale': fwd - p})
    return cands


def costruisci_candidati_multiorizzonte(bykey, min_prior=3):
    """Come costruisci_candidati ma tiene SOLO i candidati che hanno un esito reale a
    TUTTI e 3 gli orizzonti (12/24/48h) -> stesso identico set, misure confrontabili."""
    W = M.LOOKBACK_DAYS
    cands = []
    for seq in bykey.values():
        for i in range(len(seq)):
            media, n = media_finestra(seq, i, W)
            if media is None or n < min_prior:
                continue
            fwd = {}
            ok = True
            for name, (lo, hi) in ORIZZONTI.items():
                v = forward_h(seq, i, lo, hi)
                if v is None:
                    ok = False
                    break
                fwd[name] = v
            if not ok:
                continue
            m_rec, _ = media_finestra(seq, i, W, sub_lo=1.0)
            m_old, _ = media_finestra(seq, i, W, sub_hi=1.0)
            trend = M.classifica_trend(m_rec, m_old)
            p = seq[i]['p']
            cands.append({'p': p, 'media': media, 'trend': trend,
                          'ret': {k: (fwd[k] - p) / p * 100.0 for k in ORIZZONTI}})
    return cands


def confronto_orizzonti(bykey):
    """LIFT del gate a 12/24/48h sullo STESSO set di candidati. Sceglie l'orizzonte di
    apprendimento: 24h e' adottato se lift_24h >= 0.70*lift_48h (regola brief 04/08)."""
    print("=" * 78)
    print("2-bis) CONFRONTO ORIZZONTI (lift del gate a 12/24/48h, stesso set)")
    cands = costruisci_candidati_multiorizzonte(bykey)
    # [R5] prova dell'interruttore: cambiare la finestra cambia davvero l'esito.
    for seq in bykey.values():
        for i in range(len(seq)):
            m, nn = media_finestra(seq, i, M.LOOKBACK_DAYS)
            if m and nn >= 3:
                a, b = forward_h(seq, i, 6, 18), forward_h(seq, i, 36, 60)
                if a is not None and b is not None and abs(a - b) > 1e-9:
                    print(f"   [R5 interruttore OK] stesso candidato: fwd(12h)={a:.3f} != fwd(48h)={b:.3f}")
                    break
        else:
            continue
        break
    passa = [c for c in cands if M.gate_temporale(c['p'], c['media'], c['trend'])['passa']]
    scarta = [c for c in cands if not M.gate_temporale(c['p'], c['media'], c['trend'])['passa']]
    print(f"   set: n={len(cands)}  passa={len(passa)}  scarta={len(scarta)}")
    lift = {}
    for k in ORIZZONTI:
        mp = statistics.median(c['ret'][k] for c in passa)
        ms = statistics.median(c['ret'][k] for c in scarta)
        lift[k] = mp - ms
        print(f"   {k:4s}: passa_med={mp:+6.2f}% (pos {pct_pos([c['ret'][k] for c in passa]):3.0f}%)  "
              f"scarta_med={ms:+6.2f}%  LIFT={lift[k]:+6.2f}")
    if lift['48h']:
        r24 = lift['24h'] / lift['48h']
        print(f"   -> ratio 24h/48h = {r24:.3f}  =>  "
              f"{'ADOTTA 24h' if r24 >= 0.70 else 'NON adottare, resta 48h'}")
    return lift


def pct_pos(v):
    return 100 * sum(1 for x in v if x > 0) / len(v) if v else 0.0


def unit_test():
    print("=" * 78); print("1) UNIT TEST funzioni pure")
    ok = True

    def check(desc, cond):
        nonlocal ok
        ok = ok and cond
        print(f"   [{'OK' if cond else 'FAIL'}] {desc}")

    check("sconto_temporale(8, 10) == 20%", abs(M.sconto_temporale(8.0, 10.0) - 20.0) < 1e-9)
    check("sconto_temporale su media None -> None", M.sconto_temporale(8.0, None) is None)
    check("rendimento cresce con lo sconto", M.rendimento_atteso_percent(20) > M.rendimento_atteso_percent(5))
    check("sovrapprezzo -> rendimento negativo", M.rendimento_atteso_percent(-5) < 0)
    check("trend down penalizza", M.rendimento_atteso_percent(15, 'down') < M.rendimento_atteso_percent(15, 'flat'))
    check("classifica_trend caduta -> down", M.classifica_trend(8.0, 10.0) == 'down')
    check("classifica_trend stabile -> flat", M.classifica_trend(10.0, 10.1) == 'flat')
    # gate: sovrapprezzo -> scarta
    g = M.gate_temporale(10.0, 9.0, 'flat')  # prezzo>media => sconto negativo
    check("gate scarta sovrapprezzo", not g['passa'])
    # gate: carta piccola con sconto modesto -> guadagno assoluto sotto soglia -> scarta
    g = M.gate_temporale(2.0, 2.15, 'flat')  # sconto ~7%, gain atteso ~0.09EUR
    check("gate scarta micro-guadagno su carta piccola", not g['passa'])
    # gate: sconto forte su carta media -> passa
    g = M.gate_temporale(12.0, 15.6, 'up')   # sconto ~23%
    check("gate passa affare vero (sconto forte, carta media)", g['passa'])
    # gate: fuori fascia prezzo
    g = M.gate_temporale(45.0, 60.0, 'up')
    check("gate scarta prezzo fuori fascia (>30)", not g['passa'])
    # gate: trend down con sconto modesto -> scarta
    g = M.gate_temporale(10.0, 11.5, 'down')  # sconto ~13% < 20 override
    check("gate scarta down con sconto sotto override", not g['passa'])
    print(f"   => {'TUTTI OK' if ok else 'CI SONO FAIL'}")
    return ok


def backtest_selettivita(cands):
    print("=" * 78)
    print(f"2) BACKTEST selettivita' del gate (lookback {M.LOOKBACK_DAYS:.0f}gg, fwd 48h+-12h, n={len(cands)})")
    passa, scarta = [], []
    for c in cands:
        g = M.gate_temporale(c['p'], c['media'], c['trend'])
        (passa if g['passa'] else scarta).append(c)
    for nome, grp in (("PASSANO il gate", passa), ("SCARTATI dal gate", scarta)):
        if grp:
            print(f"   {nome:22s} n={len(grp):4d}  mediana_ret={statistics.median(c['ret_reale'] for c in grp):+6.1f}%  "
                  f"%pos={pct_pos([c['ret_reale'] for c in grp]):4.0f}%  mediana_gain={statistics.median(c['gain_reale'] for c in grp):+.2f}EUR")
    if passa and scarta:
        lift = statistics.median(c['ret_reale'] for c in passa) - statistics.median(c['ret_reale'] for c in scarta)
        print(f"   -> LIFT del gate: {lift:+.1f} punti di rendimento mediano (passati vs scartati)")
    return passa


def taratura_soglia_eur(cands):
    print("=" * 78)
    print("3) TARATURA prudente MIN_ABS_GAIN_EUR (action-rate e rendimento realizzato)")
    tot = len(cands)
    for soglia in (0.30, 0.50, 0.75, 1.00, 1.50, 2.00):
        passati = []
        for c in cands:
            g = M.gate_temporale(c['p'], c['media'], c['trend'], min_abs_gain_eur=soglia)
            if g['passa']:
                passati.append(c)
        if passati:
            ar = 100 * len(passati) / tot
            print(f"   soglia {soglia:.2f}EUR: agisce su {len(passati):4d}/{tot} ({ar:4.1f}%)  "
                  f"mediana_ret={statistics.median(c['ret_reale'] for c in passati):+6.1f}%  "
                  f"%pos={pct_pos([c['ret_reale'] for c in passati]):4.0f}%  "
                  f"mediana_gain_reale={statistics.median(c['gain_reale'] for c in passati):+.2f}EUR")
        else:
            print(f"   soglia {soglia:.2f}EUR: nessuna azione")


if __name__ == '__main__':
    if not glob.glob(DATASET_GLOB):
        print(f"Dataset non trovato: {DATASET_GLOB}"); sys.exit(1)
    bykey = carica()
    cands = costruisci_candidati(bykey)
    ok = unit_test()
    passa = backtest_selettivita(cands)
    confronto_orizzonti(bykey)
    taratura_soglia_eur(cands)
    print("=" * 78)
    print(f"Motore: lookback={M.LOOKBACK_DAYS:.0f}gg, temp_disc_min={M.TEMP_DISC_MIN:.0f}%, "
          f"min_abs_gain={M.MIN_ABS_GAIN_EUR:.2f}EUR, fascia {M.PREZZO_MIN_EUR:.0f}-{M.PREZZO_MAX_EUR:.0f}EUR")
    sys.exit(0 if ok else 1)
