# Indice copertura — archivio_ufficiale

Aggiornare a mano dopo ogni estrazione nuova (`estrai_archivio_manager.py`).
Non è una fonte di dati: solo un colpo d'occhio su cosa c'è, prima di
aprire le cartelle una per una.

| manager | partizione | GW estratte | arene Limited (division escluse) |
|---|---|---|---|
| crowss | pre_2026-08-07 (benchmark umano) | 24 | 220 |
| crowss | dal_2026-08-07 (modello G) | 1 | 27 |

**Copertura grade** (indice condiviso `analisi_manager/dati/storico_grade_*`,
dopo completamento mirato): 96,3% sull'aggregato crowss pre-G (10/08/2026).

**Ultimo run binari**: vedi `binario1_out.json` / `binario2_out.json` in
questa cartella per i numeri, o rilanciare
`analisi_manager/p23_binario1_mga.py` / `p24_binario2_ga.py` (girano da
soli su tutto quello che trovano in `archivio_ufficiale/manager_*/`).
