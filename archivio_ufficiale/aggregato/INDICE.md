# Indice copertura — archivio_ufficiale

Aggiornare a mano dopo ogni estrazione nuova (`estrai_archivio_manager.py`).
Non è una fonte di dati: solo un colpo d'occhio su cosa c'è, prima di
aprire le cartelle una per una.

| manager | partizione | GW estratte | arene Limited (division escluse) |
|---|---|---|---|
| crowss | pre_2026-08-07 (benchmark umano) | 24 | 220 |
| crowss | dal_2026-08-07 (modello G) | 1 | 27 |
| tigermila11 | (nessuna, non è crowss) | 19/22 con dati | 120 |
| tsubasa_451 | (nessuna, non è crowss) | 21/22 con dati | 509 |
| ch4 | (nessuna, non è crowss) | 7/22 con dati | 63 |

`gabittom` estratto e SCARTATO (10/08/2026): solo 2 arene su 22 GW,
manager quasi inattivo in quella finestra, cartella rimossa.

**Copertura grade** (indice condiviso `analisi_manager/dati/storico_grade_*`,
dopo completamento mirato sui 4 manager nuovi, 18208 righe totali
nell'indice): ~91% delle carte nel pool aggregato (91,0% binario1,
90,9% binario2, 10/08/2026 sera). Di queste, solo il 54,0% produce un
aggiustamento G effettivamente non-zero (serve ≥2 carte con grade nello
stesso gruppo lega+ruolo per quella GW — altrimenti lo z-score resta
inerte), invariato rispetto al ~57% misurato sul solo crowss.

**Ultimo run binari**: vedi `binario1_out.json` / `binario2_out.json` in
questa cartella per i numeri, o rilanciare
`analisi_manager/p23_binario1_mga.py` / `p24_binario2_ga.py` (girano da
soli su tutto quello che trovano in `archivio_ufficiale/manager_*/`).
