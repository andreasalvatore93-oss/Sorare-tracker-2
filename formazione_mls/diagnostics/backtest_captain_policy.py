"""
Backtest Captain Policy (04/08, seguito filone capitano)

Harness riusabile per confrontare policy di scelta capitano alternative
contro la regola attuale di produzione (`pick_captain()`: max atteso grezzo
tra i movimento, GK escluso). Riusa l'infrastruttura gia' scritta per
`backtest_arene_produzione.bilancio_stesse_carte` (P.score_atteso,
B.inizio_giornata, B.fine_giornate) invece di riscriverla -- generalizza la
logica gia' fatta (e poi cancellata) nella sessione precedente per il test
del bias di ruolo su 513 formazioni.

Fonti di formazioni REALI (stesso schema carte: slug/nome/ruolo/capitano/
punteggio), nessuna nuova query:
  - mie: dati_globali/arene_formazioni.json['formazioni'] (593 voci)
  - forever-young: dati_globali/manager_forever-young.json['giornate']
  - crowss: dati_globali/manager_crowss.json['giornate'] (mai usato prima)

Per ogni formazione valutabile: calcola l'atteso walk-forward (stessi
parametri di produzione, `P.score_atteso`) per ogni carta non-GK, poi
applica ciascuna policy e somma il bonus REALE catturato (0.2 * reale del
capitano scelto) su tutte le formazioni. Bootstrap sulle differenze
per-formazione (stesso approccio di `intervallo_media` in backtest_arene.py).

Uso: python formazione_mls/diagnostics/backtest_captain_policy.py
"""
import os
import sys
import glob
import random
import bisect
import datetime
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B
import backtest_arene_produzione as BP

MOLTIPLICATORE_CAPITANO = BP.MOLTIPLICATORE_CAPITANO
_RUOLO_TO_CODICE = BP._RUOLO_TO_CODICE

BIAS_RUOLO = {'DEF': -8.37, 'MID': -6.00, 'FWD': -7.37}  # gia' misurato, zona capitano
MIN_STORICO_USCITA = 6


def _stat(dettaglio, nome):
    for riga in dettaglio:
        if riga.get('stat') == nome:
            return riga.get('statValue', 0.0) or 0.0
    return None


def tasso_uscita_precoce(cache, slug, cutoff):
    """Frazione di partite storiche (prima di `cutoff`) uscite con
    mins_played<60 -- proxy del rischio 'sostituito presto', diverso dalla
    volatilita' del punteggio gia' testata (quella guarda la dispersione del
    punteggio finale, non il minutaggio)."""
    valori = []
    for v in cache.dettagli(slug).values():
        g = v.get('anyGame')
        if not g or v.get('scoreStatus') not in ('FINAL', 'REVIEWING'):
            continue
        data = P._data(v)
        if data is None or not (data < cutoff):
            continue
        ds = v.get('detailedScore')
        if not ds:
            continue
        minuti = _stat(ds, 'mins_played')
        if minuti is None:
            continue
        valori.append(minuti)
    if len(valori) < MIN_STORICO_USCITA:
        return None
    return sum(1 for m in valori if m < 60) / len(valori)


def dev_std_storica(cache, slug, cutoff, ultimi=15):
    """Deviazione standard dei punteggi storici del giocatore prima del
    cutoff -- la VOLATILITA' del singolo, che serve alle policy che cercano
    (o evitano) varianza a seconda del premio in palio."""
    validi = [n.get('score') or 0.0 for n in cache.gamelog(slug)
              if (P._data(n) or cutoff) < cutoff
              and n.get('scoreStatus') in ('FINAL', 'REVIEWING')]
    ultimi_n = validi[-ultimi:]
    if len(ultimi_n) < 4:
        return None
    return statistics.pstdev(ultimi_n)


_FORZE_GOL = None


