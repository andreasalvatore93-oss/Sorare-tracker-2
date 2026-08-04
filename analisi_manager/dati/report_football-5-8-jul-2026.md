# Report analisi manager — GW football-5-8-jul-2026

Generato: 2026-08-04 23:12 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **37** su 3 manager attivi. Scarti: 8 non ha giocato (0).
- **Residuo medio (bias) = -3.33**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.153; MAE 14.5; dispersione previsto 4.2 vs reale 18.9 (4.5x compressione).
- Lift di selezione: atteso medio dei loro pick 51.0 vs slot medio 51.8 = **-0.8** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 12 | -7.9 | 17.9 | +0.28 |
| Midfielder | 9 | +0.9 | 9.0 | +0.13 |
| Forward | 9 | +3.3 | 17.5 | +0.14 |
| Goalkeeper | 7 | -9.3 | 11.8 | +0.11 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 23 | -0.4 | 13.7 | +0.06 |
| Cap 220 | 10 | -3.7 | 13.0 | +0.22 |
| Beginner | 4 | -19.1 | 22.4 | -0.30 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| kleague | 24 | -1.8 | 11.8 | +0.12 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 20 | -0.2 | 16.4 | -0.12 |
| 45-50 | 10 | -11.4 | 15.1 | -0.89 |
| 55-60 | 3 | -9.7 | 9.7 | +1.00 |
| <45 | 2 | +8.8 | 10.7 | - |
| >=60 | 2 | +3.0 | 3.0 | - |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 17 | -0.9 | 11.0 | +0.28 |
| 50-60 | 17 | -6.0 | 17.8 | +0.23 |
| <40 | 3 | -2.3 | 15.3 | -0.91 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 16 | +3.5 | 9.8 | +0.11 |
| True | 13 | -13.0 | 18.0 | +0.17 |
| None | 8 | -1.3 | 18.0 | +0.08 |

## Consenso

- A giocatore unico: n 30, bias -3.90, corr +0.124.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 29 | -2.3 | 13.1 | +0.19 |
| 2 manager | 1 | -49.0 | 49.0 | - |

## B. Capitano

- Formazioni con capitano valutabile: 9.
- Il loro capitano è la carta a **max atteso** della formazione: 5/9 (56%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 5/9 (56%).
- Residuo capitani -2.12 (n 8) vs non-capitani -3.66 (n 29).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 9.
- Corr(atteso_somma, rank reale) = -0.119 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.452.

## Correlazioni & code

- corr(residuo, atteso) = -0.069 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.083.
- corr(residuo, profondità storico) = -0.285 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 8.1% | flop (<25) 13.5%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| fins49 | 18 | -4.7 | 17.0 | +0.14 |
| eoghankelly | 15 | +2.5 | 9.2 | +0.03 |
| ninoshooter | 4 | -19.1 | 22.4 | -0.30 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| YAGO | Forward | kleague | 52 | 79 | +26 |
| Malik Tillman | Forward | germania | 52 | 76 | +24 |
| Malik Tillman | Forward | germania | 52 | 76 | +24 |
| Ahn Hyeok-Ju | Midfielder | kleague | 42 | 61 | +19 |
| Marko Tolić | Midfielder | cina | 50 | 69 | +19 |
| Dan Ndoye | Forward | inghilterra | 46 | 64 | +18 |
| Kim Young Gwon | Defender | kleague | 51 | 67 | +16 |
| Kim Young Gwon | Defender | kleague | 51 | 67 | +16 |
| Jung Seung-Hyun | Defender | kleague | 50 | 64 | +14 |
| Choi Jun | Defender | kleague | 51 | 58 | +7 |
| Lee Gyu-Sung | Midfielder | kleague | 54 | 60 | +6 |
| Kim Jin-Su | Defender | kleague | 61 | 64 | +3 |
| Kim Jin-Su | Defender | kleague | 61 | 64 | +3 |
| Jo Hyeon-Woo | Goalkeeper | kleague | 50 | 53 | +3 |
| Jo Hyeon-Woo | Goalkeeper | kleague | 50 | 53 | +3 |

- Ruoli nella coda: {'Forward': 4, 'Midfielder': 3, 'Defender': 6, 'Goalkeeper': 2}
- Leghe nella coda: {'kleague': 11, 'germania': 2, 'cina': 1, 'inghilterra': 1}
