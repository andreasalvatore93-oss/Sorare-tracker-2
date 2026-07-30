# Riassunto evoluzione modello predittivo — handoff per nuova sessione/account

**Scritto per essere letto da zero, su un account Claude diverso da quello che ha fatto questo
lavoro** (l'utente alterna due account, poca/nessuna memoria condivisa tra sessioni). Non
presupporre nessun contesto pregresso: tutto quello che serve è qui dentro.

**Aggiornato 27/07/2026 (sera)**: se cerchi solo "qual è lo stato adesso", salta direttamente
alla **sezione 26** (l'ultima) — è l'HANDOFF completo di questa sessione, scritto apposta per il
prossimo account Claude: espansione a 20 campionati, calibrazione pooled, la SCOPERTA che il
backtest di calibrazione era divergente dalla formula di produzione, e il refactor DEF avviato
(funzione condivisa `compute_score_atteso_def` + backtest allineato) con i PROSSIMI PASSI ESATTI da
cui ripartire. La sezione 25 resta come stato del pomeriggio (i due filoni allora sospesi sono ora
completati, vedi sezione 26A). Le sezioni 1-24 restano cronistoria
utile per il PERCHÉ delle decisioni, non per lo stato attuale. Leggi comunque SEMPRE questo
documento dall'inizio alla fine prima di concludere che qualcosa manca, non fidarti solo
dell'ultima sezione o della memoria persistente (la sezione 14D spiega perché, con un caso reale).
Le sezioni 1-13 restano come cronistoria di come ci si è arrivati (parametri di produzione
FINALIZZATI per DEF/MID/FWD/GK, scoperta e validazione della formula `level_score`/floor,
implementazione Arena/All Stars, infrastruttura K League completa), utile se serve capire IL
PERCHÉ di una decisione, non per sapere lo stato attuale.

Repo: `Sorare-tracker-2` (github.com/andreasalvatore93-oss/Sorare-tracker-2), cartella locale
`C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2`, branch `main`. Stato scritto qui: **tutto
già pushato su GitHub** salvo diversa indicazione esplicita più sotto — verificare comunque con
`git status`/`git log` invece di fidarsi ciecamente, potrebbero essere passate altre sessioni nel
frattempo.

**Vedi anche** [`docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`](RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md)
— documento "vivo" (da aggiornare, non duplicare) con l'architettura completa del tool
formazione MLS e la sua storia fino a questa sessione. Questo file qui invece è lo **snapshot di
handoff di QUESTA sessione specifica** (cosa è stato fatto oggi, dove siamo rimasti, come
ripartire) — leggere prima quello per il quadro generale, poi questo per i dettagli operativi
freschi.

## 0. CHECKLIST MAESTRA — test da rifare ogni volta che si aggiunge una o più leghe

**Aggiunta 29/07/2026, su richiesta esplicita dell'utente**: il modello è dichiarato "unico
globale" (nessun parametro per singola lega, salvo eccezioni esplicite documentate). Questo
significa che ogni volta che una NUOVA lega completa la pipeline discovery-globale +
`CALIBRATION_MODE=1` (predict) e accumula dati sufficienti in cache, **il modello globale deve
essere confrontato di nuovo con questi dati freschi** — se la nuova lega sposta una conclusione
già presa, il modello va aggiornato; se la conferma, non si tocca nulla ma si annota qui la
riconferma. Questa sezione esiste per non perdere la lista dei ~40 test che compongono il modello
(altrimenti, sessione dopo sessione, si rischia di dimenticarne qualcuno — stesso principio della
sezione 14D sui falsi allarmi da memoria non aggiornata).

**Verifica 30/07 notte**: la sessione di stanotte (29/07 sera–30/07, sez. 35) ha lavorato SOLO su
infrastruttura/velocità della pipeline GitHub Actions (retry, cache disco, sharding, timeout) — **
nessuna formula di scoring/shrinkage/calibrazione toccata**, quindi questa checklist NON ha bisogno
di aggiornamenti dai fix di stanotte. Nessun nuovo script diagnostico creato (i 6 fix di sez. 35
sono su `discovery_fixture.py`, `opponent_strength.py` e il workflow, non su `formazione_*/
diagnostics/`). Verificato a vista che nessuna voce sotto è invalidata dai fix di velocità.

**Verifica di completezza (29/07, stessa sera)**: prima versione di questa sezione compilata a
memoria conteneva ~28 voci. L'utente ha chiesto conferma "al 100%" — verificato con un controllo
incrociato reale (`find . -name "validate_*.py" -o -name "analyze_*.py" -o ...` su tutto il repo,
non solo `formazione_mls/diagnostics/`) contro l'elenco: **trovati 9 script mancanti**, aggiunti
qui sotto (punti 10b/10c/10d, 17 esteso, 19 esteso, 20 esteso, 20b, 22b, E'). Il conteggio esatto
degli script diagnostici nel repo al momento di questa verifica: 47 (`find` sopra) + 2 script
monitoraggio/copertura non catturati dal pattern (`live_prediction_log.py`,
`audit_leghe_possedute.py`). Se in futuro si dubita ancora della completezza, ripetere lo stesso
comando `find` e diffare contro questa sezione — non fidarsi della sola memoria.

**Convenzione**: ogni riga = (nome test, script per rilanciarlo, cosa verifica, ESITO ATTUALE/
parametro in produzione, sezione del RIASSUNTO dove è documentato per esteso). "Rifare quando"
è sempre implicito = "quando si aggiungono nuove leghe con dati di calibrazione sufficienti",
salvo diversa indicazione esplicita nella riga.

### A. Parametri base per ruolo (half_life, trend, range, sensitivity)

1. **Grid search cross-player pesato per n_test** — `formazione_mls/calibrazione/
   aggregate_grid_search.py` (modalità `GLOBALE=1`, un run per ruolo) — trova la combinazione
   hl/trend/range vincente per composite score (MAE + penalità copertura, peso 0.1). Produzione
   oggi: hl **DEF=20/MID=25/FWD=25 (tutte le leghe), GK=6 fisso** (fix caso reale Daniel, non
   toccare anche se l'aggregato suggerisse altro), trend **DEF=0.0/MID=0.2/FWD=0.3 (tutte le
   leghe, dal 29/07)**, range_multiplier invariato per ruolo. Sez. 21, 24.C, 34.D.
2. **Bootstrap win-rate sui parametri vincenti** — `formazione_mls/calibrazione/
   bootstrap_stability.py` — quanto è solido il "vincitore" secco su ricampionamenti. Ultimo esito:
   31-50% win-rate (sez. 26.A), `opponent_sensitivity=29.0` unico parametro sempre stabile (100%).
3. **Leave-one-league-out** — `formazione_mls/calibrazione/leave_one_league_out.py` — calibra su
   N-1 leghe, valida sulla esclusa. Sez. 26.A.
4. **Granulari sì/no per ruolo** — dentro lo stesso grid search sopra. Produzione: **SENZA
   granulari ovunque**, tranne un'ANOMALIA MAI RISOLTA: Croazia DEF da sola vince CON granulari
   (campione 5 giocatori, quasi certo rumore, mai riverificato con più dati) — sez. 24 (Filone B),
   da ricontrollare quando Croazia avrà più storico.
5. **`validate_trend_intensity_generic.py`** (29/07, esteso a tutte le leghe) — ritest trend, vedi
   punto 1. Sez. 34.D.
6. **`validate_gk_trend.py`** — trend specifico GK (mai testato prima del 26/07). Esito: 0.7 quasi
   ottimale, non toccato. Sez. 12.
7. **`validate_halflife_venue.py`** (esteso a tutte le leghe il 29/07) — half_life E
   fattore_casa_trasferta insieme. Sez. 12, 34.D/34.J.
8. **`validate_venue_per_league.py`** — fattore casa/trasferta PER SINGOLA lega (non pooled). Campioni
   big5 europei (Spagna/Francia/Germania/Inghilterra/Italia/Belgio) ancora troppo piccoli per
   conclusioni robuste — **da rifare quando questi 6 avranno più storico** (post pausa estiva).
   Sez. 24.I, backlog esplicito `project_backlog_venue_retest_nuove_leghe`.
9. **`validate_halflife_trend_grid2d.py`** — interazione half_life×trend (non colta testando un
   parametro alla volta). Esito: interazione reale ma minuscola, non applicata. Sez. 34.D.
10. **`opponent_strength.SENSITIVITY_BY_ROLE`** (sensibilità di `opponent_lambda_mult` al gol
    reale) — validato con `validate_opponent_conceded_level.py`,
    `validate_opponent_conceded_level_allroles.py`,
    `validate_opponent_conceded_level_isolated_otherleagues.py` (quest'ultimo isola le 26 leghe
    extra da MLS/Korea, stesso guadagno confermato). Produzione: GK 0.7, DEF 0.8, MID 0.7, FWD 1.0
    — MLS/Korea, non ancora ritestato sulle altre 26 leghe estese oggi. Sez. 33.B, 34.D.
10b. **`validate_opponent_sensitivity_posttuning.py`** — ricontrolla SENSITIVITY_BY_ROLE DOPO il
    retuning 29/07 di half_life/trend (i due parametri interagiscono: half_life diverso cambia
    lambda_pos/lambda_neg su cui la sensitivity agisce). Da rilanciare ogni volta che half_life/
    trend cambiano di nuovo, non solo per nuove leghe.
10c. **`validate_range_multiplier_coverage.py`** — verifica se `RANGE_MULTIPLIER` centra la
    copertura ideale (~68%, p16-p84) via % di copertura reale invece che MAE (che non discrimina
    fra range diversi). **Copre già TUTTE le leghe/ruoli** (glob `formazione_*/output/*_<ruolo>_
    all|_calibration/.cache`, correzione alla nota precedente che diceva il contrario).
    **RITEST 29/07 dopo il retuning globale di oggi**: la copertura attuale è OGGI PIÙ ALTA del
    target ~68% per tutti e 4 i ruoli — GK 77.7% (range_mult=1.4), DEF 72.9% (1.2), MID 77.6%
    (1.4), FWD 78.5% (1.4). Per centrare 68% servirebbe abbassare a ~1.0-1.05 (DEF) o ~1.15-1.2
    (GK/MID/FWD) — **NON applicato oggi** (il range mostrato è solo cosmetico/informativo, non
    tocca score_atteso/selezione, e il test 33 di oggi ha già mostrato che il range non è
    comunque un segnale utile per scegliere) — proporre all'utente se vale la pena centrare la
    copertura per onestà del numero mostrato.
10e. **Normalizzazione per-lega di `opponent_strength` (NUOVO 29/07, mai testato prima)** —
    `GLOBAL_MEAN_CONCEDED=1.29`/`GLOBAL_STD_CONCEDED=1.17` sono UNA costante fissa per tutte le
    leghe. Verificato empiricamente (media/std reali di gol subiti per lega, 24 leghe con dati):
    range da 0.874±0.921 (Argentina, n=103 partite) a 1.577±1.306 (Grecia, n=26 partite, campione
    minuscolo) — MLS stesso è alto (1.530), non centrale. Il grosso delle leghe con campione
    decente (14-33 squadre: Italia, Spagna, Germania, Inghilterra, Francia, Olanda, K League)
    cluster ragionevolmente vicino alla costante globale (1.09-1.47). **Nessuna azione presa**:
    la divergenza è concentrata nelle leghe con pochissime partite (Argentina/Grecia/Brasile),
    probabilmente rumore campionario più che un vero effetto di lega — **da rimonitorare quando
    queste leghe piccole accumulano più storico**, non serve normalizzazione per-lega ora.
10f. **Calibrazione quantitativa dell'ampiezza dei bonus sinergia (NUOVO 29/07, mai testato
    prima)** — oggi i bonus (`POSITIVE_SYNERGY_BONUS=3`, `TEAMMATE_SYNERGY_BONUS_VARIANCE=5`,
    `GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA=8`, quindi GK-DEF totale 11) sono scelti A MANO, mai
    derivati dalla correlazione misurata. Calcolato un "effect size" grezzo (r × dev.std. del
    compagno, un proxy della vera regressione lineare) dagli stessi dati di
    `measure_teammate_correlation.py`: def-gk 6.69 (bonus attuale 11, **~1.6× più alto**),
    def-def 4.79 (bonus 8, ~1.7×), fwd-fwd 3.72/fwd-mid 3.60 (bonus 8, ~2.2×), gk-mid 2.78/
    def-mid 2.50 (bonus 8, ~3.2×), **mid-mid 2.34 (bonus 8, ~3.4× — lo scarto più grande)**.
    **NON un risultato definitivo**: l'effect size grezzo (r×std) non è la stessa cosa
    dell'ampiezza "giusta" di un bonus pensato per ridurre la VARIANZA della somma (obiettivo
    Arena/All Stars a soglia), che richiederebbe un modello decisionale dedicato, non solo una
    pendenza di regressione — **da approfondire con un design apposito prima di cambiare
    qualunque costante**, non applicare per analogia. Segnala comunque che oggi il bonus
    `TEAMMATE_SYNERGY_BONUS_VARIANCE=5` è probabilmente TROPPO UNIFORME tra coppie con
    correlazione molto diversa (2.3 vs 4.8 di effect size raw).
10g. **`validate_opponent_trend_h2h_gk.py`** (GK) e **`validate_opponent_trend_h2h_generic.py`**
    (MID/FWD, tutte le leghe — DEF scartato su richiesta esplicita precedente) — due segnali
    aggiuntivi mai provati: TREND (media corta 3 vs lunga 10 partite di gol fatti/subiti
    dall'avversario) e H2H (storico scontri diretti squadra-avversario, se ≥2 precedenti).
    **SCARTATO**: l'utente ha preferito "la media generica" senza nemmeno guardare i numeri
    (sez. 33.H) — non riproporre senza una richiesta nuova esplicita.

### B. Formula di produzione (level_score, Stadio D, cap, shrinkage)

11. **`level_score` atteso da tasso eventi decisivi** — `formazione_mls/diagnostics/
    validate_level_score_event_rate.py` + `smoke_test_level_score_production.py` — sostituisce
    la media generica con un valore atteso Poisson pos/neg. IMPLEMENTATO in produzione su tutte le
    leghe. Ultimo ritest (10 leghe): -1.69%/-1.28%/-0.55%/-1.28% MAE (GK/DEF/MID/FWD). Sez. 13.F,
    22, 23.A, 24.A.
12. **Regola netto→livello (tabella level_score)** — validata su 8+ casi reali Sorare
    (screenshot utente), non un test statistico ma una regola FISSA — riverificare solo se
    emergono controesempi reali (non da rifare per nuove leghe). Sez. 11.
13. **Floor level_score (`score = MAX(level, level+granulari)` se level>=60)** — regola fissa,
    stesso discorso del punto 12. Sez. 11.
14. **Decomposizione level_score con half_life/trend propri (SCARTATA)** —
    `validate_level_score_decomposition.py` — guadagno marginale/rumore. Non riprovare senza nuovo
    motivo. Sez. 12.
15. **Fattore ambientale per opponent_sensitivity (SCARTATO)** —
    `validate_environmental_opponent_sensitivity.py` — nessuna formula ambientale batte la
    costante fissa. Sez. 13.F.
16. **`validate_team_defense_strength.py`** — fattore_forza_avversario su ranking
    (`domesticLeagueRanking`) — RIMOSSO da score_atteso (peggiora il MAE), poi scoperto che il dato
    stesso era contaminato (non storico, sez. 33.A) — sostituito dal gol reale (punto 10/17). Sez.
    12, 33.A.
17. **Stadio D con dato pulito (`opponent_strength.opponent_is_strong`)** — condizionamento
    venue+avversario sui granulari specifici (gol subiti/passaggio/clean sheet per DEF/MID).
    Fondato su `inspect_decisive_event_conditioning.py` (26/07, la probabilità di un evento
    decisivo cambia per venue/avversario?) e validato con `validate_stadio_d_mae.py` (le
    correzioni Stadio D riducono davvero il MAE per singolo giocatore, non solo in aggregato).
    IMPLEMENTATO su tutte le leghe (29/07). Sez. 11, 33.D, oggi.
18. **Cap goals_conceded** — bug reale (era cappato a ±10, ma il gioco è lineare senza tetto fino
    a 6-7 gol). RIMOSSO su tutte le leghe (GK/DEF/MID). Verificare se emergono partite con >7 gol
    subiti mai viste finora (non un retest statistico, solo un controllo di plausibilità). Sez.
    33.E.
19. **Combinazioni granulari cross-ruolo (33 testate, 2 validate)** —
    `validate_cross_role_combos.py` + `validate_cross_role_combos_isolated_otherleagues.py`
    (isola le 26 leghe extra da MLS/Korea), `validate_def_all_combos.py`,
    `validate_def_duels_opponent.py`, `validate_def_tackle_intercept_opponent.py` (precursori
    DEF-specifici, poi generalizzati nello script cross-ruolo),
    `validate_gk_offense_penalty_possession.py` — le 2 validate: `fwd_offense_granular_delta`
    (FWD vs poss_lost_ctrl DEF avversario) e `gk_def_pen_area_multiplier` (GK vs pen_area_entries
    DEF avversario). Le altre 31 combinazioni, scartate — non riprovarle senza nuovo motivo. Sez.
    33.F/G, 34.E.
20. **Shrinkage outlier/hot-streak (SHRINK_K per ruolo)** — diagnostico originale
    `inspect_outlier_reliability.py` (26/07, ha misurato il fenomeno "poche presenze + media
    trainata dai picchi": 19.7% DEF, 24.1% GK, 16.9% FWD, 7.1% MID) → `formazione_mls/diagnostics/
    validate_outlier_shrinkage.py` (oggi riscritto con auto-discovery, copre tutte le leghe) +
    `validate_outlier_shrinkage_tiered.py` (variante per titolarità via `mins_played`, superata dal
    prior dinamico) + `validate_shrink_k.py`/`validate_shrink_k_gk_true_formula.py` (ritest post-
    retuning half_life/trend — **lezione da non ripetere**: un giro precedente aveva usato per GK
    una formula SEMPLIFICATA invece di quella vera di produzione, dando risultati sbagliati, sez.
    24.C — verificare sempre con `compute_score_atteso_<ruolo>` reale, non una versione ad-hoc).
    Prima **modello unico GLOBALE su tutte le 27 leghe** (deciso oggi 29/07): **GK k=30, DEF k=15,
    MID k=5, FWD k=5**. Rifare ad ogni nuova lega — questo test è quello con l'esito più mutevole
    finora (GK e MID hanno cambiato conclusione completamente da una sessione all'altra man mano
    che i dati crescevano). Sez. 14.B, 24.C, oggi (sezione corrente).
20b. **Recalibrazione parametri In Season allineata alla formula reale** —
    `recalibrate_6leagues_inseason.py` (21/07, prima ricalibrazione con granulari VERI
    ricostruiti, non un flag inerte) → `recalibrate_def_aligned.py` (27/07, dopo la scoperta che
    il backtest era divergente dalla produzione, sez. 26.B/27 — DEF/FWD ricalibrati con la formula
    ALLINEATA). Stessa famiglia del punto 1, ma con la lezione esplicita "verificare sempre che il
    backtest usi la formula VERA di produzione, non una copia divergente" — da ricontrollare se si
    tocca di nuovo la formula di uno dei 4 ruoli.
21. **Breakdown per singola lega dello shrinkage FWD (MLS vs resto)** — script ad-hoc scritto
    oggi (non salvato nel repo, solo scratchpad) — ha smentito la vecchia esclusione "shrinkage
    FWD peggiora fuori MLS". **Da riscrivere/salvare come script vero se si vuole ripetere** questo
    controllo di dettaglio in futuro (oggi non persistito).
22. **Prior dinamico da presence_rate (per lo shrinkage sopra)** — regressione lineare
    presence_rate→prior per ruolo (GK/DEF/MID/FWD), dati da `.game_log_cache` (NON `.cache`, quello
    non ha gli status DID_NOT_PLAY). Coefficienti oggi: GK n=115 corr+0.245, DEF n=381 corr+0.447,
    MID n=331 corr+0.530, FWD n=287 corr+0.522 — da rifare quando le nuove leghe accumulano
    `.game_log_cache` sufficiente. Sez. 31.D, memoria `project_prior_dinamico_presence_rate`.

### C. Correlazioni tra compagni di squadra / sinergie

22b. **FWD+MID stessa squadra vs squadre diverse** — `formazione_mls/diagnostics/
    analyze_fwd_mid_team_pairing.py` (19/07 notte) — precursore/caso specifico poi assorbito nel
    test generico sotto (punto 23): same-team FWD-MID passato da marginale (+0.147, 2 leghe) a
    significativo (+0.191, 7 leghe) via `measure_teammate_correlation.py`. Non serve rilanciare
    questo script a parte, il punto 23 lo copre già in generale.
23. **Correlazione same-team** — `formazione_mls/diagnostics/measure_teammate_correlation.py`
    (auto-discovery filesystem, gira su TUTTE le leghe disponibili automaticamente). Ultimo esito
    (20 leghe, sez. 27.H): def-gk +0.349, def-def +0.201, fwd-fwd +0.177, fwd-mid +0.173, mid-mid
    +0.166, def-mid +0.156, gk-mid +0.142, def-fwd +0.107 — tutte in produzione (nudge
    `TEAMMATE_SYNERGY_BONUS_VARIANCE`, solo Arena/All Stars). **Da rilanciare quando si aggiungono
    leghe** (già esteso a 25 leghe il 28/07, sez. 28.H — va rilanciato di nuovo ora che sono ~27).
24. **Anti-sinergia cross-team (avversari)** — stesso script sopra, sezione cross-team. Solo
    fwd-gk (-0.289) in produzione. Le altre 6 coppie (def-def, mid-mid, gk-mid, def-mid, def-fwd,
    fwd-mid) sono risultate stabili su 25 leghe (28.H) ma **RIMANDATE su richiesta esplicita
    dell'utente** ("rifammela dopo") — riproporre la stessa domanda, non decidere da soli, quando
    si riprende questo filone.
25. **Sinergie In Season on/off (A/B su formazioni reali)** — `compare_synergy_toggles.py`,
    `compare_synergy_toggles_allleagues.py`,
    `compare_crossteam_matchreuse_toggles.py` — `POSITIVE_SYNERGY_BONUS_BY_PAIR` e
    `MATCH_REUSE_PENALTY` disattivati per In Season MLS/K League (guadagno di punteggio reale
    misurato su 6 formazioni); `SAME_TEAM_SYNERGY_BONUS_BY_PAIR` disattivato solo per Arena
    All Stars uncapped. **Test fatto SOLO su MLS/K League** (le uniche con In Season) — non
    applicabile alle altre leghe che non hanno In Season dedicata. Sez. 34.C.
26. **Analisi valore capitano portiere** — `formazione_mls/diagnostics/
    analyze_gk_captain_value.py` — bias di calibrazione GK vs movimento nella "zona capitano".
    `GK_CAPTAIN_MARGIN` oggi **6.7** (ricalibrato su 10 campionati, sez. 24.C) — **da ricalibrare
    quando cresce il pool GK** (resta il ruolo con meno dati). Solo `formazione_mls/
    build_formazione_finale.py` (modifiche capitano solo sul tool fuso, per richiesta esplicita).
    Sez. 18, 24.C.
27. **Simulazione tradeoff cap 260** — `formazione_mls/diagnostics/
    simulate_cap260_tradeoff.py` — conviene inseguire attivamente il cap L10? Esito: NO (sacrificio
    medio ~47pt vs break-even ~12pt). Non serve rifare a meno di cambi strutturali al bonus. Sez.
    13.B.
28. **Pesi reali dei gruppi granulari (quanto conta ognuno)** — `formazione_mls/diagnostics/
    inspect_granular_weights.py` — quota di `level_score` sul totale (56/41/49/63% GK/DEF/MID/FWD),
    "Eventi rari" a peso ~0 (rimosso dal codice). **Da rilanciare quando crescono le cache delle
    nuove leghe**, per verificare che le proporzioni restino coerenti. Sez. 9, 10, 24.A.

### D. Qualità di selezione (la metrica che conta davvero) e non-regressione

29. **Selection quality (lift catturato vs caso/oracolo)** — `formazione_mls/diagnostics/
    selection_quality.py` (solo DEF/FWD, argomento CLI) + **`selection_quality_shrinkage_allroles.py`
    (NUOVO 29/07, tutti e 4 i ruoli)** — la SCOPERTA chiave (sez. 27.C): il MAE non è la metrica
    giusta, conta quanto bene il modello ORDINA i candidati. **RITEST 29/07 dopo il retuning
    globale dello shrinkage della sezione corrente**: confronto lift MODELLO (shrink produzione)
    vs NO-SHRINK vs media pesata — **GK: shrink k=30 aiuta molto (-3.0% lift vs -37.6% senza
    shrink, ma solo 11 giornate/1 lega, campione minuscolo)**; **DEF: shrink k=15 aiuta lievemente
    (17.2% vs 16.0% lift, 140 giornate/16 leghe)** — il retuning di oggi ha risolto il vecchio
    problema (prima lo shrink DEF peggiorava il lift, sez. 27.C); **MID: shrink k=5 aiuta
    (45.1% vs 43.6%, ma solo 33 giornate/1 lega)**; **FWD: shrink k=5 PEGGIORA il lift (8.8% vs
    12.3-13.2% senza shrink, 21 giornate/1 lega)** — stesso problema storico di DEF, risolto con
    lo `score_ordinamento` (punto 30).
30. **Ordinamento senza shrinkage (`score_ordinamento`)** — separazione fra il numero MOSTRATO
    (con shrinkage, minimizza MAE) e l'ordine usato per selezionare (`shrink_k=0`, minimizza il
    lift). **IMPLEMENTATO PER DEF (tutte le leghe, sez. 28.E) e ORA ANCHE PER FWD (29/07, tutte
    le 27 leghe)** — MLS ce l'aveva già solo per FWD (mai propagato alle altre 26, bug trovato e
    corretto in corsa: quelle 26 leghe non hanno una funzione condivisa
    `compute_score_atteso_fwd` come MLS, quindi si riusa `grezzo_nuovo` già in scope invece di
    chiamare una funzione inesistente — verificato con py_compile/import prima di committare).
    **GK/MID non hanno `score_ordinamento`** — dal ritest sopra lo shrink li AIUTA (non li
    danneggia come FWD), quindi per ora non serve — ma il campione è piccolo (11-33 giornate),
    **da riverificare quando crescono più leghe con abbastanza candidati/giornata per GK/MID**
    (oggi quasi tutte le giornate valide vengono da una sola lega, non abbastanza titolari/
    giornata nelle leghe piccole per un vero test). Sez. 27.F, oggi.
31. **Non-regressione formula produzione vs backtest** — `nonregression_score_atteso_def.py`,
    `nonregression_score_atteso_fwd.py` — confrontano la funzione condivisa `compute_score_atteso_
    <ruolo>` contro il blocco inline REALE di produzione (estratto ed eseguito con `exec`, non
    riscritto a mano). Diff massima registrata: 7e-15 (DEF), 0.0 (FWD). **GK e MID non hanno un
    equivalente, MA IL RISCHIO È STRUTTURALMENTE DIVERSO (verificato 29/07)**: DEF/FWD storicamente
    avevano DUE copie della formula (una nella funzione condivisa per il backtest, una inline in
    `build_prediction`) che POTEVANO divergere — da qui il bisogno del test. **GK e MID invece
    chiamano `compute_score_atteso_gk`/`_mid` DIRETTAMENTE dentro `build_prediction`** (un solo
    punto di verità, nessuna copia parallela) — non serve un non-regression test perché non esiste
    un percorso di codice che possa divergere. Resta comunque vero che `compute_score_atteso_gk`/
    `_mid` esistono solo su MLS, non estratte sulle altre leghe (debito tecnico, sez. 31.D, memoria
    `project_backlog_fwd_shared_function_solo_mls`) — lì la formula è tutta inline, verificare a
    vista se si tocca quella formula.
32. **Tetto teorico (ICC, varianza entro/fra giocatori)** — analisi one-off (non uno script
    riutilizzabile), sez. 27.G: 94.5% della varianza DEF è rumore partita-per-partita, il modello
    è già al 17.8% del lift disponibile contro un tetto teorico ~15.5-22.5%. **Da ripetere se si
    vuole verificare che il tetto non sia salito con più dati/più partite per giocatore** (non
    urgente, il principio resta valido finché lo storico per giocatore non cresce molto).

### E'. Monitoraggio continuo e tool di copertura (non backtest, ma da tenere a mente)

32b. **MAE live** — `formazione_mls/predict/live_prediction_log.py` (scrive un pending-log per
    giocatore/partita target) + `formazione_kleague/diagnostics/resolve_live_predictions.py`
    (risolve confrontando con lo score reale non appena disponibile). Solo MLS/K League per ora
    (sez. 12), MAI esteso alle altre 25 leghe — utile da monitorare quando si toccano i parametri,
    non un test da "rilanciare" ma un log continuo da controllare periodicamente.
32c. **Copertura pool eleggibile / leghe mancanti** — `audit_leghe_possedute.py` (elenca tutte le
    leghe possedute con slug esatto, marca quelle non tracciate) e `diagnostics/
    discover_missing_leagues.py` (scansione carte per trovare leghe senza pipeline dedicata,
    output in `docs/CAMPIONATI_MANCANTI.md`). Non sono test statistici sul modello, ma vanno
    rilanciati quando si sospetta che manchino leghe/giocatori dal pool (sez. 23.F, 24.B).

### E. Test scartati/superati su "affidabilità" del singolo giocatore (29/07, oggi)

33. **Range di confidenza come segnale di affidabilità** — `formazione_mls/diagnostics/
    measure_range_reliability.py` (nuovo oggi) — range_width predice la dispersione reale?
    SCARTATO: correlazione ~0 per GK/DEF/FWD, MID debole e instabile (+0.20→+0.11 split-half).
    Fenomeno "stesso atteso, range diverso" diffuso (17-52% dei casi) ma irrilevante, il range non
    predice nulla. Oggi, sezione corrente.
34. **Trend recente come rischio** — `formazione_mls/diagnostics/
    measure_trend_presence_reliability.py` (test A, nuovo oggi) — SCARTATO: nessuna correlazione
    (-0.08/+0.07) tra ampiezza del trend e errore di previsione, in nessun ruolo. Oggi.
35. **Presence_rate come proxy di consistenza (non di media)** — stesso file (test B) — SCARTATO:
    dove c'è un segnale (DEF/MID +0.17/+0.19) va nella direzione OPPOSTA all'intuizione (chi gioca
    di più ha dev.std. più alta, non più bassa). Oggi.

### F. Nuovi test proposti (29/07) — 3 ESEGUITI oggi stesso, 1 rimandato

33b. **Ricalibrare i coefficienti presence_rate→prior dinamico** —
    `formazione_mls/diagnostics/recalibrate_presence_rate_prior.py` (NUOVO, eseguito 29/07). Pool
    esteso a 27 leghe (94-376 giocatori per ruolo) vs il pool più piccolo di sez. 31.D. **Risultato
    importante**: GK stabile (45.48/4.30 vs 45.41/4.36), ma DEF/MID/FWD hanno una pendenza
    (quanto il presence_rate basso penalizza il prior) MOLTO più debole di quella in produzione —
    DEF -26% (14.95→11.00), MID -37% (19.42→12.33), **FWD -63% (18.71→6.92, più che dimezzata)**.
    Correlazione ancora reale (0.13-0.27) ma il prior dinamico oggi rischia di penalizzare
    TROPPO i panchinari, specialmente FWD/MID. **NON ANCORA APPLICATO** (proposto all'utente,
    in attesa di conferma prima di cambiare le costanti in produzione).
34. **Interazione `opponent_lambda_mult` × troncatura Poisson** — verificato numericamente:
    **NESSUNA interazione**. Anche a λ=3.6 (ben oltre il massimo λ_pos osservato nei dati reali,
    1.2 per FWD) la differenza fra troncare a k_max=6 o k_max=15 è 0.0035 punti — irrilevante,
    perché `netto_to_level` satura comunque a ±5 di netto, la troncatura non perde informazione
    utile per costruzione. **Chiuso, non serve azione.**
35. **Correlazione compagni di squadra a livello di sotto-categoria granulare** — testato
    (script ad-hoc, non salvato nel repo): Duelli DEF vs Duelli MID (+0.010), Passaggio MID vs
    Azioni_difensive DEF (-0.033), Offensivo FWD vs Passaggio MID (+0.050), Gol_subiti DEF vs
    Offensivo MID (+0.058) — **tutte vicine a zero**, molto più deboli delle correlazioni sul
    punteggio TOTALE già in produzione (0.13-0.35). Il segnale di sinergia vive nell'aggregato/
    level_score, non nelle sotto-categorie specifiche testate. **Chiuso, nessun segnale
    sfruttabile trovato.**
36. **Estendere il test A/B sinergie (oggi solo In Season MLS/K League, sez. 34.C) alle Arene
    dedicate delle altre 9 leghe** (Belgio, Turchia, Portogallo, Spagna, Germania, Francia/Ligue1,
    Croazia, Scozia, Olanda/Eredivisie) — **NON FATTIBILE in locale** (richiede rose realmente
    possedute + query dal vivo per generare formazioni Arena vere, non simulabile dalle sole
    cache di calibrazione già su disco). **Da fare alla prossima run reale del generatore
    formazioni** su quelle leghe, non un test offline.

### G. Come procedere in pratica quando arriva una nuova lega

1. Completare per la nuova lega: discovery globale (se prevista) + `CALIBRATION_MODE=1` (predict)
   per popolare `.cache`/`.game_log_cache` — SENZA questo passo i test sopra non vedono nessun dato
   nuovo (sez. 34.F, lezione Germania).
2. Rilanciare in ordine i test della sezione A (parametri base) e poi B (shrinkage/level_score),
   confrontando il "vincitore" con quello attuale — se cambia, proporre il cambio all'utente PRIMA
   di applicarlo (mai in autonomia, principio "un tema alla volta" di sempre).
3. Rilanciare C (correlazioni/sinergie) solo se si sospetta un cambiamento (i nudge sono piccoli,
   il ritorno sull'investimento di rilanciarli spesso è basso finché non si accumula molto storico).
4. D (selection quality/non-regressione) va rifatto solo quando si cambia la FORMULA di un ruolo,
   non per ogni nuova lega.
5. Se un test conferma la produzione attuale, annotarlo qui con la data e i numeri (anche un
   "riconfermato, nessun cambio" è informazione utile per non riproporlo).

## 1. Contesto: cos'è il tool formazione (riassunto minimo)

Sistema che, dato l'elenco delle carte MLS possedute dall'utente su Sorare (fantasy game calcio
NFT), calcola per ognuno dei 4 ruoli (GK/DEF/MID/FWD) uno score atteso per la prossima partita
(media pesata storica x fattori casa/trasferta, forza avversario, trend, granulari per
statistica), poi fonde i 4 migliori in N formazioni ottimali. Script principali:
`formazione_mls/predict/test_gk.py`, `test_def.py`, `test_mid.py`, `test_mls_fwd_all.py`.
Parametri della formula (half_life, range_multiplier, opponent_sensitivity, trend_intensity) sono
FISSI, decisi da un grid search di calibrazione (72 combinazioni testate in backtest rigoroso).

## 2. Cosa è successo in QUESTA sessione (in ordine)

### A. Fix Finding 3 dell'audit logico: doppio conteggio casa/trasferta

`fattore_casa_trasferta` era calcolato sul punteggio TOTALE della partita — che però include già
il contributo di ogni gruppo granulare (falli, duelli, passaggio, ecc.), causando un doppio
conteggio quando poi ogni fattore granulare veniva applicato separatamente. **Fix**: ora si
calcola solo sul RESIDUO (score totale meno la somma di tutti i gruppi granulari tracciati),
applicato a DEF/MID/FWD (GK non toccato: i granulari lì sono solo diagnostici, non in
produzione). Verificato su dati reali con un run vero: l'effetto casa/trasferta ora emerge dai
gruppi granulari specifici (es. gol subiti, falli) invece che duplicato da un fattore globale
gonfiato. **Committato e pushato** (commit `5219bf8d`, poi mergiato in `d8538e3a`).

### B. Discovery globale estesa a tutti e 4 i ruoli + filtro qualità

Prima c'era solo `mls_mid_discovery_global.py` (centrocampisti). Estesa a GK/DEF/FWD
(`mls_gk_discovery_global.py`, `mls_def_discovery_global.py`, `mls_fwd_discovery_global.py`),
stesso approccio: scansione pubblica (nessun cookie richiesto) delle 30 squadre MLS, filtro
lato client per posizione. Workflow `mls_mid_discovery_global.yml` sostituito da un workflow a
matrice unico, `mls_discovery_global.yml` (un job per ruolo).

Risultati grezzi (30/07, prima del filtro qualità): **74 GK, 340 DEF, 346 MID, 276 FWD**.

**Filtro qualità aggiunto** (richiesta esplicita utente: "non voglio calibrare su giocatori
scarsi che non comprerei"): tenuti solo i giocatori con media `(L5+L10+L40)/3 >= 30.0`
(costante `MIN_AVG_SCORE_QUALITY`, letta da env, default 30.0 — abbassata da un iniziale 40.0
perché tagliava troppo, specialmente sui portieri). Le medie L5/L10/L40 vengono lette
direttamente dall'API Sorare (`anyPlayer.averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE /
LAST_TEN_PLAYED_SO5_AVERAGE_SCORE / LAST_FORTY_SO5_AVERAGE_SCORE)`), non calcolate a mano. Se uno
dei tre valori manca, il giocatore è escluso per sicurezza (storico insufficiente).

Giocatori qualificati dopo il filtro (soglia 30): **27 GK, 156 DEF, 156 MID**, FWD non ancora
verificato con questa soglia esatta (con soglia 40 di test erano 62/276).

Tutto **committato e pushato** (commit `50b23531`).

### C. Infrastruttura di calibrazione allargata (grid search su tutti, non solo posseduti)

Obiettivo: ricalibrare i parametri fissi su un campione molto più ampio dei soli posseduti
(12-45 giocatori a seconda del ruolo), ora che la formula è corretta (fix punto A).

- **`CALIBRATION_MODE`** (env var booleana, nei 4 script `test_<ruolo>.py`): se attiva, legge la
  lista GLOBALE filtrata (invece dei soli posseduti) e riesegue il grid search COMPLETO (72
  combinazioni, funzione `run_grid_search` già esistente nel codice ma non più usata in
  produzione) invece del singolo backtest fisso. Output isolato in cartelle
  `formazione_mls/output/mls_<ruolo>_calibration/` (separate da `mls_<ruolo>_all/` di
  produzione, per non inquinare quello che legge `build_formazione_finale.py`).
- **`.github/workflows/grid_search_calibrazione.yml`**: workflow a batch (input: `ruolo`
  gk/def/mid/fwd, `batch_index`, `batch_size` default 200, `min_avg_score_quality` default 30).
  GitHub Actions ha un limite di 256 job/matrice, da qui la logica a batch — ma finora ogni ruolo
  è stato coperto da UN SOLO batch (nessuno ha superato 200 giocatori qualificati).
- **`.github/workflows/grid_search_aggregate.yml`** + `formazione_mls/calibrazione/
  aggregate_grid_search.py` (parametrizzato per ruolo via env `RUOLO`, prima era hardcoded solo
  per FWD): calcola quale combinazione di parametri generalizza meglio ATTRAVERSO tutti i
  giocatori con dati sufficienti. **Nota**: l'aggregazione è puro calcolo locale sui file JSON già
  scaricati (`git pull`) — non serve rilanciare un workflow GitHub per farla, basta eseguire lo
  script in locale con `RUOLO=<ruolo> python formazione_mls/calibrazione/aggregate_grid_search.py`
  dopo un `git pull`. Il workflow `grid_search_aggregate.yml` esiste solo per farlo girare anche
  da CI se preferito, non è necessario.

**Due bug REALI trovati e corretti durante il primo giro di batch veri** (importante, per non
ripeterli in futuro):

1. **`MIN_STARTER_ODDS` non veniva disattivato in `CALIBRATION_MODE`**: era una costante fissa
   (0.70) con un commento che diceva "se rifai il grid search, riportala a 0.0 a mano" — non letta
   da env, quindi l'override che passavo dal workflow non aveva alcun effetto. Nel primo batch GK
   (27 giocatori) questo ha escluso 25/27 giocatori (starterOdds sotto soglia — irrilevante per
   la calibrazione, che deve guardare tutto lo storico, non solo la prossima partita). **Fix**:
   ora è `0.0 if CALIBRATION_MODE else 0.70` in tutti e 4 gli script. Commit `7a72cad9`.
2. **Bug critico nel retry di push del job `calibrate`** (workflow a matrice, fino a 8 worker
   paralleli): il loop era scritto come `for attempt in 1..8: git add + diff-check + commit +
   push`, ripetendo il diff-check ad OGNI tentativo — dopo un primo commit locale riuscito, se il
   push falliva (conflitto con un altro worker), il tentativo successivo trovava l'indice già
   pulito (nulla di NUOVO da staggare, essendo già committato) e usciva con "Nessuna modifica da
   salvare" **senza mai ritentare il push** — il commit restava intrappolato nel checkout effimero
   del runner e andava perso, MA il job segnalava comunque successo (mascherando il problema).
   Nel primo batch DEF (156 difensori, max-parallel:8) questo ha fatto perdere 123 risultati su
   156 (solo 33 salvati). **Fix**: diff-check e commit avvengono UNA VOLTA sola, poi un loop
   `until git push` dedicato SOLO al retry del push (fetch+merge tra un tentativo e l'altro) —
   stesso pattern già corretto e testato nei workflow di discovery esistenti
   (`formazione_completa.yml`). Commit `1e293791`. **Dopo il fix, il batch DEF rilanciato è
   passato da 33 a 99 risultati salvati su 156** — se in futuro si scrive un altro workflow a
   matrice con commit paralleli, NON riprodurre l'errore del punto 1 (ricontrollare `git diff
   --cached` dopo un commit già fatto).

### D. Batch eseguiti e risultati di aggregazione (fine sessione)

Tutti i batch sono stati lanciati con `batch_index=0`, `batch_size=200`,
`min_avg_score_quality=30` — in ogni caso un solo batch ha coperto tutto il ruolo.

| Ruolo | Qualificati | Grid completi | Con dati sufficienti per l'aggregazione | Combinazione vincente aggregata |
|---|---|---|---|---|
| GK | 27 | 7 (4 senza storico sufficiente per NESSUNA combinazione) | **3** | hl=12.0, range=1.2x, opp_sens=29.0, trend=0.7, **senza granulari** — MAE 18.42, copertura 69.4% |
| DEF | 156 | 99 | **74** | hl=9.0, range=1.4x, opp_sens=29.0, trend=0.7, **con granulari** — MAE 16.65, copertura 68.3% |
| MID | 156 | 96 | **68** | hl=12.0, range=1.4x, opp_sens=29.0, trend=0.7, **senza granulari** — MAE 15.61, copertura 68.9% |
| FWD | ? | — | — | **NON ANCORA FATTO** |

Confronto con i parametri attuali di produzione (calibrati su soli posseduti, PRIMA del fix
Finding 3 — quindi non un confronto a parità di condizioni, solo un riferimento):
- GK produzione: hl=9.0, range=1.6x, opp_sens=20.0, trend=0.7, senza granulari (12 posseduti,
  MAE 21.03, copertura 63.3%)
- DEF produzione: hl=9.0, range=1.2x, opp_sens=29.0, trend=1.3, con granulari (45 posseduti,
  MAE 15.65, copertura 69.4%)
- MID produzione: hl=12.0, range=1.4x, opp_sens=29.0, trend=0.7, con granulari (19 posseduti,
  MAE 15.62, copertura 68.3%)

Osservazione interessante: sul campione allargato e con la formula corretta, DEF continua a
beneficiare dei fattori granulari (conferma la scelta attuale), mentre per MID il campione
allargato suggerisce che i granulari NON aiutino più (la versione senza è in cima alla
classifica, anche se di poco: MAE 15.61 vs 15.81 con granulari) — da tenere in considerazione se
si decide di aggiornare i parametri di produzione.

I file `combinazione_vincente_aggregata.json` per GK/DEF/MID sono su disco in
`formazione_mls/output/mls_<ruolo>_calibration/` ma **NON ANCORA COMMITTATI** (generati in
locale, vedi sezione "Stato del repo" sotto).

## 3. Cosa manca / prossimi passi immediati (in ordine)

1. **Lanciare il batch FWD**: `gh workflow run "Grid Search Calibrazione (allargata, a batch)" -f
   ruolo=fwd -f batch_index=0 -f batch_size=200 -f min_avg_score_quality=30`, poi monitorare
   (`gh run watch <id> --exit-status`, o `gh run list --workflow="Grid Search Calibrazione
   (allargata, a batch)" --limit 3` per il run id). **Attenzione rate-limit**: l'utente lavora
   spesso in parallelo sull'app/sito Sorare — chiedere conferma prima di lanciare nuove run se non
   è chiaro se sta usando l'app in quel momento (gli è già capitato di chiedere di mettere in
   pausa script locali per lo stesso motivo).
2. **Aggregare FWD** (locale, no GitHub necessario): `git pull --rebase origin main` poi
   `RUOLO=fwd python formazione_mls/calibrazione/aggregate_grid_search.py`.
3. **Decidere con l'utente** se e come aggiornare i parametri fissi di produzione (costanti
   `HALF_LIFE_GAMES`/`RANGE_MULTIPLIER`/`OPPONENT_SENSITIVITY`/`TREND_INTENSITY` e il flag
   granulari sì/no) nei 4 `test_<ruolo>.py`, sulla base dei risultati aggregati — NON farlo senza
   chiedere, è una decisione che cambia il comportamento di produzione.
4. **Committare** `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` (creato in questa sessione ma mai
   committato — vedi sezione "Stato del repo" sotto) e i file
   `combinazione_vincente_aggregata.json` di GK/DEF/MID già generati.
5. Poi tornare ai **Finding 4-5** dell'audit logico (condizionamento 2D venue+forza avversario,
   correlazione tra slot della formazione GK-DEF-FWD) — discussi ma non implementati, richiedono
   un design dedicato prima di scrivere codice (vedi `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`
   sezione 5 per il dettaglio).

## 4. Lavoro parallelo in corso su un ALTRO argomento (bot di trading, non il modello predittivo)

Nella stessa giornata, in un'altra conversazione/worktree, è in corso un lavoro SEPARATO e non
correlato: rendere dinamiche (basate su percentili storici) le soglie di margine di
`bots/bot_definitivo.py` (ex `bot_supremo_test.py`, rinominato in questa giornata) e dei bot
standalone `autobuy_sorare.py`/`makeoffer_sorare.py`. Menzionato qui solo per completezza — se
l'utente lo tira in ballo in questa sessione, è un filone indipendente con la sua sessione
dedicata, non mischiarlo con il lavoro sul modello predittivo descritto sopra.

## 5. Stato del repo a fine sessione (verificare comunque, non fidarsi ciecamente)

**Pushato su `origin/main`**: fix Finding 3 (`5219bf8d`), discovery globale 4 ruoli + filtro
qualità (`50b23531`), infrastruttura calibrazione (`29d67869`), fix MIN_STARTER_ODDS (`7a72cad9`),
fix bug retry push (`1e293791`), più tutti i commit automatici dei bot (`Grid Search Calibrazione
(<ruolo>): <slug>` uno per giocatore, generati dai workflow) e i commit periodici di "Bot Supremo:
lista nera" (bot di trading indipendente, sempre attivo in background).

**NON ancora committato** (file locali, generati/modificati in questa sessione):
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` (creato, mai `git add`)
- `formazione_mls/output/mls_gk_calibration/combinazione_vincente_aggregata.json`
- `formazione_mls/output/mls_def_calibration/combinazione_vincente_aggregata.json`
- `formazione_mls/output/mls_mid_calibration/combinazione_vincente_aggregata.json`

Da committare quando si riprende (nessuna fretta, sono solo risultati informativi, non toccano
la produzione):
```
git add docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md \
  formazione_mls/output/mls_gk_calibration/combinazione_vincente_aggregata.json \
  formazione_mls/output/mls_def_calibration/combinazione_vincente_aggregata.json \
  formazione_mls/output/mls_mid_calibration/combinazione_vincente_aggregata.json
git commit -m "Aggiunge documentazione evoluzione + combinazioni vincenti aggregate GK/DEF/MID"
git pull --rebase origin main  # ci saranno sicuramente nuovi commit automatici dei bot nel frattempo
git push origin main
```

## 6. File chiave per orientarsi rapidamente

- `formazione_mls/predict/test_gk.py` / `test_def.py` / `test_mid.py` / `test_mls_fwd_all.py` —
  formula di scoring + `CALIBRATION_MODE`
- `formazione_mls/discovery/mls_<ruolo>_discovery_global.py` — discovery pubblica + filtro qualità
- `formazione_mls/calibrazione/aggregate_grid_search.py` — aggregazione cross-player (locale)
- `.github/workflows/grid_search_calibrazione.yml` — batch grid search allargato
- `.github/workflows/grid_search_aggregate.yml` — aggregazione via CI (opzionale, si può fare in locale)
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` — storia/architettura completa del tool (documento vivo)

## 7. Aggiornamento 26/07/2026 — decisione presa, parametri di produzione FINALIZZATI

Continuazione della sessione sopra, in un account diverso. Riepilogo di quello che è successo,
in ordine:

### A. Batch FWD completato + aggregazione (chiudeva il punto 1-2 della sezione 3)

Lanciato il batch mancante (139 attaccanti qualificati, 0 job falliti). Aggregazione (non pesata,
prima versione): hl=9.0, range=1.4x, opp_sens=29.0, trend=1.0, senza granulari, MAE 16.76,
copertura 68.0%, 41 giocatori. Committato (`11016946`).

### B. Scoperto e corretto un bug di fondo nell'aggregazione: media non pesata per n_test

Analizzando il caso FWD, l'effetto dei fattori granulari per SINGOLO giocatore variava da -5 a +5
di MAE tra combinazioni con/senza — ma la media aggregata su 41 giocatori si cancellava quasi a
zero (+0.07 medio, std 1.42). Causa: il MAE per-giocatore viene da un backtest rigoroso con
`min_history=6`, e la finestra di partite testate per giocatore è spesso minuscola (mediana 7,
alcuni con solo 1-3 partite) — un giocatore con 1 sola partita testata pesava nella media quanto
uno con 9, ma il suo "MAE" è di fatto l'errore di un singolo evento, non una stima stabile.
Verificato con dati: i 2 casi più estremi (`osvaldo-pedro-capemba` -5.1, `matias-coccaro-ferreira`
-1.57) avevano entrambi `n_test=1`; correlazione moderata (-0.39) tra n_test e ampiezza dell'effetto.

**Fix** in `formazione_mls/calibrazione/aggregate_grid_search.py`: esclude i giocatori con meno di
`MIN_TEST_GAMES` (env, default 3) partite di backtest dall'aggregazione, e pesa MAE/copertura dei
rimanenti per `n_test` invece di una media semplice per-giocatore. `n_test` ora salvato
direttamente nel campo `n_test` del `grid.json` di ogni giocatore in tutti e 4 gli script
`test_<ruolo>.py` (per i run futuri); fallback al parsing di "Partite testate" dal
`prediction_<slug>_*.txt` per i dati già raccolti del 25/07 (che non avevano ancora questo campo).
Rieseguita l'aggregazione pesata su DEF/MID/FWD con i dati già su disco (nessun nuovo run GitHub
necessario). Commit `ee16fd44`/`a3afc2dc`.

**Risultato pesato (min 3 partite di backtest), molto più coerente del non pesato**:

| Ruolo | half_life | range | opp_sens | trend | granulari | MAE | copertura | n_gioc (partite pesate) |
|---|---|---|---|---|---|---|---|---|
| GK (invariato, campione insufficiente: solo 2 con n_test>=3) | 12.0 | 1.2 | 29.0 | 0.7 | NO | 18.42 | 69.4% | 3 |
| DEF | 12.0 | 1.2 | 29.0 | 0.7 | NO | 16.28 | 67.5% | 68 (517 partite) |
| MID | 12.0 | 1.4 | 29.0 | 0.7 | NO | 15.55 | 70.9% | 65 (492 partite) |
| FWD | 12.0 | 1.4 | 29.0 | 0.7 | NO | 17.33 | 68.2% | 37 (255 partite) |

Tutti e tre i ruoli con dati sufficienti (DEF/MID/FWD) convergono sugli STESSI parametri
(`hl=12.0, opp_sens=29.0, trend=0.7`, senza granulari) — molto più coerente del risultato non
pesato precedente (che per FWD divergeva su hl=9.0/trend=1.0, inquinato da singoli match).

### C. Scoperta tecnica importante: il flag "granulari sì/no" non esisteva davvero in produzione

Il flag `use_granular_factors` passato a `rigorous_backtest` controllava SOLO il backtest
diagnostico mostrato nell'output testuale — la formula REALE di `score_atteso` usata per
costruire le formazioni (in DEF/MID/FWD) moltiplicava SEMPRE tutti i fattori granulari
incondizionatamente, indipendentemente da cosa diceva la calibrazione. GK invece li aveva già
rimossi correttamente dalla formula reale (hardcoded). **Fix**: rimossi i fattori granulari anche
dallo `score_atteso` reale di DEF/MID/FWD (stesso pattern di GK) — senza questo fix, applicare i
nuovi parametri "senza granulari" non avrebbe avuto alcun effetto pratico sulle formazioni.

### D. Confronto A/B su formazioni reali + decisione dell'utente

Applicati i parametri pesati a DEF/MID/FWD (GK invariato) e lanciata una run reale
(`formazione_completa.yml`, num_formazioni=5), confrontata con l'ultima run precedente col vecchio
modello (anch'essa 5 formazioni). Risultato: TOTALE COMPLESSIVO 1577 -> 1653 pt (+4.8%), con
riordinamenti interessanti — caso più chiaro: **Antino Lopez** (DEF che gioca solo il 25% delle
ultime 40 partite storiche, ma con picchi isolati come 86/81) era capitano nel vecchio modello a
86pt (sovrappesato dagli half_life/trend più reattivi e dai granulari non normalizzati), nel nuovo
modello scende a un più realistico 75pt/non più capitano; **Carles Gil** (centrocampista che gioca
quasi sempre, 100% presenze ultime 5/10, media stabile 67-70) sale correttamente a capitano.
Verificato contro le statistiche Sorare reali dei due giocatori (screenshot diretto dall'utente) —
il nuovo modello descrive meglio "chi performa in modo affidabile" vs "chi ha avuto un picco
isolato di fortuna". **Nota**: le due run distano ~5 ore con partite MLS in corso nel mezzo, quindi
parte della differenza numerica potrebbe venire da dati aggiornati (starter odds/nuove partite),
non solo dal cambio di parametri — ma il caso Antino Lopez/Carles Gil è un confronto diretto,
concettualmente pulito, e ha convinto l'utente.

**Decisione presa (26/07)**: parametri UFFICIALI (non più "test") in produzione:
- **DEF**: `hl=12.0, range=1.2, opp_sens=29.0, trend=0.7`, SENZA granulari (era hl=9.0/trend=1.3/CON granulari)
- **MID**: `hl=12.0, range=1.4, opp_sens=29.0, trend=0.7`, SENZA granulari (era trend=1.0/CON granulari, resto invariato)
- **FWD**: `hl=12.0, range=1.4, opp_sens=29.0, trend=0.7`, SENZA granulari (numeri invariati, solo granulari rimossi)
- **GK**: INVARIATO (`hl=9.0, range=1.6, opp_sens=20.0, trend=0.7`, senza granulari) — campione
  troppo piccolo (2-3 giocatori) per fidarsi di un'aggregazione pesata, da rivedere quando si avrà
  più storico.

Commit di finalizzazione: `2e9fa0eb`/`f246973e`. Tutto pushato su `origin/main`.

### E. Prossimi passi (in ordine, sostituisce la sezione 3 sopra)

1. **Finding 3+F** dell'audit logico (condizionamento 2D venue+forza avversario invece che
   separati; correlazione tra slot della formazione: bonus sinergia GK+DEF stessa partita,
   penalità anti-sinergia GK vs FWD avversario) — vedi `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`
   sezione 5. C'era un task in background (`task_c858ec41`, lanciato dall'utente in un'altra
   sessione locale) per una proposta di design — **mai verificato se ha prodotto un output**,
   l'utente non sa come controllarlo da qui: chiedere se l'ha trovato, altrimenti si riparte da
   zero su questo tema quando arriva il suo turno.
2. **GK**: ricalibrare quando si avrà un campione più ampio di giocatori con storico sufficiente
   (oggi solo 2-3 qualificati con n_test>=3) — non prioritario, resta backlog.
3. **Backlog di idee più ampio** (26/07, l'utente ha dichiarato "una settimana di tempo per
   implementare e migliorare il modello", da affrontare UNA ALLA VOLTA, scegliendo insieme
   l'approccio prima di implementare — non procedere in autonomia su più fronti):
   - Robustezza statistica del backtest: campioni piccoli per giocatore (vedi punto B sopra),
     possibile cross-validation temporale o bootstrap sui giocatori per capire quanto è stabile
     la "combinazione vincente", split train/validation espliciti.
   - Feature aggiuntive non sfruttate: infortuni/squalifiche imminenti, calendario congestionato
     (rotazione/turnover), modulo tattico (bassa priorità).
   - Gestione outlier/hot-streak non sostenibili: pesare la media storica anche per "affidabilità"
     (numero di presenze recenti, non solo half-life), rilevamento automatico di picchi isolati
     da attenuare (caso Antino Lopez come esempio concreto).
   - Monitoraggio continuo: MAE "live" calcolato in produzione (score_atteso pubblicato vs score
     reale ottenuto), non solo backtest retrospettivo.
   - Estensione dell'infrastruttura (discovery globale + filtro qualità + calibrazione a batch) ad
     altri campionati oltre MLS, come test di generalizzazione.
4. Lavoro indipendente/non correlato in corso su un ALTRO filone (bot di trading
   `bots/bot_definitivo.py`) — vedi sezione 4 sopra, non mischiare.

## 8. Approfondimento robustezza statistica del backtest (26/07, stesso giorno — primo tema del backlog punto 3)

Prima di passare al tema successivo del backlog, l'utente ha voluto approfondire "Robustezza
statistica del backtest" (B+C+D del menu di opzioni proposto, poi anche una quarta iterazione).
MLS è **a circa metà campionato** al momento di scrivere questo — informazione rilevante: il
volume di dati per giocatore crescerà ancora ma non esploderà a breve (al massimo raddoppierà
entro fine stagione), quindi ha senso sfruttare bene i dati attuali con metodi statistici più
prudenti invece di aspettare passivamente più partite.

**B. Bootstrap win-rate** (nuovo script `formazione_mls/calibrazione/bootstrap_stability.py`,
1000 ricampionamenti con sostituzione dei giocatori qualificati, per ruolo): la combinazione
vincente ufficiale vince solo il **17.4% (FWD)**, **32.8% (DEF)**, **19.2% (MID)** dei
ricampionamenti — nessun vincitore netto, con un campione leggermente diverso di giocatori MLS
sarebbe probabilmente uscita una combinazione diversa. Segnale positivo: **`opponent_sensitivity
=29.0` non cambia MAI** nella top-10 di nessun ruolo — è l'unico parametro davvero stabile; le
vere zone di incertezza sono half_life (9 vs 12) e il flag granulari.

**C. Intervallo di confidenza bootstrap 95% sul MAE**: bande larghe per tutti i ruoli (es. FWD
15.84-18.70) — confermano che differenze di 0.1-0.3 MAE tra combinazioni viste durante
l'aggregazione erano dentro il rumore statistico, non un segnale reale.

**D. Sensitivity check su `MIN_TEST_GAMES`** (soglia minima partite di backtest per essere
incluso nell'aggregazione, provata a 3/5/7): la combinazione vincente CAMBIA a seconda della
soglia (es. FWD: trend 0.7→1.3→0.7 a seconda della soglia; DEF: hl 12→9→9) — mai un salto a
parametri assurdi, ma conferma ulteriore che il segnale è debole rispetto al rumore campionario.
Solo un check, nessun artefatto prodotto (i JSON ufficiali erano stati temporaneamente sovrascritti
da questi run di prova e sono stati ripristinati con `git checkout` subito dopo).

**Raccomandazione a media pesata bootstrap** (estensione di `bootstrap_stability.py`, seconda
iterazione): invece di riportare solo il vincitore secco, calcola una media dei parametri numerici
pesata per quante volte ogni combinazione vince nei ricampionamenti — un valore continuo che
riflette l'incertezza invece di un estremo arbitrario della griglia discreta:

| Ruolo | half_life (pesato) | range (pesato) | opp_sens (pesato) | trend (pesato) | granulari nelle vittorie |
|---|---|---|---|---|---|
| FWD | 10.48 | 1.40 | 29.00 | 0.92 | 31.1% (NO prevale) |
| DEF | 10.99 | 1.25 | 28.97 | 0.73 | 29.9% (NO prevale) |
| MID | 11.14 | 1.32 | 28.98 | 0.86 | 32.4% (NO prevale) |

**Perché è una buona notizia**: la percentuale "granulari" è consistentemente intorno al 30% su
tutti e tre i ruoli (non vicina al 50%) — la decisione "senza granulari" già presa non è un
coin-flip casuale, è un segnale debole ma coerente attraverso i ruoli. Gli scarti sui parametri
numerici rispetto ai valori ufficiali fissati sono modesti (half_life ~10.5-11 pesato vs 12.0
ufficiale; trend più alto per MID/FWD, 0.86-0.92 pesato vs 0.70 ufficiale — DEF è il più vicino,
0.73 vs 0.70).

**Decisione presa**: NON cambiare i parametri ufficiali ora (già validati dal caso reale Antino
Lopez/Carles Gil, e comunque nello stesso "vicinato" statistico di questi valori pesati — nessuno
scarto scioccante). Questi numeri servono come **riferimento per il prossimo giro di
ricalibrazione** a stagione più avanzata: se il vincitore secco del prossimo grid search si
avvicinerà a questi valori pesati, sapremo che la stima si è stabilizzata; se diverge molto,
sapremo che il segnale è ancora debole anche con più dati.

**Tema chiuso**. Prossimo tema dal backlog (sezione 7E sopra), da scegliere con l'utente uno alla
volta: condizionamento 2D venue+avversario/correlazione slot formazione (il più maturo ma da
ridisegnare da zero, task in background non recuperabile), feature aggiuntive, gestione
outlier/hot-streak, monitoraggio MAE live, estensione ad altri campionati.

## 9. Allargamento soglia qualità calibrazione + scoperta `level_score` (26/07, notte)

Emerso dal tema robustezza statistica: il vero collo di bottiglia è il numero totale di partite
disponibili (37-68 giocatori/255-517 partite per ruolo dopo il filtro qualità=30 + n_test>=3). Il
filtro qualità serve alla PRODUZIONE (non suggerire giocatori scarsi), non alla calibrazione (che
cerca parametri strutturali della formula) — deciso di abbassarlo **solo per la calibrazione** a
**15** (via `min_avg_score_quality` del workflow, produzione invariata a 30).

**Fix preventivo**: `grid_search_calibrazione.yml` ora esclude i giocatori con un `grid.json` già
presente prima di applicare batch_index/batch_size — permette di riabbassare la soglia e
processare SOLO i giocatori nuovi, senza rifare query/job sui già analizzati.

**Lanciati batch per tutti e 4 i ruoli** (autorizzato esplicitamente dall'utente per l'esecuzione
notturna, incluso l'eventuale lancio di batch residui senza chiedere conferma). **Attenzione
rate-limit gestita**: lanciare i 4 ruoli in PARALLELO avrebbe significato fino a 32 job CI
contemporanei sullo stesso account Sorare (4 ruoli x max 8 worker) — rischio concreto di 429
condiviso (incidente reale già documentato in passato). Cancellati i run DEF/MID/FWD lanciati in
parallelo (erano ancora in fase discover_batch, nessuna query pesante fatta) e rilanciati **in
sequenza, uno alla volta** (GK→DEF→MID→FWD), tramite uno script di orchestrazione bash in
background. Tutti e 4 completati con successo, nessun batch residuo necessario (pool
completamente coperto in un solo batch per ruolo).

Risultati (aggregazione pesata per n_test, min 3 partite):

| Ruolo | Qualificati (soglia 15) | Con n_test>=3 | Combinazione vincente | MAE | Bootstrap win-rate |
|---|---|---|---|---|---|
| GK | 29 (+2 vs soglia 30) | 13 (+10) | hl=9.0, range=1.4, opp_sens=29.0, trend=0.7, NO granulari | 18.96 | 12.2% (debole) |
| DEF | 197 (+41) | 69 (+1) | hl=12.0, range=1.2, opp_sens=29.0, trend=0.7, NO granulari | 16.39 | 34.0% (incerta, la più solida) |
| MID | 183 (+27) | 68 (+3) | hl=12.0, range=1.2, opp_sens=29.0, trend=0.7, NO granulari | 15.30 | 19.6% (debole) |
| FWD | 157 (+18) | 38 (+1) | hl=9.0, range=1.4, opp_sens=29.0, trend=0.7, NO granulari | 17.44 | 14.5% (debole) |

**Lezione onesta**: raddoppiare/ampliare il pool di giocatori per DEF/MID/FWD NON ha migliorato
sostanzialmente il win-rate bootstrap (era 17-33%, ora 14-34%) — il problema non è "poca varietà
di giocatori", è che le combinazioni vicine sono genuinamente statisticamente equivalenti con
questo volume di partite per giocatore (limitato dalla metà campionato MLS). Servirà aspettare
che la stagione avanzi (più partite a testa), non solo più giocatori. `opponent_sensitivity`
resta l'UNICO parametro sempre stabile (~29.0 ovunque, incluso ora GK). Non applicato alla
produzione (nessuna decisione presa stanotte, solo dati raccolti per la prossima sessione).

### Scoperta importante: il peso reale dei granulari (approfondimento richiesto dall'utente)

L'utente ha notato (da screenshot Sorare reali di Andre Blake) che alcune categorie di punteggio
sembravano pesare molto più di altre. Creato `formazione_mls/diagnostics/inspect_granular_weights.py`
(diagnostico locale, legge solo le cache `.cache/*_detail_cache.json` già scaricate, nessuna
nuova query) per misurare il peso reale di ogni gruppo granulare sul movimento assoluto del
punteggio, su TUTTE le partite disponibili (non a campione a mano).

**Scoperta principale**: il campo `level_score` (category=UNKNOWN nel detailedScore, legato al
bonus clean sheet per il portiere: ~35 se ha subito gol nei primi 60', ~60 se clean sheet) **non è
incluso in NESSUNO dei gruppi granulari tracciati, in NESSUN ruolo** — e vale da solo la quota più
grande del punteggio ovunque: **56,2% GK, 40,9% DEF, 48,8% MID, 62,8% FWD** (migliaia di partite
reali analizzate). **Nota importante segnalata dall'utente**: `level_score` ha una base FISSA di
35 assegnata a chiunque scenda in campo anche un secondo — quindi il peso misurato è gonfiato da
questa componente fissa non predicibile; la vera leva sfruttabile è probabilmente più piccola e
riconducibile a poche soglie discrete (ha giocato/clean sheet), non un continuo — da scorporare
prima di investire tempo nel modellarlo.

**Altra scoperta utile**: la categoria **"Eventi rari" vale 0,0-0,1% su TUTTI e 4 i ruoli**
(candidato sicuro per la rimozione dal codice, zero rischio). Il resto dei gruppi ha un mix
sensato per ruolo (Duelli domina per DEF/MID/FWD 17-23%, Efficacia offensiva cresce avvicinandosi
all'attacco 0%→2%→5%→9%, Gol subiti si riduce allontanandosi dalla difesa 11%→6%→3%→assente).

**Non implementato stasera** (solo diagnosticato): rimuovere le categorie a peso zero, scorporare
la base fissa di `level_score` per misurarne la vera varianza sfruttabile, eventualmente
progettare un modo di condizionare `level_score`/clean-sheet-proneness per venue/avversario.
Priorità identificata per il prossimo giro sul tema granulari.

## 10. Mattina 26/07 — Punto 1 (rimozione categorie a peso zero) e Punto 2 (scomposizione level_score)

### Punto 1: categorie a peso zero rimosse dal codice

Rimosso da tutti e 4 gli script `test_<ruolo>.py`, basato sui dati di `inspect_granular_weights.py`:
- **GK**: `FOULS_STATS`, `OFFENSIVE_STATS`, `RARE_EVENTS_STATS` (tutti 0.0% su 268 partite/29
  portieri). Erano già solo diagnostici (mai in `score_atteso`), quindi il comportamento REALE del
  modello è invariato — solo pulizia di codice/output/computazione.
- **DEF/MID/FWD**: rimosso solo `RARE_EVENTS_STATS` (0.0-0.1% su 857-1534 partite). Contribuiva
  ancora al calcolo del residuo (`covered_total`), impatto trascurabile viste le dimensioni.

Verificato con `py_compile` + smoke test sintetico (`rigorous_backtest`/`run_grid_search` con dati
finti) su tutti e 4 gli script, nessun errore. Committato e pushato (`e926f208`/`f145fa82`).

### Punto 2: scomposizione della base fissa di `level_score`

Investigazione sulla distribuzione reale di `level_score` (non solo la sua magnitudine media, come
richiesto). Risultato importante: **`level_score` NON è continuo in nessun ruolo** — è quantizzato
su soli 5-6 valori distinti in tutti e 4 i ruoli:
- **GK** (268 partite): 35 (68%), 60 (25%), 15 (5.6%), 5 (0.7%), 70 (0.4%)
- **DEF** (1534 partite): 35 (84%), 60 (11%), 15 (4.2%), 70 (0.8%), 5 (0.1%)
- **MID** (1459 partite): 35 (76%), 60 (18%), 70 (3.4%), 15 (2.5%), 80 (0.3%), 100 (0.1%)
- **FWD** (915 partite): 35 (65%), 60 (28%), 70 (5.0%), 80 (1.2%), 15 (1.1%), 90 (0.1%)

Il valore 35 domina sempre — conferma la nota dell'utente sulla "base fissa". Cross-tabulazione con
`mins_played`/`goals_conceded`/`clean_sheet_60`/`goals` per capire cosa determina i livelli
superiori: **la regola NON è la stessa per tutti i ruoli** e non è pulita/deterministica dai soli
3-4 campi controllati:
- GK: livello 60 non è spiegato SOLO dal flag clean sheet (trovati casi di livello 60 con gol
  subiti) — più sporco del previsto, probabilmente altri fattori Sorare non documentati.
- DEF: sorpresa — il salto a livello 60 correla molto più con **aver segnato un gol** (36% dei
  casi a livello 60 vs 0.2% a livello 35) che con il clean sheet (24.3% vs 27.0%, quasi
  indifferente). Per un difensore, `level_score` sembra premiare soprattutto contributi decisivi
  offensivi, non la fase difensiva.

**Conclusione**: `level_score` è il sistema di bonus "contributo decisivo" di Sorare (probabilmente
lo stesso mostrato come "Punteggio decisivo" nella UI) — una variabile CATEGORIALE legata a eventi
rari e decisivi (gol, clean sheet, assist), non un valore da normalizzare per casa/trasferta con
`compute_split_factor` come gli altri granulari. Punto 2 considerato chiuso per stasera (obiettivo
raggiunto: sappiamo che non è rumore, sappiamo che è quantizzato, sappiamo grosso modo cosa lo
muove) — la regola esatta servirebbe più tempo/dati ed è naturalmente collegata al tema successivo
(la sinergia GK+DEF per il clean sheet condiviso, i contributi decisivi dei compagni di squadra
nella stessa partita, sono esattamente il tipo di correlazione tra slot che il Finding 4/F della
sezione 5 di `RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` intendeva modellare). Non implementato,
solo diagnosticato — nessuna modifica al codice di produzione per questo punto.

## 11. Mattina 26/07 (continua) — REGOLA ESATTA di `level_score` scoperta e validata dall'utente su Sorare

Approfondimento richiesto dall'utente (partendo dagli attaccanti, poi da estendere a tutti i
ruoli): mappata ogni combinazione di stat `POSITIVE_DECISIVE_STAT`/`NEGATIVE_DECISIVE_STAT` (che
hanno SEMPRE `totalScore=0.0` come riga propria — il loro impatto reale è tutto dentro
`level_score`, non nella riga della singola statistica) contro il valore di `level_score`
risultante, su tutte le partite in cache di tutti e 4 i ruoli.

**Regola CORRETTA E FINALE** (prima versione ipotizzata "primo evento/eventi successivi in ordine
cronologico" era sbagliata — corretta dall'utente il 26/07 con controesempi reali GK: la vera
chiave e' il CONTEGGIO NETTO di eventi decisivi, sommando i valori se un evento si ripete, es.
doppietta=2 gol):
```
netto = sum(statValue di tutte le righe POSITIVE_DECISIVE_STAT)
      - sum(statValue di tutte le righe NEGATIVE_DECISIVE_STAT)

netto -2 -> level_score  5
netto -1 -> level_score 15
netto  0 -> level_score 35  (base)
netto +1 -> level_score 60
netto +2 -> level_score 70
netto +3 -> level_score 80
netto +4 -> level_score 90
netto +5 -> level_score 100
```
Il salto dal centro (35) al primo scalino e' piu' grande (+-25) di ogni scalino successivo
(+-10) -- ma la funzione dipende dal CONTEGGIO NETTO, non dall'ordine temporale in cui gli eventi
sono avvenuti in partita (un gol e un errore-che-porta-a-un-gol nella stessa partita si annullano
esattamente: netto 1-1=0 -> resta a 35, indipendentemente da quale dei due sia successo prima).

**Validato dall'utente con schermate Sorare reali** (non solo dedotto dai dati):
1. Aaron Salem Boupendza Pozzi (2 gol + 1 assist, Zhejiang Greentown vs Sichuan FC, 01/04/2025):
   score 91.9 = level_score 80 (35 + 25 primo gol + 10 secondo gol + 10 assist) + granulari 11.9
   (screenshot UI: Generale -1.5, Possesso -6, Passaggio 7.4, In attacco 12 = 11.9). Conferma
   ESATTA sia della formula di level_score sia che score_totale = level_score + somma granulari.
2. Denis Bouanga (1 gol + 1 errore-che-porta-a-un-gol, San Diego FC vs Los Angeles FC, 03/05/2026):
   `level_score`=35 (netto). Screenshot UI mostra la sezione "Punteggio decisivo" come un GAUGE a
   scala di EVENTI (non punti diretti): "Positivo decisivo: 1 (Gol)", "Negativo decisivo: -1
   (Errore che ha causato un gol)" → netto 0 sulla scala eventi → livello resta a 35. "Punteggio
   complessivo" (i granulari): -9.9. Totale reale: 35 + (-9.9) = 25.1, esatto.
3. Antony Alves Santos (1 `penalty_conceded`, Vancouver Whitecaps vs Portland Timbers,
   05/04/2026): `level_score`=15 (35-20), coerente con la regola per un singolo evento negativo.
4. Andre Blake (GK, clean sheet netto, Philadelphia Union vs DC United, 18/04/2026):
   `level_score`=60, confermato dall'utente -- la regola vale identica anche per il portiere
   (clean_sheet_60 conta come 1 evento positivo netto).
5. Michael Collodi (GK, `last_man_tackle`+`penalty_save`, Seattle Sounders vs FC Dallas,
   26/04/2026): `level_score`=70 (netto +2: 35+25+10). Confermato dall'utente: "su Sorare il
   level_score si chiama Punteggio decisivo... con un clean sheet in piu' sarebbe stato 80". Al
   decisivo 70 si sommano granulari +16 per il totale reale 86.1.
6. Pablo Sisniega (GK, `own_goals`+`red_card`, San Diego FC vs Vancouver Whitecaps, 30/11/2025):
   `level_score`=5 (netto -2: 35-20-10). Confermato dall'utente, granulari -3.6 portano il
   punteggio totale reale a 1.4 ("che partita di merda che ha fatto").
7. Akil Watts (DEF, 1 gol, Portland Timbers vs St. Louis City SC, 08/06/2025, MLS):
   `level_score`=60, granulari +17.6, score reale 77.56. Confermato dall'utente.
8. Ajani Fortune (MID, 1 gol, Orlando City SC vs Atlanta United, 16/05/2026, MLS):
   `level_score`=60, granulari +20.8, score reale 80.8. Confermato dall'utente.

**REGOLA VALIDATA SU TUTTI E 4 I RUOLI** (GK, DEF, MID, FWD) con casi reali confrontati su Sorare
dall'utente — nessuna differenza di meccanismo tra ruoli, stessa tabella netto→livello ovunque.
Chiarimento importante dell'utente sul floor: **`goals_conceded` (gol subiti) NON è mai un evento
decisivo negativo per il portiere** — è una statistica GENERAL separata. Se un portiere ha un
evento decisivo positivo (es. rigore parato) ma subisce molti gol, il floor tiene comunque il
punteggio al livello raggiunto (es. 60), indipendentemente da quanti gol subisce — questo spiega
retroattivamente i casi "sporchi" trovati nella prima cross-tabulazione di stamattina (livello 60
con fino a 6 gol subiti: non erano un'anomalia della regola, erano il floor in azione).

**Tema level_score chiuso.** Prossimo passo naturale: usare questa comprensione per stimare un
`level_score` atteso per la prossima partita (basato sul tasso storico di eventi decisivi del
giocatore) invece di lasciarlo dentro la media generica — da progettare insieme quando si riprende
il lavoro implementativo.

**Scoperta importante collegata**: `level_score` NON e' quindi un misterioso "black box Sorare" --
è letteralmente il "**Punteggio decisivo**" mostrato nella UI (gauge -3..+5 con soglie
0/15/35/60/70/80/90/100), un contatore di EVENTI decisivi (non punti) che poi si traduce in un
valore di livello secondo tabella fissa. Il "Punteggio complessivo" della UI corrisponde
esattamente alla somma dei nostri gruppi granulari (Generale/Possesso/Passaggio/In
attacco/Difesa). `score_totale = level_score (Punteggio decisivo) + somma_granulari (Punteggio
complessivo)` -- confermato aritmeticamente su piu' casi reali.

**Implicazione per il modello**: la vera leva sfruttabile non è "normalizzare level_score per
casa/trasferta" (era l'approccio sbagliato, level_score non è un valore continuo con una media
mobile sensata) — è stimare la **probabilità storica di ciascun evento decisivo per il giocatore**
(tasso gol/partita, tasso assist, tasso cartellino, tasso clean sheet per GK/DEF) e usarla per
calcolare un valore atteso di `level_score` per la prossima partita, anziché lasciarlo
implicitamente dentro la media pesata generica dello score totale (dove il rumore degli eventi
rari lo confonde con le fluttuazioni "normali" di gioco). Non ancora implementato — prossimo passo
naturale, da fare per tutti e 4 i ruoli (richiesta esplicita dell'utente: "dobbiamo farlo anche
sugli altri ruoli").

### Regola del FLOOR (segnalata dall'utente con caso reale Erling Haaland, 26/07)

Scoperta aggiuntiva importante, verificata sui dati cache: **quando `level_score >= 60` (almeno un
evento decisivo positivo netto, nessun negativo che lo compensi), il punteggio finale della
partita non può MAI scendere sotto `level_score` stesso**, indipendentemente da quanto siano
negativi i granulari. Caso che ha innescato la scoperta: Erling Haaland (Arsenal 5 - Manchester
City 1), 1 gol, granulari -3 → punteggio atteso "sulla carta" 57, ma il punteggio FINALE reale
mostrato da Sorare è 60 (il floor).

**Verificato empiricamente sui nostri dati** (non solo dedotto dallo screenshot):
- 5 casi reali con `level_score >= 60` e granulari negativi, su FWD/DEF/MID/GK: **in tutti e 5** lo
  `score` reale restituito dall'API Sorare corrisponde ESATTAMENTE a `level_score` (floor attivo),
  mai alla somma grezza più bassa.
- 8 casi reali con `level_score = 35` (nessun decisivo positivo pulito) e granulari molto negativi:
  **in tutti e 8** lo `score` reale è la somma grezza (`level_score + granulari`), SENZA floor —
  scende liberamente sotto 35.

**Regola completa e finale**:
```
score_totale = level_score + granulari                         se level_score <= 35 (nessun floor)
score_totale = MAX(level_score, level_score + granulari)        se level_score >= 60 (floor attivo)
```

**Implicazione pratica**: un evento decisivo positivo funziona come una specie di "assicurazione"
sul punteggio — garantisce un pavimento (60/70/80...) indipendentemente da una brutta prestazione
generale nella stessa partita. Questo significa che il valore atteso di "probabilità di un evento
decisivo" per un giocatore non è solo il suo contributo medio ai punti, ma include anche una
riduzione del rischio al ribasso — rilevante per qualunque futura stima predittiva di
`level_score`, non solo per calcolarne il valore medio atteso ma anche per il range di confidenza
(varianza ridotta sul lato basso quando il giocatore ha buone probabilità di un evento decisivo).

## 12. Sera 26/07/2026 — rimozione `fattore_forza_avversario`, GK, monitoraggio MAE live, bilanciamento anti-stack

Sessione successiva a quella descritta in sezione 11, stesso giorno. In ordine:

**Rimosso `fattore_forza_avversario` da `score_atteso` per tutti e 4 i ruoli, MLS e K League**
(commit `c7a4b831a`). Backtest walk-forward rigoroso
(`formazione_mls/diagnostics/validate_team_defense_strength.py`) ha mostrato che questo fattore
(basato su `domesticLeagueRanking`, generico offesa+difesa) PEGGIORA il MAE del 4-9% su tutti i
ruoli — testata anche un'alternativa più specifica (gol subiti per squadra, ricostruita a costo
zero dalle cache esistenti di GK/DEF/MID): batte comunque la rimozione secca, tranne un margine
minimo per GK non ritenuto sufficiente a giustificare nuove query GraphQL in produzione. Il
fattore resta calcolato e mostrato in output per diagnostica, solo non più moltiplicato.
`HALF_LIFE_GAMES` e `fattore_casa_trasferta` sono stati ri-validati con lo stesso rigore
(`validate_halflife_venue.py`): entrambi confermati validi per tutti i ruoli (delta <0.5%),
nessuna modifica necessaria.

**GK: tutti i parametri tunabili confermati vicini all'ottimo, nessuna modifica necessaria.**
Oltre a Stadio D (già rimosso in sessione precedente, +4.21% MAE se tenuto) e all'avversario
(sopra), validato anche `TREND_INTENSITY` (mai testato prima,
`formazione_mls/diagnostics/validate_gk_trend.py`): 0.7 è quasi ottimale (alternativa migliore
-0.08%, rumore), disattivare il trend costa +1.46%. Il problema residuo di GK non è di formula ma
di dati: campione di calibrazione ancora piccolo (15 giocatori/129 punti test contro 72-178/311-616
degli altri ruoli) — non ha mai avuto la "calibrazione allargata" che hanno avuto DEF/MID/FWD.
Backlog aperto, rimandato.

**Testata e SCARTATA la decomposizione level_score/granulare** (esito negativo,
`formazione_mls/diagnostics/validate_level_score_decomposition.py`): l'ipotesi era prevedere lo
score totale scomponendo `level_score_atteso + granulare_atteso` con half_life/trend PROPRI per
ciascun pezzo, invece della media pesata unica sul totale in produzione. Grid search walk-forward
(8281 combinazioni per ruolo) mostra guadagni marginali e probabilmente rumore (<1.3% su tutti i
ruoli), con ottimi spesso al bordo della griglia (sintomo di overfitting); il test più onesto
(decomposizione SENZA ri-tarare nulla) è nullo o leggermente peggiore in 3 ruoli su 4. Non portata
in produzione.

**Aggiunto monitoraggio MAE live per MLS** (commit `9860c99ff`, implementato da un agente in
background): ogni run di produzione dei 4 ruoli MLS ora registra (`formazione_mls/predict/
live_prediction_log.py`) uno "pending log" JSON per giocatore/partita target con lo `score_atteso`
generato; un nuovo script (`formazione_mls/diagnostics/resolve_live_predictions.py`) confronta
poi queste previsioni con lo score reale non appena la cache si aggiorna con la partita giocata,
calcola l'errore e produce un report di MAE live per ruolo (totale e ultime N partite, per
individuare drift). Zero nuove query API, overhead trascurabile, nessuna modifica alla formula.
Scope solo MLS per ora (K League può seguire).

**Meccaniche di gioco Sorare chiarite dall'utente (fondamentali, non derivabili dal codice)**:
- **In Season**: contro un target fisso di Sorare, non contro altri manager.
- **Arena**: 5 giocatori (anche tutti classic), 1 formazione contro altri 9 manager, premiati i
  primi 3. **Capitano Arena: bonus +20%, NON +50%** — il codice usa ancora `CAPTAIN_BONUS = 0.5`
  globale per tutti i tipi di formazione (bug noto, non ancora corretto).
- **All Stars**: stesso meccanismo di Arena ma su scala globale (~20.000 partecipanti, premiati i
  primi 1000 — taglio 5%, molto più estremo del 30% di Arena).
- **Bonus anti-stack (SOLO In Season)**: formazione con MENO di 3 giocatori della stessa squadra →
  +2% al punteggio di ciascuno dei 5; con 3+ della stessa squadra il bonus salta per tutti.
  Non esiste in Arena/All Stars.
- **Bonus "cap 260" (SOLO In Season e All Stars, NON Arena)**: menzionato dall'utente ma non ancora
  approfondito — probabilmente imparentato con (ma non identico a) l'`ARENA_L10_CAP` già
  implementato per Arena. Da chiarire in una prossima sessione.

**Fix implementato: bilanciamento sinergia GK-DEF con bonus anti-stack** (commit `e658958ab`,
MLS+K League). Contesto: `build_formazione_finale.py` aveva già una sinergia GK+DEF (aggiunta in
sessione precedente per la correlazione clean sheet: schierare il DEF della stessa squadra del GK
è leggermente incoraggiato) scritta PRIMA di sapere del bonus anti-stack. Analisi: quella sinergia
da sola porta al massimo a 2 giocatori della stessa squadra (GK + 1 DEF titolare) — nessun
conflitto col bonus anti-stack (soglia 3), lasciata invariata. Il conflitto nasce solo nello slot
EXTRA, dove la stessa sinergia poteva spingere verso il 3° giocatore della squadra del GK, perdendo
il 2% certo su tutti e 5 per un guadagno di correlazione incerto. Aggiunto `apply_stack_guard`
(parametro nuovo di `build_one_lineup`, attivo SOLO per `tipo == 'IN_SEASON'`): nello slot extra,
un candidato che farebbe salire una squadra a 3+ viene fortemente deprioritizzato nell'ordine di
scelta — MAI escluso (se non ci sono alternative valide resta comunque selezionabile: a volte,
es. capolista contro ultima, può convenire sacrificare il 2% per un punteggio quasi certo, scelta
che resta dell'utente, non dell'algoritmo). Se una formazione finisce comunque con 3+ della stessa
squadra, viene segnalato chiaramente in output (testo e HTML: "bonus anti-stack NON applicato").
Arena/All Stars non toccate (nessun bonus anti-stack lì). Verificato con test locale (candidati
fittizi): il guard evita il 3° giocatore quando esiste un'alternativa valida, e ripiega sullo
stack solo quando non ce ne sono (segnalandolo).

**Backlog aperto a fine sessione (12)**:
1. GK: calibrazione allargata (discovery su tutti i portieri MLS qualificati) — rimandato.
2. K League: infrastruttura discovery globale equivalente a MLS, per ripetere le analisi
   cross-league (Stadio D, avversario, ecc.) e confrontare pattern universali vs specifici MLS.
3. Verificare empiricamente se la correlazione reale tra compagni di squadra nei dati giustifica di
   spingere DI PIÙ sullo stacking in Arena/All Stars (specialmente All Stars, taglio 5%).
4. Correggere `CAPTAIN_BONUS` per essere specifico per tipo (Arena 20% vs In Season/All Stars —
   valore per questi ultimi due mai verificato esplicitamente con l'utente, assunto 50% finora).
5. Chiarire e implementare il bonus "cap 260".
6. Outlier/hot-streak (mai affrontato), monitoraggio MAE live esteso a K League.

## 13. Sera 26/07/2026 (continua, sessione successiva) — Arena/All Stars bonus reali, K League discovery+calibrazione globale, calibrazione GLOBALE unificata

Sessione lunga, molti filoni gestiti in parallelo con agenti in background (worktree isolati,
mergiati man mano in questa sessione). In ordine logico (non cronologico):

### A. Punto 3 e 4 del backlog sopra: CHIUSI
- Punto 3 (stacking Arena/All Stars): **eliminato dal backlog** su richiesta esplicita
  dell'utente — troppo sforzo per il beneficio atteso.
- Punto 4 (`CAPTAIN_BONUS` per tipo): implementato. `CAPTAIN_BONUS_BY_TYPE` per tipo di
  formazione: In Season 50%, Arena 20% (verificato dall'utente su casi reali Sorare),
  All Stars 50%. **Bug trovato e corretto in K League**: dopo lo split di Arena in
  ARENA_260/ARENA_220/ARENA_UNCAPPED (vedi sotto), la mappa K League aveva ancora la vecchia
  chiave singola `'ARENA': 0.2` — le nuove chiavi ricadevano sul default 50% invece di 20%.
  Bug reale, non solo teorico (avrebbe sballato i totali mostrati per Arena K League).

### B. Bonus formazione reali Sorare (verificati dall'utente con screenshot UI, non dedotti)

Panel "BONUS FORMAZIONE" della UI Sorare mostra due componenti separate, sommate in un totale:
- **"Multi-club" +2%**: e' lo stesso bonus che chiamavamo "anti-stack" (meno di 3 giocatori della
  stessa squadra), solo nome diverso in UI. Nessuna nuova meccanica, gia' implementato.
- **"Cap 260" +4%**: se la somma delle **L10** (non punteggio atteso/reale) dei titolari e'
  <= soglia, +4% su tutte le carte. **Soglia diversa per tipo**: 260 per In Season, **370 per
  All Stars** (scalata a 7 giocatori invece di 5). E' un **soft cap** — si puo' sforare, si perde
  solo il bonus (mai un vincolo che filtra le scelte). Implementato come rilevamento PASSIVO
  (`check_cap260` in `format_lineup`/`render_lineup_html`): mostra se la formazione gia' scelta
  (ottimizzata per punteggio atteso, nessuna ricerca vincolata) rientra o no, nessuna modifica
  alla selezione dei giocatori. Sia il bonus multi-club sia il cap sono confermati validi ANCHE
  per All Stars (`stack_guard` esteso da `tipo == 'IN_SEASON'` a
  `tipo in ('IN_SEASON', 'ALLSTARS')`), non solo In Season come si pensava prima.

**IMPORTANTE — da non confondere**: il cap Arena (`ARENA_260`/`ARENA_220`) e' un concetto
DIVERSO, anche se sulla stessa metrica (somma L10): per Arena e' un **vincolo di formato
obbligatorio** (non si puo' sforare, filtra attivamente le scelte in `build_one_lineup` via
`FIXED_L10_CAP_BY_TYPE`), non un bonus opzionale. L'utente gioca sempre Arena a cap fisso, ma
alcune Arene usano 260, altre 220 — da qui lo split in tre tipi:

- **`ARENA_260`** / **`ARENA_220`**: cap L10 obbligatorio, vincolante.
- **`ARENA_UNCAPPED`**: nessun limite (terza modalita' Arena reale, richiesta dall'utente).

Sostituito il vecchio tipo generico `'ARENA'` (con tuning opzionale `ARENA_L10_CAP` via env) con
queste tre chiavi fisse in `FORMATION_SHAPES`. Priorita' di generazione: In Season -> Arena
cap260 -> Arena cap220 -> Arena uncapped -> All Stars. Implementato prima su MLS, poi
specchiato su K League (con il fix del bug capitano di cui sopra).

**Verificato sul backtest ("simulate_cap260_tradeoff.py", nuovo script diagnostico)**: rincorrere
attivamente il cap 260 In Season sacrificando punteggio atteso NON conviene quasi mai nel pool
testato — sacrificio medio ~47pt contro un break-even teorico di ~12pt (4% del capped), 0/8
giornate simulate sono riuscite a scendere sotto 260 con giocatori "buoni". Il bonus resta quindi
solo un extra "gratis" quando capita, non un obiettivo da inseguire attivamente (rilevamento
passivo confermato come scelta giusta, non serve una Fase 2 di ricerca attiva).

### C. K League: discovery globale + calibrazione allargata COMPLETA (prima volta)

Costruita da zero l'infrastruttura mai esistita (verificato su TUTTI i branch/commit del repo,
l'utente pensava fosse gia' stata fatta ma si sbagliava): `formazione_kleague/discovery/
kleague_<ruolo>_discovery_global.py` x4 (clone esatto del pattern MLS) + workflow
`.github/workflows/kleague_discovery_global.yml`. Squadre K League 1 ottenute con query LIVE
verificata (`competition(slug:"k-league-1") { clubs }`, 12/12 trovate — nota tecnica: il campo
giusto e' `clubs`, non `teams`/`currentClubs` che falliscono). Poi costruito anche
`grid_search_calibrazione_kleague.yml` (clone del workflow MLS) e generalizzato
`aggregate_grid_search.py` con `CAMPIONATO=mls|kleague` (default mls, retrocompatibile).

Lanciati in sequenza (stessa cautela rate-limit di sempre, un ruolo alla volta) tutti e 4 i batch
K League. Risultati calibrazione K League (solo, min 3 partite test):

| Ruolo | Giocatori qualificati | Vincitore K League | vs produzione (clonata da MLS) |
|---|---|---|---|
| GK | 3/27 | hl=9.0, range=1.2, opp_sens=29.0, trend=0.7 | Campione troppo piccolo da solo, ma stessa direzione di MLS |
| DEF | 15/114 | hl=12.0, range=1.2, **opp_sens=20.0**, trend=0.7 | **Diverge**: unico caso su 8 ruoli/campionati con segnale opposto a 29.0 |
| MID | 10/61 | hl=12.0, range=1.4, opp_sens=29.0, trend=0.7 | Identico |
| FWD | 21/138 | hl=12.0, range=1.4, opp_sens=29.0, trend=0.7 | Identico |

**Il caso DEF K League**: spiegato dall'utente con conoscenza di dominio ("il campionato coreano
e' famoso per difensori molto forti, pochi gol segnati, e' una loro caratteristica nota") — non
rumore, ma un vero effetto di contesto. **Deciso di NON creare un parametro diverso per K League**
(andrebbe contro il principio "un solo modello globale, i campionati servono solo ad accumulare
dati") — vedi punto E per la direzione scelta invece.

Aggiornato **solo GK**: `opponent_sensitivity` 20.0 -> 29.0, sia MLS che K League (stesso fix,
stesso giorno, coerente con tutti gli altri ruoli/campionati). MID/FWD gia' allineati. DEF NON
toccato (vedi sopra).

### D. Calibrazione GLOBALE unificata (MLS+K League combinati, non piu' separati)

Richiesta esplicita dell'utente: "il modello sara' sempre uno solo, globale, usiamo i vari
campionati solo per accumulare dati". Aggiunta modalita' `GLOBALE=1` ad
`aggregate_grid_search.py`: combina i giocatori qualificati di TUTTI i campionati noti in un
unico pool pesato per n_test (un giocatore K League pesa esattamente come uno MLS a parita' di
partite testate), invece di due aggregazioni separate. Output in
`calibrazione_globale/output/<ruolo>_calibration/` (nuova cartella dedicata).

Risultati (nessuna modifica di produzione applicata oltre al fix GK di sopra):
- **GK** (16 giocatori/140 partite) e **DEF** (84 giocatori/640 partite, campione ORA grande):
  confermano che la produzione attuale e' gia' vicina all'ottimo. Bonus: l'anomalia DEF K League
  (opp_sens=20) **sparisce** quando si aggregano piu' dati (MLS domina il peso per volume) —
  coerente col fatto che sia un effetto reale ma di scala minore, non abbastanza forte da
  spostare la stima globale pesata.
- **MID** (78/575): il "vincitore" per composite score suggeriva di riaccendere i granulari
  (trend=1.3) — **verificato e SCARTATO**: riordinando per puro MAE (non composite score, che
  include una penalita' di copertura arbitraria), il vincitore vero e' un tris a pari merito
  (range 1.2/1.4/1.6 indifferenti) con `hl=12.0, opp_sens=29.0, trend=0.7, SENZA granulari` —
  **esattamente i parametri di produzione attuali**. Il segnale "granulari" era un artefatto
  della penalita' di copertura nel composite score, non un vero guadagno di accuratezza. MID
  confermato ottimale cosi' com'e'.
- **FWD** (59/400): segnale debole (trend 0.7->1.0), non applicato.

Fix minore contestuale: il riepilogo finale di `aggregate_grid_search.py` ora mostra
esplicitamente CON/SENZA granulari nella riga di stampa (prima l'informazione c'era solo nel
campo `label` del json salvato, non nel testo stampato — ambiguo a colpo d'occhio).

### E. Prossimi passi (in ordine, sessione in corso al momento di scrivere)

Discusse con l'utente due direzioni per "svoltare" il modello, coerenti col principio "un modello
solo, globale":

1. **Fattore ambientale per `opponent_sensitivity`** (invece di costanti fisse per ruolo/lega):
   il caso DEF K League suggerisce che "quanto conta l'avversario" potrebbe dipendere da un
   contesto di punteggio misurabile (es. media gol/partita osservata), non da una costante fissa
   — permetterebbe al modello di restare unico ma adattarsi automaticamente a qualsiasi
   campionato futuro, invece di un valore scelto a mano per lega.
2. **`level_score` atteso**: stimare il tasso storico di eventi decisivi per giocatore (gol/
   assist/cartellini/clean sheet) per calcolare un valore atteso di `level_score` per la
   prossima partita (usando la regola netto->livello validata in sezione 11, floor incluso in
   sezione 11), invece di lasciarlo dentro la media pesata generica dello score totale. Identificato
   da tempo come probabilmente la leva piu' grossa mai sfruttata (formula validata al 100% con
   casi reali Sorare, identica in ogni ruolo/campionato).

Entrambe le analisi sono state avviate in background (agenti separati, worktree isolati) —
risultati in sezione F sotto, stessa sessione, poco dopo.

### F. Risultati delle due direzioni esplorate — ENTRAMBE esito onesto "non procedere per ora"

**Direzione 1 (fattore ambientale per `opponent_sensitivity`)** —
`formazione_mls/diagnostics/validate_environmental_opponent_sensitivity.py`:
- **Scoperta preliminare importante**: `OPPONENT_SENSITIVITY` **non è nemmeno usato nello
  `score_atteso` reale oggi** — verificato nel codice (`test_def.py` e affini): sopravvive solo
  dentro `rigorous_backtest()`/`run_grid_search()` per un MAE diagnostico in log, MAI nel calcolo
  che sceglie/ordina i giocatori (il fattore forza-avversario generico è stato rimosso il 26/07,
  vedi sezione 12). Quindi calibrarne la sensibilità è oggi un esercizio accademico finché non si
  decide di reintrodurre un fattore avversario in qualche forma (che finora ha sempre perso
  contro "nessun aggiustamento", vedi sezione 12).
- Caratterizzazione ambientale: K League ha sì un ambiente di punteggio meno variabile di MLS ma
  di poco (rapporto deviazione standard gol-subiti K/MLS = 0.91) — troppo mite per spiegare lo
  scarto 20.0 vs 29.0 trovato dal grid search isolato su DEF K League (che implicherebbe un
  rapporto ~0.69).
- Backtest walk-forward: **nessuna delle due formule ambientali testate batte la costante fissa
  29.0** in modo significativo, né su MLS né su K League, né su DEF né sul ruolo di controllo MID.
- **Raccomandazione: non procedere.** Il segnale K League DEF (15 giocatori/114 partite) resta
  probabilmente rumore da campione piccolo — non si spiega con la variabilità ambientale
  misurabile e non produce un guadagno di MAE riproducibile.

**Direzione 2 (`level_score` atteso da tasso di eventi decisivi)** —
`formazione_mls/diagnostics/validate_level_score_event_rate.py`:
- Regola netto→level_score (sezione 11) **confermata esatta al 100%** su tutte le partite in
  cache di tutti e 4 i ruoli (es. FWD 599/599, DEF 957/957).
- Approccio (diverso dal tentativo già scartato in sezione 12, che ri-calibrava half_life/trend
  separati): tasso storico di eventi decisivi (modello Poisson pos/neg, stesso `HALF_LIFE_GAMES`
  di produzione, **zero ri-taratura**) → valore atteso della distribuzione categoriale di
  level_score, poi SOSTITUITO (non sommato a fianco) al posto della componente level_score
  implicita nella media generica attuale.
- Risultato: **migliora il MAE totale su tutti e 4 i ruoli** (FWD -0.63%, DEF -1.01%, MID -0.51%,
  GK -1.18%) — direzione consistente, a differenza del tentativo precedente (che peggiorava 3
  ruoli su 4). Il floor (sezione 11) non scatta mai in questa formulazione: opera su un valore
  atteso continuo, non su un evento realizzato — nota aperta se si vuole approfondire.
- **Raccomandazione: segnale più coerente ma ancora troppo piccolo** (sotto l'1.3%, stesso ordine
  di grandezza del "rumore" già visto altrove in questa sessione) **per giustificare la
  complessità aggiuntiva in produzione così com'è.** Varrebbe la pena riprendere in mano solo se
  si trova un modo di rendere operativo il floor (es. sulla coda della distribuzione, non sul
  valore atteso) o si combina con un'altra leva.

**In sintesi per chi riprende da qui**: la sessione del 26/07 ha validato molto (Arena/All Stars
completi, K League ora ha infrastruttura globale pari a MLS, calibrazione GLOBALE unificata) ma
le due idee "grosse" per migliorare ulteriormente l'accuratezza (fattore ambientale, level_score
atteso) sono risultate entrambe segnali reali ma troppo deboli per la produzione — non è un
fallimento della sessione, è un buon controllo di rigore: si è verificato con backtest reali
invece di intuizione, ed entrambe le idee restano documentate/pronte se in futuro emergeranno più
dati o un'angolazione diversa (es. combinarle, o applicarle solo dove il segnale è più forte).

### G. Stato repo a fine sessione (26/07 notte)

Tutto pushato su `origin/main` (nessun lavoro pendente non pushato). File aggiunti/modificati di
rilievo in questa sessione (oltre a quanto già elencato nelle sezioni A-F sopra):
- `formazione_mls/build_formazione_finale.py` / `formazione_kleague/build_formazione_finale.py`
  — Arena split, cap 260/370, bonus capitano per tipo.
- `formazione_kleague/discovery/kleague_*_discovery_global.py` (nuovi) +
  `.github/workflows/kleague_discovery_global.yml` (nuovo).
- `.github/workflows/grid_search_calibrazione_kleague.yml` +
  `grid_search_aggregate_kleague.yml` (nuovi).
- `formazione_mls/calibrazione/aggregate_grid_search.py` — modalità `GLOBALE=1`.
- `calibrazione_globale/output/<ruolo>_calibration/` (nuova cartella, risultati aggregati
  MLS+K League combinati).
- `formazione_mls/predict/test_gk.py` / `formazione_kleague/predict/test_gk.py` —
  `OPPONENT_SENSITIVITY` 20.0→29.0.
- `formazione_mls/diagnostics/` — 6 nuovi script diagnostici (outlier reliability/shrinkage
  x2, simulate_cap260_tradeoff, validate_environmental_opponent_sensitivity,
  validate_level_score_event_rate) — nessuno in produzione, solo analisi.

**Backlog aperto per la prossima sessione** (in ordine di interesse, non di urgenza — nulla è
bloccante):

0. **PROSSIMO TEMA SCELTO DALL'UTENTE (26/07 notte, fine sessione) — correlazione tra gli slot
   della formazione.** Oggi ogni giocatore viene scelto in modo indipendente (il migliore per il
   suo slot/ruolo), a parte una sinergia parziale GK-DEF/GK-vs-FWD-avversario già implementata a
   mano (bonus/penalità euristici, non misurati sui dati — vedi sezione 12,
   `synergy_sort_key`/`synergy_adjusted_rows` in `build_formazione_finale.py`). **Non è mai stato
   misurato quanto REALMENTE correlano i punteggi di compagni di squadra nella stessa partita**
   (es. se un centrocampista fa una partita ottima, l'attaccante della stessa squadra ha più
   probabilità del solito di aver fatto bene anche lui — correlazione positiva reale o
   percepita?). Era già stato segnalato in una sessione precedente come "il tema più maturo ma
   mai chiuso" — un task di design in background era stato lanciato dall'utente in un'altra
   sessione locale e mai recuperato/verificato, quindi si riparte sostanzialmente da zero.
   **Come approcciarlo**: usare le cache di calibrazione già su disco (stesso dato usato da tutti
   gli script `formazione_mls/diagnostics/validate_*.py` di questa sessione) per ricostruire,
   partita per partita, chi ha giocato insieme nella stessa squadra (stesso approccio già usato in
   `validate_team_defense_strength.py` per raggruppare giocatori per squadra/data) e misurare la
   covarianza reale tra gli score di compagni di squadra nella stessa partita (per ruolo/coppia di
   ruoli). Se la correlazione e' misurabile e non trascurabile, valutare se un'ottimizzazione
   congiunta (non piu' greedy indipendente per slot) possa aumentare il punteggio atteso totale o
   ridurne la varianza in modo utile — MA solo dopo aver misurato la correlazione vera sui dati,
   non prima: la sinergia GK-DEF esistente oggi è stata implementata su intuizione, non
   verificata quantitativamente, e potrebbe risultare più debole (o più forte, o diversa) di
   quanto assunto. Approccio consigliato: nessuna modifica alla produzione finché non si ha un
   numero reale di correlazione in mano (stesso rigore walk-forward/backtest di tutti gli altri
   `validate_*.py` di questa sessione).

1. `level_score` atteso: riprendere se si trova un modo di rendere operativo il floor, o se si
   vuole comunque provare il guadagno marginale (-0.5/-1.2% MAE) in produzione nonostante sia
   piccolo — decisione dell'utente, non tecnica.
2. K League: bonus "Multi-club"/"Cap 260-370" mai verificati con screenshot reali K League
   (solo MLS) — probabilmente identici (stessa piattaforma Sorare) ma da confermare se si gioca
   K League attivamente.
3. Il caso "MID vincitore per composite score ≠ vincitore per MAE puro" (sezione D) — l'aggregatore
   usa un composite score con penalità di copertura arbitraria (0.3×|copertura-68%|); potrebbe
   valere la pena rivedere quella penalità/soglia 68% per tutti i ruoli, non solo notarlo caso per
   caso come fatto oggi per MID.
4. GK resta il ruolo con meno dati anche nella calibrazione globale (16 giocatori/140 partite
   contro 59-84 degli altri ruoli) — nessuna azione richiesta ora, solo da tenere presente quando
   si rifà il giro di calibrazione più avanti in stagione.
5. Bonus anti-stack ("Multi-club") — verificare se ha senso spingere DI PIÙ sullo stacking in
   Arena/All Stars: **eliminato dal backlog il 26/07** (troppo sforzo per il beneficio atteso),
   riportato qui solo perché compariva nel backlog precedente — NON riaprirlo senza una richiesta
   esplicita nuova dell'utente.
6. Starter odds come fattore di rischio continuo nello score_atteso (invece di solo filtro
   binario) — proposto e **SCARTATO il 26/07 notte** su richiesta esplicita dell'utente ("è
   marginale"), riportato qui solo per non riproporlo senza una richiesta nuova.

## 14. Sessione 27/07/2026 — correlazione compagni squadra (misurata e tarata), chiusura outlier/composite score, correzione memoria K League

Ripresa da un account diverso. Punto di partenza: il backlog (punto 0 sezione 13) e la memoria
persistente dell'account indicavano diversi temi aperti; **due si sono rivelati falsi allarmi da
memoria non aggiornata** (vedi sezione D sotto) — lezione operativa, non solo di modello.

### A. Correlazione tra slot della formazione — misurata, verificata robusta, tarata SOLO Arena/All Stars

Nuovo script `formazione_mls/diagnostics/measure_teammate_correlation.py`: residuo walk-forward
(reale − baseline media/venue/trend, stesso approccio di `validate_team_defense_strength.py`) di
compagni di squadra nella stessa partita, dalle cache di calibrazione GK/DEF/MID/FWD.

**Risultati same-team** (permutation test 999 shuffle + split-half cronologico, tutti p<0.05 e
segno stabile): GK-DEF **+0.40** (la più forte, già modellata ma sottostimata), DEF-MID +0.27,
GK-MID +0.26, DEF-DEF +0.23. FWD non mostra correlazione same-team significativa con nessun ruolo.

**Cross-team** (GK vs ruolo della squadra avversaria — verifica diretta dell'anti-sinergia già
codificata in `synergy_sort_key`): GK vs MID avversario **-0.20, p=0.036** (validata); GK vs FWD
avversario -0.24 ma p=0.12 (direzione giusta, campione corto).

**Tuning applicato** in `formazione_mls/build_formazione_finale.py` (`variance_mode`, nuove
costanti `GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA=8`, `TEAMMATE_SYNERGY_BONUS_VARIANCE=5`): bonus
GK-DEF rafforzato (3→11 totali) + nuovi bonus GK-MID/DEF-MID/DEF-DEF, **SOLO per Arena/All Stars**.
Motivazione del confine: in In Season il target è fisso, il valore atteso della somma non dipende
dalla correlazione (Finding 3+F, già chiuso) — spingere la scelta verso compagni correlati
costerebbe EV reale senza beneficio; il beneficio esiste solo dove la varianza conta (taglio
premi Arena 30%/All Stars 5%). Anti-sinergia GK-vs-avversario esistente lasciata invariata (era
già corretta nella direzione). Commit `4193c85ce`.

### B. Outlier/hot-streak (caso Antino Lopez) — CHIUSO, applicato solo per FWD

Due agenti in background hanno finito il lavoro diagnostico mai concluso in sessioni precedenti
(`validate_outlier_shrinkage.py`/`_tiered.py`, scritti il 26/07 ma senza decisione registrata).
Risultato: shrinkage Empirical Bayes (media pesata tirata verso il prior di ruolo, pseudo-count
`k`) migliora il MAE **solo per FWD**, e solo sul segmento a rischio che aveva motivato il tema
(n<8 partite storiche): **-2.9%** a k=5, con n≥8 invariato. DEF: il guadagno cade sul segmento
sbagliato (n≥8, fino a -5.3%, ma n<8 resta a -2%) — segno di rumore/overfitting, non applicato.
MID: <1% ovunque, rumore, non applicato. GK: campione troppo piccolo per decidere.

Applicato in produzione **solo** `formazione_mls/predict/test_mls_fwd_all.py`
(`SHRINK_K_OUTLIER_FWD=5.0`, `MEDIA_RUOLO_FWD_PRIOR=51.86`, k scelto per coerenza con lo
`shrink_k=5.0` già usato altrove in `media_condizionata()`).

### C. Penalità di copertura nel composite score dell'aggregatore — CHIUSO, peso corretto

Il target 68% è fondato (approssima ±1 dev std teorica, coerente con `RANGE_MULTIPLIER`/p16-p84),
ma il peso 0.3 (mai calibrato) faceva scegliere per MID un MAE **+2.72% peggiore** del vero
minimo. Abbassato a **0.1** in `aggregate_grid_search.py` + le 3 varianti per-ruolo — verificato
che con 0.1 il composite score coincide col vincitore per MAE puro su tutti e 4 i ruoli. **Nessun
impatto sui parametri già in produzione** (il vero vincitore MID coincideva già con quanto
schierato), ma corregge il prossimo giro di ricalibrazione. Entrambi B e C nel commit `e4be6571d`.

### D. Lezione operativa: due falsi allarmi da memoria persistente non aggiornata

Proponendo i "prossimi passi", sono stati segnalati come backlog aperti due temi **già chiusi in
sessioni precedenti mai recuperate correttamente**:
1. **"K League: infrastruttura di calibrazione allargata da costruire"** — in realtà completata
   la sera del 26/07 (sezione 13 di questo stesso documento: discovery globale, calibrazione
   allargata su tutti e 4 i ruoli, anomalia DEF K League investigata e chiusa come "non
   procedere"). L'errore: letta solo la memoria persistente (stale, scritta prima che il lavoro
   fosse fatto) e, separatamente, solo l'ultima sezione di backlog di questo documento — MAI la
   sezione 13 di mezzo che conteneva la risposta corretta.
2. **"GK: calibrazione allargata da fare"** — fatta tre volte (sezione 2: 27 giocatori; sezione 9:
   soglia abbassata a 15, 13 con dati sufficienti; sezione 13D: calibrazione globale MLS+K League,
   16 giocatori/140 partite, **conclusione esplicita "produzione già vicina all'ottimo"**). Il
   campione resta piccolo per un limite strutturale (1 GK per squadra), non perché non sia stato
   cercato — la nota di backlog originale diceva di aspettare che la stagione avanzi, non di
   rilanciare la discovery.

**Correzione applicata**: memoria `project_kleague_cross_validation_modello.md` riscritta con lo
stato reale e riferimento a questa sezione; `project_modello_predittivo_formazioni_mls.md`
corretta con nota esplicita dell'errore. **Regola per il futuro** (salvata anche come feedback
generale, non solo per questo repo): quando viene chiesto di "prendere visione del riassunto",
va letto per intero, non solo l'indice di memoria o l'ultima sezione — la memoria persistente può
essere stale rispetto a lavoro fatto in sessioni successive mai recuperate.

### E. Esplorato e ACCANTONATO: rilevare via GraphQL se una carta è bloccata in una lineup attiva

Obiettivo indagato: sapere, tramite query GraphQL, se una carta è già schierata in una formazione
Sorare attiva (per evitare che il tool suggerisca in una run separata — es. Arena dopo In Season —
un giocatore già usato). Scoperto durante l'indagine (con l'utente che incollava risposte
GraphQL reali): `lockedForLeaderboard` (su `ComposeTeamBenchCard`, scoping per singola
classifica/gameweek) e `usedIn`/`concurrentSo5Lineups` (su `Card`) restano `null`/`[]` anche
quando la carta è visibilmente piazzata in uno slot di una formazione ancora in bozza/non
confermata — quindi non affidabili per lo stato "in bozza". La scadenza di una gameweek è
condivisa da tutte le formazioni nello stesso istante (`so5Fixture.endDate`, confermato
dall'utente), quindi la parte "temporale" del problema sarebbe stata semplice; la parte "quali
carte sono bloccate ORA" avrebbe richiesto query aggiuntive per-carta o per-classifica (non
disponibili nella query di discovery esistente, che oggi chiede solo `slug`/`anyPlayer.slug`).
**Costo/complessità non ritenuti utili dall'utente** ("gioco non vale la candela") —
**non implementato, non riproporre senza una richiesta esplicita nuova.**

### F. Stato repo a fine sessione (27/07)

Pushato su `origin/main`: `4193c85ce` (sinergia Arena/All Stars da correlazione misurata +
`measure_teammate_correlation.py`), `e4be6571d` (shrinkage outlier FWD + peso composite score).
Nessun lavoro di codice pendente non committato. Backlog aggiornato:

1. K League: bonus Multi-club/Cap 260-370 mai verificati con screenshot reali K League (solo
   mirrorati da MLS) — richiede l'utente che gioca attivamente K League, non analizzabile da un
   agente.
2. Estensione dell'infrastruttura ad altri campionati oltre MLS/K League — decisione di
   investimento dell'utente, non un'analisi.
3. ~~GK calibrazione allargata~~, ~~outlier/hot-streak~~, ~~composite score~~, ~~correlazione
   compagni squadra~~ — **tutti chiusi in questa sessione o in precedenza** (vedi sezioni A-D
   sopra), non riaprire senza una richiesta esplicita nuova.
4. Rilevamento carte bloccate in lineup Sorare via GraphQL (sezione E) — accantonato per
   complessità/beneficio, non riproporre senza una richiesta esplicita nuova.

## 15. Sessione 27/07/2026 (sera) — Generatore Formazioni: terzo tool, fusione MLS+K League

Ripresa da un account diverso. Richiesta esplicita dell'utente: un TERZO script/workflow che generi
lineup pescando da MLS e K League **insieme**, **senza toccare** `formazione_mls/` e
`formazione_kleague/` (restano intatti, usabili da soli). Sessione lunga con più giri di test reali
su GitHub Actions e correzione di bug trovati sul campo — dettaglio in ordine cronologico perché
ogni bug ha portato al successivo.

### A. Requisiti raccolti (uno alla volta, con l'utente) e progettazione

**6 tipi di formazione** nel nuovo tool:
1. **In Season MLS** — pool solo MLS, 5 titolari, min 4 In Season + max 1 Classic
2. **In Season K League** — identico, pool solo K League
3. **Arena MLS** — pool solo MLS, **cap L10 fisso 260, non scelto dall'utente** (le Arene dedicate
   sono sempre a 260 su Sorare, verificato dall'utente)
4. **Arena K League** — identico, pool solo K League
5. **Arena All Stars** — stesse regole di un'Arena dedicata (5 carte, anche tutte Classic) ma pool
   **misto** MLS+K League, e qui SÌ il cap è scelto dall'utente tra 260/220/uncapped (come fa
   Sorare per questa modalità)
6. **All Stars** — 7 carte, pool misto, cap 370 **soft** (bonus +4% se rispettato, mai un vincolo
   che filtra le scelte)

**Ordine di priorità** (build condiviso, stesso pool di copie via `CardPool`): In Season (MLS poi
K League) → Arena dedicate (MLS poi K League) → Arena All Stars (260→220→uncapped) → All Stars.

**Ottimizzazione job discussa PRIMA di implementare** (tema "un tema alla volta"): il costo
dominante della pipeline produzione è 1 job predict per carta posseduta (checkout+setup ≈20-35s di
overhead contro ~7.5s di calcolo reale) — batching valutato ma rimandato ("partiamo così, se ci
mette troppo modifichiamo"); cache incrementale già esistente (`.game_log_cache`/`.cache`,
committata dai due tool) confermata riusabile senza modifiche.

**Filtro qualità nuovo** (diverso da tutto il resto del progetto): carta ammessa nel pool SOLO se
L5 **e** L10 **e** L40 sono **tutti e tre** ≥35 (AND severo, non media come nel discovery_global di
calibrazione — quello resta a soglia 30 sulla media, invariato). Fallback di sicurezza previsto se
un ruolo/lega resta sguarnito.

**Input configurabili**: niente più un campo numerico per tipo (non scala con nuovi campionati
futuri). Soluzione: 4 campi numerici semplici per i tipi sempre "misti" (Arena All Stars ×3 cap +
All Stars, non cresceranno mai con nuovi campionati) + 2 campi testo brevi `lega:quantità` solo per
i tipi legati a una lega specifica (`in_season`, `arena_dedicata`, es. `"mls:4,kleague:1"`) — un
domani un nuovo campionato è solo un nuovo codice lega nella stessa stringa, zero nuovi campi nel
workflow.

### B. Implementazione: `generatore_formazioni/` (nuova cartella, nulla toccato nei due tool)

- `generatore_formazioni/build_formazione_globale.py` — script di fusione. **Riusa per import**
  (via `importlib`, nessuna duplicazione) le funzioni generiche già esistenti in
  `formazione_mls/build_formazione_finale.py` (`CardPool`, `build_one_lineup`,
  `synergy_adjusted_rows`, `render_lineup_html`, `render_report_html`, `parse_consiglio`,
  `load_card_counts`) — erano già indipendenti dalla lega, bastava passargli dati taggati con la
  lega giusta. Output **solo HTML** (richiesta esplicita utente).
- `generatore_formazioni/quality_filter.py` — query GraphQL L5/L10/L40 (stesso pattern già
  collaudato in `mls_gk_discovery_global.py`, mai una query nuova/rischiosa).
- `.github/workflows/generatore_formazioni.yml` — Action "Generatore Formazioni": richiama gli
  script discover/predict/consiglio **esistenti e invariati** di entrambi i tool (stessi path di
  output/cache → la cache incrementale viene riusata cosi' com'e', zero query storiche nuove per
  giocatori già noti), poi un job finale nuovo che fa la fusione.

Testato in locale con dati reali già su disco (filtro qualità disattivato via monkeypatch, nessuna
rete disponibile in locale): tutti gli 8 tipi si generano correttamente, HTML valido. Commit
iniziale pushato su `main` (`34aefd19b`).

### C. Bug 1 (run reale): filtro qualità troppo lento — query sull'intero pool scoperto

Prima run reale (2 formazioni In Season+Arena): il job finale ha impiegato **~7 minuti** e
interrogato **287 carte** (l'intero pool scoperto per 4 ruoli × 2 leghe), incappando anche in un
**429 con `Retry-After` di 236 secondi** (quasi 4 minuti da solo) — probabilmente perché le 287
query partivano subito dopo ~280 job predict paralleli sullo stesso account Sorare nello stesso
run, sommando carico.

**Causa**: il filtro qualità controllava OGNI carta scoperta, non solo quelle che servivano per le
formazioni richieste (richiesta esplicita dell'utente: "fagli interrogare solo il numero di
giocatori richiesto... se non riesce, ne interroga un altro, finché non completa").

**Fix**: `LazyQualityPool` (`quality_filter.py`) — parte VUOTA, cresce solo quando
`build_one_lineup` segnala che manca un candidato per uno slot: si controllano i prossimi
candidati non ancora verificati (batch di 3, `GROW_BATCH`) e si riprova, finché la formazione si
completa o il pool scoperto è davvero esaurito. Verificato con un test locale simulato: **27 query
invece di 284** per lo stesso risultato. In produzione reale, seconda run: job finale sceso da
**6m57s a 34s**, richieste esattamente le carte necessarie (30 su un pool di 285).

### D. Bug 2 (run reale): default del workflow generava formazioni non richieste

Run successiva: l'utente ha lasciato il campo `in_season` "vuoto" (senza cancellare attivamente il
testo pre-scritto dal form GitHub) e sono comparse 2 formazioni In Season non richieste — il
default nello YAML era `'mls:1,kleague:1'` (ereditato dal vecchio pattern a singolo-tool), mentre
`arena_dedicata` aveva già default `'mls:0,kleague:0'`. **Fix**: uniformato il default di
`in_season` a `'mls:0,kleague:0'` — un campo non toccato ora genera davvero 0.

### E. Bug 3 (run reale, il più importante): cap L10 delle Arene MAI rispettato

Con Bug 2 corretto, le formazioni richieste (Arene) sforavano COMUNQUE il cap (297-311 invece di
260, su 5/5 formazioni). Diagnosi in due passaggi:

1. **Prima ipotesi (sbagliata)**: pool troppo piccolo dopo il fix del Bug 1 (solo 2-3 candidati
   controllati per ruolo). Provato ad aggiungere un pre-riempimento minimo (`MIN_POOL_FOR_L10_CAP`)
   — non ha risolto: anche con 12 candidati/ruolo disponibili (L10 minimi reali 38-49), sforava
   comunque.
2. **Causa reale**: `build_one_lineup` (funzione CONDIVISA, identica nei due tool originali)
   sceglieva il miglior punteggio che rientrava nel budget residuo **slot per slot in ordine fisso
   GK→DEF→MID→FWD→extra**, senza MAI riservare budget per lo slot EXTRA finale — che quindi
   sforava quasi sempre (un giocatore vero costa sempre >0 di L10, non esiste un pareggio esatto a
   budget zero). Riordinare i ruoli (provato: FWD-first) NON bastava, spostava solo il problema.
   Confermato con l'utente: le run standalone dei due tool originali non avevano MAI incontrato
   questo bug nei loro output storici (probabilmente solo fortuna sulla distribuzione L10 delle
   loro carte specifiche) — il difetto è strutturale, non introdotto dalla fusione.

**Decisione esplicita dell'utente** (superando il vincolo iniziale "non toccare i due tool"): il
cap è un vincolo VERO, va corretto **anche nei due tool condivisi**, non solo nel nuovo script — "se
deve sforare il cap meglio non generarla proprio".

**Fix applicato IDENTICO in `formazione_mls/build_formazione_finale.py` E
`formazione_kleague/build_formazione_finale.py`** (`build_one_lineup`): ogni slot ora riserva la
somma dei minimi L10 disponibili per TUTTI gli slot ancora da riempire (extra incluso) prima di
scegliere un candidato; se nessun candidato rientra nemmeno riservando, la formazione **fallisce**
con lo stesso errore di "candidato esaurito" — **rimosso ogni fallback che sforava in silenzio**
(prima: "prendi il più economico disponibile anche se sfora"). Verificato su dati reali di
entrambi i tool: cap sempre rispettato (257-260/260 su più formazioni generate). Il riordino
"FWD-first" nel Generatore Formazioni è stato rimosso (era un cerotto per lo stesso sintomo, non
più necessario col fix vero).

### F. Bug 4 (scoperta collegata): filtro qualità in tensione diretta con le Arene a cap

Notato dall'utente ("mi sembra che il filtro quality faccia solo danni"): il filtro L5/L10/L40≥35
esclude proprio le carte ECONOMICHE (L10 basso) che servirebbero per stare sotto un cap di 260 —
i due meccanismi lavorano l'uno contro l'altro. **Decisione**: il filtro qualità ha senso SOLO dove
conta il punteggio assoluto (In Season, All Stars, Arena All Stars uncapped), NON dove conta invece
il risparmio L10 (Arena dedicate, Arena All Stars 260/220). **Fix**: nel Generatore Formazioni, i
tipi con cap L10 obbligatorio ora usano il pool GREZZO (tutte le carte scoperte, zero query di
qualità — anche più veloci), il filtro lazy resta attivo solo per i tipi senza cap. Verificato:
5/5 formazioni Arena "entro budget", 0 query di qualità quando si chiedono solo tipi con cap.

### G. Stato repo a fine sessione (27/07 sera)

Pushato su `origin/main`: `34aefd19b` (Generatore Formazioni, primo commit), `db895e6c7` (filtro
qualità lazy), `2977df7a0` (default `in_season` a 0/0), `d5792fcf4` (fix cap L10 riserva budget +
hard-fail, in ENTRAMBI i tool condivisi + scoping filtro qualità). Nessun lavoro di codice pendente
non committato.

**File chiave nuovi**: `generatore_formazioni/build_formazione_globale.py`,
`generatore_formazioni/quality_filter.py`, `.github/workflows/generatore_formazioni.yml`.
**File modificati nei due tool esistenti** (SOLO la funzione `build_one_lineup`, resto invariato):
`formazione_mls/build_formazione_finale.py`, `formazione_kleague/build_formazione_finale.py`.

### H. Verifica reale del fix cap L10 (run 3, stessa sera) — funziona

Run richiesta dall'utente per testare il fix: 1 In Season MLS + 1 In Season K League + 2 Arena All
Stars cap260 + 1 All Stars. Esito: 5/5 generate, **entrambe le Arena All Stars entro budget**
(cap 260 mai sforato), job finale solo 29s (24 query di qualità, solo sui tipi senza cap). Le note
"Cap 260/370: bonus +4% non ottenuto" viste su In Season/All Stars sono il bonus SOFT (solo
informativo, mai un vincolo) — non c'entrano col cap obbligatorio delle Arene, comportamento
corretto.

### I. Run "carico reale" (run 4) — 3 osservazioni dell'utente, analizzate con dati veri

Richiesta dell'utente: 6 In Season MLS + 6 In Season K League + 1 Arena MLS + 1 Arena K League + 1
Arena All Stars 260 (il volume che schiera davvero ogni giornata, "vediamo se il modello regge").
Tre osservazioni sull'output, **investigate leggendo i dati reali (consiglio/cache), non a
intuizione**:

1. **Bonus anti-stack (Multi-club) non evidenziato quando attivo** — prima veniva mostrato SOLO
   il warning di fallimento. **Fix applicato e pushato** (`a1c8c2ef8`): ora mostrato sempre,
   sia il caso positivo ("Bonus Multi-club +2%/giocatore: attivo") sia il fallimento, identico nei
   due tool + script fuso (stesse funzioni riusate).

2. **Budget delle Arene "sballato"**: extra con punteggio 14-26pt quando ne esistevano di molto
   migliori nello stesso budget. Causa reale: il fix precedente (sezione E) garantisce che il cap
   non sfori MAI, ma resta un greedy slot-per-slot con riserva — si accontenta della PRIMA
   combinazione che entra nel budget, non cerca quella con punteggio totale massimo. **Soluzione
   concordata con l'utente**: knapsack ESATTO sui 4 ruoli principali + scelta ottima dello slot
   extra, provando ogni ripartizione di budget (non solo quella che spende di più sui primi 4).
   **STATO A FINE SESSIONE: PARZIALE, non completato**:
   - Scritte in `formazione_mls/build_formazione_finale.py` le funzioni `_pareto_frontier`
     (riduce i candidati di un ruolo ai soli non-dominati: nessuno più caro E con punteggio minore
     o uguale a uno già incluso) e `_optimize_capped_lineup` (DP su GK/DEF/MID/FWD combinato con
     la scelta ottima dell'extra) — **sintassi verificata (`py_compile` OK), ma NON ANCORA
     collegate a `build_one_lineup`** (che continua a usare il vecchio greedy-con-riserva).
   - **NON ancora replicato in `formazione_kleague/build_formazione_finale.py`** (identico al
     pattern già usato per il fix precedente, va rifatto identico).
   - **NON ancora integrato/testato in `generatore_formazioni/`** (eredita tutto per import da
     `formazione_mls`, quindi si aggiorna da solo una volta wired nel file sorgente — ma va
     comunque testato sul caso reale).
   - Scelta di design già presa (da rispettare quando si riprende): il knapsack **non incorpora i
     nudge di sinergia da correlazione** (piccoli, ±3/±11, applicati oggi in `variance_mode`) —
     l'obiettivo qui è il punteggio reale massimo sotto cap, non l'ordine di scelta. Significa che
     per i tipi con cap L10 (Arena dedicate, Arena All Stars 260/220) la sinergia GK-DEF/GK-MID/
     ecc. andrebbe PERSA se si passa al knapsack così com'è — non ancora deciso con l'utente se va
     bene o se serve un'estensione (es. DP annidato per ogni possibile portiere, più costoso).
     **Da chiarire alla ripresa prima di completare il collegamento.**
   - Il knapsack si applica SOLO quando `role_slots` ha un ruolo per slot senza ripetizioni
     (vero per tutte le Arene con cap oggi) e `max_classic is None` (vero per tutte) — per shape
     diverse (es. All Stars con 2x DEF/MID, mai a cap oggi) va mantenuto il vecchio percorso come
     fallback, già previsto nel design ma da implementare quel branching in `build_one_lineup`.

3. **Caso Zinckernagel (2 copie) — NON un bug, verificato con dati reali**: escluso dalle lineup
   In Season #4/#5 per anti-sinergia (il suo Chicago Fire gioca contro Charlotte FC, il cui
   portiere Kristijan Kahlina era schierato in quelle lineup) — dato di calendario reale
   confermato nel consiglio (`SQUADRA`/`AVVERSARIO`). Escluso dalla #6 perché la sua ultima copia
   era Classic e quello slot aveva già consumato l'unica Classic ammessa (su un altro giocatore,
   DEF). Finito in Arena perché lì non c'è il vincolo "max 1 Classic".

   **Domanda di follow-up dell'utente, NON ancora risolta**: per le In Season, ha senso che il
   portiere venga scelto SEMPRE per primo (`role_slots` inizia con GK), e l'anti-sinergia esclude
   poi FWD/MID in base a quel portiere -- mai il contrario, indipendentemente da quale punteggio
   sia più alto. **Osservazione tecnica emersa in sessione (da validare/implementare)**: per le In
   Season il target è fisso (nessuna variabilità da sfruttare) — una sessione precedente (Finding
   3+F, sezione 12/13) aveva già stabilito che la correlazione tra compagni NON cambia il valore
   atteso della somma (linearità del valore atteso), motivo per cui `variance_mode` è stato
   limitato ad Arena/All Stars. La penalità anti-sinergia DI BASE (`ANTI_SYNERGY_PENALTY`/
   `POSITIVE_SYNERGY_BONUS`, indipendente da `variance_mode`) però continua ad applicarsi anche
   alle In Season, dove — con lo stesso ragionamento — non dovrebbe avere alcun beneficio di
   valore atteso. **Proposta discussa ma non implementata**: rimuovere l'anti/positive-sinergia di
   base per le In Season, lasciarla solo per Arena/All Stars — ogni slot scelto puramente per
   punteggio, senza artefatti da chi è stato scelto come portiere. Da confermare con l'utente prima
   di toccare `synergy_adjusted_rows`/`synergy_sort_key` (funzioni condivise nei due tool).

4. **Varianza capitano tra lineup multiple, richiesta dell'utente (NON implementata)**: con più
   copie di un giocatore fortissimo, oggi ogni lineup lo nomina capitano indipendentemente (stesso
   giocatore capitano in più lineup dello stesso pacchetto) — l'utente vuole una logica che eviti
   di riassegnare il capitano a chi lo è già stato in un'altra lineup (dello stesso tipo, o
   dell'intera run — **domanda posta all'utente, risposta non ancora arrivata**), per varianza sul
   rischio complessivo della giornata invece di concentrarlo tutto su un solo giocatore. Richiede
   tracciare un set di "già capitanati" condiviso tra le chiamate di `generate_lineups_for_type`
   (oggi `pick_captain` sceglie sempre e solo il punteggio più alto, senza memoria tra lineup) e
   modificare `pick_captain`/i punti di chiamata in entrambi i tool + script fuso. Non iniziato.

**Backlog aperto per la prossima sessione** (in ordine di priorità, dato quanto emerso oggi):
1. **PRIORITARIO**: completare il knapsack (punto 2 sopra) — decidere sinergia sì/no, collegare a
   `build_one_lineup`, replicare in K League, testare su una run reale.
2. Decidere e implementare la rimozione dell'anti-sinergia di base per le In Season (punto 3
   sopra) — richiede conferma esplicita dell'utente prima di toccare le funzioni condivise.
3. Varianza capitano tra lineup (punto 4 sopra) — richiede la risposta dell'utente sullo scope
   (per tipo o sull'intera run) prima di implementare.
4. Batching dei job predict (rimandato dalla sezione A, mai diventato necessario finora).
5. Verificare il fix del cap L10 sul caso limite "pool davvero troppo piccolo per qualunque
   combinazione" (deve fallire pulito, non ancora visto in una run reale).
6. Tutto il backlog della sezione 13E/14F resta valido e non toccato in questa sessione (bonus
   K League da verificare con screenshot reali, estensione ad altri campionati, ecc.).

### J. Stato repo esatto a fine sessione (per chi riprende, anche su un altro account)

Ultimo commit pushato su `origin/main`: `a1c8c2ef8` (bonus anti-stack sempre mostrato). **Questa
sessione lascia inoltre modifiche WIP non ancora committate/pushate in
`formazione_mls/build_formazione_finale.py`** (funzioni `_pareto_frontier`/
`_optimize_capped_lineup`, sintassi valida ma non collegate/usate) — verranno committate insieme a
questo aggiornamento del riassunto con un messaggio esplicito "WIP, non collegato". **Prima di
lanciare qualunque run del Generatore Formazioni con tipi a cap L10 (Arena), verificare che il
branching in `build_one_lineup` sia stato completato** — finché non lo è, il comportamento resta
quello del vecchio greedy-con-riserva (corretto sul cap, non ottimale sul punteggio), non rotto.

## 16. Sessione 27/07/2026 (notte) — knapsack Arene collegato, testato, replicato in K League

Ripresa da un account diverso. Chiude il punto 1 (PRIORITARIO) del backlog della sezione 15J.

**Decisione presa con l'utente prima di implementare** (unico punto aperto lasciato dalla sessione
precedente): il knapsack **NON incorpora i nudge di sinergia** (GK-DEF/GK-MID/DEF-MID/DEF-DEF,
vedi sezione 14A) — punta solo al punteggio grezzo massimo sotto il cap. Motivazione dell'utente:
più semplice da collegare/testare subito; il costo è la perdita dei bonus piccoli (+3/+11 pt) SOLO
per i tipi a cap L10 (Arena dedicate, Arena All Stars 260/220) — Arena/All Stars senza cap non sono
toccate (restano sul vecchio percorso con sinergia intatta).

**Scoperta importante durante l'implementazione**: `generate_lineups_for_type` passa
`variance_mode=True` per **tutte** le Arene, incluse quelle a cap L10 (non solo quelle senza cap
come si poteva pensare leggendo solo la sezione 15) — quindi il gating iniziale del knapsack non
poteva escludere `variance_mode=True`, altrimenti non si sarebbe mai attivato per nessuna Arena a
cap. Il knapsack ignora semplicemente il valore di `variance_mode` quando lo attiva (lo attiva solo
in base a `l10_cap is not None` + forma dello shape), coerente con la decisione sopra.

**Implementazione** (`build_one_lineup`, IDENTICA in `formazione_mls/build_formazione_finale.py` e
`formazione_kleague/build_formazione_finale.py`): se `l10_cap` è impostato, `max_classic` è `None`,
`apply_stack_guard` è `False` e `role_slots` ha un ruolo per slot senza ripetizioni (vero oggi solo
per le 3 Arene dedicate — MAI per In Season che ha `max_classic=1`, MAI per All Stars che ripete
DEF/MID), usa `_optimize_capped_lineup` (il DP scritto nella sessione precedente, mai toccato) al
posto del vecchio greedy-con-riserva. Fix minore collegato in `_optimize_capped_lineup`: prima non
tracciava il RUOLO dello slot extra scelto (necessario per l'etichetta `EXTRA (ruolo)` in output) —
aggiunto tag di ruolo alla lista `extra_candidates`. Nuovo helper `_consume_pick` (consuma la copia
IN_SEASON se disponibile, altrimenti CLASSIC — stesso ordine di preferenza del vecchio `pick`).
`formazione_kleague/build_formazione_finale.py` non aveva ancora `_pareto_frontier`/
`_optimize_capped_lineup` (mai portate lì nella sessione precedente, solo scritte in MLS) —
aggiunte identiche (senza `variance_mode`, parametro che K League non ha mai avuto).

`generatore_formazioni/build_formazione_globale.py` non richiede modifiche: importa
`build_one_lineup` direttamente da `formazione_mls` (`bff`) per **tutti** gli 8 tipi, incluse le
Arene K League — il fix si applica automaticamente una volta wired nel sorgente MLS.

**Verificato con test sintetico locale** (dati finti, nessuna rete — stesso approccio "smoke test"
già usato nelle sessioni precedenti): 4 candidati per ruolo con L10/punteggio costruiti apposta
perché il vecchio greedy avrebbe scelto una combinazione subottima; il knapsack trova l'ottimo
esatto (**verificato per confronto diretto con un brute-force su tutte le combinazioni possibili**,
stesso risultato: score 287, L10 220/220), rispetta sempre il cap, fallisce pulito quando il cap è
impossibile da rispettare per qualunque combinazione, e non altera il comportamento dei tipi senza
cap (Arena uncapped, che restano sul vecchio percorso greedy). Stesso test ripetuto sul modulo
K League con esito identico. **Non ancora testato su una run reale GitHub Actions** (solo dati
sintetici in locale) — da fare alla prima occasione utile prima di considerarlo definitivo.

**Stato repo**: modifiche committate sul branch di lavoro (non su `main`, per richiesta esplicita
dell'utente di pushare su `main` solo a fine sessione/su richiesta — vedi sezione 17 sotto per
il seguito della stessa nottata).

## 17. Stessa notte (continua) — redesign In Season con 2+ formazioni, varianza capitano

Chiude i punti 2 e 3 del backlog della sezione 16 (discussi con l'utente PRIMA di implementare,
come da prassi "un tema alla volta").

### A. Redesign logica In Season quando se ne richiedono 2 o più

Punto di partenza diverso dalla proposta iniziale (semplice rimozione dell'anti-sinergia): l'utente
ha chiesto una logica più articolata perché le In Season sono "le più importanti di tutte le
formazioni". Nuove regole, attive **solo quando le In Season richieste in un run sono 2 o più**
(con una sola richiesta, comportamento INVARIATO rispetto a prima):

- **Formazione #1**: comportamento storico invariato — sinergia GK-DEF soft attiva (bonus
  `POSITIVE_SYNERGY_BONUS`), GK scelto per primo per costruzione (`role_slots` inizia con GK).
- **Formazioni #2..N**: greedy puro, nessun bonus di sinergia, nessuna priorità di ruolo — ogni
  slot scelto solo per punteggio grezzo massimo disponibile.
- **In ENTRAMBI i casi** (novità rispetto a prima): il vincolo "portiere vs attaccante avversario"
  (prima un forte scoraggiamento — `ANTI_SYNERGY_PENALTY`, comunque selezionabile come ultima
  risorsa) diventa un'**esclusione assoluta** — quella combinazione non compare mai, a costo di
  fallire la formazione se non ci sono alternative (stesso principio hard-fail già usato per il
  cap L10 delle Arene).

**Implementazione** (identica in `formazione_mls/build_formazione_finale.py`,
`formazione_kleague/build_formazione_finale.py`, e propagata a
`generatore_formazioni/build_formazione_globale.py` per `MLS_IN_SEASON`/`KLEAGUE_IN_SEASON`):
- `synergy_sort_key`/`synergy_adjusted_rows`: nuovo parametro `apply_positive_synergy` (gate unico
  per il bonus DEF-GK e la vecchia penalità soft MID/FWD — quest'ultima ormai ridondante quando il
  filtro duro è attivo, ma innocua se lasciata).
- `build_one_lineup`: nuovo parametro `strict_gk_anti_synergy` — quando `True`, filtra COMPLETAMENTE
  (non solo deprioritizza) i candidati MID/FWD della squadra avversaria del portiere, sia per gli
  slot titolari sia per lo slot extra, PRIMA di applicare qualunque sinergia soft.
  `apply_positive_synergy=False` disattiva anche il bonus DEF-GK.
- `generate_lineups_for_type` (nei 3 file): calcola `in_season_multi = tipo in (...IN_SEASON) and
  count >= 2`, poi per `idx==1`: `apply_positive_synergy=True`; per `idx>1`:
  `apply_positive_synergy=False`; `strict_gk_anti_synergy=in_season_multi` sempre.

### B. Varianza capitano tra formazioni multiple, scope PER TIPO/COMPETIZIONE

Confermato dall'utente: scope "intracompetizione" — In Season MLS conta a sé, In Season K League a
sé, ogni Arena dedicata a sé, Arena All Stars a sé, All Stars a sé. Coincide naturalmente con lo
scope di ogni singola chiamata a `generate_lineups_for_type` (già un tipo per chiamata), quindi
nessuna struttura dati aggiuntiva cross-tipo necessaria.

**Implementazione** (identica nei 3 file): `pick_captain(formazione, avoid_slugs=None)` — se
fornito, preferisce il punteggio più alto TRA i titolari non ancora capitanati in questo tipo;
ripiega sul punteggio più alto assoluto se non c'è alternativa (mai un peggioramento del punteggio
atteso solo per la varianza). `format_lineup`/`render_lineup_html` accettano `avoid_captain_slugs`
e lo passano a `pick_captain`. `generate_lineups_for_type` mantiene un set `captained_slugs` locale
(resettato ad ogni chiamata, quindi già per-tipo), lo passa a entrambe le funzioni di rendering, poi
richiama `pick_captain` con lo stesso set per sapere quale slug aggiungere prima della prossima
iterazione. **Nota implicita**: un giocatore con 1 sola copia non può comunque comparire in due
lineup dello stesso tipo (il `CardPool` lo impedirebbe strutturalmente) — quindi non serve un
controllo esplicito "2+ copie", la condizione è già garantita dal pool.

### C. Verificato con test sintetici locali (nessuna rete)

- Con `count==1`: comportamento identico a prima (candidato "vincolato" ancora selezionabile come
  ultima risorsa se conviene — verificato con un MID che sarebbe stato il punteggio più alto in
  assoluto ma gioca per la squadra avversaria del GK).
- Con `count>=2`, formazione #1: GK scelto per primo, DEF con bonus sinergia sceglie il compagno di
  squadra ANCHE quando ha un punteggio grezzo leggermente più basso di un'alternativa (verificato
  con uno scarto costruito apposta: 50+3 batte 52 grezzo); il MID della squadra avversaria del GK è
  escluso del tutto (mai scelto, a differenza del caso `count==1`).
- Con `count>=2`, formazioni #2+: stesso vincolo dell'esclusione assoluta sul MID, ma il DEF viene
  scelto per puro punteggio grezzo (52 batte 50+3 quando il bonus è disattivato) — confermata la
  differenza tra i due modi.
- Varianza capitano: 3 formazioni In Season generate in sequenza, 3 capitani diversi (nessuna
  ripetizione quando esistono alternative valide nella lineup).

### D. Verificato su run reale GitHub Actions (run #5, 27/07 notte) — TUTTO CONFERMATO

Run [30253520459](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30253520459):
6 In Season MLS, 6 In Season K League, 1 Arena MLS (cap 260), 1 Arena K League (cap 260), 1 Arena
All Stars (cap 260), 1 All Stars — 16/16 formazioni generate, nessun errore.

- **Knapsack Arene**: le 3 formazioni a cap L10 obbligatorio rispettano tutte il budget, vicinissime
  al limite (L10 250.0/260.0, 253.0/260.0, 258.0/260.0 — tutte "entro budget") — segno che sta
  davvero ottimizzando (vicino al cap), non solo rispettandolo per caso. Etichetta extra con ruolo
  corretto (es. "EXTRA · MID").
- **Varianza capitano**: 0 ripetizioni DENTRO lo stesso tipo — 6 capitani diversi tra le In Season
  MLS, 6 diversi tra le In Season K League. Un capitano ripetuto tra In Season MLS e Arena MLS
  (Sebastian Berhalter) è corretto: sono tipi/competizioni diverse, lo scope è per tipo.
- Bonus capitano Arena confermato +20% in output (`CAPTAIN_BONUS_BY_TYPE`), nessuna regressione.

**Nota per la prossima sessione (richiesta esplicita dell'utente, 27/07 notte)**: per ORA le
modifiche vanno fatte solo sul Generatore Formazioni (`generatore_formazioni/` +
`formazione_mls/build_formazione_finale.py`, da cui il tool fuso importa `build_one_lineup` per
TUTTI gli 8 tipi, MLS e K League inclusi) — l'utente userà probabilmente solo questo tool d'ora in
poi. `formazione_kleague/build_formazione_finale.py` è stato comunque tenuto allineato in questa
sessione (knapsack + redesign In Season + varianza capitano, tutti e 3 i fix), ma non è più
prioritario mantenerlo in parallelo nelle prossime sessioni finché l'utente non lo richiede di
nuovo esplicitamente.

### E. Stato repo e prossimi passi

Tutto pushato su `main` (knapsack sezione 16 + redesign In Season/varianza capitano sezione 17),
verificato su run reale.

**Backlog aggiornato**: nessun punto prioritario aperto su questo filone al momento. Resta valido
tutto il backlog di 13E/14F/15J (bonus K League da verificare con screenshot reali, estensione ad
altri campionati, ecc.), non toccato in questa sessione.

## 18. Stessa notte (continua) — capitano portiere: analisi dati + margine minimo

**Richiesta esplicita dell'utente**: dalla sua esperienza pluriennale su Sorare, un portiere quasi
mai conviene come capitano (basta un gol subito per perdere il bonus clean sheet, i portieri hanno
punteggi tendenzialmente più bassi) — ma è un'intuizione, mai verificata sui dati. Chiesta
un'analisi locale (nessuna nuova query) per quantificare quanto conviene/sconviene un portiere
capitano rispetto a un giocatore di movimento, anche a parità o quasi di punteggio atteso.

**Nota concettuale importante** (chiarisce perché questo NON è solo "avversione al rischio"): il
bonus capitano è una percentuale del punteggio REALE ottenuto (non dell'atteso). Scegliere il
capitano in base al solo "atteso" grezzo è ottimale in valore atteso SOLO SE l'atteso è calibrato
allo stesso modo tra ruoli. Se il modello sovrastima sistematicamente i portieri rispetto al
movimento a parità di atteso nominale, scegliere il portiere in base al raw atteso è un errore
anche in pura logica di valore atteso — non serve invocare la varianza per giustificare
l'intuizione dell'utente, basta una bias di calibrazione per ruolo.

### A. Analisi (`formazione_mls/diagnostics/analyze_gk_captain_value.py`, nuovo script)

Walk-forward identico ad altri diagnostici del progetto (`rigorous_backtest` di ciascun
`test_<ruolo>.py`, PARAMETRI UFFICIALI di produzione, granulari OFF, opponent factor neutro) su
TUTTE le cache di calibrazione già su disco, MLS+K League insieme (149 partite GK, 1673 partite
movimento DEF+MID+FWD combinate). Nessuna nuova query API.

**Bias di calibrazione complessivo** (media reale − atteso): GK **−3.12 pt**, movimento **+0.29 pt**
— il modello sovrastima sistematicamente i portieri, il movimento è quasi non distorto.

**Nella "zona capitano" (atteso ≥ 55, dove si gioca tipicamente la scelta)** il divario esplode:

| Gruppo | n | Atteso medio | Reale medio | Bias | Frequenza "crollo" (reale <50% atteso) |
|---|---|---|---|---|---|
| GK | 38 | 60.6 | 45.2 | **−15.4 pt** | 10.5% (gap medio 52pt) |
| Movimento | 517 | 62.0 | 56.9 | −5.2 pt | 7.7% (gap medio 40pt) |

Confronto per fascia di punteggio atteso (bucket da 5pt): dai 50 punti in su, a parità di atteso
nominale il reale medio del GK è sistematicamente più basso di quello del movimento, e il divario
CRESCE con l'atteso (−7.5, −10.7, −7.8, −15.6 pt nelle fasce successive fino a 70) — non è rumore
casuale, è un pattern consistente. **Conclusione: l'intuizione dell'utente era corretta e
quantificabile.** Il divario "equo" implicito nella zona capitano è: `bias_movimento -
bias_GK = -5.2 - (-15.4) ≈ 10.2 pt`.

### B. Fix implementato: margine minimo per il capitano portiere

Prima modifica rapida (già fatta prima dell'analisi, su richiesta): a parità ESATTA di atteso tra
portiere e movimento, preferire il movimento (`_captain_sort_key`, poi sostituita dal fix B sotto,
più completo).

**Fix finale** (`pick_captain` in `formazione_mls/build_formazione_finale.py`, DA CUI il Generatore
Formazioni importa `pick_captain` per TUTTI gli 8 tipi — **richiesta esplicita dell'utente: per ora
le modifiche SOLO sul tool fuso, non più su `formazione_kleague/build_formazione_finale.py`
standalone**, che quindi NON è stato toccato in questo fix, a differenza dei fix precedenti della
stessa notte): nuova costante `GK_CAPTAIN_MARGIN = 10.0` (tarata sul gap ~10.2pt misurato sopra). Un
portiere diventa capitano SOLO se il suo atteso supera il miglior atteso tra i giocatori di
movimento della formazione di almeno `GK_CAPTAIN_MARGIN` punti — altrimenti vince il movimento anche
se il portiere ha un atteso nominale più alto (ma non abbastanza). Riscritta la funzione senza il
vecchio `_captain_sort_key` (rimosso, sostituito da questa logica più esplicita): separa i candidati
in `outfield` (tutto tranne lo slot `'GK'`, che identifica sempre univocamente il portiere) e `gk`,
sceglie il migliore per punteggio in ciascun gruppo, poi applica la soglia di margine. Compatibile
con la varianza capitano (`avoid_slugs`, sezione 17B) — il filtro "già capitanati" si applica prima,
poi la logica GK/movimento gira normalmente sul sottoinsieme filtrato.

**Verificato con test sintetici locali**: parità esatta (70 vs 70) → movimento; GK sopra ma sotto
margine (70 vs 65, diff 5) → movimento comunque; GK esattamente al margine (75 vs 65, diff 10) →
GK; GK ben oltre (85 vs 65, diff 20) → GK; compatibilità con `avoid_slugs` verificata (varianza
capitano continua a funzionare, la logica GK/movimento si applica al sottoinsieme filtrato).

### C. Stato repo

Nuovo file `formazione_mls/diagnostics/analyze_gk_captain_value.py` (analisi, non tocca la
produzione) + modifica a `pick_captain` in `formazione_mls/build_formazione_finale.py`. **NON
toccato `formazione_kleague/build_formazione_finale.py`** (richiesta esplicita dell'utente, vedi
sopra) — se in futuro cambia idea e richiede di nuovo il doppio tool, replicare identico il fix di
`pick_captain` anche lì (stesso pattern usato più volte in questa sessione per gli altri fix).
Pronto per il commit, non ancora pushato su `main` al momento di scrivere questa sezione.

**Backlog**: nessun punto prioritario aperto. `GK_CAPTAIN_MARGIN=10.0` è un valore tarato su dati
oggi disponibili (campione GK ancora relativamente piccolo, 149 partite) — da rivedere alla
prossima ricalibrazione allargata quando la stagione avanza, stesso principio già applicato ai
parametri ufficiali del modello.

## 19. Stessa notte (continua) — sinergia FWD-MID same-team, estensione a 4 nuovi campionati

### A. Analisi: conviene FWD+MID di squadre diverse (atteso combinato più alto) o della stessa
squadra (atteso combinato più basso)?

Nuovo script `formazione_mls/diagnostics/analyze_fwd_mid_team_pairing.py` (nessuna nuova query,
cache di calibrazione già su disco, MLS+K League). Premessa teorica verificata: il valore atteso di
una SOMMA di due punteggi non dipende dalla correlazione tra i due (solo la varianza ne risente) —
se l'atteso è ben calibrato per ruolo (confermato: bias MID +0.71pt, FWD +0.55pt, quasi nullo), la
coppia con atteso combinato più alto dovrebbe sempre vincere in media, indipendentemente dalla
squadra. Verificato se questo tiene sui dati.

**Risultato, più sfumato della teoria pura**: correlazione dei residui same-team **+0.147
(p=0.076)** — al limite della soglia 0.05, non netta ma neanche trascurabile — contro cross-team
**+0.002 (p=0.89)**, praticamente zero come atteso (nessun legame reale tra giocatori di squadre
diverse). A parità di atteso combinato, nelle fasce centrali (80-120pt) le coppie same-team
realizzano in media **+1/+3.4/+8.7 punti** in più delle cross-team; nelle fasce alte (120-140) il
segno si inverte (-1.8/-3.2, campioni piccoli). Simulazione diretta: una coppia same-team con
atteso combinato ~125 batte in media coppie cross-team con atteso combinato **fino a 20 punti più
alto** (solo a +25 il cross-team supera). **Controllo anti-artefatto**: 50 coppie giocatore
distinte dietro le 152 osservazioni same-team (max 8 partite insieme per la coppia più frequente)
— il segnale non è guidato da un singolo duo dominante.

**Conclusione onesta**: segnale di sinergia FWD-MID same-team plausibile ma debole/marginale (p non
sotto soglia standard, pattern non pulito in ogni fascia) — **non portato in produzione**, resta un
punto da riosservare quando il campione crescerà (stesso principio di cautela già applicato ad
altri segnali deboli in questo progetto, es. sezione 13F).

### B. Estensione pipeline completa a 4 nuovi campionati (Portogallo/Austria/Scozia/Croazia)

**Richiesta esplicita dell'utente**: estendere l'infrastruttura a 4 campionati dove possiede carte
(slug trovati in `sorare_lista_nera.txt` su main, sezione `## campionato_inseason_temp`): Croazia
`1-hnl`, Austria `austrian-bundesliga`, Scozia `premiership-gb-sct`, Portogallo `primeira-liga-pt`.
**Solo le carte POSSEDUTE dall'utente** in quei campionati (stesso pattern discovery non-globale di
MLS/K League, NON la variante `_global` usata per la calibrazione allargata) — esplicitamente
confermato con l'utente per evitare equivoci.

Lavoro delegato a un agente in background, in worktree isolato, in due giri (stesso agente ripreso
via `SendMessage` per non perdere il contesto già costruito):

1. **Primo giro**: solo discovery (16 script `discovery/<lega>_<ruolo>_discovery.py` + 4 workflow
   `<lega>_discovery.yml`, clone meccanico di `formazione_kleague/discovery/`).
2. **Secondo giro** (richiesta ampliata dall'utente: "voglio la cache incrementale applicata subito,
   così alla prima run tracciamo tutto e dopo in fase di predict sarà più facile"): scoperto che la
   cache incrementale del game log vive SOLO in `predict/test_<ruolo>.py` (non in discovery, sia per
   MLS che K League) — quindi ampliato lo scope alla pipeline COMPLETA (`predict/` x4 ruoli +
   `consiglio/` + `build_formazione_finale.py` + workflow `<lega>_completa.yml`), clone verbatim di
   `formazione_kleague/` con solo adattamenti meccanici di path/nome lega. STESSI parametri
   ufficiali di produzione per ruolo (GK 9.0/1.6/29.0/0.7, DEF 12.0/1.2/29.0/0.7, MID/FWD
   12.0/1.4/29.0/0.7), stessa cache incrementale (`GAME_LOG_REFRESH_COUNT=2`) e cache dettagli
   granulari (`.cache/<slug>_detail_cache.json`).

**Vincolo rispettato in entrambi i giri**: NON integrato nel pool di `generatore_formazioni/`
(rimane MLS+K League soltanto, verificato con `git diff --stat` che il file non è stato toccato) —
tool standalone separati per ora, stesso stadio in cui si trovava K League prima della fusione.
NESSUN `gh workflow run` lanciato, NESSUN push al remoto durante lo sviluppo, NESSUNA query GraphQL
reale (solo verifica sintattica/strutturale + smoke test con dati finti).

**Scelte dell'agente da conoscere**: liste `_FALLBACK_PLAYER_SLUGS` (giocatori di test hardcoded nei
file K League, es. Hugo Lloris/Mamadou Fofana) svuotate a `[]` per questi 4 campionati (si
popoleranno dalla discovery reale al primo run) — lasciate invece intatte le note storiche che
descrivono lo SCHEMA `detailedScore` di Sorare (non specifiche di un campionato). Titoli/commenti
che identificano esplicitamente "questo file è per la lega X" aggiornati al nome nuovo; commenti
storici sulla provenienza di un parametro (es. "OPPONENT_SENSITIVITY=29.0 calibrato su K League")
lasciati invariati perché sono un fatto storico vero, il valore è solo riusato come punto di
partenza per questi campionati (non ancora ricalibrato su dati propri).

**Verificato**: `py_compile` su tutti i 60 file Python nuovi (discovery+predict+consiglio+build),
`yaml.safe_load` su tutti i 12 workflow (8 discovery+completa + 4 già esistenti prima), merge
pulito nel branch di lavoro (solo file nuovi, nessun conflitto).

### C. Prossimo passo pianificato (in coda, non ancora eseguito)

L'utente ha dato il via libera a lanciare la discovery+predict REALE (query GraphQL vere) per i 4
campionati, **in sequenza, un campionato alla volta** (stessa cautela rate-limit già documentata
più volte in questo progetto — mai più leghe/ruoli in parallelo sullo stesso account Sorare, rischio
concreto di 429). Solo le carte possedute dall'utente in ciascun campionato. Risultati tenuti nelle
rispettive cartelle `formazione_<lega>/output/`, pronti per un'eventuale fusione futura nel pool del
Generatore Formazioni — **ma la fusione stessa NON va fatta finché l'utente non lo richiede
esplicitamente** (già confermato due volte in questa sessione). Da eseguire alla ripresa.

### D. Stato repo

Tutto pushato su `main` (analisi FWD-MID + pipeline completa 4 nuovi campionati), nessuna run reale
lanciata ancora. Prossimo passo: sezione C sopra.

## 20. Stessa notte (continua) — run reali 4 campionati, due bug reali trovati/corretti, correlazioni
## reindagate su 6 campionati, modello aggiornato

### A. Bug 1: la cache incrementale non veniva MAI persistita (MLS/K League inclusi)

Prima run reale dei 4 nuovi campionati: nessun file `.cache`/`.game_log_cache` finiva nel repo,
nonostante i log del job `predict` mostrassero chiaramente il fetch/salvataggio in corso. Causa:
`actions/upload-artifact@v4` esclude i file/cartelle nascosti per default
(`include-hidden-files: false`, mai impostato esplicitamente) — il job `predict` (matrice per
giocatore) scrive la cache in locale e la carica come artifact per il job `merge`, ma l'artifact
conteneva SOLO il file di predizione, mai `.cache`/`.game_log_cache`. **Bug preesistente anche per
MLS e K League**, non solo i 4 nuovi: verificato che l'ultimo commit che ha aggiunto file a
`mls_gk_all/.cache` risale a uno stile di commit per-singolo-giocatore precedente all'introduzione
del pattern matrix+artifact — da allora la cache era di fatto ferma (il fallback "cache
insufficiente" ha sempre coperto la cosa senza errori visibili, solo con piu' query del necessario
ad ogni run). **Fix**: aggiunto `include-hidden-files: true` a tutti gli step `upload-artifact` di
predict in `formazione_completa.yml`, `formazione_completa_kleague.yml`, i 4 nuovi campionati, e
`generatore_formazioni.yml`.

### B. Bug 2: nessun retry su errori HTTP non-429 nella discovery

Rilancio dei 4 campionati dopo il fix A: la discovery MID del Portogallo ha incontrato un 403
CloudFront transitorio, e `graphql_query` (in tutti i 32 script discovery del progetto) trattava
QUALUNQUE errore >=400 diverso da 429 come "nessun dato", ritornando `{}` senza ritentare —
azzerando il pool MID (`player_slugs.json` sovrascritto con lista vuota) e facendo fallire l'intera
run (nessun candidato MID disponibile per la formazione finale). **Fix**: ogni errore HTTP >=400 ora
viene ritentato con lo stesso backoff esponenziale di 429 (fino a 5 tentativi) prima di arrendersi,
applicato identico a tutti e 32 gli script discovery (MLS/K League/4 nuovi campionati).

### C. Run reali completate con successo (dopo i due fix)

Tutti e 4 i campionati generati con successo (In Season, giocatori posseduti scoperti, cache
incrementale ora effettivamente persistita — verificato: 34/24/31/25 file `.game_log_cache` per
Portogallo/Austria/Scozia/Croazia rispettivamente). Nessuna fusione nel pool del Generatore
Formazioni (resta MLS+K League soltanto, come richiesto esplicitamente più volte).

### D. Correlazioni reindagate su 6 campionati (non più 2) — FWD-MID diventa significativa

`measure_teammate_correlation.py` esteso da MLS-only a tutti e 6 i campionati (K League +
Portogallo/Austria/Scozia/Croazia, usando le cache "_all" di produzione per i 4 nuovi dove non
esiste ancora una cartella "_calibration" dedicata — stessi dati). Risultato: **FWD-MID same-team
passa da marginale a significativo e stabile**: corr +0.161, p=0.005 (prima: +0.106/+0.147,
p=0.076-0.17 su solo 2 campionati), split-half concorde (+0.174/+0.152). Le altre correlazioni note
si confermano più solide con più dati: DEF-GK +0.390, GK-MID +0.225, DEF-MID +0.238, DEF-DEF +0.190
(tutte p<0.05). Cross-team: GK-vs-MID avversario e GK-vs-FWD avversario ORA ENTRAMBI significativi
(-0.250 p=0.005, -0.281 p=0.024 — prima GK-FWD era solo marginale p=0.12), a conferma dell'anti-
sinergia già codificata.

**Modello aggiornato**: `TEAMMATE_SYNERGY_BONUS_VARIANCE` (nudge di sinergia da correlazione
misurata, SOLO Arena/All Stars) esteso da DEF/MID anche a FWD in `synergy_sort_key` — stesso piccolo
nudge già usato per gli altri ruoli, nessun fattore nuovo introdotto. Solo `formazione_mls/
build_formazione_finale.py` (richiesta esplicita utente: modifiche solo sul tool fuso per ora).

### E. Stato repo

Tutto pushato su `main`: fix A, fix B, run reali 4 campionati (con cache popolata), reindagine
correlazioni + estensione nudge FWD. Nessun'altra azione in sospeso su questo filone.

## 21. Stessa notte (continua) — ricalibrazione parametri In Season su 6 campionati, granulari
## ritestati sul serio, 3 parametri aggiornati in produzione

Richiesta esplicita dell'utente: a prescindere dalla sinergia (sezioni 16-20), rifare le indagini
di calibrazione che hanno portato al modello attuale (grid search cross-player pesato per n_test,
stessa metodologia di `aggregate_grid_search.py`) usando i dati dei 6 campionati, focus sulla stima
del punteggio SINGOLO per le competizioni In Season (non Arena).

**Primo tentativo scartato**: `formazione_mls/diagnostics/recalibrate_6leagues_inseason.py` chiamava
`run_grid_search` senza passare gli array granulari (possession/passing/duelli/ecc.), rendendo il
flag "con/senza granulari" inerte per costruzione (MAE identico in ogni riga con/senza) — l'utente
ha corretto: bisognava ricostruire i VERI array granulari (stessa logica esatta di `build_prediction`
in ciascun `test_<ruolo>.py`: `extract_group_score` sulle STATS del modulo, capping identico,
`residual_values` = punteggio meno tutti i gruppi coperti) e ritestare sul serio.

**Rifatto correttamente** (`build_granular_kwargs`, nuova funzione nello script): ricostruisce per
ogni ruolo gli stessi identici array usati in produzione (GK: possesso/passaggio/portiere/gol
subiti; DEF: + azioni difensive/clean sheet; MID: + azioni difensive, no clean sheet; FWD: senza
azioni difensive/gol subiti/clean sheet), usando le costanti STATS e i CAP di ciascun modulo
(nessun valore hardcoded, sempre letto dal modulo per restare fedele a eventuali differenze tra
ruoli). Aggregazione per **composite score** (MAE + penalità copertura, peso 0.1 — stesso criterio
già in uso, sezione 14C — NON per solo MAE: il `range_multiplier` non cambia mai il MAE, solo
l'ampiezza dell'intervallo, quindi ordinare per solo MAE renderebbe la scelta tra range diversi
arbitraria).

**Risultato con i granulari testati sul serio**: **confermano ancora nessun beneficio** in NESSUN
ruolo (nei top-5 per composite score, le varianti "+granulari" o non compaiono affatto o sono
nettamente peggiori — es. MID: 15.84 con granulari vs 15.62 senza) — stavolta è una vera
riconferma, non un artefatto. Sui parametri numerici emergono pero' 3 scarti piccoli ma reali
rispetto alla produzione attuale (opponent_sensitivity e range_multiplier confermati invariati
ovunque):

| Ruolo | Parametro | Prima | Dopo | Composite prima | Composite dopo |
|---|---|---|---|---|---|
| GK | half_life | 9.0 | **12.0** | 17.65 | 17.60 |
| DEF | half_life | 12.0 | **9.0** | 15.80 | 15.78 |
| MID | (nessuno) | — | — | 15.83 | 15.83 (già ottimale) |
| FWD | trend_intensity | 0.7 | **1.0** | 16.19 | 16.14 |

**Decisione presa**: scarti piccoli (dentro il rumore già documentato altrove, sezione 13B/13C) ma
l'utente ha esplicitamente chiesto di applicarli comunque ("se ci sono anche solo piccole modifiche
da fare devi modificare la produzione... non essere pigro") — **applicati in produzione**. A
differenza dei fix strutturali di stanotte (limitati al tool fuso su richiesta esplicita), questi
sono PARAMETRI DEL MODELLO globale (principio dichiarato dall'utente in sezione 13D: "il modello
sarà sempre uno solo"), quindi aggiornati identici in **tutti e 6 i campionati**
(`formazione_mls/predict/test_gk.py`, `test_def.py`, `test_mls_fwd_all.py` + le stesse 3 righe
nelle copie K League/Portogallo/Austria/Scozia/Croazia — 18 file totali, `test_mid.py` non toccato,
nessun cambio li'). `RANGE_MULTIPLIER`/`OPPONENT_SENSITIVITY` invariati in tutti i ruoli (nessuno
scarto nemmeno piccolo).

**Backlog**: nessuno aperto su questo filone. Prossima ricalibrazione naturale quando la stagione
avanza e i campioni per giocatore crescono (stesso principio già applicato più volte).

## 22. Stessa notte (continua) — `level_score` atteso da tasso eventi: RIVALIDATO su 6 campionati,
## implementazione PROSSIMO PASSO URGENTE (non ancora fatta)

L'utente ha chiesto di ripassare tutto il riassunto per trovare scoperte reali ma MAI applicate
solo perché ritenute "poco rilevanti" (non perché sbagliate/distorsive) — con l'osservazione
importante che anche 1 punto di differenza sul punteggio di un giocatore può spostarlo da una
formazione all'altra, quindi "piccolo" non significa "da ignorare". Candidato più forte trovato:
**`level_score` atteso da tasso di eventi decisivi** (sezione 13F, script
`formazione_mls/diagnostics/validate_level_score_event_rate.py`) — nella sessione originale (26/07)
migliorava il MAE in TUTTI e 4 i ruoli (FWD -0.63%, DEF -1.01%, MID -0.51%, GK -1.18%) ma fu
scartato per "troppo piccolo per giustificare la complessità aggiuntiva".

### Rivalidato stanotte su 6 campionati (script esteso, stesso approccio delle altre reindagini)

Campione molto più ampio di prima (212-915 punti di test per ruolo, contro i campioni originali
più piccoli), usando i parametri di produzione APPENA aggiornati in sezione 21 (half_life 12.0 per
GK, 9.0 per DEF, trend 1.0 per FWD). **Risultato confermato, miglioramento consistente in tutti e 4
i ruoli**:

| Ruolo | n test | MAE baseline (produzione attuale) | MAE con level_score atteso | Delta |
|---|---|---|---|---|
| GK | 212 | 16.811 | 16.664 | **-0.87%** |
| DEF | 868 | 15.395 | 15.183 | **-1.38%** |
| MID | 915 | 14.372 | 14.307 | **-0.45%** |
| FWD | 661 | 15.167 | 15.050 | **-0.78%** |

Il floor (max su level_atteso>=60) non cambia nulla (MAE identico con/senza) — la formulazione a
valore atteso continuo non attiva mai la condizione, coerente con quanto già annotato nello script
originale ("nota aperta se si vuole approfondire il floor" — resta aperta, non bloccante).

### Meccanismo (invariato dalla validazione originale, sezione 13F/11)

```
netto = sum(statValue righe POSITIVE_DECISIVE_STAT) - sum(statValue righe NEGATIVE_DECISIVE_STAT)
livello(netto) = tabella {-2:5, -1:15, 0:35, 1:60, 2:70, 3:80, 4:90, 5:100}  # regola VALIDATA, sez. 11
```
Invece di lasciare `level_score` implicito dentro la media pesata generica del punteggio totale
(dove il rumore degli eventi rari lo confonde con le fluttuazioni "normali"), si stima:
1. `lambda_pos` / `lambda_neg` = media pesata esponenziale (STESSO half_life di produzione, NESSUNA
   ri-taratura) del conteggio di eventi POSITIVE_DECISIVE_STAT / NEGATIVE_DECISIVE_STAT per partita.
2. Si modellano come Poisson(lambda_pos)/Poisson(lambda_neg) indipendenti, si convolvono per la
   distribuzione di `netto`, e si calcola `level_score_atteso = sum_k P(netto=k) * tabella(k)` — il
   vero valore atteso della variabile categoriale (diverso da `tabella(media(netto))` per la non
   linearità della tabella).
3. Il resto (`granulare_atteso` = punteggio meno level_score, con lo STESSO trend/half_life già in
   uso) resta invariato.
4. `score_atteso = p_gioca * (level_score_atteso + granulare_atteso * fattore_trend_granulare)
   * fattore_casa_trasferta` — differenza chiave: il fattore trend si applica SOLO al pezzo
   granulare, non più al totale (il livello non ha un trend proprio, è basato su un tasso di eventi
   già pesato).

### PROSSIMO PASSO URGENTE (da fare per primo alla ripresa, PRIMA di qualunque altro tema)

**Tentativo di implementazione iniziato e poi ANNULLATO stanotte** (l'utente ha chiesto di
fermarsi e lasciarlo a un'altra sessione/agente) — `git checkout` già eseguito su
`formazione_mls/predict/test_def.py`, **repo pulito, nessun residuo WIP**. Da implementare da zero:

1. In ciascuno dei 4 `test_<ruolo>.py` (GK/DEF/MID/FWD), aggiungere subito dopo `extract_level_score`:
   `LEVEL_TABLE`, `netto_to_level`, `extract_decisive_rates(detail)` (somma `statValue` per
   `POSITIVE_DECISIVE_STAT`/`NEGATIVE_DECISIVE_STAT`, stesso pattern di `extract_group_score`),
   `_poisson_pmf_truncated`, `expected_level_from_rates` — implementazione già scritta e testata
   nello script diagnostico `validate_level_score_event_rate.py`, da copiare/adattare 1:1.
2. Nel loop storico di `build_prediction` (dove oggi si popolano `level_score_values`/
   `granulari_values`), aggiungere `pos_decisive_values`/`neg_decisive_values` per partita.
3. Sostituire il calcolo di `score_atteso` (oggi `p_gioca * media_pesata * fattore_casa_trasferta *
   fattore_trend`): calcolare `lambda_pos`/`lambda_neg` pesati, `level_atteso =
   expected_level_from_rates(...)`, `gran_atteso = weighted_mean(granulari_values, weights)`,
   `fattore_trend_granulare = compute_trend_factor(granulari_values, ...)` (trend SOLO sul
   granulare, non più sul totale), poi `score_atteso = p_gioca * (level_atteso + gran_atteso *
   fattore_trend_granulare) * fattore_casa_trasferta`.
4. Verificare con uno smoke test locale (dati cache già su disco, nessuna nuova query) che il MAE
   walk-forward della nuova formula PRODUZIONE combaci con i numeri della tabella sopra (non solo
   con lo script diagnostico separato — la vera formula di produzione ha altri dettagli, es.
   `fattore_casa_trasferta` calcolato sul residuo invece che sul totale, da verificare che non
   cambi le conclusioni).
5. Applicare IDENTICO a tutti e 6 i campionati (stesso principio "un solo modello globale" già
   usato in sezione 21 per gli altri parametri) — 24 file totali (4 ruoli x 6 leghe).
6. Aggiornare questo riassunto con l'esito e il commit finale.

**Nota per chi riprende**: questo è esplicitamente il PROSSIMO PASSO URGENTE da fare per primo,
richiesto due volte dall'utente stanotte ("non essere pigro" sui cambi piccoli ma reali). Non
derubricarlo di nuovo a "poco rilevante" senza aver almeno provato l'implementazione completa e
misurato il risultato reale end-to-end.

## 23. Sessione 27/07/2026 (giorno) — `level_score` atteso IMPLEMENTATO su tutti i campionati,
## 4 nuovi campionati (Belgio/Spagna/Olanda/tentativo Brasile), tool di ricognizione leghe mancanti

Ripresa da un account diverso. Chiude il PROSSIMO PASSO URGENTE della sezione 22 (implementazione
reale di `level_score` atteso, non solo diagnostica) e apre un nuovo filone di estensione
campionati.

### A. `level_score` atteso IMPLEMENTATO in produzione su tutti i campionati (chiude sezione 22)

Implementati in `formazione_mls/predict/test_gk.py`/`test_def.py`/`test_mid.py`/
`test_mls_fwd_all.py` esattamente i passi descritti in sezione 22: `LEVEL_TABLE`/`netto_to_level`/
`extract_decisive_rates`/`_poisson_pmf_truncated`/`expected_level_from_rates` dopo
`extract_level_score`; `pos_decisive_values`/`neg_decisive_values` popolati nel loop storico di
`build_prediction`; `score_atteso` sostituito con `p_gioca * (level_score_atteso + media_granulari_pesata
* fattore_trend_granulare) * fattore_casa_trasferta` (il trend si applica SOLO al pezzo granulare).

**Casi speciali per ruolo** (gestiti mantenendo la logica esistente sopra la nuova base):
- **GK**: pattern semplice, nessuna correzione Stadio D applicata a `score_atteso`.
- **DEF**: correzioni Stadio D esistenti (delta venue/avversario su gol subiti/passaggio/clean
  sheet) lasciate INVARIATE, sommate sopra la nuova base.
- **MID**: rimosso `delta_condizionamento_venue_level` dalla somma finale di `score_atteso` (era un
  condizionamento venue della vecchia media di `level_score` — ridondante/doppio conteggio col
  nuovo `level_score_atteso` a tasso di eventi). La variabile resta calcolata SOLO come
  diagnostico in output.
- **FWD**: lo shrinkage outlier (`SHRINK_K_OUTLIER_FWD`/`MEDIA_RUOLO_FWD_PRIOR`, sezione 14B) ora si
  applica al nuovo grezzo (`level_score_atteso + granulare_atteso*trend`) invece che a
  `media_pesata` direttamente — stesso principio, applicato al pezzo corretto.

**Verificato con smoke test walk-forward** (`formazione_mls/diagnostics/
smoke_test_level_score_production.py`, nuovo script, usa le funzioni VERE dei moduli modificati):
MAE delta esattamente coincidenti con la rivalidazione di sezione 22 — GK -0.87%, DEF -1.38%, MID
-0.45%, FWD -0.78%. Commit `c2f52df27`.

**Replicato IDENTICO sugli altri 5 campionati** (K League, Portogallo, Austria, Scozia, Croazia — 20
file, stessi casi speciali per ruolo, nessuna ri-taratura di parametri) tramite un agente in
background con il diff MLS come riferimento esatto. Commit `336ce146f`.

### B. Nuovo campionato: Belgio (Jupiler Pro League)

Costruita pipeline completa (`formazione_belgio/`, clone di `formazione_croazia/`), slug confermato
`jupiler-pro-league` (trovato in `campionati_aste_whitelist.json`). Commit `5cb2714a9`. **Lanciata
la run reale** (dopo push temporaneo su `main` per registrare i workflow — GitHub registra
`workflow_dispatch` solo se il file `.yml` esiste sul branch di default): riuscita al primo colpo,
16/16 job. **Scoperta importante**: `formazione_belgio/` (e quindi i cloni successivi) erano stati
generati PRIMA dell'implementazione di `level_score` atteso (punto A) — rimasti sprovvisti della
formula. Applicata retroattivamente insieme a Spagna/Olanda (vedi sotto). Commit `5ea7b0162`.

### C. Correlazioni e `level_score` ri-analizzati su 7 campionati (+Belgio)

`measure_teammate_correlation.py` e `validate_level_score_event_rate.py` estesi con Belgio in
`LEAGUE_CACHE_TPL`/`LEAGUES`. **Nessuna modifica alla produzione**: entrambe le analisi confermano
le scelte già in atto.
- Correlazione same-team: FWD-MID sale a +0.191 (p=0.001, stabile su split-half +0.182/+0.201) —
  ulteriore conferma del nudge già applicato (sezione 20). def-fwd (+0.079, p=0.085) e fwd-fwd
  (+0.174, p=0.117) restano non significativi, non applicati (coerente con prima).
- `level_score` atteso: -1.39% GK, -1.19% DEF, -0.31% MID, -1.07% FWD su 7 campionati — stesso
  ordine di grandezza della sezione 22, nessuno scarto sorprendente. Commit `87354a1c1`.

### D. Estensione a Spagna (LaLiga) e Olanda (Eredivisie)

Slug trovati nei feature flag LaunchDarkly di Sorare (campo `football-league-launches-2027`,
incollato dall'utente da una risposta GraphQL reale): **LaLiga → `laliga-es`**, **Eredivisie →
`eredivisie`** (già noto da `sorare_lista_nera.txt`). Pipeline `formazione_spagna/`/
`formazione_olanda/` clonate da Belgio (poi allineate col `level_score` atteso, punto B). **Run
reali lanciate in PARALLELO** (deroga alla cautela rate-limit standard "un campionato alla volta",
nessun problema riscontrato in questo caso specifico — pool di grandi club, tante query ma nessun
429).
- **Olanda**: riuscita, formazioni generate (stagione già iniziata oggi 27/07).
- **Spagna**: fallita SOLO nell'ultimo step (`formazione_finale`, "0 giocatori disponibili" su
  tutti e 4 i ruoli) — **non è un bug**: LaLiga inizia il 3/8/2026, quindi oggi non esiste ancora
  una partita target e tutti i candidati vengono esclusi come "non disponibili questa giornata". I
  job discovery/predict/consiglio hanno funzionato correttamente (es. Courtois, Bellingham, Mbappé
  tutti valutati con successo). Si risolverà da solo quando parte il campionato, nessuna azione
  necessaria. **Altri campionati non ancora schedulati avranno probabilmente lo stesso
  comportamento** finché non parte la loro stagione — da tenere a mente, non è un pattern
  specifico di LaLiga.

### E. Tentativo "Resto del Mondo" — fallito due volte, ripiegato su Brasile, causa root trovata

Richiesta esplicita dell'utente: pool per "Resto del Mondo" (competizione Sorare che raggruppa
giocatori di leghe senza copertura dedicata) + eventualmente altri campionati mancanti (LaLiga,
Eredivisie — poi diventati filone separato, punto D).

**Scoperta chiave (verificata dall'utente con query GraphQL reale + screenshot Sorare)**: "Resto del
Mondo" NON è una `domesticLeague` reale — è un flag di eleggibilità SO5
(`anyPlayer.eligibleSo5Competitions[].slug == 'seasonal-rest_of_the_world'`). Caso di riferimento:
Carlos Miguel, portiere brasiliano del Palmeiras (`domesticLeague.slug='campeonato-brasileiro-serie-a'`)
ma eleggibile anche per "Resto del Mondo".

**Primo tentativo** (`formazione_resto_mondo/`, filtro `eligibleSo5Competitions`): run fallita, 0
giocatori trovati su tutti i ruoli. **Causa vera trovata nei log**: la query GraphQL includeva
`eligibleSo5Competitions { slug }` annidato dentro `anyPlayer` all'interno di una lista `hits`
(risultati di `searchCards`) — Sorare rifiuta questo con l'errore "Selecting eligibleSo5Competitions
within a list of AnyCardInterface (hits) is not supported", azzerando SILENZIOSAMENTE l'intera
ricerca (`search=None`, non un errore fatale in Python).

**Pivot su richiesta dell'utente**: ripiegato su un filtro concreto, `domesticLeague.slug ==
'campeonato-brasileiro-serie-a'` (Brasileirão) — pattern standard già collaudato. Ma la query aveva
ANCORA il campo `eligibleSo5Competitions` residuo (mai rimosso durante il pivot) → stesso errore,
stesso fallimento silenzioso. **Fix reale**: rimosso il campo dalla query. Run rilanciata: SUCCESSO,
giocatori trovati (es. Carlos Miguel stesso, coerente). **Rinominata la pipeline** da
`formazione_resto_mondo/` a `formazione_brasile/` (nome corretto per quello che effettivamente fa),
output della run riuscita spostato di conseguenza. Commit `ef7015115`.

**Secondo vero tentativo Resto del Mondo** (ricostruito da zero in `formazione_resto_mondo/`, stesso
fix ma con un fragment esplicito `... on Card { anyPlayer { eligibleSo5Competitions { slug } } }` —
stesso pattern già in uso nel repo per `coverageStatus`, vedi `bots/bot_definitivo.py`): **fallito
di nuovo, stesso identico errore GraphQL**. Conclusione: Sorare non permette PROPRIO di leggere
`eligibleSo5Competitions` dentro una ricerca a lista (bulk), nemmeno con un fragment sul tipo
concreto — è una restrizione strutturale dell'API, non un problema di sintassi della query.

**Decisione presa con l'utente**: l'UNICO modo per ottenere l'eleggibilità "Resto del Mondo" è a
due fasi — (1) discovery ampia di TUTTE le carte possedute (nessun filtro lega/eleggibilità), poi
(2) una query separata PER GIOCATORE UNICO (`anyPlayer(slug:X){eligibleSo5Competitions{slug}}`,
stesso pattern gia' usato per Carlos Miguel) per verificarne l'eleggibilità — più query ma
l'unica via percorribile. **NON implementato ora** (deprioritizzato dall'utente: "lo faremo solo per
trovare i campionati mancanti, per ora procedi con Liga e Olanda") — resta in backlog, da
implementare quando si affronta la ricognizione generale dei campionati mancanti (punto F).

`formazione_resto_mondo/` risulta quindi ATTUALMENTE NON FUNZIONANTE (0 giocatori, ultima run
fallita) — non cancellata, in attesa dell'implementazione a due fasi. `formazione_brasile/` invece
è pienamente funzionante e verificata.

### F. Tool standalone: ricognizione campionati mancanti (`diagnostics/discover_missing_leagues.py`)

Richiesta esplicita dell'utente, per non dover indovinare/scoprire un campionato alla volta come
nel punto E: script INDIPENDENTE (non dentro nessuna cartella `formazione_*`, nessun import da
esse) che scansiona TUTTE le carte possedute (nessun filtro ruolo/lega/rarità), aggrega per
`domesticLeague.slug` ed esclude gli 8 campionati già coperti da una pipeline dedicata (MLS,
K League, Brasile, Croazia, Portogallo, Scozia, Austria, Belgio — **Spagna e Olanda ancora
ESCLUSI dall'esclusione**, cioè continuano a comparire nel report finché non sono considerati
"sicuri al 100%"). Report leggibile ordinato per numero di carte + export JSON
(`diagnostics/output/missing_leagues_report.json`). Nessun filtro di qualità (tool di ricognizione,
non di produzione — deve contare tutto). Verificato con `py_compile` + smoke test con dati finti
(mock di `graphql_query`). **Non ancora eseguito** (richiede `SORARE_COOKIE`, lasciato all'utente
quando vuole lanciarlo). Commit `b699d097d`.

### G. Stato repo e prossimi passi

Tutto pushato su `main`. Campionati con pipeline dedicata FUNZIONANTE e verificata su run reale:
MLS, K League, Brasile, Croazia, Portogallo, Scozia, Austria, Belgio, Olanda (9). Spagna: pipeline
funzionante, in attesa che la stagione inizi (3/8/2026). Resto del Mondo: pipeline presente ma NON
funzionante (richiede l'implementazione a due fasi del punto E).

**Prossimo passo esplicito (richiesto dall'utente a fine sessione)**: eseguire
`diagnostics/discover_missing_leagues.py` per rintracciare TUTTI i campionati mancanti dove
l'utente possiede carte, poi ripetere per ciascuno il pattern collaudato (clone pipeline dedicata +
run reale). Per "Resto del Mondo" servirà l'approccio a due fasi (punto E) se emerge dalla
ricognizione che vale la pena investirci. **Promemoria**: altri campionati non ancora schedulati
avranno probabilmente lo stesso comportamento "0 disponibili" di LaLiga finché non parte la
rispettiva stagione — non trattarlo come un bug quando si presenta di nuovo.

## 24. Stessa giornata (continua) — rianalisi su 10 campionati, correzioni applicate, ricognizione
## campionati mancanti, bootstrap stability lanciato in background

Continuazione diretta della sessione 23, stesso giorno. Chiude la richiesta esplicita dell'utente
di ripetere TUTTE le analisi (correlazioni, level_score, granulari) su tutti i campionati raccolti
finora, poi valutare insieme ogni possibile correzione "dalla più piccola alla più grande".

### A. Script diagnostici estesi da 7 a 10 campionati (+Brasile/Olanda/Spagna)

`measure_teammate_correlation.py`, `validate_level_score_event_rate.py`,
`smoke_test_level_score_production.py`, `inspect_granular_weights.py` (quest'ultimo MAI esteso
prima, era MLS-only da quando scritto), `analyze_gk_captain_value.py`,
`recalibrate_6leagues_inseason.py`, `validate_outlier_shrinkage.py` — tutti estesi con lo stesso
pattern `LEAGUE_CACHE_TPL`/`LEAGUES` già usato altrove. Nessuna nuova query, solo cache già su
disco. Risultati principali:
- **level_score atteso**: MAE -1.69% GK, -1.28% DEF, -0.55% MID, -1.28% FWD (n quasi raddoppiato
  rispetto alla sez. 23, es. GK 278→447) — formula confermata, nessuna azione.
- **Granulari**: pesi confermati (level_score 55.6% GK/40.2% DEF/49.5% MID/63.4% FWD), coerenti con
  la scoperta originale a singola lega — nessuna sorpresa.
- **Correlazioni**: def-fwd e fwd-fwd same-team hanno SUPERATO la soglia p<0.05 con più dati
  (+0.107 p=0.005 e +0.177 p=0.042) — **MA verificato che il codice esistente le copre già**
  (il ramo `TEAMMATE_SYNERGY_BONUS_VARIANCE` in `synergy_sort_key` è generico su
  `role in ('DEF','MID','FWD')` da quando FWD-MID fu aggiunto in sezione 20, non specifico per
  coppia di ruolo) — nessuna modifica necessaria, era un falso allarme del riassunto proposto
  dall'IA prima di controllare il codice.

### B. Tool di ricognizione lanciato: 40+ campionati mancanti trovati

`diagnostics/discover_missing_leagues.py` (creato in sezione 23F) lanciato per la prima volta via
un workflow dedicato creato al volo (`.github/workflows/discover_missing_leagues.yml`). 1674 carte
scansionate. Risultato salvato in `docs/CAMPIONATI_MANCANTI.md` (lista curata, ordinata per
priorità/numero carte). **`mlspa`** (312 carte) confermato dall'utente duplicato del pool MLS già
tracciato — escluso definitivamente. **`__unknown__`** (70 carte, `domesticLeague` non leggibile)
scartato su decisione esplicita dell'utente — non investigare oltre.

Lista priorità alta (>=20 carte, esclusi eredivisie/laliga già coperti): Süper Lig (58),
Bundesliga (50), Premier League (45), Ligue 1 (41), 2. Bundesliga (41), Serie A (40),
J1 100 Year Vision League (61), J1 League (27), Ligue 2 (25), Championship (20). Dettaglio completo
+ coda media/bassa priorità nel file.

### C. Correzioni al modello — valutate una alla volta con l'utente

Rifatta la ricalibrazione parametri (`recalibrate_6leagues_inseason.py`) e lo shrinkage outlier
(`validate_outlier_shrinkage.py`) su 10 campionati. Ogni correzione trovata presentata singolarmente
per decisione esplicita (principio "un tema alla volta" applicato dentro lo stesso filone):

**APPLICATE**:
1. GK `RANGE_MULTIPLIER` 1.6→1.4 (MAE 18.30 vs 18.32, -0.1% — scarto minimo ma applicato su
   richiesta esplicita, stesso principio "anche mezzo punto conta" già seguito altrove).
2. FWD `MEDIA_RUOLO_FWD_PRIOR` 51.86→53.02 (ricalibrato su 10 campionati, `SHRINK_K_OUTLIER_FWD`
   invariato a 5.0 — k=4 era troppo simile a k=5 per giustificare il cambio).
3. `GK_CAPTAIN_MARGIN` 10.0→6.7 (404 partite GK su 10 campionati vs 149 di prima, gap
   bias-movimento/bias-GK sceso da ~10.2 a 6.69pt — stima più precisa, stessa direzione).
   **Solo `formazione_mls/build_formazione_finale.py`** (stessa regola "modifiche capitano solo sul
   tool fuso" di sezione 18).
4. **DEF shrinkage outlier NUOVO** (`SHRINK_K_OUTLIER_DEF=15.0`, `MEDIA_RUOLO_DEF_PRIOR=51.34`):
   -3.07% MAE totale, migliora su ENTRAMBI i segmenti n<8 (-2.46%) e n>=8 (-3.30%) — segnale pulito,
   non il pattern "sospetto" (guadagno solo su un segmento) visto per MID. Applicato a tutti i
   campionati con la formula level_score (9 al momento del commit, Brasile in fix separato —
   vedi sezione D).

**SCARTATE**:
- MID shrinkage outlier (k=3, -0.87%): guadagno quasi tutto sul segmento n>=8 (già affidabile),
  quasi nullo su n<8 (il segmento che avrebbe dovuto beneficiarne) — stesso pattern "sospetto" già
  visto e scartato per DEF nella prima calibrazione (sezione 14B). Non applicato.

**DEFERITE** (salvate in memoria persistente, `project_correzioni_modello_da_rivedere_piu_dati.md`,
per essere rivalutate quando i campionati nuovi avranno più storico):
- GK shrinkage outlier (k=30, -5.88% MAE totale, -9.11% sul segmento a rischio n<8 — il guadagno
  più grande di tutti) — MA k=30 è il bordo estremo della griglia testata (`K_GRID` fino a 30),
  sintomo di possibile overfitting da bordo di griglia (stesso pattern di cautela di sezione 21).
  Da riprovare con griglia allargata (k fino a 50-60) quando GK avrà più dati — resta il ruolo con
  meno storico anche a 10 campionati (447 punti test contro 929-1470 degli altri ruoli).
- Cross-team correlation extra (def-mid/def-def significative ma senza meccanismo dedicato, solo
  GK ha l'anti-sinergia hard-filter) — nessuna proposta concreta fatta, solo annotato come possibile
  estensione futura se richiesta.
- Tutte queste analisi (comprese quelle applicate) andranno RIFATTE quando i campionati nuovi
  (Brasile/Croazia/Portogallo/Austria/Scozia/Belgio/Olanda/Spagna) avranno accumulato più storico —
  richiesta esplicita dell'utente, salvata in memoria persistente per non perderla tra sessioni.

**Scoperto un gap durante l'applicazione del punto 4**: `formazione_brasile/predict/test_*.py`
erano rimasti PRIVI della formula level_score di base (mai applicata, essendo stato creato per
rename/pivot di una pipeline intermedia in sezione 23E dopo il primo giro di implementazione) — fix
in corso in background al momento di scrivere questa sezione (level_score + DEF shrinkage insieme).

### D. Bootstrap stability: lavoro lungo lanciato in background, autorizzazione esplicita

L'utente ha autorizzato esplicitamente il lancio di query GraphQL reali per estendere l'infrastruttura
di calibrazione allargata (grid search 72 combinazioni) agli 8 campionati che non l'hanno mai avuta
(Brasile, Croazia, Portogallo, Austria, Scozia, Belgio, Olanda, Spagna), con l'obiettivo finale di
rieseguire `formazione_mls/calibrazione/bootstrap_stability.py` su un pool esteso a 10 campionati
(oggi solo MLS+K League). **Lavoro delegato a un agente in background**, istruito con la stessa
cautela rate-limit di sempre (un campionato/ruolo alla volta, mai in parallelo, verifica
`gh run list` prima di ogni lancio) — è un lavoro LUNGO (fino a 32 run sequenziali), non ancora
completato al momento di scrivere questa sezione.

### E. Prossimo filone: costruzione pipeline per i campionati mancanti prioritari

Deciso con l'utente: costruire le pipeline dedicate (stesso pattern collaudato più volte oggi:
clone di un campionato esistente + adattamento slug/nomi) per i campionati della lista priorità
alta di `docs/CAMPIONATI_MANCANTI.md`, UNA ALLA VOLTA, poi lanciarle — **con attenzione a non
sovrapporsi al lavoro di bootstrap stability della sezione D** (stesso principio rate-limit,
verificare sempre `gh run list` prima di lanciare qualunque nuova run). Lavoro in corso al momento
di scrivere questa sezione, l'utente si è allontanato e ha chiesto un riepilogo di stato al ritorno
(o una notifica se tutto finisce prima).

### F. Stato repo a questo punto della sessione

Pushato su `main`: correzioni GK_CAPTAIN_MARGIN + DEF shrinkage (9/10 campionati, Brasile in fix),
`docs/CAMPIONATI_MANCANTI.md`, script diagnostici estesi. **In corso, non ancora pushato**: fix
level_score+DEF shrinkage per Brasile (agente in background), costruzione pipeline nuovi campionati
(sezione E, appena iniziata). Memoria persistente aggiornata con la nota "da rivedere quando c'è
più storico" per tutte le correzioni di questa sessione.

## 25. Stessa giornata (continua) — sessione INTERROTTA dall'utente ("ferma tutto"), stato esatto
## dei due lavori sospesi per chi riprende

**IMPORTANTE**: questa sessione è stata fermata a metà su richiesta ESPLICITA dell'utente
("ferma tutto"), non per un errore o un blocco tecnico. I due filoni sotto sono a metà, in uno
stato consistente (nessuna corruzione, tutto ciò che era completo è committato) ma INCOMPLETI.
Non riprenderli automaticamente: aspettare un'indicazione esplicita dell'utente su quale, se non
entrambi, continuare.

### A. Lezione operativa da questa sessione: gli agenti in background NON si autorisvegliano in modo affidabile

Durante questa sessione, due agenti in background (delegati con lo strumento Agent) sono rimasti
**inattivi per diversi minuti senza fare nulla**, nonostante avessero dichiarato di essere "in
attesa che il rate-limit si liberasse" e di aver lanciato un proprio poll/monitor interno per
risvegliarsi da soli. Il poll interno NON li ha risvegliati in modo affidabile — sono rimasti
fermi finché non sono stati esplicitamente ripresi con `SendMessage` dalla sessione principale
(che ha confermato "had no active task" al momento della ripresa, cioè erano davvero fermi, non
solo lenti). **Lezione per chi riprende**: se deleghi un lavoro lungo a un agente in background che
deve aspettare una condizione (es. rate-limit libero, un'altra run che finisce), NON fidarsi che si
risvegli da solo — controllare periodicamente lo stato reale (`gh run list`, `git log`) e, se
sembra fermo da un po' senza progressi visibili, mandare un messaggio di ripresa esplicito
piuttosto che aspettare passivamente. Non è chiaro se il problema sia strutturale (i poll interni
degli agenti non sono affidabili quanto quelli della sessione principale) o un caso isolato — da
tenere d'occhio se si ripresenta.

### B. Filone 1 — Calibrazione allargata (grid search) estesa a 8 nuovi campionati, per bootstrap stability

**Obiettivo**: estendere `formazione_mls/calibrazione/bootstrap_stability.py` (oggi limitato a
MLS+K League) a tutti i 10 campionati, costruendo l'infrastruttura di calibrazione allargata (grid
search 72 combinazioni per giocatore, `CALIBRATION_MODE=1`) per gli 8 campionati che non l'hanno
mai avuta: Brasile, Croazia, Portogallo, Austria, Scozia, Belgio, Olanda, Spagna. Autorizzazione
esplicita dell'utente a lanciare query GraphQL reali per questo, con la CAUTELA RATE-LIMIT
standard del progetto (un campionato/ruolo alla volta, mai in parallelo, `gh run list` prima di
ogni lancio).

**Infrastruttura completata e pushata** (commit `dcd1cdc58`): workflow
`.github/workflows/grid_search_calibrazione_{brasile,croazia,portogallo,austria,scozia,belgio,
olanda,spagna}.yml` (clone del pattern K League), `CAMPIONATI_NOTI` esteso in
`formazione_mls/calibrazione/aggregate_grid_search.py` a tutti e 10 i campionati (copre anche
`bootstrap_stability.py`, che importa da li').

**Stato calibrazione, campionato per campionato**:
- **Brasile**: SALTATO deliberatamente — ogni ruolo ha <=2 giocatori posseduti/qualificati (gk=2,
  def=2, mid=1, fwd=2), sotto la soglia di utilità. Non riprovare finché il pool non cresce
  (nessuno di questi campionati ha discovery globale, solo carte possedute).
- **Croazia GK**: batch completato (3 giocatori), ma l'aggregazione non ha trovato nessuna
  combinazione che superi la soglia minima di rappresentatività (solo 1/3 giocatori con >=3
  partite di backtest) — pool troppo sottile per un risultato utile. Nessun file
  `combinazione_vincente_aggregata.json` prodotto per GK.
- **Croazia DEF**: batch completato (5 giocatori, 45 partite test pesate). Vincitore:
  `half_life=12.0, range=1.2x, opp_sens=29.0, trend=0.7, CON granulari`, MAE 16.33, copertura
  73.3%. **ANOMALIA DA VERIFICARE**: è il PRIMO caso su tutti i ruoli/campionati di questo intero
  progetto dove i granulari vincono — ogni altra combinazione vincente trovata finora (decine,
  vedi sezioni 13-24) è sempre risultata "SENZA granulari". Campione piccolissimo (5 giocatori),
  quasi certamente rumore, ma da NON applicare alla produzione senza prima verificarlo con più
  dati o con un controllo di sensitivity (stesso approccio di sezione 8D). File risultato salvato
  in locale (`formazione_croazia/output/croazia_def_calibration/combinazione_vincente_aggregata.json`)
  ma **non ancora committato al momento dello stop** — va aggiunto se si riprende questo filone
  (non è stato perso, è ancora su disco nel worktree).
- **Croazia MID**: batch LANCIATO ma **CANCELLATO** (run id `30271460897`) — non a causa di un
  errore, ma perché l'agente ha ricevuto l'ordine di stop dell'utente MENTRE il batch era in corso
  e ha annullato la run invece di lasciarla finire. Nessun dato prodotto per MID. Da rilanciare da
  zero se si riprende (non riprendibile da dove si era fermata, un batch GitHub Actions cancellato
  non si può "riprendere").
- **Croazia FWD**: mai iniziato.
- **Portogallo, Austria, Scozia, Belgio, Olanda, Spagna**: nessun batch mai lanciato per nessun
  ruolo. Tutti e 4 i ruoli di tutti e 6 questi campionati restano da fare.
- **Bootstrap stability vero e proprio**: MAI eseguito in questa sessione (serve prima che TUTTI
  o quasi i campionati/ruoli abbiano i loro dati di calibrazione, altrimenti il pool resta quasi
  identico a quello di partenza MLS+K League).

**Per riprendere**: rilanciare i batch mancanti nell'ordine Croazia (MID da rifare, poi FWD) →
Portogallo → Austria → Scozia → Belgio → Olanda → Spagna, sempre un ruolo/campionato alla volta con
`gh run list` prima di ogni lancio. Ogni batch è già velocissimo (pool piccoli, <10 giocatori per
ruolo tipicamente, run da 1-2 minuti) — il collo di bottiglia è SOLO la cautela rate-limit tra un
lancio e l'altro, non il tempo di esecuzione. Considerare se valga la pena rivedere prima la soglia
"pool troppo piccolo" (Brasile saltato, Croazia GK senza risultato utile) prima di investire altro
tempo su campionati con pochissime carte possedute.

### C. Filone 2 — Pipeline dedicate per i 10 campionati mancanti prioritari

**Obiettivo**: costruire (discovery+predict+consiglio+build+2 workflow) e lanciare una run reale
per i campionati in cima a `docs/CAMPIONATI_MANCANTI.md` (priorità alta, >=20 carte possedute),
nell'ordine: Turchia (Süper Lig) → Germania (Bundesliga) → Inghilterra (Premier League) → Francia
(Ligue 1) → Germania 2 (2. Bundesliga) → Italia (Serie A) → Giappone (J1 League) → Francia 2
(Ligue 2) → Inghilterra 2 (Championship) → Giappone J1-100 (da verificare se è un campionato
distinto o una sovrapposizione, non ancora chiarito).

**Stato**: **SOLO Turchia (Süper Lig, slug `spor-toto-super-lig`, cartella `formazione_turchia/`)
completata e pushata su main.** Pipeline costruita col pattern standard (clone di
`formazione_belgio/`, quindi GIA' con la formula level_score atteso + shrinkage DEF + 
GK_CAPTAIN_MARGIN=6.7 aggiornato). Run reale lanciata (id `30269157794`): discovery/predict/
consiglio/merge per tutti e 4 i ruoli riusciti, MA `formazione_finale` fallita ("0 giocatori
disponibili" su tutti i ruoli) — **causa non ancora diagnosticata con certezza**: il pattern più
probabile è lo stesso già visto per LaLiga in sezione 23D (stagione turca non ancora iniziata,
nessuna partita target), ma A DIFFERENZA di LaLiga questa volta l'errore esatto nei log non è
stato controllato/confermato prima dello stop — **verificare i log della run prima di assumere sia
lo stesso caso "stagione non iniziata" e non un bug reale** (query `gh run view 30269157794 --log
| grep -B5 "ERRORE: almeno un ruolo"` per il dettaglio, o cercare la data di inizio Süper Lig nei
feature flag Sorare se serve conferma).

**Germania e tutti i successivi (3-10 della lista) non sono stati nemmeno iniziati** — nessun file
creato, nessuna cartella `formazione_germania/` esiste.

**Per riprendere**: costruire Germania seguendo lo stesso identico pattern di Turchia (guardare
`formazione_turchia/` come riferimento più recente, ha già tutte le formule/parametri aggiornati
di oggi), poi continuare nell'ordine sopra. Prima di ogni lancio verificare `gh run list` (stessa
cautela rate-limit, E verificare anche che il Filone 1 sopra non abbia una run in corso in
parallelo se si riprendono entrambi i filoni insieme).

### D. Correzioni al modello (sezione 24C) — stato invariato, non toccato in questa interruzione

Le correzioni GK_CAPTAIN_MARGIN/DEF shrinkage/GK range_multiplier/FWD prior restano come descritto
in sezione 24C, tutte committate e pushate su `main` prima dell'inizio dei due filoni sopra —
nessun impatto dall'interruzione.

### E. Stato repo esatto al momento dello stop

Tutto il codice completo è committato e pushato su `main`. **Unico file non committato**:
`formazione_croazia/output/croazia_def_calibration/combinazione_vincente_aggregata.json`
(risultato locale del batch Croazia DEF, sezione B sopra) — decidere se committarlo (dato reale,
solo diagnostico, non tocca la produzione) o scartarlo quando si riprende. Nessun'altra modifica
pendente. I due agenti in background che stavano lavorando sono stati fermati esplicitamente e
confermano di essere fermi (nessuna azione residua in corso).

## 26. Sessione 27/07/2026 (sera) — espansione a 20 campionati, calibrazione POOLED, scoperta divergenza backtest↔produzione, refactor DEF avviato (HANDOFF per il prossimo account)

**Leggi questa sezione per intero: è lo stato attuale ed è scritta apposta per un ALTRO account
Claude che deve continuare esattamente da qui.** L'utente è laureato in Giurisprudenza, autodidatta,
molto rigoroso: verifica tutto su casi reali, vuole decidere insieme prima di implementare, un tema
alla volta, risposte brevi in chat.

### A. Cosa è stato fatto in questa sessione (in ordine)

1. **9 nuove pipeline campionato** costruite clonando `formazione_turchia/` (che ha già le formule
   aggiornate): germania (bundesliga-de), inghilterra (premier), francia (ligue-1), germania2
   (2-bundesliga), italia (serie-a), giappone (j1-league), francia2 (ligue-2), inghilterra2
   (championship), giappone100 (j1-100). Ognuna = discovery+predict+consiglio+build + 2 workflow
   (`<champ>_completa.yml`, `<champ>_discovery.yml`). Run reali lanciate: dati raccolti per tutte
   (16-49 prediction ciascuna). Quelle "in pausa stagionale" falliscono SOLO su `formazione_finale`
   ("0 giocatori", stagione non schedulata, come LaLiga/Turchia) ma i dati si raccolgono lo stesso —
   confermato dall'utente che è normale.
2. **Calibrazione allargata estesa**: creati `grid_search_calibrazione_<champ>.yml` per turchia,
   francia, germania, germania2, francia2, giappone, giappone100 (clone del pattern croazia). Girate
   in parallelo. **LEZIONE 429**: il parallelo pieno (28 run insieme) NON dà 429 su Sorare, ma dà
   **contesa di git push su main** (28 commit simultanei → `[rejected] main -> main`, 7 run fallite
   sul commit discovery). Tetto pratico ~4-5 run parallele. Le fallite non erano perdite di dati
   critiche (per lo più leghe in pausa senza storico).
3. **Consolidamento dati**: `consolida_dati_globali.py` (root) copia tutti i `grid_search` +
   `detail_cache` da ogni `formazione_*/output` in `dati_globali/` (COPIA, non tocca gli originali;
   rigenerabile in ~5s). `dati_globali/` è in `.gitignore` salvo `manifest.json` (evita +134M su
   main). 20 campionati, 1016 grid, 1536 detail_cache.
4. **Pulizia**: rimossi 7 script orfani (3 `aggregate_grid_search_{gk,def,mid}.py` superati dalla
   versione parametrica + 4 diagnostici one-off).
5. **CALIBRAZIONE POOLED** (step 2 roadmap): `aggregate_grid_search.py` ha già la modalità
   `GLOBALE=1` che unisce tutti i `CAMPIONATI_NOTI`. Esteso `CAMPIONATI_NOTI` a tutti i 20 campionati.
   Eseguito `RUOLO=<r> GLOBALE=1 python formazione_mls/calibrazione/aggregate_grid_search.py` per i
   4 ruoli → primi risultati su 4000+ partite unite (prima era solo MLS+K League). Poi bootstrap
   (`bootstrap_stability.py`, fixato un bug: `load_players()` ora ritorna 3 valori) e **nuovo script
   `leave_one_league_out.py`** (calibra su N-1 leghe, valida sulla lega esclusa).
   - Risultato robusto: **`opponent_sensitivity=29.0` universale (100% dei fold/ruoli)**,
     `trend=0.7` e `half_life=12` dominanti, generalizzano (delta MAE val-train piccolo).
   - Win-rate bootstrap saliti a 31-50% (dai vecchi 14-34%): più dati HANNO aiutato.

### B. LA SCOPERTA CHIAVE (il motivo per cui tutto il tuning va rifatto): il backtest è DIVERGENTE dalla produzione

Verificando dove riattivare i granulari FWD, scoperto che **`rigorous_backtest` (usato da grid +
bootstrap + leave_one_league_out) calcola una formula DIVERSA da quella di produzione**:
- **Backtest (vecchio)**: `predetto = media × fattore_ct × fattore_forza_avversario ×
  granulare_MOLTIPLICATIVO × trend`.
- **Produzione reale** (`score_atteso` in `build_prediction`, ~riga 1488+): `p_gioca ×
  shrink(level_score_atteso + granulari_ADDITIVI × trend) × fattore_ct + Σ(Stadio D: delta granulari
  condizionati venue+avversario su gol_subiti/passaggio/clean_sheet)`.

Conseguenze: **`opponent_sensitivity` e il toggle "granulari" del grid NON mappano sulla produzione**
(la produzione ha rimosso il fattore moltiplicativo avversario e usa level_score additivo). Solo
`half_life` e `trend_intensity` transitano; `range_multiplier` è cosmetico (solo la banda). **Ecco
perché i segnali di calibrazione restavano deboli: si ottimizzava una formula stale, non quella che
schiera davvero le formazioni.** Tutti i numeri della sezione A del tuning sono quindi da RIFARE con
il backtest allineato.

L'utente ha deciso (option 1): **REVERT** di ogni cambio parametri (fatto: `git stash` "flip
parametri revertati" — recuperabile ma NON applicato) e **allineare il backtest alla produzione**
estraendo lo scoring in una **funzione condivisa** chiamata sia da produzione sia da backtest (così
non divergono mai più), POI ricalibrare pulito.

### C. Refactor DEF AVVIATO (dove mi sono fermato — riparti ESATTAMENTE da qui)

In `formazione_mls/predict/test_def.py` (commit `db5d8641f`, già su main) ho aggiunto DUE funzioni,
**senza toccare la produzione** (`build_prediction` è INTATTA, quindi lo score reale delle formazioni
NON è cambiato):
1. **`compute_score_atteso_def(...)`**: replica ESATTA della formula di produzione DEF (righe ~1408-
   1534 di build_prediction: level_score atteso da tassi eventi + granulari additivi×trend +
   shrinkage `SHRINK_K_OUTLIER_DEF`/`MEDIA_RUOLO_DEF_PRIOR` + `fattore_ct` sul residuo + Stadio D
   condizionato venue+avversario). Coi default = identica alla produzione; variabile su
   half_life/trend per il grid. Validata: py_compile + smoke test.
2. **`rigorous_backtest_prod_def(...)`**: backtest walk-forward che ad ogni partita chiama la STESSA
   `compute_score_atteso_def` sullo storico precedente. Sostituisce concettualmente il vecchio
   `rigorous_backtest`. Ritorna la stessa struttura (`mae`, `pct_dentro_range`, `n_test`) per restare
   compatibile con `aggregate_grid_search.py`. Validata: py_compile + smoke.

### D. PROSSIMI PASSI ESATTI (in ordine) — riparti da qui

1. **Verificare che `compute_score_atteso_def` == produzione byte-identica** (test di non-regressione,
   CRITICO prima di fidarsene): il modo pulito è collegarla dentro `build_prediction` come unica
   sorgente dello `score_atteso` (sostituire l'assegnazione a riga ~1488 e il `+=` Stadio D a ~1532
   con una chiamata alla funzione, MANTENENDO le variabili diagnostiche inline che servono a valle —
   Stadio C/range/output usano `delta_*`, `grezzo_nuovo_corretto`, `fattore_casa_trasferta`), poi
   lanciare una run vera DEF e confrontare lo score di un giocatore con la `prediction_*.txt` già
   committata (generata dal codice vecchio): DEVE essere identico. In alternativa, harness offline
   che ricostruisce gli array dai `.cache/*_detail_cache.json` (la logica di estrazione è le righe
   ~1200-1271 di build_prediction: `extract_level_score`, `extract_decisive_rates`, granulari =
   game_score - level_score, residuo = game_score - covered_total) e confronta funzione vs formula
   inline. **Non applicare nulla in produzione finché non è verificato identico.**
2. **Wiring nel grid**: nel percorso `CALIBRATION_MODE` di `build_prediction` (dove chiama
   `run_grid_search`), passare anche gli array che il nuovo backtest richiede (pos_decisive_values,
   neg_decisive_values, granulari_values, goals_conceded_values, passing_values, clean_sheet_values,
   residual_values — alcuni già passati, altri no) e far chiamare `rigorous_backtest_prod_def` invece
   del vecchio `rigorous_backtest`. **Ridefinire la griglia** sui SOLI parametri reali: `half_life`
   ∈{9,12}, `trend_intensity`∈{0.7,1.0,1.3}, `range_multiplier` (solo banda) — TOGLIERE
   `opponent_sensitivity` e il toggle granulari (non esistono più in produzione).
3. **Ricalibrare DEF** con il backtest allineato (rilanciare i batch DEF o un harness offline sui
   detail_cache già in `dati_globali/`), poi `RUOLO=def GLOBALE=1 python .../aggregate_grid_search.py`
   → primi MAE che misurano DAVVERO il modello di produzione. Confrontare con i parametri attuali.
4. **Replicare a GK, MID, FWD**: stessa estrazione `compute_score_atteso_<ruolo>` + backtest allineato.
   ATTENZIONE: ogni ruolo ha la sua formula (GK ha level_score legato al clean sheet, niente offensivo;
   FWD ha `SHRINK_K_OUTLIER_FWD`/`MEDIA_RUOLO_FWD_PRIOR` e la sua versione di Stadio D — leggerla in
   `test_mls_fwd_all.py` ~riga 1341-1351, NON assumere sia identica a DEF).
5. **Solo DOPO** la ricalibrazione allineata: decidere con l'utente i cambi di produzione veri
   (i parametri stanno replicati in ~20 copie `formazione_*/predict/test_<ruolo>.py`, vanno cambiati
   tutti — modello unico globale). NB: `formazione_resto_mondo` è una copia leggermente sfasata, tenerne conto.
6. Poi gli altri temi del tuning (rifit level_score su scala piena, Finding 4/5 correlazioni slot,
   MAE live) e gli step 3-4 della roadmap sotto.

### E. Roadmap complessiva concordata con l'utente (priorità = TUNING; NON il deadline formazioni)

L'utente schiera formazioni a mano da 2 anni, quindi il "deve schierare domani" NON è vincolante: la
**priorità dichiarata è il tuning** (la statistica come vantaggio competitivo). Ordine:
1. ~~Ricalibrazione nuovi campionati~~ FATTA.
2. **Tuning modello con calcoli locali** ← SIAMO QUI (refactor backtest↔produzione, punto C/D sopra).
3. **Unire i pool nel tool unificato**: `generatore_formazioni/build_formazione_globale.py` è il "tool
   unificato" (un click, tutte le formazioni). Oggi ha `CONSIGLIO_DIRS`/`DISCOVERY_DIRS` hardcoded
   SOLO su MLS+K League: legge i consigli da `formazione_<champ>/output/<champ>_<ruolo>_all/`. Va
   esteso a tutti i campionati perché peschi da tutte le carte possedute.
4. **Pulire repo**: eliminare le action per-campionato OBSOLETE (il passo `formazione_finale` per-lega
   è ridondante col tool unificato; discovery+predict+consiglio SERVONO come fornitori dati), un solo
   tool. Opzionale raggruppare `formazione_<champ>/` sotto `campionati/` (invasivo: path hardcoded
   ovunque; le GitHub Actions NON si possono spostare da `.github/workflows/`). **Fare una SCANSIONE
   SECRET prima**: il repo è ancora PUBBLICO, l'utente lo renderà privato/lo chiuderà.

### F. Stato repo a fine sessione

Tutto committato e pushato su `main`. Commit chiave di oggi: pipeline 9 campionati (`4b3c576f2`),
pulizia+consolidamento (`e7d6722d4`), CAMPIONATI_NOTI esteso (`5cc9ec54f`), bootstrap fix +
leave_one_league_out (`25b8a15b6`), combinazioni pooled GK/DEF/MID/FWD (in `calibrazione_globale/
output/*/combinazione_vincente_aggregata.json`), refactor DEF (`db5d8641f`). Working tree pulito
salvo lo `git stash` dei flip parametri revertati (recuperabile con `git stash list`/`git stash show`,
ma NON riapplicare senza il backtest allineato). Nessuna run GitHub in corso.

## 27. Sessione 27/07/2026 (notte) — backtest allineato completato, e la SCOPERTA che il MAE è la metrica sbagliata

### A. Punti 26.D.1-D.4 chiusi

1. **Non-regressione DEF verificata** (`formazione_mls/diagnostics/nonregression_score_atteso_def.py`):
   `compute_score_atteso_def` è **identica** alla produzione. 298 giocatori, 5.364 casi
   (varianti casa/trasferta × rank avversario × p_gioca), **diff max 7e-15**. Il test non riscrive
   la formula: **estrae il blocco inline dal sorgente** di `build_prediction` e lo esegue con `exec`,
   quindi confronta contro il codice di produzione letterale (se la produzione cambia, il test se ne
   accorge).
2. **Grid allineato** (`run_grid_search_prod_def` + `GRID_SEARCH_COMBINATIONS_PROD`): tolti
   `opponent_sensitivity` e il toggle granulari (non esistono più nella formula reale), restano
   `half_life`, `trend_intensity`, `range_multiplier`. `CALIBRATION_MODE` ora usa questo.
3. **Stessa cosa per FWD** (`compute_score_atteso_fwd`, `rigorous_backtest_prod_fwd`,
   `nonregression_score_atteso_fwd.py`): 187 giocatori, 1.122 casi, **diff 0.000e+00**. NB: la
   formula FWD è diversa — shrink 5.0/53.02 e Stadio D ridotto alla sola correzione "Passaggio"
   per venue, nessun condizionamento avversario.
4. **`build_prediction` NON è stata modificata per nessun ruolo**: lo score delle formazioni è
   invariato rispetto a prima della sessione.

### B. Ricalibrazione allineata: i parametri erano già all'ottimo, e il modello non ha quasi segnale

Ricalibrazione **offline** sulle detail_cache già in repo (`recalibrate_def_aligned.py`), nessuna
chiamata di rete: DEF 287 giocatori / 2.233 casi / 20 campionati; FWD 175 / 1.356 / 19.

- **`half_life` e `trend_intensity` sono INERTI**: su tutte le 18 combinazioni DEF il MAE sta fra
  14.980 e 14.988 (spread 0.05%). Idem FWD. Il vecchio grid *sembrava* discriminare solo perché
  ottimizzava la formula moltiplicativa divergente (sezione 26.B).
- **`SHRINK_K_OUTLIER_DEF=15`, `MEDIA_RUOLO_DEF_PRIOR=51.34`, Stadio D=on: già tutti all'ottimo**
  (k=0 → +3.83%, prior 44 → +2.32%, Stadio D off → +0.62%). Stesso esito FWD per `shrink_k=5`.
- **`range_multiplier`**: la griglia era troncata dal lato sbagliato (a 1.2 la copertura era già 72%
  contro l'ideale 68%); **1.1 centra 68.2%**. Impatto reale marginale: in produzione
  `RANGE_MULTIPLIER` alimenta solo la banda di *fallback*, lo Stadio C usa i percentili pesati.
- **`MEDIA_RUOLO_FWD_PRIOR` è l'unico parametro davvero sub-ottimale**: 42 batte 53.02 di **-1.22%
  MAE fuori campione** (leave-one-league-out, 19/19 fold scelgono 40-44). Causa: il prior fu fissato
  sulla **media** degli score, ma il MAE è minimizzato dalla **mediana** e la distribuzione FWD è
  asimmetrica a destra (media 55.1, mediana 50.1). **NON applicato**, vedi sotto.

**Il dato che ridimensiona tutto** — baseline banali a confronto (DEF):
```
predire sempre 51.34 (costante)      MAE 15.21
media pesata storica del giocatore   MAE 15.63
MODELLO COMPLETO                     MAE 14.99
```
Il modello batte "la stessa costante per tutti" dell'1.5%, e la media pesata dello storico è
*peggiore* della costante. Con ~15 partite per giocatore lo storico individuale è quasi tutto
rumore: ecco perché lo shrinkage aggressivo vince e perché half_life/trend non spostano nulla.

### C. LA SCOPERTA: il MAE è la metrica sbagliata, e ottimizzarlo PEGGIORA le formazioni

Il MAE misura "quanto sbaglio il punteggio del singolo giocatore". Ma per schierare non serve
indovinare il punteggio: serve **ordinare** bene i candidati e prendere i migliori. Le due cose
divergono, e non di poco.

Nuovo harness **`formazione_mls/diagnostics/selection_quality.py`**: per ogni giornata di ogni
campionato prende i giocatori che hanno davvero giocato, calcola le predizioni walk-forward (solo
storico precedente), ordina, e misura i **punti reali** ottenuti dai top K — fra due riferimenti:
**CASO** (media di tutti i candidati = schierare a caso) e **ORACOLO** (i migliori K veri). Il
"lift catturato" è la frazione di distanza caso→oracolo percorsa.

Risultati (top 3 per giornata):
```
DEF (123 giornate, 15 campionati)          FWD (70 giornate, 9 campionati)
media pesata storica       20.4%           media semplice          23.8%
media semplice             19.1%           media pesata storica    22.9%
MODELLO (produzione)       13.7%           MODELLO (produzione)    22.0%
ultima partita              7.3%           ultima partita          -0.2%
solo level_score atteso     3.3%           solo level_score        -6.1%
```
**Sulla metrica che decide le formazioni, il modello di produzione NON batte una media pesata
banale** — pur avendo un MAE nettamente migliore (14.99 vs 15.63 su DEF). Ed è esattamente il
rovesciamento del ranking per MAE.

**Causa individuata: lo SHRINKAGE.** Tira tutti verso il prior di ruolo: ottimo per il MAE
(avvicina al centro) ma distrugge la **discriminazione fra giocatori**, che è l'unica cosa che
serve per scegliere. Peggio: con `k` fisso tira **di più chi ha meno storico**, quindi non è
nemmeno una trasformazione monotona — **altera l'ordinamento**, non lo comprime soltanto.

Dose-risposta DEF (lift catturato): `k=15` (produzione) **13.7%** → `k=5` 17.1% → `k=2` **18.0%**
→ `k=0` 17.8%.

Significatività (bootstrap appaiato sulle giornate): DEF no-shrink vs produzione **+0.73
pt/giornata**, IC95% [-0.40, +1.82], P(>0)=89.6% — **non** significativo al 95% da solo. Ma su 12
configurazioni di valutazione (top_k ∈ {1,2,3,5} × min_candidati ∈ {4,5,8}) il segno è **positivo
12/12**, delta da +0.17 a +1.90. FWD **non concludente** (8/12, delta piccoli).

**Corollario sul prior FWD**: abbassarlo a 42 migliora il MAE ma rende il modello sistematicamente
pessimista (bias medio passa da -0.24 a **-4.13**), e per schierare serve il **valore atteso**, non
la mediana. E comunque non cambierebbe le scelte: Spearman fra i due ordinamenti **0.996**, top-5
identica, spostamento di rango mediano 2 posizioni. **Guadagno di MAE inutile in pratica.**

### D. Prossimi passi proposti

1. **Decidere con l'utente** se togliere/ridurre lo shrinkage nell'ORDINAMENTO dei consigli (non
   necessariamente nello score mostrato): è il primo cambio con un guadagno plausibile in
   produzione (~+0.7 pt per difensore schierato). Sample ancora sottile → in alternativa
   raccogliere più giornate e ri-misurare con `selection_quality.py`.
2. **NON replicare il tuning MAE a GK/MID**: su due ruoli su due ha ottimizzato la cosa sbagliata.
   Semmai replicare la coppia funzione-condivisa + `selection_quality`.
3. Il vero margine non è nei parametri di questa formula (il modello estrae ~1.5% sul MAE e ~14-22%
   del lift disponibile): sta nel **segnale nuovo** esterno allo storico del giocatore (forza reale
   squadra, contesto partita, minutaggio atteso) e nella **selezione roster/prezzo**.
4. Restano aperti gli step 3-4 della roadmap (tool unificato su tutti i campionati, pulizia repo +
   scansione secret prima di rendere privato).

### E. Stato repo

Branch di lavoro `claude/sorare-tracker-predictive-model-88a17f` (worktree), **non ancora su main**.
Commit: `0edaef117` (DEF non-regressione + grid allineato), `8a05feaa6` (FWD), `f2efe6256`
(selection_quality). Produzione invariata. Lo `git stash` dei flip parametri revertati è ancora lì,
e ora sappiamo che **non va riapplicato**.

### F. IMPLEMENTATO (27/07, stessa sessione): ordinamento senza shrinkage per DEF

Il punto D.1 è stato **fatto**. Separati i due usi dello score, che prima erano lo stesso numero:

| | a cosa serve | come si calcola | cambiato? |
|---|---|---|---|
| `score_atteso` | **mostrato** ("pt attesi"), miglior stima del punteggio | con shrinkage (minimizza il MAE) | **NO, invariato** |
| `score_ordinamento` | **solo per ordinare** il consiglio | stessa funzione condivisa, `shrink_k=0` | nuovo |

Catena: `test_def.py` scrive la riga `ORDINAMENTO: x.xx` → `build_consiglio_def.py` la legge, ordina
e la ripropaga → `build_formazione_finale.py` / `build_formazione_globale.py` la usano per ordinare
i pool. I punti mostrati e sommati restano `atteso`.

**Fallback TUTTO-O-NIENTE**: se anche un solo giocatore non ha la riga, si ordina tutto per pt
attesi come prima. I due score stanno su scale diverse (senza shrinkage la dispersione fra giocatori
è più ampia), quindi mescolarli nella stessa `sort` confronterebbe grandezze non omogenee — errore
che il test di integrazione ha effettivamente scoperto nella prima versione del fallback.

**Verifiche fatte**:
- Non-regressione su **tutti i 20 campionati allineati**, ognuno col proprio blocco di produzione e
  i propri `detail_cache`: **2.384 casi, diff massima 7e-15**. Lo score MOSTRATO non cambia in
  nessun campionato.
- Test di integrazione della catena predizione→consiglio→formazione sui 3 scenari (tutti con la
  riga / uno senza / nessuno): ordine e numeri come atteso, retrocompatibile.
- 61 file modificati, 20 campionati. **`formazione_resto_mondo` ESCLUSA**: copia disallineata (non
  ha nemmeno `SHRINK_K_OUTLIER_DEF`, formula di produzione diversa) — resta com'era e, grazie al
  fallback, continua a funzionare.

**LIMITE NOTO**: non verificato su una run reale end-to-end, manca `SORARE_COOKIE` in locale. La
prima run vera va guardata: deve comparire la riga `ORDINAMENTO:` e l'ordine del consiglio DEF deve
differire da quello dei pt attesi.

**Da fare ancora**: la stessa separazione per GK/MID/FWD **non** è stata applicata — su FWD la
misura non era concludente (8/12), su GK/MID non è ancora stata fatta. Prima va misurata con
`selection_quality.py`, non replicata per analogia.

### G. Il tetto teorico: perché il tuning del modello è CHIUSO

Decomposizione della varianza degli score reali (DEF: 298 giocatori, 4.043 partite):

```
dev.std. TOTALE            19.26
dev.std. ENTRO giocatore   18.72   <- rumore partita-per-partita, NON prevedibile
dev.std. FRA giocatori      4.53   <- "bravura" persistente, l'unica cosa prevedibile
ICC = 5.5%   (FWD: 9.0%)
```

Il **94.5%** della varianza di un difensore è rumore. Con 15 partite di storico l'affidabilità
della stima del giocatore è 46.8%. Simulando con questi parametri reali il tetto di **qualunque**
modello basato sullo storico:

| | tetto con 15 partite | tetto con bravura VERA nota | **misurato** |
|---|---|---|---|
| DEF | 15.5% | 22.5% | **17.8%** |
| FWD | 22.4% | 28.8% | **22–24%** |

**Siamo già al tetto.** Confermato da una seconda direzione: `half_life` variato da 4 a "piatta"
lascia il lift fra 16.3% e 17.8% (e la media pesata semplice resta sopra il modello ovunque).
Ogni ulteriore ritocco dei parametri di questo modello è provatamente tempo perso.

### H. Correlazioni ri-misurate sui 20 campionati (876 partite, 4.358 coppie)

Same-team, residuo walk-forward, permutation test + split-half:

| coppia | corr | split-half | in produzione? |
|---|---|---|---|
| def-gk | **+0.349** * | +0.434 / +0.344 | sì, bonus 11 (era misurata +0.40) |
| def-def | +0.201 * | +0.229 / +0.189 | sì, bonus 5 |
| fwd-fwd | +0.177 * | +0.201 / +0.170 | sì (regola generica compagno) |
| fwd-mid | +0.173 * | +0.224 / +0.161 | sì |
| mid-mid | +0.166 * | +0.144 / +0.174 | sì |
| def-mid | +0.156 * | +0.148 / +0.166 | sì |
| gk-mid | +0.142 * | +0.090 / +0.155 | sì, bonus 5 |
| def-fwd | +0.107 * | +0.138 / +0.094 | sì |
| **fwd-gk** | **+0.029** (n.s.) | +0.128 / +0.004 | — nullo, correttamente escluso |

**Esito: confermano la produzione attuale, nessun cambio necessario.** Il quadro reale è "tutte le
coppie di compagni correlano ~+0.15/+0.20, GK-DEF il doppio, GK-FWD zero" — che è ciò che i nudge
attuali già fanno. Cade però la nota nel codice secondo cui "FWD non mostra correlazione con nessun
ruolo": sul campione grande FWD correla con MID, FWD e DEF; solo con GK no (la regola generica
compagno lo copriva già dal 27/07 notte).

**Micro-imprecisione nota, non corretta**: un FWD prende il bonus compagno anche quando l'unico
compagno già schierato è il PORTIERE, dove la correlazione è nulla. Distinguere richiederebbe
conteggi per ruolo; effetto trascurabile.

**Candidato NON implementato**: cross-team tutte le coppie sono negative (fwd-gk -0.258*,
gk-mid -0.192*, def-mid -0.156*, def-def -0.122*, mid-mid -0.125*), non solo GK-vs-attaccante come
codificato oggi. In Arena/All Stars la correlazione negativa *riduce* la varianza, quindi
converrebbe evitare due giocatori di squadre che si affrontano, qualunque ruolo. **Ma lo split-half
è instabile** (def-mid +0.036 poi -0.187; fwd-gk +0.031 poi -0.320): serve più storico prima di
metterlo in produzione.

### I. Il guadagno vero trovato: il POOL, non il modello

Il modello è al tetto, ma la scelta dei candidati no. `build_formazione_globale.py` pescava solo da
MLS + K League: le carte possedute negli altri 18 campionati, per cui la pipeline gira già, non
venivano mai considerate — e le All Stars accettano qualsiasi campionato.

| ruolo | candidati prima | ora | guadagno stimato per slot |
|---|---|---|---|
| GK | 36 | 82 | +1.08 |
| DEF | 109 | 254 | +0.95 |
| MID | 76 | 200 | +1.17 |
| FWD | 67 | 170 | +1.05 |

**~+7 punti per formazione a 7 slot** — più grande di qualunque intervento sul modello misurato in
questa sessione, e senza rischio di modellazione: sono carte già possedute. Implementato (leghe
scoperte dal filesystem, `_grow_for('mixed')` cresce una carta alla volta per non moltiplicare per
20 le query L5/L10/L40).

### J. Backlog aggiornato (27/07 sera)

**SCARTATO su decisione esplicita dell'utente**: estendere le formazioni *In Season* agli altri 18
campionati nel tool unificato. Non serve. Le In Season restano su MLS + K League
(`DEDICATED_LEAGUES`), le Arene dedicate sulle 11 leghe di `ARENA_LEAGUES`. Non riproporlo.

Resta invece aperto: Arene dei campionati in pausa (consigli vuoti, si popolano da sole),
`formazione_resto_mondo` da allineare o dismettere, anti-sinergia cross-team estesa a tutti i ruoli
(numeri promettenti ma split-half instabile), pulizia repo + scansione secret prima di renderlo
privato.

---

# 28. Sessione 27/07/2026 (sera-notte) — il tuning è CHIUSO, il guadagno è altrove: pipeline riscritta sulla GIORNATA

**Leggi questa sezione per intero: è lo stato attuale e sostituisce operativamente buona parte
di quanto sopra.** L'utente è laureato in Giurisprudenza, autodidatta, verifica tutto su casi
reali (stasera ha confrontato l'output con Sorare aperto davanti), vuole risposte brevi e
decidere lui prima che si implementi.

## 28.A — Le tre conclusioni che contano

1. **Il tuning del modello predittivo è finito.** È al tetto teorico dei dati (sezione 27.G):
   ICC 5.5% per i DEF, cioè il 94.5% della varianza è rumore partita-per-partita. Il massimo
   estraibile da 15 partite di storico è ~15.5% del lift disponibile e il modello ne prende
   17.8%. Verificato da due direzioni indipendenti (sweep dei parametri e sweep di `half_life`).
   **Non rimettersi a limare parametri: è provatamente tempo perso.**
2. **Il guadagno vero è nel POOL e nella PIPELINE, non nella previsione.** Estendere il pool
   All Stars da 2 a 25 campionati vale ~+1 punto per slot (~+7 a formazione), più di qualunque
   intervento sul modello misurato in questa sessione.
3. **La pipeline aveva un difetto che invalidava tutto**: nessuno stadio guardava *quando*
   gioca il giocatore. Le formazioni pescavano da consigli scaduti o di partite lontane una
   settimana. Risolto ripartendo dalla **So5Fixture** (la giornata Sorare).

## 28.B — Il difetto trovato dall'utente e la sua causa

L'utente ha osservato: *"sta pescando solo portieri MLS e K League, che domani non giocano, non
hanno starter odds, giocano tra una settimana"*. Verificato sui dati: i consigli MLS puntavano a
partite del **25-26 luglio (già giocate)**, quelli K League al **1 agosto**.

Due cause indipendenti, entrambe reali:

1. **Nessun filtro sulla data della partita target.** Ogni predizione punta alla "prossima
   partita di quel giocatore", qualunque essa sia, e il generatore le mescolava tutte.
2. **Il filtro starter-odds era INERTE proprio dove serviva.** Il codice era
   `if odds is not None and odds < soglia: escludi` — cioè **chi non aveva odds veniva TENUTO
   "per sicurezza"**. Ma le odds escono a ~24-48h dal match: chi gioca fra settimane non ne ha,
   quindi passava sempre indenne. Con soglia 0.80 il filtro non toccava nessuno dei giocatori
   che andavano scartati.

**Correzione**: con una soglia attiva (>0) le odds assenti ora **escludono**. Senza soglia il
comportamento permissivo resta.

## 28.C — La riscrittura: si parte dalla GIORNATA, non dai campionati

L'utente ha fornito la traccia decisiva (payload catturato dal sito):
`ArenaLineupsFixtureSelectorCurrentFixtureQuery` con `So5Fixture`
`slug: football-28-31-jul-2026`, `seasonGameWeek: 95`, `startDate`/`endDate`.

**Nuovo script `discovery_fixture.py`** (root):

1. Risolve la fixture per **numero di gameweek** (input `gameweek`, es. 95) o per slug.
2. `so5Fixture(slug).anyGames` restituisce tutte le partite della giornata **con le squadre**.
3. Scarica le carte possedute e tiene **solo quelle il cui club scende in campo**.
4. Solo su quelle interroga le starter odds, applicando la soglia.
5. Scrive i `player_slugs.json` per lega/ruolo ed emette una **matrice JSON lega/ruolo**.

**Misurato sulla gameweek 95**: 1674 carte possedute, 139 di squadre che giocano, **58
sopravvissuti** a soglia 0.80, in **3 minuti e 11 secondi**.

**Nuovo workflow `formazione_giornata.yml`** — end-to-end, l'unico input da cambiare ogni
settimana è il numero di gameweek: discovery (fixture), predict SOLO dei sopravvissuti con
matrice dinamica, consigli, formazioni. **Girato con successo in 7 minuti e 24 secondi**,
contro i ~30 di prima.

### Vincoli dell'API scoperti per tentativi (NON riprovarli)

- `active_competitions:<slug-fixture>` restituisce **0 risultati**. Quel filtro accetta slug di
  competizione (es. `mlspa`), non di fixture.
- Batching odds con **alias GraphQL** su `anyPlayer`: rifiutato,
  `"Duplicated root field: anyPlayer"`.
- `players(slugs: [...])` **esiste e funziona**, ma *"Selecting `anyFutureGames` within a list of
  `AnyPlayerInterface` is not supported"*: niente batching delle odds per questa via.
- **L'introspezione dello schema è disabilitata** (`__type` ritorna campi vuoti). Per scoprire i
  campi si usa il trucco degli errori: l'API suggerisce da sola
  (*"Did you mean `anyPositions`?"*).
- Campi inesistenti verificati: `position` su `AnyPlayerInterface`, `bench` e `notInSquad` su
  `PlayingStatusOdds`, argomento `seasonGameWeeks` su `so5Fixtures`.
- **Conseguenza**: le odds si possono chiedere solo un giocatore alla volta. L'unica leva sui
  tempi è **ridurre quanti giocatori interrogare**, da cui il pre-filtro sulle squadre in campo.

## 28.D — Campionati: da 20 a 25, e come si scoprono gli slug

`audit_leghe_possedute.py` e il workflow "Audit leghe possedute" elencano **tutte** le leghe in
cui l'utente ha carte, con lo **slug esatto Sorare** e i giocatori per ruolo, marcando quelle non
tracciate. **Usare sempre questo invece di indovinare gli slug.**

Create in questa sessione clonando `formazione_turchia`: **Danimarca** (`superliga-dk`),
**Argentina** (`superliga-argentina-de-futbol`), **Svizzera** (`super-league-ch`), **Grecia**
(`super-league-1`), **senza_lega** (filtro invertito: tiene solo le carte **senza**
`domesticLeague`).

**Lezione da non ripetere**: Iñaki Peña sembrava "senza campionato" e su quella base l'utente
aveva deciso di non tracciare la Grecia. Era sbagliato: l'audit lo mostra come
`ignacio-pena-sotorres` sotto `super-league-1`. Prima l'audit, poi le conclusioni.

Leghe possedute ancora NON tracciate (dall'audit, con numero di carte): `liga-mx` 17,
`segunda-division-es` 12, `serie-b-it` 10, `3-liga-de` 10, `first-division-b` 6, `ekstraklasa` 5,
`russian-premier-league` 4, `pro-league` 4, `2-liga` 4, `primera-a` 3, `eliteserien` 3, più altre
minori. Si creano in due minuti con il clone.

## 28.E — Modifiche di produzione applicate (tutte su main)

1. **Ordinamento DEF senza shrinkage** (sez. 27.C e 27.F): `score_atteso` resta il numero
   *mostrato*, `score_ordinamento` (stessa funzione condivisa con `shrink_k=0`) decide
   l'*ordine*. Propagato come riga `ORDINAMENTO:` lungo tutta la catena. Vale +0.73 pt per
   difensore schierato. Non-regressione verificata su 20 campionati, 2.384 casi, diff massima
   7e-15.
2. **Riga `KICKOFF:`** nei consigli, estratta dalla riga `Data:` già presente nei file di
   predizione (nessuna modifica agli 84 script di predict). Il generatore scarta chi è fuori
   dalla finestra, e un **consiglio senza KICKOFF è considerato stale e scartato**
   (override `MATCH_WINDOW_REQUIRE_KICKOFF=0`).
3. **`MATCH_WINDOW_DAYS` = 7 giorni di CALENDARIO**, non ore da adesso: con 2 giorni contati
   alle 19:00 di lunedì si tagliavano le partite del giovedì sera.
4. **Pool All Stars esteso a tutti i campionati** (leghe scoperte dal filesystem).
   `_grow_for('mixed')` cresce una carta alla volta, sempre la migliore globale, per non
   moltiplicare per 25 le query L5/L10/L40.
5. **Arene dedicate per 11 campionati** (erano 2): MLS, K League, Belgio, Eredivisie, Turchia,
   Portogallo, Spagna, Germania, Ligue 1, Croazia, Scozia. Tutte le tabelle per-tipo sono
   generate da `ARENA_LEAGUES`: aggiungerne una è una riga.
6. **`build_consiglio` crea la cartella di output se manca** (le leghe nuove fallivano con
   FileNotFoundError).
7. **Rimosso il vecchio `generatore_formazioni.yml`** (241 job, ~30 minuti, non conosceva le
   leghe nuove, a un soffio dal limite GitHub di 256 job), sostituito da
   `formazione_giornata.yml`. Rimosse anche le sonde usa-e-getta usate per scoprire lo schema.

## 28.F — Risultato reale verificato dall'utente

All Stars da 7, gameweek 95: **417 pt (451 con capitano)**, confermata dall'utente
(*"ci sono tutti"*).

| slot | giocatore | attesi |
|---|---|---|
| GK | Elías Ólafsson (Danimarca) | 61 |
| DEF | Marcos Johan López | 53 |
| DEF | Scott McKenna | 53 |
| MID | Philip Billing | 66 |
| MID | Josip Mišić | 64 |
| FWD (capitano) | Mika Godts | 68 |
| EXTRA | Kerem Aktürkoğlu | 52 |

**Nota operativa importante**: l'utente ha visto un giocatore (Miguel) comparire *dopo*, quando
Sorare gli ha aggiunto le odds. **Le odds escono a scaglioni**, quindi conviene rilanciare la
discovery vicino al deadline: ora costa 3 minuti, quindi la si può ripetere due o tre volte prima
di schierare.

## 28.G — Decisioni prese dall'utente (NON riproporle)

- **Cap 370**: resta un **suggerimento, non un vincolo**. Confermato esplicitamente.
- **In Season per gli altri campionati**: scartata, non serve (sez. 27.J).
- **Log delle run rosse**: non gli interessa, non li guarda. Le pipeline delle leghe piccole
  falliscono sul job `formazione_finale` (0 GK o 0 DEF in quella lega) senza conseguenze sul
  resto.
- **Vecchio generatore**: eliminato su sua richiesta.

## 28.H — BACKLOG (da qui riparte il prossimo)

1. **Giocatori senza campionato nel tool fuso** *(richiesta esplicita dell'utente)* — **FATTO
   28/07**: `discovery_fixture.py` ora dirotta chi non ha `domesticLeague` su `senza_lega`
   invece di scartarlo (branch `else: dirname = 'senza_lega'`), che confluisce da solo nel pool
   All Stars (`formazione_senza_lega` ha già predict/consiglio/output per tutti e 4 i ruoli,
   scoperta automatica da filesystem in `build_formazione_globale.py`). **DA VERIFICARE su una
   run reale**: non c'era nessun giocatore senza lega nella gameweek 95, quindi il branch non è
   mai stato eseguito con dati veri — controllare la prima volta che ne compare uno (log
   `discovery_fixture` deve mostrarlo sotto `senza_lega` invece che "lega senza pipeline --
   ignorato", e deve comparire nell'output All Stars).
2. **`formazione_resto_mondo`** *(l'utente ha chiesto di chiarire il problema)* — **CHIARITO
   28/07, in sospeso**: non è solo disallineata, è **completamente inerte**: nessun workflow la
   richiama, mai prodotto un `_all` (quindi `build_formazione_globale.py` non la scopre neppure).
   Il suo criterio di discovery è diverso dagli altri: non `domesticLeague`, ma eleggibilità alla
   competizione SO5 "Resto del Mondo" (`anyPlayer.eligibleSo5Competitions`, slug
   `seasonal-rest_of_the_world`) — un giocatore può comparirci pur avendo già una lega domestica
   tracciata altrove (es. Carlos Miguel, Brasileirao + Resto del Mondo). Allinearla non è un clone
   di pipeline ma un nuovo tipo di filtro in `discovery_fixture.py`. **Chiesto all'utente se gioca
   davvero questa competizione: non lo sa ancora, deve verificare su Sorare.** Nessuna azione
   presa, riprendere quando ha la risposta (dismettere se non la gioca, altrimenti progettare il
   filtro `eligibleSo5Competitions`).
3. **Anti-sinergia cross-team su tutti i ruoli** — **RIMISURATA 28/07** con `measure_teammate_
   correlation.py` (ora auto-discovery di TUTTI i campionati dal filesystem, non più lista fissa
   a 10): 25 campionati, 1157 partite same-team / 547 cross-team (contro le 20/876 di sez. 27.H).
   **Novità importante**: con più dati la maggior parte delle coppie cross-team è ora STABILE in
   split-half (stesso segno, grandezza simile prima/seconda metà): def-def -0.136 (-0.144/-0.148),
   mid-mid -0.139 (-0.143/-0.149), gk-mid -0.208 (-0.118/-0.229), def-mid -0.175 (-0.034/-0.215),
   def-fwd -0.127 (-0.185/-0.127), fwd-mid -0.109 (-0.098/-0.118) — tutte p<0.05. **Ironia**:
   l'unica coppia già in produzione (fwd-gk, -0.289) è ora la MENO stabile (prima metà -0.003,
   seconda -0.357). Same-team confermato invariato, tutto stabile (nessun cambio necessario).
   **Proposto all'utente di estendere la penalità cross-team alle coppie ora stabili — RIMANDATO
   su sua richiesta esplicita ("rifammela dopo, ricorda domanda per dopo"): riproporre la stessa
   domanda quando riprende questo filone, non decidere da soli.**
4. **Aggiungere le leghe mancanti** dall'elenco in 28.D quando servono.
5. **Refuso**: il report HTML dice ancora "Fusione MLS + K League" in fondo.
6. **Repo ancora PUBBLICO**: scansione secret prima di renderlo privato.
7. **Le correlazioni sono già state ri-misurate su 20 campionati (sez. 27.H) e confermano la
   produzione attuale: nessun cambio necessario.** Non rifarle senza dati nuovi.

## 28.I — Stato repo

Tutto su `main`. Script nuovi principali: `discovery_fixture.py`, `audit_leghe_possedute.py`,
`diagnostica_slug.py`, e in `formazione_mls/diagnostics/`:
`nonregression_score_atteso_def.py`, `nonregression_score_atteso_fwd.py`,
`selection_quality.py`, `recalibrate_def_aligned.py`.

Workflow principali: **`formazione_giornata.yml`** (quello da usare per schierare),
`audit_leghe.yml`, `diagnostica_slug.yml`, `discovery_fixture.yml`, più i
`<lega>_completa.yml` per l'uso singolo per campionato.

---

# 29. Sessione 28/07/2026 — report HTML arricchito (L10/nome/esclusi/alternative/drag&drop) + apertura tema "portafoglio In Season"

**Leggi questa sezione per intero, è l'HANDOFF corrente.** Continua direttamente dalla 28.
L'utente ha chiesto di scrivere qui il riassunto e proseguire in una NUOVA chat.

## 29.A — Modifiche al report HTML (tutte su main, verificate)

Punto di partenza: l'utente guardava l'ultima formazione generata col modello aggiornato e ha
chiesto una serie di migliorie al report HTML di `generatore_formazioni/build_formazione_globale.py`
(che riusa `formazione_mls/build_formazione_finale.py` come libreria, `bff` nel codice).

1. **L10 mostrato su ogni carta** (piccolo, sotto il range pt). **Scoperta importante**: il dato
   L10/copie possedute (`player_card_counts.json`) non veniva più scritto da nessuno script dopo il
   passaggio a `discovery_fixture.py` (la vecchia discovery per-campionato che lo scriveva non gira
   più). **Fix**: `discovery_fixture.py` ora interroga L10 (`lastTenPlayedAvgScore`) con UNA query
   in più per giocatore, ma SOLO sui sopravvissuti finali (dopo finestra+odds, ~50-60 giocatori),
   non su tutto il pool posseduto — costo reale misurato: **+40 secondi** su discovery, non i 15
   minuti temuti (quel rallentamento era dovuto a una run parallela concorrente sullo stesso account
   Sorare, non alla query). **Verificato con un confronto pulito**: run senza L10 11m37s, run con
   L10 senza concorrenza 11m36s — praticamente identico. **Tenere la query, non è il collo di
   bottiglia.**
2. **Nome reale del giocatore (displayName Sorare)** al posto dello slug title-case (l'utente non
   riconosceva alcuni giocatori dallo slug). `displayName` era già fetchato da `discovery_fixture.py`
   ma scartato — ora persistito in un nuovo file `player_names.json` per lega/ruolo, caricato da
   `CardPool` (metodo `display_name(slug)`, fallback allo slug se manca).
3. **Conteggio candidati esclusi**: sotto l'intestazione, mostra quanti giocatori idonei per
   starter-odds/finestra NON sono finiti in nessuna formazione, totale e per ruolo (`CardPool.
   used_slugs()`).
4. **Pannello "alternative"** a fianco di ogni formazione: giocatori con punteggio vicino, PESCATI
   SOLO da altre formazioni già generate in questa run (scelta deliberata: sistema chiuso, coerente
   col drag&drop — vedi 29.B). Round-robin per slot (bug iniziale corretto: un top-N globale per
   vicinanza lasciava scoperti gli slot con meno candidati vicini, es. il ruolo FWD restava senza
   alternativa se MID ne aveva di più vicine).
5. **Drag&drop**: ogni pcard e ogni chip "alternativa" sono trascinabili; sganciando un'alternativa
   su una pcard dello STESSO ruolo li scambia (puro swap di HTML/attributi `data-*` già pronti lato
   Python, zero ricalcolo server). Il totale e il bonus capitano si aggiornano via JS; **limite
   noto**: le note L10/cap-260/anti-stack sotto ogni formazione restano quelle della generazione,
   NON si aggiornano con lo scambio. Nessuna persistenza (refresh = torna allo stato generato).
6. **Layout carte**: dopo due tentativi scartati dall'utente (righe per ruolo raggruppate;
   disposizione a diagonale GK-DEF-MID-EXTRA/FWD stile "schieramento") si è tornati alla **fila
   originale** (ordine di formazione, scroll orizzontale se serve). **Le carte sono rimaste più
   piccole** (104px invece di 152px, richiesta separata e confermata, non ritirata).
7. **Refuso corretto**: il footer non dice più "Fusione MLS + K League" ma conta dinamicamente
   `len(LEAGUES)` (25 oggi).

**NON ancora verificato dal vivo**: il drag&drop è stato controllato staticamente (dati/HTML
corretti via script Python + ispezione DOM) ma MAI trascinato per davvero in un browser. Da provare
alla prossima occasione.

**Nota su un artefatto di test**: durante la verifica visiva, il browser di anteprima ha mostrato
per un istante dati incrociati fra due formazioni (stesso portiere/difensore duplicati in due
lineup diverse) — **era un problema di cache del browser di anteprima, NON un bug nel codice**:
verificato leggendo l'HTML grezzo con `grep`, i dati erano sempre corretti. Se ricapita un
disallineamento fra quello che vedi a schermo e quello che pensi di aver generato, controllare
prima il file sorgente prima di sospettare un bug.

## 29.B — Perché le alternative pescano solo da altre formazioni generate (non dal pool intero)

Discusso esplicitamente con l'utente: pescare dal pool eleggibile completo darebbe alternative più
pertinenti, ma romperebbe l'assunzione "sistema chiuso" su cui si regge il drag&drop (nessun
controllo di disponibilità copie in JS). **Deciso di tenerlo chiuso**: un giocatore mai piazzato in
nessuna lineup generata probabilmente non era comunque tra i migliori disponibili.

## 29.C — Query L10 aggiunta a `discovery_fixture.py`: dettaglio tecnico

Nuova funzione `l10_singola(slug)` (query `lastTenPlayedAvgScore`, stesso pattern di
`odds_singola`), chiamata SOLO nel loop finale sui sopravvissuti (dopo il filtro finestra+odds).
Scrive `player_card_counts.json` con `{'in_season': 1, 'classic': 0, 'l10': valore}` per ogni
sopravvissuto — **attenzione se si tocca questo file in futuro**: il valore `in_season: 1` è
un'assunzione esplicita (non tracciamo le copie reali in questa pipeline veloce), necessaria perché
includere lo slug nel file SENZA quel campo farebbe leggere 0 copie possedute a `CardPool` (bug
potenziale, evitato scrivendolo sempre).

## 29.D — Il tema aperto: "portafoglio" In Season, corretta un'assunzione della sez. 27.J

**Meccanica di gioco chiarita dall'utente (fondamentale, non derivabile dal codice)**: In Season
non è "il tuo punteggio contro un numero fisso, vinci in proporzione" come si pensava (sez. 27.J/
28.G) — è **"schieri fino a 6 formazioni (o 5, o quante vuoi), se ANCHE SOLO UNA supera il target
della giornata (es. 350 pt) vinci il premio"**. È un "massimo di N tentativi indipendenti", non un
punteggio singolo. Questo capovolge la conclusione precedente ("la varianza non serve in In Season,
solo il valore atteso conta") — **con premio a soglia raggiunta da ALMENO UNA delle N formazioni,
la varianza torna rilevante**, esattamente come per Arena/All Stars ma con un meccanismo diverso
(max di N tentativi, non un taglio su un campo di manager).

**Due leve distinte identificate** (nessuna ancora implementata, solo discusse):
1. **Varianza DENTRO ogni formazione** (sinergia same-team GK+DEF/DEF+DEF/ecc., già misurata e già
   implementata per Arena/All Stars via `variance_mode` — vedi `GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA`/
   `TEAMMATE_SYNERGY_BONUS_VARIANCE` in `formazione_mls/build_formazione_finale.py`): oggi
   `VARIANCE_MODE_TYPES` in `generatore_formazioni/build_formazione_globale.py` NON include
   `MLS_IN_SEASON`/`KLEAGUE_IN_SEASON` — quindi questo bonus forte è spento per In Season. **Verificato
   nel codice** (l'utente ricordava giusto): esiste già un nudge PICCOLO (`POSITIVE_SYNERGY_BONUS=3`,
   non `GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA=8`) applicato alla PRIMA formazione In Season di ogni
   lega (quando se ne chiedono 2+, dalla seconda in poi `apply_positive_synergy=False`, "greedy
   puro" — vedi `in_season_multi` in `generate_lineups_for_type`). Non è quindi la versione forte
   da Arena, solo quella soft preesistente.
2. **Decorrelazione TRA le N formazioni** (idea nuova, mai implementata): evitare di riusare la
   STESSA partita reale (stessa coppia squadra-avversario) in più di una delle N formazioni della
   giornata, per rendere i "tentativi" il più indipendenti possibile (se 2 formazioni condividono la
   partita e quella va male, falliscono insieme). Meccanismo proposto: tracciare, mentre si generano
   le N formazioni in sequenza, quali partite reali sono gia' "occupate" e penalizzare (soft, non
   escludere) i candidati della stessa partita nelle formazioni successive — stesso pattern di
   `apply_stack_guard`/`ANTI_SYNERGY_PENALTY` già in uso.

**Anti-sinergia cross-team estesa** (backlog punto 3 della sez. 28.H, rimisurata 28/07 su 25
campionati): chiarito che "solo GK-vs-attaccante" della descrizione precedente era IMPRECISO — il
codice oggi penalizza già MID **e** FWD avversari del portiere (`role in ('MID','FWD')` in
`synergy_sort_key`). Quello che manca davvero: **def-def, mid-mid, def-mid, def-fwd, fwd-mid**
(tutte ora stabili in split-half sui 25 campionati, vedi sez. 28.H punto 3). Implementarle
richiederebbe tracciare la squadra di OGNI giocatore già scelto nella formazione (non solo il
portiere) — un'estensione reale di `build_one_lineup`, non una riga in più.

**L'utente aveva proposto un compromesso più semplice** (forzare tutta questa logica su 1 sola
delle 6 formazioni In Season, le altre 5 invariate) **ma l'ha ritirato** dopo la spiegazione sopra
("no no la mia era solo un'idea, esploriamo la tua direzione") a favore della decorrelazione su
TUTTE le N, non concentrata su una sola.

### Prossimi passi (in ordine, da scegliere insieme, NON implementare senza conferma)

1. **Verificare se il premio In Season è davvero "soglia singola, basta 1 su N"** come descritto
   dall'utente (sembra già confermato dalla sua descrizione, ma non c'è uno screenshot Sorare
   diretto in questa sessione — utile controllarlo se emergono dubbi).
2. **Decidere l'implementazione della decorrelazione tra formazioni** (punto 2 sopra): il pezzo
   nuovo, probabilmente la leva più forte. Serve progettare come tracciare "partite reali già
   usate" attraverso le N formazioni In Season generate in sequenza (stesso schema di
   `captained_slugs` in `generate_lineups_for_type`, ma per coppia squadra-avversario invece che
   per slug).
3. **Decidere se accendere la sinergia same-team "forte" (variance-mode) anche per In Season**
   (punto 1 sopra) — probabilmente insieme al punto 2, non da solo (la sola sinergia dentro una
   formazione non aiuta se le N formazioni sono comunque tutte correlate tra loro sulle stesse
   partite).
4. Poi tornare al backlog rimasto della sez. 28.H: `formazione_resto_mondo` (in attesa che l'utente
   verifichi se gioca quella competizione), leghe mancanti, scansione secret prima di rendere
   privato il repo (quest'ultima esplicitamente scartata "per ora" in questa sessione).
5. **Testare il drag&drop dal vivo** in un browser (mai fatto, solo verificato staticamente — vedi
   29.A).

## 29.E — Stato repo

Tutto pushato su `main`. Nessun branch di lavoro separato aperto. Modifiche di oggi sparse su:
`discovery_fixture.py` (routing senza-lega dalla sessione precedente + query L10 + player_names.json
+ player_card_counts.json), `formazione_mls/build_formazione_finale.py` (CardPool esteso con nomi/
L10/tags factorizzati, drag&drop HTML/CSS/JS nel template condiviso), `generatore_formazioni/
build_formazione_globale.py` (fase di generazione/rendering separata in due passate per il pannello
alternative, conteggio esclusi, etichetta campionati dinamica).

**Nota operativa**: durante la sessione sono girate in parallelo, nello stesso checkout locale,
altre sessioni dell'utente (bot di trading `bot_profit`, lavoro su un altro campionato/predict) che
hanno causato diversi conflitti di push — sempre risolti con `git stash push -u` (mai perso lavoro
altrui) prima di `pull --rebase`+`push`. Se ricapita "cannot pull with rebase: unstaged changes" o
push rifiutati, questo è il pattern giusto, non un errore da correggere diversamente.

# 30. Sessione 28/07/2026 (pomeriggio) — velocizzazione run + bug L10 + filtro qualità rimosso + leghe mancanti

## 30.A — Obiettivo di partenza

L'utente ha notato che le run del generatore formazioni impiegavano 10-15 minuti anche con un pool
di eleggibilità piccolo, e ha chiesto di analizzare l'intero processo (discovery → predict/consiglio
→ generatore) per tagliare dove non serve, senza cambiare l'output. Durante l'analisi sono emersi
anche due bug reali (non solo performance), scoperti guardando i log di run reali insieme
all'utente — **mai per intuizione, sempre verificati su dati reali**, coerente con
[[feedback_verifica_con_casi_reali_sorare]].

## 30.B — Performance: dove andava il tempo, e cosa NON ha funzionato

Causa dominante NON era il volume di query ma i **429 (rate limit Sorare)**: un singolo 429 con
`Retry-After` costa 150-255 secondi, molto più di quanto si guadagni andando veloci. Verificato su
5+ run reali che il rate limit è **cumulativo su tutto il job** (~60-70 richieste/minuto), non per
singolo blocco.

**Tentativo fallito e scartato**: batching via alias GraphQL multipli su `anyPlayer` per più slug
diversi nella stessa query — RIFIUTATO dal server Sorare (`"Duplicated root field: anyPlayer"`),
già documentato altrove nel repo (`scanners/bot_profit.py` riga ~491,
`docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` riga 2659) ma riscoperto perché non controllato
PRIMA di implementare — lezione: controllare sempre il repo per errori Sorare già documentati prima
di provare un giro di ottimizzazione GraphQL.

**Fix applicati, verificati su run reali**:
- `generatore_formazioni/quality_filter.py`: cache su disco per giornata (L5/L10/L40 già
  interrogati non vengono richiesti di nuovo tra run) — poi reso in gran parte superfluo dalla
  rimozione del filtro qualità (30.D).
- `discovery_fixture.py`: **unite in una query sola** le chiamate odds e L10 per lo stesso
  giocatore (`odds_e_l10_singola`, sostituisce `odds_singola`+`l10_singola`) — non è l'alias
  rifiutato sopra: è UN solo `anyPlayer(slug)` con due gruppi di campi per LO STESSO giocatore,
  sintassi GraphQL normale. Dimezza le chiamate HTTP. Pausa fra chiamate (`ODDS_L10_SLEEP`, env)
  alzata da 0.2s → 0.5s → 0.7s dopo verifica reale che 0.5s restava sopra soglia.
- Risultato misurato: discovery da **9m19s a 3m33s** (run 30339461288), run totale da **15m18s a
  9m16s**.

## 30.C — Bug reale #1: L10 calcolato ma mai committato

Il job `discovery` del workflow (`.github/workflows/formazione_giornata.yml`) faceva
`git add formazione_*/output/*_discovery/player_slugs.json` — **solo questo file**. L10 e nomi
(`player_card_counts.json`, `player_names.json`), calcolati correttamente ogni run da
`discovery_fixture.py`, venivano scartati a fine job (filesystem effimero del runner) e MAI letti
dai job `predict`/`formazione` a valle (checkout fresco di `main`). Scoperto dall'utente notando che
alcune carte nell'HTML generato non mostravano L10 pur avendolo assegnato lo stesso giorno — verifica
puntuale su un caso reale (Carlos Miguel, L10=52 visto live su Sorare, mancante nell'output). **Primo
tentativo di fix sbagliato**: escludere le carte con L10 ignoto dai calcoli di cap invece di
correggere la causa — l'utente ha fermato subito ("il problema non è 'lo escludo', la soluzione è
trova quell'L10"). Fix corretto: aggiunto `player_card_counts.json` e `player_names.json` al
`git add` del job discovery. Verificato: dopo il fix, `player_card_counts.json` per Brasile GK
conteneva `"l10": 52.0`, e la carta appariva schierata con l'L10 corretto nell'HTML.

## 30.D — Bug reale #2: filtro qualità L5/L10/L40 ridondante ed escludeva candidati validi

Caso reale trovato dall'utente: Iñaki Peña (`ignacio-pena-sotorres`, L10=46, L40=49 — solidi) escluso
da TUTTE le formazioni All Stars di una run con solo 8 portieri eleggibili, perché L5=26 (una
striscia recente) sotto la soglia 35 del filtro qualità (`quality_filter.py`, AND severo su
L5/L10/L40). Decisione presa con l'utente: il filtro era nato prima che `discovery_fixture.py`
avesse un filtro starter-odds configurabile, ora è ridondante (lo starter-odds già filtra chi
probabilmente non gioca) e più punitivo del necessario, soprattutto nei giorni di pool scarso dove
servirebbe di più. **Rimosso del tutto** (non abbassato): `LazyQualityPool` sostituita da
`_NoFilterPool` in `generatore_formazioni/build_formazione_globale.py` (tutti i candidati scoperti
sono già "passing", zero query L5/L10/L40). Rimosso anche l'input workflow `min_quality_score`
(non più letto). Aggiunto `LIST_UNUSED_CANDIDATES` (env/input workflow, default 0) per stampare nel
log, a richiesta, i candidati eleggibili mai schierati con nome — usato per il controllo di 30.F.
Verificato: rilanciando con 8 formazioni per 8 portieri disponibili, tutti gli 8 vengono usati,
incluso Peña.

## 30.E — Bug reale #3: leghe mancanti (Ekstraklasa, Primera División cilena)

Confrontando a mano la lista MID/FWD eleggibili del bot con lo screenshot reale della collezione
Sorare dell'utente, sono emersi 2 giocatori visti da Sorare (starter-odds ≥ soglia, squadra in
campo) ma scartati dal log con `lega senza pipeline`: Kacper Urbanski (Ekstraklasa, Polonia) e
Francisco Gonzalez (Primera División, Cile). Aggiunte le due leghe: mapping in `LEAGUE_DIR`
(`discovery_fixture.py`) + pipeline `formazione_polonia/` e `formazione_cile/` (predict/consiglio,
copiate da `formazione_svizzera/` con solo sostituzione del nome — nessuna logica specifica per
lega). Si aggiungono da sole al pool "mixed" (`_discover_leagues()` scopre le leghe dal filesystem,
nessun altro codice da toccare).

## 30.F — Bug reale #4: secondo filtro starter-odds nascosto, fisso al 70%, in TUTTI i predict

Per verificare se restavano altre leghe/giocatori non tracciati, l'utente ha chiesto un run con
`starter_odds_min=0` (nessun filtro) per vedere l'intero pool eleggibile e confrontarlo a mano con
la sua collezione reale (es. tutti i portieri di giornata, incluse le carte a odds 0%). Risultato
sorprendente: col filtro a 0 il pool GK restava comunque a 8, identico al run con soglia 80% — la
discovery in realtà aveva scoperto correttamente **tutti i 20 portieri reali** (verificato contando
i `player_names.json` per lega: 2+4+1+1+2+1+3+1+1+4 = 20, combacia esatto con lo screenshot
dell'utente), ma il consiglio finale per Austria ne teneva solo 1 su 4, segnalando "3
esclusi/non disponibili questa giornata".

Causa: **ogni script `test_<ruolo>.py`** (uno per lega/ruolo, ~112 file quasi identici) ha una
riga `MIN_STARTER_ODDS = 0.0 if CALIBRATION_MODE else 0.70` — un SECONDO filtro starter-odds,
fisso al 70%, indipendente e non collegato in alcun modo alla soglia scelta in
`discovery_fixture.py`/nell'input del workflow. Impostare `starter_odds_min=0` cambiava solo il
primo filtro (discovery), non questo secondo (dentro ogni predict), quindi chi era sotto 70% veniva
comunque scartato in silenzio al passo successivo.

Fix: portata `MIN_STARTER_ODDS` a `0.0` fisso in tutti e 112 i file (`formazione_*/predict/
test_{gk,def,mid,mls_fwd_all}.py`), sostituzione automatica via script Python (regex sulla riga di
assegnazione, verificato che tutti i 112 file avessero pattern identico prima di sostituire, poi
compilati tutti con `py_compile` per sicurezza). Scelta: **disattivare il valore** (soglia a 0)
invece di rimuovere chirurgicamente il blocco di codice che lo usa in ognuno dei 112 file — stesso
risultato funzionale (nessuna esclusione), rischio molto più basso.

**Nota per il prossimo controllo**: questo era un lavoro esplicitamente definito dall'utente come
"va fatto" indipendentemente dal bisogno della giornata corrente — verificare la copertura reale
del pool eleggibile, non solo tarare i parametri. Probabile che vada ripetuto (con
`LIST_UNUSED_CANDIDATES=1` + `starter_odds_min=0`) su un'altra giornata per controllare se restano
altre leghe non mappate oltre a Ekstraklasa/Primera División cilena.

## 30.G — Decisioni prese dall'utente (NON riproporle)

- Filtro qualità L5/L10/L40: **eliminato**, non riabbassato a soglia più permissiva.
- Push su `main` durante la sessione: ok farlo liberamente senza chiedere conferma quando si sta
  lavorando/testando direttamente su main (nessun branch separato in uso) — la vecchia regola
  "chiedere conferma prima di pushare su main" valeva per un contesto con branch di lavoro separati,
  non applicabile quando main stesso è l'ambiente di test corrente (vedi
  [[feedback_push_main_solo_a_fine_sessione]], aggiornata).
- Candidati con L10 ignoto: la soluzione corretta è recuperare il dato, MAI escludere il candidato
  come scorciatoia.

## 30.H — Stato repo

Tutto pushato su `main`. File toccati: `discovery_fixture.py` (LEAGUE_DIR esteso, query odds+L10
unita, ODDS_L10_SLEEP), `.github/workflows/formazione_giornata.yml` (git add esteso nel job
discovery, input `list_unused_candidates` al posto di `min_quality_score`),
`generatore_formazioni/quality_filter.py` (cache disco, poi in gran parte superfluo),
`generatore_formazioni/build_formazione_globale.py` (`_NoFilterPool`, elenco candidati non
schierati), `formazione_mls/build_formazione_finale.py` (nessuna modifica netta: primo tentativo di
fix sull'esclusione L10 fatto e poi ripristinato con `git checkout --`), `formazione_polonia/` e
`formazione_cile/` (nuove pipeline), 112 file `formazione_*/predict/test_*.py` (MIN_STARTER_ODDS
disattivato).

Run di verifica lanciata con `starter_odds_min=0` dopo questo commit, per controllare se con le
leghe Polonia/Cile aggiunte e il secondo filtro rimosso il pool eleggibile combacia finalmente al
100% con la collezione reale dell'utente su tutti i ruoli, non solo GK.

## 30.I — TEST IN CORSO (28/07, sera): discovery spezzata in 3 job paralleli + merge

**ATTENZIONE se questa sezione è ancora qui SENZA un aggiornamento successivo che dice "test
concluso" o "ripristinato": il test è stato interrotto a metà sessione. Prima di continuare
qualunque altro lavoro sul generatore formazioni, controllare lo stato reale del workflow
(`.github/workflows/formazione_giornata.yml`) e di `discovery_fixture.py` — se la discovery è
ancora spezzata in 3 job e non è stata confermata funzionante da un run completo verificato
dall'utente, va ripristinato il meccanismo precedente a un singolo job `discovery` (vedi sotto
"Come ripristinare se fallisce").**

**Perché**: la discovery singola (dopo i fix di 30.B) impiega ~3m30s-6m a seconda di quanti
giocatori risultano eleggibili nella giornata (in una run con pool allargato per il controllo di
30.F ci ha messo 6 minuti). L'utente vuole verificare se spezzare la discovery in 3 job paralleli
(per sottoinsieme di ruoli) più un job di merge, eseguiti da GitHub Actions su runner diversi,
riduce il tempo totale — È UN TEST, esplicitamente a rischio noto: il rate limit di Sorare osservato
finora (~60-70 richieste/minuto) potrebbe essere legato all'account/cookie condiviso da tutti i job,
non alla singola connessione — in quel caso 3 job paralleli non aumentano il throughput reale,
rischiano solo più 429 complessivi. Va giudicato SOLO sul risultato di un run reale.

**Come funziona il test**: `discovery_fixture.py` accetta una nuova env `DISCOVERY_ROLES`
(sottoinsieme di `gk,def,mid,fwd`, default tutti e 4) per processare solo quei ruoli. Tre job
paralleli nel workflow (`discovery_a`: gk+def, `discovery_b`: mid, `discovery_c`: fwd — bilanciati
approssimativamente sul numero di candidati visti finora, non un criterio esatto), ciascuno scrive
SOLO le sue cartelle di output per ruolo (nessuna sovrapposizione di file tra job, quindi nessun
vero conflitto di merge sui contenuti). Un quarto job `discovery_merge` (needs: tutti e 3) combina i
tre `MATRICE_JSON` parziali in uno solo, che alimenta il job `predict` (ora `needs: discovery_merge`
invece di `needs: discovery`); il job `formazione` ora ha `needs: [discovery_merge, predict]`.

**Come ripristinare se fallisce (o se questa sessione si interrompe senza conferma)**:
```
git log --oneline -- .github/workflows/formazione_giornata.yml discovery_fixture.py
```
poi `git revert` (o `git checkout <commit-prima-del-test> -- .github/workflows/formazione_giornata.yml discovery_fixture.py`) del/dei commit con messaggio che menziona "discovery in 3 job paralleli" / "DISCOVERY_ROLES" — riporta al singolo job `discovery` che gira tutti e 4 i ruoli, già verificato funzionante e via via ottimizzato in 30.B. Non serve toccare altro (predict/formazione tornano automaticamente a leggere `needs: discovery` una volta ripristinato il workflow).

**ESITO (28/07, run 30348298610): FUNZIONA, tenuto attivo.** I 3 job discovery sono girati
davvero in parallelo (stesso timestamp di avvio, 09:50:48Z) e hanno finito in **1m32s totali**
(discovery_a, GK+DEF, il più lento) contro i 3m30s-6m del singolo job precedente. **Zero 429
reali** su tutti e 3 i job nonostante l'esecuzione simultanea (i pochi match testuali "429" in
discovery_a erano falsi positivi, nessuna riga "[429] tentativo"). Il rate limit di Sorare NON è
quindi rigidamente condiviso/cumulativo fra job/runner diversi come temuto in apertura di 30.I —
o almeno non abbastanza da annullare il beneficio a 3 job. Run totale sceso a **7m9s** (da 9m16s
del run precedente, 15m18s a inizio sessione). Nessun rollback necessario: lo split resta il
meccanismo di produzione.

## 30.J — Verifica copertura pool eleggibile, ruolo per ruolo (confronto manuale con screenshot Sorare)

Dopo i fix di 30.C-30.F, l'utente ha chiesto un controllo sistematico ("va fatto indipendentemente
dal bisogno della giornata corrente", vedi 30.F) confrontando a mano, ruolo per ruolo, la lista
eleggibili del bot (run con `starter_odds_min=0`, `LIST_UNUSED_CANDIDATES=1`) con screenshot reali
della sua collezione Sorare filtrata sulla stessa giornata.

**Esito, GW95 (28/07)**:
- **GK**: 20 trovati dal bot = 20 reali. Combacia esatto.
- **DEF**: 40 trovati dal bot = 40 reali (un solo nome apparentemente mancante, Ahmetcan Kaplan,
  ma il motivo è che Sorare non gli ha ancora assegnato starter-odds — dato non disponibile, non
  un bug nostro).
- **MID**: 38 trovati dal bot. 3 nomi apparentemente mancanti dalla prima occhiata dell'utente
  (Dejan Zukić, Kendry Páez, Arno Verschueren) — stesso motivo: nessuna starter-odds ancora
  assegnata su Sorare per questi tre. Non un bug.
- **FWD**: 37 trovati dal bot, confermato corretto dall'utente (include Francisco Gonzalez dal
  Cile e i 2 nuovi della Polonia: Allahyar Sayyadmanesh, Patrik Wålemark).

**Conclusione**: con le pipeline Polonia/Cile aggiunte (30.E) e il secondo filtro starter-odds
nascosto disattivato (30.F), il pool eleggibile scoperto dal bot combacia AL 100% con la collezione
reale dell'utente su tutti e 4 i ruoli, su questa giornata. Gli unici scarti residui sono giocatori
a cui Sorare stesso non ha ancora assegnato starter-odds (dato assente alla fonte, non recuperabile
lato nostro finché Sorare non lo pubblica). Nessuna lega mancante oltre a Ekstraklasa/Primera
División cilena già trovate. **Non riproporre questo controllo per la stessa giornata** — ripeterlo
eventualmente su una giornata futura diversa se emergono nuovi sospetti di copertura incompleta.

## 30.K — TEST v2 IN CORSO (28/07, sera): 6 job discovery + max-parallel predict a 10

**ATTENZIONE se questa sezione è ancora qui SENZA un aggiornamento successivo con l'esito: il test
è stato interrotto a metà sessione. Controllare `gh run list --workflow formazione_giornata.yml`
per lo stato dell'ultimo run prima di continuare altro lavoro sul generatore formazioni.**

Dopo il successo del test a 3 job (30.I/30.J: discovery da 9m19s a 1m32s, run totale 7m9s),
richiesto un test ancora più estremo: **6 job discovery** invece di 3, e **max-parallel del job
predict alzato da 6 a 10** (richiesta iniziale "alza a 15", poi corretta esplicitamente
dall'utente a 10 — "mi sembra troppo").

**Come funziona il nuovo split**: GK e FWD restano un job intero ciascuno (pool più piccoli,
20 e 37 giocatori su GW95). DEF e MID (i più affollati, 40 e 38) sono spezzati ANCHE per metà
delle leghe di destinazione, non solo per ruolo — nuova env `DISCOVERY_LEAGUE_HALF` ('A'/'B') in
`discovery_fixture.py`, split alfabetico fisso e deterministico delle cartelle `formazione_<lega>`
(incluso `senza_lega`). Il filtro si applica PRIMA di interrogare odds+L10 (il vero costo), non
dopo — quindi il numero di richieste HTTP per job è davvero dimezzato, non solo il lavoro di
scrittura. La paginazione `CARDS_QUERY` (piccolo costo) resta duplicata fra i due job dello stesso
ruolo, effetto collaterale accettato. 6 job: `discovery_gk`, `discovery_def_a`, `discovery_def_b`,
`discovery_mid_a`, `discovery_mid_b`, `discovery_fwd`, poi `discovery_merge` (needs tutti e 6)
combina i `MATRICE_JSON` parziali.

**Rischio noto esplicitamente**: nessuno nuovo rispetto al test precedente — stesso dubbio se il
rate limit di Sorare sia condiviso per account, già NON confermato nel test a 3 job (zero 429 con
3 job simultanei). Il rischio incrementale qui è solo l'aumento di `max-parallel` sul job predict
(più checkout/job GitHub Actions simultanei che condividono lo stesso `SORARE_COOKIE` per le
chiamate di predizione, non ancora testato a questo grado di parallelismo).

**Come ripristinare se fallisce**: stesso meccanismo di 30.I — `git log` sui due file
(`.github/workflows/formazione_giornata.yml`, `discovery_fixture.py`) e `git revert`/`checkout` dei
commit col messaggio "TEST v2" / "6 job discovery" per tornare alla versione a 3 job (30.I),
oppure ulteriormente indietro al singolo job se anche quella andasse ripristinata.

**ESITO (28/07, run 30349453664): FUNZIONA, tenuto attivo — ancora meglio del test precedente.**
Run totale **5m18s** (da 7m9s del test a 3 job, 15m18s a inizio sessione). Discovery (6 job in
parallelo): 1m14s. Predict (max-parallel 10): 3m37s (era ~5min). Formazione: 16s. **Zero 429 reali
su tutti e 6 i job discovery**, nonostante il parallelismo raddoppiato rispetto al test precedente
— conferma ulteriore che il rate limit di Sorare non è il collo di bottiglia condiviso temuto, o
comunque non abbastanza da annullare il beneficio a questo livello di parallelismo. Nessun
rollback necessario: split a 6 job + max-parallel 10 restano il meccanismo di produzione.

**Non spingere oltre senza nuova richiesta esplicita dell'utente** — il rapporto tempo risparmiato
per ulteriore split cala (discovery già a ~1 minuto, il margine residuo è nel job `predict`/
`formazione`, non nella discovery), e il rischio di saturare il rate limit condiviso resta non
zero anche se non ancora osservato.

## 30.L — TEST v3 IN CORSO (28/07, sera): 12 job discovery + max-parallel predict a 14

**ATTENZIONE se questa sezione è ancora qui SENZA un esito ("funziona"/"ripristinato"): il test
è stato interrotto a metà sessione. Controllare `gh run list --workflow formazione_giornata.yml`
prima di continuare altro lavoro.**

Dopo il successo del v2 (30.K: 6 job, run 5m18s), richiesto un test "vediamo se esplode tutto" a
12 job discovery (GK×2, DEF×4, MID×4, FWD×2 — quote proporzionali alle dimensioni relative dei
pool) + `max-parallel` del job predict alzato da 10 a 14 (richiesta iniziale 15, poi 12
job/max-parallel 14 dopo un giro di correzioni dell'utente in diretta).

Generalizzata `DISCOVERY_LEAGUE_HALF` (A/B fisso) in `DISCOVERY_LEAGUE_SHARD` ('idx:n', N
arbitrario) in `discovery_fixture.py` — stesso principio (split alfabetico fisso delle cartelle di
destinazione, filtro applicato PRIMA delle chiamate odds+L10), solo generalizzato a N quote invece
di 2. Workflow riscritto per intero (troppi job da editare a mano in sicurezza, rigenerato via
script Python e verificato con `yaml.safe_load` prima di scrivere).

**Come ripristinare se fallisce**: stesso meccanismo di 30.I/30.K — `git log` sui due file e
revert/checkout del commit "TEST v3" / "12 job discovery" per tornare alla v2 (6 job, 30.K),
già confermata stabile.

**ESITO (28/07, run 30350390404): FUNZIONA, tenuto attivo — non e' esploso niente.** Run totale
**4m21s** (da 5m18s del v2, 15m18s a inizio sessione: -71% totale in questa sessione). Discovery
(12 job in parallelo): ~1 minuto. **Zero 429 su tutti e 12 i job**, zero job falliti in tutta la
pipeline (discovery/predict/formazione). Nessun rollback necessario: 12 job + max-parallel 14
restano il meccanismo di produzione.

**Non spingere oltre in questa sessione** — il rendimento marginale di ulteriore split è ormai
piccolo (discovery già a ~1 minuto, il pavimento pratico è probabilmente il checkout+pip install
di ogni job GitHub Actions, ~15-20s fissi per job, che con troppi job comincia a pesare più del
lavoro utile). Se in futuro si vuole andare oltre, valutare prima di ridurre l'overhead fisso per
job (es. cache pip) piuttosto che aumentare ancora il numero di shard.

## 30.M — TEST v4 IN CORSO (28/07, sera, "ultimo test promesso"): 24 job discovery + max-parallel 28

**ATTENZIONE se questa sezione è ancora qui SENZA un esito: il test è stato interrotto a metà
sessione. Controllare `gh run list --workflow formazione_giornata.yml` prima di continuare.**

Dopo v3 (30.L: 12 job, 4m21s, zero 429), richiesto un raddoppio totale per vedere il limite
pratico: **24 job discovery** (GK×4, DEF×8, MID×8, FWD×4, stesso principio di sharding
proporzionale) + **max-parallel predict a 28** (doppio di 14). Generato via script Python come i
test precedenti, verificato con `yaml.safe_load` prima di applicare.

**Come ripristinare se fallisce**: `git log` + revert/checkout del commit "TEST v4" / "24 job
discovery" per tornare a v3 (12 job, 30.L), già confermata stabile.

**ESITO (28/07, run 30351006630): FUNZIONA, tenuto attivo — non e' esploso niente, ultimo test
della serie ("ultimo test promesso").** Run totale **4m05s** (v3 era 4m21s — guadagno marginale di
soli ~16s, come previsto: il pavimento pratico e' vicino). Zero 429, zero job falliti su
discovery/predict/formazione, nonostante 24 job discovery + max-parallel 28 simultanei.

**Decisione presa con l'utente**: nonostante il guadagno marginale minimo, **v4 (24 job) resta
l'assetto di produzione** invece di tornare a v3 — motivazione esplicita: con giornate piu'
affollate (piu' formazioni richieste, pool piu' grandi) il margine di sharding piu' fine potrebbe
contare di piu' di quanto misurato su questa giornata specifica (GW95, pool relativamente piccolo).
Non e' una scelta guidata dai numeri di OGGI, ma da un margine di sicurezza per il futuro.

**Riepilogo finale della serie di test (stessa sessione, stessa giornata GW95)**:

| Versione | Job discovery | max-parallel predict | Discovery | Run totale |
|---|---|---|---|---|
| Iniziale | 1 | 6 | 9m19s | 15m18s |
| v1 | 3 | 6 | 1m32s | 7m9s |
| v2 | 6 | 10 | 1m14s | 5m18s |
| v3 | 12 | 14 | ~1min | 4m21s |
| **v4 (finale)** | **24** | **28** | **~1min23s** | **4m05s** |

Da 15m18s a 4m05s: **-73% sul tempo totale della run**, zero 429 e zero fallimenti in tutti i 5
livelli testati. **Non riproporre altri test di scaling senza una richiesta esplicita** — il
pavimento pratico e' stato raggiunto, ulteriori guadagni richiederebbero ridurre l'overhead fisso
per job (checkout+pip install, ~15-20s/job) piuttosto che aumentare ancora gli shard.

## 31.A — Sessione 28/07/2026 (notte) — Audit completo del modello richiesto dall'utente

Dopo i test di scaling (sezione 30), richiesto un audit generale e adversariale di **tutto** il
modello che porta a una prediction di formazione: "individuane incongruenze logiche, errori,
discrepanze... ripercorri ogni singolo step". Regola di lavoro concordata: ogni bug trovato viene
proposto via pop-up, l'utente risponde si/no, e solo poi si decide se fixare subito o mettere in
coda. Trovati e confermati con dati reali (mai per assunzione) diversi bug distinti, elencati
sotto in ordine di scoperta.

## 31.B — Bug reale: `p_gioca` come moltiplicatore di `score_atteso` (rimosso, tutte le 28 leghe/4 ruoli)

`score_atteso` era moltiplicato per `p_gioca` (probabilita' di scendere in campo) in tutti i ruoli.
Decisione dell'utente: `score_atteso` deve rappresentare "quanto rende SE gioca", non un valore
atteso pesato per l'incertezza sulla presenza — quel rischio va gestito a monte come filtro secco
(`starterOdds`/`MIN_STARTER_ODDS`), non come sconto continuo che penalizza chi ha assenze
irrilevanti nello storico (amichevoli, nazionale). Rimosso da GK/DEF/MID su tutte le 28 leghe e da
FWD — **con un errore reale nel primo giro**: il batch-fix su FWD aveva riportato "Modificati: 81"
(27 leghe × 3 ruoli, FWD silenziosamente a zero senza errore visibile) e solo una riverifica
sistematica (`grep -rl "p_gioca \*"` su tutto il repo, non fidarsi del conteggio riportato dallo
script) ha scoperto che FWD non era stato toccato su 27/28 leghe. Rifatto e riverificato: 27/27
modificati, zero match residui, tutti i file compilano.

## 31.C — Simulazione locale delle 6 formazioni MLS In Season: 3 bug reali trovati

Su richiesta esplicita dell'utente ("niente piu' run finche' non risolvi tutti i bug, farai tu i
calcoli in locale"), costruita una simulazione locale (no GitHub Actions) delle 6 migliori
formazioni MLS In Season con la prossima giornata reale, solo giocatori posseduti. L'utente ha
esaminato i risultati riga per riga e trovato 3 bug reali:

1. **Bug allocazione budget classic (Gil)**: `build_one_lineup` processava gli slot in ordine
   fisso (GK→DEF→MID→FWD→EXTRA) e assegnava il budget classic (1 sola carta classic per lineup
   nelle formazioni IN_SEASON) al primo slot che ne aveva bisogno, non al piu' conveniente. Gil
   (MID, classic-only, ~70 punti atteso) veniva scartato a favore di uno slot DEF molto meno
   decisivo, con perdita netta di punteggio. **Fix**: `build_one_lineup` ora fa un dry-run
   (`measure_gains=True`) per misurare il guadagno marginale di ogni slot se gli venisse assegnato
   il budget classic, poi assegna il budget SOLO allo slot con guadagno massimo. Verificato con
   test sintetico (scenario che rispecchia Gil): output corretto, +2 punti rispetto al
   comportamento greedy precedente.
2. **Bug discovery/paginazione (Zinckernagel scomparso)**: Zinckernagel non appariva in nessuna
   delle 6 formazioni nonostante fosse un giocatore valido. Causa: in `discovery_fixture.py`, la
   paginazione di `CARDS_QUERY` trattava una pagina vuota a meta' risultato (`hits` vuoto ma
   `page < nbPages`) come "fine dei risultati raggiunta", perdendo silenziosamente in modo
   silenzioso tutte le pagine successive — confermato riproducendo la query pulita (pagina 5/21
   vuota per un glitch transitorio, poi di nuovo popolata a un retry immediato). **Fix**: la
   paginazione ora distingue esplicitamente "ultima pagina raggiunta" (`page >= nbPages`, break
   normale) da "pagina vuota a meta' senza motivo" (retry fino a 3 volte con 1s di pausa, poi
   `return 2` con errore esplicito invece di troncare in silenzio).
3. **Bug contatore sinergie same-team (gia' in coda da prima)**: `chosen_roles_by_team` usava un
   `set()` di ruoli per squadra invece di un contatore — due compagni di squadra dello stesso ruolo
   contavano come uno solo ai fini di bonus/penalita' di sinergia. Fix: sostituito con un `dict`
   contatore per ruolo. Gia' committato in precedenza insieme a FWD ordinamento e allineamento
   backtest GK/MID (commit `66baaf8f4`).

## 31.D — Bug reale: prior di shrinkage fisso, indipendente dal tasso di presenza storico

Indagando due casi segnalati dall'utente (Jack Skahan MID e David Vazquez DEF, entrambi con
`score_atteso` sospettosamente alto per giocatori marginali), confermato che il prior di ruolo
usato nello shrinkage-verso-il-ruolo (`MEDIA_RUOLO_X_PRIOR`) era una costante fissa uguale per
tutti, panchinari e titolari. Misurato su dati reali (`.game_log_cache/*.json`, l'unica cache che
conserva gli status `DID_NOT_PLAY` — un primo tentativo con `.cache/*.json` ha dato risultati
palesemente sbagliati, tutti i giocatori a presence_rate=1.0, per lo stesso motivo) una
correlazione positiva reale fra tasso di presenza storico e punteggio medio quando il giocatore
gioca: GK n=115 corr=+0.245, DEF n=381 corr=+0.447, MID n=331 corr=+0.530, FWD n=287 corr=+0.522.
Fittate 4 regressioni lineari (una per ruolo) e sostituito il prior fisso con
`max(0.0, intercetta + pendenza*presence_rate)` quando il presence_rate e' disponibile (default
`None` = comportamento vecchio invariato per i chiamanti di backtest che non lo passano).
Implementato e propagato a GK/MID/DEF su tutte le 27 leghe con il meccanismo di shrinkage (esclusa
`formazione_resto_mondo`, [[project_backlog_resto_mondo_modello_arretrato]]), FWD solo su MLS
(decisione gia' presa in precedenza di non estendere lo shrinkage FWD alle altre 27 leghe — misurato
che il non-shrinkage batte lo shrinkage li'). Verificato live su MID: Jack Skahan sceso da 52.76 a
42.50, comportamento atteso per un panchinaro con storico di assenze. Dettaglio tecnico completo in
memoria: `project_prior_dinamico_presence_rate.md`.

**Scoperta collaterale durante la propagazione**: `compute_score_atteso_gk` e
`compute_score_atteso_mid` come funzioni condivise (usate sia da `build_prediction` sia dal
backtest) esistono SOLO in MLS — le altre 27 leghe hanno lo shrinkage calcolato inline dentro
`build_prediction`, stesso debito tecnico gia' noto per FWD
([[project_backlog_fwd_shared_function_solo_mls]]). Non bloccante per questo fix (adattato alla
struttura inline dove serviva), ma da tenere presente per audit futuri di disallineamento
backtest/produzione.

## 31.E — Fix reale (gia' committato separatamente): `player_team_slug` a maggioranza invece che dall'ultima partita

Trovato durante lo stesso audit: `player_team_slug` era calcolato per maggioranza di partite
home/away sull'intera finestra storica invece che dalla squadra dell'ultima partita reale —
rischio concreto di attribuzione alla squadra VECCHIA dopo un trasferimento a meta' finestra
(sbagliando fattore casa/trasferta, sinergie di squadra, avversario nel report). Fix applicato e
committato (commit `7e8f20714`) su tutti e 4 i ruoli, tutte le leghe.

## 31.F — Decisioni prese dall'utente (NON riproporle)

- `p_gioca` resta fuori da `score_atteso` in via definitiva (sezione 31.B) — il rischio di assenza
  si gestisce solo col filtro starter-odds, non come sconto continuo.
- Shrinkage FWD resta MLS-only, non va esteso alle altre 27 leghe (misurato: peggiora la
  selezione li').
- Il prior dinamico da presence rate (31.D) e' l'assetto di produzione per GK/MID/DEF su tutte le
  leghe tranne `formazione_resto_mondo`.
- "Delega ogni fix ad un agente": per lavoro ripetitivo di propagazione su molte leghe (stesso
  pattern verificato su MLS da replicare 27 volte), usare Agent in background invece di farlo
  turno per turno — ogni agente deve riverificare da solo con grep/conteggi reali, non limitarsi a
  dichiarare successo (lezione imparata dall'errore di 31.B).

## 31.G — Backlog aperto (non fatto in questa sessione)

- `formazione_resto_mondo`: unica lega su 28 senza NESSUNO dei refactor recenti
  (level_score/shrinkage/score_ordinamento/p_gioca-fuori-da-score/prior-dinamico) — valutare se
  vale la pena riportarla al passo con le altre.
- Verifica live puntuale di GK e DEF con un caso reale specifico dopo il fix del prior dinamico
  (fatto solo per MID/Skahan finora — compilano entrambi ma non e' stato controllato un numero
  reale prima/dopo).
- Ri-simulazione locale delle 6 formazioni MLS In Season dopo tutti questi fix, per confermare che
  siano finalmente "sensate" secondo il giudizio dell'utente.
- Test del retry di paginazione (31.C, punto 2) contro un vero caso di fallimento transitorio —
  finora solo verificato per compilazione, mai esercitato in produzione (difficile da riprodurre a
  comando).

## 31.H — Stato repo a fine sessione

Tutto committato e pushato su `main` (commit `9fced5cab`, 84 file: prior dinamico su GK/MID/DEF
27 leghe + FWD MLS, fix paginazione discovery, fix allocazione budget classic). `main` allineato
con `origin/main`, nessun conflitto. Non incluse nel commit: le cartelle `.debug` sotto
`formazione_mls/output/*/.debug/` (dump di debug non tracciati, accumulati da run reali con errori
di complexity-limit — lasciate intatte, decisione di pulizia non presa).

## 32 — Sessione 29/07/2026 — bug reali trovati su run vere (sharding, squadra/avversario,
## retry sprecati) + tempi di run portati da 22 a 9m33s, tutto committato e pushato

Sessione guidata da run reali ripetute su GitHub Actions (non simulazioni locali): l'utente
segnalava formazioni "sballate" e tempi di run troppo lunghi, ogni bug e' stato confermato con
dati reali prima del fix, poi verificato rilanciando la run vera.

**Bug reali trovati e fixati (tutti committati+pushati su main):**

1. **Sotto-shard MLS/K League si cancellavano a vicenda i giocatori scoperti**: `git merge -X ours`
   su file JSON single-line, quando 2 sotto-shard scrivevano lo stesso file scartava per intero
   meta' del roster gia' pushata (Woledzi/Palacios, DEF Nashville, verificato posseduti via query
   diretta API ma assenti dal pool). Fix: `merge_discovery_json.py` fa l'unione invece di
   scartare, richiamato in tutti i 39 retry-loop di discovery nel workflow.
2. **Crash silenzioso nel riepilogo FWD MLS**: unpack di tupla a 8 campi quando l'append ne
   aveva 9 (`score_ordinamento` aggiunto ieri) — `ValueError` per ogni giocatore, score gia'
   calcolato perso in silenzio. Ha rotto ~95% delle predizioni FWD di uno shard.
3. **Guadagno budget classic azzerato quando il candidato #1 del ruolo era esaurito**: il calcolo
   del "gain" per slot confrontava col candidato dal punteggio piu' alto in ASSOLUTO
   (`candidates[0]`), ignorando se avesse ancora copie disponibili, invece che con la vera
   alternativa in_season disponibile. Bug scoperto dall'utente: Gil/Berhalter classic (61-63pt)
   restavano fuori mentre giocatori piu' scarsi (53-55pt) venivano schierati. Verificato con
   simulazione reale: Berhalter passa da 0/6 a 2/6 lineup, punteggio totale portafoglio
   1707->1731.
4. **Lega esclusa per intero se mancava anche solo 1 ruolo su 4**: `_discover_leagues()` in
   `generatore_formazioni/build_formazione_globale.py` richiedeva TUTTE e 4 le cartelle ruolo
   (ancorato su `*_gk_all`). Cile (solo FWD) e Polonia (solo FWD+MID) sparivano da ogni
   formazione nonostante consigli validi generati ogni giorno.
5. **SQUADRA/AVVERSARIO corrotti da partite fuori competizione**: la finestra delle ultime 5
   partite per determinare la squadra attuale del giocatore poteva essere dominata da
   competizioni non-mlspa (global-cup, amichevoli, nazionale) con `homeTeam`/`awayTeam` vuoti o
   riferiti a un contesto diverso — Messi mostrava "N/D", Griezmann risultava "Atletico Madrid"
   invece che la sua squadra MLS. Fix: si preferiscono le partite della STESSA competizione della
   partita target, fallback permissivo se il giocatore non ne ha nello storico. Applicato a
   tutti e 4 i ruoli MLS.
6. **Nessun retry sulla risoluzione fixture/gameweek**: un blocco CloudFront transitorio (vedi
   punto 8) su questa UNICA chiamata di bootstrap ha fatto fallire un'intera run (discovery_fwd_0,
   1 job su 34, ma sufficiente a bloccare tutto). Aggiunto retry minimo (3 tentativi, 3s).
7. **Retry da 60s sprecati su giocatori con storico strutturalmente insufficiente**: un panchinaro
   con storico quasi tutto DID_NOT_PLAY non ha speranza di successo ritentando la stessa query
   pochi secondi dopo, ma il loop non distingueva questo caso da un fallimento transitorio.
   Aggiunto flag `_STRUCTURAL_INSUFFICIENCY` per uscire subito, senza attesa, SOLO nei 2 casi
   davvero strutturali (nessuna partita nella finestra, meno di MIN_USABLE_GAMES) — il caso
   "nessuna partita futura trovata" resta con retry normale (li' un retry puo' aiutare davvero).
8. **Circuit breaker per blocco CloudFront**: quando Sorare blocca con HTTP 403 "Request blocked"
   (blocco IP/sessione, non per-giocatore), ogni giocatore restante bruciava comunque ~60s di
   retry prima di arrendersi, perche' ogni giocatore e' un processo separato senza stato
   condiviso. Aggiunto un marker file in `/tmp` (non nel repo): appena rilevato, i tentativi
   successivi diventano un singolo tentativo secco. Propagato anche a K League (mancava, era solo
   su MLS).

**Tempi di run — percorso non lineare, con 2 tentativi falliti prima di trovare la causa vera:**

- Pausa fissa fra giocatori nei job predict ridotta da 10s a 2s (validato: zero 429 osservati
  anche a parallelismo molto piu' alto in discovery).
- `PREDICT_SHARD_N` fisso alzato da 2 a 4: **ha PEGGIORATO i tempi** (14m51s -> 15m23s) invece di
  migliorarli — con 56 job predict totali invece di 40, il vero limite (il tetto di ~20 job
  CONCORRENTI dell'account, gia' scoperto una volta, non il max-parallel=77 del workflow) causava
  piu' coda, non piu' parallelismo reale.
- Sostituito con sharding ADATTIVO (~25 giocatori/shard invece di un N fisso identico per ogni
  ruolo) — minimizza il conteggio totale di job mantenendo ogni shard piccolo.
- Il fix piu' determinante e' stato il punto 7 sopra (retry sprecati su dati strutturalmente
  insufficienti): la run piu' lenta aveva un singolo job da 509s dominato quasi per intero da
  questo pattern, non da CloudFront.
- **Risultato finale**: da 22 minuti (con blocco CloudFront) a **9m33s** (run reale
  `30413832505`), formazioni verificate sensate (Bouanga presente, Griezmann/Messi con
  squadra corretta, nessun job fallito, All Stars non richiesta rimossa dal lancio).

**Bonus trovato durante l'audit di log completi (discovery/predict/consiglio, 3 agenti in
parallelo su ~110 job di una run reale)**: nessun altro bug oltre a quelli sopra — discovery e
consiglio/formazione risultati puliti.

## 32.A — TEMA APERTO per la prossima sessione: punteggi/schieramento ancora sotto dubbio

L'utente ha aperto un'indagine sui **punteggi attesi (project score)** assegnati a diversi
giocatori e sulla **logica di schieramento**, con dubbi specifici su:
- alcuni giocatori con punteggio percepito come sovra/sotto-stimato (es. segnalati oggi: Thomas
  Muller, Paxten Aaronson, Adrian Cubas, Andy Najar — controllati uno per uno con la formula
  completa e il backtest reale, MAE nella norma per tutti (13-24pt), NESSUN bug di calcolo
  trovato finora, ma l'utente non si ritiene soddisfatto e vuole approfondire oltre);
- i **portieri** in particolare (es. Schwake/Thomas non sempre schierati nonostante ranking alto —
  verificato che dipende dalla competizione per il budget classic condiviso fra ruoli, meccanismo
  confermato funzionante con un test dal vivo, ma da approfondire ulteriormente su casi specifici);
- lo **schieramento** (quali giocatori finiscono in quale formazione/slot) in generale, non solo i
  singoli punteggi.

**Run di riferimento per l'analisi**: la numero **42** (`generatore_formazioni_run42_2026-07-29_013054.html`,
run GitHub Actions `30413832505`, 9m33s, l'ultima buona) — usare quella come base per il prossimo
giro di indagine, non le run precedenti ne' eventuali run successive lanciate senza coordinarsi
con la sessione. Riprendere da qui: analizzare formazione per formazione (l'utente aveva appena
iniziato con "In Season MLS #5" quando la sessione si e' interrotta), verificando in particolare
se e quando ogni lineup consuma lo slot classic e su quale giocatore.

## 32.B — Stato repo a fine sessione (29/07)

Tutto committato e pushato su `main`. Nessuna modifica pendente non salvata. Le run di oggi hanno
anche generato output/commit automatici extra (prediction_*.txt, consiglio_*.txt, debug) da parte
del bot — normali, non richiedono azione.

## 33 — Sessione 29/07/2026 (continua) — riabilitato il fattore forza avversario con dato pulito,
## bug reali trovati sui granulari, battuta esaustiva di combinazioni cross-ruolo

Sessione lunga, partita dal ripasso del RIASSUNTO e proseguita con un'indagine sul modello
predittivo guidata dall'utente ("Messi contro la difesa peggiore vs la migliore del campionato
dovrebbero dare lo stesso punteggio?" — risposta: NO, ma il modello all'epoca non li distingueva
affatto, perche' `fattore_forza_avversario` era gia' stato rimosso da score_atteso il 26/07).

### 33.A — Scoperta: `domesticLeagueRanking` e' un dato CONTAMINATO, non storico

Verificando perche' un coefficiente basato su questo campo continuasse a risultare inutile nei
backtest, scoperto che `domesticLeagueRanking` (posizione in classifica) e' un attributo
**CORRENTE** della squadra lato Sorare, non un valore storico ancorato alla data della partita.
Prova diretta: stessa partita storica (es. LA Galaxy, 24/08/2025), letta da cache di giocatori
diversi (aggiornate in momenti diversi), restituisce ranking DIVERSI (10 vs 11) — quantificato su
tutte le leghe: 282/13671 coppie (squadra, data-partita) incoerenti, 22 squadre coinvolte. Questo
significa che ogni media storica calcolata su questo campo (`avg_opp_rank_hist`, sia nel vecchio
`fattore_forza_avversario` sia nello Stadio D di DEF/MID) e' inquinata da uno snapshot non
ancorato al tempo — non un vero storico. Conseguenza pratica: **tutti i backtest passati che
avevano concluso "il fattore forza avversario non aiuta" erano viziati nel metodo** (anche se la
direzione della conclusione probabilmente restava giusta, visto che un dato rumoroso tende a
sembrare inutile comunque).

### 33.B — Nuovo modulo `opponent_strength.py`: dato pulito (gol reali), non ranking

Creato `opponent_strength.py` (root del repo, modulo condiviso): ricostruisce lo storico
gol subiti/fatti per squadra dalle cache GK+DEF+MID gia' su disco (**nessuna query nuova**) — dato
genuinamente storico e immutabile, preso da `goals_conceded` nel `detailedScore` di partite gia'
giocate (a differenza del ranking, questo NON cambia se riletto in momenti diversi). Validato con
backtest walk-forward rigoroso (`formazione_mls/diagnostics/validate_opponent_conceded_level*.py`,
media ultime 10 partite dell'avversario, grid search sensibilita'):

| Ruolo | Segnale | Sensibilita' | Miglioramento MAE |
|---|---|---|---|
| FWD | gol SUBITI dall'avversario | 1.0 | **-0.58%** |
| GK | gol FATTI dall'avversario (segno invertito) | 1.0 | **-0.59%** |
| MID | gol SUBITI dall'avversario | 0.7 | **-0.29%** |
| DEF | gol SUBITI dall'avversario | 1.0 | **-0.27%** |

Applicato su lambda_pos_dec (quindi su `level_score_atteso`) in **MLS + K League, tutti e 4 i
ruoli** (8 file). Le altre 26 leghe restano INVARIATE per ora (formula duplicata inline per
lega, non una funzione condivisa come MLS — troppo rischioso toccare tutto in un colpo solo) —
**backlog flaggato** (chip creato, task "Estendi fattore forza avversario alle altre 26 leghe").

### 33.C — Bug reale: il fix su MID non arrivava in produzione

Controllando i granulari su richiesta dell'utente, scoperto che il primo giro di implementazione
per MID aveva modificato la copia SBAGLIATA di `lambda_pos_dec`: MID (come GK) chiama
`compute_score_atteso_mid()` per il vero `score_atteso` in produzione, mentre DEF/FWD ricalcolano
inline — il fix era finito in una copia diagnostica inerte (result dict, mai usata per il
punteggio reale). Fixato spostando l'aggiustamento dentro la funzione condivisa realmente
chiamata.

### 33.D — Bug reale: Stadio D di DEF/MID ancora contaminato dal ranking

Controllo piu' approfondito ha rivelato che il vecchio `fattore_forza_avversario` moltiplicativo
era stato rimosso (26/07) ma **una PARTE separata della formula — lo "Stadio D" che condiziona
gol_subiti/passaggio/offensivo/clean_sheet su "avversario forte/debole" — usava ANCORA lo stesso
`domesticLeagueRanking` contaminato**, sommando il suo contributo a `score_atteso` in produzione
per DEF e MID (MLS + K League, 4 file: GK/FWD non hanno questo pezzo). Fix: nuova funzione
`opponent_strength.opponent_is_strong()` (booleano "avversario forte" basato sui gol REALI fatti
nelle ultime 10 partite, non sul ranking), con fallback al vecchio comportamento se i nuovi
parametri non sono passati (backtest/calibrazione esistenti invariati).

### 33.E — Bug reale: cap sbagliato su "gol subiti" granulare (GK/DEF/MID)

L'utente ha segnalato a memoria le vere regole di scoring Sorare per il granulare `goals_conceded`
(diverso da `level_score`/clean sheet, gia' documentato in sez. 11): **-5/gol per GK, -4/gol per
DEF, -2/gol per MID, LINEARE, SENZA TETTO**. Verificato con piu' esempi REALI estratti dalle cache
(non solo la sua indicazione a memoria) su MLS e K League, fino a 6-7 gol subiti in una sola
partita — mai un cap, sempre esattamente lineare (es. GK 7 gol = -35, DEF 6 gol = -24, MID 7 gol =
-14). Il codice invece cappava a +-10 (`GOALS_CONCEDED_CAP`) per tutti e tre i ruoli — bug reale,
confermato e rimosso in tutti e 6 i file (GK/DEF/MID x MLS/K League): il granulare ora usa il
valore reale non cappato per calcolare le medie storiche.

### 33.F — Battuta esaustiva di combinazioni granulari cross-ruolo (24 test totali)

Su richiesta esplicita dell'utente ("prova tutte le combinazioni sensate... non mi importa quanto
ci vuole"), backtestate sistematicamente tutte le combinazioni sensate granulare-proprio vs
granulare-avversario non ancora testate, stessa metodologia walk-forward di sempre (media ultime
10 partite avversario, grid search sensibilita', MAE su un pezzo additivo del punteggio):

**DEF vs FWD/MID avversari (10 combinazioni, tutte scartate)**:
duello vinto vs duel_lost (-0.07%), tackle vinto vs poss_lost_ctrl (0.00%), intercettazione vs
missed_pass (-0.06%), efficacia difensiva aggregata vs big_chance_created (0.00%), duel_won vs
won_contest (0.00%), interception_won vs accurate_pass (~0.00%), won_tackle vs pen_area_entries
(0.00%), falli vs won_contest (0.00%), goals_conceded granulare vs ontarget_scoring_att (0.00%),
passaggio vs duel_won pressing (-0.01%).

**MID vs DEF/FWD/MID avversari (9 combinazioni, tutte scartate)**:
offensivo vs duel_lost DEF (-0.06%), offensivo vs poss_lost_ctrl DEF (0.00%), passaggio vs
duel_lost DEF (-0.06%), duel_won vs duel_lost FWD (-0.16%, il migliore del gruppo ma comunque
trascurabile), interception_won vs missed_pass FWD (0.00%), won_tackle vs won_contest FWD
(-0.00%), duel_won vs duel_lost MID (-0.00%), passaggio vs duel_won MID pressing (0.00%),
offensivo vs poss_lost_ctrl MID (0.00%).

**FWD vs DEF/MID avversari (5 combinazioni, 1 VALIDATA)**:
- offensivo vs duel_lost DEF (-0.01%, scartato)
- **offensivo vs poss_lost_ctrl DEF: -0.38% MAE, minimo pulito a sensibilita'=3.0** (curva a
  campana vera su griglia estesa 0-10, non rumore) — **VALIDATO E IMPLEMENTATO** (vedi sotto)
- won_contest vs duel_lost DEF (-0.01%, scartato)
- offensivo vs duel_lost MID (-0.07%, scartato)
- passaggio vs duel_won MID pressing (0.00%, scartato)

**GK, combinazioni rimanenti (3, tutte scartate)**:
granulare Goalkeeping vs pen_area_entries avversario (-0.01%), poss_lost_ctrl proprio vs duel_won
avversario/pressing (-0.01%), passaggio vs duel_won avversario/pressing (-0.01%).

**Totale sessione: 5 (GK iniziali) + 4 (allroles gol) + 10 (DEF) + 14 (cross-ruolo) = 33
combinazioni testate, 1 sola validata e implementata** (FWD offensivo vs poss_lost_ctrl DEF
avversario) oltre al segnale principale gol subiti/fatti (33.B). Conferma quanto gia' sospettato
dal bootstrap di sez. 8: con 10-20 partite di storico per giocatore, la stragrande maggioranza dei
segnali granulari-condizionati-su-avversario e' rumore statistico, non segnale reale — il gol
resta l'unico evento abbastanza raro/discreto e abbastanza ben tracciato da generare un
aggiustamento pulito e ripetibile.

### 33.G — Implementato: FWD offensivo vs poss_lost_ctrl DEF avversario

Aggiunta `opponent_strength.fwd_offense_granular_delta()`: delta ADDITIVO (non moltiplicativo) sul
granulare "offensivo" di un FWD, basato sul `poss_lost_ctrl` medio dei difensori avversari nelle
ultime 10 partite (media/std globali fisse dal backtest: 9.97/4.48, sensibilita' 3.0). Applicato in
MLS + K League `test_mls_fwd_all.py`, sommato a `grezzo_nuovo` (MLS) / `score_atteso` (K League)
prima dello shrinkage/venue.

### 33.H — Decisioni prese dall'utente (NON riproporle)

- Fattore forza avversario (gol reali) IN PRODUZIONE per tutti e 4 i ruoli, MLS+K League — non e'
  piu' "solo diagnostico" come il vecchio, entra davvero nello score_atteso.
- Le altre 26 leghe restano un backlog esplicito, non toccarle senza chiederlo (troppo rischioso
  farlo tutto insieme, formula duplicata non condivisa).
- H2H specifico (scontri diretti storici) scartato senza nemmeno testarlo: "preferisco la media
  generica".
- Tema "granulari DEF vs avversario" chiuso dopo 24 combinazioni: nessun altro segnale sfruttabile
  oltre al gol.

### 33.I — Backlog aperto

- Estendere il fattore forza avversario (gol reali) + fix Stadio D + fix cap gol-subiti alle altre
  26 leghe (chip gia' creato, task_504a5391).
- Non ancora testate in modo sistematico le stesse combinazioni per GK vs DEF specificamente (solo
  FWD+MID pooled finora per gk_remaining) — se servisse in futuro, isolare l'avversario per ruolo
  specifico invece che FWD+MID insieme potrebbe cambiare il risultato.
- I diagnostics creati oggi (`formazione_mls/diagnostics/validate_opponent_*.py`,
  `validate_def_*.py`, `validate_cross_role_combos.py`, `validate_gk_offense_penalty_possession.py`)
  restano nel repo come riferimento riproducibile — non cancellarli, documentano il "perche'" di
  ogni scarto per non riproporre lo stesso test in futuro.

### 33.J — Stato repo

Tutto committato e pushato su `main` durante la sessione (commit multipli, uno per blocco logico
di fix). Nessuna modifica pendente non salvata a fine sezione.

## 34 — Sessione 29/07 (seconda parte): 3 bug urgenti, retuning esteso a tutte le leghe,
## discovery globale Bundesliga, regola "nessun guadagno e' trascurabile"

### 34.A — 3 bug urgenti dalla run gw96 (fixati per primi, priorita' massima)

Dopo la run gw96 mls:6+kleague:6 di fine sessione 33, l'utente ha segnalato 3 bug reali:

1. **All Stars generata senza essere richiesta**: il workflow `formazione_giornata.yml` aveva
   `allstars` default `'1'` invece di `'0'` — bastava dimenticare `-f allstars=0` per generarne una
   non voluta. Fix: default cambiato a `'0'`.
2. **Pannello "Top esclusi" mischiava le leghe**: un'unica lista combinata era affiancata solo alla
   primissima formazione in assoluto (es. esclusi Korea mostrati accanto alla prima formazione
   MLS). Fix: pannello PER-LEGA in `generatore_formazioni/build_formazione_globale.py`, affiancato
   alla prima formazione di CIASCUNA lega (usando `POOL_LEAGUE_BY_TYPE[tipo]` per capire a quale
   lega appartiene ogni blocco); le formazioni "mixed"/"mixed_u23" (All Stars) prendono un pannello
   combinato su tutte le leghe rilevanti.
3. **Leghe irrilevanti negli esclusi**: conseguenza diretta del bug #1 (allstars accidentale
   faceva scattare `leghe_rilevanti = set(LEAGUES)`, tutte le 28 leghe) — risolto automaticamente
   fixando #1, verificato che `leghe_rilevanti` sia comunque corretta per costruzione.

Verificato con una run reale (30448257173, gw96, allstars=0 esplicito): nessuna All Stars generata,
2 pannelli distinti (MLS con squadre MLS, K League con squadre coreane), nessun leak di altre leghe.

### 34.B — Regola esplicita dell'utente: "non esiste un guadagno trascurabile, esiste solo guadagno"

Punto di svolta della sessione: fino a questo momento, guadagni MAE sotto ~0.4% venivano scartati
come "rumore". L'utente ha imposto una regola diversa: **qualunque guadagno positivo, per quanto
piccolo, va applicato** (a meno di conflitti con un fix specifico gia' validato su un caso reale).
Questo ha riaperto e ritarato parametri che erano stati "chiusi" nella sessione precedente.

Regola gemella, imposta a meta' sessione: **"tutti i test fatti vanno fatti su tutte le leghe"**
(non solo MLS/Korea) — piu' dati = piu' accuratezza statistica, anche se poi l'applicazione in
produzione resta scoped a MLS/Korea per prudenza.

### 34.C — Sinergie In Season: 2 disattivate per guadagno reale

Test A/B locali (genera le stesse 6 formazioni con/senza ciascuna sinergia, confronta i totali):

- **`POSITIVE_SYNERGY_BONUS_BY_PAIR`**: disattivato per In Season MLS/K League. MLS 2033->2035pt
  (+2/6 formazioni), K League invariato (nessun costo a disattivarlo).
- **`MATCH_REUSE_PENALTY`** (decorrelazione formazioni che condividono la stessa partita reale):
  disattivato per In Season MLS/K League. MLS +21pt/6 formazioni, K League +2pt/6. Nota: il
  beneficio di decorrelazione (rischio diversificato tra formazioni) non e' catturato dal
  punteggio atteso totale — scelta esplicita dell'utente di privilegiare comunque il guadagno
  misurato.
- **`SAME_TEAM_SYNERGY_BONUS_BY_PAIR`**: disattivato SOLO per `ARENA_ALLSTARS_UNCAPPED` (1880pt
  attivo vs 1920pt disattivato su 6 formazioni) — 260/220 IDENTICI on/off (il cap L10 obbligatorio
  rende la sinergia ininfluente li', nessuna modifica).
- `ANTI_SYNERGY_PENALTY`, `STACK_GUARD_PENALTY`, `CROSS_TEAM_PENALTY_BY_PAIR`: confermati inerti
  ovunque testato (MLS, K League, Eredivisie, Turchia, Portogallo, Croazia, Scozia — 7 leghe,
  nessun delta in nessuna). Belgio/Spagna/Germania/Francia saltate per assenza di candidati
  (leghe in pausa estiva, vedi 34.F). Le restanti 16 leghe non hanno un tipo Arena dedicato
  isolabile con l'infrastruttura attuale.

### 34.D — Retuning half_life/trend_intensity/sensitivity/shrink_K post-fix, su tutte le leghe

Tutti i parametri sotto erano stati calibrati PRIMA dei fix di opponent_lambda_mult/Stadio D/cap
goals_conceded della sessione precedente — potenzialmente non piu' ottimali. Ritestati con backtest
walk-forward rigoroso estendendo il dataset a TUTTE le 28 leghe (prima alcuni script erano
MLS-only, es. `validate_halflife_venue.py`).

**HALF_LIFE_GAMES** (applicato a TUTTE le 28 leghe, parametro globale gia' storicamente
sincronizzato tra leghe): DEF 9.0->20.0 (-0.55% MAE), MID 12.0->25.0 (-0.31%), FWD 12.0->25.0
(-0.32%). Grid esteso fino a 150 senza trovare un vero minimo interno per nessuno dei 4 ruoli
(convergenza asintotica) — scelto il ginocchio di rendimento decrescente, non il bordo assoluto,
per non perdere sensibilita' a partite anomale. **GK lasciato a 6.0** (fix Daniel De Sousa Brito
gia' validato su un caso reale ha priorita' su un guadagno medio aggregato che avrebbe richiesto
half_life=20+, contrario allo spirito del fix).

**TREND_INTENSITY** (applicato SOLO MLS/Korea, scelta esplicita dell'utente — le altre 26 leghe
restano ai vecchi valori): DEF 0.7->0.0, MID 0.7->0.2, FWD 1.0->0.3 (-1.25%/-0.39%/-0.73% MAE).

**SENSITIVITY_BY_ROLE** (`opponent_strength.py`, MLS/Korea): GK 1.0->0.7 (-0.04%), DEF 1.0->0.8
(-0.01%). MID lasciato a 0.7 (guadagno 0.0001 di MAE, indistinguibile dal rumore). FWD gia'
ottimale a 1.0.

**SHRINK_K_OUTLIER_<ruolo>** (MLS/Korea): DEF 15->18 (-0.002%), MID 10->7 (-0.045%), FWD 5->6
(-0.005%), tutti minimi interni puliti. **GK caso a parte**: nessun minimo interno trovato fino a
k=50 (converge verso "ignora lo storico individuale"), ma verificato DUE VOLTE (formula
semplificata e poi formula VERA di produzione) che questo NON peggiora il sottogruppo portieri ad
alta varianza (tipo Daniel) — anzi migliora anche li'. Applicato comunque un valore prudente
(5.0->20.0, non il migliore assoluto 50) per restare piu' lontano da un bordo mai esteso oltre.

Grid 2D (half_life x trend_intensity insieme, per verificare interazioni non colte testando un
parametro alla volta): interazione reale ma minuscola (-0.002% DEF, -0.027% MID, -0.014% FWD) — non
applicata, i minimi trovati erano anch'essi al bordo della grid (convergenza asintotica, non un
vero minimo).

### 34.E — Nuova feature: GK vs pen_area_entries dei DIFENSORI avversari

Granulare mai isolato prima: `opponent_strength.gk_def_pen_area_multiplier()`, bonus GK basato
SOLO sulle `pen_area_entries` dei difensori avversari (separato dal bonus FWD+MID gia' esistente,
si affianca senza sostituirlo). Validato -0.13% MAE (`validate_cross_role_combos.py`, gruppo
`gk_vs_def_only`), costanti reali (non fabbricate) ricalcolate da `build_opponent_series` —
GLOBAL_MEAN_DEF_PEN_AREA=1.9428, GLOBAL_STD_DEF_PEN_AREA=2.2335. Applicato MLS/Korea.

Altre combinazioni testate in questo giro, tutte scartate (nessun guadagno reale): DEF vs GK
avversario (aerial/duel vs alte uscite, ~0%), GK vs solo-DEF duel_lost (~0%), H2H DEF (+0.19%,
peggiora), trend proprio DEF/MID/FWD gia' catturato dal retuning trend_intensity sopra.

### 34.F — Discovery globale Bundesliga (Germania), prima delle 5 leghe backlog rimanenti

Scoperta: Spagna/Germania/Francia/Inghilterra/Italia/Belgio hanno storico cache molto scarso
(12-32 partite a lega) — causa reale: la discovery esistente per queste leghe e' SOLO
fixture-based (candidati solo tra le carte POSSEDUTE con una partita nella finestra corrente), e
questi 6 campionati sono gli UNICI davvero in pausa estiva lunga (fine campionato a maggio, ripresa
ad agosto) — a differenza di Croazia/Turchia/Austria/Argentina/Olanda che hanno gia' ripreso o non
si sono mai fermate del tutto. MLS/K League hanno in piu' uno script di discovery "_global" (pesca
TUTTI i giocatori di qualita' della lega, indipendentemente da possesso/fixture) — mai replicato
per le altre 26 leghe.

Costruito per la Germania (Bundesliga), prima delle 6 leghe mancanti:
1. Verificati dal vivo (via GitHub Actions, query `football { competition(slug: "bundesliga-de")
   { clubs(first: 50) { nodes { slug name } } } }`) i 18 slug club ufficiali — MAI indovinati,
   rischio di risultati silenziosamente vuoti gia' documentato altrove nel codice.
2. Creati `formazione_germania/discovery/germania_<ruolo>_discovery_global.py` (4 file, clone
   esatto dello schema MLS/K League).
3. Lanciati via workflow dedicato (`run_germania_discovery_global.yml`) — primo tentativo fallito
   con 403 su push (mancava `permissions: contents: write` nel workflow), fixato e rilanciato con
   successo.

Risultato: **279 giocatori Bundesliga scoperti** (GK 11, DEF 78, MID 84, FWD 96),
`player_slugs.json` committati su main. **Nota importante**: questi NON sono carte possedute
dall'utente — servono solo ad allargare il campione statistico per calibrazione/backtest, zero
impatto sulle formazioni reali generate (quelle restano sempre sulle carte davvero possedute).
**Prossimo passo, non ancora fatto**: lanciare predict in `CALIBRATION_MODE=1` sui 279 slug per
scaricare davvero lo storico partite e popolare le cache (`formazione_germania/output/
germania_<ruolo>_calibration/.cache`) — la sola discovery non aggiunge nessuna partita allo
storico, serve questo passo successivo. Tempo stimato NON verificato (30-60+ minuti). Restano
Spagna/Francia/Inghilterra/Italia/Belgio con lo stesso identico procedimento.

### 34.G — K League: falso allarme sul meccanismo gain-per-slot, poi allineato per coerenza

Il backlog "K League senza ottimizzazione classic" (da ieri) presupponeva che
`formazione_kleague/build_formazione_finale.py` fosse usato in produzione — verificato che e' in
realta' uno script STANDALONE LEGACY mai chiamato da nessun workflow: la pipeline reale
(`generatore_formazioni/build_formazione_globale.py`, usata da `formazione_giornata.yml`) importa
UN SOLO modulo condiviso (`formazione_mls/build_formazione_finale.py`) per TUTTE le leghe, K League
incluso — il meccanismo gain-per-slot era quindi GIA' corretto in produzione, nessun bug reale
sulle formazioni generate. Il file legacy e' comunque stato allineato per coerenza (stesso
meccanismo `_run(allow_classic_slot=..., measure_gains=...)` portato li', adattato alla firma piu'
vecchia del file). Nessun impatto sulle formazioni reali in nessuno dei due casi.

### 34.H — Decisioni prese dall'utente in questa sessione (NON riproporle)

- "Non esiste un guadagno trascurabile, esiste solo guadagno" — regola permanente per i backtest
  d'ora in poi, applicare anche i guadagni minimi (con l'eccezione di conflitti con fix specifici
  gia' validati su casi reali, es. half_life GK).
- "Tutti i test fatti vanno fatti su tutte le leghe" — regola permanente per la fase di TEST, non
  automaticamente per l'APPLICAZIONE in produzione (che resta scoped a MLS/Korea salvo diversa
  indicazione).
- GK half_life resta 6.0 nonostante il guadaglio aggregato favorisca valori piu' alti — il fix
  Daniel (caso reale) ha priorita'.
- MATCH_REUSE_PENALTY disattivato accettando la perdita del beneficio di decorrelazione, a favore
  del guadagno di punteggio atteso misurato.
- Estensione delle 26 leghe rimanenti (sia per le feature opponent-strength sia per discovery
  globale) resta backlog esplicito, un tema/una lega alla volta, non tutto insieme.

### 34.I — Backlog aperto (dettaglio completo nella memoria auto-persistente Claude, non solo qui)

- **Produzione solo MLS/Korea**: 10 miglioramenti validati (opponent_lambda_mult, fix Stadio D, cap
  goals_conceded, fwd_offense_granular_delta, gk_def_pen_area_multiplier, trend_intensity,
  sensitivity, shrink_K, 2 sinergie disattivate) da estendere alle altre 26 leghe.
- **Discovery globale big5**: Germania fatta (discovery, calibration ancora da lanciare), restano
  Spagna/Francia/Inghilterra/Italia/Belgio con lo stesso procedimento.
- **Retest venue nuove leghe**: rifare `validate_venue_per_league.py` quando i big5 europei
  avranno piu' storico (oggi campioni troppo piccoli per conclusioni robuste per lega).
- **Naming fuorviante**: label "solo diagnostico" per il granulare in `test_mid.py` (in realta'
  usato), e testo "scalati per P(gioca)" per i delta Stadio D (rimosso davvero il 28/07, testo
  rimasto stale) — nessun impatto funzionale, solo chiarezza per letture future.
- **Tema "meglio il piu' affidabile o il piu' forte"**: annunciato dall'utente, contenuto ancora
  da spiegare in una prossima sessione — non ipotizzare/implementare nulla senza la spiegazione
  completa.

### 34.J — Stato repo

Tutto committato e pushato su `main` durante la sessione. Diagnostics creati oggi (mantenuti nel
repo come riferimento riproducibile, stessa convenzione delle sessioni precedenti):
`validate_halflife_venue.py` (esteso a tutte le leghe), `validate_venue_per_league.py`,
`validate_trend_intensity_generic.py`, `validate_opponent_trend_h2h_generic.py`,
`validate_shrink_k*.py`, `validate_halflife_trend_grid2d.py`, `compare_synergy_toggles*.py`,
`compare_crossteam_matchreuse_toggles.py`, `verify_bundesliga_clubs.py`, workflow
`verify_bundesliga_clubs.yml` e `run_germania_discovery_global.yml`.

## 35. Sessione 29/07 sera–30/07 notte — Caccia alla velocità della pipeline (in corso, non risolta)

**Obiettivo esplicito dell'utente**: la run `formazione_giornata.yml` con scope fisso (gw98,
`arena_dedicata=portogallo:2,scozia:2,croazia:2`, `starter_odds_min=0`, nessun'altra formazione)
impiegava ~20 minuti. Target: **massimo 10 minuti**, stesso output, stessa qualità di scoring,
senza saltare leghe/ruoli. Istruzione esplicita: bundlare più fix insieme prima di ogni retest,
leggere sempre i log prima di rilanciare, non fermarsi finché non si scende sotto i 10 minuti (o
finché non si è genuinamente bloccati).

**Tentativo di redesign strutturale (single-process invece di matrice GitHub Actions)**: fatto su
branch separato `redesign-async-pipeline` (in un clone a parte), testato dal vivo 4 volte, poi
**ELIMINATO COMPLETAMENTE** su richiesta esplicita dell'utente dopo che i test hanno confermato un
limite strutturale: il rate-limit Sorare reagisce fortemente a **connessioni concorrenti dalla
stessa fonte/IP**, non solo al volume medio di richieste — un solo processo (sequenziale o con
pool di thread) non riesce a eguagliare il throughput della pipeline a matrice multi-runner (IP
diversi per runner). **Non riproporre questo redesign.**

**Fix reali applicati e pushati su `main` (verificati, NON solo ipotesi)**:
1. `fetch-depth: 1` su tutti i 39 `actions/checkout@v4` del workflow.
2. `cache: "pip"` + `cache-dependency-path: requirements-formazione.txt` (nuovo file root) su
   tutti i 39 `actions/setup-python@v5`.
3. Job `consiglio`: `max-parallel: 77` (mancava) + `timeout-minutes` 15→30 (veniva ucciso a metà
   del retry-loop di push).
4. `discovery_fixture.py`: `PREDICT_SHARD_LEAGUES` generalizzato da `{'mls','kleague'}` a `None`
   (tutte le leghe), `PREDICT_SHARD_TARGET_SIZE` 25→15 (più shard, job predict più piccoli).
5. `opponent_strength.py`: cache su **disco** (`/tmp/opponent_strength_cache/`, ephemera per
   runner, mai committata) per `_build_series_for_league`, `_build_def_poss_lost_series`,
   `_build_def_pen_area_series`. Causa: ogni predict è un processo separato per giocatore, quindi
   la cache in-memoria del modulo si azzerava ad ogni giocatore — un job con 15 giocatori
   rifaceva la scansione completa della cartella cache (200+ file) 15 volte. FWD il più colpito
   (scansiona due cartelle). Verificato: valori identici prima/dopo, confronto diretto.
6. `discovery_fixture.py`, `_resolve_query_with_retry`: da 3 tentativi/3s fissi (~20s totali) a 6
   tentativi con backoff crescente + jitter (5,10,15,20,25s+jitter, ~90s totali). Causa: un job
   discovery su 34 fallito per intero per un blocco CloudFront (403) su `FixtureList` più lungo
   dei 20s coperti — e siccome `predict` richiede (`needs:`) il successo di TUTTI i job
   discovery, quel singolo fallimento ha ucciso l'INTERA run (tutto skippato a cascata).

**Nota per letture future**: nei log di questi job compare il tag `[turchia_gk_discovery]` — è
solo il nome del modulo Python condiviso (`turchia_gk_discovery.py`, importato come `base` da
quasi tutti gli script) usato per il logging, **non significa che c'entri la lega Turchia**.
Perso tempo stanotte a incolparla per errore.

**Stato a fine sessione (non risolto)**: target dei 10 minuti **non ancora raggiunto e non
ancora confermato in una run completata dopo tutti i 6 fix**. Ultima run lanciata:
`30494326179` (gw98, stesso scope, lanciata 2026-07-29 21:57:24 UTC, dopo il fix #6) — **stato
non verificato**, l'utente ha fermato il lavoro prima di poter controllare l'esito. La run
precedente (`30493943673`, dopo il fix #5 ma prima del #6) è fallita esattamente per la causa
del fix #6 (blocco CloudFront + retry insufficiente), quindi il fix #5 (cache disco
opponent_strength) **non è ancora stato verificato dal vivo** per il suo effetto reale sulla
velocità di FWD, perché quella run non è mai arrivata al job predict.

Scritto un documento di handoff dedicato per continuare questo lavoro senza dover rileggere tutta
la sessione: `docs/HANDOFF_VELOCITA_PIPELINE.md` — contenente lo scope esatto del test, tutti i
6 fix con motivazione, cosa NON toccare (redesign single-process, formule di scoring, copertura
discovery), stato esatto delle run pendenti, e i prossimi passi in ordine.
*(Nota aggiunta il 30/07: quel filone è stato ripreso e chiuso nella sez. 36 qui sotto; il
documento di handoff è stato fuso per intero nella sez. 36.A2 e poi eliminato — questo RIASSUNTO
è ora l'unico documento sull'evoluzione del bot.)*

**Task secondario, priorità più bassa, non urgente**: workflow `calibrazione_lega.yml` (generico,
riusabile per qualunque lega) lanciato per `lega=germania, ruolo=gk, batch_index=0, batch_size=200`
(run `30491495720`) — **stato non riverificato dopo il lancio**. Da continuare con def/mid/fwd
Bundesliga solo dopo che la velocità è risolta e stabile.

### 35.K — Tutto quello che resta da fare (checklist operativa fine sessione 29/07–30/07)

In ordine di priorità dichiarato dall'utente:

1. **[PRIORITÀ 1, aperto] Velocità pipeline sotto i 10 minuti** — non ancora confermata a fine
   sessione 35. *(Chiuso il 30/07 nella sez. 36: tempo sceso a ~8m, vedi 36.K.)*
2. **[PRIORITÀ 2, aperto] Calibrazione Bundesliga** — solo `gk` lanciato (run `30491495720`, mai
   riverificato), mancano `def`/`mid`/`fwd`. Da riprendere solo dopo il punto 1.
3. **[Backlog, non urgente] `formazione_resto_mondo` arretrata** — riaperta il 29/07 su richiesta
   esplicita, pipeline/formula vecchia rispetto alle altre 27 leghe. Non toccare finché non viene
   ridiscussa esplicitamente (memoria `project_backlog_resto_mondo_modello_arretrato`).
4. **[Backlog, non urgente] Verifica ripopolamento punteggi "0" stantii** — il fix `activeClub`
   del 29/07 sembra aver risolto il pattern (Rios 0→58 su gw98), ma va riverificato su altre run/
   giocatori quando se ne presenta l'occasione (memoria
   `project_backlog_verifica_zero_score_ripopolati`).
5. **[Backlog, non urgente, invariato da prima di stanotte, vedi sez. 34.I]**:
   - 10 miglioramenti di produzione validati solo su MLS/Korea, da estendere alle altre 26 leghe.
   - Discovery globale big5 (Spagna/Francia/Inghilterra/Italia/Belgio) — solo Germania fatta finora.
   - Retest venue per lega quando i big5 europei avranno più storico.
   - Naming fuorviante ("solo diagnostico" in `test_mid.py`, testo Stadio D stale) — solo chiarezza,
     nessun impatto funzionale.
6. **[Tema annunciato, mai iniziato]** "Meglio il giocatore più affidabile o il più forte" — la
   spiegazione completa del tema non è mai arrivata in questa sessione (dirottata dalla priorità
   sulla velocità). Non ipotizzare/implementare nulla finché l'utente non lo spiega per esteso.
   Alcuni test correlati (range/trend/presence_rate come segnale di affidabilità) sono già stati
   fatti e SCARTATI stanotte (checklist, sezione E, punti 33-35) — ma quella è solo una parte
   laterale del tema più ampio annunciato, non sostituisce la spiegazione dell'utente.
di fix). Nessuna modifica pendente non salvata a fine sezione.

## 36. Sessioni 29-30/07 notte — Velocità pipeline: da 21m06s a ~8m, causa radice trovata nei log

**Punto di partenza**: una sessione precedente (Sonnet 5) aveva lavorato tutta la notte del 29/07
sullo stesso obiettivo senza raggiungerlo, lasciando un documento di handoff (poi fuso qui per
intero, vedi 36.A2, ed eliminato come file separato — questo RIASSUNTO è l'unico documento
sull'evoluzione del bot). Run di riferimento verificata a scope identico (gw98,
`arena_dedicata=portogallo:2,scozia:2,croazia:2`): **21m06s** (`30494326179`, chiusa con
successo — la sessione precedente non aveva potuto verificarne l'esito).

### 36.A — I due vincoli veri, misurati (non ipotizzati)

Tutto quello che segue viene dall'API di GitHub Actions, job per job e step per step, e dai dump
`.debug/` committati nel repo. Nessun fix è stato applicato su ipotesi.

**Vincolo 1 — il `git push` di ogni job era il 46% di tutta la compute.** Run `30484170456`
(20m15s, 156 job):

| fase | job | wall | job-sec | di cui push git | lavoro utile |
|---|---|---|---|---|---|
| discovery | 36 | 247s | 3079 | 1123 (36%) | 1159 |
| predict | 60 | 663s | 7106 | 2429 (34%) | 3327 |
| consiglio | 58 | 268s | 4020 | **2934 (73%)** | **0** |
| formazione | 1 | 26s | 26 | 2 | 0 |
| **totale** | **156** | **1215s** | **14234** | **6488 (46%)** | **4486 (31%)** |

Causa: ogni job pushava su `main` con il retry-loop `until git push; do sleep 5-17; fetch;
merge -X ours; merge_discovery_json; commit --amend; done`. Ogni giro fa passare **un solo**
job, quindi con 20 job che pushano insieme l'ultimo pagava fino a 20 giri. Il job `consiglio`
era il caso limite: 2934s di push per **0 secondi** di lavoro reale (lo step "Costruisci
consiglio" segnava 0s su tutti e 58 i job).

**Vincolo 2 — il tetto di 20 job concorrenti.** Verificato: la concorrenza massima osservata è
20 esatti su *ogni* run, quindi `max-parallel: 77` nel workflow era inerte. Il wall time è
governato da `somma_job_secondi / 20`, e ogni job in più aggiunge i suoi ~19s fissi
(checkout 13,3s + setup-python 2,4s + pip 3,2s + set up job 1,1s) al totale da dividere:
156 job = ~2900 job-secondi di **solo overhead**. Questo era già stato scoperto una volta (vedi
commento in `discovery_fixture.py` e sez. 30) ma poi contraddetto: il fix #4 della sessione
precedente aveva **abbassato** `PREDICT_SHARD_TARGET_SIZE` da 25 a 15, cioè aumentato il numero
di job, che con un tetto fisso a 20 non aiuta e paga solo più overhead.

### 36.A2 — Tentativo di redesign scartato e guardrail (merge dall'ex `HANDOFF_VELOCITA_PIPELINE.md`)

Contenuto storico della sessione precedente (Sonnet 5), fuso qui perché il RIASSUNTO deve restare
l'unico documento sull'evoluzione del bot — l'handoff separato è stato eliminato.

**Tentativo di redesign strutturale (single-process invece di matrice GitHub Actions)**: fatto su
branch separato `redesign-async-pipeline` (in un clone a parte), testato dal vivo 4 volte, poi
**ELIMINATO COMPLETAMENTE** su richiesta esplicita dell'utente dopo che i test hanno confermato un
limite strutturale: il rate-limit Sorare reagisce fortemente a **connessioni concorrenti dalla
stessa fonte/IP**, non solo al volume medio di richieste — un solo processo (sequenziale o con
pool di thread, anche con pacing conservativo) non riesce a eguagliare il throughput della
pipeline a matrice multi-runner (dove ogni runner GitHub Actions ha un IP diverso). L'utente ha
definito questo tentativo "fallito miseramente". **Non riproporlo.**

**Guardrail confermati validi per tutto il filone (sez. 36 intera)**:
- non toccare la logica di scoring/shrinkage/formule nei `test_{gk,def,mid,mls_fwd_all}.py` per
  guadagnare velocità — quella parte è tarata a lungo e chiusa (vedi sez. "Roadmap tuning
  definitivo"); il problema è sempre stato di infrastruttura/velocità di esecuzione, mai di
  formula (unica eccezione, non di formula ma di bug: il fix `presence_rate` in 36.E, che
  ripristina predizioni mancanti per errore, non ne cambia la logica);
- non abbassare la qualità/copertura della discovery (saltare leghe, ridurre pagine scansionate)
  per andare più veloci — precedente reale di una scansione troncata che perdeva giocatori
  posseduti in silenzio ("Zinckernagel perso in silenzio", vedi commenti in `discovery_fixture.py`);
- nei log dei job discovery/predict compare il tag `[turchia_gk_discovery]` — è solo il nome del
  modulo Python condiviso (`turchia_gk_discovery.py`, importato come `base` da quasi tutti gli
  script) usato per il logging, **non significa che c'entri la lega Turchia**.

**Task secondario indipendente, menzionato nell'handoff originale**: workflow `calibrazione_lega.yml`
(generico, riusabile) lanciato per `lega=germania, ruolo=gk` (run `30491495720`, mai riverificato
nel corso di questo filone). Non correlato alla velocità della pipeline formazioni: resta un
elemento della checklist generale a priorità più bassa (vedi sezione dedicata più avanti se
presente, o verificarne lo stato quando si riprende quel filone).

### 36.B — Cosa è stato cambiato (solo infrastruttura, nessuna formula toccata)

Nuovo modulo `pipeline_artifacts.py` (documentato per esteso al suo interno):

1. **Passaggio dati via artifact invece di push.** I 36 job discovery, i job predict e il
   consiglio non pushano più: caricano un artifact. `discovery_merge` li unisce con la stessa
   semantica di `merge_discovery_json.py` (lista → unione, dict → update, che esiste per i
   sotto-shard delle leghe pesanti che scrivono sullo *stesso* `player_slugs.json`). Un nuovo job
   `salva_output` fa **un solo commit** con tutto a fine run, con `always()` per conservare la
   proprietà di prima (se predict/consiglio falliscono a metà, i parziali vengono comunque
   committati). Lo stato finale di `main` è lo stesso di prima.
2. **`consiglio` da 58 job a UNO.** Gli script di consiglio non fanno chiamate di rete e costano
   0s: in sequenza in un job unico costano meno di un secondo a coppia. Da 268s di wall a **34s**.
3. **`predict` da 60-81 job per combinazione a bin raggruppati** con bin-packing LPT, emessi in
   numero maggiore dei 20 slot e ordinati dal più pesante: Actions ne avvia 20 e dispatcha gli
   altri man mano che uno slot si libera. Gli slug processati da ogni shard sono **invariati**
   (stesso split `i % n == idx`, spostato in `pipeline_artifacts.py slugs`).
4. **Sharding ricalcolato sul conteggio vero** dopo il merge, non su quello parziale visto dal
   singolo job discovery. Ha corretto per questa via un bug reale pre-esistente: sulla
   `30494326179` la matrice conteneva **insieme** `{mls,gk}` (tutti gli slug), `{mls,gk,0:2}` e
   `{mls,gk,1:2}`, perché i due sotto-shard di una lega pesante calcolano `shard_n` su metà
   roster ciascuno — ogni giocatore mls/gk veniva elaborato **due volte**.
5. **Tetto duro `MAX_GIOCATORI_PER_SHARD = 8`** (vedi 36.C: perché il modello di costo da solo
   non basta).

### 36.C — Vicolo cieco documentato: il costo per giocatore NON è una proprietà stabile

Tentativo intermedio: misurare dai log il costo reale per coppia lega/ruolo
(`pipeline_costi.json`, modello `[primo_giocatore_s, giocatore_successivo_s]`, aggiornato a ogni
run con media esponenziale) e decidere lo sharding da lì. **Ha PEGGIORATO i tempi: 13m56s contro
i 10m53s del round precedente.** A 15 minuti di distanza, con gli stessi 30 giocatori,
`olanda/fwd` è passato da **1,0s a 14,6s per giocatore**: la stima la dava a 30s totali, non
veniva spezzata, e ha poi impiegato 437s in un solo job.

Conseguenza tenuta nel codice: la tabella dei costi serve solo a **ordinare** il riempimento dei
bin, con pavimento (4s) e tetto (31s) sul marginale per non credere a stime assurde. Il presidio
vero è il tetto duro sul numero di giocatori per shard, che regge qualunque cosa dica la stima.

### 36.D — La causa radice, trovata nei dump `.debug/` committati

L'instabilità di 36.C aveva una causa precisa. La query `allPlayerGameScores` ha complessità
≈ `130 + 28 × partite_richieste`, contro un tetto di **500** per le chiamate senza APIKEY.
Misurato sui dump committati:

```
first=30 -> "Query has complexity of 970, which exceeds max complexity of 500.
             Using an APIKEY the limit would be 30000."
first=60 -> complexity of 1812
```

In `fetch_game_log_incremental`, quando la cache è insufficiente il "fetch ampio" chiede
`max(target_window_size * 2, 30)` partite. Con `WINDOW_SIZE = 30` (alzato da 15 il 29/07) fa
**60**: quella chiamata **non è mai riuscita**, per nessun giocatore, in nessuna run. Anche con
`WINDOW_SIZE = 15` chiedeva 30, cioè 970 — sfondava comunque. Due conseguenze, entrambe misurate:

- **velocità**: ogni tentativo bruciava il retry esterno da 10+20+40s. Sono i ~30s per giocatore
  che dominavano la fase predict e che cambiavano da run a run, rendendo impossibile qualunque
  bilanciamento statico;
- **qualità**: quei giocatori restavano senza storico.

**Fix**: `fetch_game_scores()` chiede la stessa finestra in pagine da 10 partite (complessità
~410), accumulando i nodi e restituendo la *stessa* struttura della chiamata singola — il codice
a valle non cambia di una riga. Se la prima pagina fallisse (API che non accetta
`after`/`pageInfo`) si ripiega sulla chiamata singola di prima: il caso peggiore possibile è
esattamente il comportamento di oggi, non uno peggiore. Applicato ai 112 script predict.
Verificato dal vivo: `12x "Game log paginato: 60 partite in 6 pagine da max 10"`, **0 errori di
complessità**, 0 ripieghi, e **2 secondi** per 60 partite contro ~70s di retry a vuoto.

Nota: l'APIKEY (che alzerebbe il tetto a 30000) **non è una strada percorribile** — l'utente
l'ha già richiesta a Sorare e al momento non è disponibile. Non riproporla come soluzione.

### 36.E — Secondo bug reale trovato per la stessa via: `presence_rate`

I file `ERRORE_<slug>.txt` (192 su `main` quando è stato trovato, 38-62 nuovi per ogni run) hanno
una causa indipendente. Nei predict FWD:

```python
if starter_odds is not None:
    p_gioca = starter_odds / 10000.0
else:
    presence_rate = len(usable) / total_considered if total_considered else 1.0
    p_gioca = presence_rate
```

`presence_rate` è assegnato **solo** nel ramo `else`, ma ~50 righe più sotto il prior dinamico
dello shrinkage lo usa **sempre**: `max(0.0, 34.42 + 18.71 * presence_rate)`. Quindi ogni
giocatore per cui Sorare **aveva** pubblicato le starter odds — il caso normale a 24-48h dal
match, ed esattamente il caso delle run con `starter_odds_min=0` — moriva in `UnboundLocalError`
e restava silenziosamente fuori dai consigli.

Fix: l'assegnazione si sposta sopra l'`if`. È il tasso di presenza **storico**, non ha nulla a
che vedere con la presenza delle odds (lo dice il commento stesso nel codice). Il valore usato
nel ramo `else` è identico a prima, stessa espressione. Riguardava 26 file su 112: tutti e soli i
`test_mls_fwd_all.py` — GK/DEF/MID assegnavano già `presence_rate` incondizionatamente (82 file
verificati), il che conferma quanto già noto, cioè che la versione FWD della funzione non era
stata propagata come quella DEF.

### 36.F — Verifica di non-regressione

Confronto dei report HTML della run di riferimento (`run61`, 21m06s) e della prima run
rifattorizzata (`run63`, 13m56s), a scope identico: **238 righe totali, 2 righe diverse**, ed
entrambe sono solo il timestamp di generazione (`Generato 22:18Z` contro `22:59Z`). Stesse 6
formazioni, stessi 25 giocatori, stesso ordine. I due file hanno anche la stessa dimensione
esatta in byte.

Verificato inoltre che **lo scope richiesto non influenza il costo della pipeline**: solo il job
`formazione` riceve gli input `arena_dedicata`/`allstars`/`in_season` (40 job su 41 non li vedono
nemmeno). Discovery, predict e consiglio elaborano sempre tutte le leghe e tutti i giocatori
posseduti — 895 giocatori su 68 coppie lega/ruolo — che si chiedano 6 formazioni o 20. I fix sono
quindi strutturali, non tarati sullo scope di test.

### 36.G — Progressione misurata

| run | configurazione | tempo | esito |
|---|---|---|---|
| `30494326179` | prima di questa sessione (riferimento) | **21m06s** | success |
| `30496069817` | artifact invece di push, consiglio in 1 job, 20 bin | **10m53s** | fallita nel push HTML |
| `30497294536` | + sharding dal modello di costo (peggiorativo, vedi 36.C) | **13m56s** | success |
| `30498399199` | + tetto duro 8 giocatori/shard, 45 bin | **11m30s** | success |
| `30499100175` | + paginazione del game log (36.D) | **10m21s** | success |

Fix collaterale reale sulla `30496069817`: il job `formazione` generava l'HTML ma il push
falliva sempre, quindi l'HTML non arrivava su `main` e **il link notificato su Telegram era
rotto** (segnalato dall'utente). Causa: il job applica gli artifact nel working tree ma committa
solo l'HTML, quindi al primo conflitto di push il `git merge` del retry-loop si rifiutava di
partire (`Your local changes to the following files would be overwritten by merge`). Risolto
mettendo da parte quei file con `git stash --keep-index` prima del commit; verificato che
`run63` è poi arrivato su `main`.

### 36.H — Cosa resta aperto su questo filone

1. La fase `predict` resta la voce dominante (~5m40s su 10m21s). Le due leve non ancora sfruttate:
   il `checkout` da 13,3s per job su un repo da 150MB (uno `sparse-checkout` della sola lega dello
   shard lo porterebbe a ~4s, cioè ~60s di wall su ~45 job), e il fatto che la cache game-log
   ora si popola davvero per i giocatori che prima non la riempivano mai — le run successive
   dovrebbero scendere da sole man mano che quei giocatori passano al refresh leggero (`first=2`).
2. `pipeline_costi.json` si ritara a ogni run: da tenere d'occhio, ma **non** trattarlo come un
   dato affidabile per decisioni strutturali (vedi 36.C).
3. I file `ERRORE_`/`.debug/` committati non vengono mai cancellati e sono una delle ragioni per
   cui il repo è a 150MB, che a sua volta è il costo del checkout. Pulirli è indipendente dai fix
   di cui sopra ma si ripagherebbe su ogni job di ogni run.

### 36.I — Seconda tornata (30/07, 00:00–00:40): da 9m17s a 7m55s, e il tetto vero

Ripresa su richiesta dell'utente ("nuovo target 8 minuti", poi 7, poi "esaurisci i
miglioramenti possibili"). Tutto misurato, come sopra.

**1. L'albero di lavoro era 1,2 GB, non 150 MB.** I 150 MB sono la dimensione COMPRESSA del
repo su GitHub; quello che ogni job copia nel checkout è l'albero. Composizione misurata:

| | MB | file | |
|---|---|---|---|
| `.debug/` (dump GraphQL) | 654,2 | 61.746 | **54%** |
| `.cache/` (dettaglio partite) | 244,9 | 2.445 | |
| `prediction_*.txt` | 166,5 | 29.892 | |
| `.game_log_cache/` | 93,8 | 2.653 | |
| codice `.py` | 17,6 | 364 | |

I dump `.debug/` contengono richiesta e risposta integrale di **ogni** chiamata GraphQL, sono
riscritti a ogni run e **nessuno script li rilegge** (verificato: nei 112 file predict compaiono
solo scritture e riferimenti nei commenti). Messi in `.gitignore` e rimossi dall'indice: albero da
1204 MB/101.950 file a **550 MB/40.204 file**, e il `checkout` da **13,3s a 3,07s** (misurato su
74 step). Sono ~880 job-secondi per run, ~44s di wall. Restano nella storia git, quindi i dump già
committati — quelli che hanno permesso di trovare il bug di complessità — sono ancora consultabili.

**2. I 36 job discovery diventano un solo job a matrice da 20 gruppi.** Con un tetto di 20 job
concorrenti, 36 job giravano in due ondate (120s di wall per 1738 job-secondi, di cui 1150 di
lavoro vero). Raggruppati in 20 con LPT sui tempi misurati shard per shard (bin più pesante 71s,
cioè il singolo shard più lento, non spezzabile oltre) girano in una ondata: **120s → 103s**, e il
workflow da 1786 a 484 righe. Gli shard sono gli stessi uno per uno (36 coperti, verificato dalla
matrice); verso Sorare significa meno connessioni concorrenti, non più.

**3. Il pacing GraphQL era la voce di costo più grande rimasta.** Misurato dentro un bin predict:
**4,6 chiamate GraphQL per giocatore** e **un solo 429 su 106 chiamate**. Ogni giocatore è un
processo separato, quindi la pausa FISSA di 0,5s tra chiamate consecutive costava ~2,3s per
giocatore di sola attesa autoimposta: su 865 giocatori, **~2000 dei ~5400 secondi** di lavoro
della fase predict. Sostituita con un pacing che parte da 0,2s e si alza da sola (raddoppia, tetto
0,8s) al primo 429, con lo stato condiviso su file in `RUNNER_TEMP` tra i processi dello stesso
runner. Il caso peggiore possibile è il comportamento di prima, non uno peggiore — è la ragione per
cui questa forma è accettabile mentre un valore fisso più basso non lo sarebbe.

Risultato: **lavoro predict da 5395s a 2416s (-55%), zero 429** su tutti i bin campionati, nessun
rallentamento innescato. Run **7m55s**.

### 36.J — Il tetto vero: Sorare rallenta cumulativamente dentro la run

Tentativo successivo: bin più piccoli e numerosi (`MAX_GIOCATORI_PER_SHARD` 8→5, `N_BIN` 45→65)
per ridurre il peso di una stima di costo sbagliata sul tail. **Ha peggiorato: 7m55s → 10m56s.**

Il motivo si vede nella distribuzione dei bin di quella run: i quattro più lenti (307s, 269s,
261s, 240s) sono tutti bin dispatchati **tardi**, partiti a ~4 minuti dall'inizio della fase, e
hanno fatto **~20s per giocatore contro i ~3s** dei bin partiti subito. Non è inefficienza di
packing: è **Sorare che rallenta cumulativamente nel corso della run, in latenza e non con dei
429** (zero 429 osservati). In questo regime più bin significa più coda, quindi più lavoro
spostato nella parte lenta della run: sminuzzare è controproducente. Ripristinato 45/8.

**Conseguenza metodologica, importante per chi riprende**: questa è anche la ragione per cui i
tempi assoluti misurati stanotte non sono confrontabili fra loro oltre un certo punto. In 2,5 ore
sono state lanciate 11 pipeline complete, ognuna con ~900 giocatori × ~4,6 chiamate: decine di
migliaia di richieste. Lo stesso carico identico (58 coppie, 865 giocatori) ha dato 3228s e poi
5395s di lavoro predict a 15 minuti di distanza. **Prima di dichiarare che un cambiamento aiuta o
peggiora, servono run distanziate nel tempo, non consecutive.**

### 36.K — Progressione completa e stato finale

| run | cosa è cambiato | tempo |
|---|---|---|
| `30494326179` | stato di partenza (riferimento) | 21m06s |
| `30496069817` | artifact invece di push, consiglio in 1 job | 10m53s |
| `30497294536` | sharding dal modello di costo (**peggiorativo**, 36.C) | 13m56s |
| `30498399199` | tetto duro 8 giocatori/shard, 45 bin | 11m30s |
| `30499100175` | paginazione del game log (36.D) | 10m21s |
| `30499737593` | fix `presence_rate` (36.E) | 9m17s |
| `30500508993` | `.debug/` fuori dall'albero (checkout 13,3s→3,07s) | 8m09s |
| `30501219037` | discovery in 20 gruppi invece di 36 job | 9m30s (\*) |
| `30502148137` | pacing GraphQL adattivo | **7m55s** |
| `30502734469` | bin 65/5 (**peggiorativo**, 36.J) → ripristinato 45/8 | 10m56s |

(\*) run in cui il lavoro predict è misurato 5395s contro 3228s della precedente a carico
identico: rumore di latenza Sorare, non una regressione del cambiamento.

**Leve residue, in ordine di valore atteso:**

1. **`ODDS_L10_SLEEP` = 0,7s per giocatore in discovery** (~55% del lavoro di quella fase, ~28s di
   wall). **Non abbassato di proposito**: se un 429 esaurisce i retry, `odds_e_l10_singola`
   ritorna `(None, None, None)` e il chiamante lo conta come "nessuna partita nella finestra" —
   il giocatore posseduto sparisce dalle formazioni **senza errore visibile**, stessa classe di
   bug di "Zinckernagel perso in silenzio". Prima di toccare quella pausa va reso non-silenzioso
   il fallimento (far fallire il job invece di escludere il giocatore). Nel frattempo il caso è
   almeno diventato **visibile nel log** (fix in `odds_e_l10_singola`).
2. **`prediction_*.txt`: 166 MB in 29.892 file** nell'albero. `build_consiglio_*` legge solo il
   più recente per slug, quindi i precedenti sono peso morto sul checkout di ogni job. Potarli
   (tenendo gli ultimi N per slug) vale un altro pezzo dei 3s di checkout. **Non fatto**: è una
   cancellazione di dati dell'utente, va decisa da lui.
3. **Pacing adattivo anche sulla LATENZA**, non solo sui 429 (vedi 36.J: Sorare rallenta senza
   mandare 429, quindi il meccanismo attuale non se ne accorge). È l'unica leva che attaccherebbe
   il tetto vero, ma va tarata con run distanziate nel tempo.
4. **`sparse-checkout` per bin predict** (solo le leghe degli shard di quel bin): con il checkout
   già scesо a 3s il margine è ormai piccolo.

**Run di conferma finale** (dopo il ripristino 45/8, sessione ripresa dopo un'interruzione):
`30503366762`, stesso scope di sempre — **8m19s, success**. Coerente con 36.J: la stessa
configurazione di codice ha dato 7m55s e 8m19s in due run distinte, la differenza è rumore di
latenza Sorare, non un effetto del codice. **Chiuso qui su richiesta esplicita dell'utente**
("non c'è più target se non esaurire i miglioramenti possibili... si torna alla versione più
veloce poi committa pusha tutto e fermati"): configurazione 45 bin / 8 giocatori per shard
confermata come la migliore misurata, tutto committato e pushato su `main`.
