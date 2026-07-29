"""Passaggio di dati tra i job della pipeline formazioni via ARTIFACT invece
che via commit+push su main (29/07 notte, fix velocita').

## Perche'

Misurato sulla run reale 30484170456 (20m15s totali, 156 job):

    fase        job  wall   job-sec  di cui push git   lavoro utile
    discovery    36  247s      3079      1123 (36%)          1159
    predict      60  663s      7106      2429 (34%)          3327
    consiglio    58  268s      4020      2934 (73%)             0
    formazione    1   26s        26         2                   0
    TOTALE      156 1215s     14234      6488 (46%)          4486

Il 46% della compute totale se ne andava nello step `git commit + push` di
ogni job. La causa e' la contesa: ogni job pushava su `main` e il retry-loop
(`until git push; do sleep 5-17; fetch; merge -X ours; merge_discovery_json;
commit --amend; done`) fa vincere UN solo job per giro, quindi con 20 job che
pushano insieme l'ultimo pagava fino a 20 giri di attesa. Il job `consiglio`
era il caso limite: 2934s di push per 0s di lavoro vero.

Secondo vincolo, gia' noto (vedi commento in discovery_fixture.py e RIASSUNTO
sez. 30) ma mai sfruttato fino in fondo: l'account ha un tetto di **20 job
CONCORRENTI** (verificato: concorrenza massima osservata = 20 esatti su ogni
run, `max-parallel: 77` nel workflow e' inerte). Quindi il wall time e'
governato da `somma_job_secondi / 20`, e ogni job in piu' aggiunge il suo
costo fisso (checkout 12-13s + setup-python 2s + pip 3s + set up job 1s ~=
19s) al totale da dividere: 156 job = ~2900 job-secondi di solo overhead.

## Cosa fa questo modulo

Sostituisce il passaggio via git con gli artifact di Actions, e permette di
raggruppare le matrici in <= 20 job (uno per slot di concorrenza) senza
pagare 19s di overhead per ogni combinazione lega/ruolo.

I file NON smettono di essere committati: il job `salva_output` a fine run
scarica tutti gli artifact e fa UN solo commit con tutto (piu' il commit
dell'HTML dal job `formazione`), quindi lo stato finale di `main` e' lo
stesso di prima.

Sottocomandi:

  stage <stage_dir> [regex]
      Copia in <stage_dir> i file nuovi/modificati (secondo `git status`) il
      cui path relativo matcha <regex> (default: gli output delle formazioni),
      preservando il path. Scrive sempre un manifest, cosi' l'artifact esiste
      anche quando non e' cambiato nulla (una ri-run identica non deve far
      fallire il download a valle).

  apply <download_root>
      Riversa nel working tree tutti i file trovati in <download_root>/*/
      (un sottodirectory per artifact scaricato). Il PRIMO artifact che
      porta un path lo sovrascrive nel working tree (la versione della run
      corrente vince su quella committata dalla run precedente); dal SECONDO
      in poi, se il file e' uno dei JSON condivisi tra piu' shard, viene
      UNITO invece di sovrascritto -- stessa semantica di
      merge_discovery_json.py (lista -> unione ordinata, dict -> update),
      che esiste esattamente per questo (2 sotto-shard della stessa lega
      pesante scrivono lo STESSO player_slugs.json, ognuno con meta' roster:
      bug reale 28/07, Woledzi/Palacios spariti).

  matrice <n_gruppi>
      Legge le matrici emesse dai job discovery (env MATRICE_0..MATRICE_N),
      deduplica, e stampa su stdout in formato GITHUB_OUTPUT:
        matrice=            (invariata, serve alle guardie `if:` a valle)
        matrice_unique=     (una voce per coppia lega/ruolo, per il consiglio)
        gruppi_predict=     (<= n_gruppi bin, bilanciati per carico stimato)
      Va eseguito DOPO `apply`, perche' pesa ogni combinazione contando gli
      slug realmente presenti in player_slugs.json.

  combos <payload_b64>
      Stampa una riga TSV `lega<TAB>ruolo<TAB>shard` per ogni combinazione
      del gruppo (payload prodotto da `matrice`), da consumare in un ciclo
      shell nel job predict.
"""
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys


