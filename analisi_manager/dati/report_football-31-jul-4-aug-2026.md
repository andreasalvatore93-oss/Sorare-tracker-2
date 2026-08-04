# Report analisi manager — GW football-31-jul-4-aug-2026

Generato: 2026-08-05 00:55 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **592** su 9 manager attivi. Scarti: 37 non ha giocato (0), 11 no atteso (storico/target), 2 arena esclusa (arena_altro).
- **Residuo medio (bias) = -0.99**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.240; MAE 16.0; dispersione previsto 4.9 vs reale 20.0 (4.1x compressione).
- Lift di selezione: atteso medio dei loro pick 52.5 vs slot medio 51.8 = **+0.7** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 170 | -1.2 | 17.3 | -0.03 |
| Midfielder | 164 | +2.0 | 15.8 | +0.33 |
| Forward | 138 | -2.1 | 14.4 | +0.20 |
| Goalkeeper | 120 | -3.4 | 16.3 | +0.16 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Beginner | 194 | -0.3 | 15.8 | +0.25 |
| Cap 260 | 191 | -0.9 | 15.8 | +0.17 |
| Cap 220 | 109 | -1.7 | 15.6 | +0.30 |
| Elite | 79 | -1.9 | 16.8 | +0.11 |
| Uncapped | 19 | -0.8 | 18.9 | +0.54 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 259 | -1.6 | 15.2 | +0.33 |
| kleague | 53 | -0.6 | 13.9 | +0.26 |
| argentina | 48 | -8.6 | 23.1 | -0.42 |
| messico | 47 | -1.6 | 10.8 | +0.50 |
| scozia | 37 | +5.1 | 15.7 | -0.37 |
| croazia | 25 | +12.9 | 19.7 | +0.61 |
| danimarca | 24 | +6.0 | 17.4 | +0.26 |
| austria | 20 | +11.1 | 21.6 | +0.54 |
| cina | 19 | -9.8 | 13.3 | +0.42 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 240 | -0.9 | 15.4 | -0.02 |
| 45-50 | 159 | -1.9 | 15.2 | -0.28 |
| 55-60 | 127 | -1.8 | 18.7 | +0.07 |
| >=60 | 33 | +2.8 | 19.3 | +0.69 |
| <45 | 33 | +2.0 | 10.8 | +0.11 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 271 | -1.0 | 15.4 | +0.19 |
| 40-50 | 235 | -2.2 | 16.2 | +0.01 |
| 60-70 | 49 | +3.1 | 15.4 | +0.07 |
| <40 | 31 | -4.9 | 17.4 | +0.08 |
| >=70 | 6 | +31.3 | 31.3 | +0.74 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 297 | +1.2 | 15.3 | +0.19 |
| True | 279 | -3.2 | 16.9 | +0.34 |
| None | 16 | -4.5 | 13.5 | +0.04 |

## Consenso

- A giocatore unico: n 329, bias +0.67, corr +0.213.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 235 | +1.8 | 14.2 | +0.23 |
| 2 manager | 64 | -1.5 | 16.7 | +0.20 |
| 3 manager | 24 | -2.3 | 16.8 | +0.16 |
| 4 manager | 5 | -3.1 | 17.3 | +0.74 |
| 5 manager | 1 | -40.5 | 40.5 | - |

## B. Capitano

- Formazioni con capitano valutabile: 128.
- Il loro capitano è la carta a **max atteso** della formazione: 59/128 (46%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 63/128 (49%).
- Residuo capitani -1.12 (n 117) vs non-capitani -0.96 (n 475).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 128.
- Corr(atteso_somma, rank reale) = +0.094 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.040.

## Correlazioni & code

- corr(residuo, atteso) = -0.006 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.068.
- corr(residuo, profondità storico) = -0.076 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 12.2% | flop (<25) 4.9%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 306 | -0.5 | 16.2 | +0.24 |
| fins49 | 83 | +0.7 | 13.6 | +0.14 |
| milkyfresht | 62 | -5.8 | 14.9 | +0.10 |
| shirimimi | 49 | -0.5 | 17.3 | +0.28 |
| bxl-spartak | 43 | -6.0 | 14.4 | +0.20 |
| lairdinho | 28 | +1.3 | 20.3 | +0.70 |
| eoghankelly | 9 | +11.5 | 16.7 | +0.02 |
| ninoshooter | 7 | +5.4 | 21.7 | -0.55 |
| spillo678 | 5 | -6.3 | 24.3 | -0.92 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Jonathan Sirois | Goalkeeper | mls | 47 | 98 | +51 |
| Jonas Svensson | Defender | norvegia | 50 | 100 | +50 |
| Jonas Svensson | Defender | norvegia | 50 | 100 | +50 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Cameron Carter-Vickers | Defender | scozia | 52 | 100 | +48 |
| Lee Ju-Yong | Defender | kleague | 55 | 100 | +45 |
| Tobias Salquist | Defender | danimarca | 55 | 100 | +45 |
| Tobias Salquist | Defender | danimarca | 55 | 100 | +45 |
| Timo Werner | Forward | mls | 53 | 97 | +44 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |

- Ruoli nella coda: {'Midfielder': 6, 'Goalkeeper': 2, 'Defender': 6, 'Forward': 1}
- Leghe nella coda: {'mls': 4, 'norvegia': 2, 'argentina': 1, 'scozia': 1, 'kleague': 1, 'danimarca': 2, 'croazia': 4}
