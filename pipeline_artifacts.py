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

# ------------------------------------------------- modello di costo -------
# Bilanciare i gruppi predict "per numero di giocatori" non funziona: misurato
# sulla run 30496069817, il costo per giocatore varia di 80 volte tra coppie
# lega/ruolo (mls/def 0.0s, scozia/fwd 31s, cile/fwd 35s) e NON e' una
# proprieta' del ruolo (mls/fwd 0.0s contro scozia/fwd 31s). Con un modello
# per ruolo, scozia/fwd (13 giocatori x 31s = ~400s) finiva tutto in un solo
# job indivisibile e teneva in piedi l'intera fase predict per 6m35s mentre il
# pavimento teorico era ~80s.
#
# pipeline_costi.json (committato, aggiornato da ogni run tramite i
# sottocomandi 'costi'/'aggrega_costi') tiene per ogni coppia lega/ruolo:
#   [primo_giocatore_s, giocatore_successivo_s]
# cioe' costo(k giocatori nello stesso job) = primo + (k-1) * resto.
# Il 'primo' include quello che si paga una volta per processo/lega
# (costruzione serie opponent_strength, warm-up delle cache su disco), il
# 'resto' il costo marginale. La distinzione conta: per giappone/gk
# (primo 43s, resto 0s) spezzare la coppia in piu' shard COSTA, per
# scozia/fwd (primo 31s, resto 31s) e' gratis.
COSTI_PATH = 'pipeline_costi.json'

# ATTENZIONE (misurato, run 30497294536 contro 30496069817): il costo per
# giocatore di una coppia NON e' una proprieta' stabile della coppia. A 15
# minuti di distanza, con gli stessi giocatori, olanda/fwd e' passato da 1.0s
# a 14.6s per giocatore. La causa e' a monte (limite di complessita' GraphQL
# di Sorare: con cache fredda la query allPlayerGameScores chiede troppe
# partite, sfonda il tetto di complessita' 500 e fa scattare il retry esterno
# da 10+20+40s), e quali giocatori la sfondano cambia da run a run.
#
# Conseguenza: la tabella dei costi NON puo' essere l'unico presidio. Fidarsi
# solo di lei ha PEGGIORATO i tempi (13m56s contro 10m53s): olanda/fwd era
# stimata 30s, non veniva spezzata, e ha poi impiegato 437s in un solo job.
# Il presidio vero e' MAX_GIOCATORI_PER_SHARD: nessuno shard puo' contenere
# tanti giocatori da diventare lungo NEMMENO nel caso peggiore, qualunque
# cosa dica la stima. I costi misurati servono solo a ordinare il
# riempimento dei bin, con pavimento e tetto per non credere a stime assurde.

# Nessuno shard oltre questo numero di giocatori. Abbassato da 8 a 5 (30/07)
# assieme all'aumento di N_BIN: col pacing adattivo il lavoro totale di
# predict e' scesso a 2416s (pavimento ~156s a 20 slot) ma il wall era rimasto
# a 285s, cioe' 129s di sola inefficienza di packing. Il tail era un bin
# dispatchato TARDI che si e' rivelato lungo (161s) perche' la tabella dei
# costi lo dava per leggero: con stime inevitabilmente stantie (i costi si
# muovono a ogni run) l'unica difesa e' che nessun bin possa essere lungo.
MAX_GIOCATORI_PER_SHARD = 5

# Pavimento e tetto applicati al costo marginale misurato quando si pesa uno
# shard: proteggono dalle stime a 0s (che facevano finire 46 giocatori in un
# bin dato per vuoto) e da quelle patologiche.
MARGINALE_MIN_S = 4.0
MARGINALE_MAX_S = 31.0

# Fallback per una coppia mai misurata: prudente (meglio sovrastimare, cosi'
# viene spezzata e distribuita) ma non assurdo.
COSTO_IGNOTO = (15.0, 5.0)

# Peso massimo (secondi stimati) di un singolo shard: si ricava dal carico
# totale diviso gli slot di concorrenza, con un minimo per non sminuzzare
# all'infinito pagando N volte il costo di setup.
SLOT_CONCORRENTI = 20
TARGET_MIN_S = 45.0

