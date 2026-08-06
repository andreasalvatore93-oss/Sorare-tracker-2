"""Sez.25: completa storico_grade_backtest_20260806.json con gli slug del
pool P-tutte (arene di qualsiasi tipo, 10 manager reali, 8 GW) mai
interrogati perche' righe_*.json copriva solo le carte finite in arena
Cap/Uncapped. Lista in analisi_manager/p12_slug_mancanti_sez25.json (53
slug, calcolata come pool P-tutte - gia' raccolti). Stessa rotta F6
(anyPlayer.playerGameScores), stesso file di output, append/resume-safe.

Uso: SORARE_COOKIE=... SORARE_CSRF=... python analisi_manager/p12_raccolta_grade_backtest_extra.py
"""
import sys, os, io, json, time

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
import p12_raccolta_grade_backtest as R

OUT = 'analisi_manager/dati/storico_grade_backtest_20260806.json'


def main():
    r = R.g._http_session.post(R.g.GRAPHQL_URL, json={'query': '{ currentUser { slug } }'},
                               headers={'Content-Type': 'application/json', 'Cookie': R.COOKIES, 'X-CSRF-Token': R.CSRF},
                               timeout=20)
    who = (r.json().get('data') or {}).get('currentUser')
    print('currentUser:', who, flush=True)
    if not who or not who.get('slug'):
        print('SESSIONE NON VALIDA -- mi fermo.')
        return

    prev = json.load(open(OUT, encoding='utf-8'))
    risultati, errori = prev.get('giocatori', []), prev.get('errori', [])
    gia_fatti = set(p['slug'] for p in risultati) | set(e['slug'] for e in errori)

    mancanti = json.load(open('analisi_manager/p12_slug_mancanti_sez25.json', encoding='utf-8'))
    slugs = [s for s in mancanti if s not in gia_fatti]
    print(f'slug da raccogliere: {len(slugs)} (di {len(mancanti)} nella lista, {len(mancanti)-len(slugs)} gia\' fatti)', flush=True)

    t0 = time.time()
    for i, slug in enumerate(slugs, 1):
        player, err = R.query_slug(slug)
        if err:
            errori.append({'slug': slug, 'errore': err})
        elif player is None:
            errori.append({'slug': slug, 'errore': 'anyPlayer nullo'})
        else:
            risultati.append(player)
        if i % 25 == 0 or i == len(slugs):
            print(f'  [{i}/{len(slugs)}] ok={len(risultati)} errori={len(errori)}  ({time.time()-t0:.0f}s)', flush=True)
            json.dump({'giocatori': risultati, 'errori': errori}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        time.sleep(1.0)

    json.dump({'giocatori': risultati, 'errori': errori}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\nFINE: {len(risultati)} ok totali, {len(errori)} errori totali. Salvato in {OUT}', flush=True)


if __name__ == '__main__':
    main()
