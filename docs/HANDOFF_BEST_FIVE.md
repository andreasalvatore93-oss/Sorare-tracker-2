# HANDOFF — Funzione "Best Five"

Riscritto il 30/07/2026 sera (sessione "Best Five K League", seconda parte). La versione precedente
di questo file descriveva un'architettura ormai sostituita (top-N per ruolo, un job sequenziale) —
riscritto da zero per non essere fuorviante. Leggerlo per intero prima di agire.

## Cos'è "Best Five"

Per UNA lega scelta, genera la **formazione IN SEASON ottimale** (GK/DEF/MID/FWD/EXTRA, con
sinergie/anti-stack/captain) scegliendo tra **TUTTE** le carte della lega, non solo quelle
possedute dall'utente. Script separato e READ-ONLY rispetto alla pipeline di produzione
(`formazione_giornata.yml`).

**Non è più** un elenco "titolare + N backup per ruolo" calcolato con una logica propria — quello
era il design della prima sessione (30/07 pomeriggio) ed è stato **sostituito**, su richiesta
esplicita dell'utente, con la generazione di 1+N formazioni COMPLETE reali (vedi sotto).

## Architettura attuale (5 job paralleli, `.github/workflows/best_five.yml`)

1. **pool_shard**: legge il pool già filtrato per qualità (discovery_global), lo sharda in ≤20
   gruppi. Nessuna query di rete.
2. **prefiltro** (matrice, max-parallel 20): controlla le starterOdds (soglia configurabile, input
   `starter_odds`) SOLO sul proprio shard.
3. **prefiltro_merge**: unisce i sopravvissuti, li risharda in ≤20 gruppi per il predict.
4. **predict** (matrice, max-parallel 20): un subprocess `TARGET_SLUG` per giocatore, per ogni
   shard. Riusa `pipeline_artifacts.py` (stage/apply) per passare i file tra job via artifact.
5. **report**: applica gli artifact, delega il ranking a `build_consiglio_<ruolo>.py` (lo stesso
   script della produzione, zero logica duplicata), poi costruisce la **formazione vera**, salva
   su main, notifica Telegram.

Tempo misurato sull'ultimo run completo riuscito (K League, tutti e 4 i ruoli): circa 7 minuti,
vicino ai ~5 minuti della pipeline di produzione.

**Nota**: questa architettura a 5 job è passata per diversi bug reali durante lo sviluppo (redirect
stdout che corrompeva GITHUB_OUTPUT, job senza `pip install requests curl_cffi`, precedenza sbagliata
tra formato vecchio/nuovo dei risultati) — tutti fixati e committati. Se un run fallisce, controllare
per primo se un job nuovo/modificato ha dimenticato lo step `pip install`.

## Come genera la formazione vera (il cambio più grande di questa sessione)

`costruisci_formazione_vera()` in `best_five.py` **non duplica nessuna logica di sinergia/anti-
stack/captain**: importa dinamicamente `formazione_mls/build_formazione_finale.py` (stesso schema
di `generatore_formazioni/build_formazione_globale.py`) e chiama DAVVERO `CardPool`,
`generate_lineups_for_type('IN_SEASON', 1+n_backup, ...)`, `render_report_html`.

La differenza col tool unificato è **solo nella CardPool**: invece delle copie realmente possedute,
si passa `CardPool({}, names=...)` — la classe stessa ripiega già su 1 copia IN_SEASON virtuale per
ogni slug non presente nei counts, quindi ogni giocatore del pool globale risulta "posseduto" con 1
copia, zero codice ad-hoc per simularlo. Stesso motivo per cui il bonus XP è naturalmente a zero
(nessun `power` breakdown noto), coerente con la richiesta dell'utente di vedere lo score grezzo.

Conseguenza pratica: dato che ogni giocatore ha solo 1 copia virtuale, generare `count > 1`
formazioni produce automaticamente formazioni ALTERNATIVE con giocatori diversi (non può riusare
chi è già stato schierato) — questo ha sostituito il vecchio concetto di "backup per ruolo": ora
sono "formazioni di backup" complete.

**Testato**: solo offline/in locale contro dati K League reali già su disco (mai un run GitHub
Actions completo con QUESTA architettura confermato riuscito al momento della scrittura — l'ultimo
run lanciato in questa sessione è ancora in corso). Verificare lo stato prima di fidarsi ciecamente.

## Altre feature aggiunte in questa sessione

- **Report HTML**: layout a riga (stesso `render_report_html`/CSS della produzione, quindi
  automaticamente coerente — niente più template custom di Best Five).
- **Notifica Telegram**: stesso canale `BUNDLE_TELEGRAM_TOKEN`/`BUNDLE_TELEGRAM_CHAT_ID` (bundle/
  formazioni/bot_profit), NON il canale del tracker prezzi. Link via raw.githack.com, come
  `generatore_formazioni/formazione_telegram_notify.py`.
- **Carte cliccabili**: ogni pcard del report apre `https://sorare.com/it/football/players/<slug>`
  al click (script iniettato in post-processing, non tocca `build_formazione_finale.py` condiviso).

## Cosa NON è ancora attivo (rimandato dall'utente, "ci penseremo dopo")

Due funzioni sono **scritte e pushate ma inerti** perché i file di cui hanno bisogno non esistono:

- **Cap qualità prima delle starterOdds** (`BEST_FIVE_TOP_K_QUALITA`, default 40, input workflow
  `top_k_qualita`): legge `player_quality.json` in ogni `*_discovery_global/`. Non esiste ancora.
- **Nomi reali (displayName) sulle carte** invece dello slug: legge `player_names.json` in ogni
  `*_discovery_global/`. Non esiste ancora. **Attenzione**: il tool unificato ha `player_names.json`
  ma in una cartella DIVERSA (`*_discovery/`, non `*_discovery_global/`) e con copertura limitata
  alle sole carte possedute (fonte: CARDS_QUERY) — inutile per il pool globale di Best Five, che ha
  bisogno di nomi per giocatori mai posseduti. Serve una fonte diversa (TeamRoster, già cablata nel
  codice di discovery_global, il campo `displayName` era già nella risposta e veniva scartato).

**Per attivare entrambe**: rilanciare `formazione_<lega>/discovery/<lega>_<ruolo>_discovery_global.py`
per tutti e 4 i ruoli, per ciascuna lega supportata (kleague/mls/germania) — richiede query API,
quindi va fatto su GitHub Actions con permesso esplicito dell'utente, non in locale (manca il
cookie) e non di propria iniziativa. Nel frattempo entrambe le funzioni degradano in sicurezza
(nessun cap, nomi = slug title-case) — nessun crash, nessuna esclusione silenziosa.

## Leghe supportate

`LEGHE_SUPPORTATE = ('mls', 'kleague', 'germania')` in `best_five.py` — richiede discovery globale
completa per tutti e 4 i ruoli. Testato quasi esclusivamente su K League finora; MLS ha avuto un
run fallito per timeout del vecchio prefiltro sequenziale (causa risolta con la parallelizzazione),
non ancora riconfermato con un run completo pulito.

## Prossimo passo consigliato

1. Verificare l'esito dell'ultimo run lanciato (K League, tutti i ruoli, `starter_odds=0.80`) —
   se riuscito, è la prima conferma end-to-end della nuova architettura a formazione vera.
2. Se confermato, ripetere su MLS per validare anche lì.
3. Quando richiesto dall'utente: rilanciare le 12 discovery_global (3 leghe × 4 ruoli) per attivare
   cap qualità + nomi reali.
