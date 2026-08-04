# Aggregato cross-GW — filone smart-money

GW incluse: 4 (football-21-24-jul-2026, football-24-28-jul-2026, football-28-31-jul-2026, football-31-jul-4-aug-2026).
Osservazioni totali: 4322.

## Pool complessivo

- Residuo medio (bias) = **+1.57**  (n 4322, MAE 15.4, corr +0.226).

## Per ruolo (pool)

| ruolo | n | bias | corr |
|---|--:|--:|--:|
| Midfielder | 1233 | +2.5 | 0.22 |
| Defender | 1120 | +2.7 | 0.1 |
| Forward | 1085 | +0.9 | 0.21 |
| Goalkeeper | 884 | -0.4 | 0.03 |

## Persistenza per manager (asse F — il test smart-money)

Bias per GW; 'segno stabile' = stesso verso su tutte le GW con n>=10. Un manager con bias positivo persistente è uno sharp vero.

| manager | football-21-24-jul-2026 | football-24-28-jul-2026 | football-28-31-jul-2026 | football-31-jul-4-aug-2026 | pool_n | pool_bias | segno |
|---|--:|--:|--:|--:|--:|--:|--:|
| satonio | +0.4(690) | +1.5(677) | +6.8(477) | +2.0(833) | 2677 | +2.3 | + |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | +0.2(227) | -1.3(298) | +3.4(122) | -0.5(306) | 953 | -0.1 | misto |
| bxl-spartak | +3.4(78) | +3.0(36) | +18.2(10) | -6.0(43) | 167 | +1.8 | misto |
| shirimimi | +5.2(41) | -0.2(40) | ·(5) | -0.5(49) | 135 | +1.7 | misto |
| milkyfresht | -4.0(30) | +3.7(38) | - | -5.8(62) | 130 | -2.6 | misto |
| fins49 | - | +2.9(34) | - | +0.7(83) | 117 | +1.3 | + |
| lairdinho | ·(5) | -1.6(20) | +6.3(17) | +1.4(28) | 70 | +1.1 | misto |
| eoghankelly | +2.2(10) | ·(5) | ·(5) | ·(9) | 29 | +9.2 | ? |
| spillo678 | ·(5) | - | +13.1(10) | ·(5) | 20 | +6.0 | ? |
| ninoshooter | - | -6.6(10) | ·(3) | ·(7) | 20 | -1.5 | ? |
| braddersfc | - | - | ·(4) | - | 4 | -6.4 | ? |

## Skill controllata per ambiente-GW (edge = residuo - media della GW)

Toglie l'effetto 'round alto/basso-scoring'. edge>0 e n grande = il manager sceglie meglio del pool di quella GW.

| manager | n | edge medio | se | edge/se |
|---|--:|--:|--:|--:|
| eoghankelly | 29 | +7.50 | 3.47 | +2.2 |
| spillo678 | 20 | +2.51 | 5.14 | +0.5 |
| bxl-spartak | 167 | +0.77 | 1.53 | +0.5 |
| shirimimi | 135 | +0.76 | 1.60 | +0.5 |
| fins49 | 117 | +0.57 | 1.57 | +0.4 |
| satonio | 2677 | +0.56 | 0.36 | +1.6 |
| lairdinho | 70 | -1.05 | 2.51 | -0.4 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 953 | -1.53 | 0.58 | -2.6 |
| ninoshooter | 20 | -3.14 | 4.25 | -0.7 |
| milkyfresht | 130 | -3.32 | 1.50 | -2.2 |

(controllo: edge medio complessivo -0.000, deve essere ~0 per costruzione.)

## Consenso (pool, per numero di manager nella stessa GW)

| n manager | n giocatori | bias |
|---|--:|--:|
| 1 | 768 | +1.3 |
| 2 | 381 | +1.3 |
| 3 | 145 | -0.1 |
| 4 | 45 | -1.0 |
| 5 | 11 | +1.4 |
| 6 | 1 | -40.5 |
| 7 | 2 | +37.0 |
