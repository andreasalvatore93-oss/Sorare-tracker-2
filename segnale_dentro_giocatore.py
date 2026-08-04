"""segnale_dentro_giocatore — cosa prevede la GIORNATA, non il giocatore.

PERCHE'. `tetto_prevedibilita.py` ha spaccato in due il problema:

  - FRA giocatori (chi e' piu' forte): il modello ha correlazione +0.569 sulle
    medie, ed e' quasi al tetto -- la varianza fra giocatori e' solo il 5.7%
    del totale;
  - DENTRO lo stesso giocatore (quando rende sopra o sotto la propria media):
    correlazione -0.047, cioe' NULLA. Ed e' li' che sta il 94% della varianza.

Il modello, in sostanza, dice sempre la stessa cosa dello stesso giocatore: i
suoi scarti dalla media valgono 2.3 punti di deviazione standard contro i 17.1
della realta'. Non e' un difetto di taratura, e' un canale mai aperto.

Questo script chiede: **esiste qualcosa che prevede quello scarto?** Si tolgono
le medie per giocatore (media LASCIA-FUORI-UNO, per non correlare un dato con
se stesso) e si prova un segnale alla volta:

  casa/trasferta · forza dell'avversario e gol attesi della partita (Poisson di
  `modello_partita`) · forma recente (L5 contro L20) · giorni di riposo ·
  minuti giocati di recente · la previsione stessa del modello.

Ogni segnale e' disponibile PRIMA della partita e non costa una query: sono
tutti ricavati dalle cache gia' su disco.

COME SI LEGGE. La colonna che conta e' la correlazione col residuo reale: e'
il pezzo di quel 94% che il segnale riesce a mordere. Per dare la scala, la
colonna 'guadagno' traduce in punti quanto separerebbe il quinto piu' alto dal
quinto piu' basso del segnale.

Prerequisito:  python errore_modello_storico.py --json dati_globali/errore_storico.json

Uso:  python segnale_dentro_giocatore.py
"""
import argparse
import bisect
import collections
import datetime
import json
import math
import os
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import backtest_arene_cache

MIN_PRESENZE = 3


def _corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def _ic_corr(x, y, ripetizioni=400, seme=0):
    """Intervallo di confidenza al 95% per bootstrap sulle coppie."""
    import random
    rng = random.Random(seme)
    n = len(x)
    if n < 20:
        return None, None
    valori = []
    for _ in range(ripetizioni):
        idx = [rng.randrange(n) for _ in range(n)]
        c = _corr([x[i] for i in idx], [y[i] for i in idx])
        if c is not None:
            valori.append(c)
    if len(valori) < 50:
        return None, None
    valori.sort()
    return valori[int(0.025 * len(valori))], valori[int(0.975 * len(valori)) - 1]


# --------------------------------------------------------------------------
# forza delle squadre (gol attesi), checkpoint settimanali walk-forward
# --------------------------------------------------------------------------
_FORZE = None


def _forze():
    global _FORZE
    if _FORZE is None:
        import modello_partita as mp
        oss = mp.osservazioni(mp.partite_da_cache())
        oss.sort(key=lambda o: o['data'])
        date = [o['data'] for o in oss]
        cps, fz = [], []
        if oss:
            d = oss[0]['data']
            while d <= oss[-1]['data'] + datetime.timedelta(days=7):
                lo = bisect.bisect_left(date, d)
                if lo >= 400:
                    cps.append(d)
                    fz.append(mp.stima(oss[:lo], riferimento=d,
                                       regolarizzazione=0.30, emivita=120.0))
                d += datetime.timedelta(days=7)
        _FORZE = (cps, fz)
    return _FORZE


def gol_attesi(squadra, avversario, quando, in_casa):
    """(gol attesi miei, gol attesi dell'avversario) o (None, None)."""
    cps, fz = _forze()
    if not cps or not squadra or not avversario or quando is None:
        return None, None
    i = bisect.bisect_right(cps, quando) - 1
    if i < 0:
        return None, None
    f = fz[i]
    if not (f.conosciuta(squadra) and f.conosciuta(avversario)):
        return None, None
    return (f.lambda_atteso(squadra, avversario, in_casa=in_casa),
            f.lambda_atteso(avversario, squadra, in_casa=not in_casa))


