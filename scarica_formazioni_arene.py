"""Le formazioni davvero schierate in ogni arena giocata.

A COSA SERVE. Prima di far decidere al modello se entrare in un'arena bisogna
sapere quanto ci prende, e per saperlo servono le formazioni vere: quali carte
sono state schierate, chi era capitano, e quanto ha fatto ognuno. Con questo
si puo' far girare il modello "come se fosse quella giornata" e confrontare
previsto contro realizzato, sulle 673 arene dell'archivio.

Il ROI attuale (+26%) e' stato ottenuto a mano. Il modello va agganciato solo
se questa misura dice che lo migliora: con un ROI gia' positivo c'e' piu' da
perdere che da guadagnare, quindi l'onere della prova sta dal lato del modello.

I dati sono PUBBLICI: le formazioni si leggono senza cookie. Restano i limiti
di frequenza, per questo gira su Actions e non in locale (in locale mandava in
429 i bot di mercato).

Uso:  python scarica_formazioni_arene.py
"""
import datetime
import json
import os
import sys
import time

APIKEY = os.environ.get('SORARE_APIKEY', '')  # 12/08/2026: alza il tetto di complessita' e di richieste dell'account

ARCHIVIO = 'dati_globali/arene_storico.json'
OUT = 'dati_globali/arene_formazioni.json'
GRAPHQL_URL = 'https://api.sorare.com/graphql'
PAUSA = float(os.environ.get('PAUSA_SECONDI', '1.0'))

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()

Q = """
query Formazione($slug: String!) {
  so5 {
    so5LeaderboardContender(slug: $slug) {
      so5Lineup {
        so5Appearances {
          score
          position
          captain
          player { slug displayName }
          anyCard { slug }
        }
      }
    }
  }
}
"""


def graphql(query, variables):
    for tentativo in range(5):
        time.sleep(PAUSA)
        r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                    headers={'Content-Type': 'application/json',
                             'User-Agent': 'Mozilla/5.0',
                             **({'APIKEY': APIKEY} if APIKEY else {})}, timeout=60)
        if r.status_code == 429:
            attesa = min(2 ** tentativo * 3, 60)
            print(f'    rate limit, aspetto {attesa}s')
            time.sleep(attesa)
            continue
        try:
            return r.json()
        except Exception:
            return {'errors': [{'message': f'HTTP {r.status_code}'}]}
    return {'errors': [{'message': 'HTTP 429 dopo 5 tentativi'}]}


def main():
    arene = json.load(open(ARCHIVIO, encoding='utf-8'))['arene']
    # lo slug del contender non e' nell'archivio: si ricostruisce da quello
    # della classifica solo se l'abbiamo salvato, altrimenti si salta
    da_fare = [r for r in arene if r.get('contender_slug')]
    if not da_fare:
        print('Nessuno slug di formazione nell\'archivio: va aggiunto al')
        print('tracker (mySo5LeaderboardContenders.slug) e riscaricato.')
        return 2

    fatte = {}
    if os.path.exists(OUT):
        fatte = json.load(open(OUT, encoding='utf-8')).get('formazioni') or {}

    manca = [r for r in da_fare if r['contender_slug'] not in fatte]
    print(f'{len(da_fare)} formazioni | {len(fatte)} gia\' scaricate | '
          f'{len(manca)} da fare')

    for i, r in enumerate(manca, 1):
        d = graphql(Q, {'slug': r['contender_slug']})
        cont = ((d.get('data') or {}).get('so5') or {}).get('so5LeaderboardContender')
        app = ((cont or {}).get('so5Lineup') or {}).get('so5Appearances') or []
        if not app:
            continue
        fatte[r['contender_slug']] = {
            'fixture': r['fixture'], 'tipo': r['tipo'], 'slug': r['slug'],
            'mio_rank': r.get('mio_rank'), 'mio_score': r.get('mio_score'),
            'giocatori': [{
                'slug': (a.get('player') or {}).get('slug'),
                'nome': (a.get('player') or {}).get('displayName'),
                'carta': (a.get('anyCard') or {}).get('slug'),
                'ruolo': a.get('position'),
                'capitano': a.get('captain'),
                'punteggio': a.get('score')} for a in app]}
        if i % 25 == 0 or i == len(manca):
            print(f'[{i}/{len(manca)}] {r["fixture"]} {r["tipo"]}')
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump({'aggiornato': datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
                    'formazioni': fatte}, f, ensure_ascii=False, indent=1)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'aggiornato': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
            'formazioni': fatte}, f, ensure_ascii=False, indent=1)
    print(f'\n{len(fatte)} formazioni in archivio -> {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
