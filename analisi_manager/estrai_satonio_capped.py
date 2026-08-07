"""estrai_satonio_capped -- estrazione AD-HOC per manager con volume enorme.

Perche' esiste
--------------
satonio gioca 200+ arene a giornata. `ricostruisci_manager.py` scarica UNA
formazione per ogni partecipazione, quindi su questo manager esploderebbe in
query. L'utente ha scelto di NON toccare lo script principale (lo usano tutti
gli altri manager): questo file e' isolato e RIUSA le sue funzioni, non le
duplica.

Cosa fa di diverso, e SOLO questo:
  1. taglia le arene da scaricare a --cap-arene per giornata, scegliendo QUALI
     tenere PRIMA di spendere query (vedi scegli_arene);
  2. non scarica affatto le arene tagliate;
  3. scarica TUTTE le righe non-arena (servono al pool completo, regola D2).
Tutto il resto -- formato del file, disciplina D1 (retry, falliti definitivi,
mai righe mute), whitelist TIPI_ARENA_ESCLUSI -- e' quello di
ricostruisci_manager, importato.

ATTENZIONE, LEGGERE PRIMA DI LANCIARE (vedi PARERE_OPUS_SCRIPT_SATONIO):
con --cap-arene 30 le carte-arena scaricate sono esattamente 30*5 = 150 e gli
slot da riempire sono 150. Una carta si usa una volta sola per giornata (D7),
quindi il pool-arena e' uguale agli slot PER COSTRUZIONE: nessuna scorta,
nessuna selezione da misurare (stesso caso di fins49). L'unica scorta possibile
viene dalle righe NON-arena. Per questo lo script STAMPA pool vs slot per ogni
giornata e si ferma con --stop-se-pool-uguale-slot se non c'e' surplus.
Girare PRIMA una sola giornata (--max-giornate 1) e guardare quel numero.

Uso
---
    set SORARE_COOKIE=...        (deve essere nell'ambiente PRIMA dell'import)
    python analisi_manager/estrai_satonio_capped.py satonio \
        --giornate <10 slug separati da virgola> --cap-arene 30 --max-giornate 1
"""
import os
import sys
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ricostruisci_manager as RM   # noqa: E402  (COOKIE viene letto all'import)

# Le sole competizioni arena che il backtest guarda davvero
# (p13_backtest_gw_crowss.COMPETIZIONI_ARENA_AMMESSE). Beginner e arene
# dedicate a campionato vengono ESCLUSE a valle da p13/p11: scaricarle
# sarebbe spendere query per righe che nessun test leggera' mai.
COMPETIZIONI_AMMESSE = ('Cap 260', 'Cap 220', 'Uncapped')


def competizione_ammessa(riga):
    """True se l'arena e' di un tipo che i backtest valutano davvero."""
    nome = (riga.get('competizione') or '').strip()
    return any(nome.startswith(c) for c in COMPETIZIONI_AMMESSE)


def scegli_arene(righe, cap):
    """Quali arene tenere, decise SULL'INDICE (costo zero in query).

    Criterio, in quest'ordine:
      1. si tengono solo le competizioni che i backtest valutano (Cap 260,
         Cap 220, Uncapped). Beginner e arene dedicate a campionato sono
         scartate a valle da p13: pagarle sarebbe spreco puro.
      2. round-robin fra i tre tipi, non "le prime che capitano": i tre tipi
         hanno soglie di pareggio e guadagno/punto DIVERSI, quindi un campione
         sbilanciato su uno solo misura una soglia sola.
      3. dentro ogni tipo, ordine per slug del contender: deterministico e
         riproducibile. L'ordine del cursore GraphQL non lo e'.

    Torna (tenute, scartate_per_competizione, conteggio_per_tipo).
    """
    ammesse = [r for r in righe if competizione_ammessa(r)]
    scartate = len(righe) - len(ammesse)
    per_tipo = collections.OrderedDict()
    for c in COMPETIZIONI_AMMESSE:
        gruppo = sorted([r for r in ammesse
                         if (r.get('competizione') or '').strip().startswith(c)],
                        key=lambda r: r.get('contender') or '')
        if gruppo:
            per_tipo[c] = gruppo
    tenute = []
    while len(tenute) < cap and any(per_tipo.values()):
        for c in list(per_tipo):
            if not per_tipo[c]:
                continue
            tenute.append(per_tipo[c].pop(0))
            if len(tenute) >= cap:
                break
    return tenute, scartate, collections.Counter(
        (r.get('competizione') or '?').strip() for r in tenute)


