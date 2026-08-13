"""Il livello di ogni campionato, ruolo per ruolo.

A COSA SERVE. Lo shrinkage dei predict tira la previsione verso un "prior"
di ruolo che oggi e' lo stesso per tutte e 53 le leghe (47.44 + 6.62 *
presence_rate). Misurato il 13/08/2026 sulla cache dei game-log: le leghe
NON sono uguali affatto -- un centrocampista prende in media 58.6 punti in
Chinese Super League e 49.8 in Liga. Chi cambia campionato si porta dietro
solo il ~20% del vantaggio che aveva nella lega vecchia (584 casi, verifica
fuori campione su 120 mai visti), quindi l'ancora giusta e' il livello del
campionato in cui il giocatore GIOCA ADESSO, non una media mondiale.

COME SI STIMA, e perche' NON con la media grezza (13/08/2026, obiezione
dell'utente che ha corretto una prima versione sbagliata di questo file).
La media dei punteggi di una lega confonde due cose diverse: quanto quella
lega e' generosa, e quanto sono forti i giocatori che ne abbiamo in cache.
Sulle leghe poco coperte la seconda domina -- la Russia stava in cima con
OTTO centrocampisti. Qui invece si stimano INSIEME la bravura di ogni
giocatore e l'effetto di ogni lega, a giri alterni:
    punteggio = media generale + bravura(giocatore) + effetto(lega)
finche' i numeri si fermano. A tenere in piedi il confronto fra leghe sono
i giocatori che hanno giocato in due leghe diverse ("ponti"), contati e
riportati per ogni voce.
Quanto cambia: la Premier League passa da -2.1 grezzo a -9.5 pulito per gli
attaccanti -- non e' un'approssimazione diversa, e' un'altra cosa. Li'
giocano i piu' forti del mondo, quindi la media grezza sembra normale
mentre lo STESSO giocatore fa 9 punti in meno che altrove.

COSA PRODUCE. dati_globali/livello_lega_ruolo.json:
  {"per_lega_ruolo": {"spagna|FWD": {"media": -4.21, "n": 1572,
                                     "giocatori": 108, "ponti": 39}, ...},
   "per_ruolo": {"FWD": {"media": 0.0}},   <- l'ancora: lega media = 0
   "generato": "...", "min_partite": 200, "min_giocatori": 30}
I valori sono SCARTI dalla lega media (0 = lega media), non medie assolute:
chi legge somma lo scarto al prior che gia' usa.

COME SI RILANCIA.  python dati_globali/costruisci_livello_lega_ruolo.py
Zero query di rete: legge solo la cache game-log gia' in repo. Va rilanciato
ogni tanto (i livelli si muovono con le stagioni), non ad ogni run.

SCELTE, e perche'.
  - solo partite da titolare (>= 60 minuti): il punteggio di chi entra
    all'85esimo dice quanto ha giocato, non quanto vale la lega;
  - solo scoreStatus FINAL: i DID_NOT_PLAY sono zeri che sposterebbero la
    media di una lega in base a quanti panchinari abbiamo in cache;
  - solo le 53 leghe di LEAGUE_DIR: coppe e continentali mescolano squadre
    di campionati diversi, che e' esattamente cio' che qui si vuole separare;
  - una cella vale solo con almeno MIN_PARTITE partite, altrimenti si
    ricade sul livello del solo ruolo (e chi legge deve gestire il None).
"""
import os
import re
import sys
import json
import datetime
import collections

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_PARTITE = 200
MIN_GIOCATORI = 30   # una media fatta da 8 persone non entra in produzione
MIN_MINUTI = 60
GIRI = 60            # i numeri si fermano molto prima, 60 e' abbondanza
RUOLI = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}