# Path (relativi alla root del repo) considerati output della pipeline.
DEFAULT_PATH_RE = r'^formazione_[^/]+/output/'
DISCOVERY_PATH_RE = r'^formazione_[^/]+/output/[^/]+_discovery/'

# Nome del manifest scritto in ogni stage dir: garantisce che l'artifact non
# sia mai vuoto (upload-artifact salta l'upload se non trova file, e il
# download a valle fallirebbe).
MANIFEST = '_stage_manifest.txt'

# File che piu' job possono scrivere per la STESSA coppia lega/ruolo e che
# vanno quindi UNITI, non sovrascritti (vedi merge_discovery_json.py).
MERGEABLE = (
    'player_slugs.json',        # lista di slug -> unione
    'player_names.json',        # dict slug->nome -> update
    'player_card_counts.json',  # dict slug->conteggi -> update
    'prediction_log.json',      # dict slug->predizione live -> update
)

# Costo relativo per giocatore di ogni ruolo, usato SOLO per bilanciare i
# gruppi di job predict (non tocca in alcun modo lo scoring). FWD e' il piu'
# caro: opponent_strength.py gli scansiona DUE cartelle cache invece di una
# (goals_conceded + poss_lost_ctrl). Misurato sulla run 30484170456: i job
# piu' lenti erano tutti FWD (scozia/fwd 398s, olanda/fwd 357s) contro
# 40-190s degli altri ruoli.
ROLE_COST = {'fwd': 2.0, 'mid': 1.3, 'def': 1.0, 'gk': 1.0}


# ---------------------------------------------------------------- stage ----

def _git_changed(path_re):
    """Path relativi dei file nuovi o modificati che matchano path_re."""
    out = subprocess.run(
        ['git', 'status', '--porcelain', '-z', '--untracked-files=all'],
        capture_output=True, text=True, check=True,
    ).stdout
    rx = re.compile(path_re)
    changed = []
    for entry in out.split('\0'):
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        # Cancellazioni: niente da copiare. Rinomine: non le produce nessuno
        # script della pipeline (i file di output sono sempre nuovi o
        # riscritti in place), ma per sicurezza le ignoriamo invece di
        # interpretare male il formato a due path di `git status -z`.
        if 'D' in code or 'R' in code:
            continue
        path = path.replace('\\', '/')
        if rx.match(path) and os.path.isfile(path):
            changed.append(path)
    return sorted(changed)


def cmd_stage(argv):
    stage_dir = argv[0]
    path_re = argv[1] if len(argv) > 1 else DEFAULT_PATH_RE
    os.makedirs(stage_dir, exist_ok=True)
    files = _git_changed(path_re)
    for path in files:
        dst = os.path.join(stage_dir, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    with open(os.path.join(stage_dir, MANIFEST), 'w', encoding='utf-8') as f:
        f.write('\n'.join(files) + '\n')
    print(f'[stage] {len(files)} file in {stage_dir} (filtro {path_re})')
    for path in files[:40]:
        print(f'  {path}')
    if len(files) > 40:
        print(f'  ... e altri {len(files) - 40}')
    return 0


# ---------------------------------------------------------------- apply ----

def _merge_json(dst, src):
    """Unisce src (artifact) in dst (working tree) con la stessa semantica di
    merge_discovery_json.py. Ritorna True se ha scritto dst."""
    try:
        with open(dst, encoding='utf-8') as f:
            ours = json.load(f)
        with open(src, encoding='utf-8') as f:
            theirs = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(ours, list) and isinstance(theirs, list):
        merged = sorted(set(ours) | set(theirs))
    elif isinstance(ours, dict) and isinstance(theirs, dict):
        merged = dict(ours)
        merged.update(theirs)
    else:
        return False
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False)
    return True


