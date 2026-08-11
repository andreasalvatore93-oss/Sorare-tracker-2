# Indice copertura — archivio_ufficiale

Aggiornare a mano dopo ogni estrazione nuova (`estrai_archivio_manager.py`).
Non è una fonte di dati: solo un colpo d'occhio su cosa c'è, prima di
aprire le cartelle una per una.

Ultimo aggiornamento: 11/08/2026 notte — **filone grade CHIUSO**, vedi
`docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md` §8bis.

**Totale: 28 manager utili + crowss, 29 fonti, ~2.290 arene Limited
nell'archivio** (round1-3: 14 manager; round4: 11; round5 fermato a metà
su richiesta utente dopo il verdetto di Opus, 3 manager utili recuperati
comunque: malf99 54, so-finito 14, granata94 11 — grade non completato
mirato su questi tre, la copertura aggregata resta comunque ~91%).

**Scartati nel tempo (<10 arene su 22 GW, cartelle RIMOSSE dal repo)**:
gabittom, _clmt_, duddav, eugeneg, fk-bask, jackdaniels10, mago313,
mambri42, nasheuh, m_platini, samyhipiyo — 11 in totale. Interrotto a
metà e scartato: frejo (6 arene, mai committato).

**Slug NOT_FOUND (mai esistiti/rimossi da Sorare)**: titielboboh,
stevie_1dah, rossario, futbaba, 420todoeldia.

**Copertura grade**: ~91,6-91,7% delle carte nel pool aggregato.

## Esito finale (11/08/2026 notte) — non riaprire senza un'idea nuova

Il confronto diretto "G batte A in essenze" (binario1/binario2) non ha
mai raggiunto un campione sufficiente nonostante 4 round di estrazione
manager (n_discordanti 55→80→103→143, soglia stimata ~213 poi rivista a
~1.000): **estrazioni fermate, la strada "più manager" è chiusa**.

La domanda utile era un'altra — **il grade porta informazione a livello
di singola carta?** — risposta **SÌ**, chiusa con tre prove indipendenti:
placebo p=0,005, beta dentro-gruppo +0,555 (t=1,97), beta corretto per
l'errore di misura del metro ≈1,01 con IC95 [0,36 ; 1,67] che **contiene
il peso 1,0 già in produzione**. Nessuna modifica alla produzione.
Dettaglio: `docs/handoff/RISPOSTA_OPUS_SCALA_STORICA_2026-08-11.txt`.

**Bug corretto nello stesso filone**: `p23_binario1_mga.py` escludeva di
default il 19% delle formazioni (quelle con una carta a 0/DNP — proprio i
casi peggiori), gonfiando artificialmente "M entra sempre". Default
invertito (`ESCLUDI_DNP=1` per il vecchio comportamento, solo storia).

**Ultimo run binari** (28 manager utili + crowss, dati sopra):
- Binario1: 1.091 formazioni pulite, M +11.300 / A +12.150 / G +15.650,
  n_discordanti=143, delta G-A +3.500 (trim simmetrico +2.900).
- Binario2: A +112.739 (1.145 arene) / G +116.104 (1.095 arene),
  173 coppie manager-GW discordanti su 337, delta +3.365 (trim
  simmetrico +2.163).
- Test carta (`p26_test_carta_scala_storica.py`): vedi sopra.

Dettaglio in `binario1_out.json` / `binario2_out.json` /
`binario2_pool_rows.json` in questa cartella.

**Tema NUOVO aperto, non ancora iniziato**: la soglia d'ingresso arena
misurata in PUNTI e fuori campione (proposta di Opus, §5 punto 4 di
`RISPOSTA_OPUS_SCALA_STORICA_2026-08-11.txt`). Si apre solo se l'utente
decide di aprirlo — un tema alla volta.