# CARTELLE CHE SONO LO STESSO CAMPIONATO (13/08/2026, detto dall'utente).
# 'giappone100' e' la J1 100 Year Vision: una competizione breve giocata
# PRIMA della J1 che sta partendo ora, stesse identiche squadre. In
# LEAGUE_DIR sono due cartelle diverse (servono alla pipeline), ma per il
# livello di gioco sono una cosa sola: tenendole separate ogni giapponese
# risultava "cambiato lega" a meta' 2026, e la correzione gli scattava
# addosso per niente (caso reale trovato: hiiro-komori).
# Chi legge la tabella NON deve saperlo: l'elenco finisce dentro il JSON
# prodotto, sotto 'alias', e le voci sono gia' unite.
LEGHE_EQUIVALENTI = {'giappone100': 'giappone'}


DEST = os.path.join(REPO_ROOT, 'dati_globali', 'livello_lega_ruolo.json')


def normalizza(cartella):
    return LEGHE_EQUIVALENTI.get(cartella, cartella)


def leghe_note():
    """competizione Sorare -> cartella del repo, letta da LEAGUE_DIR invece
    che ricopiata: se domani si aggiunge una lega, questo script la vede.

    LA CHIAVE E' LA CARTELLA, non lo slug della competizione. Motivo: e' la
    cartella cio' che i predict di produzione si passano da soli
    (`league='spagna'` nella firma di formazione_spagna/predict/...), quindi
    e' l'unica chiave con cui la tabella si puo' consultare a runtime.
    Le divisioni restano separate -- spagna=laliga-es, spagna2=segunda-
    division-es, inghilterra=premier-league, inghilterra2=championship --
    che e' esattamente la distinzione che serve. L'unica cartella con due
    competizioni e' 'mls' (major-league-soccer e mlspa, la stessa lega con
    due slug), e li' l'unione e' quella giusta."""
    testo = open(os.path.join(REPO_ROOT, 'discovery_fixture.py'), encoding='utf-8').read()
    blocco = re.search(r'LEAGUE_DIR\s*=\s*\{(.*?)\n\}', testo, re.S)
    if not blocco:
        raise SystemExit("LEAGUE_DIR non trovato in discovery_fixture.py")
    return dict(re.findall(r"'([a-z0-9\-]+)'\s*:\s*'([a-z0-9_]+)'", blocco.group(1)))


def raccogli(leghe, fino_a=None):
    """ruolo -> lista di (giocatore, cartella, punteggio). `leghe` e' la mappa
    competizione->cartella. `fino_a` (AAAA-MM-GG) serve ai backtest
    walk-forward: esclude tutto cio' che e' successo dopo.

    Serve il GIOCATORE su ogni riga, non solo il punteggio: e' l'ingrediente
    che permette di separare la bravura dalla lega (vedi in cima al file)."""
    celle = collections.defaultdict(list)
    visti = set()
    for radice, _dirs, files in os.walk(REPO_ROOT):
        if '.game_log_cache' not in radice:
            continue
        for nome in files:
            if not nome.endswith('_gamelog.json'):
                continue
            slug = nome[:-len('_gamelog.json')]
            if slug in visti:
                continue
            visti.add(slug)
            try:
                with open(os.path.join(radice, nome), encoding='utf-8') as f:
                    d = json.load(f)
            except Exception:
                continue
            for v in d.values():
                g = v.get('anyGame') or {}
                comp = (g.get('competition') or {}).get('slug')
                stat = v.get('anyPlayerGameStats') or {}
                if (comp not in leghe or v.get('scoreStatus') != 'FINAL'
                        or (stat.get('minsPlayed') or 0) < MIN_MINUTI
                        or v.get('score') is None or not g.get('date')):
                    continue
                if fino_a and g['date'][:10] >= fino_a:
                    continue
                ruolo = RUOLI.get(v.get('positionTyped'))
                if ruolo:
                    celle[ruolo].append((slug, normalizza(leghe[comp]), v['score']))
    return celle


