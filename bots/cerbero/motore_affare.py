"""
MOTORE AFFARE -- il "cervello" del terzo bot (unificazione Profit + Definitivo).

Funzioni PURE, zero I/O, zero query: si testano offline sul dataset storico
(vedi backtest_e_test.py). Qui vive UNA sola cosa: il GATE TEMPORALE, cioe' il
segnale che Bot Definitivo non ha (dov'e' il prezzo rispetto alla storia RECENTE
della carta) e il filtro di GUADAGNO ASSOLUTO in EUR.

Divisione dei compiti nel bot (regola a due assi, in AND):
  - asse TRASVERSALE (Bot Definitivo, resta nel bot): spread 1o/2o prezzo LIVE ->
    decide se c'e' un mispricing da comprare/offrire ADESSO e a che prezzo (curve
    di margine gia' calibrate sulle preferenze reali dell'utente).
  - asse TEMPORALE (Bot Profit, QUESTO modulo): la carta e' davvero sotto la sua
    media recente? il trend non sta crollando? il guadagno atteso in EUR vale il
    flip? -> se no, si SCARTA anche se lo spread live sembra un affare.

Le soglie sono tarate sul backtest del 03/08 (dataset pattern_raw_transactions,
solo leghe di Profit, 6 giorni) e sono PROVVISORIE: tutte sovrascrivibili da env,
da ritarare con piu' dati. Vedi docs/BOT_TERZO_PROGETTO.md.
"""
import os

# --------------------------------------------------------------------------------------
# Curva del rendimento % atteso a 48h in funzione dello SCONTO temporale (minimo live
# vs media della carta nella finestra recente). Punti = mediane misurate sul backtest
# 03/08 (centro di ogni fascia). In mezzo si interpola linearmente.
#   sconto<0 (sovrapprezzo) -> -6.0% | 0-5% -> -2.1% | 5-10% -> +4.7%
#   10-20% -> +5.5% | >=20% -> +10.4%
# --------------------------------------------------------------------------------------
# Mediane misurate sul dataset a 12 giorni (03/08, 6452 tx uniche, leghe di Profit):
#   sconto<0 -> -6.2% | 0-5% -> -1.7% | 5-10% -> +3.8% | 10-20% -> +5.7% | >=20% -> +16.8%
CURVA_RITORNO_ATTESO = [
    (-10.0, -6.2),
    (0.0, -2.0),
    (2.5, -1.7),
    (7.5, 3.8),
    (15.0, 5.7),
    (25.0, 16.8),
]
CURVA_RITORNO_SLOPE_OLTRE = 0.40   # pendenza prudente oltre il 25% di sconto
CURVA_RITORNO_CAP = 20.0           # tetto: oltre non ci sono dati che reggano

# Finestra di lookback per la media recente della carta. Il backtest mostra che 7gg
# NON e' speciale: 1-2 giorni danno il lift migliore. Default 2gg (robusto).
LOOKBACK_DAYS = float(os.environ.get('TERZO_LOOKBACK_DAYS', '2'))

# Sconto temporale minimo perche' la carta sia "davvero cheap vs se stessa" (sotto,
# il rendimento mediano e' <=0). 5% e' il punto in cui diventa nettamente positivo.
TEMP_DISC_MIN = float(os.environ.get('TERZO_TEMP_DISC_MIN', '5.0'))

# 'down' = sconto sospetto (mercato in caduta): a pari sconto rende meno. Sul dataset
# a 12 giorni down/flat = 7.3/12.7 = 0.57 (a pari sconto>=10%: down +7.3%/61% pos,
# flat +12.7%/70%, up +14.4%/69%) -- meno duro di quanto sembrava sui primi 6 giorni.
# Moltiplicatore prudente 0.6 e override piu' basso (un down con sconto reale >=12%
# resta positivo, non va scartato).
TREND_MULT = {'up': 1.0, 'flat': 1.0, 'down': 0.6, None: 0.85}
TREND_FLAT_THRESHOLD_PERCENT = float(os.environ.get('TERZO_TREND_FLAT_PCT', '5.0'))
DOWN_OVERRIDE_DISC = float(os.environ.get('TERZO_DOWN_OVERRIDE_DISC', '12.0'))

# Guadagno ASSOLUTO minimo atteso (EUR, LORDO) perche' valga il flip. PROVVISORIO.
# TENSIONE MISURATA (backtest 03/08): alzare troppo questa soglia PEGGIORA i risultati
# reali, perche' per superarla con rendimenti % modesti servono carte CARE, dove pero'
# l'edge % e' debole/rumoroso (poche carte, alta varianza). Il vantaggio affidabile sta
# nelle carte scontate a prezzo medio-basso. Sweet spot misurato: 0.30-0.50EUR
# (~+5/+6% mediano, 57% positivi). Oltre 0.75EUR il rendimento realizzato va NEGATIVO.
# Default prudente 0.50 (taglia i micro-flip da centesimi senza spingere sui big cards
# non ancora validati). Da rivedere quando ci saranno piu' dati sulla fascia alta.
MIN_ABS_GAIN_EUR = float(os.environ.get('TERZO_MIN_ABS_GAIN_EUR', '0.50'))

