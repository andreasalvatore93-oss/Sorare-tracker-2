"""Incrocia i consigli K League con le formazioni di SportsGambler.

  python kleague_lineup_check.py            # partite future
  python kleague_lineup_check.py --retro    # partite gia' giocate, verifica a posteriori

Le formazioni non stanno nell'HTML: arrivano da /lineups/lineups-load2.php?id=N.
Le partite future NON hanno id finche' la formazione non esce (vicino al calcio
d'inizio), quindi in modalita' normale il tool va lanciato poco prima.

La romanizzazione coreana non coincide fra Sorare e SportsGambler
(cheong-hyo-park / Chung-Hyo Park): confronto per token con tolleranza.
"""
import datetime
import difflib
import glob
import html
import os
import re
import sys

BASE = 'https://www.sportsgambler.com'
INDICE = f'{BASE}/lineups/football/south-korea-k-league-1/'
RUOLI = ('gk', 'def', 'mid', 'fwd')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()


def _get(url, **kw):
    return _S.get(url, timeout=60,
                  headers={'Referer': INDICE, 'X-Requested-With': 'XMLHttpRequest'},
                  **kw).text


def fixtures():
    """[(data, casa, trasferta, id|None)] dalla pagina indice."""
    t = _get(INDICE)
    parti = re.split(r'<h3 class="date-headline">([^<]+)</h3>', t)
    out = []
    for i in range(1, len(parti), 2):
        data, corpo = parti[i].strip(), parti[i + 1]
        for blocco in re.split(r'<!--table row-->', corpo):
            m = re.search(r'fxs-team home">([^<]*)<.*?fxs-team">([^<]*)<', blocco, re.S)
            if not m:
                continue
            mid = re.search(r'reply_click\((\d+)\)', blocco)
            out.append((data, m.group(1).strip(), m.group(2).strip(),
                        mid.group(1) if mid else None))
    return out


def formazione(mid):
    t = _get(f'{BASE}/lineups/lineups-load2.php', params={'id': mid})
    testate = re.findall(r'<h3><span>([^<]+?)\s+(Confirmed|Predicted)\s+Lineup</span>', t)
    nomi = [html.unescape(n).strip() for n in re.findall(r'class="player-name[^"]*">([^<]+)', t)]
    if len(testate) < 2 or len(nomi) < 22:
        return None
    meta = len(nomi) // 2
    return {'stato': testate[0][1],
            'xi': {testate[0][0]: nomi[:meta], testate[1][0]: nomi[meta:]}}


def _tok(s):
    return [x for x in re.split(r'[^a-z]+', s.lower()) if len(x) > 1]


def _simile(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def stessa_persona(slug, nome):
    ts = _tok(re.sub(r'-\d{4}-\d{2}-\d{2}$', '', slug))
    tn = _tok(nome)
    if not ts or not tn:
        return False
    presi = sum(1 for a in ts if any(_simile(a, b) for b in tn))
    return presi >= max(2, min(len(ts), len(tn)) - 1)


def punteggio_squadra(slug, nome):
    ts, tn = _tok(slug), _tok(nome)
    return max((difflib.SequenceMatcher(None, a, b).ratio() for a in ts for b in tn),
               default=0.0)


def consigli(ruolo, giorno=None):
    """Righe dell'ultimo consiglio del ruolo (o dell'ultimo di quel giorno)."""
    fs = sorted(glob.glob(f'formazione_kleague/output/kleague_{ruolo}_all/consiglio_*.txt'))
    if giorno:
        fs = [f for f in fs if giorno in os.path.basename(f)]
    if not fs:
        return None
    testo = open(fs[-1], encoding='utf-8', errors='replace').read()
    righe = []
    for m in re.finditer(
            r'^\s*\d+\)\s*([a-z][a-z0-9-]*):\s*(\d+)\s*pt.*?\n\s*SQUADRA:\s*(\S+)\s*\|\s*AVVERSARIO:\s*(\S+)',
            testo, re.M | re.S):
        slug, pt, squadra, avv = m.groups()
        righe.append({'slug': slug, 'pt': int(pt), 'squadra': squadra, 'avversario': avv})
    return righe, os.path.basename(fs[-1])


def _stato_giocatore(riga, xi_per_squadra):
    """(esito, squadra_sg) confrontando con la squadra piu' somigliante."""
    migliore, punteggio = None, 0.0
    for squadra in xi_per_squadra:
        p = punteggio_squadra(riga['squadra'], squadra)
        if p > punteggio:
            migliore, punteggio = squadra, p
    if migliore is None or punteggio < 0.6:
        return None, None
    titolare = any(stessa_persona(riga['slug'], n) for n in xi_per_squadra[migliore])
    return ('TITOLARE' if titolare else 'non in XI'), migliore


MESI = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5,
        'June': 6, 'July': 7, 'August': 8, 'September': 9, 'October': 10,
        'November': 11, 'December': 12}