def effetti_lega(righe):
    """Separa la bravura dei giocatori dall'effetto della lega, a giri
    alterni. Ritorna (media_generale, {lega: effetto}), con gli effetti
    ancorati a media pesata zero: 'effetto 0' = lega media."""
    mu = sum(r[2] for r in righe) / len(righe)
    per_lega, per_gioc = collections.defaultdict(list), collections.defaultdict(list)
    for i, (gio, lega, _sc) in enumerate(righe):
        per_lega[lega].append(i)
        per_gioc[gio].append(i)
    eff = {l: 0.0 for l in per_lega}
    brav = {g: 0.0 for g in per_gioc}
    for _giro in range(GIRI):
        for gio, idx in per_gioc.items():
            brav[gio] = sum(righe[i][2] - mu - eff[righe[i][1]] for i in idx) / len(idx)
        nuovi = {l: sum(righe[i][2] - mu - brav[righe[i][0]] for i in idx) / len(idx)
                 for l, idx in per_lega.items()}
        tot = sum(len(per_lega[l]) for l in nuovi)
        centro = sum(nuovi[l] * len(per_lega[l]) for l in nuovi) / tot
        eff = {l: v - centro for l, v in nuovi.items()}
    return mu, eff


def costruisci(fino_a=None):
    celle = raccogli(leghe_note(), fino_a)
    per_lega_ruolo, per_ruolo = {}, {}
    for ruolo, righe in celle.items():
        mu, eff = effetti_lega(righe)
        per_ruolo[ruolo] = {'media': 0.0, 'media_generale': round(mu, 2), 'n': len(righe)}
        conta = collections.Counter(r[1] for r in righe)
        gioc = collections.defaultdict(set)
        leghe_di = collections.defaultdict(set)
        for gio, lega, _sc in righe:
            gioc[lega].add(gio)
            leghe_di[gio].add(lega)
        ponti = collections.Counter()
        for gio, lg in leghe_di.items():
            if len(lg) > 1:
                for l in lg:
                    ponti[l] += 1
        for lega, n in conta.items():
            if n < MIN_PARTITE or len(gioc[lega]) < MIN_GIOCATORI:
                continue
            per_lega_ruolo[f'{lega}|{ruolo}'] = {
                'media': round(eff[lega], 2), 'n': n,
                'giocatori': len(gioc[lega]), 'ponti': ponti.get(lega, 0),
                'media_grezza': round(sum(righe[i][2] for i in range(len(righe))
                                          if righe[i][1] == lega) / n, 2)}
    return {
        'per_lega_ruolo': per_lega_ruolo,
        'per_ruolo': per_ruolo,
        'alias': LEGHE_EQUIVALENTI,
        'min_giocatori': MIN_GIOCATORI,
        'min_partite': MIN_PARTITE,
        'min_minuti': MIN_MINUTI,
        'fino_a': fino_a,
        'generato': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


if __name__ == '__main__':
    fino_a = sys.argv[1] if len(sys.argv) > 1 else None
    dati = costruisci(fino_a)
    with open(DEST, 'w', encoding='utf-8') as f:
        json.dump(dati, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"celle tenute (>= {MIN_PARTITE} partite E >= {MIN_GIOCATORI} giocatori): "
          f"{len(dati['per_lega_ruolo'])}")
    for ruolo, voce in sorted(dati['per_ruolo'].items()):
        righe = [(k.split('|')[0], v) for k, v in dati['per_lega_ruolo'].items()
                 if k.endswith('|' + ruolo)]
        righe.sort(key=lambda r: -r[1]['media'])
        if not righe:
            continue
        print(f"\n{ruolo}: media generale {voce['media_generale']} punti (n={voce['n']})"
              + ("   [PORTIERI: fuori produzione, vedi in cima]" if ruolo == 'GK' else ""))
        print(f"   {'lega':14} {'effetto':>8} {'grezzo':>8} {'part.':>7} {'gioc.':>6} {'ponti':>6}")
        for lega, v in righe:
            print(f"   {lega:14} {v['media']:+8.2f} "
                  f"{v['media_grezza'] - voce['media_generale']:+8.2f} "
                  f"{v['n']:7} {v['giocatori']:6} {v['ponti']:6}")
    print(f"\nscritto: {os.path.relpath(DEST, REPO_ROOT)}")
