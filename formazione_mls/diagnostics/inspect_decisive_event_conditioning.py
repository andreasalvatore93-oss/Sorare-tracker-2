"""
Inspect Decisive Event Conditioning (26/07/2026, Stadio C tema level_score)

Diagnostico locale (nessuna query API, legge solo le cache .cache/*_detail_cache.json
gia' scaricate dai run di calibrazione) per rispondere alla domanda: "la probabilita'
che scatti un evento decisivo positivo (netto POSITIVE_DECISIVE_STAT -
NEGATIVE_DECISIVE_STAT >= +1, cioe' level_score >= 60) cambia in modo utile in base a
VENUE (casa/trasferta) e FORZA DELL'AVVERSARIO, o e' rumore?"

Contesto (vedi docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md sezione 11): level_score
ha una base fissa di 35 assegnata a chiunque scenda in campo, poi sale a scatti discreti
(5/15/35/60/70/80/90/100) in base al conteggio netto di eventi decisivi (gol, assist,
clean sheet per GK, tackle da ultimo uomo, rigore parato/causato, cartellino rosso,
autogol, errore-a-gol...). Oggi il modello usa solo la media storica generica del
giocatore per stimare level_score atteso, senza condizionare per la partita specifica.
Questo script misura se vale la pena farlo, PRIMA di scrivere qualunque codice di
produzione (nessun rischio, stesso pattern diagnostico di Stadio A/B/inspect_granular_weights.py).

Metodo:
- Per ogni giocatore in cache, determina la sua squadra con la stessa euristica gia'
  usata in produzione (test_<ruolo>.py): la squadra che compare piu' spesso tra
  home/away nelle sue partite in cache.
- Per ogni partita: netto = sum(statValue dove category=='POSITIVE_DECISIVE_STAT')
  - sum(statValue dove category=='NEGATIVE_DECISIVE_STAT') (stessa formula scoperta
  il 26/07, validata su 9 casi reali). Evento decisivo positivo = netto >= 1.
- Venue: is_home diretto da anyGame.
- Forza avversario: CONFRONTO RELATIVO al singolo giocatore (stessa logica gia' in
  produzione per fattore_forza_avversario, non una soglia globale fissa -- evita il
  problema di scale di ranking diverse tra campionati/competizioni diverse che possono
  comparire nello storico di uno stesso giocatore). Per ogni giocatore con >=6 partite
  con ranking avversario disponibile: avversario "forte" se il suo ranking (rank piu'
  basso = squadra piu' forte) e' INFERIORE alla media dei ranking avversari affrontati
  da quel giocatore nello storico in cache, altrimenti "debole".

Uso: RUOLO=mid python formazione_mls/diagnostics/inspect_decisive_event_conditioning.py
     RUOLO=all python formazione_mls/diagnostics/inspect_decisive_event_conditioning.py
     (itera gk/def/mid/fwd e somma i risultati, oltre al dettaglio per ruolo)
"""
import os
import json
import glob
import statistics
from collections import defaultdict

ROLES = ('gk', 'def', 'mid', 'fwd')
RUOLO = os.environ.get('RUOLO', 'all').strip().lower()


def netto_evento_decisivo(detailed_score):
    """Somma POSITIVE_DECISIVE_STAT - somma NEGATIVE_DECISIVE_STAT per una partita
    (formula esatta scoperta il 26/07, validata su 9 casi reali Sorare)."""
    pos = sum(row.get('statValue', 0.0) or 0.0
              for row in detailed_score if row.get('category') == 'POSITIVE_DECISIVE_STAT')
    neg = sum(row.get('statValue', 0.0) or 0.0
              for row in detailed_score if row.get('category') == 'NEGATIVE_DECISIVE_STAT')
    return pos - neg


def player_team_slug(games):
    """Stessa euristica di produzione: la squadra che compare piu' spesso tra
    home/away nello storico disponibile del giocatore."""
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    if not team_counts:
        return None
    return max(team_counts, key=team_counts.get)


def load_role_games(ruolo):
    """Ritorna una lista di dict {is_home, opp_rank, netto, is_decisive} per
    TUTTE le partite in cache per il ruolo, con squadra/avversario/ranking
    risolvibili (scarta le partite dove manca il dato di ranking avversario,
    servono per il confronto relativo)."""
    cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    rows = []
    n_players = 0
    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if not entries:
            continue
        n_players += 1
        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue

        # Prima passata: ranking avversari affrontati da QUESTO giocatore (per il
        # confronto relativo forte/debole, coerente con fattore_forza_avversario
        # gia' in produzione).
        opp_ranks = []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                r = away.get('domesticLeagueRanking')
            elif away.get('slug') == team_slug:
                r = home.get('domesticLeagueRanking')
            else:
                r = None
            if r is not None:
                opp_ranks.append(r)
        if len(opp_ranks) < 6:
            continue
        avg_opp_rank = statistics.mean(opp_ranks)

        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home, opp_rank = True, away.get('domesticLeagueRanking')
            elif away.get('slug') == team_slug:
                is_home, opp_rank = False, home.get('domesticLeagueRanking')
            else:
                continue
            if opp_rank is None:
                continue
            netto = netto_evento_decisivo(e['detailedScore'])
            rows.append({
                'is_home': is_home,
                'forte': opp_rank < avg_opp_rank,
                'netto': netto,
                'decisivo': netto >= 1,
            })

    return rows, n_players


def summarize(rows, label):
    n = len(rows)
    if n == 0:
        print(f"{label}: nessuna partita utile")
        return
    rate = sum(1 for r in rows if r['decisivo']) / n
    print(f"{label:45s} n={n:5d}  P(evento decisivo positivo) = {rate*100:5.1f}%")


def main():
    ruoli = ROLES if RUOLO == 'all' else (RUOLO,)
    all_rows = []
    for ruolo in ruoli:
        rows, n_players = load_role_games(ruolo)
        if not rows:
            print(f"\n=== {ruolo.upper()}: nessun dato utilizzabile ===")
            continue
        all_rows.extend([dict(r, ruolo=ruolo) for r in rows])

        print(f"\n=== {ruolo.upper()} ({n_players} giocatori con cache, {len(rows)} partite con "
              f"ranking avversario disponibile e >=6 partite storiche per il confronto relativo) ===")
        summarize(rows, "  Tutte le partite")
        summarize([r for r in rows if r['is_home']], "  Casa")
        summarize([r for r in rows if not r['is_home']], "  Trasferta")
        summarize([r for r in rows if r['forte']], "  Avversario piu' forte della media personale")
        summarize([r for r in rows if not r['forte']], "  Avversario piu' debole della media personale")
        summarize([r for r in rows if r['is_home'] and r['forte']], "  Casa + avversario forte")
        summarize([r for r in rows if r['is_home'] and not r['forte']], "  Casa + avversario debole")
        summarize([r for r in rows if not r['is_home'] and r['forte']], "  Trasferta + avversario forte")
        summarize([r for r in rows if not r['is_home'] and not r['forte']], "  Trasferta + avversario debole")

    if len(ruoli) > 1 and all_rows:
        print(f"\n=== TUTTI I RUOLI POOLATI ({len(all_rows)} partite) ===")
        summarize(all_rows, "  Tutte le partite")
        summarize([r for r in all_rows if r['is_home']], "  Casa")
        summarize([r for r in all_rows if not r['is_home']], "  Trasferta")
        summarize([r for r in all_rows if r['forte']], "  Avversario piu' forte della media personale")
        summarize([r for r in all_rows if not r['forte']], "  Avversario piu' debole della media personale")


if __name__ == '__main__':
    main()
