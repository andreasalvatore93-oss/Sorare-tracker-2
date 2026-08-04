"""backtest_arene_cache — indice delle cache locali per il backtest delle arene.

Il backtest modello-contro-utente (sezione 48.E del riassunto) deve rigiocare
le formazioni arena dell'utente *come se fosse quella giornata*: serve quindi
lo storico di ogni giocatore TRONCATO alla data della giornata, e i dettagli
granulari di quelle partite.

Entrambi i dati sono gia' sul disco, sparsi nelle cartelle di output delle 27
leghe:

  <lega>/output/<pool>/.game_log_cache/<slug>_gamelog.json   (partite + contesto)
  <lega>/output/<pool>/.cache/<slug>_detail_cache.json       (dettaglio granulare)

Lo stesso giocatore puo' comparire in piu' pool (per lega, per ruolo, per
calibrazione) con cache di profondita' diversa: qui si UNISCONO tutte le copie
per slug, tenendo la voce piu' ricca. Nessuna chiamata di rete.
"""
import os
import glob
import json
import io

_ROOT = os.path.dirname(os.path.abspath(__file__))

_GAMELOG_GLOB = [
    os.path.join(_ROOT, '*', 'output', '*', '.game_log_cache', '*_gamelog.json'),
    # cartella dedicata al backtest, riempita da scarica_cache_backtest.py per
    # i giocatori che la produzione non ha mai analizzato
    os.path.join(_ROOT, 'dati_globali', 'backtest_arene_cache', '.game_log_cache', '*_gamelog.json'),
]
_DETAIL_GLOB = [
    os.path.join(_ROOT, '*', 'output', '*', '.cache', '*_detail_cache.json'),
    os.path.join(_ROOT, 'dati_globali', 'backtest_arene_cache', '.cache', '*_detail_cache.json'),
]


def _leggi_json(path):
    try:
        with io.open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def _indice(glob_patterns, suffisso):
    """slug -> lista di file, dal piu' grande al piu' piccolo."""
    per_slug = {}
    for pattern in glob_patterns:
        for path in sorted(glob.glob(pattern)):
            slug = os.path.basename(path)[:-len(suffisso)]
            per_slug.setdefault(slug, []).append(path)
    for slug in per_slug:
        # a parita' di dimensione l'ordine decideva quale copia della cache
        # vince nel merge: si spareggia sul percorso, che e' stabile ovunque
        per_slug[slug].sort(key=lambda p: (-os.path.getsize(p), p))
    return per_slug


class CacheLocale(object):
    def __init__(self):
        self._file_gamelog = _indice(_GAMELOG_GLOB, '_gamelog.json')
        self._file_detail = _indice(_DETAIL_GLOB, '_detail_cache.json')
        self._gamelog = {}
        self._detail = {}

    def slug_disponibili(self):
        return set(self._file_gamelog) & set(self._file_detail)

    def gamelog(self, slug):
        """Tutte le partite note del giocatore, unite fra le copie di cache.

        Ritorna una lista di nodi so5Score ordinati dal piu' VECCHIO al piu'
        recente (l'ordine su cui lavora build_prediction dopo il reversed())."""
        if slug in self._gamelog:
            return self._gamelog[slug]
        unite = {}
        for path in self._file_gamelog.get(slug, []):
            dati = _leggi_json(path) or {}
            for chiave, nodo in dati.items():
                vecchio = unite.get(chiave)
                # a parita' di partita tiene la voce con lo status piu' definitivo
                if vecchio is None or (vecchio.get('scoreStatus') != 'FINAL'
                                       and nodo.get('scoreStatus') == 'FINAL'):
                    unite[chiave] = nodo
        nodi = [n for n in unite.values() if (n.get('anyGame') or {}).get('date')]
        nodi.sort(key=lambda n: n['anyGame']['date'])
        self._gamelog[slug] = nodi
        return nodi

    def dettagli(self, slug):
        """score_id (senza prefisso) -> dettaglio granulare."""
        if slug in self._detail:
            return self._detail[slug]
        unite = {}
        for path in self._file_detail.get(slug, []):
            dati = _leggi_json(path) or {}
            for chiave, valore in dati.items():
                if isinstance(valore, dict) and chiave not in unite:
                    unite[chiave] = valore
        self._detail[slug] = unite
        return unite

    def dettaglio_partita(self, slug, score_id):
        d = self.dettagli(slug)
        return d.get(score_id) or d.get('So5Score:' + score_id)