def _forze_checkpoint():
    """Checkpoint settimanali di ForzaSquadre (modello_partita), stesso
    pattern gia' in produzione per _pcs_squadra (GK team clean sheet) --
    qui riusato per i gol totali attesi della partita (idea 'ambiente gol')."""
    global _FORZE_GOL
    if _FORZE_GOL is None:
        import modello_partita as mp
        oss = mp.osservazioni(mp.partite_da_cache())
        oss.sort(key=lambda o: o['data'])
        darr = [o['data'] for o in oss]
        cps, fz = [], []
        if oss:
            d = oss[0]['data']
            while d <= oss[-1]['data'] + datetime.timedelta(days=7):
                lo = bisect.bisect_left(darr, d)
                if lo >= 400:
                    cps.append(d)
                    fz.append(mp.stima(oss[:lo], riferimento=d,
                                       regolarizzazione=0.30, emivita=120.0))
                d += datetime.timedelta(days=7)
        _FORZE_GOL = (cps, fz)
    return _FORZE_GOL


def gol_totali_attesi(squadra, opp_slug, cutoff, in_casa):
    cps, fz = _forze_checkpoint()
    if not cps or not squadra or not opp_slug or cutoff is None:
        return None
    try:
        co = datetime.datetime.strptime(str(cutoff)[:10], '%Y-%m-%d')
    except ValueError:
        return None
    i = bisect.bisect_right(cps, co) - 1
    if i < 0:
        return None
    f = fz[i]
    if not (f.conosciuta(squadra) and f.conosciuta(opp_slug)):
        return None
    lam_mio = f.lambda_atteso(squadra, opp_slug, in_casa=in_casa)
    lam_avv = f.lambda_atteso(opp_slug, squadra, in_casa=not in_casa)
    return lam_mio + lam_avv


def carica(path):
    return BP.carica(path)


def _reale(g):
    p = g.get('punteggio')
    if p is None:
        return None
    return p / MOLTIPLICATORE_CAPITANO if g.get('capitano') else p


def raccogli_formazioni():
    """Ritorna lista di formazioni {fixture, giocatori, fonte, competizione,
    piazzamento}, dalle 3 fonti.

    `competizione`/`piazzamento` servono a captain_per_competizione.py: la
    domanda "il capitano migliore dipende dal tipo di premio?" ha senso solo
    sapendo in che competizione si giocava e in che posizione si e' finiti.
    Le formazioni mie (arene_formazioni.json) non hanno il campo
    competizione: si usa il tipo dell'arena, che e' l'informazione
    equivalente li'."""
    out = []
    mie = carica('dati_globali/arene_formazioni.json')['formazioni']
    for v in mie.values():
        if v.get('giocatori'):
            out.append({'fixture': v['fixture'], 'giocatori': v['giocatori'], 'fonte': 'mie',
                        'competizione': v.get('tipo'), 'slug_arena': v.get('slug'),
                        'rank_reale': v.get('mio_rank'), 'punteggio_reale': v.get('mio_score')})

    for fonte, path in (('forever-young', 'dati_globali/manager_forever-young.json'),
                        ('crowss', 'dati_globali/manager_crowss.json')):
        d = carica(path)
        for fixture, arene in d['giornate'].items():
            for a in arene:
                carte = a.get('carte')
                pz = a.get('piazzamento')
                if not carte or not isinstance(pz, dict):
                    continue
                out.append({'fixture': fixture, 'giocatori': carte, 'fonte': fonte,
                            'competizione': a.get('competizione'),
                            'rank_reale': pz.get('rank'), 'punteggio_reale': pz.get('punteggio')})
    return out


