# -*- coding: utf-8 -*-
"""Il segnale "forza del reparto avversario in VOTI SORARE" (filone intralega,
13/08/2026). NON e' in produzione: esiste per essere misurato dal banco di
prova con gli aggiustamenti avversario ACCESI, che e' l'unico modo onesto di
chiedere "aggiunge qualcosa a quello che il modello sa gia'?".

DA DOVE VIENE. `analisi_manager/dati/intralega_serie.json`, prodotto a zero
query da `analisi_manager/p33_intralega_dataset.py` scandendo la cache
game-log: per ogni (lega, squadra, reparto) la serie storica del voto medio
dei TITOLARI (>=60 minuti) di quel reparto, una voce per partita.

PERCHE' LA NORMALIZZAZIONE E' MONDIALE E NON PER LEGA. L'ipotesi di partenza
dell'utente era il contrario (normalizzare dentro il campionato), ed e' stata
misurata e BOCCIATA: 4 celle su 4, la normalizzazione mondiale correla di piu'
col voto vero (p34_intralega_gate.py). La differenza fra campionati porta
informazione vera e cancellarla butta segnale. Stessa scelta, per lo stesso
motivo, di GLOBAL_MEAN_CONCEDED in opponent_strength.py.

MEDIA/SD FISSE, non ricalcolate ad ogni chiamata: se cambiassero con la cache
disponibile, la stessa partita avrebbe uno z diverso da una run all'altra e
nessuna taratura sarebbe riproducibile. Stesso principio di
GLOBAL_MEAN_CONCEDED/GLOBAL_STD_CONCEDED.
"""
import os
import json
import datetime
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
SERIE_PATH = os.path.join(_HERE, 'analisi_manager', 'dati', 'intralega_serie.json')

N_GARE_DEFAULT = 10
# Sotto questa soglia niente correzione: e' il caso "Racing Santander
# neopromosso" indicato dall'utente -- squadra senza storico in quella lega,
# nessun confronto possibile, si lascia tutto com'e'.
MIN_PARTITE_SERIE = 5

_SERIE = None
_STAT = {}


def _carica():
    global _SERIE
    if _SERIE is not None:
        return _SERIE
    try:
        with open(SERIE_PATH, encoding='utf-8') as fh:
            _SERIE = json.load(fh)['serie']
    except (OSError, json.JSONDecodeError):
        _SERIE = {}
    return _SERIE


def _media_sd_globali(reparto):
    """Media e deviazione standard MONDIALI del voto di reparto, su tutte le
    leghe. Calcolate una volta e tenute in memoria."""
    if reparto in _STAT:
        return _STAT[reparto]
    valori = []
    for chiave, punti in _carica().items():
        if chiave.rsplit('|', 1)[-1] != reparto:
            continue
        valori.extend(v for _d, v in punti)
    if len(valori) < 2:
        _STAT[reparto] = (0.0, 0.0)
        return _STAT[reparto]
    m = sum(valori) / len(valori)
    sd = (sum((v - m) ** 2 for v in valori) / (len(valori) - 1)) ** 0.5
    _STAT[reparto] = (m, sd)
    return _STAT[reparto]


def z_reparto(lega, squadra, reparto, quando, n_gare=N_GARE_DEFAULT):
    """Quanto e' forte quel reparto di quella squadra PRIMA di `quando`, in
    deviazioni standard dalla media mondiale del reparto.

    `quando`: datetime o date. Si usano solo le partite STRETTAMENTE
    precedenti (walk-forward: mai la partita che si sta prevedendo).
    Ritorna None se il dato non basta -- e None vuol dire "nessuna
    correzione", mai "correzione zero travestita".
    """
    if not lega or not squadra:
        return None
    punti = _carica().get(f'{lega}|{squadra}|{reparto}')
    if not punti:
        return None
    limite = quando.date().isoformat() if hasattr(quando, 'date') else str(quando)[:10]
    passate = [v for d, v in punti if d < limite]
    if len(passate) < MIN_PARTITE_SERIE:
        return None
    ultime = passate[-n_gare:]
    media = sum(ultime) / len(ultime)
    m, sd = _media_sd_globali(reparto)
    if sd <= 0:
        return None
    return (media - m) / sd


def copertura():
    """Diagnostica: quante serie e quante partite ci sono dentro."""
    serie = _carica()
    per_reparto = defaultdict(int)
    for chiave, punti in serie.items():
        per_reparto[chiave.rsplit('|', 1)[-1]] += len(punti)
    return {'serie': len(serie), 'partite_per_reparto': dict(per_reparto),
            'stat': {r: _media_sd_globali(r) for r in ('def', 'fwd')}}


if __name__ == '__main__':
    import pprint
    pprint.pprint(copertura())
    print(z_reparto('spagna', 'villarreal-villarreal', 'def',
                    datetime.date(2026, 5, 1)))
