"""Le starterOdds dicono la verita'? Calibrazione reale per SQUADRA.

Confronta le odds storicizzate da discovery_fixture (dati_globali/storico_odds/)
con quello che e' poi successo davvero, letto dai detail cache: un giocatore ha
"giocato da titolare" se risulta con almeno MIN_MINUTI minuti in quella
giornata.

L'unita' e' la SQUADRA, non il campionato (indicazione dell'utente): ogni
"odder" segue una o poche squadre, raramente un campionato intero. Aggregando
per lega si mescolerebbero fornitori diversi e il bias si annacquerebbe.

Il singolo giocatore sarebbe ancora piu' informativo ma ha troppe poche
partite: si stima per giocatore e lo si TIRA verso la sua squadra in modo
proporzionale alle osservazioni (stesso shrinkage gia' usato per il prior di
ruolo).

Uso:  python misura_calibrazione_odds.py
"""
import collections
import glob
import json
import os

MIN_MINUTI = float(os.environ.get('MIN_MINUTI', '60'))
FASCE = [(0.0, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]


def minuti_per_giocatore():
    """(slug, data) -> minuti giocati, dai detail cache."""
    out = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict):
                continue
            g = v.get('anyGame') or {}
            data = (g.get('date') or '')[:10]
            if not data:
                continue
            mins = 0.0
            for riga in (v.get('detailedScore') or []):
                if riga.get('stat') == 'mins_played':
                    mins = riga.get('statValue') or 0.0
            out[(slug, data)] = mins
    return out


def club_dei_giocatori():
    """slug -> club, dedotto dalla squadra presente in tutte le sue partite."""
    import collections as _c
    viste = _c.defaultdict(_c.Counter)
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict):
                continue
            g = v.get('anyGame') or {}
            h = (g.get('homeTeam') or {}).get('slug')
            a = (g.get('awayTeam') or {}).get('slug')
            if h and a:
                viste[slug][h] += 1
                viste[slug][a] += 1
    return {s: c.most_common(1)[0][0] for s, c in viste.items() if c}


K_SHRINK = float(os.environ.get('K_SHRINK', '8'))


def main():
    file_odds = sorted(glob.glob('dati_globali/storico_odds/*.json'))
    if not file_odds:
        print("Nessuna odds storicizzata ancora: serve almeno una run di "
              "discovery_fixture dopo il 01/08.")
        return
    minuti = minuti_per_giocatore()
    club_di = club_dei_giocatori()

    # osservazioni: (club, slug, odds_dichiarata, ha_giocato_titolare)
    oss = []
    for f in file_odds:
        try:
            dati = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for _lega, ruoli in (dati or {}).items():
            for _ruolo, righe in (ruoli or {}).items():
                for slug, odds in (righe or {}).items():
                    esiti = [m for (s, _d), m in minuti.items() if s == slug]
                    if not esiti:
                        continue
                    oss.append((club_di.get(slug, '?'), slug, odds,
                                max(esiti) >= MIN_MINUTI))
    if not oss:
        print('Odds storicizzate presenti ma nessun esito ancora osservabile.')
        return

    per_club = collections.defaultdict(lambda: [0, 0, 0.0])
    per_giocatore = collections.defaultdict(lambda: [0, 0, 0.0])
    for club, slug, odds, tit in oss:
        for chiave, d in ((club, per_club), (slug, per_giocatore)):
            d[chiave][0] += 1
            d[chiave][1] += 1 if tit else 0
            d[chiave][2] += odds
    globale = sum(1 for *_x, t in oss if t) / len(oss)

    print(f'osservazioni: {len(oss)} | tasso titolarita globale {globale:.0%}\n')
    print("=== per SQUADRA (l'odder segue la squadra)")
    for club, (n, ok, somma) in sorted(per_club.items(), key=lambda x: -x[1][0]):
        if n < 5:
            continue
        dich, reale = somma / n, ok / n
        print(f'  {club:38s} dichiarato {dich:.0%} -> reale {reale:.0%}  '
              f'scarto {reale-dich:+.0%}  (n={n})')

    print('\n=== per GIOCATORE (tirato verso la sua squadra, k=%g)' % K_SHRINK)
    righe = []
    for slug, (n, ok, somma) in per_giocatore.items():
        club = club_di.get(slug, '?')
        cn, cok, _cs = per_club.get(club, [0, 0, 0.0])
        base = (cok / cn) if cn else globale
        w = n / (n + K_SHRINK)
        stima = w * (ok / n) + (1 - w) * base
        righe.append((abs(stima - somma / n), slug, somma / n, stima, n))
    for _d, slug, dich, stima, n in sorted(righe, reverse=True)[:15]:
        print(f'  {slug:34s} dichiarato {dich:.0%} -> stimato {stima:.0%}  (n={n})')


if __name__ == '__main__':
    main()
