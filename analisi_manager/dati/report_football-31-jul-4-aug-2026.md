# Report analisi manager — GW football-31-jul-4-aug-2026

Generato: 2026-08-04 22:52 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **1425** su 10 manager attivi. Scarti: 103 non ha giocato (0), 32 no atteso (storico/target), 2 arena esclusa (arena_altro).
- **Residuo medio (bias) = +0.73**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.315; MAE 16.5; dispersione previsto 5.2 vs reale 20.7 (4.0x compressione).
- Lift di selezione: atteso medio dei loro pick 53.7 vs slot medio 51.8 = **+1.9** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Midfielder | 417 | +2.1 | 15.4 | +0.37 |
| Defender | 376 | +1.7 | 17.2 | +0.18 |
| Forward | 349 | +0.1 | 15.9 | +0.28 |
| Goalkeeper | 283 | -1.9 | 17.8 | +0.13 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 865 | +0.9 | 16.6 | +0.26 |
| Beginner | 194 | -0.3 | 15.8 | +0.25 |
| Elite | 154 | +2.0 | 17.4 | +0.40 |
| Cap 220 | 109 | -1.7 | 15.6 | +0.30 |
| Uncapped | 103 | +2.2 | 17.0 | +0.41 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 625 | +0.7 | 15.2 | +0.49 |
| kleague | 140 | -4.8 | 16.5 | -0.03 |
| scozia | 98 | +3.5 | 17.5 | +0.18 |
| danimarca | 90 | +4.0 | 16.6 | +0.16 |
| argentina | 89 | -5.0 | 22.0 | -0.34 |
| austria | 73 | +13.4 | 22.1 | +0.58 |
| messico | 67 | +2.2 | 13.6 | +0.54 |
| cina | 58 | -6.2 | 13.7 | +0.39 |
| croazia | 58 | +12.7 | 17.5 | +0.25 |
| svizzera | 43 | +0.2 | 17.6 | -0.06 |
| norvegia | 22 | -0.4 | 18.2 | +0.14 |
| cile | 18 | -14.2 | 14.2 | +0.45 |
| russia | 18 | -1.7 | 11.3 | +0.48 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 559 | -0.3 | 15.9 | +0.04 |
| 55-60 | 354 | +0.6 | 17.1 | +0.22 |
| 45-50 | 306 | -0.4 | 16.7 | -0.18 |
| >=60 | 163 | +6.1 | 18.3 | +0.31 |
| <45 | 43 | +3.5 | 11.5 | -0.06 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 638 | -0.5 | 15.7 | +0.25 |
| 40-50 | 492 | +0.7 | 17.2 | +0.16 |
| 60-70 | 218 | +3.1 | 15.8 | +0.08 |
| <40 | 53 | -6.0 | 17.5 | -0.16 |
| >=70 | 24 | +27.1 | 27.1 | +0.54 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 824 | +0.5 | 17.1 | +0.34 |
| False | 522 | +1.2 | 15.6 | +0.30 |
| None | 79 | -0.2 | 15.7 | +0.21 |

## Consenso

- A giocatore unico: n 492, bias +1.75, corr +0.235.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 281 | +2.3 | 15.4 | +0.25 |
| 2 manager | 137 | +4.2 | 16.4 | +0.21 |
| 3 manager | 51 | -3.0 | 15.7 | +0.21 |
| 4 manager | 17 | -8.9 | 16.2 | +0.20 |
| 5 manager | 5 | -3.1 | 17.3 | +0.74 |
| 6 manager | 1 | -40.5 | 40.5 | - |

## B. Capitano

- Formazioni con capitano valutabile: 312.
- Il loro capitano è la carta a **max atteso** della formazione: 163/312 (52%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 173/312 (55%).
- Residuo capitani +1.19 (n 294) vs non-capitani +0.61 (n 1131).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 311.
- Corr(atteso_somma, rank reale) = -0.029 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.134.

## Correlazioni & code

- corr(residuo, atteso) = +0.068 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.052.
- corr(residuo, profondità storico) = -0.042 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 16.6% | flop (<25) 3.6%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| satonio | 833 | +2.0 | 16.9 | +0.34 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 306 | -0.5 | 16.2 | +0.24 |
| fins49 | 83 | +0.7 | 13.6 | +0.13 |
| milkyfresht | 62 | -5.8 | 14.9 | +0.10 |
| shirimimi | 49 | -0.5 | 17.3 | +0.28 |
| bxl-spartak | 43 | -6.0 | 14.5 | +0.19 |
| lairdinho | 28 | +1.4 | 20.3 | +0.71 |
| eoghankelly | 9 | +11.4 | 16.7 | +0.04 |
| ninoshooter | 7 | +5.4 | 21.7 | -0.55 |
| spillo678 | 5 | -6.3 | 24.3 | -0.92 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Jonathan Sirois | Goalkeeper | mls | 47 | 98 | +51 |
| Jonathan Sirois | Goalkeeper | mls | 47 | 98 | +51 |
| Jonas Svensson | Defender | norvegia | 50 | 100 | +50 |
| Jonas Svensson | Defender | norvegia | 50 | 100 | +50 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Cameron Carter-Vickers | Defender | scozia | 52 | 100 | +48 |
| Martin Moormann | Defender | scozia | 49 | 96 | +47 |
| Samuel Essende | Forward | svizzera | 53 | 100 | +47 |
| Samuel Essende | Forward | svizzera | 53 | 100 | +47 |
| Luis Quiñones | Forward | colombia | 54 | 100 | +46 |

- Ruoli nella coda: {'Midfielder': 2, 'Goalkeeper': 6, 'Defender': 4, 'Forward': 3}
- Leghe nella coda: {'mls': 4, 'norvegia': 2, 'argentina': 4, 'scozia': 2, 'svizzera': 2, 'colombia': 1}
