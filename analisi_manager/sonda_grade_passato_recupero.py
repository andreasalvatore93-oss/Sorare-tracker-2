"""Sonda BRIEF_SONNET_GRADE_PASSATO_RECUPERO_2026-08-09: il grade di una
partita gia' giocata (scoreStatus FINAL) e' ancora servito dall'API oggi?
Riusa la query e le credenziali gia' in raccolta_grade_storico.py (stessa
rotta anyPlayer(slug).playerGameScores(last:N)). NESSUNA MODIFICA
PRODUZIONE, solo lettura.
"""
import sys, os, io, json
from datetime import datetime, timezone

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
import raccolta_grade_storico as R

SAMPLE = [
    ('mateo-lisica', 'Forward', '2026-07-28T18:00:00Z', 'D', 10000, 10000),
    ('taha-habroune', 'Midfielder', '2026-07-22T23:30:00Z', 'D', 10000, 10000),
    ('prince-amoako-junior', 'Forward', '2026-07-26T16:00:00Z', 'D', 10000, 10000),
    ('aleksandr-maksimenko', 'Goalkeeper', '2026-03-09T16:00:00Z', 'C', 10000, 10000),
    ('hyun-jun-yang', 'Forward', '2026-04-05T15:30:00Z', 'D', 10000, 10000),
]

QUERY_BIG = R.QUERY_STORICO.replace('last: 15', 'last: 40')


def query_storico_big(slug):
    if not R.SORARE_COOKIE or not R.SORARE_CSRF:
        return None
    query_str = QUERY_BIG % slug
    payload = {"operationName": "GetPlayerGameScores", "query": query_str}
    headers = {
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'Cookie': R.SORARE_COOKIE, 'X-CSRF-Token': R.SORARE_CSRF,
    }
    r = R.g._http_session.post(R.g.GRAPHQL_URL, json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        print(f'  HTTP {r.status_code}: {r.text[:300]}')
        return None
    d = r.json()
    if d.get('errors'):
        print(f'  GraphQL error: {d["errors"][:2]}')
        return None
    return d.get('data', {}).get('anyPlayer')


def main():
    n_provate = 0
    n_risposte = 0
    n_grade_presente = 0
    n_grade_identico = 0
    n_grade_diverso = 0
    esito_righe = []

    for slug, ruolo, game_date, grade_storico, odds_storico, rel_storico in SAMPLE:
        n_provate += 1
        print(f'\n--- {slug} ({ruolo}) partita {game_date} storico=grade:{grade_storico} ---')
        data = query_storico_big(slug)
        if not data:
            esito_righe.append({
                'slug': slug, 'ruolo': ruolo, 'game_date': game_date,
                'grade_storico': grade_storico, 'esito': 'NESSUNA_RISPOSTA',
            })
            print('  NESSUNA RISPOSTA')
            continue
        n_risposte += 1
        match = None
        for gs in data.get('playerGameScores', []):
            ag = gs.get('anyGame') or {}
            if ag.get('date') == game_date:
                match = gs
                break
        if match is None:
            esito_righe.append({
                'slug': slug, 'ruolo': ruolo, 'game_date': game_date,
                'grade_storico': grade_storico, 'esito': 'PARTITA_NON_NEL_LAST40',
            })
            print('  PARTITA NON TROVATA nelle ultime 40 (fuori finestra)')
            continue
        proj = match.get('projection') or {}
        pgs = (match.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}
        grade_oggi = proj.get('grade')
        rel_oggi = proj.get('reliabilityBasisPoints')
        odds_oggi = pgs.get('starterOddsBasisPoints')
        score_status_oggi = match.get('scoreStatus')
        riga = {
            'slug': slug, 'ruolo': ruolo, 'game_date': game_date,
            'scoreStatus_oggi': score_status_oggi,
            'grade_storico': grade_storico, 'grade_oggi': grade_oggi,
            'starter_odds_storico': odds_storico, 'starter_odds_oggi': odds_oggi,
            'reliability_storico': rel_storico, 'reliability_oggi': rel_oggi,
        }
        if grade_oggi is not None:
            n_grade_presente += 1
            if grade_oggi == grade_storico:
                n_grade_identico += 1
                riga['esito'] = 'IDENTICO'
            else:
                n_grade_diverso += 1
                riga['esito'] = 'DIVERSO'
        else:
            riga['esito'] = 'GRADE_NULLO_OGGI'
        esito_righe.append(riga)
        print(f'  status={score_status_oggi} grade_oggi={grade_oggi} (storico={grade_storico}) '
              f'odds_oggi={odds_oggi} (storico={odds_storico})')

    print('\n=== RIEPILOGO ===')
    print(f'righe provate: {n_provate}')
    print(f'righe con risposta: {n_risposte}')
    print(f'righe con grade presente oggi: {n_grade_presente}')
    print(f'righe con grade identico allo storico: {n_grade_identico}')
    print(f'righe con grade diverso dallo storico: {n_grade_diverso}')

    out = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'n_provate': n_provate, 'n_risposte': n_risposte,
        'n_grade_presente': n_grade_presente, 'n_grade_identico': n_grade_identico,
        'n_grade_diverso': n_grade_diverso,
        'righe': esito_righe,
    }
    with open('analisi_manager/dati/sonda_grade_passato_recupero_20260809.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('\nSalvato analisi_manager/dati/sonda_grade_passato_recupero_20260809.json')


if __name__ == '__main__':
    main()
