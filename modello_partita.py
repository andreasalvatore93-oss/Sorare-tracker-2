"""modello_partita — i gol attesi delle due squadre, prima dei giocatori.

PERCHE'. Oggi ogni previsione parte dal giocatore: si pesa il suo storico e si
corregge un po' per l'avversario. La partita, che e' l'evento che genera i
punti, non entra mai. Un attaccante che affronta la peggior difesa del
campionato in casa e uno che va a giocare contro la capolista ricevono la
stessa previsione a meno di un moltiplicatore su lambda_pos costruito sulla
media dei gol subiti dall'avversario -- una media semplice, che non separa
"ha subito tanti gol" da "ha affrontato attacchi forti".

Qui si costruisce lo strato mancante: per ogni partita, i gol attesi delle DUE
squadre, da un modello di Poisson con attacco, difesa e fattore campo:

    log lambda(A contro D, in casa) = mu + att[A] - dif[D] + casa * h

I parametri si stimano solo sul PASSATO rispetto alla partita da prevedere
(walk-forward), quindi il numero e' utilizzabile in produzione il venerdi'
per la giornata di domenica.

IL DATO. I gol di ogni squadra in ogni partita sono gia' in cache: stanno
nella riga 'goals_conceded' del detailedScore, la stessa che usa
opponent_strength. Nessuna chiamata di rete.

ATTENZIONE, e' il punto che fa sbagliare il conto: 'goals_conceded' NON e' un
dato di squadra, e' un dato di GIOCATORE -- i gol subiti mentre lui era in
campo. Un subentrato al 70' di una partita persa 3-0 ha goals_conceded=1.
Verificato sulle cache reali (7.154 squadra-partita): fra i compagni che hanno
giocato almeno 90 minuti il valore coincide nel 99,6% dei casi, e il MASSIMO
fra tutti i compagni coincide con quel valore in 6.363 casi su 6.364 (l'unico
scostamento e' una partita andata ai supplementari, dove il massimo e' il
valore giusto). Quindi la regola e': gol subiti dalla squadra = MASSIMO fra i
compagni di cui abbiamo il dettaglio.
"""
import os
import io
import glob
import json
import math
import datetime
import collections

_ROOT = os.path.dirname(os.path.abspath(__file__))

_DETAIL_GLOB = [
    os.path.join(_ROOT, 'formazione_*', 'output', '*_all', '.cache', '*_detail_cache.json'),
    os.path.join(_ROOT, 'dati_globali', 'backtest_arene_cache', '.cache', '*_detail_cache.json'),
]

CACHE_DATASET = os.path.join(_ROOT, 'dati_globali', 'partite_gol.json')


def _stat(dettaglio, nome):
    for riga in dettaglio:
        if riga.get('stat') == nome:
            return riga.get('statValue', 0.0) or 0.0
    return None


def _dt(iso):
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _squadra_del_file(giochi):
    """La squadra del giocatore: quella che compare in piu' partite sue."""
    conta = collections.defaultdict(int)
    for g in giochi:
        for lato in ('homeTeam', 'awayTeam'):
            s = (g.get(lato) or {}).get('slug')
            if s:
                conta[s] += 1
    return max(conta, key=conta.get) if conta else None


def costruisci_partite():
    """Ritorna la lista delle partite ricostruite dalle cache su disco.

    Ogni voce: {'id', 'data', 'casa', 'fuori', 'competizione',
                'subiti_casa', 'subiti_fuori', 'min_casa', 'min_fuori'}
    dove 'subiti_X' e' il massimo fra i compagni di X (None se di quel lato
    non abbiamo nessun giocatore) e 'min_X' i minuti massimi visti, che dicono
    quanto fidarsi del massimo."""
    per_lato = {}   # (id_partita, squadra) -> [max_subiti, max_minuti]
    contesto = {}   # id_partita -> anagrafica
    for pattern in _DETAIL_GLOB:
        for path in glob.glob(pattern):
            try:
                with io.open(path, encoding='utf-8') as fh:
                    cache = json.load(fh)
            except Exception:
                continue
            voci = [e for e in (cache or {}).values()
                    if isinstance(e, dict) and e.get('anyGame') and e.get('detailedScore')]
            if not voci:
                continue
            squadra = _squadra_del_file([e['anyGame'] for e in voci])
            if not squadra:
                continue
            for e in voci:
                g = e['anyGame']
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                data = _dt(g.get('date'))
                if not casa or not fuori or data is None or squadra not in (casa, fuori):
                    continue
                subiti = _stat(e['detailedScore'], 'goals_conceded')
                if subiti is None:
                    continue
                minuti = _stat(e['detailedScore'], 'mins_played') or 0.0
                gid = g.get('id') or '%s|%s|%s' % (casa, fuori, g.get('date'))
                contesto[gid] = (data, casa, fuori, (g.get('competition') or {}).get('slug'))
                chiave = (gid, squadra)
                vecchio = per_lato.get(chiave)
                if vecchio is None:
                    per_lato[chiave] = [subiti, minuti]
                else:
                    vecchio[0] = max(vecchio[0], subiti)
                    vecchio[1] = max(vecchio[1], minuti)

    partite = []
    for gid, (data, casa, fuori, comp) in contesto.items():
        lc, lf = per_lato.get((gid, casa)), per_lato.get((gid, fuori))
        partite.append({
            'id': gid, 'data': data, 'casa': casa, 'fuori': fuori, 'competizione': comp,
            'subiti_casa': lc[0] if lc else None, 'min_casa': lc[1] if lc else None,
            'subiti_fuori': lf[0] if lf else None, 'min_fuori': lf[1] if lf else None,
        })
    partite.sort(key=lambda p: p['data'])
    return partite