# Numero di bin emessi (alzato da 45 a 65 il 30/07, vedi
# MAX_GIOCATORI_PER_SHARD). Volutamente MOLTO maggiore di SLOT_CONCORRENTI e
# ordinati dal piu' pesante al piu' leggero: Actions ne avvia 20 e mette gli
# altri in coda, avviandoli man mano che uno slot si libera. E' bilanciamento
# dinamico gratuito, e con costi per giocatore instabili (vedi sopra) e' il
# solo presidio che funziona davvero: piu' bin ci sono, meno pesa sbagliare
# una stima, perche' il lavoro si redistribuisce a runtime invece di essere
# congelato in un'assegnazione statica. Il prezzo sono ~22s fissi di
# checkout+setup per bin in piu' (45 bin = ~990 job-secondi = ~50s di wall a
# 20 slot), che si ripagano al primo shard mal stimato evitato.
N_BIN = 65


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

MATRICI_DIR = '_matrici'


def _matrice_dai_job():
    """Concatena e deduplica le matrici prodotte dai job discovery.

    Le legge dai file `_matrici/*.json` portati dagli artifact. Prima stavano
    negli output di job (env MATRICE_0..35), ma con i 36 shard raggruppati in
    un solo job a matrice quella strada non funziona piu': un job che esegue
    piu' shard in sequenza scriverebbe piu' volte lo stesso output e vincerebbe
    solo l'ultimo. L'env resta letto come ripiego, per non rompere nulla se
    qualche chiamante vecchio lo usa ancora."""
    parts = []
    for path in sorted(glob.glob(os.path.join(MATRICI_DIR, '*.json'))):
        try:
            with open(path, encoding='utf-8') as f:
                testo = f.read().strip()
            if testo:
                parts.append(json.loads(testo))
        except (OSError, json.JSONDecodeError):
            print(f'[matrice] {path} non leggibile/non JSON, ignorato',
                  file=sys.stderr)
    if parts:
        print(f'[matrice] {len(parts)} matrici lette da {MATRICI_DIR}/',
              file=sys.stderr)
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


def _carica_costi():
    try:
        with open(COSTI_PATH, encoding='utf-8') as f:
            return json.load(f).get('costi') or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _costo_coppia(costi, lega, ruolo):
    """(primo, resto) per una coppia. Per una coppia mai misurata ripiega
    sulla mediana del ruolo (le coppie dello stesso ruolo si somigliano piu'
    di quelle di leghe diverse) e poi su COSTO_IGNOTO."""
    v = costi.get(f'{lega}/{ruolo}')
    if v and len(v) == 2:
        return float(v[0]), float(v[1])
    stessi = [v for k, v in costi.items()
              if k.endswith('/' + ruolo) and v and len(v) == 2]
    if stessi:
        primi = sorted(float(v[0]) for v in stessi)
        resti = sorted(float(v[1]) for v in stessi)
        mid = len(stessi) // 2
        return max(primi[mid], COSTO_IGNOTO[0]), max(resti[mid], COSTO_IGNOTO[1])
    return COSTO_IGNOTO


def _costo(k, primo, resto):
    """Secondi stimati per un job che elabora k giocatori di una coppia."""
    if k <= 0:
        return 0.0
    return primo + (k - 1) * resto


