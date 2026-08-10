# Indice copertura — archivio_ufficiale

Aggiornare a mano dopo ogni estrazione nuova (`estrai_archivio_manager.py`).
Non è una fonte di dati: solo un colpo d'occhio su cosa c'è, prima di
aprire le cartelle una per una.

Ultimo aggiornamento: 11/08/2026 (dopo round 2+3, prima che il round 4
finisca — vedi nota in fondo).

| manager | GW con dati | arene Limited |
|---|---|---|
| crowss | 18/25 (17 pre-G su 24 GW + 1 dal 7/8) | 247 |
| tsubasa_451 | 21/22 | 509 |
| golden_goal-699e9a95-...(dd0a) | 17/22 | 212 |
| tigermila11 | 19/22 | 120 |
| yippeekiyay_trading | 15/22 | 106 |
| skepticalone | 14/22 | 50 |
| shadowblack21 | 13/22 | 96 |
| raykocar | 13/22 | 25 |
| tekato-dan | 12/22 | 80 |
| pnd999 | 10/22 | 27 |
| peppe_g | 10/22 | 25 |
| alfo88 | 10/22 | 20 |
| gigigonzalez | 9/22 | 28 |
| ch4 | 7/22 | 63 |
| kowalskiuk | 4/22 | 34 |

**Totale: 15 manager utili (14 + crowss), 1.661 arene Limited nell'archivio.**

**Scartati (<10 arene su 22 GW, cartelle RIMOSSE dal repo)**: gabittom,
_clmt_, duddav, eugeneg, fk-bask, jackdaniels10, mago313, mambri42,
nasheuh — 9 in totale finora.

**Slug NOT_FOUND (mai esistiti/rimossi da Sorare)**: titielboboh,
stevie_1dah, rossario, futbaba, 420todoeldia.

**Copertura grade** (indice condiviso `analisi_manager/dati/storico_grade_*`,
dopo completamento su 1.504 slug carta dei 14 manager nuovi, ~32.000 righe
totali nell'indice): **91,6% binario1 / 91,7% binario2** delle carte nel
pool aggregato (11/08/2026 notte).

**Ultimo run binari (14 manager + crowss, 578 formazioni binario1 / 189 GW
binario2)**:
- Binario1: M +35.450, A +18.900, G +20.550 — n_discordanti G-vs-A = **80**
  (soglia Opus per un segnale non più spiegabile dal caso: ~213). Delta
  G-A +1650, ma **-1350 togliendo le 3 decisioni pro-G più pesanti**: il
  segno si ribalta, segnale non ancora robusto.
- Binario2 (pool libero): A +81.306, G +82.641 — split per manager 7/14
  pro-G vs 7/14 pro-A, nessuna direzione condivisa.

Dettaglio in `binario1_out.json` / `binario2_out.json` in questa cartella,
o rilanciare `analisi_manager/p23_binario1_mga.py` /
`analisi_manager/p24_binario2_ga.py` (girano da soli su tutto quello che
trovano in `archivio_ufficiale/manager_*/`).

**IN CORSO (11/08/2026, non ancora consolidato)**: round 4, 15 manager
nuovi (lorenzocodega, rob1502, ghosthup, fverb1-..., sweggaausbrazil,
melvinfrithzell10, lucio_spallettone, malvino, freecer, fred-eric-...,
meddok, maltazars, thetongfu, karew, elkenodescansa), brief in
`docs/handoff/BRIEF_HAIKU_ESTRAZIONE_15MANAGER_ROUND4_2026-08-11.txt`.
Numeri sopra NON lo includono ancora — aggiornare questa tabella e
rilanciare grade+binari a estrazione finita.