# --------------------------------------------------------------------------
# segnali dallo storico del giocatore, troncato alla data della partita
# --------------------------------------------------------------------------
def storico_prima(cache, slug, quando):
    """Punteggi validi e date, solo per le partite precedenti a `quando`."""
    fuori = []
    for nodo in cache.gamelog(slug):
        if nodo.get('scoreStatus') not in ('FINAL', 'REVIEWING'):
            continue
        gioco = nodo.get('anyGame') or {}
        iso = gioco.get('date')
        if not iso:
            continue
        try:
            d = datetime.datetime.strptime(str(iso)[:10], '%Y-%m-%d')
        except ValueError:
            continue
        if d >= quando:
            continue
        fuori.append((d, nodo.get('score') or 0.0, nodo))
    fuori.sort(key=lambda t: t[0])
    return fuori


def _minuti(cache, slug, nodo):
    """I minuti giocati stanno nel dettaglio granulare, non nel game log."""
    ident = str(nodo.get('id') or '')
    dett = cache.dettaglio_partita(slug, ident.split(':')[-1])
    for riga in ((dett or {}).get('detailedScore') or []):
        if riga.get('stat') == 'mins_played':
            return float(riga.get('statValue') or 0.0)
    return None


def segnali_storico(cache, slug, quando):
    st = storico_prima(cache, slug, quando)
    if len(st) < 6:
        return {}
    punteggi = [s for _, s, _ in st]
    l5 = statistics.fmean(punteggi[-5:])
    l20 = statistics.fmean(punteggi[-20:])
    fuori = {'forma': l5 - l20, 'l5': l5}
    riposo = (quando - st[-1][0]).days
    if 0 <= riposo <= 40:
        fuori['riposo'] = float(riposo)
    # quante delle ultime 5 sono state partite intere (indizio di titolarita')
    minuti = []
    for _, _, nodo in st[-5:]:
        m = _minuti(cache, slug, nodo)
        if m is not None:
            minuti.append(m)
    if len(minuti) >= 3:
        fuori['minuti'] = statistics.fmean(minuti)
    # quanto e' ballerino il giocatore: la sua dispersione storica
    if len(punteggi) >= 8:
        fuori['volatilita'] = statistics.pstdev(punteggi[-20:])
    return fuori


# --------------------------------------------------------------------------
def prepara(righe):
    """Aggiunge a ogni riga i segnali di contesto e il residuo lascia-fuori-uno."""
    cache = backtest_arene_cache.CacheLocale()
    per_slug = collections.defaultdict(list)
    for r in righe:
        per_slug[r['slug']].append(r)

    pronte = []
    for slug, gruppo in per_slug.items():
        if len(gruppo) < MIN_PRESENZE:
            continue
        somma_r = sum(g['reale'] for g in gruppo)
        somma_p = sum(g['atteso'] for g in gruppo)
        n = len(gruppo)
        for g in gruppo:
            # media LASCIA-FUORI-UNO: senza questo, il residuo di una partita
            # entrerebbe nella media da cui viene sottratto e la correlazione
            # con qualunque segnale risulterebbe schiacciata verso il basso
            g['res_reale'] = g['reale'] - (somma_r - g['reale']) / (n - 1)
            g['res_atteso'] = g['atteso'] - (somma_p - g['atteso']) / (n - 1)
            quando = None
            if g.get('data_partita'):
                try:
                    quando = datetime.datetime.strptime(g['data_partita'][:10], '%Y-%m-%d')
                except ValueError:
                    quando = None
            g['quando'] = quando
            if quando is not None:
                g.update(segnali_storico(cache, slug, quando))
                lam_mio, lam_avv = gol_attesi(g.get('squadra'), g.get('opp_slug'),
                                              quando, bool(g.get('in_casa')))
                if lam_mio is not None:
                    g['gol_miei'] = lam_mio
                    g['gol_subiti'] = lam_avv
                    g['gol_totali'] = lam_mio + lam_avv
                    g['favorito'] = lam_mio - lam_avv
            if g.get('in_casa') is not None:
                g['casa'] = 1.0 if g['in_casa'] else 0.0
            pronte.append(g)
    return pronte


