"""Scarica rewardsConfig (premio VERO, jackpot incluso) per ogni arena di
dati_globali/classifiche_arene_2026-08-08.json. Sessione ANONIMA (verificato
09/08, HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt §11: la query funziona senza
cookie e i premi letti coincidono coi jackpot noti, 4/4).

File NUOVO, salvataggio incrementale, ripredibile (salta gli slug gia'
presenti), non sovrascrive mai un file piu' grande col piu' piccolo.
"""
import json
import os
import time
import collections

try:
    from curl_cffi import requests as _rq
    S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    S = _rq.Session()

URL = 'https://api.sorare.com/federation/graphql'
IN_PATH = 'dati_globali/classifiche_arene_2026-08-08.json'
OUT_PATH = 'dati_globali/premi_arene_2026-08-08.json'
FALLITI_PATH = 'dati_globali/premi_arene_2026-08-08_falliti.json'
PAUSA = 0.4

HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'Origin': 'https://sorare.com',
    'Referer': 'https://sorare.com/',
    'Accept-Language': 'it',
    'sorare-client': 'Web',
    'sorare-version': '20260717144535',
    'sorare-build': '41952aef67694959421f5e001684878b72a52225',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
}

Q = """
query Premi($slug: String!) {
  so5 {
    so5Leaderboard(slug: $slug) {
      rewardsConfig {
        ranking {
          ranks
          rewardConfigs { __typename ... on CardShardRewardConfig { quantity } }
        }
      }
    }
  }
}
"""


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def graphql(slug):
    for tentativo in range(6):
        S.cookies.clear()
        try:
            r = S.post(URL, json={'query': Q, 'variables': {'slug': slug}}, headers=HEADERS, timeout=30)
        except Exception as e:
            time.sleep(3 * (tentativo + 1))
            continue
        if r.status_code == 429:
            attesa = min(int(r.headers.get('retry-after') or 0) or 2 ** tentativo * 3, 90)
            log(f'  429, aspetto {attesa}s')
            time.sleep(attesa)
            continue
        try:
            return r.json()
        except Exception:
            return {'errors': [{'message': f'HTTP {r.status_code}'}]}
    return {'errors': [{'message': '429 dopo 6 tentativi'}]}


def premi_da_ranking(ranking):
    """[(posizione_1based, quantity_o_None_se_currency)]"""
    out = []
    pos = 1
    for fascia in ranking or []:
        larghezza = fascia.get('ranks') or 1
        rc = (fascia.get('rewardConfigs') or [])
        q = None
        for x in rc:
            if x.get('__typename') == 'CardShardRewardConfig':
                q = x.get('quantity')
                break
        for _ in range(larghezza):
            out.append((pos, q))
            pos += 1
    return out


def carica_esistenti():
    if not os.path.exists(OUT_PATH):
        return {}
    try:
        d = json.load(open(OUT_PATH, encoding='utf-8'))
        return {a['slug']: a for a in d.get('arene', [])}
    except Exception:
        return {}


def salva(risultati, falliti):
    tmp = OUT_PATH + '.tmp'
    json.dump({'aggiornato': 'scarica_premi_arene.py (sessione anonima, rewardsConfig)',
               'arene': list(risultati.values())},
              open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)
    json.dump(falliti, open(FALLITI_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def main():
    d = json.load(open(IN_PATH, encoding='utf-8'))
    arene = d['arene']
    log(f'arene totali da processare: {len(arene)}')

    esistenti = carica_esistenti()
    log(f'gia\' presenti (ripresa): {len(esistenti)}')
    da_fare = [a for a in arene if a['slug'] not in esistenti]
    log(f'restano da scaricare: {len(da_fare)}')

    falliti = json.load(open(FALLITI_PATH, encoding='utf-8')) if os.path.exists(FALLITI_PATH) else []

    per_tipo_ok = collections.Counter()
    for i, a in enumerate(da_fare, 1):
        body = graphql(a['slug'])
        errore = None
        if body.get('errors'):
            errore = str(body['errors'])[:200]
        else:
            lb = ((body.get('data') or {}).get('so5') or {}).get('so5Leaderboard')
            if not lb:
                errore = 'so5Leaderboard null'
            else:
                rc = lb.get('rewardsConfig')
                if not rc:
                    errore = 'rewardsConfig null'
                else:
                    ranking = rc.get('ranking')
                    premi = premi_da_ranking(ranking)
                    esistenti[a['slug']] = {'slug': a['slug'], 'tipo': a['tipo'],
                                             'premi_per_posizione': premi}
                    per_tipo_ok[a['tipo']] += 1

        if errore:
            falliti.append({'slug': a['slug'], 'tipo': a['tipo'], 'errore': errore})

        if i % 100 == 0 or i == len(da_fare):
            salva(esistenti, falliti)
            log(f'progresso: {i}/{len(da_fare)}  ok totali={len(esistenti)}  '
                f'falliti totali={len(falliti)}  per tipo ok finora={dict(per_tipo_ok)}')

        time.sleep(PAUSA)

    salva(esistenti, falliti)
    log(f'FINE. ok totali={len(esistenti)}  falliti totali={len(falliti)}')
    log(f'file: {OUT_PATH}')


if __name__ == '__main__':
    main()