def osservazioni(partite):
    """Le partite viste come coppie (attacco, difesa) -> gol segnati.

    Una partita di cui conosciamo un solo lato produce comunque una
    osservazione utile: se sappiamo quanto ha subito la squadra di casa,
    sappiamo quanto ha segnato quella in trasferta. Sono ~7.100 osservazioni
    contro le ~2.100 partite complete, e per stimare attacco e difesa servono
    proprio queste."""
    fuori = []
    for p in partite:
        # subiti dalla squadra di casa == segnati dalla squadra in trasferta
        if p['subiti_casa'] is not None:
            fuori.append({'data': p['data'], 'attacco': p['fuori'], 'difesa': p['casa'],
                          'casa_attacca': False, 'gol': p['subiti_casa'],
                          'competizione': p['competizione'], 'id': p['id'],
                          'minuti': p['min_casa']})
        if p['subiti_fuori'] is not None:
            fuori.append({'data': p['data'], 'attacco': p['casa'], 'difesa': p['fuori'],
                          'casa_attacca': True, 'gol': p['subiti_fuori'],
                          'competizione': p['competizione'], 'id': p['id'],
                          'minuti': p['min_fuori']})
    fuori.sort(key=lambda o: o['data'])
    return fuori


# --------------------------------------------------------------------------
# Stima di attacco/difesa
# --------------------------------------------------------------------------

# Quanto tirare attacco e difesa verso lo zero (= verso la squadra media).
# Con ~12 partite per squadra in cache, senza regolarizzazione una squadra con
# tre partite fortunate diventerebbe la migliore del mondo.
REGOLARIZZAZIONE = 0.08
# Emivita in giorni del peso di una partita passata: una di sei mesi fa pesa
# meta' di una di oggi. Le rose cambiano, la forza no.
EMIVITA_GIORNI = 180.0
MIN_PARTITE_SQUADRA = 3
ITERAZIONI = 60


class ForzaSquadre(object):
    """Attacco, difesa e fattore campo stimati su un insieme di osservazioni.

    Poisson con log-legame, stimato per discesa: e' una regressione con una
    riga per squadra-attacco e una per squadra-difesa, e la forma chiusa dei
    minimi quadrati non vale (i gol non sono gaussiani e il legame e' log).
    Sessanta passi di Newton coordinato bastano: si veda `convergenza`."""

    def __init__(self, mu=0.0, casa=0.0, attacco=None, difesa=None, conteggio=None):
        self.mu = mu
        self.casa = casa
        self.attacco = attacco or {}
        self.difesa = difesa or {}
        self.conteggio = conteggio or {}

    def lambda_atteso(self, squadra_att, squadra_dif, in_casa):
        """Gol attesi di `squadra_att` contro `squadra_dif`.

        Una squadra mai vista vale 0 nel suo termine, cioe' "squadra media":
        e' il ripiego sicuro, la previsione resta quella del campo medio."""
        a = self.attacco.get(squadra_att, 0.0)
        d = self.difesa.get(squadra_dif, 0.0)
        return math.exp(self.mu + a + d + (self.casa if in_casa else 0.0))

    def conosciuta(self, squadra):
        return self.conteggio.get(squadra, 0) >= MIN_PARTITE_SQUADRA


def _peso_tempo(quando, riferimento):
    giorni = (riferimento - quando).total_seconds() / 86400.0
    if giorni < 0:
        giorni = 0.0
    return 0.5 ** (giorni / EMIVITA_GIORNI)