def _data_fixture(testo, anno=2026):
    m = re.search(r'(\d{1,2})\s+(\w+)', testo)
    if not m or m.group(2) not in MESI:
        return None
    return datetime.date(anno, MESI[m.group(2)], int(m.group(1)))


def modalita_futura(ruoli):
    """SOLO le partite ancora da giocare. Le passate hanno gia' un XI, ma
    confrontarci i consigli di oggi non significa nulla: e' l'errore fatto
    il 01/08 (risultati presi dalle giornate del 25-26 luglio)."""
    oggi = datetime.date.today()
    fx = [f for f in fixtures() if (_data_fixture(f[0]) or oggi) >= oggi]
    pronti = [f for f in fx if f[3] is not None]
    print(f'{len(fx)} partite da giocare: {len(pronti)} con formazione pubblicata.')
    if not pronti:
        print('Nessuna formazione ancora pubblicata per le partite future.')
        print('Prossime: ' + ', '.join(f'{c} vs {f}' for _d, c, f, _i in fx[:4]))
        print("Gli XI compaiono vicino al calcio d'inizio: riprovare piu' tardi.")
        return
    xi = {}
    for _d, casa, fuori, mid in pronti:
        f = formazione(mid)
        if f:
            xi.update(f['xi'])
            print(f'  {casa} vs {fuori}: {f["stato"]}')
    for ruolo in ruoli:
        d = consigli(ruolo)
        if not d:
            continue
        righe, fname = d
        print(f'\n=== {ruolo.upper()} ({fname}) ===')
        for r in righe[:12]:
            esito, squadra = _stato_giocatore(r, xi)
            print(f"  {r['pt']:>3} pt  {r['slug']:<34} "
                  f"{esito + ' (' + squadra + ')' if esito else 'formazione non pubblicata'}")


def modalita_retro(ruoli, giorno='2026-07-26', top=None):
    """Quante volte i consigliati di quel giorno sono davvero partiti titolari."""
    giorno_sg = {'2026-07-26': 'Sunday 26 July', '2026-07-25': 'Saturday 25 July',
                 '2026-07-22': 'Wednesday 22 July', '2026-07-19': 'Sunday 19 July',
                 '2026-07-18': 'Saturday 18 July'}[giorno]
    fx = [f for f in fixtures() if f[3] is not None and f[0] == giorno_sg]
    xi = {}
    for _d, casa, fuori, mid in fx:
        f = formazione(mid)
        if f and f['stato'] == 'Confirmed':
            xi.update(f['xi'])
    print(f'XI confermati raccolti per {len(xi)} squadre (partite di luglio).\n')

    tot_t = tot_n = 0
    for ruolo in ruoli:
        d = consigli(ruolo, giorno=giorno)
        if not d:
            print(f'[{ruolo}] nessun consiglio del {giorno}.')
            continue
        righe, fname = d
        t = n = 0
        dettagli = []
        for r in (righe[:top] if top else righe):
            esito, squadra = _stato_giocatore(r, xi)
            if esito is None:
                continue
            if esito == 'TITOLARE':
                t += 1
            else:
                n += 1
                dettagli.append(f"{r['pt']}pt {r['slug']}")
        tot_t += t
        tot_n += n
        if t + n:
            print(f'{ruolo.upper():4s} {fname}: titolari {t}/{t+n} ({t/(t+n)*100:.0f}%)')
            if dettagli:
                print('     non titolari:', ', '.join(dettagli[:6]))
    if tot_t + tot_n:
        print(f'\nTOTALE: {tot_t}/{tot_t+tot_n} consigliati partiti titolari '
              f'({tot_t/(tot_t+tot_n)*100:.0f}%)')


if __name__ == '__main__':
    args = sys.argv[1:]
    ruoli = [a for a in args if a in RUOLI] or list(RUOLI)
    if '--retro' in args:
        top = next((int(a.split('=')[1]) for a in args if a.startswith('--top=')), None)
        modalita_retro(ruoli, top=top)
    else:
        modalita_futura(ruoli)