def cmd_apply(argv):
    root = argv[0]
    if not os.path.isdir(root):
        print(f'[apply] nessun artifact in {root}')
        return 0
    # Ordine deterministico degli artifact, cosi' due esecuzioni sugli stessi
    # dati producono lo stesso risultato.
    art_dirs = sorted(
        os.path.join(root, d) for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d))
    )
    written = {}   # path relativo -> primo artifact che l'ha portato
    n_copy = n_merge = n_skip = 0
    for art in art_dirs:
        for dirpath, _dirnames, filenames in os.walk(art):
            for name in filenames:
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, art).replace('\\', '/')
                if rel == MANIFEST:
                    continue
                if rel in written and name in MERGEABLE:
                    if _merge_json(rel, src):
                        n_merge += 1
                        continue
                    n_skip += 1
                    print(f'[apply] ATTENZIONE: merge non riuscito per {rel} '
                          f'(da {os.path.basename(art)}), tengo '
                          f'{written[rel]}')
                    continue
                if rel in written:
                    # Path portato da due artifact ma non unibile: non
                    # dovrebbe capitare (i prediction_*.txt hanno slug e
                    # timestamp nel nome), lo segnaliamo invece di
                    # sovrascrivere in silenzio.
                    n_skip += 1
                    print(f'[apply] ATTENZIONE: {rel} presente in '
                          f'{written[rel]} e {os.path.basename(art)}, '
                          f'tengo il primo')
                    continue
                os.makedirs(os.path.dirname(rel) or '.', exist_ok=True)
                shutil.copy2(src, rel)
                written[rel] = os.path.basename(art)
                n_copy += 1
    print(f'[apply] {len(art_dirs)} artifact -> {n_copy} file copiati, '
          f'{n_merge} uniti, {n_skip} ignorati')
    return 0


# -------------------------------------------------------------- matrice ----

def _matrice_dai_job():
    """Concatena e deduplica le matrici emesse dai job discovery."""
    parts = []
    for i in range(200):
        raw = os.environ.get(f'MATRICE_{i}')
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            parts.append(json.loads(raw))
        except json.JSONDecodeError:
            print(f'[matrice] MATRICE_{i} non e\' JSON valido, ignorata',
                  file=sys.stderr)
    combined, seen = [], set()
    for combo in (x for p in parts for x in p):
        key = json.dumps(combo, sort_keys=True)
        if key not in seen:
            seen.add(key)
            combined.append(combo)
    return combined


def _conta_slug():
    """(lega, ruolo) -> numero di slug in player_slugs.json."""
    counts = {}
    for path in glob.glob('formazione_*/output/*_discovery/player_slugs.json'):
        path = path.replace('\\', '/')
        lega = path.split('/')[0][len('formazione_'):]
        dirname = path.split('/')[2]              # <lega>_<ruolo>_discovery
        ruolo = dirname[len(lega) + 1:-len('_discovery')]
        try:
            with open(path, encoding='utf-8') as f:
                slugs = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(slugs, list):
            counts[(lega, ruolo)] = len(slugs)
    return counts


def _peso(combo, counts):
    """Carico stimato di una combinazione (numero di slug del suo shard,
    pesato per il costo del ruolo)."""
    tot = counts.get((combo['league'], combo['role']), 0)
    shard = (combo.get('shard') or '').strip()
    n_slug = tot
    if shard:
        try:
            idx, n = (int(x) for x in shard.split(':'))
            n_slug = len([i for i in range(tot) if i % n == idx])
        except ValueError:
            pass
    costo = ROLE_COST.get(combo['role'], 1.0)
    return max(n_slug, 1) * costo


def _bin_packing(combos, counts, n_bins):
    """LPT (longest processing time first): ordina per carico decrescente e
    mette ogni combinazione nel bin piu' scarico. Serve a evitare il caso
    reale della run 30484170456, dove un solo job (scozia/fwd, 398s) teneva
    in piedi l'intera fase predict mentre gli altri finivano in 40s."""
    pesate = sorted(((_peso(c, counts), c) for c in combos),
                    key=lambda x: -x[0])
    n_bins = max(1, min(n_bins, len(pesate)))
    bins = [{'peso': 0.0, 'combos': []} for _ in range(n_bins)]
    for peso, combo in pesate:
        b = min(bins, key=lambda b: b['peso'])
        b['peso'] += peso
        b['combos'].append(combo)
    return [b for b in bins if b['combos']]


