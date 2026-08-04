# Report analisi manager — GW football-31-jul-4-aug-2026

Generato: 2026-08-04 22:19 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **290** su 8 manager attivi. Scarti: 18 no atteso (storico/target), 12 non ha giocato (0).
- **Residuo medio (bias) = -1.35**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.229; MAE 15.9; dispersione previsto 4.7 vs reale 19.8 (4.2x compressione).
- Lift di selezione: atteso medio dei loro pick 51.8 vs slot medio 51.8 = **-0.0** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 89 | +0.2 | 17.2 | +0.03 |
| Midfielder | 81 | +2.1 | 14.7 | +0.42 |
| Forward | 61 | -4.1 | 14.3 | +0.12 |
| Goalkeeper | 59 | -5.7 | 17.0 | -0.12 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 148 | -1.1 | 16.2 | +0.07 |
| Cap 220 | 109 | -1.7 | 15.6 | +0.30 |
| Uncapped | 18 | +1.7 | 17.4 | +0.58 |
| Beginner | 15 | -5.4 | 12.9 | +0.04 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 132 | -2.8 | 15.3 | +0.24 |
| kleague | 34 | -1.9 | 15.6 | +0.20 |
| scozia | 23 | +7.6 | 14.2 | -0.37 |
| messico | 19 | -3.0 | 11.3 | +0.53 |
| argentina | 19 | -7.6 | 24.0 | -0.53 |
| danimarca | 18 | +5.5 | 16.5 | +0.34 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 113 | -1.9 | 14.7 | +0.01 |
| 45-50 | 90 | -1.3 | 15.1 | -0.32 |
| 55-60 | 59 | -3.1 | 18.8 | +0.05 |
| <45 | 19 | +0.8 | 11.6 | -0.23 |
| >=60 | 9 | +11.5 | 27.2 | +0.86 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 135 | -2.1 | 16.3 | -0.04 |
| 50-60 | 117 | -1.4 | 14.9 | +0.24 |
| <40 | 24 | -3.1 | 16.4 | +0.24 |
| 60-70 | 11 | +2.6 | 14.7 | +0.46 |
| >=70 | 3 | +32.2 | 32.2 | +1.00 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 157 | -2.7 | 17.1 | +0.31 |
| False | 123 | +0.7 | 14.4 | +0.16 |
| None | 10 | -5.5 | 14.4 | -0.33 |

## Consenso

- A giocatore unico: n 210, bias -0.00, corr +0.222.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 166 | +0.7 | 14.4 | +0.22 |
| 2 manager | 37 | -1.0 | 16.7 | +0.23 |
| 3 manager | 6 | -6.5 | 18.3 | +0.64 |
| 4 manager | 1 | -40.5 | 40.5 | - |

## B. Capitano

- Formazioni con capitano valutabile: 64.
- Il loro capitano è la carta a **max atteso** della formazione: 28/64 (44%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 38/64 (59%).
- Residuo capitani +0.38 (n 60) vs non-capitani -1.81 (n 230).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 62.
- Corr(atteso_somma, rank reale) = +0.098 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.020.

## Correlazioni & code

- corr(residuo, atteso) = -0.011 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.054.
- corr(residuo, profondità storico) = -0.088 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 11.0% | flop (<25) 4.8%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| fins49 | 83 | +0.7 | 13.6 | +0.14 |
| milkyfresht | 62 | -5.8 | 14.9 | +0.10 |
| shirimimi | 49 | -0.5 | 17.3 | +0.28 |
| bxl-spartak | 42 | -6.5 | 14.4 | +0.20 |
| lairdinho | 33 | +3.1 | 20.2 | +0.67 |
| eoghankelly | 9 | +11.5 | 16.7 | +0.02 |
| ninoshooter | 7 | +5.4 | 21.7 | -0.55 |
| spillo678 | 5 | -6.3 | 24.3 | -0.92 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Jonathan Sirois | Goalkeeper | mls | 47 | 98 | +51 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Lee Ju-Yong | Defender | kleague | 55 | 100 | +45 |
| Tobias Salquist | Defender | danimarca | 55 | 100 | +45 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Juan Brunetta | Midfielder | messico | 59 | 100 | +41 |
| Brandon Bye | Defender | mls | 48 | 87 | +39 |
| Mohamed Elyounoussi | Midfielder | danimarca | 55 | 94 | +39 |
| Ezequiel Unsain | Goalkeeper | argentina | 53 | 90 | +38 |
| Aaron Long | Defender | mls | 47 | 83 | +36 |
| Aaron Long | Defender | mls | 47 | 83 | +36 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |

- Ruoli nella coda: {'Midfielder': 5, 'Goalkeeper': 3, 'Defender': 7}
- Leghe nella coda: {'mls': 5, 'argentina': 2, 'kleague': 1, 'danimarca': 2, 'croazia': 2, 'messico': 1, 'austria': 2}