def calcola_previsioni(cache, fine, formazioni):
    """Per ogni formazione valutabile, ritorna {'candidati': [...], 'fonte':...}
    dove candidati = lista di dict {ruolo, atteso, reale, nome} per i soli
    movimento (GK escluso, la scelta GK-vs-movimento non e' in discussione
    qui -- gia' decisa e in produzione)."""
    risultati = []
    scartate_no_fd = 0
    scartate_no_pred = 0

    per_fixture_cutoff = {}
    for f in formazioni:
        fixture = f['fixture']
        fd = fine.get(fixture)
        if fd is None:
            scartate_no_fd += 1
            continue

        carte_uniche = sorted(set((g['slug'], g['ruolo']) for g in f['giocatori']))
        chiave = (fixture,) + tuple(carte_uniche)
        cutoff = per_fixture_cutoff.get(chiave)
        if cutoff is None and chiave not in per_fixture_cutoff:
            cutoff = B.inizio_giornata(cache, fd, carte_uniche)
            per_fixture_cutoff[chiave] = cutoff
        if cutoff is None:
            scartate_no_fd += 1
            continue

        candidati = []
        ok = True
        for g in f['giocatori']:
            if g['ruolo'] == 'Goalkeeper':
                continue
            r = _reale(g)
            if r is None:
                ok = False
                break
            pred = P.score_atteso(cache, g['slug'], g['ruolo'], fd, cutoff)
            if pred is None:
                ok = False
                break
            ctx = P.contesto(cache, g['slug'], g['ruolo'], fd, cutoff)
            opp_rank = ctx.get('opp_rank') if ctx else None
            gol_tot = None
            if ctx:
                gol_tot = gol_totali_attesi(ctx.get('squadra'), ctx.get('opp_slug'), cutoff, ctx.get('casa'))
            candidati.append({'ruolo': _RUOLO_TO_CODICE[g['ruolo']], 'atteso': pred['atteso'],
                              'reale': r, 'nome': g['nome'], 'opp_rank': opp_rank,
                              'partite_storiche': pred.get('partite_storiche'),
                              'uscita_precoce': tasso_uscita_precoce(cache, g['slug'], cutoff),
                              'gol_totali': gol_tot,
                              'dev_std': dev_std_storica(cache, g['slug'], cutoff)})
        if not ok or len(candidati) < 2:
            scartate_no_pred += 1
            continue

        # somma GREZZA di tutte e 5 le carte (GK compreso), senza bonus
        # capitano: serve a captain_per_competizione.py per ricostruire il
        # punteggio totale sotto una scelta di capitano diversa
        # (totale = base + 0.2 * reale_del_capitano).
        base = 0.0
        somma_grezza = 0.0
        base_ok = True
        for g in f['giocatori']:
            r = _reale(g)
            if r is None or g.get('punteggio') is None:
                base_ok = False
                break
            base += r
            somma_grezza += g['punteggio']

        risultati.append({'candidati': candidati, 'fonte': f['fonte'],
                          'competizione': f.get('competizione'),
                          'slug_arena': f.get('slug_arena'),
                          'rank_reale': f.get('rank_reale'),
                          'punteggio_reale': f.get('punteggio_reale'),
                          # controllo d'integrita': la somma delle carte deve
                          # tornare col punteggio dichiarato (stesso presidio
                          # di bilancio_stesse_carte, ~2% di righe sporche)
                          'somma_grezza': somma_grezza if base_ok else None,
                          'base_reale': base if base_ok else None})

    print(f"Formazioni raccolte: {len(formazioni)}  "
          f"scartate (fixture/cutoff mancante)={scartate_no_fd}  "
          f"scartate (previsione mancante)={scartate_no_pred}  "
          f"valutabili={len(risultati)}")
    return risultati


# --- POLICY ---

def policy_baseline(candidati):
    """Regola attuale di produzione: max atteso grezzo."""
    return max(candidati, key=lambda c: c['atteso'])


def policy_bias_ruolo(candidati):
    """Gia' testata (bocciata, lift ~0 su 513 formazioni): applica SEMPRE
    BIAS_RUOLO. Qui riproposta sul campione allargato (idea 3)."""
    return max(candidati, key=lambda c: c['atteso'] + BIAS_RUOLO.get(c['ruolo'], 0.0))


def make_policy_bias_margine(soglia):
    """Idea 1: applica BIAS_RUOLO solo se lo scarto fra i due migliori per
    atteso grezzo e' <= soglia (caso 'in bilico'); altrimenti baseline."""
    def policy(candidati):
        ordinati = sorted(candidati, key=lambda c: c['atteso'], reverse=True)
        if len(ordinati) < 2 or (ordinati[0]['atteso'] - ordinati[1]['atteso']) > soglia:
            return ordinati[0]
        return max(candidati, key=lambda c: c['atteso'] + BIAS_RUOLO.get(c['ruolo'], 0.0))
    policy.__name__ = f'bias_margine_{soglia}'
    return policy


def bonus_totale(risultati, policy):
    """Ritorna lista di bonus (0.2*reale del capitano scelto) per formazione."""
    return [(MOLTIPLICATORE_CAPITANO - 1.0) * policy(r['candidati'])['reale'] for r in risultati]


