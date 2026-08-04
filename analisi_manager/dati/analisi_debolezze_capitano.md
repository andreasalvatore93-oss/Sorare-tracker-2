# Analisi pooled 4 GW — dove il modello e' piu' debole + capitano

Sessione 05/08/2026, ore 01:30 (Roma, CEST). Pool: 4 GW (21 lug - 4 ago 2026),
1645 pick grezzi / 892 giocatore-partita unici, 354 formazioni.
Script: temporanei (non versionati), rigenerabili dai dati in analisi_manager/dati/.

## AVVERTENZA METODOLOGICA — le sigma dei report per-GW sono GONFIATE

Nel pool lo stesso giocatore-partita compare piu' volte, una per ogni manager che
lo schiera (1645 righe = 892 giocatori-partita unici). Le osservazioni NON sono
indipendenti: n gonfiata, se sottostimata, sigma sovrastimate.
Caso concreto: "portogallo +19.8 pt a 6.4 sigma" era Vangelis Pavlidis (100 pt)
contato 8 volte + Lenglet 3 volte. De-duplicando, il Portogallo esce del tutto
dalle soglie di n. Stessa sorte per quasi tutte le anomalie per-lega.
=> Leggere sempre la versione de-duplicata prima di credere a un effetto.

## VERDETTO IN TRE RIGHE

1. De-duplicando, NESSUN effetto supera 2.1 sigma: il modello non ha una
   debolezza sistematica identificabile con queste feature. Bias pool +0.60 (1.0 sigma).
2. La debolezza vera e' a livello FORMAZIONE, non giocatore: corr(atteso_sum, rank
   in arena) = -0.02, cioe' ~ZERO. Vedi sezione dedicata.
3. Capitano: CONFERMATO CHIUSO. Il nostro pick_captain pareggia con gli umani
   (+0.19 pt/formazione, +0.7 sigma) e nessuna policy alternativa lo batte.


## DE-DUPLICATO: 1 riga per (gw, giocatore) — il test onesto

Nel pool lo stesso giocatore-partita compare piu volte (piu manager lo schierano):
le n sono gonfiate e le sigma sovrastimate. Qui una riga per giocatore-partita.

Pool unico: n=892 bias=+0.60 se=0.59 (+1.0 sigma)
Pool grezzo (con duplicati): n=1645 bias=+0.41 se=0.45 (+0.9 sigma)

### Casa/trasferta (de-duplicato)

| gruppo | n | bias | se | sigma |
|---|--:|--:|--:|--:|
| trasferta | 423 | +1.20 | 0.91 | +1.3 |
| casa | 419 | +0.26 | 0.82 | +0.3 |
| n/d | 50 | -1.75 | 2.35 | -0.7 |

### Ruolo (de-duplicato)

| gruppo | n | bias | se | sigma |
|---|--:|--:|--:|--:|
| Defender | 293 | +1.26 | 0.99 | +1.3 |
| Midfielder | 231 | +2.43 | 1.18 | +2.1 |
| Forward | 219 | -1.34 | 1.16 | -1.2 |
| Goalkeeper | 149 | -0.70 | 1.57 | -0.4 |

### Lega (de-duplicato)

| gruppo | n | bias | se | sigma |
|---|--:|--:|--:|--:|
| mls | 341 | -0.16 | 0.95 | -0.2 |
| kleague | 113 | +0.38 | 1.58 | +0.2 |
| argentina | 58 | -2.36 | 2.32 | -1.0 |
| danimarca | 55 | +3.21 | 2.45 | +1.3 |
| messico | 45 | -3.17 | 2.09 | -1.5 |
| brasile | 40 | -0.96 | 2.44 | -0.4 |
| croazia | 30 | +0.59 | 3.30 | +0.2 |
| cina | 26 | -3.27 | 3.83 | -0.9 |
| scozia | 25 | +5.45 | 3.88 | +1.4 |
| austria | 21 | +4.66 | 3.93 | +1.2 |