# Fascia prezzo (storica di Definitivo: 1-30). Estendibile senza costo query.
PREZZO_MIN_EUR = float(os.environ.get('TERZO_PREZZO_MIN_EUR', '1.0'))
PREZZO_MAX_EUR = float(os.environ.get('TERZO_PREZZO_MAX_EUR', '30.0'))

# Fee venditore Sorare: chi vende incassa il 95%. Serve per stimare l'utile NETTO.
SORARE_SELLER_NET = 0.95


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def sconto_temporale(prezzo, media_recente):
    """Sconto% del prezzo rispetto alla media recente della carta. None se non
    calcolabile (media assente/<=0)."""
    if media_recente is None or media_recente <= 0 or prezzo is None:
        return None
    return (media_recente - prezzo) / media_recente * 100.0


def rendimento_atteso_percent(sconto_percent, trend=None):
    """Rendimento % atteso a 48h dato lo sconto temporale, modulato dal trend.
    Interpolazione lineare sulla curva misurata, con coda compressa e tetto."""
    if sconto_percent is None:
        return 0.0
    x = sconto_percent
    pts = CURVA_RITORNO_ATTESO
    if x <= pts[0][0]:
        base = pts[0][1]
    elif x >= pts[-1][0]:
        base = min(pts[-1][1] + (x - pts[-1][0]) * CURVA_RITORNO_SLOPE_OLTRE, CURVA_RITORNO_CAP)
    else:
        base = pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                base = y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y0
                break
    return base * TREND_MULT.get(trend, TREND_MULT[None])


def classifica_trend(media_recente, media_piu_vecchia):
    """up/flat/down confrontando la media recente con quella piu' vecchia della
    finestra. None se dati insufficienti."""
    if media_recente is None or media_piu_vecchia is None or media_piu_vecchia <= 0:
        return None
    ch = (media_recente - media_piu_vecchia) / media_piu_vecchia * 100.0
    if ch <= -TREND_FLAT_THRESHOLD_PERCENT:
        return 'down'
    if ch >= TREND_FLAT_THRESHOLD_PERCENT:
        return 'up'
    return 'flat'


def gate_temporale(true_min_price, media_recente, trend,
                    min_abs_gain_eur=None, temp_disc_min=None):
    """GATE dell'asse temporale. Ritorna un dict con il verdetto:
      {'passa': bool, 'motivo': str, 'sconto_temporale': float|None,
       'rendimento_atteso_pct': float, 'guadagno_atteso_eur': float}
    Il bot procede all'esecuzione (asse trasversale/Definitivo) SOLO se passa=True.

    guadagno_atteso_eur e' LORDO sul prezzo del minimo; il bot poi paga meno (offerta
    scontata) e incassa il 95% in rivendita -- questa e' la stima prudente 'a parita'
    di prezzo' per il floor assoluto."""
    min_abs = MIN_ABS_GAIN_EUR if min_abs_gain_eur is None else min_abs_gain_eur
    disc_min = TEMP_DISC_MIN if temp_disc_min is None else temp_disc_min

    disc = sconto_temporale(true_min_price, media_recente)
    if disc is None:
        return {'passa': False, 'motivo': 'nessuno storico recente utilizzabile',
                'sconto_temporale': None, 'rendimento_atteso_pct': 0.0, 'guadagno_atteso_eur': 0.0}

    if not (PREZZO_MIN_EUR <= true_min_price <= PREZZO_MAX_EUR):
        return {'passa': False, 'motivo': f'prezzo {true_min_price:.2f}EUR fuori fascia '
                f'[{PREZZO_MIN_EUR:.0f}-{PREZZO_MAX_EUR:.0f}]',
                'sconto_temporale': disc, 'rendimento_atteso_pct': 0.0, 'guadagno_atteso_eur': 0.0}

    if disc < disc_min:
        return {'passa': False, 'motivo': f'sconto temporale {disc:.1f}% < {disc_min:.0f}% '
                f'(non e\' cheap vs la sua media recente)',
                'sconto_temporale': disc, 'rendimento_atteso_pct': 0.0, 'guadagno_atteso_eur': 0.0}

    if trend == 'down' and disc < DOWN_OVERRIDE_DISC:
        return {'passa': False, 'motivo': f'trend in caduta con sconto {disc:.1f}% < '
                f'{DOWN_OVERRIDE_DISC:.0f}% (sconto sospetto, mercato che scivola)',
                'sconto_temporale': disc, 'rendimento_atteso_pct': 0.0, 'guadagno_atteso_eur': 0.0}

    ret = rendimento_atteso_percent(disc, trend)
    gain = true_min_price * ret / 100.0
    if gain < min_abs:
        return {'passa': False, 'motivo': f'guadagno atteso {gain:.2f}EUR < soglia '
                f'{min_abs:.2f}EUR (utile assoluto troppo piccolo per il flip)',
                'sconto_temporale': disc, 'rendimento_atteso_pct': ret, 'guadagno_atteso_eur': gain}

    return {'passa': True, 'motivo': f'sconto {disc:.1f}%, trend {trend or "n/d"}, '
            f'rendimento atteso {ret:.1f}% ({gain:.2f}EUR)',
            'sconto_temporale': disc, 'rendimento_atteso_pct': ret, 'guadagno_atteso_eur': gain}