def intervallo_media(valori, seme=0, giri=2000):
    return B.intervallo_media(valori, seme=seme, giri=giri)


def confronta(risultati, nome, policy, base_bonus):
    bonus = bonus_totale(risultati, policy)
    diff = [b - a for b, a in zip(bonus, base_bonus)]
    tot_diff = sum(diff)
    ic = intervallo_media(diff)
    vince = sum(1 for d in diff if d > 1e-9)
    perde = sum(1 for d in diff if d < -1e-9)
    segnale = "" if ic[0] <= 0 <= ic[1] else ("  <-- IC esclude lo zero" if tot_diff > 0
                                               else "  <-- IC esclude lo zero (NEGATIVO)")
    print(f"  {nome:<28} tot diff={tot_diff:+8.2f}  media/formazione={statistics.mean(diff):+.4f}  "
          f"IC95%=[{ic[0]:+.4f}, {ic[1]:+.4f}]  vince/perde={vince}/{perde}{segnale}")


def main():
    print("Caricamento cache e formazioni reali (3 fonti)...\n")
    cache = C.CacheLocale()
    arene_storico = carica('dati_globali/arene_storico.json')['arene']
    fine = B.fine_giornate(arene_storico)

    formazioni = raccogli_formazioni()
    by_fonte = defaultdict(int)
    for f in formazioni:
        by_fonte[f['fonte']] += 1
    print("Formazioni per fonte:", dict(by_fonte))

    risultati = calcola_previsioni(cache, fine, formazioni)
    by_fonte_ok = defaultdict(int)
    for r in risultati:
        by_fonte_ok[r['fonte']] += 1
    print("Valutabili per fonte:", dict(by_fonte_ok))

    base_bonus = bonus_totale(risultati, policy_baseline)
    print(f"\nBaseline (atteso grezzo): bonus totale={sum(base_bonus):.2f}  "
          f"media/formazione={statistics.mean(base_bonus):.4f}\n")

    print("=== Idea 3: bias di ruolo SEMPRE applicato, campione allargato ===")
    confronta(risultati, 'bias_ruolo (sempre)', policy_bias_ruolo, base_bonus)

    print("\n=== Idea 1: bias di ruolo solo nei casi in bilico (grid soglie) ===")
    for soglia in (3, 5, 8, 12, 20):
        confronta(risultati, f'bias_margine<={soglia}', make_policy_bias_margine(soglia), base_bonus)

    print("\n=== Idea 4 (diagnostica): bias residuo per favorita/sfavorita, zona capitano (atteso>=55) ===")
    zona = [c for r in risultati for c in r['candidati'] if c['atteso'] >= 55 and c['opp_rank'] is not None]
    print(f"n candidati zona capitano con opp_rank noto: {len(zona)}")
    if zona:
        ranks = sorted(c['opp_rank'] for c in zona)
        n = len(ranks)
        t1, t2 = ranks[n // 3], ranks[2 * n // 3]
        # opp_rank: piu' basso = squadra avversaria piu' forte (rank 1 = migliore),
        # quindi rank BASSO = io sfavorito, rank ALTO = io favorito
        def bucket(rk):
            if rk <= t1:
                return 'SFAVORITO (avversario forte)'
            if rk <= t2:
                return 'NEUTRO'
            return 'FAVORITO (avversario debole)'
        per_bucket = defaultdict(list)
        for c in zona:
            per_bucket[bucket(c['opp_rank'])].append(c)
        for nome_b in ('SFAVORITO (avversario forte)', 'NEUTRO', 'FAVORITO (avversario debole)'):
            cs = per_bucket[nome_b]
            if not cs:
                continue
            mp = statistics.mean(c['atteso'] for c in cs)
            mr = statistics.mean(c['reale'] for c in cs)
            print(f"  {nome_b:<32} n={len(cs):>5}  atteso medio={mp:6.1f}  reale medio={mr:6.1f}  bias={mr-mp:+6.2f}")

        print("\n=== Idea 4 in policy: bonus se FAVORITO (opp_rank > terzile alto) ===")
        BONUS_FAVORITO = 2.17  # gap misurato sopra, FAVORITO vs resto

        def policy_favorita(candidati):
            def score(c):
                extra = BONUS_FAVORITO if (c.get('opp_rank') is not None and c['opp_rank'] > t2) else 0.0
                return c['atteso'] + extra
            return max(candidati, key=score)

        confronta(risultati, 'favorita (sempre)', policy_favorita, base_bonus)

        # 04/08 notte: la pendenza reale~atteso e' b=1.53 (vedi
        # diagnostica_di_metodo): le differenze di atteso sono COMPRESSE di
        # 1.53x rispetto a quelle reali, quindi un bonus misurato in punti
        # REALI va diviso per b prima di sommarlo all'atteso, altrimenti
        # ribalta scelte che non dovrebbe. Tutte le correzioni testate finora
        # avevano questo difetto: qui la griglia sul fattore di scala.
        print("\n=== Idea 4 ri-scalata: stesso bonus diviso per la compressione (grid) ===")
        for fattore in (0.4, 0.65, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 25.0):
            b_scalato = BONUS_FAVORITO * fattore

            def policy_scalata(candidati, _b=b_scalato):
                def score(c):
                    extra = _b if (c.get('opp_rank') is not None and c['opp_rank'] > t2) else 0.0
                    return c['atteso'] + extra
                return max(candidati, key=score)

            confronta(risultati, f'favorita x{fattore} (+{b_scalato:.2f})', policy_scalata, base_bonus)

        print("\n=== Nuova idea A: favorita + ruolo COMBINATI ===")

        def policy_favorita_e_ruolo(candidati):
            def score(c):
                extra = BONUS_FAVORITO if (c.get('opp_rank') is not None and c['opp_rank'] > t2) else 0.0
                return c['atteso'] + extra + BIAS_RUOLO.get(c['ruolo'], 0.0)
            return max(candidati, key=score)

        confronta(risultati, 'favorita+ruolo', policy_favorita_e_ruolo, base_bonus)

    print("\n=== Nuova idea B (diagnostica): bias per profondita' di storico, zona capitano ===")
    zona_b = [c for r in risultati for c in r['candidati']
             if c['atteso'] >= 55 and c.get('partite_storiche') is not None]
    print(f"n candidati con partite_storiche noto: {len(zona_b)}")
    if zona_b:
        vals = sorted(c['partite_storiche'] for c in zona_b)
        n = len(vals)
        u1, u2 = vals[n // 3], vals[2 * n // 3]

        def bucket_storico(v):
            if v <= u1:
                return 'POCO storico'
            if v <= u2:
                return 'MEDIO storico'
            return 'MOLTO storico'
        per_b = defaultdict(list)
        for c in zona_b:
            per_b[bucket_storico(c['partite_storiche'])].append(c)
        for nome_b in ('POCO storico', 'MEDIO storico', 'MOLTO storico'):
            cs = per_b[nome_b]
            if not cs:
                continue
            mp_ = statistics.mean(c['atteso'] for c in cs)
            mr_ = statistics.mean(c['reale'] for c in cs)
            print(f"  {nome_b:<16} n={len(cs):>5}  atteso medio={mp_:6.1f}  reale medio={mr_:6.1f}  "
                  f"bias={mr_-mp_:+6.2f}")

    print("\n=== Nuova idea C (diagnostica): bias per rischio 'uscita precoce' (mins<60), zona capitano ===")
    zona_c = [c for r in risultati for c in r['candidati']
             if c['atteso'] >= 55 and c.get('uscita_precoce') is not None]
    print(f"n candidati con tasso uscita precoce noto: {len(zona_c)}")
    if zona_c:
        vals = sorted(c['uscita_precoce'] for c in zona_c)
        n = len(vals)
        v1, v2 = vals[n // 3], vals[2 * n // 3]

        def bucket_uscita(v):
            if v <= v1:
                return 'BASSO rischio uscita'
            if v <= v2:
                return 'MEDIO rischio uscita'
            return 'ALTO rischio uscita'
        per_c = defaultdict(list)
        for c in zona_c:
            per_c[bucket_uscita(c['uscita_precoce'])].append(c)
        for nome_c in ('BASSO rischio uscita', 'MEDIO rischio uscita', 'ALTO rischio uscita'):
            cs = per_c[nome_c]
            if not cs:
                continue
            mp_ = statistics.mean(c['atteso'] for c in cs)
            mr_ = statistics.mean(c['reale'] for c in cs)
            print(f"  {nome_c:<22} n={len(cs):>5}  atteso medio={mp_:6.1f}  reale medio={mr_:6.1f}  "
                  f"bias={mr_-mp_:+6.2f}")

    print("\n=== Nuova idea D (diagnostica): bias per ambiente gol della partita, zona capitano ===")
    zona_d = [c for r in risultati for c in r['candidati']
             if c['atteso'] >= 55 and c.get('gol_totali') is not None]
    print(f"n candidati con gol_totali_attesi noto: {len(zona_d)}")
    if zona_d:
        vals = sorted(c['gol_totali'] for c in zona_d)
        n = len(vals)
        g1, g2 = vals[n // 3], vals[2 * n // 3]

        def bucket_gol(v):
            if v <= g1:
                return 'partita CHIUSA (pochi gol attesi)'
            if v <= g2:
                return 'partita MEDIA'
            return 'partita APERTA (molti gol attesi)'
        per_d = defaultdict(list)
        for c in zona_d:
            per_d[bucket_gol(c['gol_totali'])].append(c)
        for nome_d in ('partita CHIUSA (pochi gol attesi)', 'partita MEDIA', 'partita APERTA (molti gol attesi)'):
            cs = per_d[nome_d]
            if not cs:
                continue
            mp_ = statistics.mean(c['atteso'] for c in cs)
            mr_ = statistics.mean(c['reale'] for c in cs)
            print(f"  {nome_d:<36} n={len(cs):>5}  atteso medio={mp_:6.1f}  reale medio={mr_:6.1f}  "
                  f"bias={mr_-mp_:+6.2f}")

        print("\n=== Nuova idea D in policy: bonus se partita APERTA (gol_totali > terzile alto) ===")
        BONUS_APERTA = 5.6  # gap misurato sopra, APERTA vs resto

        def policy_ambiente_gol(candidati):
            def score(c):
                extra = BONUS_APERTA if (c.get('gol_totali') is not None and c['gol_totali'] > g2) else 0.0
                return c['atteso'] + extra
            return max(candidati, key=score)

        confronta(risultati, 'ambiente_gol (sempre)', policy_ambiente_gol, base_bonus)

        def make_policy_gol_margine(soglia):
            def policy(candidati):
                ordinati = sorted(candidati, key=lambda c: c['atteso'], reverse=True)
                if len(ordinati) < 2 or (ordinati[0]['atteso'] - ordinati[1]['atteso']) > soglia:
                    return ordinati[0]
                return policy_ambiente_gol(candidati)
            return policy

        print("\n=== Nuova idea D, gating per margine (il bonus e' grande, qui puo' contare) ===")
        for soglia in (3, 5, 8, 12):
            confronta(risultati, f'ambiente_gol_margine<={soglia}', make_policy_gol_margine(soglia), base_bonus)

    diagnostica_di_metodo(risultati, base_bonus)


def diagnostica_di_metodo(risultati, base_bonus):
    """Le due domande MAI poste nei due round di test (04/08 notte):

    1. HEADROOM: quanto vale l'intera decisione? Finora abbiamo confrontato
       policy fra loro senza mai misurare il tetto (capitano scelto con
       preveggenza) e il pavimento (peggior candidato). Se il tetto e'
       piccolo, nessuna euristica potra' mai pagare e il filone e' chiuso
       per aritmetica, non per sfortuna.
    2. MALEDIZIONE DEL VINCITORE: tutti i bias li abbiamo misurati su TUTTI
       i candidati, mai CONDIZIONATI all'essere stati scelti. Ma argmax su
       una stima rumorosa seleziona preferenzialmente chi e' stato
       sovrastimato: e' il meccanismo che pick_captain() usa davvero.
    3. SCALA: se reale ~ a + b*atteso con b>1, le differenze di atteso sono
       COMPRESSE rispetto a quelle reali -- e ogni correzione additiva in
       punti reali (tutte quelle testate) e' sovradimensionata di un fattore
       b quando la si somma all'atteso.
    """
    print("\n" + "=" * 78)
    print("DIAGNOSTICA DI METODO (mai fatta prima)")
    print("=" * 78)

    q = MOLTIPLICATORE_CAPITANO - 1.0
    oracolo = [q * max(c['reale'] for c in r['candidati']) for r in risultati]
    pessimo = [q * min(c['reale'] for c in r['candidati']) for r in risultati]
    casuale = [q * statistics.mean(c['reale'] for c in r['candidati']) for r in risultati]

    mb = statistics.mean(base_bonus)
    print("\n--- 1. HEADROOM: quanto vale l'intera decisione capitano ---")
    print(f"  peggior candidato (pavimento)  {statistics.mean(pessimo):7.3f} pt/formazione")
    print(f"  candidato a caso               {statistics.mean(casuale):7.3f} pt/formazione")
    print(f"  REGOLA ATTUALE (max atteso)    {mb:7.3f} pt/formazione")
    print(f"  ORACOLO (max reale, tetto)     {statistics.mean(oracolo):7.3f} pt/formazione")
    print(f"\n  Guadagno gia' catturato dalla regola attuale sul caso: "
          f"{mb - statistics.mean(casuale):+.3f} pt/formazione")
    print(f"  Margine RESIDUO fino all'oracolo:                     "
          f"{statistics.mean(oracolo) - mb:+.3f} pt/formazione")
    quota = (mb - statistics.mean(casuale)) / (statistics.mean(oracolo) - statistics.mean(casuale))
    print(f"  => la regola attuale cattura il {quota:.1%} del guadagno disponibile "
          f"(caso -> oracolo)")

    colpi = sum(1 for r in risultati
                if policy_baseline(r['candidati'])['reale'] == max(c['reale'] for c in r['candidati']))
    attesi_a_caso = sum(1.0 / len(r['candidati']) for r in risultati)
    print(f"\n  Quante volte pick_captain() azzecca il candidato migliore: "
          f"{colpi}/{len(risultati)} ({colpi/len(risultati):.1%})")
    print(f"  Quante ne azzeccherebbe scegliendo a caso:                 "
          f"{attesi_a_caso:.0f}/{len(risultati)} ({attesi_a_caso/len(risultati):.1%})")

    print("\n--- 2. MALEDIZIONE DEL VINCITORE (bias condizionato alla selezione) ---")
    bias_scelto, bias_tutti = [], []
    for r in risultati:
        sel = policy_baseline(r['candidati'])
        bias_scelto.append(sel['reale'] - sel['atteso'])
        bias_tutti.append(statistics.mean(c['reale'] - c['atteso'] for c in r['candidati']))
    ic = intervallo_media([a - b for a, b in zip(bias_scelto, bias_tutti)])
    print(f"  bias medio del candidato SCELTO da pick_captain : {statistics.mean(bias_scelto):+6.2f} pt")
    print(f"  bias medio di TUTTI i candidati                 : {statistics.mean(bias_tutti):+6.2f} pt")
    print(f"  differenza (scelto - tutti)                     : "
          f"{statistics.mean(bias_scelto) - statistics.mean(bias_tutti):+6.2f} pt  "
          f"IC95%=[{ic[0]:+.2f}, {ic[1]:+.2f}]")
    print("  (negativo = argmax seleziona preferenzialmente chi era SOVRASTIMATO)")

    print("\n--- 3. SCALA: compressione dell'atteso rispetto al reale (zona capitano) ---")
    zona = [c for r in risultati for c in r['candidati'] if c['atteso'] >= 55]
    xs = [c['atteso'] for c in zona]
    ys = [c['reale'] for c in zona]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else float('nan')
    print(f"  n={len(zona)}  pendenza reale~atteso: b={b:.2f}")
    print(f"  => 1 pt di differenza di ATTESO vale {b:.2f} pt di differenza REALE attesa.")
    if b > 1:
        print(f"  => ogni correzione additiva in punti reali andrebbe divisa per b "
              f"prima di sommarla all'atteso: quelle testate erano ~{b:.1f}x troppo grandi.")


if __name__ == '__main__':
    main()