def _shard_n(k, primo, resto, target):
    """In quanti shard spezzare una coppia da k giocatori perche' nessuno
    superi `target` secondi. Tiene conto del fatto che ogni shard ripaga il
    costo di setup (`primo`): se `primo` da solo sfonda il target, spezzare
    oltre non serve e si ferma."""
    if k <= 1:
        return 1
    for n in range(1, k + 1):
        per_shard = -(-k // n)          # ceil
        if _costo(per_shard, primo, resto) <= target:
            return n
        if per_shard <= 1:
            break
    return k


def _combos_da_coppie(unique, counts, costi):
    """Costruisce la lista di shard da elaborare partendo dalle coppie
    lega/ruolo trovate dalla discovery e dal conteggio VERO degli slug dopo
    il merge.

    Sostituisce gli shard calcolati da discovery_fixture.py, che li derivava
    dal conteggio PARZIALE visto dal singolo job: per le leghe pesanti
    (HEAVY_LEAGUE_SHARD) i due sotto-shard vedono meta' roster ciascuno e
    potevano emettere famiglie di shard incoerenti. Bug reale osservato sulla
    run 30494326179: la matrice conteneva insieme {mls,gk} (tutti gli slug),
    {mls,gk,0:2} e {mls,gk,1:2}, quindi OGNI giocatore mls/gk veniva
    elaborato DUE volte."""
    # Prima passata con shard_n=1 per stimare il carico totale, seconda per
    # fissare il target (spezzare aumenta il totale, ripagando il setup).
    base = []
    for pair in unique:
        k = counts.get((pair['league'], pair['role']), 0)
        primo, resto = _costo_coppia(costi, pair['league'], pair['role'])
        base.append((pair, k, primo, resto))
    tot = sum(_costo(k, p, r) for _pair, k, p, r in base)
    target = max(TARGET_MIN_S, tot / SLOT_CONCORRENTI)

    combos = []
    for pair, k, primo, resto in base:
        # Il massimo tra quello che dice la stima e il tetto DURO sul numero
        # di giocatori: e' quest'ultimo il presidio contro le stime sbagliate.
        n = max(_shard_n(k, primo, resto, target),
                -(-k // MAX_GIOCATORI_PER_SHARD) if k else 1)
        n = max(1, min(n, max(k, 1)))
        if n <= 1:
            combos.append(dict(pair))
        else:
            for i in range(n):
                combos.append({**pair, 'shard': f'{i}:{n}'})
    return combos, target


def _peso(combo, counts, costi):
    """Carico stimato in secondi di un singolo shard."""
    tot = counts.get((combo['league'], combo['role']), 0)
    shard = (combo.get('shard') or '').strip()
    k = tot
    if shard:
        try:
            idx, n = (int(x) for x in shard.split(':'))
            k = len([i for i in range(tot) if i % n == idx])
        except ValueError:
            pass
    primo, resto = _costo_coppia(costi, combo['league'], combo['role'])
    # Marginale con pavimento/tetto: vedi il commento su MARGINALE_MIN_S.
    resto = min(max(resto, MARGINALE_MIN_S), MARGINALE_MAX_S)
    return _costo(k, min(max(primo, resto), MARGINALE_MAX_S * 2), resto)


def _bin_packing(combos, counts, costi, n_bins):
    """LPT (longest processing time first): ordina per carico decrescente e
    mette ogni shard nel bin piu' scarico. I bin escono ordinati dal piu'
    pesante al piu' leggero, cosi' Actions avvia per primi quelli lunghi e
    usa quelli corti per riempire la coda."""
    pesate = sorted(((_peso(c, counts, costi), c) for c in combos),
                    key=lambda x: -x[0])
    n_bins = max(1, min(n_bins, len(pesate)))
    bins = [{'peso': 0.0, 'combos': []} for _ in range(n_bins)]
    for peso, combo in pesate:
        b = min(bins, key=lambda b: b['peso'])
        b['peso'] += peso
        b['combos'].append(combo)
    return sorted((b for b in bins if b['combos']),
                  key=lambda b: -b['peso'])


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
    n_gruppi = int(argv[0]) if argv else N_BIN
    dai_job = _matrice_dai_job()
    counts = _conta_slug()
    costi = _carica_costi()

    # Coppie lega/ruolo da elaborare: vengono dai job discovery (solo le leghe
    # con giocatori eleggibili in questa giornata). Gli shard invece si
    # ricalcolano qui sul conteggio vero -- vedi _combos_da_coppie.
    unique = []
    for c in dai_job:
        pair = {'league': c['league'], 'role': c['role']}
        if pair not in unique:
            unique.append(pair)

    combos, target = _combos_da_coppie(unique, counts, costi)
    bins = _bin_packing(combos, counts, costi, n_gruppi)

    gruppi = []
    for i, b in enumerate(bins):
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

    tot = sum(_peso(c, counts, costi) for c in combos)
    n_giocatori = sum(counts.get((p['league'], p['role']), 0) for p in unique)
    print(f'[matrice] {len(unique)} coppie lega/ruolo, {n_giocatori} giocatori,'
          f' {len(costi)} coppie con costo misurato', file=sys.stderr)
    print(f'[matrice] carico stimato {tot:.0f}s -> target per shard '
          f'{target:.0f}s -> {len(combos)} shard in {len(bins)} gruppi '
          f'(pavimento teorico {tot / SLOT_CONCORRENTI:.0f}s a '
          f'{SLOT_CONCORRENTI} slot)', file=sys.stderr)
    for i, b in enumerate(bins):
        print(f'  gruppo {i + 1:02d}: {b["peso"]:6.1f}s  '
              f'{len(b["combos"])} shard  {_etichetta(b["combos"])}',
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


# ---------------------------------------------------------------- costi ----
# Cartella dei parziali di misura (una per gruppo predict), non committata:
# 'aggrega_costi' li fonde in pipeline_costi.json a fine run.
COSTI_PARZIALI_DIR = '_costi_parziali'

# Peso della misura nuova nella media esponenziale. Basso di proposito: i
# tempi di una singola run sono rumorosi (rate-limit, cache fredda del
# runner), il modello deve muoversi piano.
COSTI_ALPHA = 0.3


def cmd_costi(argv):
    """Aggrega le misure per giocatore di UN gruppo predict (TSV
    `lega<TAB>ruolo<TAB>secondi`, nell'ordine di elaborazione) in un parziale
    dentro la stage dir. Il PRIMO giocatore di ogni coppia nel job da la
    stima di `primo` (setup incluso), gli altri quella di `resto`."""
    tsv, stage_dir = argv[0], argv[1]
    idx = argv[2] if len(argv) > 2 else '0'
    primi, resti = {}, {}
    try:
        with open(tsv, encoding='utf-8') as f:
            righe = [l.rstrip('\n').split('\t') for l in f if l.strip()]
    except OSError:
        righe = []
    for r in righe:
        if len(r) < 3:
            continue
        pair = f'{r[0]}/{r[1]}'
        try:
            sec = float(r[2])
        except ValueError:
            continue
        if pair not in primi:
            primi[pair] = sec
        else:
            resti.setdefault(pair, []).append(sec)
    dati = {}
    for pair, primo in primi.items():
        v = resti.get(pair) or []
        dati[pair] = {'primo': primo, 'resti': v}
    dst_dir = os.path.join(stage_dir, COSTI_PARZIALI_DIR)
    os.makedirs(dst_dir, exist_ok=True)
    with open(os.path.join(dst_dir, f'{idx}.json'), 'w', encoding='utf-8') as f:
        json.dump(dati, f, ensure_ascii=False)
    print(f'[costi] {len(dati)} coppie misurate in questo gruppo')
    return 0


def cmd_aggrega_costi(_argv):
    """Fonde i parziali in pipeline_costi.json con media esponenziale."""
    try:
        with open(COSTI_PATH, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        doc = {}
    costi = doc.get('costi') or {}
    primi, resti = {}, {}
    for path in sorted(glob.glob(os.path.join(COSTI_PARZIALI_DIR, '*.json'))):
        try:
            with open(path, encoding='utf-8') as f:
                dati = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for pair, v in dati.items():
            primi.setdefault(pair, []).append(v.get('primo', 0.0))
            resti.setdefault(pair, []).extend(v.get('resti') or [])
    if not primi:
        print('[aggrega_costi] nessun parziale, pipeline_costi.json invariato')
        return 0

    def _mediana(v):
        v = sorted(v)
        n = len(v)
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

    n_nuove = n_agg = 0
    for pair in sorted(primi):
        p_new = _mediana(primi[pair])
        r_new = _mediana(resti[pair]) if resti.get(pair) else p_new
        p_new = max(p_new, r_new)
        vecchio = costi.get(pair)
        if vecchio and len(vecchio) == 2:
            p = (1 - COSTI_ALPHA) * float(vecchio[0]) + COSTI_ALPHA * p_new
            r = (1 - COSTI_ALPHA) * float(vecchio[1]) + COSTI_ALPHA * r_new
            n_agg += 1
        else:
            p, r = p_new, r_new
            n_nuove += 1
        costi[pair] = [round(p, 1), round(r, 1)]

    doc['_modello'] = ('lega/ruolo -> [primo_giocatore_s, '
                       'giocatore_successivo_s]; usato SOLO per bilanciare i '
                       'gruppi di job predict, nessun effetto sullo scoring')
    doc['costi'] = costi
    with open(COSTI_PATH, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f'[aggrega_costi] {n_agg} coppie aggiornate, {n_nuove} nuove, '
          f'{len(costi)} totali in {COSTI_PATH}')
    return 0


COMANDI = {
    'stage': cmd_stage,
    'apply': cmd_apply,
    'matrice': cmd_matrice,
    'combos': cmd_combos,
    'coppie': cmd_coppie,
    'slugs': cmd_slugs,
    'costi': cmd_costi,
    'aggrega_costi': cmd_aggrega_costi,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDI:
        print(__doc__)
        return 2
    return COMANDI[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
