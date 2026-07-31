"""Risolve un conflitto git SOLO su best_five_prezzi_cache.json facendo
l'unione a livello di dizionario (per slug, tiene la voce con il 'ts' piu'
recente) invece di un merge -X ours che scarterebbe silenziosamente i prezzi
appena fetchati da un'altra lega in parallelo (stesso tipo di bug gia' visto
sui JSON di discovery il 28/07). Usato dai workflow best_five.yml e
best_five_contender.yml durante il retry di 'git push' in conflitto.

Legge le due versioni in conflitto (:2: ours, :3: theirs) via 'git show',
scrive il file unito su disco pronto per 'git add' + commit.
"""
import json
import subprocess
import sys


def _leggi_versione(stage, path):
    try:
        raw = subprocess.run(
            ['git', 'show', f':{stage}:{path}'],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(raw) if raw.strip() else {}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'best_five_prezzi_cache.json'
    ours = _leggi_versione(2, path)
    theirs = _leggi_versione(3, path)

    merged = dict(theirs)
    for slug, voce in ours.items():
        esistente = merged.get(slug)
        if esistente is None or voce.get('ts', '') >= esistente.get('ts', ''):
            merged[slug] = voce

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Cache unita: {len(ours)} (ours) + {len(theirs)} (theirs) -> {len(merged)} voci totali.")


if __name__ == '__main__':
    main()