def stima(osserv, riferimento=None, regolarizzazione=REGOLARIZZAZIONE,
          emivita=EMIVITA_GIORNI, iterazioni=ITERAZIONI):
    """Stima attacco/difesa/campo su `osserv` (tutte gia' filtrate al passato).

    `riferimento` e' la data rispetto a cui si pesa il tempo (di norma la data
    della partita da prevedere)."""
    if not osserv:
        return ForzaSquadre()
    if riferimento is None:
        riferimento = max(o['data'] for o in osserv)

    righe = []
    conteggio = collections.Counter()
    for o in osserv:
        p = 0.5 ** (max(0.0, (riferimento - o['data']).total_seconds() / 86400.0) / emivita)
        if p < 1e-4:
            continue
        righe.append((o['attacco'], o['difesa'], 1.0 if o['casa_attacca'] else 0.0,
                      float(o['gol']), p))
        conteggio[o['attacco']] += 1
        conteggio[o['difesa']] += 1
    if not righe:
        return ForzaSquadre()

    peso_tot = sum(r[4] for r in righe)
    gol_tot = sum(r[3] * r[4] for r in righe)
    mu = math.log(max(gol_tot / peso_tot, 1e-3))
    casa = 0.0
    attacco = collections.defaultdict(float)
    difesa = collections.defaultdict(float)

    # indici, per non riscorrere tutto ad ogni passo
    per_att = collections.defaultdict(list)
    per_dif = collections.defaultdict(list)
    for i, (a, d, h, y, p) in enumerate(righe):
        per_att[a].append(i)
        per_dif[d].append(i)

    def _lam(i):
        a, d, h, _y, _p = righe[i]
        return math.exp(mu + attacco[a] + difesa[d] + casa * h)

    for _passo in range(iterazioni):
        # attacco, un passo di Newton per squadra (con penalita' ridge)
        for squadra, idx in per_att.items():
            g = h = 0.0
            for i in idx:
                lam = _lam(i)
                p, y = righe[i][4], righe[i][3]
                g += p * (y - lam)
                h += p * lam
            g -= regolarizzazione * attacco[squadra] * len(idx)
            h += regolarizzazione * len(idx)
            if h > 0:
                attacco[squadra] += g / h
        # difesa (segno gia' dentro il parametro: negativo = difesa forte)
        for squadra, idx in per_dif.items():
            g = h = 0.0
            for i in idx:
                lam = _lam(i)
                p, y = righe[i][4], righe[i][3]
                g += p * (y - lam)
                h += p * lam
            g -= regolarizzazione * difesa[squadra] * len(idx)
            h += regolarizzazione * len(idx)
            if h > 0:
                difesa[squadra] += g / h
        # fattore campo
        g = h = 0.0
        for i, (_a, _d, hh, y, p) in enumerate(righe):
            if hh:
                lam = _lam(i)
                g += p * (y - lam)
                h += p * lam
        if h > 0:
            casa += g / h
        # media generale (assorbe la deriva di attacco/difesa)
        g = h = 0.0
        for i in range(len(righe)):
            lam = _lam(i)
            g += righe[i][4] * (righe[i][3] - lam)
            h += righe[i][4] * lam
        if h > 0:
            mu += g / h

    return ForzaSquadre(mu=mu, casa=casa, attacco=dict(attacco), difesa=dict(difesa),
                        conteggio=dict(conteggio))


def salva_dataset(partite, path=CACHE_DATASET):
    dati = [dict(p, data=p['data'].isoformat()) for p in partite]
    with io.open(path, 'w', encoding='utf-8') as fh:
        json.dump(dati, fh, ensure_ascii=False)
    return path


def carica_dataset(path=CACHE_DATASET):
    with io.open(path, encoding='utf-8') as fh:
        dati = json.load(fh)
    for p in dati:
        p['data'] = datetime.datetime.fromisoformat(p['data'])
    dati.sort(key=lambda p: p['data'])
    return dati


def partite_da_cache(ricostruisci=False, path=CACHE_DATASET):
    if not ricostruisci and os.path.isfile(path):
        return carica_dataset(path)
    partite = costruisci_partite()
    salva_dataset(partite, path)
    return partite


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    partite = costruisci_partite()
    salva_dataset(partite)
    oss = osservazioni(partite)
    complete = sum(1 for p in partite
                   if p['subiti_casa'] is not None and p['subiti_fuori'] is not None)
    squadre = collections.Counter()
    for o in oss:
        squadre[o['attacco']] += 1
    print('partite ricostruite : %d  (complete su entrambi i lati: %d)' % (len(partite), complete))
    print('osservazioni att/dif: %d' % len(oss))
    print('squadre             : %d  (mediana %d partite a testa)' %
          (len(squadre), sorted(squadre.values())[len(squadre) // 2]))
    print('periodo             : %s -> %s' % (partite[0]['data'].date(), partite[-1]['data'].date()))
    print('gol medi a partita  : %.3f' % (sum(o['gol'] for o in oss) / len(oss)))
    print('salvato in %s' % CACHE_DATASET)