def centra_per_giocatore(righe, campo):
    """Toglie la media per giocatore anche al SEGNALE: dentro-giocatore vuol
    dire confrontare le partite di uno con le altre partite dello stesso."""
    per_slug = collections.defaultdict(list)
    for r in righe:
        if r.get(campo) is not None:
            per_slug[r['slug']].append(r)
    x, y = [], []
    for gruppo in per_slug.values():
        if len(gruppo) < MIN_PRESENZE:
            continue
        m = statistics.fmean(g[campo] for g in gruppo)
        for g in gruppo:
            x.append(g[campo] - m)
            y.append(g['res_reale'])
    return x, y


def guadagno_quintili(x, y):
    """Differenza di punteggio reale fra il quinto piu' alto e il piu' basso."""
    coppie = sorted(zip(x, y))
    n = len(coppie)
    if n < 50:
        return None
    q = n // 5
    basso = statistics.fmean(v for _, v in coppie[:q])
    alto = statistics.fmean(v for _, v in coppie[-q:])
    return alto - basso


SEGNALI = [
    ('casa', 'in casa (1) o fuori (0)'),
    ('favorito', 'gol attesi miei meno avversario'),
    ('gol_totali', 'gol attesi totali della partita'),
    ('gol_miei', 'gol attesi della mia squadra'),
    ('gol_subiti', 'gol attesi dell avversario'),
    ('forma', 'forma recente (L5 meno L20)'),
    ('l5', 'media ultime 5'),
    ('minuti', 'minuti medi nelle ultime 5'),
    ('riposo', 'giorni dall ultima partita'),
    ('volatilita', 'dispersione storica'),
    ('res_atteso', 'la previsione del modello di oggi'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join('dati_globali', 'errore_storico.json'))
    ap.add_argument('--ruolo', default=None, help='limita a un ruolo (Forward, Defender, ...)')
    args = ap.parse_args()

    percorso = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
    if not os.path.exists(percorso):
        print(f'manca {percorso}: lancia prima  python errore_modello_storico.py --json {args.json}')
        return 1
    with open(percorso, encoding='utf-8') as f:
        righe = json.load(f)
    if args.ruolo:
        righe = [r for r in righe if r['ruolo'] == args.ruolo]

    print('=' * 88)
    print('SEGNALI DENTRO IL GIOCATORE — cosa prevede lo scarto dalla propria media')
    print('=' * 88)
    pronte = prepara(righe)
    sd = statistics.pstdev([r['res_reale'] for r in pronte])
    print(f'{len(pronte)} partite di {len({r["slug"] for r in pronte})} giocatori con >={MIN_PRESENZE} presenze')
    print(f"dispersione dello scarto da spiegare: {sd:.1f} punti\n")

    print(f"  {'segnale':<34} {'n':>5} {'corr':>7} {'IC 95%':>18} {'guadagno':>9}")
    print('  ' + '-' * 76)
    for campo, etichetta in SEGNALI:
        x, y = centra_per_giocatore(pronte, campo)
        if len(x) < 50:
            print(f"  {etichetta:<34} {len(x):>5}   (campione insufficiente)")
            continue
        c = _corr(x, y)
        if c is None:
            print(f"  {etichetta:<34} {len(x):>5}   (segnale costante)")
            continue
        lo, hi = _ic_corr(x, y)
        ic = f'[{lo:+.3f}, {hi:+.3f}]' if lo is not None else ''
        g = guadagno_quintili(x, y)
        gs = f'{g:+.1f} pt' if g is not None else ''
        print(f"  {etichetta:<34} {len(x):>5} {c:+7.3f} {ic:>18} {gs:>9}")

    print('\nNOTA: la colonna guadagno e la differenza di punteggio REALE medio fra il quinto')
    print('piu alto e il quinto piu basso del segnale, a parita di giocatore.')

    congiunta(pronte)
    per_ruolo(pronte)
    per_profondita(righe, pronte)
    return 0


def _ols(colonne, y):
    """Minimi quadrati con eliminazione di Gauss (poche colonne, niente numpy)."""
    k = len(colonne)
    a = [[sum(colonne[i][t] * colonne[j][t] for t in range(len(y))) for j in range(k)]
         + [sum(colonne[i][t] * y[t] for t in range(len(y)))] for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(a[r][i]))
        if abs(a[p][i]) < 1e-12:
            return None
        a[i], a[p] = a[p], a[i]
        for r in range(k):
            if r == i:
                continue
            f = a[r][i] / a[i][i]
            for c in range(i, k + 1):
                a[r][c] -= f * a[i][c]
    return [a[i][k] / a[i][i] for i in range(k)]


def congiunta(pronte, campi=('casa', 'favorito', 'gol_subiti')):
    """I segnali si sovrappongono (il fattore campo e' dentro i gol attesi):
    qui si stimano insieme, per sapere quanto aggiunge ciascuno agli altri."""
    per_slug = collections.defaultdict(list)
    for r in pronte:
        if all(r.get(c) is not None for c in campi):
            per_slug[r['slug']].append(r)
    righe = [g for gruppo in per_slug.values() if len(gruppo) >= MIN_PRESENZE for g in gruppo]
    if len(righe) < 200:
        print('\nREGRESSIONE CONGIUNTA: campione insufficiente')
        return
    medie = {c: {} for c in campi}
    for slug, gruppo in per_slug.items():
        if len(gruppo) < MIN_PRESENZE:
            continue
        for c in campi:
            medie[c][slug] = statistics.fmean(g[c] for g in gruppo)
    colonne = [[g[c] - medie[c][g['slug']] for g in righe] for c in campi]
    y = [g['res_reale'] for g in righe]
    beta = _ols(colonne, y)
    print(f'\nREGRESSIONE CONGIUNTA dentro-giocatore ({len(righe)} partite)')
    if beta is None:
        print('  sistema singolare')
        return
    for c, b in zip(campi, beta):
        sd = statistics.pstdev([g[c] - medie[c][g['slug']] for g in righe])
        print(f"  {c:<14} coefficiente {b:+7.2f}   effetto di 1 sd del segnale: {b * sd:+.1f} pt")
    stimato = [sum(b * col[t] for b, col in zip(beta, colonne)) for t in range(len(y))]
    c = _corr(stimato, y)
    print(f"  correlazione complessiva del modello congiunto: {c:+.3f}   "
          f"varianza spiegata {c ** 2:.1%} dello scarto")


def per_ruolo(pronte, campo='favorito'):
    print(f'\nIL SEGNALE MIGLIORE ({campo}) PER RUOLO')
    for ruolo in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
        sotto = [r for r in pronte if r['ruolo'] == ruolo]
        x, y = centra_per_giocatore(sotto, campo)
        if len(x) < 80:
            print(f'  {ruolo:<12} campione insufficiente ({len(x)})')
            continue
        c = _corr(x, y)
        lo, hi = _ic_corr(x, y)
        g = guadagno_quintili(x, y)
        ic = f'[{lo:+.3f}, {hi:+.3f}]' if lo is not None else ''
        print(f"  {ruolo:<12} n={len(x):>4}  corr {c:+.3f} {ic}  guadagno {g:+.1f} pt")


def per_profondita(righe, pronte, campo='favorito'):
    """Il modello ordina peggio chi ha poco storico (corr +0.14 contro +0.30):
    quel segmento e' anche quello dove il contesto partita rende di piu'?"""
    print(f'\nPER PROFONDITA DI STORICO — il modello contro il contesto ({campo})')
    con = [r for r in pronte if r.get('partite_storiche') is not None]
    if len(con) < 200:
        return
    con.sort(key=lambda r: r['partite_storiche'])
    n = len(con)
    for i in range(3):
        pezzo = con[i * n // 3:(i + 1) * n // 3]
        x, y = centra_per_giocatore(pezzo, campo)
        c_seg = _corr(x, y) if len(x) >= 80 else None
        c_mod = _corr([r['atteso'] for r in pezzo], [r['reale'] for r in pezzo])
        etichetta = f"{pezzo[0]['partite_storiche']:.0f}-{pezzo[-1]['partite_storiche']:.0f} partite"
        s = f"  {etichetta:<18} n={len(pezzo):>4}  modello (totale) {c_mod:+.3f}"
        s += f"   contesto (dentro) {c_seg:+.3f}" if c_seg is not None else '   contesto: -'
        print(s)


if __name__ == '__main__':
    sys.exit(main())