### Profondita storico (de-dup)

| gruppo | n | bias | se | sigma |
|---|--:|--:|--:|--:|
| 20-29 | 514 | +0.34 | 0.75 | +0.5 |
| 10-19 | 235 | -0.29 | 1.17 | -0.3 |
| >=30 | 72 | +1.07 | 2.38 | +0.4 |
| <10 | 71 | +4.88 | 2.34 | +2.1 |


## CAPITANO — pool 4 GW

Formazioni: 354
- Residuo dei capitani scelti: n=324 bias=+1.24 se=1.04 (+1.2 sigma)
- Residuo dei non-capitani:   n=1321 bias=+0.21 se=0.50 (+0.4 sigma)
- Formazioni complete valutabili: 247
- Loro capitano == nostro max-atteso: 95/247 (38%)
- Loro capitano rende sopra la media della formazione: 135/247 (55%)

### Punti extra dati dal capitano (+20% del suo punteggio reale), stessa formazione

| policy | punti extra medi |
|---|--:|
| peggiore possibile | 6.75 (se 0.11) |
| a caso (=media form.) | 10.57 (se 0.11) |
| LORO (scelta reale) | 11.10 (se 0.24) |
| NOSTRO pick_captain (max atteso) | 11.29 (se 0.26) |
| oracolo (senno di poi) | 15.12 (se 0.19) |

Delta NOSTRO - LORO = +0.19 pt/formazione (se 0.27, +0.7 sigma), n=247
Headroom oracolo - NOSTRO = +3.84 pt/formazione (tetto teorico del capitano)
Range totale policy (caso - peggiore) = +3.82 pt

### Che ruolo scelgono come capitano (e come rende)

| ruolo | n | quota | residuo | reale medio |
|---|--:|--:|--:|--:|
| Forward | 151 | 43% | -7.38 | 48.0 |
| Midfielder | 129 | 37% | +0.84 | 58.3 |
| Defender | 70 | 20% | -1.67 | 52.5 |

### Il nostro atteso-somma predice il piazzamento?

- n formazioni 354; corr(atteso_sum, rank) = +0.054 (serve NEGATIVA)
- corr(atteso_sum, punteggio formazione) = +0.091
- quintile BASSO atteso_sum: rank medio 5.47, punti 256.9 (n70)
- quintile ALTO  atteso_sum: rank medio 6.29, punti 265.3 (n70)

---
## Livello FORMAZIONE (5 carte, reali GREZZI senza capitano)

n=247
corr(atteso_sum, reale_sum_grezzo) = +0.182
corr(atteso_sum, punteggio_form Sorare)= +0.173
corr(atteso_sum, rank)                 = -0.020  (serve NEGATIVA)
corr(reale_sum_grezzo, rank)           = -0.829  (verifica di sanita: DEVE essere molto negativa)
corr(punteggio_form, rank)             = -0.816
std atteso_sum 13.1 vs std reale_sum 44.8 -> compressione 3.4x

Quintile BASSO atteso_sum: reale_sum 252.7, rank 5.22
Quintile ALTO  atteso_sum: reale_sum 272.1, rank 5.59
-> delta reale_sum quintile alto-basso = +19.4 pt su 5 carte


## CAPITANO: perche i Forward rendono peggio

| ruolo | n CAP | reale CAP | n NONcap | reale NONcap | delta |
|---|--:|--:|--:|--:|--:|
| Forward | 133 | 54.5 | 280 | 53.1 | +1.4 |
| Midfielder | 125 | 60.2 | 300 | 56.6 | +3.6 |
| Defender | 66 | 55.7 | 404 | 52.5 | +3.2 |

(se il delta e ~0 il ruolo non e penalizzato DA capitano: rende come sempre.
La differenza fra ruoli e il livello BASE del ruolo, non un errore di scelta.)

### Che ruolo sceglierebbe il NOSTRO pick_captain (max atteso)

