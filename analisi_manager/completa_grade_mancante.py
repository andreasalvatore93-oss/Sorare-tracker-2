"""Completamento MIRATO dell'indice grade condiviso (10/08/2026).

Procedura STANDARD da richiamare da qualunque backtest che trovi carte
senza grade in `p12_backtest_formazione_grade.carica_indice_grade()`: invece
di accettare il buco, interroga Sorare SOLO per quegli slug (stessa rotta
gia' in uso, `anyPlayer(slug).playerGameScores(last:15)`,
vedi `raccolta_grade_storico.py`) e accumula il risultato in un file
persistente che l'indice condiviso legge in automatico
(`analisi_manager/dati/storico_grade_crowss_completamento.json`).

E' INCREMENTALE: ogni run aggiunge solo le righe nuove (dedup su
slug+game_date), il file cresce GW dopo GW e beneficia OGNI consumer
dell'indice condiviso (p12/p13/p23...), non solo chi l'ha lanciato.

Richiede SORARE_COOKIE e SORARE_CSRF in env (query autenticata: senza
credenziali torna [] senza fare nulla, non solleva errore -- chi chiama
decide se e' bloccante).

Uso diretto:
  SORARE_COOKIE=... SORARE_CSRF=... python analisi_manager/completa_grade_mancante.py slug1 slug2 ...
Uso come libreria:
  import completa_grade_mancante as CG
  aggiunte, falliti = CG.completa(['slug1', 'slug2'])
"""
import os
import sys
import io
import json

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g  # noqa: E402

SORARE_COOKIE = os.environ.get('SORARE_COOKIE', '')
SORARE_CSRF = os.environ.get('SORARE_CSRF', '')

QUERY_STORICO = """
query GetPlayerGameScores {
  anyPlayer(slug: "%s") {
    slug
    playerGameScores(last: 15) {
      score
      scoreStatus
      anyGame { date }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""

PATH_COMPLETAMENTO = os.path.join(os.path.dirname(__file__), 'dati',
                                  'storico_grade_crowss_completamento.json')


def _carica_esistenti():
    if not os.path.exists(PATH_COMPLETAMENTO):
        return []
    with open(PATH_COMPLETAMENTO, encoding='utf-8') as fh:
        return json.load(fh)


def _salva(righe):
    os.makedirs(os.path.dirname(PATH_COMPLETAMENTO), exist_ok=True)
    with open(PATH_COMPLETAMENTO, 'w', encoding='utf-8') as fh:
        json.dump(righe, fh, ensure_ascii=False, indent=1)


def _query_slug(slug):
    if not SORARE_COOKIE or not SORARE_CSRF:
        return None, 'no_credenziali'
    payload = {"operationName": "GetPlayerGameScores", "query": QUERY_STORICO % slug}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
              'Cookie': SORARE_COOKIE, 'X-CSRF-Token': SORARE_CSRF}
    try:
        r = g._http_session.post(g.GRAPHQL_URL, json=payload, headers=headers, timeout=20)
    except Exception as e:
        return None, f'errore_rete: {e}'
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}: {r.text[:200]}'
    d = r.json()
    if d.get('errors'):
        return None, f'GraphQL: {d["errors"][:2]}'
    ap = (d.get('data') or {}).get('anyPlayer')
    if ap is None:
        return None, 'anyPlayer_null'
    return ap.get('playerGameScores') or [], None


def completa(slugs):
    """Interroga Sorare per gli slug dati, aggiunge le righe NUOVE (dedup
    su slug+game_date) al file persistente. Ritorna (n_righe_aggiunte,
    dict slug->motivo per gli slug che NON hanno prodotto nulla)."""
    esistenti = _carica_esistenti()
    chiavi = {(r.get('slug'), r.get('game_date')) for r in esistenti}
    falliti = {}
    nuove = 0
    for slug in slugs:
        scores, errore = _query_slug(slug)
        if errore:
            falliti[slug] = errore
            continue
        if not scores:
            falliti[slug] = 'nessuna_partita_in_last15'
            continue
        for s in scores:
            proj = s.get('projection') or {}
            grade = proj.get('grade')
            dt = (s.get('anyGame') or {}).get('date')
            if not grade or not dt:
                continue
            chiave = (slug, dt)
            if chiave in chiavi:
                continue
            chiavi.add(chiave)
            esistenti.append({'slug': slug, 'game_date': dt, 'grade': grade})
            nuove += 1
    if nuove:
        _salva(esistenti)
    return nuove, falliti


def main():
    slugs = sys.argv[1:]
    if not slugs:
        print('Uso: python completa_grade_mancante.py slug1 slug2 ...')
        sys.exit(1)
    if not SORARE_COOKIE or not SORARE_CSRF:
        print('SORARE_COOKIE / SORARE_CSRF mancanti in env: nessuna query possibile.')
        sys.exit(1)
    nuove, falliti = completa(slugs)
    print(f'{nuove} righe nuove aggiunte a {PATH_COMPLETAMENTO}')
    if falliti:
        print(f'{len(falliti)}/{len(slugs)} slug senza risultato:')
        for slug, motivo in falliti.items():
            print(f'  {slug}: {motivo}')


if __name__ == '__main__':
    main()