def _etichetta(combos):
    """Nome leggibile del gruppo per la UI di Actions (i nomi dei job a
    matrice vengono dal valore della matrice: un blob base64 li renderebbe
    illeggibili)."""
    voci = []
    for c in combos[:3]:
        shard = (c.get('shard') or '').strip()
        voci.append(f"{c['league']}/{c['role']}" + (f"[{shard}]" if shard else ''))
    testo = ' '.join(voci)
    if len(combos) > 3:
        testo += f' +{len(combos) - 3}'
    return testo


def cmd_matrice(argv):
    n_gruppi = int(argv[0]) if argv else 20
    combos = _matrice_dai_job()
    counts = _conta_slug()

    unique = []
    for c in combos:
        pair = {'league': c['league'], 'role': c['role']}
        if pair not in unique:
            unique.append(pair)

    gruppi = []
    for i, b in enumerate(_bin_packing(combos, counts, n_gruppi)):
        payload = base64.b64encode(
            json.dumps(b['combos'], separators=(',', ':')).encode()
        ).decode()
        gruppi.append({
            'nome': f"{i + 1:02d} {_etichetta(b['combos'])}",
            'g': payload,
        })

    def _dump(x):
        return json.dumps(x, separators=(',', ':'))

    print('matrice=' + _dump(combos))
    print('matrice_unique=' + _dump(unique))
    print('gruppi_predict=' + _dump(gruppi))

    tot = sum(_peso(c, counts) for c in combos)
    print(f'[matrice] {len(combos)} combinazioni ({len(unique)} coppie '
          f'lega/ruolo, carico stimato {tot:.0f}) -> {len(gruppi)} gruppi '
          f'predict', file=sys.stderr)
    for i, b in enumerate(_bin_packing(combos, counts, n_gruppi)):
        print(f'  gruppo {i + 1:02d}: carico {b["peso"]:6.1f}  '
              f'{len(b["combos"])} combo  {_etichetta(b["combos"])}',
              file=sys.stderr)
    return 0


# --------------------------------------------------------------- combos ----

def cmd_combos(argv):
    combos = json.loads(base64.b64decode(argv[0]).decode())
    for c in combos:
        print(f"{c['league']}\t{c['role']}\t{(c.get('shard') or '').strip()}")
    return 0


def cmd_coppie(_argv):
    """Righe TSV `lega<TAB>ruolo` (una per coppia) dalla matrice unica passata
    nell'env MATRICE_UNIQUE, per il ciclo del job consiglio."""
    combos = json.loads(os.environ.get('MATRICE_UNIQUE') or '[]')
    for c in combos:
        print(f"{c['league']}\t{c['role']}")
    return 0


def cmd_slugs(argv):
    """Slug (separati da spazio) da elaborare per una combinazione
    lega/ruolo/shard. Stessa logica di split che stava inline nel workflow
    (`i % n == idx` sulla lista ordinata di player_slugs.json): l'insieme di
    slug processati da ogni shard e' INVARIATO."""
    lega, ruolo = argv[0], argv[1]
    shard = (argv[2] if len(argv) > 2 else '').strip()
    path = (f'formazione_{lega}/output/{lega}_{ruolo}_discovery/'
            'player_slugs.json')
    with open(path, encoding='utf-8') as f:
        slugs = json.load(f)
    if shard:
        idx, n = (int(x) for x in shard.split(':'))
        slugs = [s for i, s in enumerate(slugs) if i % n == idx]
    print(' '.join(slugs))
    return 0


COMANDI = {
    'stage': cmd_stage,
    'apply': cmd_apply,
    'matrice': cmd_matrice,
    'combos': cmd_combos,
    'coppie': cmd_coppie,
    'slugs': cmd_slugs,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDI:
        print(__doc__)
        return 2
    return COMANDI[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