| ruolo | n | quota | reale medio |
|---|--:|--:|--:|
| Midfielder | 128 | 52% | 58.9 |
| Defender | 60 | 24% | 49.0 |
| Forward | 56 | 23% | 58.9 |
| Goalkeeper | 3 | 1% | 53.4 |

### Policy capitano a confronto (punti extra = 0.20 x reale del capitano)

| policy | punti extra | delta vs NOSTRO | sigma |
|---|--:|--:|--:|
| max atteso fra MID | 11.45 | +0.17 | +0.7 |
| max atteso escl. GK | 11.29 | +0.00 | +0.0 |
| max atteso (NOSTRO) | 11.29 | +0.00 | +0.0 |
| max L10 | 11.02 | -0.27 | -1.1 |
| max atteso in casa | 11.01 | -0.27 | -1.2 |
| piu storico | 10.44 | -0.84 | -2.6 |

---

## LETTURA — cosa dicono davvero questi numeri

### 1. La debolezza principale: il salto giocatore -> formazione
A livello giocatore corr(atteso, reale) = +0.22. Sommando 5 carte la
correlazione NON sale (+0.18): dovrebbe salire, perche' mediando 5 rumori
indipendenti il rumore si riduce. Non sale perche' (a) le 5 carte condividono
l'ambiente-GW (round alto/basso-scoring), quindi il loro errore e' correlato,
e (b) lo spread di atteso_sum e' minuscolo: std 13.1 su 5 carte (2.6 a carta)
contro std 44.8 del realizzato = compressione 3.4x, la stessa gia' documentata
a livello di singolo giocatore.
Conseguenza operativa dura: corr(atteso_sum, rank) = -0.02. Il nostro
atteso-somma NON predice il piazzamento in arena. Non e' un bug della
classifica: corr(reale_sum, rank) = -0.83, la classifica funziona benissimo,
siamo noi a non anticiparla.
Il segnale pero' NON e' nullo: quintile alto vs basso di atteso_sum =
+19.4 pt reali su 5 carte. Stessa struttura gia' vista in §5 del riassunto
unificato: l'edge esiste negli ESITI (code, quintili) ed e' invisibile nella
correlazione media. Coerente, non nuovo.

### 2. Capitano: un falso positivo evitato
Prima lettura: i manager scelgono Forward come capitano nel 43% dei casi e i
FWD-capitano hanno residuo -7.4, il peggiore di tutti i ruoli => "sbagliano
ruolo". FALSO. Controllando col ruolo, i FWD capitani rendono +1.4 SOPRA i FWD
non-capitani (55 vs 53): non c'e' nessuna penalita' da capitano. Il -7.4 e'
semplicemente il livello base del ruolo Forward, che il nostro modello
sovrastima come gia' noto. Esattamente la trappola di §11 del riassunto
unificato ("un bias marginale forte non implica un buon criterio di scelta").
Il NOSTRO pick_captain sceglie MID nel 52% dei casi (loro 37%) e infatti
raccoglie leggermente di piu', ma la differenza non e' significativa.
Sei policy alternative testate: nessuna batte "max atteso"; "piu' storico"
la peggiora a -2.6 sigma. Il capitano vale comunque poco: fra la scelta
peggiore e quella a caso ballano 3.8 pt su formazione, e l'oracolo col senno
di poi ne guadagna solo altri 3.8. pick_captain resta da non toccare.

### 3. Segnali marginali da riguardare quando arrivano piu' GW
- Midfielder: bias +2.43 (2.1 sigma, n 231 unici). Li sottostimiamo.
- Storico < 10 partite: bias +4.88 (2.1 sigma, n 71). Sottostimiamo i
  giocatori con poco storico — coerente con uno shrinkage prior troppo forte
  su chi ha pochi dati. E' l'unica ipotesi azionabile emersa da questa analisi.
- Casa/trasferta: nel pool grezzo sembrava un effetto da 3 pt a 2.7 sigma;
  de-duplicando scende a +1.2 vs +0.3 (1.3 sigma). Non azionabile.