def main():
    ap = argparse.ArgumentParser(description="Estrazione con cap arene, per manager enormi.")
    ap.add_argument('manager')
    ap.add_argument('--giornate', required=True, help="slug separati da virgola")
    ap.add_argument('--cap-arene', type=int, default=30)
    ap.add_argument('--max-giornate', type=int, default=None,
                    help="ferma dopo N giornate NUOVE (usare 1 per la prova)")
    ap.add_argument('--stop-se-pool-uguale-slot', action='store_true',
                    help="ferma la run se una giornata non ha carte di scorta")
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    if not RM.COOKIE:
        RM.log("SORARE_COOKIE assente: l'indice tornerebbe vuoto senza errore. Mi fermo.")
        return 1

    dest = args.json or os.path.join(RM.REPO_ROOT, 'dati_globali',
                                     f'manager_{args.manager}.json')
    dati = RM.carica(dest)
    dati['manager'] = args.manager

    giornate = [x.strip() for x in args.giornate.split(',') if x.strip()]
    if args.max_giornate:
        gia_fatte = dati.get('giornate') or {}
        nuove = [g for g in giornate if g not in gia_fatte]
        giornate = [g for g in giornate if g in gia_fatte] + nuove[:args.max_giornate]

    q_indice = q_form = 0
    for i, giornata in enumerate(giornate, 1):
        completate = (dati.get('giornate') or {}).get(giornata)
        retry_rows = (dati.get('retry') or {}).get(giornata)
        if completate is not None and not retry_rows:
            RM.log(f"[{i}/{len(giornate)}] {giornata}: gia' fatta, salto.")
            continue

        if retry_rows:
            da_scaricare = retry_rows
            RM.log(f"[{i}/{len(giornate)}] {giornata}: riprovo {len(da_scaricare)} falliti")
        else:
            righe, ok = RM.partecipazioni(args.manager, giornata)
            q_indice += 1
            if not ok:
                RM.log(f"[{i}/{len(giornate)}] {giornata}: indice incompleto, NON salvo.")
                continue
            righe = [r for r in righe if r.get('tipo_arena') not in RM.TIPI_ARENA_ESCLUSI]
            arene = [r for r in righe if r.get('tipo_arena')]
            non_arena = [r for r in righe if not r.get('tipo_arena')]
            tenute, scartate_comp, per_tipo = scegli_arene(arene, args.cap_arene)
            RM.log(f"[{i}/{len(giornate)}] {giornata}: {len(righe)} partecipazioni "
                   f"({len(arene)} arene, {len(non_arena)} non-arena). "
                   f"Arene ammesse tenute: {len(tenute)}/{len(arene)} "
                   f"(escluse per competizione: {scartate_comp}); mix {dict(per_tipo)}")
            da_scaricare = tenute + non_arena

        nuovi_completati, nuovi_pendenti, falliti_def = [], [], []
        for r in da_scaricare:
            carte, chi, piazzamento = RM.formazione(r['contender'])
            q_form += 1
            if carte is None:
                tentativi = r.get('_tentativi', 0) + 1
                if tentativi >= RM.MAX_TENTATIVI_CONTENDER:
                    RM.log(f"  FALLITO DEFINITIVO: {r['contender'][:60]}")
                    falliti_def.append(r['contender'])
                else:
                    r['_tentativi'] = tentativi
                    nuovi_pendenti.append(r)
                continue
            if chi and chi != args.manager:
                RM.log(f"  ATTENZIONE: {r['contender'][:50]} e' di {chi}, scartata.")
                falliti_def.append(r['contender'])
                continue
            r.pop('_tentativi', None)
            r['carte'] = carte
            r['piazzamento'] = piazzamento
            nuovi_completati.append(r)

        dati.setdefault('giornate', {})[giornata] = (completate or []) + nuovi_completati
        if nuovi_pendenti:
            dati.setdefault('retry', {})[giornata] = nuovi_pendenti
        elif giornata in (dati.get('retry') or {}):
            del dati['retry'][giornata]
        if falliti_def:
            lista = dati.setdefault('falliti_definitivi', {}).setdefault(giornata, [])
            for cs in falliti_def:
                if cs not in lista:
                    lista.append(cs)

        # CONTROLLO OBBLIGATORIO (CLAUDE.md): pool contro slot. Se il pool non
        # supera gli slot non c'e' selezione da misurare e il test e' nullo per
        # costruzione: meglio saperlo alla prima giornata che dopo dieci.
        righe_gw = dati['giornate'][giornata]
        mute = sum(1 for r in righe_gw if not r.get('carte'))
        carte_pool = {c.get('carta') for r in righe_gw for c in (r.get('carte') or [])}
        slot = sum(len(r.get('carte') or []) for r in righe_gw if r.get('tipo_arena'))
        RM.log(f"  CONTROLLO {giornata}: righe={len(righe_gw)} mute={mute} "
               f"pool={len(carte_pool)} slot={slot} "
               f"pool>slot={'SI' if len(carte_pool) > slot else 'NO -- nessuna scorta'} "
               f"retry={len(nuovi_pendenti)} falliti={len(falliti_def)}")
        RM.salva(dati, dest)
        if args.stop_se_pool_uguale_slot and len(carte_pool) <= slot:
            RM.log("  STOP: nessuna carta di scorta, la selezione non e' misurabile. "
                   "Alzare --cap-arene o accettare il solo Test3.")
            break

    RM.log(f"Scritto {dest} -- query: indice={q_indice} formazioni={q_form} "
           f"totale={q_indice + q_form}")
    RM.riepilogo(dati)
    return 0


if __name__ == '__main__':
    sys.exit(main())
