# Report analisi manager — GW football-1-4-jul-2026

Generato: 2026-08-04 23:13 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **49** su 2 manager attivi. Scarti: 1 no atteso (storico/target).
- **Residuo medio (bias) = -5.99**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.305; MAE 14.7; dispersione previsto 5.9 vs reale 17.1 (2.9x compressione).
- Lift di selezione: atteso medio dei loro pick 54.9 vs slot medio 51.8 = **+3.1** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Forward | 16 | +0.5 | 13.8 | +0.53 |
| Midfielder | 14 | -11.3 | 16.5 | -0.01 |
| Defender | 10 | -8.9 | 11.8 | +0.41 |
| Goalkeeper | 9 | -6.0 | 16.7 | -0.13 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Uncapped | 34 | -7.1 | 15.7 | +0.36 |
| Cap 260 | 10 | -5.2 | 13.9 | +0.17 |
| Cap 220 | 5 | +0.0 | 9.7 | +0.36 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| inghilterra | 18 | -8.3 | 12.2 | +0.56 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 16 | -7.6 | 15.2 | -0.27 |
| 55-60 | 12 | -1.4 | 12.4 | +0.28 |
| >=60 | 10 | -9.8 | 17.4 | +0.17 |
| 45-50 | 9 | -5.1 | 15.8 | +0.28 |
| <45 | 2 | -6.0 | 6.0 | - |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 60-70 | 20 | -8.3 | 17.5 | +0.36 |
| 50-60 | 14 | -8.5 | 12.6 | +0.68 |
| 40-50 | 13 | +0.8 | 13.4 | +0.35 |
| <40 | 1 | -6.2 | 6.2 | - |
| >=70 | 1 | -13.5 | 13.5 | - |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| None | 25 | -1.5 | 10.9 | +0.69 |
| True | 18 | -8.4 | 18.3 | -0.07 |
| False | 6 | -17.5 | 19.8 | +0.51 |

## Consenso

- A giocatore unico: n 39, bias -4.89, corr +0.344.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 38 | -5.7 | 13.6 | +0.40 |
| 2 manager | 1 | +24.2 | 24.2 | - |

## B. Capitano

- Formazioni con capitano valutabile: 10.
- Il loro capitano è la carta a **max atteso** della formazione: 4/10 (40%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 4/10 (40%).
- Residuo capitani -10.84 (n 10) vs non-capitani -4.75 (n 39).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 10.
- Corr(atteso_somma, rank reale) = +0.632 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = -0.393.

## Correlazioni & code

- corr(residuo, atteso) = -0.040 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.165.
- corr(residuo, profondità storico) = +0.041 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 8.2% | flop (<25) 4.1%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 44 | -6.7 | 15.3 | +0.33 |
| fins49 | 5 | +0.0 | 9.7 | +0.36 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Davidson | Forward | cina | 59 | 94 | +35 |
| Malik Tillman | Midfielder | germania | 53 | 81 | +28 |
| Matt Freese | Goalkeeper | mls | 48 | 72 | +24 |
| Matt Freese | Goalkeeper | mls | 48 | 72 | +24 |
| Noni Madueke | Forward | inghilterra | 51 | 67 | +15 |
| Harry Kane | Forward | germania | 64 | 78 | +14 |
| Harry Kane | Forward | germania | 64 | 78 | +14 |
| Bradley Barcola | Forward | francia | 52 | 66 | +14 |
| Rúben Dias | Defender | inghilterra | 58 | 67 | +10 |
| Nicolas Pépé | Forward | spagna | 62 | 71 | +9 |
| Aurélien Tchouaméni | Midfielder | spagna | 58 | 65 | +7 |
| Bruno Nazário | Forward | kleague | 59 | 66 | +7 |
| Erling Haaland | Forward | inghilterra | 57 | 63 | +5 |
| William Saliba | Defender | inghilterra | 53 | 57 | +3 |
| Declan Rice | Midfielder | inghilterra | 58 | 60 | +2 |

- Ruoli nella coda: {'Forward': 8, 'Midfielder': 3, 'Goalkeeper': 2, 'Defender': 2}
- Leghe nella coda: {'cina': 1, 'germania': 3, 'mls': 2, 'inghilterra': 5, 'francia': 1, 'spagna': 2, 'kleague': 1}
