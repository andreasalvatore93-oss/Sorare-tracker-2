"""Unisce i file JSON di discovery (player_slugs.json/player_names.json/
player_card_counts.json) tra la copia locale e origin/main, invece di
scartare uno dei due con 'git merge -X ours' (bug reale 28/07: per MLS/K
League la discovery di GK/DEF/MID/FWD e' spezzata in 2 sotto-shard che
scansionano meta' roster ciascuno e scrivono sullo STESSO file -- essendo
un dump JSON su una riga, QUALSIASI conflitto viene risolto da -X ours
tenendo per intero la versione del sotto-shard che fa la merge, scartando
per intero l'altra meta' del roster gia' pushata. Woledzi/Palacios spariti
da mls_def_discovery in questo modo, scoperto verificando con l'API reale
che le carte esistono ma non risultavano piu' nel file finale).

Va chiamato DOPO 'git merge --no-edit -X ours origin/main' (che ha gia'
risolto la storia git, tenendo per ora la versione locale): questo script
corregge il CONTENUTO dei file unendo quello che origin/main aveva e che
-X ours ha scartato, poi il chiamante deve ri-committare (git commit
--amend) prima di ritentare il push."""
import glob
import json
import subprocess


def _origin_content(path):
    try:
        out = subprocess.run(
            ['git', 'show', f'origin/main:{path}'],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _merge_file(path):
    theirs = _origin_content(path)
    if theirs is None:
        return
    try:
        with open(path, encoding='utf-8') as f:
            ours = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        ours = None
    if ours is None:
        merged = theirs
    elif isinstance(ours, dict) and isinstance(theirs, dict):
        merged = dict(theirs)
        merged.update(ours)
    elif isinstance(ours, list) and isinstance(theirs, list):
        merged = sorted(set(ours) | set(theirs))
    else:
        return
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False)


def main():
    paths = []
    for pattern in ('player_slugs.json', 'player_names.json', 'player_card_counts.json'):
        paths += glob.glob(f'formazione_*/output/*_discovery/{pattern}')
    for path in paths:
        _merge_file(path.replace('\\', '/'))


if __name__ == '__main__':
    main()
