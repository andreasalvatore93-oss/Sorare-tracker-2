# Aggregato cross-GW — filone smart-money

GW incluse: 4 (football-21-24-jul-2026, football-24-28-jul-2026, football-28-31-jul-2026, football-31-jul-4-aug-2026).
Osservazioni totali: 1645.

## Pool complessivo

- Residuo medio (bias) = **+0.41**  (n 1645, MAE 14.9, corr +0.221).

## Per ruolo (pool)

| ruolo | n | bias | corr |
|---|--:|--:|--:|
| Defender | 470 | +0.4 | 0.07 |
| Midfielder | 425 | +2.1 | 0.26 |
| Forward | 413 | -0.2 | 0.19 |
| Goalkeeper | 337 | -0.9 | 0.02 |

## Persistenza per manager (asse F — il test smart-money)

Bias per GW; 'segno stabile' = stesso verso su tutte le GW con n>=10. Un manager con bias positivo persistente è uno sharp vero.

| manager | football-21-24-jul-2026 | football-24-28-jul-2026 | football-28-31-jul-2026 | football-31-jul-4-aug-2026 | pool_n | pool_bias | segno |
|---|--:|--:|--:|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | +0.2(227) | -1.3(298) | +3.5(122) | -0.5(306) | 953 | -0.1 | misto |
| bxl-spartak | +3.4(78) | +3.0(36) | +18.2(10) | -6.0(43) | 167 | +1.8 | misto |
| shirimimi | +5.2(41) | -0.3(40) | ·(5) | -0.5(49) | 135 | +1.7 | misto |
| milkyfresht | -4.0(30) | +3.7(38) | - | -5.8(62) | 130 | -2.6 | misto |
| fins49 | - | +2.9(34) | - | +0.7(83) | 117 | +1.3 | + |
| lairdinho | ·(5) | -1.6(20) | +6.2(17) | +1.3(28) | 70 | +1.0 | misto |
| eoghankelly | +2.2(10) | ·(5) | ·(5) | ·(9) | 29 | +9.2 | ? |
| spillo678 | ·(5) | - | +13.1(10) | ·(5) | 20 | +6.0 | ? |
| ninoshooter | - | -6.6(10) | ·(3) | ·(7) | 20 | -1.5 | ? |
| braddersfc | - | - | ·(4) | - | 4 | -6.4 | ? |

## Skill controllata per ambiente-GW (edge = residuo - media della GW)

Toglie l'effetto 'round alto/basso-scoring'. edge>0 e n grande = il manager sceglie meglio del pool di quella GW.

| manager | n | edge medio | se | edge/se |
|---|--:|--:|--:|--:|
| eoghankelly | 29 | +8.27 | 3.51 | +2.4 |
| spillo678 | 20 | +3.40 | 5.13 | +0.7 |
| fins49 | 117 | +2.06 | 1.57 | +1.3 |
| shirimimi | 135 | +1.56 | 1.59 | +1.0 |
| bxl-spartak | 167 | +1.29 | 1.52 | +0.9 |
| lairdinho | 70 | +0.14 | 2.52 | +0.1 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 953 | -0.63 | 0.58 | -1.1 |
| ninoshooter | 20 | -1.90 | 4.27 | -0.4 |
| milkyfresht | 130 | -2.32 | 1.49 | -1.6 |

(controllo: edge medio complessivo +0.000, deve essere ~0 per costruzione.)

## Consenso (pool, per numero di manager nella stessa GW)

| n manager | n giocatori | bias |
|---|--:|--:|
| 1 | 628 | +0.4 |
| 2 | 191 | +0.8 |
| 3 | 59 | +1.2 |
| 4 | 10 | +1.5 |
| 5 | 2 | -20.3 |
| 6 | 2 | +37.0 |
