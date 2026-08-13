"""
build_formazione_finale.py

Fusione finale: legge l'ultimo consiglio_<timestamp>.txt gia' prodotto da
ciascuno dei 4 ruoli (mls_fwd_all/, mls_mid_all/, mls_def_all/, mls_gk_all/,
gia' generati dai rispettivi workflow di produzione discover->predict->merge)
e ne ricava fino a N formazioni ottimali per TRE tipi di competizione Sorare
diversi (26/07, seconda sessione, richiesta esplicita dell'utente):

- **IN SEASON** (quella storica, gia' in produzione): 1 GK, 1 DEF, 1 MID,
  1 FWD, 1 EXTRA (DEF/MID/FWD) — max 1 carta CLASSIC per formazione.
- **ARENA**: stessa struttura a 5 slot delle In Season, ma SENZA vincolo
  classic (possono essere tutte classic, non obbligatorio ma possibile).
  Supporta un tuning opzionale: cap sulla L10 combinata dei 5 giocatori
  (vedi ARENA_L10_CAP sotto).
- **ALL STARS**: 7 giocatori, struttura CONFERMATA dall'utente (26/07):
  1 GK, 2 DEF, 2 MID, 1 FWD, 1 EXTRA (DEF/MID/FWD) — nessun vincolo classic.

Nessuna chiamata GraphQL: puramente locale sui file gia' committati, quindi
istantaneo. Va rilanciato dopo ogni aggiornamento dei consigli di ruolo per
restare aggiornato (i file consiglio_*.txt piu' recenti per cartella sono
sempre quelli usati).

REGOLA "MAX 1 CLASSIC PER FORMAZIONE" (SOLO In Season, 25/07):
Le discovery di ruolo scansionano SIA carte IN_SEASON che CLASSIC, e
player_card_counts.json riporta le copie possedute separate per tipo
({'in_season': n, 'classic': m, 'l10': x}). LA SCELTA DEL GIOCATORE PER OGNI
SLOT E' GUIDATA SOLO DALLO SCORE ATTESO, MAI DAL TIPO DI CARTA: si scorre la
classifica del ruolo (gia' ordinata per score decrescente) e si prende il
primo giocatore disponibile, sia la sua carta migliore IN_SEASON o CLASSIC —
un giocatore col punteggio piu' alto viene scelto anche se posseduto SOLO in
classic. Il tipo di carta entra in gioco unicamente per decidere QUALE copia
dello stesso giocatore consumare: si consuma prima la copia IN_SEASON
(irrilevante per lo score, ma preserva l'eventuale slot CLASSIC per un altro
giocatore che ne ha davvero bisogno). Per Arena/All Stars questo vincolo non
esiste: qualunque copia disponibile (in_season o classic) viene consumata
liberamente, sempre iniziando da in_season per coerenza.

PRIORITA' TRA TIPI (26/07, richiesta esplicita dell'utente):
I 3 tipi condividono lo STESSO pool di giocatori posseduti (CardPool), quindi
generarli in ordine di priorita' IN SEASON -> ARENA -> ALL STARS fa si' che,
se il pool si esaurisce, siano naturalmente le formazioni meno prioritarie
(prima All Stars, poi Arena) a non essere completate — mai le In Season.
Ogni tipo puo' essere messo a 0 per disattivarlo del tutto. Il totale
richiesto (NUM_TOTALE_FORMAZIONI) deve combaciare ESATTAMENTE con la somma
dei 3 sotto-totali, altrimenti lo script si ferma subito (fail-fast, non
tronca silenziosamente).

TUNING ARENA_L10_CAP (26/07, richiesta esplicita dell'utente):
Se impostato (env ARENA_L10_CAP, es. "260"), le formazioni Arena vengono
generate rispettando un tetto sulla somma delle L10 (media ultime 10 partite
GIOCATE, LAST_TEN_PLAYED_SO5_AVERAGE_SCORE) dei 5 giocatori schierati -- non
solo il punteggio atteso piu' alto in assoluto, ma il migliore CHE rispetta
il tetto. Implementato come euristica greedy con budget residuo (non un
knapsack esatto): ad ogni slot si sceglie il miglior candidato la cui L10
(0 se mancante, permissivo) non fa sforare il budget rimasto; se nessun
candidato rispetta il budget, si prende quello con L10 piu' bassa disponibile
e la formazione viene segnalata come "budget L10 non rispettato" in output
(limite noto, non blocca la generazione). L10 mancante non esclude MAI un
giocatore (stesso principio di sicurezza degli altri filtri del progetto).

LOGICA MULTI-FORMAZIONE PER TIPO:
Un giocatore usato in una lineup (di qualunque tipo) NON puo' essere riusato
in una lineup successiva, A MENO CHE non si possiedano piu' copie della sua
carta (ogni copia, in_season o classic, e' un utilizzo possibile in una
lineup diversa, anche di tipo diverso). Se un ruolo esaurisce i candidati
disponibili prima di raggiungere il numero richiesto PER QUEL TIPO, la
generazione di quel tipo si ferma li' e lo segnala, ma si prosegue comunque
con il tipo successivo in ordine di priorita' (il pool residuo potrebbe
ancora bastare, essendo strutture/vincoli diversi).

Se player_card_counts.json non esiste ancora per un ruolo, si assume 1 copia
IN_SEASON di default (0 classic, L10 sconosciuta) per ogni giocatore di quel
ruolo non presente nel file.
"""
import os
import re
import sys
import glob
import html
import json
import math
import datetime

ROLES = {
    'GK': 'formazione_mls/output/mls_gk_all',
    'DEF': 'formazione_mls/output/mls_def_all',
    'MID': 'formazione_mls/output/mls_mid_all',
    'FWD': 'formazione_mls/output/mls_fwd_all',
}

DISCOVERY_DIRS = {
    'GK': 'formazione_mls/output/mls_gk_discovery',
    'DEF': 'formazione_mls/output/mls_def_discovery',
    'MID': 'formazione_mls/output/mls_mid_discovery',
    'FWD': 'formazione_mls/output/mls_fwd_discovery',
}

OUTPUT_DIR = 'formazione_mls/output'

CONSIGLIO_LINE_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')
# NUOVO (26/07, tema correlazione GK-DEF): riga "SQUADRA: x | AVVERSARIO: y"
# scritta subito dopo la riga consiglio da build_consiglio_<ruolo>.py.
TEAM_RE = re.compile(r'^SQUADRA:\s+(\S+)\s+\|\s+AVVERSARIO:\s+(\S+)\s*$')
# NUOVO (29/07, richiesta esplicita utente): fattore forza avversario (SOLO
# diagnostico, non entra in score_atteso -- vedi test_<ruolo>.py) mostrato
# nel report accanto a squadra/avversario, per ogni giocatore schierato ED
# escluso.
OPP_FACTOR_RE = re.compile(r'^AVV_FACTOR:\s+([\d.]+)\s*$')
# NUOVO (27/07): calcio d'inizio della partita target, scritto da
# build_consiglio_<ruolo>.py. Serve a scartare chi NON gioca nella giornata per
# cui si schiera (partita gia' giocata o fra giorni).
KICKOFF_RE = re.compile(r'^KICKOFF:\s+(\S+)\s*$')
# NUOVO (27/07, sezione 27.C del RIASSUNTO): score di ordinamento senza
# shrinkage, scritto da build_consiglio_<ruolo>.py. Serve SOLO a ordinare i
# pool; i punti mostrati/sommati restano 'atteso'. Riga opzionale: sui
# consigli generati prima si continua a ordinare per 'atteso'.
ORDINAMENTO_RE = re.compile(r'^ORDINAMENTO:\s+(-?[\d.]+)\s*$')
# NUOVO (12/08/2026, richiesta esplicita utente): riga "AMBIGUO: si" scritta
# da build_consiglio_<ruolo>.py quando il predict aveva trovato due partite
# future con odds pubblicate insieme (caso Freese, 10/08 --
# _prossima_partita_vera in test_gk.py e affini). Prima il badge esisteva
# solo in scouting_gw.py (che lo legge direttamente dai prediction_*.txt);
# qui arriva via il consiglio aggregato, quindi vale anche per il
# generatore. Riga opzionale: assente = 'ambiguo' resta False, nessuna
# regressione sui consigli vecchi.
AMBIGUO_RE = re.compile(r'^AMBIGUO:\s*si\s*$')

DEFAULT_NUM_FORMAZIONI = 1

# --- Strutture dei 3 tipi di formazione (26/07, seconda sessione) ----------
# 'role_slots': un elemento per slot obbligatorio (ripetuto se servono piu'
# giocatori dello stesso ruolo, es. 2x DEF in All Stars).
# 'extra_roles': ruoli ammessi per lo slot EXTRA finale (stesso per tutti e 3).
# 'max_classic': None = nessun vincolo, 1 = max 1 carta classic per formazione.
FORMATION_SHAPES = {
    'IN_SEASON': {
        'label': 'In Season',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': 1,
    },
    # 3 varianti Arena (26/07, richiesta esplicita): stessa struttura a 5
    # slot, cambia solo il cap FISSO sulla L10 combinata -- sono modalita'
    # Sorare distinte, generabili tutte nello stesso run. Priorita' interna
    # tra le tre: cap260 -> cap220 -> uncapped (vedi loop in main()).
    'ARENA_260': {
        'label': 'Arena (cap 260)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ARENA_220': {
        'label': 'Arena (cap 220)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ARENA_UNCAPPED': {
        'label': 'Arena (uncapped)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ALLSTARS': {
        'label': 'All Stars',
        'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
}

# Sinergia/anti-sinergia GK vs giocatori di movimento (26/07, tema
# correlazione): se il portiere di Squadra A gioca contro Squadra B, un gol
# subito dalla Squadra B gli toglie il bonus clean sheet -- quindi schierare
# insieme un MID/FWD di Squadra B e' fortemente scoraggiato (l'attaccante
# potrebbe comunque prendere un buon voto, ma e' una combinazione meno
# sensata quando ci sono molte alternative). Per i difensori vale l'opposto,
# piu' debole: schierare GK+DEF della STESSA squadra e' incoraggiato ma non
# obbligatorio (uno 0-0 capita, non e' vietato l'avversario). Implementato
# come riordino dei candidati (penalita'/bonus sul punteggio SOLO per
# l'ordine di scelta, il punteggio REALE mostrato in output resta quello
# originale) -- MAI un'esclusione assoluta, sempre "ultima risorsa" se non
# ci sono alternative valide (richiesta esplicita dell'utente).
ANTI_SYNERGY_PENALTY = 10_000  # abbastanza grande da finire sempre in fondo alla classifica di scelta
POSITIVE_SYNERGY_BONUS = 3  # piccolo nudge, non ribalta differenze di punteggio importanti
# Quanto punteggio atteso conviene sacrificare per accoppiare GK e DEF della
# stessa squadra.
#
# RIMISURATO il 02/08 su 69.151 coppie previsione/realizzato (era 5, stimato su
# 4 formazioni di una sola giornata). La catena e' questa:
#   - la correlazione degli ERRORI fra portiere e difensore e' +0.297, la piu'
#     alta di tutte le coppie di ruoli: e' la porta inviolata che li premia
#     insieme. (Le misure precedenti davano +0.333 ma erano correlazioni dei
#     PUNTEGGI, che includono la parte gia' prevista dal modello: per la
#     varianza dell'errore serve questa.)
#   - dentro una formazione da 5 quella coppia aggiunge +2.25 punti di
#     dispersione, perche' gli altri tre slot la smorzano
#   - in arena un punto di dispersione vale 0.78 punti di punteggio atteso su
#     una formazione da 265, 0.53 a 280, 0.31 a 295: piu' si e' sopra il
#     pareggio, meno serve rischiare
# Il valore a 280 -- la zona in cui le arene si giocano davvero -- e' 1.19.
GK_DEF_PAIR_BONUS = float(os.environ.get('GK_DEF_PAIR_BONUS', '1.2'))
# Secondo difensore della stessa squadra del portiere: la coppia DEF+DEF vale
# 0.71 a 280, quindi il secondo aggiunge meno del primo, non quanto il primo.
GK_DEF_PAIR_BONUS_2 = float(os.environ.get('GK_DEF_PAIR_BONUS_2', '0.7'))

# Bonus anti-stack Sorare (26/07, scoperto dall'utente per In Season, CONFERMATO
# valido anche per All Stars il 26/07 sera -- stessa soglia, non scalata a 7
# giocatori): se una formazione ha MENO di 3 giocatori della stessa squadra,
# ogni giocatore riceve +2% al proprio punteggio; con 3+ della stessa squadra
# il bonus salta per TUTTI (5 In Season, 7 All Stars). La sinergia GK+DEF
# sopra, da sola, porta al massimo a 2 giocatori della stessa squadra (GK + 1
# DEF titolare) -- nessun conflitto, resta "gratis". Il conflitto nasce solo
# se un ALTRO slot (tipicamente l'extra) porterebbe una squadra al 3o
# giocatore: li' il costo e' certo (-2% su tutti) mentre il beneficio di
# correlazione e' incerto, quindi di default scoraggiamo (non vietiamo: a
# volte, es. capolista contro ultima, puo' valere la pena sacrificare il
# bonus per un punteggio quasi certo -- scelta che spetta all'utente, non
# all'algoritmo) il 3o giocatore della stessa squadra. Applicato per In
# Season e All Stars (apply_stack_guard): Arena NON ha questo bonus (ha il
# suo cap L10 obbligatorio separato, nessuna % aggiuntiva).
IN_SEASON_STACK_LIMIT = 2
STACK_GUARD_PENALTY = 8_000  # come ANTI_SYNERGY_PENALTY: spinge in fondo, non esclude

# Sinergia da correlazione misurata, SOLO Arena/All Stars (27/07, tema
# "correlazione slot formazione" del backlog, vedi diagnostics/
# measure_teammate_correlation.py). Prima di questo tuning i nudge sopra
# (POSITIVE_SYNERGY_BONUS/ANTI_SYNERGY_PENALTY) erano intuizione mai
# misurata. Il residuo walk-forward (reale - baseline media/venue/trend) di
# compagni di squadra nella STESSA partita, sulle cache di calibrazione
# GK/DEF/MID/FWD, mostra correlazioni positive robuste. Perche' SOLO Arena/
# All Stars: in In Season il target e' fisso, il valore atteso della somma
# non dipende dalla correlazione (Finding 3+F, chiuso), quindi spingere la
# scelta verso compagni correlati costerebbe valore atteso reale senza
# alcun beneficio -- il beneficio esiste solo dove la varianza conta
# (taglio premi Arena 30%/All Stars 5%).
#
# RI-MISURATO 28/07 sera su 25 campionati (146 squadre, 1213 partite con 2+
# giocatori cachati -- prima erano solo 1-2 campionati): valori CAMBIATI in
# modo sostanziale rispetto alla prima misurazione (GK-DEF +0.40->+0.355,
# DEF-MID +0.27->+0.136, GK-MID +0.26->+0.143, DEF-DEF +0.23->+0.221) e
# soprattutto FWD, che prima "non mostrava correlazione significativa con
# nessun ruolo", ORA la mostra (def-fwd +0.093 p=0.006, fwd-mid +0.169
# p=0.001, fwd-fwd +0.154 p=0.045 -- tutti stabili split-half tranne
# fwd-fwd che ha n piu' piccolo, 173 coppie). mid-mid (+0.130 p=0.011,
# stabile) non era mai stato isolato prima. Valori scalati ~20x la
# correlazione misurata (stessa convenzione di prima), sostituendo il
# vecchio bonus FLAT unico (TEAMMATE_SYNERGY_BONUS_VARIANCE=5 per qualunque
# coppia DEF/MID/FWD) con un valore per coppia -- usa chosen_roles_by_team,
# stessa infrastruttura di CROSS_TEAM_PENALTY_BY_PAIR.
#
# RI-MISURATO 30/07 (richiesta esplicita utente, campione quasi 25x piu'
# grande: 30.068 coppie/162 squadre, dopo il fix anyPlayers->activePlayers)
# -- quasi tutte le correlazioni sono uscite PIU' DEBOLI del 28/07 (def-mid
# 0.136->0.094, gk-mid 0.143->0.107, mid-mid 0.130->0.108, def-fwd
# 0.093->0.060), stabili split-half su tutte. Eccezione: fwd-fwd molto PIU'
# FORTE e ora su un campione solido (0.154->0.223, n=945 contro i 173 di
# prima). def-def/gk-def sostanzialmente invariati. Nessun cambio di
# METODO oggi (resta lo scaling x20 grezzo) -- solo refresh dei numeri con
# dati piu' puliti; il modello decisionale dedicato (legare la dimensione
# del bonus alla reale probabilita' di superare la soglia premio Arena/
# All Stars, invece di scalare la correlazione a naso) resta in backlog,
# mai iniziato.
# SCALING x20 -> x12 (31/07): il "modello decisionale dedicato" citato qui
# sopra come mai iniziato e' stato fatto -- vedi
# formazione_mls/diagnostics/ab_arena_synergy_threshold.py. Monte Carlo su
# punteggi REALI, compagni campionati dalla STESSA partita vera, e come
# metrica la PROBABILITA' di superare la soglia invece del punteggio atteso
# (la sinergia serve ad alzare la varianza: il valore atteso e' cieco proprio
# all'effetto per cui questa tabella esiste).
#
# Misurato su ALLSTARS a soglie FISSE, x12 domina x20 su ENTRAMBE le metriche:
# 428.5 pt attesi contro 426.2, e a 470/490/510/530/550/570 fa
# +0.68/+2.79/+6.65/+8.65/+8.98/+6.55 punti percentuali contro
# -0.26/+0.69/+3.47/+4.96/+5.54/+4.62 -- con x20 a soglia 470 la sinergia era
# perfino CONTROPRODUCENTE. Plateau ottimale fra x10 e x15 (x10 e x15 danno
# formazioni identiche), 12 e' il centro.
#
# Effetto sugli altri tipi: NESSUNO. Per ARENA_ALLSTARS_260/220 e le Arene
# dedicate il cap L10 obbligatorio rende la sinergia inerte (formazioni
# identiche ON/OFF, verificato due volte), ARENA_ALLSTARS_UNCAPPED e le In
# Season sono gia' escluse a monte. Il cambio tocca quindi solo All Stars.
#
# LIMITE NOTO, da tenere presente: misurato su 4 formazioni (il cap duro per
# ALLSTARS) di UNA sola giornata. Applicato subito per scelta esplicita
# dell'utente, con l'impegno di rimisurare sulle prossime giornate -- vedi
# backlog. Per rifare la misura:
#   TIPI=ALLSTARS QUANTE=4 SCALA=12 SOGLIE="470,490,510,530,550,570" \
#     python formazione_mls/diagnostics/ab_arena_synergy_threshold.py
# Quanto vale la varianza dipende da DOVE sei rispetto al pareggio: misurato in
# arena, un punto di dispersione vale 0.78 punti di punteggio atteso su una
# formazione da 265, 0.53 a 280, 0.31 a 295. Sotto il pareggio serve rischiare,
# sopra si rischia solo di buttare via un piazzamento gia' in mano.
#
# I bonus qui sotto sono tarati a 280. Questo fattore li scala in base a quanto
# forte sta venendo la formazione: pieno e mezzo se e' debole, un terzo se e'
# gia' forte. Con forza ignota resta 1.0, cioe' il comportamento tarato.
#
# ATTENZIONE ALLA SCALA (04/08). La curva qui sotto e' misurata su una
# formazione ARENA da 5 slot, fascia 255-300. '_forza_stimata' invece proietta
# sul numero di slot VERO del tipo, e All Stars ne ha 7: li' esce 363-410,
# sempre oltre il fondo della curva, quindi il fattore vale 0.585 SEMPRE (un
# solo valore su 3180 chiamate misurate) -- non e' "scalato sulla forza", e'
# uno sconto fisso del 41% che non risponde a niente. Sulle In Season (5 slot
# ma ~250 punti) succede l'opposto: fattore 1.43-1.47, bonus gonfiati del 45%
# proprio dove la varianza conta meno. E sulle arene con cap L10 non viene mai
# chiamato, perche' quelle passano dal knapsack che ignora le sinergie.
# FORZA_NORM=1 riporta la forza alla scala a 5 slot prima di leggere la curva,
# e passa la forza anche allo slot EXTRA (l'unico dove la stima e' piu'
# affidabile -- 4 titolari su 5 gia' scelti -- e l'unico escluso).
#
# RESTA SPENTO: la diagnosi sopra e' solida, la cura non ha passato la prova.
# Su UNA giornata, con Monte Carlo su punteggi reali, sembrava vincere su tutte
# e sei le soglie (+0.28/+1.09 pp, diagnostics/ab_fattore_varianza.py). Su 48
# giornate VERE con punteggi REALIZZATI (ab_fattore_varianza_storico.py) il
# risultato non regge: 44 formazioni su 48 restano identiche, 3 migliorano e 1
# peggiora, differenza media -0.74 pt con IC95% [-3.29, +1.81] -- lo zero e'
# dentro. Sulle soglie basse -2.08 pp, sopra 440 nessuna differenza.
# La lezione e' quella gia' pagata altre volte: una misura su una sola giornata
# non basta, per quanto la teoria sia convincente. Non riaccenderlo senza un
# campione che sposti davvero quell'intervallo.
FORZA_RIFERIMENTO = 280.0
_CAMBIO_DISPERSIONE = ((265.0, 0.78), (280.0, 0.53), (295.0, 0.31))
FORZA_NORM = os.environ.get('FORZA_NORM', '0') == '1'
SLOT_RIFERIMENTO = 5   # su quanti slot e' misurata _CAMBIO_DISPERSIONE


def fattore_varianza(forza_attesa):
    """Quanto scalare i bonus di sinergia, data la forza della formazione."""
    if forza_attesa is None:
        return 1.0
    punti = _CAMBIO_DISPERSIONE
    if forza_attesa <= punti[0][0]:
        v = punti[0][1]
    elif forza_attesa >= punti[-1][0]:
        v = punti[-1][1]
    else:
        v = punti[-1][1]
        for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
            if x0 <= forza_attesa <= x1:
                v = y0 + (y1 - y0) * (forza_attesa - x0) / (x1 - x0)
                break
    base = 0.53   # il valore a FORZA_RIFERIMENTO, su cui i bonus sono tarati
    return max(0.3, min(1.6, v / base))


SAME_TEAM_SYNERGY_BONUS_BY_PAIR = {
    # RIMISURATO il 02/08 su 69.151 coppie previsione/realizzato, walk-forward.
    # I valori precedenti (4/3/3/2/1...) venivano da correlazioni dei PUNTEGGI
    # moltiplicate per 12; quelle giuste per la varianza dell'errore sono le
    # correlazioni dei RESIDUI, che sono circa la meta'. Qui sotto il valore in
    # punti di punteggio atteso su una formazione da 280, cioe' la zona in cui
    # le arene si giocano davvero (a 265 vale il 50% in piu', a 295 il 40% in
    # meno: la varianza serve solo quando si e' sotto il pareggio).
    frozenset(('GK', 'DEF')): 1.2,    # rho +0.297, la piu' alta
    frozenset(('DEF', 'DEF')): 0.7,   # rho +0.174
    frozenset(('FWD', 'FWD')): 0.5,   # rho +0.117
    frozenset(('DEF', 'MID')): 0.3,   # rho +0.077
    frozenset(('GK', 'MID')): 0.3,    # rho +0.071
    frozenset(('FWD', 'MID')): 0.3,   # rho +0.068
    frozenset(('MID', 'MID')): 0.3,   # rho +0.067
    frozenset(('DEF', 'FWD')): 0.1,   # rho +0.031, quasi indipendenti
}

# Sinergia same-team per In Season (30/07, NUOVO -- prima esclusa del tutto,
# vedi commento storico su variance_mode piu' sotto). L'esclusione si basava
# su un ragionamento incompleto ("il target e' fisso quindi il valore atteso
# non dipende dalla correlazione, nessun beneficio") -- vero per il valore
# atteso, MA la correlazione cambia comunque la PROBABILITA' di superare il
# target fisso (piu' varianza aiuta se il bersaglio e' sopra la media, che e'
# il caso comune: bersagli reali forniti dall'utente 340/360/400/420/460).
# Misurato con formazione_mls/diagnostics/estimate_inseason_synergy_
# allpairs.py: Monte Carlo su punteggi REALI (non normale), coppie
# same-team/data osservate davvero, pool "top 60% per media" (n=1085-4177
# osservazioni per coppia dopo l'ampliamento richiesto dall'utente -- il
# giro iniziale a top 25%/n=175-326 aveva anche un bug di campionamento,
# corretto: il pool di coppie reali aveva media diversa dal pool generale,
# gonfiando il delta misurato prima della correzione). Valori = punti
# equivalenti medi sui 5 target reali (quanto dovrebbe salire la media SENZA
# sinergia per eguagliare la P(superare il target) CON sinergia). Solo LE
# COPPIE CON SEGNALE CHIARO: gk-mid e def-fwd erano sostanzialmente zero su
# tutti i target, non modellate (comportamento invariato per quelle due).
# Bonus MOLTO piu' piccoli di SAME_TEAM_SYNERGY_BONUS_BY_PAIR (Arena/All
# Stars) perche' In Season ha "6 vite" per un solo premio: il beneficio
# marginale della varianza dentro UNA formazione e' diluito dal poter gia'
# tentare piu' formazioni indipendenti (vedi MATCH_REUSE_PENALTY).
#
# !!! NON USATA IN PRODUZIONE (accertato 31/07, audit completo) !!!
# Due fatti distinti, entrambi verificati empiricamente:
#
# 1. NON E' MAI STATA ATTIVA. Le formazioni reali le genera
#    generatore_formazioni/build_formazione_globale.py, non la
#    generate_lineups_for_type di QUESTO file (che il workflow non chiama
#    mai -- vedi .github/workflows/formazione_giornata.yml, che lancia solo
#    il generatore globale). Nel percorso vivo tre cose indipendenti la
#    spengono: le In Season non sono in VARIANCE_MODE_TYPES, il gate
#    apply_positive_synergy e' False per MLS_IN_SEASON/KLEAGUE_IN_SEASON, e
#    build_one_lineup_with_growth non passa MAI synergy_bonus_dict (quindi
#    _same_team_synergy_bonus ripiegherebbe comunque sulla tabella Arena).
#    Dimostrato azzerando il dizionario: zero differenze su 6 formazioni
#    (formazione_mls/diagnostics/check_inseason_synergy_alive.py).
#
# 2. ATTIVARLA NON CONVIENE, misurato su ENTRAMBE le metriche:
#    - punti attesi (ab_inseason_synergy_gate.py): costa 0 pt su MLS e 3 pt
#      su K League;
#    - probabilita' di superare la soglia premio, cioe' la metrica per cui
#      questa tabella era stata calibrata (ab_inseason_synergy_threshold.py,
#      Monte Carlo su punteggi reali con i compagni campionati dalla STESSA
#      partita vera): differenze fra -0.54 e +0.31 punti percentuali sulle
#      soglie 320-420, di segno incoerente -- rumore, non un effetto. Il
#      meccanismo funziona (dev.std del totale 49.0 -> 49.7, e una formazione
#      in piu' con compagni di squadra) ma e' troppo piccolo per contare.
#
# Lasciata nel file, e non cancellata, perche' i valori misurati restano un
# dato utile se un domani cambiano le soglie o il numero di formazioni
# schierabili. NON riattivarla senza rifare i due test sopra.
IN_SEASON_SYNERGY_BONUS_BY_PAIR = {
    frozenset(('FWD', 'FWD')): 6,   # 5.90pt equivalenti (n=507)
    frozenset(('FWD', 'MID')): 3,   # 3.40pt equivalenti (n=2306)
    frozenset(('GK', 'DEF')): 2,    # 2.46pt equivalenti (n=1823)
    frozenset(('MID', 'MID')): 2,   # 2.02pt equivalenti (n=1085)
    frozenset(('DEF', 'DEF')): 1,   # 1.08pt equivalenti (n=2282)
    frozenset(('DEF', 'MID')): 1,   # 1.06pt equivalenti (n=4177)
    # GK-MID/DEF-FWD: effetto trascurabile su tutti i 5 target, non modellate.
}


def _same_team_synergy_bonus(role, row, chosen_roles_by_team, bonus_dict=None):
    """Analogo a _cross_team_penalty ma per compagni di squadra (bonus, non
    penalita'). Somma il bonus per OGNI OCCORRENZA di ruolo gia' scelta nella
    STESSA squadra di 'row' che forma una coppia con sinergia positiva
    misurata -- FIX 28/07 (bug reale trovato dall'utente): chosen_roles_by_team
    e' un CONTATORE per ruolo, non un set, altrimenti 2 compagni DEF gia'
    scelti (caso strutturale in All Stars, che ha 2 slot DEF) valevano quanto
    1 solo, sottostimando sistematicamente bonus/penalita' ogni volta che una
    squadra ha 2+ giocatori dello stesso ruolo gia' in formazione.
    'bonus_dict' (30/07): quale tabella usare -- SAME_TEAM_SYNERGY_BONUS_BY_PAIR
    (Arena/All Stars, default) o IN_SEASON_SYNERGY_BONUS_BY_PAIR."""
    if bonus_dict is None:
        bonus_dict = SAME_TEAM_SYNERGY_BONUS_BY_PAIR
    if not chosen_roles_by_team:
        return 0
    team_slug = row.get('team_slug')
    if not team_slug:
        return 0
    bonus = 0
    for prev_role, count in chosen_roles_by_team.get(team_slug, {}).items():
        w = bonus_dict.get(frozenset((role, prev_role)))
        if w:
            bonus += w * count
    return bonus

# Decorrelazione tra le N formazioni In Season (28/07, sez. 29.D/tema
# "portafoglio": il premio scatta se ALMENO UNA delle N formazioni supera il
# target di giornata, non sulla media -- quindi le N formazioni rendono di piu'
# se sono tentativi il piu' possibile INDIPENDENTI. Se piu' formazioni
# condividono la stessa partita reale (stessa coppia squadra-avversario) e
# quella partita va male, falliscono insieme: nessun vantaggio dai tentativi
# multipli).
#
# A DIFFERENZA di ANTI_SYNERGY_PENALTY/STACK_GUARD_PENALTY (valori enormi,
# quasi un'esclusione "ultima risorsa" per regole di gioco certe), questo e'
# un TIE-BREAKER leggero (28/07 sera, richiesta esplicita utente dopo revisione:
# il valore originale 6_000 rischiava di buttar fuori un giocatore nettamente
# piu' forte solo per decorrelare un beneficio mai misurato su dati reali --
# vedi memoria di sessione). Stessa scala di TEAMMATE_SYNERGY_BONUS_VARIANCE/
# SAME_TEAM_SYNERGY_BONUS_BY_PAIR: pesa solo quando due candidati sono gia'
# vicini per punteggio, non ribalta un divario di qualita' reale.
MATCH_REUSE_PENALTY = 6



# --- Stack consentito sulle partite squilibrate (01/08) ---------------------
# Misurato su 9058 partite ricostruite (misura_fullstack.py): con 5 giocatori
# della stessa squadra la probabilita' di superare una soglia alta passa dal
# 10% al 14.9%, e sulle STRAFAVORITE sale anche il punteggio medio. Il criterio
# NON e' la classifica -- non esiste alla prima giornata ed e' rumore nelle
# prime -- ma il divario di forza rosa, cioe' il punteggio medio storico dei
# giocatori dei due club.
SOGLIA_FORZA_STACK = float(os.environ.get('SOGLIA_FORZA_STACK', '6.0'))
_FORZA_ROSA = None


def _forza_rosa():
    global _FORZA_ROSA
    if _FORZA_ROSA is None:
        _FORZA_ROSA = {}
        for base in ('forza_rosa.json',
                     os.path.join(os.path.dirname(__file__), '..', 'forza_rosa.json')):
            try:
                with open(base, encoding='utf-8') as f:
                    _FORZA_ROSA = json.load(f) or {}
                break
            except Exception:
                continue
    return _FORZA_ROSA


def stack_consentito(row):
    """True se la squadra e' cosi' piu' forte dell'avversario da rendere lo
    stack conveniente. Se manca il dato di una delle due, False: si resta al
    comportamento di prima."""
    f = _forza_rosa()
    mio, avv = row.get('team_slug'), row.get('opponent_team_slug')
    if not (mio and avv and mio in f and avv in f):
        return False
    return (f[mio] - f[avv]) >= SOGLIA_FORZA_STACK


def _match_key(row):
    team = row.get('team_slug')
    opponent = row.get('opponent_team_slug')
    if not team or not opponent:
        return None
    return frozenset((team, opponent))


# Estensione anti-sinergia CROSS-team (28/07 sera, richiesta esplicita utente
# dopo ri-misurazione su 25 campionati/1213 partite -- vedi
# diagnostics/measure_teammate_correlation.py, sezione "Cross-team"). L'unica
# anti-sinergia cross-team gia' in produzione era GK-vs-MID/FWD della squadra
# avversaria del portiere (ANTI_SYNERGY_PENALTY sotto). I dati confermano
# ALTRE coppie cross-team negative e STABILI split-half (segno identico prima/
# seconda meta' cronologica): DEF-DEF -0.137 (split -0.101/-0.167), DEF-FWD
# -0.126 (split -0.189/-0.118), MID-MID -0.118 (split -0.187/-0.105). DEF-MID
# (-0.167, p=0.001) e' risultata SIGNIFICATIVA ma NON stabile split-half
# (-0.006 prima meta' vs -0.210 seconda -- probabile rumore/effetto
# recente non consolidato) e resta ESCLUSA finche' non si ri-conferma.
# Scala ~20x la correlazione misurata, stessa convenzione di
# SAME_TEAM_SYNERGY_BONUS_BY_PAIR (nudge
# soft, mai un'esclusione). Chiave = coppia di ruoli non ordinata.
#
# AGGIORNAMENTO 30/07 (sez. 37/38 RIASSUNTO, ricalibrazione su 23.211 partite
# dopo il fix anyPlayers->activePlayers, campione cross-team quasi triplicato
# e piu' pulito -- decisione utente via popup a fine sessione): DEF-FWD
# rimisurata piu' forte (-0.195, era -0.126) -> penalty 3->4. DEF-MID
# rimisurata SIGNIFICATIVA e ora il campione cross-team piu' grande di tutti
# (6021 coppie) da' -0.131 -> AGGIUNTA (era esclusa il 28/07 per instabilita'
# split-half su un campione molto piu' piccolo). DEF-DEF oggi NON
# significativo (-0.030, p=0.067, era -0.137) -> RIMOSSA (decisione utente
# via popup). MID-MID oggi piu' debole (-0.082 vs -0.118) ma ancora negativa:
# lasciata INVARIATA su richiesta esplicita dell'utente -- richiede conferma
# esplicita prima di toccarla.
# RI-MISURATO 31\07 su TUTTE le coppie insieme, stesso dataset (7.271 partite
# ricostruite dai detail cache, 97k coppie avversarie) --
# formazione_mls/diagnostics/misura_correlazione_cross_team.py.
# Novita' di metodo: accanto alla correlazione fra AVVERSARI si misura una
# correlazione di CONTROLLO fra le stesse coppie di ruoli ma su partite
# DIVERSE. Serve perche' due punteggi qualsiasi non sono scorrelati per caso
# (i ruoli hanno medie e dispersioni diverse): solo lo scarto fra le due
# colonne e' effetto reale dello scontro diretto. Il controllo e' uscito ~0
# ovunque, quindi le correlazioni negative qui sotto sono genuine.
#
#  coppia    n coppie   corr avversari   controllo   x20 implicito
#  DEF-MID     22410       -0.1544         +0.0113        3.1
#  DEF-FWD     15853       -0.2250         +0.0122        4.5
#  DEF-DEF     13424       -0.1009         -0.0038        2.0
#  FWD-MID     12896       -0.0788         +0.0031        1.6
#  MID-MID      9592       -0.1030         +0.0008        2.1
#  GK-MID       6106       -0.1448         +0.0128        2.9
#  FWD-GK       4340       -0.3121         -0.0013        6.2
#  DEF-GK       7371       -0.0403         +0.0079        0.8  (escluso)
#  FWD-FWD      4633       -0.0373         -0.0383        0.7  (escluso)
#  GK-GK         967       +0.0380         +0.0098         -   (escluso)
#
# Le tre penalita' che c'erano gia' sono CONFERMATE e ben tarate (3 contro
# 3.1, 4 contro 4.5, 2 contro 2.1): la tabella era giusta, era solo inerte
# per il bug del gate (vedi sotto _cross_team_penalty).
# AGGIUNTE 31\07 le quattro coppie che mancavano, fra cui la piu' forte di
# tutte: FWD contro il GK avversario (-0.31). Ha senso strutturale --
# l'attaccante segna quando fa gol, il portiere avversario segna quando tiene
# la porta inviolata: sono opposti per costruzione, e fino a oggi il modello
# non li scoraggiava affatto.
# ESCLUSE di proposito DEF-GK (troppo debole), GK-GK (correlazione positiva,
# e comunque n=967) e soprattutto FWD-FWD: la sua correlazione (-0.037) e'
# identica al proprio controllo (-0.038), cioe' non c'e' NESSUN effetto da
# scontro diretto, solo la distribuzione dei punteggi di ruolo.
#
# RIPORTATA IN SCALA il 04/08 (formazione_mls/diagnostics/misura_sinergie_
# coppie.py, 75.474 coppie previsione/realizzato walk-forward col modello di
# oggi). Era l'ULTIMA tabella rimasta sulla vecchia convenzione "correlazione
# dei PUNTEGGI x20": la gemella positiva (SAME_TEAM_SYNERGY_BONUS_BY_PAIR) era
# gia' passata il 02/08 alle correlazioni dei RESIDUI convertite in punti di
# punteggio atteso, questa no. Le due tabelle vivevano quindi su scale diverse
# di un fattore 5-10, e il generatore sacrificava fino a SEI punti certi per
# evitare una coppia avversaria che ne costa UNO -- lo stesso errore gia'
# corretto sul bonus GK+DEF (era 5, misurato 1.2), rimasto sull'altra meta'.
#
# Segno e ordine delle coppie sono CONFERMATI (nessuna coppia aggiunta o tolta,
# nessuna cambia verso). Cambia solo la scala. La conversione e' la stessa del
# lato positivo: quanto quella coppia toglie alla dispersione di una formazione
# da 5, per quanto vale un punto di dispersione a FORZA_RIFERIMENTO=280:
#   sd * (sqrt(5) - sqrt(5 + 2*rho)) * 0.53,  con sd = 17.45
#
#  coppia    n coppie    rho     IC 95%            controllo   punti@280
#  GK-FWD      10237   -0.227   [-0.243,-0.210]     +0.001       1.0   (era 6)
#  DEF-FWD     47429   -0.144   [-0.153,-0.134]     -0.000       0.6   (era 4)
#  GK-MID      12746   -0.121   [-0.138,-0.106]     +0.003       0.5   (era 3)
#  DEF-MID     58527   -0.090   [-0.098,-0.081]     +0.006       0.4   (era 3)
#  MID-MID     27119   -0.063   [-0.076,-0.050]     -0.003       0.25  (era 2)
#  MID-FWD     43625   -0.058   [-0.067,-0.048]     -0.001       0.25  (era 2)
#  DEF-DEF     31437   -0.046   [-0.057,-0.035]     +0.001       0.2   (era 2)
#  GK-DEF      13931   -0.011   IC include lo zero               -     (assente)
#  FWD-FWD     17415   -0.016   pari al proprio controllo        -     (assente)
#  GK-GK        1472   +0.034   IC include lo zero               -     (assente)
#
# Il "controllo" e' la stessa coppia di ruoli su partite DIVERSE: esce ~0
# ovunque, quindi queste correlazioni sono davvero effetto dello scontro
# diretto e non della forma delle distribuzioni di ruolo.
CROSS_TEAM_PENALTY_BY_PAIR = {
    frozenset(('FWD', 'GK')): 1.0,   # rho -0.227, la piu' forte: l'attaccante
                                     # segna coi gol, il portiere avversario
                                     # con la porta inviolata
    frozenset(('DEF', 'FWD')): 0.6,   # rho -0.144
    frozenset(('GK', 'MID')): 0.5,    # rho -0.121
    frozenset(('DEF', 'MID')): 0.4,   # rho -0.090
    frozenset(('MID', 'MID')): 0.25,  # rho -0.063
    frozenset(('FWD', 'MID')): 0.25,  # rho -0.058
    frozenset(('DEF', 'DEF')): 0.2,   # rho -0.046
}


def _cross_team_penalty(role, row, chosen_roles_by_team):
    """Somma la penalita' per OGNI OCCORRENZA di ruolo gia' scelta nella
    squadra AVVERSARIA di 'row' che forma una coppia cross-team confermata
    negativa (vedi CROSS_TEAM_PENALTY_BY_PAIR). 'chosen_roles_by_team': dict
    team_slug -> CONTATORE di ruoli gia' presenti in formazione per quella
    squadra (FIX 28/07: era un set, sottostimava la penalita' quando la
    squadra avversaria ha 2+ giocatori dello stesso ruolo gia' scelti)."""
    if not chosen_roles_by_team:
        return 0
    opponent = row.get('opponent_team_slug')
    if not opponent:
        return 0
    penalty = 0
    for prev_role, count in chosen_roles_by_team.get(opponent, {}).items():
        w = CROSS_TEAM_PENALTY_BY_PAIR.get(frozenset((role, prev_role)))
        if w:
            penalty += w * count
    return penalty


def synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                      variance_mode=False, apply_positive_synergy=True, used_matches=None,
                      chosen_roles_by_team=None, synergy_bonus_dict=None,
                      apply_cross_team_penalty=True, forza_attesa=None):
    """Punteggio AGGIUSTATO solo per decidere l'ORDINE di scelta tra candidati
    dello stesso ruolo, dato il portiere gia' selezionato per questa lineup.
    Non altera mai 'atteso' nel dict originale (usato per punteggio/range in
    output) -- vedi commento sopra ANTI_SYNERGY_PENALTY per la logica.
    'team_counts'/'apply_stack_guard': vedi commento sopra IN_SEASON_STACK_LIMIT.
    'variance_mode': vedi commento sopra SAME_TEAM_SYNERGY_BONUS_BY_PAIR
    (SOLO Arena/All Stars -- generate_lineups_for_type decide il valore).
    'apply_positive_synergy' (27/07, richiesta esplicita utente per le In
    Season con 2+ formazioni richieste): gate UNICO sia per il bonus DEF-GK
    (POSITIVE_SYNERGY_BONUS) sia per la penalita' soft MID/FWD-vs-avversario
    (ANTI_SYNERGY_PENALTY) -- quest'ultima e' comunque superata da un filtro
    DURO in build_one_lineup quando serve (strict_gk_anti_synergy), quindi qui
    resta solo per il caso in cui il filtro duro non e' attivo (Arena/All
    Stars, o In Season con una sola formazione richiesta, comportamento
    INVARIATO rispetto a prima). Se False (formazioni "greedy" #2..N delle In
    Season multiple), niente bonus/penalita' di correlazione: solo punteggio
    grezzo -- il vincolo di schieramento resta comunque garantito dal filtro
    duro, applicato a monte, non da qui.
    'sort_score' (30/07, vedi _apply_xp_bonus in build_formazione_globale.py):
    se il candidato ha un punteggio boost-XP calcolato SOLO per l'ordine di
    scelta (senza gonfiare 'atteso', il numero mostrato), si parte da quello
    invece che da 'atteso' -- stesso principio di 'ordinamento' ma per il
    bonus XP invece dello shrinkage."""
    adjusted = row.get('sort_score', row['atteso'])
    team_slug = row.get('team_slug')
    if apply_positive_synergy:
        if role in ('MID', 'FWD') and gk_opponent_slug and team_slug == gk_opponent_slug:
            adjusted -= ANTI_SYNERGY_PENALTY
    # BLOCCO DIFENSIVO GK+DEF con gate PROPRIO (01/08). Prima stava dentro
    # apply_positive_synergy, spento sulle In Season: era percio' inerte
    # proprio dove serve. La correlazione same-team GK-DEF e' +0.341, la piu'
    # forte di tutte (condividono la porta inviolata): quando il portiere fa
    # piu' di 55, il suo difensore fa in media 60.6 contro 47.5 -- tredici
    # punti di differenza sullo stesso giocatore.
    # Misurato DENTRO formazioni da 5 (le coppie isolate sovrastimano):
    #   GK+1DEF  top10% 11.8% vs 10.0%  -> vale 5 pt di sacrificio
    #   GK+2DEF  top10% 14.9% vs 10.0%  -> l'effetto cresce, non satura
    # In mediana danneggia, ma il bersaglio e' sempre la coda alta per scelta
    # esplicita dell'utente: un premio basso mancato costa poco, quello alto
    # costa tutto.
    #
    # GATE 'not variance_mode' (04/08, doppio conteggio reale): questo blocco e
    # la tabella same-team piu' sotto sono LA STESSA MISURA -- GK_DEF_PAIR_BONUS
    # vale 1.2 e SAME_TEAM_SYNERGY_BONUS_BY_PAIR[GK,DEF] vale 1.2, entrambi
    # ricavati dallo stesso rho +0.29 il 02/08. In variance_mode (Arena/All
    # Stars) sparavano ENTRAMBI: un DEF della squadra del portiere prendeva
    # +2.40 invece di +1.16, e il secondo +2.60 invece di +1.87. Verificato
    # chiamando synergy_sort_key direttamente. Fuori da variance_mode (In
    # Season) la tabella non e' applicata, quindi questo blocco resta l'unica
    # fonte del bonus e il comportamento li' NON cambia.
    if (not variance_mode) and role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
        gia_presi = (chosen_roles_by_team or {}).get(gk_team_slug, {}).get('DEF', 0)
        # scalato sulla forza: la varianza serve sotto il pareggio, non sopra
        adjusted += fattore_varianza(forza_attesa) * (
            GK_DEF_PAIR_BONUS if gia_presi == 0 else GK_DEF_PAIR_BONUS_2)
    # PENALITA' CROSS-TEAM SCORPORATA dal gate (31/07, bug reale trovato
    # dall'utente su una formazione In Season MLS reale: Markanich (DEF,
    # Minnesota) schierato INSIEME a Dreyer e Tverskov (MID, San Diego), cioe'
    # giocatori avversari nella STESSA partita -- se Minnesota tiene la porta
    # inviolata il difensore segna e i due centrocampisti no, sono
    # negativamente correlati per costruzione).
    #
    # Il commento sotto ad apply_positive_synergy in build_formazione_globale.py
    # aveva gia' previsto questo caso: quel flag e' il gate UNICO di TRE
    # meccanismi (nudge GK-DEF, penalita' cross-team, bonus same-team), e
    # metterlo a False per le In Season -- scelta presa per i primi due -- ha
    # spento in silenzio anche il terzo. Le penalita' cross-team calibrate il
    # 30/07 erano quindi INERTI proprio sulle In Season.
    #
    # Misurato sul report reale run91: 7 formazioni su 34 contenevano coppie
    # avversarie nella stessa partita, per 23 punti di penalita' mai applicata.
    # Ora ha un gate PROPRIO, attivo di default: e' un vincolo di realta'
    # (due carte che si annullano a vicenda), non una preferenza tattica come
    # le sinergie positive.
    # SCALATA SULLA FORZA dal 04/08, come i bonus positivi: era l'unico
    # meccanismo di correlazione a NON passare da fattore_varianza. Un punto di
    # dispersione vale 0.78 su una formazione da 265 e 0.31 su una da 295, e
    # questo vale identico che la dispersione la si guadagni (compagni) o la si
    # perda (avversari) -- e' la stessa valuta. Senza lo scaling, la penalita'
    # restava piena proprio sulle formazioni forti, dove togliere varianza
    # e' un beneficio e non un costo.
    if apply_cross_team_penalty:
        adjusted -= fattore_varianza(forza_attesa) * _cross_team_penalty(
            role, row, chosen_roles_by_team)
    # apply_positive_synergy nel gate (30/07): prima non serviva perche' In
    # Season aveva variance_mode sempre False -- ora che la sinergia same-team
    # e' abilitata anche li', deve rispettare lo stesso "greedy puro dalla
    # 2a formazione in poi" delle altre sinergie (vedi docstring sopra),
    # altrimenti le In Season multiple userebbero la sinergia solo per la
    # PRIMA formazione in modo incoerente col resto.
    # GATE PROPRIO (01/08), stesso motivo della penalita' cross-team e del
    # blocco GK+DEF: apply_positive_synergy spegne TRE meccanismi insieme ed e'
    # spento sulle In Season per una ragione che riguarda solo il primo, quindi
    # la sinergia same-team era inerte proprio dove serve. Misurata dentro
    # formazioni da 5, top 10%: DEF+DEF 11.5% vs 10.0% (vale 4 pt), MID+MID e
    # MID+FWD 10.9%/10.8% (2.5 pt). Valori coerenti con la tabella, che resta.
    if variance_mode and team_slug:
        adjusted += fattore_varianza(forza_attesa) * _same_team_synergy_bonus(
            role, row, chosen_roles_by_team, synergy_bonus_dict)
    if (apply_stack_guard and team_slug and team_counts
            and team_counts.get(team_slug, 0) >= IN_SEASON_STACK_LIMIT
            and not stack_consentito(row)):
        adjusted -= STACK_GUARD_PENALTY
    if used_matches and _match_key(row) in used_matches:
        adjusted -= MATCH_REUSE_PENALTY
    return adjusted


def synergy_adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                           variance_mode=False, apply_positive_synergy=True, used_matches=None,
                           chosen_roles_by_team=None, synergy_bonus_dict=None,
                           apply_cross_team_penalty=True, forza_attesa=None):
    """Ritorna i candidati di un ruolo di movimento riordinati per sinergia/
    anti-sinergia col portiere scelto (vedi synergy_sort_key), la sinergia
    da correlazione misurata (SOLO variance_mode) ed eventualmente per il
    vincolo anti-stack In Season/All Stars. Se il portiere non ha
    squadra/avversario noti (consiglio generato prima di questo
    aggiornamento, o dato di calendario mancante) e non c'e' ne' vincolo
    anti-stack ne' variance_mode ne' sinergia positiva da applicare, non
    cambia nulla -- comportamento identico a prima."""
    if (not apply_stack_guard and not variance_mode
            and not (apply_positive_synergy and (gk_team_slug or gk_opponent_slug or chosen_roles_by_team))
            and not (apply_cross_team_penalty and chosen_roles_by_team)
            and not used_matches):
        return rows
    return sorted(rows, key=lambda row: synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug,
                                                           team_counts, apply_stack_guard, variance_mode,
                                                           apply_positive_synergy, used_matches,
                                                           chosen_roles_by_team, synergy_bonus_dict,
                                                           apply_cross_team_penalty, forza_attesa),
                  reverse=True)


def _read_int_env(name, default):
    val = os.environ.get(name)
    if val is None or val.strip() == '':
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_formation_counts():
    """Legge i 4 parametri di conteggio formazioni (26/07, seconda sessione):
    NUM_TOTALE_FORMAZIONI, NUM_FORM_IN_SEASON, NUM_FORM_ARENA,
    NUM_FORM_ALLSTARS -- da env var (input workflow_dispatch). Ognuno dei 3
    sotto-totali puo' essere 0 (tipo disattivato). Compatibilita' locale:
    se nessuna delle 4 env var e' impostata, ricade sul vecchio singolo
    argomento CLI/env NUM_FORMAZIONI (comportamento pre-26/07: tutte In
    Season). FAIL-FAST: il totale deve combaciare esattamente con la somma
    dei 3 sotto-totali, altrimenti SystemExit prima di fare qualunque cosa."""
    has_new_inputs = any(
        os.environ.get(k) not in (None, '')
        for k in ('NUM_TOTALE_FORMAZIONI', 'NUM_FORM_IN_SEASON', 'NUM_FORM_ARENA_260',
                   'NUM_FORM_ARENA_220', 'NUM_FORM_ARENA_UNCAPPED', 'NUM_FORM_ALLSTARS')
    )
    if not has_new_inputs:
        # Vecchio comportamento (pre-26/07): un solo numero, tutte In Season.
        n = DEFAULT_NUM_FORMAZIONI
        if len(sys.argv) > 1:
            try:
                candidate = int(sys.argv[1])
                if candidate >= 1:
                    n = candidate
            except ValueError:
                pass
        else:
            env_val = os.environ.get('NUM_FORMAZIONI')
            if env_val:
                try:
                    candidate = int(env_val)
                    if candidate >= 1:
                        n = candidate
                except ValueError:
                    pass
        return {'IN_SEASON': n, 'ARENA_260': 0, 'ARENA_220': 0, 'ARENA_UNCAPPED': 0, 'ALLSTARS': 0}, n

    num_totale = _read_int_env('NUM_TOTALE_FORMAZIONI', 0)
    num_in_season = _read_int_env('NUM_FORM_IN_SEASON', 0)
    num_arena_260 = _read_int_env('NUM_FORM_ARENA_260', 0)
    num_arena_220 = _read_int_env('NUM_FORM_ARENA_220', 0)
    num_arena_uncapped = _read_int_env('NUM_FORM_ARENA_UNCAPPED', 0)
    num_allstars = _read_int_env('NUM_FORM_ALLSTARS', 0)

    somma = num_in_season + num_arena_260 + num_arena_220 + num_arena_uncapped + num_allstars
    if num_totale != somma:
        raise SystemExit(
            f"ERRORE: NUM_TOTALE_FORMAZIONI={num_totale} non combacia con la somma dei tipi "
            f"(In Season={num_in_season} + Arena cap260={num_arena_260} + Arena cap220={num_arena_220} + "
            f"Arena uncapped={num_arena_uncapped} + All Stars={num_allstars} = {somma}). "
            f"Correggi gli input del workflow -- nessuna formazione generata."
        )

    return {'IN_SEASON': num_in_season, 'ARENA_260': num_arena_260, 'ARENA_220': num_arena_220,
            'ARENA_UNCAPPED': num_arena_uncapped, 'ALLSTARS': num_allstars}, num_totale


def latest_consiglio(output_dir):
    matches = sorted(glob.glob(os.path.join(output_dir, 'consiglio_*.txt')))
    return matches[-1] if matches else None


def parse_consiglio(path):
    """Ritorna lista ordinata di dict {slug, atteso, low, high, team_slug,
    opponent_team_slug} nell'ordine gia' presente nel file (score decrescente,
    come prodotto da build_consiglio_<ruolo>.py). team_slug/opponent_team_slug
    sono None se assenti (consiglio generato prima del 26/07, o dato di
    calendario "N/D") -- retrocompatibile, la logica di sinergia si disattiva
    automaticamente in quel caso."""
    rows = []
    pending = None
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            m = CONSIGLIO_LINE_RE.match(stripped)
            if m:
                if pending:
                    rows.append(pending)
                slug, atteso, low, high = m.groups()
                pending = {'slug': slug, 'atteso': int(atteso), 'low': int(low), 'high': int(high),
                           'team_slug': None, 'opponent_team_slug': None, 'ordinamento': None,
                           'kickoff': None, 'opp_factor': None, 'ambiguo': False}
                continue
            m = ORDINAMENTO_RE.match(stripped)
            if m and pending:
                pending['ordinamento'] = float(m.group(1))
                continue
            m = KICKOFF_RE.match(stripped)
            if m and pending:
                pending['kickoff'] = m.group(1)
                continue
            m = TEAM_RE.match(stripped)
            if m and pending:
                team_slug, opp_slug = m.groups()
                pending['team_slug'] = None if team_slug == 'N/D' else team_slug
                pending['opponent_team_slug'] = None if opp_slug == 'N/D' else opp_slug
                continue
            m = OPP_FACTOR_RE.match(stripped)
            if m and pending:
                pending['opp_factor'] = float(m.group(1))
                continue
            m = AMBIGUO_RE.match(stripped)
            if m and pending:
                pending['ambiguo'] = True
        if pending:
            rows.append(pending)
    return rows


def load_card_counts(discovery_dir):
    """Carica slug -> {'in_season': n, 'classic': m, 'l10': x|None}, da
    player_card_counts.json. Se il file non esiste (discovery mai lanciata
    dopo l'aggiornamento che ha aggiunto questi campi), ritorna un dict
    vuoto: il chiamante assumera' 1 copia IN_SEASON di default (L10 ignota)
    per ogni giocatore non presente."""
    path = os.path.join(discovery_dir, 'player_card_counts.json')
    if not os.path.exists(path):
        return {}, path
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), path
    except (json.JSONDecodeError, OSError):
        return {}, path


def load_player_names(discovery_dir):
    """Carica slug -> displayName reale Sorare da player_names.json (scritto
    da discovery_fixture.py, 28/07). Se il file non esiste (discovery non
    ancora aggiornata) ritorna {}: il chiamante ripiega sullo slug title-case
    come faceva prima di questa data."""
    path = os.path.join(discovery_dir, 'player_names.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_all_roles():
    role_data = {}
    role_files = {}
    role_counts = {}
    counts_files = {}
    for role, out_dir in ROLES.items():
        path = latest_consiglio(out_dir)
        role_files[role] = path
        role_data[role] = parse_consiglio(path) if path else []

        counts, counts_path = load_card_counts(DISCOVERY_DIRS[role])
        role_counts[role] = counts
        counts_files[role] = counts_path if os.path.exists(counts_path) else None
    return role_data, role_files, role_counts, counts_files


class CardPool:
    """Traccia quante copie IN_SEASON e CLASSIC di ogni giocatore restano
    disponibili, attraverso TUTTE le formazioni generate in questa run
    (di qualunque tipo — In Season, Arena, All Stars condividono lo stesso
    pool). Default: 1 copia IN_SEASON (0 classic, L10 ignota) per uno slug
    non presente nel relativo player_card_counts.json."""

    def __init__(self, counts_by_role, names=None):
        self._total = {}
        self._l10 = {}
        self._power = {}
        # Il ruolo e' una proprieta' della CARTA, non del giocatore: Sorare puo'
        # cambiare ruolo a un giocatore lasciando alle carte gia' emesse quello
        # vecchio. Caso reale (Lee Dong-kyung, Ulsan): 1 classic da centrocampo
        # e 2 in season da attacco. Fondendo i conteggi col solo slug il pool
        # credeva di avere 2 in season utilizzabili anche a centrocampo, e ci
        # schierava una carta d'attacco come MID. Qui si tiene il dettaglio per
        # (slug, ruolo); _total resta la somma, per i punti che non sanno il
        # ruolo e a cui il totale basta.
        self._per_role = {}
        self._used_per_role = {}
        for role, counts in counts_by_role.items():
            for slug, breakdown in counts.items():
                self._per_role[(slug, role)] = {
                    'in_season': breakdown.get('in_season', 0),
                    'classic': breakdown.get('classic', 0)}
                cur = self._total.setdefault(slug, {'in_season': 0, 'classic': 0})
                cur['in_season'] = max(cur['in_season'], breakdown.get('in_season', 0))
                cur['classic'] = max(cur['classic'], breakdown.get('classic', 0))
                l10 = breakdown.get('l10')
                if l10 is not None:
                    # L'L10 e' una proprieta' della CARTA (quindi della coppia
                    # slug+ruolo), non del giocatore: stesso D7 del ruolo qui
                    # sopra. Misurato l'08/08 su 400 carte vere: quando il
                    # ruolo della carta differisce da quello attuale del
                    # giocatore l'L10 cambia fino a 5 punti, in entrambe le
                    # direzioni (jeppe-erenbjerg 62->66, anders-dreyer 66->61).
                    # Qui la chiave resta lo slug, perche' i ~180 chiamanti di
                    # card_pool.l10() in 25 leghe passano solo quello; ma per
                    # uno slug con carte in RUOLI diversi si tiene il valore
                    # PIU' ALTO invece dell'ultimo letto (che era arbitrario,
                    # dipendeva dall'ordine dei ruoli): sul cap arena e' la
                    # scelta prudente, non si sottostima cio' che Sorare
                    # sommera'. Per gli slug a ruolo unico -- la larghissima
                    # maggioranza -- non cambia niente.
                    if slug not in self._l10 or l10 > self._l10[slug]:
                        self._l10[slug] = l10
                power = breakdown.get('power')
                if power is not None:
                    self._power[slug] = power
        self._names = names or {}
        self._used = {}

    def display_name(self, slug):
        """displayName reale Sorare se noto (da player_names.json, vedi
        load_player_names), altrimenti ripiega sullo slug title-case."""
        return self._names.get(slug) or _slug_display_name(slug)

    def _total_for(self, slug):
        # Slug non nei conteggi = mai visto posseduto (bug run 112: player_slugs
        # e player_card_counts disallineati dal merge shard, uno slug puo' finire
        # nei candidati senza una entry di conteggio). Default a 0, non 1: mai
        # schierare un giocatore di cui non c'e' prova di possesso.
        return self._total.get(slug, {'in_season': 0, 'classic': 0})

    def _used_for(self, slug):
        return self._used.get(slug, {'in_season': 0, 'classic': 0})

    def remaining_in_season(self, slug, role=None):
        if role is not None and (slug, role) in self._per_role:
            return (self._per_role[(slug, role)]['in_season']
                    - self._used_per_role.get((slug, role), {}).get('in_season', 0))
        return self._total_for(slug)['in_season'] - self._used_for(slug)['in_season']

    def remaining_classic(self, slug, role=None):
        if role is not None and (slug, role) in self._per_role:
            return (self._per_role[(slug, role)]['classic']
                    - self._used_per_role.get((slug, role), {}).get('classic', 0))
        return self._total_for(slug)['classic'] - self._used_for(slug)['classic']

    def copies_owned(self, slug):
        t = self._total_for(slug)
        return t['in_season'] + t['classic']

    def copies_split(self, slug):
        """Copie possedute divise per tipo (07/08). Il dato c'era gia' in
        _total_for, mancava solo un accessore pubblico: serve alla card per
        dire '2 copie (1 IS + 1 CL)' invece del solo totale."""
        return dict(self._total_for(slug))

    def use(self, slug, card_type, role=None):
        u = self._used.setdefault(slug, {'in_season': 0, 'classic': 0})
        u[card_type] += 1
        if role is not None:
            ur = self._used_per_role.setdefault((slug, role),
                                                {'in_season': 0, 'classic': 0})
            ur[card_type] += 1

    def l10(self, slug):
        """L10 (media ultime 10 partite giocate) nota per slug, o None se
        mai persistita (dato mancante -- vedi ARENA_L10_CAP, trattata come 0
        nel calcolo del budget, mai come esclusione)."""
        return self._l10.get(slug)

    def set_l10(self, slug, valore):
        """Fissa l'L10 di uno slug (usato dal top-up del generatore che la
        recupera dall'API player-level quando la discovery non l'ha
        persistita). L'L10 e' un campo Sorare sempre esposto: un buco qui
        faceva contare 0 quel giocatore nel cap arena, sforando il tetto."""
        if valore is not None:
            self._l10[slug] = valore

    def power_bonus_fraction(self, slug):
        """Somma dei basis points del powerBreakdown Sorare (season/collection/
        xp/scarcity/special edition/active clubs/nationality/positions) per
        slug, come frazione (es. 1000 basis points -> 0.10). 0.0 se il dato
        non e' stato raccolto (giocatore mai visto in una CARDS_QUERY, o
        senza carta con bonus noto) -- MAI un'esclusione, solo nessun
        moltiplicatore extra. Il chiamante decide se applicarla (28/07:
        SOLO In Season/All Stars 7/Under 23, mai nelle Arene, confermato
        dall'utente -- vedi XP_BONUS_TYPES in build_formazione_globale.py)."""
        pb = self._power.get(slug)
        if not pb:
            return 0.0
        return sum(v or 0 for k, v in pb.items() if k.endswith('_bp')) / 10000.0

    def used_slugs(self):
        """Slug con almeno una copia consumata in una qualunque formazione
        di questa run (di qualunque tipo -- il pool e' condiviso)."""
        return {slug for slug, u in self._used.items()
                if u['in_season'] > 0 or u['classic'] > 0}


def _min_available_l10(rows, used_slugs, card_pool):
    """Minimo L10 (mancante trattato come 0.0, permissivo) tra i candidati di
    'rows' NON ancora usati in questa lineup -- usato per riservare budget ai
    prossimi slot quando l10_cap e' attivo (27/07, fix di un difetto reale:
    senza riserva, i primi slot potevano spendere tutto il budget sui
    punteggi migliori, lasciando lo slot EXTRA finale sempre sforato perche'
    mai processato con budget residuo garantito)."""
    vals = [card_pool.l10(r['slug']) or 0.0 for r in rows if r['slug'] not in used_slugs]
    return min(vals) if vals else 0.0


def _pareto_frontier(rows, card_pool, role=None):
    """Candidati disponibili (almeno una copia posseduta) ordinati per L10
    crescente, tenendo solo quelli che migliorano il punteggio rispetto a
    TUTTI i candidati piu' economici gia' inclusi (frontiera di Pareto: mai
    utile scegliere un candidato piu' caro E con punteggio minore o uguale a
    uno gia' disponibile). Riduce drasticamente lo spazio di ricerca del
    knapsack sotto senza perdere nessuna soluzione ottima possibile."""
    avail = [(row, card_pool.l10(row['slug']) or 0.0) for row in rows
             if card_pool.remaining_in_season(row['slug'], role) > 0
             or card_pool.remaining_classic(row['slug'], role) > 0]
    avail.sort(key=lambda x: x[1])
    frontier = []
    best = float('-inf')
    for row, l10 in avail:
        if row['atteso'] > best:
            frontier.append((row, l10))
            best = row['atteso']
    return frontier


def _optimize_capped_lineup(shape, role_data, card_pool, l10_cap):
    """Knapsack ESATTO sui 4 slot principali (GK/DEF/MID/FWD, un candidato
    ciascuno) per massimizzare il PUNTEGGIO TOTALE sotto l10_cap (27/07,
    richiesta esplicita utente: la vecchia euristica greedy-con-riserva
    rispettava il cap ma si accontentava della prima combinazione che
    entrava nel budget, non della migliore -- risultato: extra con punteggio
    anche di 14-26pt quando ne esistevano di molto migliori nello stesso
    budget). Prova OGNI possibile ripartizione di budget tra i 4 ruoli
    principali E lo slot EXTRA (miglior punteggio disponibile nel budget
    residuo, tra tutti i ruoli ammessi, mai lo stesso giocatore gia' scelto),
    non solo quella che spende piu' budget sui primi 4 -- cosi' trova il vero
    massimo del totale a 5 slot. SOLO valido per shape con un ruolo per slot
    (nessuna ripetizione, es. Arena) e max_classic=None (vero per tutti i
    tipi con cap L10 oggi, mai per In Season/All Stars che non hanno cap).
    Non incorpora i nudge di sinergia da correlazione (piccoli, +3/+11 --
    qui l'obiettivo e' il punteggio reale, non l'ordine di scelta). Ritorna
    (picks_dict {ruolo/EXTRA: row}, l10_totale) o (None, None) se nessuna
    combinazione e' possibile (pool esaurito per almeno un ruolo)."""
    # R3/P4 (passaggio 2, fix reale: formazione non schierabile, L10 261.1 su
    # cap 260 in produzione). CAUSA: `int(round(l10 * RES))` arrotonda ogni
    # L10 al piu' vicino decimo PRIMA di sommarlo -- puo' arrotondare per
    # DIFETTO fino a 0.05 per carta, quindi fino a 0.25 sulle 5 carte. Il
    # budget discretizzato (budget_units) accettava percio' combinazioni la
    # cui somma REALE (non arrotondata) superava l10_cap, senza che il knapsack
    # se ne accorgesse -- e il ramo che lo chiama (build_one_lineup) segnava
    # SEMPRE l10_cap_rispettato=True per questo percorso, nessun controllo a
    # valle. FIX in due parti, mai una sola:
    # 1. i costi si arrotondano per ECCESSO (math.ceil), mai per difetto: ogni
    #    cost_i e' un limite superiore garantito del vero l10_i*RES, quindi
    #    "sum(cost_i) <= budget_units" implica "sum(l10_i) <= l10_cap" con
    #    certezza aritmetica, non per approssimazione. Il budget stesso si
    #    arrotonda per DIFETTO (math.floor), stessa direzione conservativa.
    # 2. la somma L10 REALE (non discretizzata) di ogni combinazione candidata
    #    viene ricalcolata e riverificata <= l10_cap prima di accettarla come
    #    "best": la prima parte del fix la rende ridondante nel caso comune,
    #    ma e' la garanzia che conta, non un'euristica in piu' (vedi CLAUDE.md,
    #    non dedurre per differenza: qui si VERIFICA il vincolo vero, non si
    #    assume che il proxy discretizzato l'abbia gia' rispettato).
    # L'eps (1e-9) serve solo a non far scattare ceil/floor per rumore in
    # virgola mobile su valori gia' esatti (es. 26.0 * 10 = 260.00000000001).
    RES = 10  # risoluzione: decimi di L10, gestisce valori con 1 decimale
    EPS = 1e-9
    budget_units = int(math.floor(l10_cap * RES + EPS))

    # Tie-break starter odds (P5/passaggio 2, B07): la regola "a parita' di
    # atteso, si preferisce quello con starter odds piu' alta" (decisione
    # utente: TIE-BREAK, non bonus additivo, tolleranza 1 punto pieno di
    # atteso) non arrivava MAI qui -- il knapsack ottimizzava solo
    # row['atteso'] puro, ignorando l'ordine del percorso greedy (dove vive
    # _sort_ordinamento in build_formazione_globale.py). Non serve un bucket a
    # griglia fissa qui: ad ogni cella di budget si confrontano ESATTAMENTE
    # due candidati (il nuovo e l'occupante attuale), quindi un confronto
    # pairwise diretto sulla distanza e' corretto e non ha il problema di
    # transitivita' che riguarda l'ordinamento di una LISTA (vedi commento
    # in build_formazione_globale.py su _sort_ordinamento) -- qui non si sta
    # costruendo un ordine, solo decidendo un vincitore alla volta.
    PREFERENZA_ODDS_TOLLERANZA = float(os.environ.get('PREFERENZA_ODDS_TOLLERANZA', '1.0'))

    def _vince_su(ns, odds_ns, score_cur, odds_cur):
        """True se il candidato 'ns/odds_ns' deve sostituire l'occupante
        attuale 'score_cur/odds_cur' nella stessa cella di budget."""
        if abs(ns - score_cur) <= PREFERENZA_ODDS_TOLLERANZA:
            if (odds_ns or 0.0) != (odds_cur or 0.0):
                return (odds_ns or 0.0) > (odds_cur or 0.0)
            return ns > score_cur
        return ns > score_cur

    frontiers = {}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        f = _pareto_frontier(role_data[role], card_pool, role)
        if not f:
            return None, None
        frontiers[role] = f

    # states[nb] = (score, picks, l10_reale_totale) -- l10_reale_totale e' la
    # somma NON arrotondata dei l10 scelti finora, portata avanti a parte dal
    # proxy discretizzato (nb) usato solo per la ricerca del budget.
    states = {0: (0.0, {}, 0.0)}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        new_states = {}
        for used, (score, picks, l10_reale) in states.items():
            # un giocatore non puo' stare due volte nella stessa formazione,
            # nemmeno con carte di ruolo diverso (regola Sorare). Qui mancava:
            # il controllo c'era solo sullo slot EXTRA.
            gia_scelti = {r['slug'] for r in picks.values()}
            for row, l10 in frontiers[role]:
                if row['slug'] in gia_scelti:
                    continue
                cost = int(math.ceil(l10 * RES - EPS))
                nb = used + cost
                if nb > budget_units:
                    continue
                ns = score + row['atteso']
                cur = new_states.get(nb)
                if cur is None:
                    vince = True
                else:
                    cur_odds = cur[1].get(role, {}).get('starter_odds')
                    vince = _vince_su(ns, row.get('starter_odds'), cur[0], cur_odds)
                if vince:
                    new_picks = dict(picks)
                    new_picks[role] = row
                    new_states[nb] = (ns, new_picks, l10_reale + l10)
        if not new_states:
            return None, None
        states = new_states

    extra_candidates = []
    for role in shape['extra_roles']:
        for row, l10 in _pareto_frontier(role_data[role], card_pool, role):
            extra_candidates.append((role, row, l10))

    best_total = best_picks = best_extra = best_used = None
    for used, (score4, picks4, l10_reale4) in states.items():
        used_slugs = {row['slug'] for row in picks4.values()}
        # Candidati che rientrano DAVVERO nel vincolo vero per questo budget
        # residuo (verifica sulla somma reale, non sul discretizzato -- stessa
        # garanzia (2) del fix R3/P4, indipendente dall'arrotondamento sopra).
        fittanti = [(role, row, l10) for role, row, l10 in extra_candidates
                    if row['slug'] not in used_slugs
                    and l10_reale4 + l10 <= l10_cap + EPS]
        if not fittanti:
            continue
        # Tie-break odds (P5/B07): ancorato al MIGLIOR atteso fra i fittanti,
        # non a una griglia fissa -- fra chi sta entro PREFERENZA_ODDS_
        # TOLLERANZA da quel massimo, vince chi ha odds piu' alte. Un solo
        # slot da scegliere qui (non un ordinamento di lista): nessun
        # problema di transitivita'.
        migliore_atteso = max(row['atteso'] for _r, row, _l in fittanti)
        vicini = [c for c in fittanti
                  if c[1]['atteso'] >= migliore_atteso - PREFERENZA_ODDS_TOLLERANZA]
        role, row, l10 = max(vicini, key=lambda c: (
            c[1].get('starter_odds') or 0.0, c[1]['atteso']))
        l10_reale_totale = l10_reale4 + l10
        total = score4 + row['atteso']
        if best_total is None or total > best_total:
            best_total = total
            best_picks = picks4
            best_extra = (role, row, l10)
            best_used = l10_reale_totale

    if best_picks is None:
        return None, None

    result = dict(best_picks)
    result['EXTRA'] = (best_extra[0], best_extra[1])
    return result, best_used


def _consume_pick(card_pool, slug, role=None):
    """Consuma una copia dello slug scelto dal knapsack: preferisce IN_SEASON
    se disponibile (stesso ordine di preferenza del vecchio greedy 'pick'),
    altrimenti CLASSIC -- valido solo dove max_classic e' None (unico caso in
    cui il knapsack e' applicabile, vedi build_one_lineup)."""
    if card_pool.remaining_in_season(slug, role) > 0:
        card_pool.use(slug, 'in_season', role)
        return 'in_season'
    card_pool.use(slug, 'classic', role)
    return 'classic'


def build_one_lineup(shape, role_data, card_pool, l10_cap=None, apply_stack_guard=False, variance_mode=False,
                      apply_positive_synergy=True, strict_gk_anti_synergy=False, used_matches=None,
                      synergy_bonus_dict=None):
    """Costruisce UNA formazione secondo 'shape' (uno dei FORMATION_SHAPES),
    tenendo conto delle copie gia' esaurite (card_pool) e del vincolo
    max_classic della shape (None = nessun vincolo). Se l10_cap e' impostato
    (SOLO Arena), sceglie ad ogni slot il miglior punteggio che rientra nel
    budget residuo MENO una riserva (somma dei minimi L10 disponibili per gli
    slot ancora da riempire, extra incluso) -- garantisce che il cap non
    venga MAI sforato: se a un certo slot nessun candidato rientra nemmeno
    riservando, la formazione fallisce con lo stesso errore di "candidato
    esaurito", nessun fallback che sfora in silenzio (27/07, fix di un
    difetto reale: prima i primi slot potevano spendere tutto il budget sui
    punteggi migliori, lasciando lo slot EXTRA finale sempre sforato).
    'apply_stack_guard' (SOLO In Season/All Stars, vedi
    commento sopra IN_SEASON_STACK_LIMIT): scoraggia (non vieta) il 3o
    giocatore della stessa squadra nello slot extra, per non perdere per
    errore il bonus anti-stack Sorare. 'variance_mode' (SOLO Arena/All Stars,
    vedi commento sopra SAME_TEAM_SYNERGY_BONUS_BY_PAIR): rafforza la
    sinergia GK-DEF e aggiunge nudge GK-MID/DEF-MID/DEF-DEF basati sulla
    correlazione misurata. Ritorna (formazione, errore, l10_cap_rispettato,
    stack_bonus_perso); formazione e' una lista di tuple
    (slot_label, row, card_type). stack_bonus_perso e' True se la
    formazione finale ha comunque 3+ giocatori della stessa squadra
    (informativo, sempre False se apply_stack_guard=False).

    'apply_positive_synergy' / 'strict_gk_anti_synergy' (27/07, richiesta
    esplicita utente per le In Season con 2+ formazioni richieste): quando
    strict_gk_anti_synergy=True, i candidati MID/FWD della squadra
    AVVERSARIA del portiere vengono ESCLUSI del tutto (non solo
    deprioritizzati) da ogni slot (titolari ed extra) -- un vero vincolo di
    schieramento, mai piu' un'ultima risorsa. apply_positive_synergy=False
    disattiva anche il bonus soft DEF-GK (nessuna priorita' di sinergia,
    solo punteggio grezzo) -- usato per le formazioni "greedy" successive
    alla prima quando le In Season richieste sono 2+ (vedi
    generate_lineups_for_type). Con una sola In Season richiesta, o per
    Arena/All Stars, entrambi i flag restano ai default (comportamento
    INVARIATO rispetto a prima di questa modifica).

    Se il knapsack ESATTO e' applicabile (l10_cap impostato, un ruolo per
    slot senza ripetizioni, max_classic=None, nessuna sinergia da applicare
    -- vero oggi per le 3 Arene dedicate, MAI per In Season/All Stars che o
    non hanno cap o ripetono ruoli), lo usa al posto del vecchio greedy-con-
    riserva per il punteggio totale MASSIMO garantito sotto il cap (27/07,
    vedi _optimize_capped_lineup). Decisione presa con l'utente (27/07): il
    knapsack NON incorpora MAI i nudge di sinergia, anche se variance_mode=
    True viene passato (oggi lo e' sempre per le Arene, incluse quelle a
    cap) -- il cap L10 e' un vincolo duro con poco margine, l'utente ha
    scelto di privilegiare il punteggio grezzo massimo sotto quel vincolo
    piuttosto che un DP annidato che preservi anche la sinergia.
    apply_stack_guard e' invece sempre False per questi tipi oggi (mai
    passato True insieme a un l10_cap), quindi non c'e' scelta da fare li'."""
    role_slots = shape['role_slots']
    max_classic = shape['max_classic']
    can_use_knapsack = (
        l10_cap is not None
        and max_classic is None
        and not apply_stack_guard
        and len(role_slots) == len(set(role_slots))
        and set(role_slots) == {'GK', 'DEF', 'MID', 'FWD'}
    )
    if can_use_knapsack:
        result, _l10_total = _optimize_capped_lineup(shape, role_data, card_pool, l10_cap)
        if result is None:
            return (None,
                    "Nessun candidato disponibile per completare la formazione entro il cap L10 "
                    "(copie esaurite o pool insufficiente).",
                    True, False)
        picks = []
        for role in role_slots:
            row = result[role]
            ctype = _consume_pick(card_pool, row['slug'], role)
            picks.append((role, row, ctype))
        extra_role, extra_row = result['EXTRA']
        extra_ctype = _consume_pick(card_pool, extra_row['slug'], extra_role)
        picks.append((f'EXTRA ({extra_role})', extra_row, extra_ctype))
        return picks, None, True, False

    # Ottimizzazione allocazione classic (28/07, bug reale trovato dall'utente:
    # Carles Gil, 70pt, restava fuori perche' il difensore -- 63pt -- aveva
    # gia' "preso" l'unico slot classic disponibile per la formazione, solo
    # perche' processato prima nell'ordine fisso GK->DEF->MID->FWD. Il
    # vincolo "max 1 classic per formazione" e' giusto, ma va assegnato allo
    # slot che ne guadagna di piu', non al primo che lo richiede. Con
    # max_classic finito (oggi sempre 1, solo In Season), si esegue prima
    # una passata "base" a classic disattivato ovunque per misurare, slot per
    # slot, quanto varrebbe abilitare il classic PROPRIO li' (differenza di
    # punteggio col miglior candidato in_season-only) -- poi si rifa' la
    # passata vera abilitando il classic solo nello slot che ne trae il
    # massimo guadagno. Con max_classic=None (Arena/All Stars) il classic e'
    # illimitato, questa ottimizzazione non serve e non si attiva.
    def _run(allow_classic_slot, measure_gains=False):
        used_this_lineup = set()
        classic_budget_used = [0]
        l10_used = [0.0]
        l10_cap_rispettato = [True]
        team_counts = {}
        gains = {}
        picks = []
        # con quale ruolo e' stata scelta ogni carta: serve a consumare la
        # copia giusta, visto che le copie dipendono dal ruolo della carta
        ruolo_scelto = {}

        def _forza_stimata():
            """Quanto forte sta venendo la formazione, proiettata a 5 slot.

            Serve a scalare i bonus di sinergia: la varianza vale 0.78 punti
            per punto sotto il pareggio e 0.31 sopra, quindi un bonus fisso e'
            giusto in media e sbagliato agli estremi. Con meno di due slot
            scelti non c'e' abbastanza per stimare e si resta al valore tarato.
            """
            scelti = [r for _s, r, _c in picks]
            if len(scelti) < 2:
                return None
            n_slot = len(shape['role_slots']) + 1
            forza = sum(r['atteso'] for r in scelti) * n_slot / len(scelti)
            if FORZA_NORM:
                # riportata alla scala su cui _CAMBIO_DISPERSIONE e' misurata
                forza *= SLOT_RIFERIMENTO / n_slot
            return forza


        def pick(pool_rows, role_slot_l10_check, reserve=0.0, slot_label=None,
                 role_by_slug=None):
            # role_by_slug: da quale pool di ruolo arriva ogni riga. Serve perche'
            # le copie disponibili dipendono dal ruolo della carta, non solo dal
            # giocatore (vedi CardPool). Per lo slot EXTRA le righe vengono da
            # ruoli diversi, quindi e' una mappa e non un ruolo solo.
            def _ruolo(slug):
                return (role_by_slug or {}).get(slug)

            candidates = [r for r in pool_rows if r['slug'] not in used_this_lineup]
            if l10_cap is not None and role_slot_l10_check:
                budget_residuo = l10_cap - l10_used[0] - reserve
                candidates = [r for r in candidates if (card_pool.l10(r['slug']) or 0.0) <= budget_residuo]

            slot_allows_classic = (max_classic is None) or (allow_classic_slot == '__ANY__') or (allow_classic_slot is not None and slot_label == allow_classic_slot)
            best_in_season = best_classic = None
            for row in candidates:
                slug = row['slug']
                if best_in_season is None and card_pool.remaining_in_season(slug, _ruolo(slug)) > 0:
                    best_in_season = row
                if best_classic is None and card_pool.remaining_classic(slug, _ruolo(slug)) > 0:
                    best_classic = row
                if best_in_season is not None and (best_classic is not None or not measure_gains):
                    break
            if measure_gains and slot_label is not None and max_classic is not None:
                # Guadagno di abilitare il classic PROPRIO in questo slot,
                # tenendo tutti gli altri slot fissi a in_season-only: e' la
                # differenza fra il miglior candidato classic disponibile e il
                # miglior candidato in_season disponibile per QUESTO slot.
                #
                # FIX (29/07, bug reale trovato dall'utente: Carles Gil classic
                # -- 61pt -- restava fuori da una lineup dove NESSUNO slot
                # aveva usato il budget classic, con Pep Biel -- 55pt -- e
                # Mathias Laborda -- 53pt -- schierati al suo posto). Prima si
                # confrontava `best_classic` con `candidates[0]` (il candidato
                # dal punteggio piu' alto in assoluto, IGNORANDO se ha ancora
                # copie disponibili): appena il candidato #1 di un ruolo
                # risultava esaurito da una lineup precedente (frequente dalla
                # 5a/6a lineup di un portafoglio in poi), `top is best_classic`
                # falliva quasi sempre anche quando il miglior classic
                # disponibile (es. Sebastian Berhalter, 2 copie classic mai
                # esaurite) valeva chiaramente piu' del miglior in_season
                # disponibile -- azzerando il gain di quello slot per un
                # confronto con un giocatore ormai fuori pool, non con
                # l'alternativa in_season reale. Il confronto corretto e'
                # semplicemente best_classic vs best_in_season, senza scomodare
                # candidates[0].
                if best_in_season is not None and best_classic is not None:
                    if best_classic is not best_in_season:
                        gains[slot_label] = best_classic['atteso'] - best_in_season['atteso']
                    else:
                        gains[slot_label] = 0
                elif best_in_season is None and best_classic is not None:
                    # nessun candidato in_season disponibile: il classic e'
                    # OBBLIGATORIO per riempire questo slot, priorita' massima.
                    gains[slot_label] = float('inf')
                else:
                    gains[slot_label] = 0
            if slot_allows_classic:
                for row in candidates:
                    slug = row['slug']
                    if card_pool.remaining_in_season(slug, _ruolo(slug)) > 0:
                        return row, 'in_season'
                    if (max_classic is None or classic_budget_used[0] < max_classic) and card_pool.remaining_classic(slug, _ruolo(slug)) > 0:
                        return row, 'classic'
                return None, None
            else:
                return (best_in_season, 'in_season') if best_in_season is not None else (None, None)

        gk_team_slug = gk_opponent_slug = None
        # Ruoli gia' scelti per squadra (28/07, estensione anti-sinergia
        # cross-team -- vedi CROSS_TEAM_PENALTY_BY_PAIR): a differenza di
        # gk_team_slug/gk_opponent_slug (solo il portiere), qui si accumula la
        # squadra di OGNI giocatore gia' piazzato, per penalizzare candidati la
        # cui squadra e' avversaria di una gia' scelta in una coppia di ruoli
        # confermata negativa (non solo GK-vs-attaccante).
        chosen_roles_by_team = {}

        role_slot_counts = {}
        for role in shape['role_slots']:
            role_slot_counts[role] = role_slot_counts.get(role, 0) + 1
        role_occurrence = {role: 0 for role in role_slot_counts}

        for slot_idx, role in enumerate(shape['role_slots']):
            role_occurrence[role] += 1
            slot_label = role if role_slot_counts[role] == 1 else f"{role}{role_occurrence[role]}"

            reserve = 0.0
            if l10_cap is not None:
                reserve = sum(_min_available_l10(role_data[r], used_this_lineup, card_pool)
                              for r in shape['role_slots'][slot_idx + 1:])
                reserve += _min_available_l10(
                    [row for r in shape['extra_roles'] for row in role_data[r]], used_this_lineup, card_pool)

            if role == 'GK':
                gk_candidates = role_data['GK']
                if used_matches or chosen_roles_by_team:
                    gk_candidates = synergy_adjusted_rows(role, gk_candidates, None, None, used_matches=used_matches,
                                                           apply_positive_synergy=apply_positive_synergy,
                                                           chosen_roles_by_team=chosen_roles_by_team)
                row, ctype = pick(gk_candidates, l10_cap is not None, reserve, slot_label=slot_label,
                                  role_by_slug={r['slug']: 'GK' for r in gk_candidates})
            else:
                pool_rows = role_data[role]
                if strict_gk_anti_synergy and role in ('MID', 'FWD') and gk_opponent_slug:
                    pool_rows = [r for r in pool_rows if r.get('team_slug') != gk_opponent_slug]
                candidates = synergy_adjusted_rows(role, pool_rows, gk_team_slug, gk_opponent_slug,
                                                    team_counts, apply_stack_guard, variance_mode,
                                                    apply_positive_synergy, used_matches, chosen_roles_by_team,
                                                    synergy_bonus_dict, forza_attesa=_forza_stimata())
                row, ctype = pick(candidates, l10_cap is not None, reserve, slot_label=slot_label,
                                  role_by_slug={r['slug']: role for r in candidates})

            if row is None:
                reason = ("vincolo di schieramento (portiere vs avversario) + copie esaurite o consiglio vuoto"
                          if strict_gk_anti_synergy else "copie esaurite o consiglio vuoto")
                return None, f"Nessun candidato disponibile per lo slot {slot_label} ({reason}).", l10_cap_rispettato[0], False, gains

            used_this_lineup.add(row['slug'])
            if ctype == 'classic':
                classic_budget_used[0] += 1
            if l10_cap is not None:
                l10_used[0] += card_pool.l10(row['slug']) or 0.0
            picks.append((slot_label, row, ctype))
            ruolo_scelto[row['slug']] = role

            row_team_slug = row.get('team_slug')
            if row_team_slug:
                team_counts[row_team_slug] = team_counts.get(row_team_slug, 0) + 1
                # Contatore per ruolo (FIX 28/07), non set: 2 compagni DEF gia'
                # scelti devono contare 2x nel bonus/penalita', non 1x.
                _team_roles = chosen_roles_by_team.setdefault(row_team_slug, {})
                _team_roles[role] = _team_roles.get(role, 0) + 1

            if role == 'GK':
                gk_team_slug = row.get('team_slug')
                gk_opponent_slug = row.get('opponent_team_slug')

        # Extra: il migliore rimanente tra i ruoli ammessi dalla shape (esclusi i
        # titolari di QUESTA lineup, le copie gia' esaurite, e rispettando
        # classic_budget/l10_cap), a prescindere dal ruolo specifico -- stessa
        # sinergia/anti-sinergia applicata anche qui.
        combined = []
        for role in shape['extra_roles']:
            for row in role_data[role]:
                if (strict_gk_anti_synergy and role in ('MID', 'FWD') and gk_opponent_slug
                        and row.get('team_slug') == gk_opponent_slug):
                    continue
                combined.append((role, row))
        # forza_attesa allo slot EXTRA (04/08, sotto FORZA_NORM): e' l'unico
        # slot che non la passava, e paradossalmente quello dove la stima e'
        # piu' affidabile -- qui i titolari sono TUTTI gia' scelti, non due.
        _forza_extra = _forza_stimata() if FORZA_NORM else None
        combined.sort(key=lambda rc: synergy_sort_key(rc[0], rc[1], gk_team_slug, gk_opponent_slug,
                                                        team_counts, apply_stack_guard, variance_mode,
                                                        apply_positive_synergy, used_matches,
                                                        chosen_roles_by_team, synergy_bonus_dict,
                                                        forza_attesa=_forza_extra), reverse=True)

        extra_rows = [row for _role, row in combined]
        extra_role_by_slug = {row['slug']: role for role, row in combined}
        extra_row, extra_type = pick(extra_rows, l10_cap is not None, 0.0, slot_label='EXTRA',
                                     role_by_slug=extra_role_by_slug)

        if extra_row is None:
            reason = "vincolo di schieramento (portiere vs avversario) + copie esaurite" if strict_gk_anti_synergy else "copie esaurite"
            return None, f"Nessun candidato disponibile per lo slot extra ({reason}).", l10_cap_rispettato[0], False, gains

        extra_role = extra_role_by_slug[extra_row['slug']]
        picks.append((f'EXTRA ({extra_role})', extra_row, extra_type))
        ruolo_scelto[extra_row['slug']] = extra_role

        extra_team_slug = extra_row.get('team_slug')
        if extra_team_slug:
            team_counts[extra_team_slug] = team_counts.get(extra_team_slug, 0) + 1

        if not measure_gains:
            for _slot, row, ctype in picks:
                card_pool.use(row['slug'], ctype, ruolo_scelto.get(row['slug']))

        stack_bonus_perso = apply_stack_guard and any(c >= 3 for c in team_counts.values())
        return picks, None, l10_cap_rispettato[0], stack_bonus_perso, gains

    if max_classic is None:
        picks, error, l10_ok, stack_perso, _gains = _run(allow_classic_slot=None)
        return picks, error, l10_ok, stack_perso

    # Passata di misura (28/07, fix allocazione classic): nessuno slot puo'
    # usare il classic, ma per ognuno si registra quanto varrebbe abilitarlo
    # li' (gains dict). Non consuma il card_pool (measure_gains=True).
    _baseline_picks, baseline_error, _l10_ok, _stack, gains = _run(allow_classic_slot=None, measure_gains=True)
    if baseline_error:
        # Nessuna combinazione e' possibile senza classic da NESSUNA parte:
        # fallback al comportamento storico (classic al primo slot che lo
        # richiede, ordine fisso) -- meglio una formazione completa che
        # nessuna formazione.
        picks, error, l10_ok, stack_perso, _gains = _run(allow_classic_slot='__ANY__')
        return picks, error, l10_ok, stack_perso

    winner_slot = max(gains, key=gains.get) if gains else None
    if winner_slot is None or gains.get(winner_slot, 0) <= 0:
        # Nessuno slot trae beneficio dal classic: la passata base (tutta
        # in_season) e' gia' la migliore, ma non e' stata consumata sul
        # card_pool -- rifarla con measure_gains=False per il consumo reale.
        picks, error, l10_ok, stack_perso, _gains = _run(allow_classic_slot=None)
        return picks, error, l10_ok, stack_perso

    picks, error, l10_ok, stack_perso, _gains = _run(allow_classic_slot=winner_slot)
    return picks, error, l10_ok, stack_perso


# Bonus capitano NON uniforme tra i tipi di formazione (verificato dall'utente
# il 26/07/2026 su casi reali Sorare): in Arena il capitano riceve solo +20%,
# non +50% come In Season/All Stars.
CAPTAIN_BONUS_BY_TYPE = {
    'IN_SEASON': 0.5,
    'ARENA_260': 0.2,
    'ARENA_220': 0.2,
    'ARENA_UNCAPPED': 0.2,
    'ALLSTARS': 0.5,
}

# Bonus "Cap 260" (SOLO In Season, 26/07 -- verificato dall'utente con screenshot
# reali della UI Sorare, pannello "BONUS FORMAZIONE"): se la somma delle L10 dei
# 5 titolari e' <= 260, si ottiene un +4% aggiuntivo su tutte le carte della
# formazione (si somma ad altri bonus formazione come "Multi-club", non ancora
# implementato/verificato del tutto -- vedi RIASSUNTO). E' una metrica DIVERSA
# dal cap L10 obbligatorio di Arena (ARENA_L10_CAP): li' e' un vincolo di
# formato che filtra le scelte durante la costruzione; qui e' solo INFORMATIVO
# (fase 1, rilevamento passivo) -- si limita a segnalare se la formazione gia'
# scelta (ottimizzata per punteggio atteso, nessun vincolo L10 attivo per
# In Season) rientra o no sotto la soglia, senza cercare attivamente
# un'alternativa che la rispetti. Nessun impatto sul totale numerico mostrato
# (stesso trattamento "solo informativo" gia' usato per il bonus anti-stack).
CAP260_BONUS = 0.04
# Soglia L10 per il bonus, per tipo (26/07 -- confermato dall'utente che il
# bonus esiste ANCHE per All Stars, non solo In Season, con soglia scalata a
# 7 giocatori invece di 5: 370 invece di 260, stessa % +4%).
CAP260_L10_THRESHOLD_BY_TYPE = {'IN_SEASON': 260.0, 'ALLSTARS': 370.0}


# Margine minimo di punteggio atteso che un portiere deve superare rispetto
# al migliore giocatore di movimento per convenire come capitano (27/07,
# richiesta esplicita utente, confermata con dati reali via
# formazione_mls/diagnostics/analyze_gk_captain_value.py -- NESSUNA nuova
# query, solo cache di calibrazione gia' su disco). Ricalibrato lo stesso
# giorno estendendo lo script a 10 campionati (MLS, K League, Brasile,
# Croazia, Portogallo, Austria, Scozia, Belgio, Olanda, Spagna): 404 partite
# GK (quasi 3x il campione precedente di 149 GK / 1673 movimento
# MLS+K League) confermano la stessa direzione con stima piu' precisa. Il
# bonus capitano e' una percentuale del punteggio REALE ottenuto (non
# dell'atteso), quindi scegliere il capitano solo in base all'atteso grezzo
# e' ottimale SOLO se l'atteso e' calibrato allo stesso modo tra ruoli --
# non lo e': nella fascia di punteggio atteso rilevante per la scelta
# capitano (>=55, dove tipicamente si gioca la decisione), il bias di
# calibrazione (reale - atteso) e' -12.06pt per i portieri contro -5.37pt
# per il movimento -- un divario di 6.69pt, coerente con l'esperienza
# dell'utente su Sorare ("basta un gol subito per perdere il bonus clean
# sheet, i portieri hanno punteggi tendenzialmente piu' bassi") anche se lui
# stesso non l'aveva mai verificato sui dati. A parita' o quasi di atteso
# nominale, il portiere realizza in media MENO del giocatore di movimento:
# un margine fisso corregge la scelta senza dover ricalibrare l'intera
# formula solo per la selezione capitano.
GK_CAPTAIN_MARGIN = 6.7


def pick_captain(formazione, avoid_slugs=None):
    """B09 (P7, passaggio 2, SOLO documentale -- nessuna modifica di massa
    senza chiedere all'utente): questa versione (CON GK_CAPTAIN_MARGIN e la
    regola GK/movimento) e' quella DI PRODUZIONE -- il generatore globale
    (generatore_formazioni/build_formazione_globale.py) importa SOLO
    formazione_mls. Le 52 copie per-lega in formazione_<lega>/
    build_formazione_finale.py:pick_captain NON hanno questa regola (versione
    piu' vecchia, 1182 righe contro 2349): qualunque run per-lega STANDALONE
    (fuori dal generatore globale) sceglie un capitano diverso, senza errore
    visibile. Non sono allineate da propaga_modello.py (che copre solo
    predict/test_*.py, non build_formazione_finale.py).

    Il capitano ottimale sarebbe, in puro valore atteso, il giocatore con
    lo score atteso piu' alto della formazione (il bonus e' una percentuale
    del punteggio REALE di quel giocatore, quindi massimizzare l'atteso
    massimizza il bonus atteso) -- MA questo vale solo se l'atteso e'
    calibrato allo stesso modo tra ruoli. Non lo e' per i portieri (vedi
    GK_CAPTAIN_MARGIN sopra): un portiere diventa capitano solo se il suo
    atteso supera quello del miglior giocatore di movimento di almeno
    GK_CAPTAIN_MARGIN punti, altrimenti vince il movimento anche se il
    portiere ha un atteso nominale piu' alto (ma non abbastanza).
    'avoid_slugs' (27/07, richiesta esplicita utente: varianza capitano tra
    piu' formazioni della STESSA competizione/tipo, quando esistono 2+ copie
    di una carta che permettono di riusarla in piu' lineup): se fornito,
    preferisce il punteggio piu' alto TRA i titolari non ancora capitanati in
    questo tipo; se sono gia' stati capitanati tutti (nessuna alternativa),
    ripiega sul pool completo -- mai un peggioramento del punteggio atteso
    solo per la varianza, la logica GK/movimento resta comunque applicata."""
    candidates = formazione
    if avoid_slugs:
        filtered = [p for p in formazione if p[1]['slug'] not in avoid_slugs]
        if filtered:
            candidates = filtered

    outfield = [p for p in candidates if p[0] != 'GK']
    if not outfield:
        return max(candidates, key=lambda p: p[1]['atteso'])
    best_outfield = max(outfield, key=lambda p: p[1]['atteso'])

    gk = [p for p in candidates if p[0] == 'GK']
    if not gk:
        return best_outfield
    best_gk = max(gk, key=lambda p: p[1]['atteso'])

    if best_gk[1]['atteso'] >= best_outfield[1]['atteso'] + GK_CAPTAIN_MARGIN:
        return best_gk
    return best_outfield


def format_lineup(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True,
                   stack_bonus_perso=False, check_cap260=False, tipo=None, apply_stack_guard=False,
                   avoid_captain_slugs=None):
    lines = []
    lines.append(f"--- Formazione {tipo_label} #{idx} ---")
    captain_slot, captain_row, _captain_type = pick_captain(formazione, avoid_captain_slugs)
    totale_atteso = totale_low = totale_high = 0
    totale_l10 = 0.0
    for slot, row, ctype in formazione:
        tag = " [CLASSIC]" if ctype == 'classic' else ""
        copie = card_pool.copies_owned(row['slug'])
        nota_copie = f" ({copie} copie possedute)" if copie > 1 else ""
        cap_tag = " [C]" if row['slug'] == captain_row['slug'] else ""
        lines.append(f"{slot:<12} {row['slug']}: {row['atteso']} pt ({row['low']}-{row['high']}){tag}{nota_copie}{cap_tag}")
        totale_atteso += row['atteso']
        totale_low += row['low']
        totale_high += row['high']
        totale_l10 += card_pool.l10(row['slug']) or 0.0

    captain_bonus_pct = CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5)
    bonus = round(captain_row['atteso'] * captain_bonus_pct)
    totale_con_capitano = totale_atteso + bonus
    lines.append(f"TOTALE: {totale_atteso} pt ({totale_low}-{totale_high})")
    lines.append(f"CAPITANO CONSIGLIATO: {captain_row['slug']} (+{bonus} pt, +{captain_bonus_pct:.0%}) "
                 f"-> TOTALE CON CAPITANO: {totale_con_capitano} pt")
    if l10_cap is not None:
        stato = "OK" if l10_cap_rispettato else "NON RISPETTATO (nessun candidato entro budget, preso il piu' economico disponibile)"
        lines.append(f"L10 combinata: {totale_l10:.1f} / cap {l10_cap:.1f} -- {stato}")
    if apply_stack_guard:
        if stack_bonus_perso:
            lines.append("ATTENZIONE: 3+ giocatori della stessa squadra -- bonus anti-stack 2%/giocatore NON applicato "
                          "(valuta tu se il contesto della partita giustifica comunque lo stack).")
        else:
            lines.append("Bonus anti-stack (Multi-club) +2%/giocatore: attivo (meno di 3 titolari della stessa squadra).")
    if check_cap260:
        soglia_cap = CAP260_L10_THRESHOLD_BY_TYPE.get(tipo, 260.0)
        stato260 = "OK" if totale_l10 <= soglia_cap else "NON rispettato"
        lines.append(f"Cap {soglia_cap:.0f}: L10 combinata {totale_l10:.1f} / {soglia_cap:.0f} -- {stato260} "
                      f"({'+4% bonus formazione attivo' if totale_l10 <= soglia_cap else 'bonus +4% non ottenuto'})")
    return "\n".join(lines), totale_atteso


# --- Report visivo HTML (26/07, seconda sessione, richiesta esplicita
# dell'utente): oggi l'unico output e' testo puro, funzionale ma poco
# leggibile a colpo d'occhio. Genera un file .html AUTONOMO (nessuno script/
# font esterno, apribile con un doppio click da repo locale via file://,
# nessun server/download necessario) con un layout a "carte" ispirato alla
# UI reale di Sorare: striscia colorata per ruolo (niente foto/stemmi reali,
# non disponibili dall'API — iniziali del giocatore al loro posto), punteggio
# atteso in grande, range sotto, badge capitano, tag Classic/copie multiple.
# Committato dal workflow accanto al .txt esistente (stesso nome, estensione
# diversa).
ROLE_COLORS_HTML = {'GK': '#8b7cf6', 'DEF': '#3aa1e8', 'MID': '#2fbf8f', 'FWD': '#ef5b5b'}
EXTRA_COLOR_HTML = '#f0a83b'


def _slot_role_color(slot_label):
    for role, color in ROLE_COLORS_HTML.items():
        if slot_label.startswith(role):
            return color
    m = re.search(r'\(([A-Z]+)\)', slot_label)
    if m and m.group(1) in ROLE_COLORS_HTML:
        return ROLE_COLORS_HTML[m.group(1)]
    return EXTRA_COLOR_HTML


def _slug_initials(slug):
    parts = [p for p in slug.split('-') if p and not p.isdigit()]
    return ''.join(p[0].upper() for p in parts[:2]) or '??'


def _slug_display_name(slug):
    return ' '.join(w[:1].upper() + w[1:] for w in slug.split('-') if w)


ROLES_HTML = ('GK', 'DEF', 'MID', 'FWD')


def _slot_role(slot_label):
    """Ruolo REALE (GK/DEF/MID/FWD) di uno slot, sia esso diretto ('DEF1')
    che EXTRA ('EXTRA (MID)'). Condiviso fra pannello alternative e drag&drop
    (28/07) -- prima esisteva solo una copia locale in
    generatore_formazioni/build_formazione_globale.py, spostata qui perche'
    ora serve anche a render_card_html per il matching lato client."""
    for role in ROLES_HTML:
        if slot_label.startswith(role):
            return role
    m = re.search(r'\(([A-Z]+)\)', slot_label)
    return m.group(1) if m and m.group(1) in ROLES_HTML else None


def _pcard_tags_html(ctype, copie, xp_bonus_frac=0.0, split=None):
    """split (07/08): {'in_season': n, 'classic': m} per dire QUANTE copie sono
    di che tipo. Prima si vedeva solo 'N copie' e, avendone due di tipo
    diverso, non si capiva quale andasse usata dove -- richiesta esplicita
    dell'utente."""
    tags = []
    if ctype == 'classic':
        tags.append('<span class="tag tag-classic">Classic</span>')
    else:
        tags.append('<span class="tag tag-inseason">In Season</span>')
    if copie > 1:
        det = ''
        if split and (split.get('in_season') or 0) and (split.get('classic') or 0):
            det = f" ({split['in_season']} IS + {split['classic']} CL)"
        tags.append(f'<span class="tag tag-copies">{copie} copie{det}</span>')
    # Tag visibile del bonus power/xp/collezione/stagione (28/07, richiesta
    # esplicita utente: senza questo tag non si vedeva se il bonus era stato
    # applicato o se il punteggio era semplicemente piu' alto per altri
    # motivi). Mostrato SOLO quando il chiamante passa xp_bonus_frac > 0 --
    # cioe' SOLO per i tipi in XP_BONUS_TYPES (In Season/All Stars 7/U23),
    # mai per le Arene, dove il bonus non e' applicato.
    if xp_bonus_frac:
        tags.append(f'<span class="tag tag-xpbonus">+{xp_bonus_frac:.0%} xp</span>')
    return ''.join(tags)


def _short_team(slug):
    """Nome squadra abbreviato da uno slug Sorare (es.
    'inter-miami-cf-fort-lauderdale-florida' -> 'Inter Miami Cf') -- euristica
    (primi 3 token, title-case), non un lookup esatto: gli slug Sorare non
    hanno una lista di nomi brevi gia' pronta da nessuna parte nel repo, e
    costruire un dizionario per ~30+ squadre x 28 leghe non vale lo sforzo per
    un'etichetta diagnostica. None/'N/D' -> 'N/D'."""
    if not slug or slug == 'N/D':
        return 'N/D'
    parole = slug.split('-')[:3]
    return ' '.join(w.capitalize() for w in parole)


def _team_vs_opponent_html(team_slug, opponent_team_slug, opp_factor):
    """Riga 'Squadra vs Avversario' (29/07, richiesta esplicita utente: sapere
    subito contro chi gioca ogni giocatore schierato/escluso).
    Il coefficiente di forza avversario NON viene piu' mostrato (29/07,
    bug reale trovato dall'utente): 'domesticLeagueRanking' e' un attributo
    CORRENTE della squadra lato Sorare, non un valore storico legato alla
    singola partita -- interrogando lo stesso giorno di partita da cache di
    giocatori diversi (aggiornate in momenti diversi) si ottengono ranking
    DIVERSI per la stessa partita (verificato: 282/13671 coppie
    squadra+data, 22 squadre, valori incoerenti tra loro). La media
    'avg_opp_rank_hist' usata per calcolare il fattore e' quindi contaminata
    da uno snapshot non ancorato al tempo, non un vero storico -- mostrare
    un numero calcolato su questo dato sarebbe fuorviante anche se il
    fattore stesso resta gia' escluso da score_atteso. opp_factor resta nel
    dato (AVV_FACTOR nel consiglio) per un eventuale fix futuro, ma non
    renderizzato."""
    if not team_slug and not opponent_team_slug:
        return ''
    squadra = _short_team(team_slug)
    avversario = _short_team(opponent_team_slug)
    return f'<div class="pcard-match">{squadra} vs {avversario}</div>'


def _pcard_body_html(slug, atteso, low, high, l10, tags_html, card_pool,
                      team_slug=None, opponent_team_slug=None, opp_factor=None, starter_odds=None,
                      ambiguo=False, nuovo_campionato=False, nc_da=None):
    """Contenuto dinamico di una pcard (tutto tranne striscia colore/ruolo/
    badge capitano, che restano legati allo SLOT, non al giocatore) --
    fattorizzato (28/07) per essere riusato SIA per la carta reale SIA per
    calcolare in anticipo, in Python, l'HTML che un'alternativa diventerebbe
    se trascinata al posto del titolare (drag&drop lato client, nessun
    ricalcolo server: lo scambio e' un puro swap di HTML gia' pronto)."""
    l10_html = f'<div class="pcard-l10">L10: {l10:.0f}</div>' if l10 is not None else ''
    # Starter-odds su OGNI carta (10/08/2026, richiesta esplicita utente,
    # solo nell'HTML): stessa fonte gia' usata dal tie-break (row['starter_
    # odds'], persistita da discovery_fixture.py) -- zero costo, il dato era
    # gia' in mano. Chi non ce l'ha (odds ignote/discovery vecchia) non
    # mostra la riga, come per L10.
    odds_html = (f'<div class="pcard-odds">Odds: {starter_odds:.0%}</div>'
                 if starter_odds is not None else '')
    match_html = _team_vs_opponent_html(team_slug, opponent_team_slug, opp_factor)
    # Badge "fixture ambigua" (12/08/2026, richiesta esplicita utente): stesso
    # marker AMBIGUO_FIXTURE gia' mostrato in scouting_gw.py (caso Freese, due
    # partite future con odds pubblicate insieme -- vedi HANDOFF_UNIFICATO
    # §10bis). title= per il tooltip, niente testo lungo in carta.
    ambiguo_html = ('<div class="pcard-ambiguo" title="Due partite future con '
                     'odds pubblicate insieme: l\'atteso potrebbe riferirsi alla '
                     'partita sbagliata (caso Freese, 10/08).">⚠ Fixture ambigua</div>'
                     if ambiguo else '')
    # Badge "nuovo campionato" (13/08/2026, richiesta esplicita utente). SOLO
    # cosmetico: il flag lo scrive _annota_nuovo_campionato nel generatore
    # (lega dominante dello storico != lega in cui gioca ora) e non entra in
    # nessun calcolo. Serve a riconoscere le carte su cui l'atteso e' meno
    # affidabile -- misurato: 5,5 punti di sovrastima salendo di categoria, 7
    # di sottostima scendendo. Si spegne da solo quando lo storico nella lega
    # nuova diventa la maggioranza.
    da = f" (storico: {nc_da})" if nc_da else ''
    nuovo_camp_html = ('<div class="pcard-nuovacamp" title="Ha cambiato '
                       'campionato: lo storico su cui e\' calcolato l\'atteso '
                       'e\' quasi tutto in un\'altra lega' + html.escape(da) +
                       ', quindi il punteggio atteso potrebbe essere '
                       'differente.">🌍 Nuovo campionato</div>'
                       if nuovo_campionato else '')
    return (
        f'<span class="pcard-fatto">OK</span>'
        f'<div class="pcard-avatar">{_slug_initials(slug)}</div>'
        f'<div class="pcard-name">{card_pool.display_name(slug)}</div>'
        f'<div class="pcard-score">{atteso:.1f}</div>'
        f'<div class="pcard-range">{low:.1f}–{high:.1f} pt</div>'
        f'{l10_html}'
        f'{odds_html}'
        f'{match_html}'
        f'{ambiguo_html}'
        f'{nuovo_camp_html}'
        f'<div class="pcard-tags">{tags_html}</div>'
    )


def render_card_html(slot_label, row, ctype, card_pool, is_captain, apply_xp_bonus=False):
    color = _slot_role_color(slot_label)
    role_label = re.sub(r'^EXTRA \(([A-Z]+)\)$', r'EXTRA · \1', slot_label)
    role = _slot_role(slot_label) or ''
    copie = card_pool.copies_owned(row['slug'])
    xp_bonus_frac = card_pool.power_bonus_fraction(row['slug']) if apply_xp_bonus else 0.0
    split = card_pool.copies_split(row['slug']) if hasattr(card_pool, 'copies_split') else None
    tags_html = _pcard_tags_html(ctype, copie, xp_bonus_frac, split)
    captain_badge = '<span class="pcard-captain">C</span>' if is_captain else ''
    l10 = card_pool.l10(row['slug'])
    body_html = _pcard_body_html(row['slug'], row['atteso'], row['low'], row['high'], l10, tags_html, card_pool,
                                  team_slug=row.get('team_slug'), opponent_team_slug=row.get('opponent_team_slug'),
                                  opp_factor=row.get('opp_factor'), starter_odds=row.get('starter_odds'),
                                  ambiguo=row.get('ambiguo', False),
                                  nuovo_campionato=row.get('nuovo_campionato', False),
                                  nc_da=row.get('_nc_da'))
    # data-body (28/07): l'HTML esatto della pcard-body per QUESTO giocatore,
    # gia' pronto -- il drag&drop lato client lo scambia con quello di
    # un'alternativa senza ricalcolare nulla in JS (vedi script nel template).
    return (
        f'<div class="pcard{" is-classic" if ctype == "classic" else ""}" '
        f'draggable="true" style="--role-color:{color}" '
        f'data-slug="{html.escape(row["slug"], quote=True)}" data-role="{role}" '
        f'data-score="{row["atteso"]}" data-xp-frac="{xp_bonus_frac}" '
        f'data-name="{html.escape(card_pool.display_name(row["slug"]), quote=True)}" '
        f'data-body="{html.escape(body_html, quote=True)}">'
        f'<div class="pcard-stripe" style="background:{color}"></div>'
        f'<span class="pcard-role">{role_label}</span>'
        f'{captain_badge}'
        f'<div class="pcard-body">{body_html}</div>'
        f'</div>'
    )


def render_lineup_html(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True,
                        stack_bonus_perso=False, check_cap260=False, tipo=None, apply_stack_guard=False,
                        avoid_captain_slugs=None, apply_xp_bonus=False):
    captain_slot, captain_row, _captain_type = pick_captain(formazione, avoid_captain_slugs)
    # Tornati alla fila originale (28/07): sia il raggruppamento per ruolo
    # sia la diagonale non convincevano l'utente ("non ci siamo") -- niente
    # riordino, stessa sequenza di formazione, striscia unica con scroll
    # orizzontale se serve. Carte piu' piccole restano (richiesta separata,
    # confermata).
    cards_html = ''.join(
        render_card_html(slot, row, ctype, card_pool, row['slug'] == captain_row['slug'], apply_xp_bonus)
        for slot, row, ctype in formazione
    )
    totale_atteso = sum(row['atteso'] for _, row, _ in formazione)
    captain_bonus_pct = CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5)
    # SEMPLIFICATO 30/07: prima 'captain_row[atteso]' poteva includere il
    # bonus xp/collezione/stagione (vedi _apply_xp_bonus in
    # build_formazione_globale.py, che moltiplicava atteso PRIMA che
    # arrivasse qui), quindi serviva "de-gonfiarlo" per non applicare il
    # bonus capitano a cascata sopra un numero gia' gonfiato (fix 28/07).
    # Dal 30/07 'atteso' non viene PIU' mai gonfiato (il bonus XP entra solo
    # in 'sort_score', usato per scegliere chi schierare, mai per il
    # punteggio mostrato) -- 'captain_row[atteso]' e' sempre il valore vero,
    # nessuna correzione necessaria.
    bonus = round(captain_row['atteso'] * captain_bonus_pct)
    totale_con_capitano = totale_atteso + bonus
    l10_note = ''
    if l10_cap is not None:
        totale_l10 = sum(card_pool.l10(row['slug']) or 0.0 for _, row, _ in formazione)
        stato = 'entro budget' if l10_cap_rispettato else 'budget NON rispettato'
        l10_note = f'<div class="captain-note">L10: {totale_l10:.1f} / {l10_cap:.1f} ({stato})</div>'
    stack_note = ''
    if apply_stack_guard:
        if stack_bonus_perso:
            stack_note = ('<div class="captain-note" style="color:#d9534f">ATTENZIONE: 3+ giocatori della stessa '
                           'squadra — bonus anti-stack 2%/giocatore NON applicato</div>')
        else:
            stack_note = ('<div class="captain-note">Bonus Multi-club +2%/giocatore: attivo (meno di 3 titolari '
                           'della stessa squadra)</div>')
    cap260_note = ''
    if check_cap260:
        soglia_cap = CAP260_L10_THRESHOLD_BY_TYPE.get(tipo, 260.0)
        totale_l10_c260 = sum(card_pool.l10(row['slug']) or 0.0 for _, row, _ in formazione)
        ok260 = totale_l10_c260 <= soglia_cap
        colore = '' if ok260 else ' style="color:#d9534f"'
        esito = '+4% bonus formazione attivo' if ok260 else 'bonus +4% non ottenuto'
        cap260_note = (f'<div class="captain-note"{colore}>Cap {soglia_cap:.0f}: L10 {totale_l10_c260:.1f} / '
                        f'{soglia_cap:.0f} ({esito})</div>')
    # data-captain-pct (28/07): il drag&drop lato client deve ricalcolare
    # totale e bonus capitano dopo uno scambio senza rifare la run -- serve
    # solo la percentuale, il resto (chi e' capitano, punteggi) si legge
    # dagli attributi data-* delle pcard gia' presenti nel DOM.
    return (
        f'<div class="lineup-block"><div class="lineup-meta">'
        f'<div class="lineup-title">{tipo_label} <span>#{idx}</span></div></div>'
        f'<div class="card-strip">{cards_html}</div>'
        f'<div class="lineup-total" data-captain-pct="{captain_bonus_pct}">'
        f'<div><span class="label">Totale</span><span class="figure">{totale_atteso:.1f} pt</span></div>'
        f'<div class="divider"></div>'
        f'<div><span class="label">Con capitano</span>'
        f'<span class="figure with-captain">{totale_con_capitano:.1f} pt</span></div>'
        f'<div class="captain-note">Capitano <b class="cap-name">{card_pool.display_name(captain_row["slug"])}</b> '
        f'<span class="cap-bonus">(+{bonus} pt, +{captain_bonus_pct:.0%})</span></div>{l10_note}{stack_note}{cap260_note}'
        f'</div></div>'
    )


HTML_REPORT_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #0a0d12; --surface: #131a23; --surface-2: #1c2530; --stripe: #232d3a;
    --text: #edf1f6; --muted: #8a93a6; --muted-2: #5f6879; --gold: #f4c542;
    --border: rgba(255,255,255,0.08);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f3f4f7; --surface: #ffffff; --surface-2: #eef0f4; --stripe: #e3e6ec;
      --text: #1a2029; --muted: #5b6474; --muted-2: #8a93a6; --border: rgba(20,25,35,0.08);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
    padding: 40px 32px 64px; max-width: 1180px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 6px; }}
  .subhead {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 32px; }}
  .lineup-row {{ display: flex; gap: 20px; align-items: flex-start; margin-bottom: 40px; }}
  .lineup-row .lineup-block {{ flex: 1 1 auto; min-width: 0; margin-bottom: 0; }}
  .alt-panel {{
    flex: 0 0 200px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 14px; align-self: stretch;
  }}
  .alt-panel-title {{
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--muted); margin-bottom: 10px; line-height: 1.4;
  }}
  .alt-list {{ display: flex; flex-direction: column; gap: 10px; }}
  .alt-chip {{ display: flex; align-items: center; gap: 8px; cursor: grab; border-radius: 8px; padding: 2px; }}
  .alt-chip[draggable="true"]:active {{ cursor: grabbing; }}
  .pcard[draggable="true"] {{ cursor: grab; }}
  .pcard[draggable="true"]:active {{ cursor: grabbing; }}
  .pcard.drop-target, .alt-chip.drop-target {{
    outline: 2px dashed var(--gold); outline-offset: 2px;
  }}
  .alt-circle {{
    flex: 0 0 28px; width: 28px; height: 28px; border-radius: 50%; background: var(--surface-2);
    border: 1px solid var(--border); display: flex; align-items: center; justify-content: center;
    font-size: 0.62rem; font-weight: 700; color: var(--muted);
  }}
  .alt-name {{ font-size: 0.72rem; font-weight: 600; line-height: 1.2; }}
  .alt-score {{ font-size: 0.64rem; color: var(--muted); }}
  .lineup-block {{ margin-bottom: 40px; }}
  .lineup-meta {{ margin-bottom: 12px; }}
  .lineup-title {{ font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .lineup-title span {{ color: var(--text); }}
  .card-strip {{ display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; }}
  .pcard {{
    position: relative; flex: 0 0 104px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.2);
  }}
  .pcard-stripe {{ height: 4px; width: 100%; }}
  .pcard-body {{ padding: 8px 6px 8px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; }}
  .pcard-role {{
    position: absolute; top: 6px; left: 6px; font-size: 0.52rem; font-weight: 700;
    letter-spacing: 0.07em; text-transform: uppercase; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 16%, transparent);
    padding: 1px 5px; border-radius: 4px;
  }}
  .pcard-captain {{
    position: absolute; top: 5px; right: 5px; width: 16px; height: 16px; border-radius: 50%;
    background: var(--gold); color: #241c00; font-size: 0.58rem; font-weight: 800;
    display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--surface);
    /* 08/08: il capitano sta SEMPRE sopra la spunta verde di "copiata", che
       occupava lo stesso identico angolo (top/right 5px) e lo nascondeva --
       dopo aver copiato le 5 carte non si sapeva piu' chi fosse il capitano. */
    z-index: 2;
  }}
  .pcard-avatar {{
    width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.72rem; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 18%, var(--surface-2));
    border: 2px solid color-mix(in srgb, var(--role-color) 55%, transparent); margin-top: 8px;
  }}
  .pcard-name {{ font-size: 0.62rem; font-weight: 650; line-height: 1.2; min-height: 1.6em; display: flex; align-items: center; }}
  .pcard-score {{ font-size: 1.15rem; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; color: var(--role-color); }}
  .pcard-range {{ font-size: 0.55rem; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .pcard-l10 {{ font-size: 0.5rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }}
  .pcard-odds {{ font-size: 0.85rem; font-weight: 800; color: #3a9de0; font-variant-numeric: tabular-nums; }}
  .pcard-match {{ font-size: 0.62rem; color: var(--text); opacity: 0.85; line-height: 1.3; text-align: center; }}
  .pcard-ambiguo {{
    font-size: 0.55rem; font-weight: 700; color: #f0a83b;
    background: rgba(240,168,59,0.16); border-radius: 4px; padding: 1px 5px;
    text-align: center; cursor: help;
  }}
  .pcard-nuovacamp {{
    font-size: 0.55rem; font-weight: 700; color: #7aa7ff;
    background: rgba(122,167,255,0.16); border-radius: 4px; padding: 1px 5px;
    text-align: center; cursor: help;
  }}
  .pcard-tags {{ display: flex; gap: 3px; flex-wrap: wrap; justify-content: center; min-height: 14px; }}
  .tag {{ font-size: 0.5rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; padding: 1px 4px; border-radius: 3px; }}
  .tag-classic {{ background: rgba(240,168,59,0.16); color: #f0a83b; }}
  .tag-copies {{ background: var(--stripe); color: var(--muted); }}
  .tag-xpbonus {{ background: rgba(76,175,80,0.16); color: #4caf50; }}
  /* QOL 07/08 (richiesta utente: schierare ~300 giocatori a giornata facendo
     avanti e indietro con Sorare, senza perdere il segno e senza sbagliare
     formazione). Tre stati VISIBILI a colpo d'occhio:
       - CLASSIC: contorno dorato. Sono quelle che pesano diversamente e vanno
         distinte al volo dalle In Season, soprattutto quando si hanno 2 copie.
       - carta GIA' COPIATA: si spegne, cosi' si sa dove si era arrivati.
       - formazione GIA' SCHIERATA: si spegne tutta e si accascia in alto.
     Lo stato vive in localStorage, per giornata: un refresh non lo perde. */
  /* CLASSIC vs IN SEASON (rimarcato 08/08, richiesta esplicita utente: la
     scritta "classic" da sola "e' poco intuitiva"). Tre segnali insieme,
     leggibili senza rileggere il testo: contorno dorato DOPPIO (2px invece
     di 1), striscia dorata in cima al posto del colore ruolo (il ruolo si
     legge comunque nel badge in alto a sinistra), e il tag pieno d'oro con
     un rombo davanti invece che scritta scolorita su fondo grigio. */
  .pcard.is-classic {{ border-color: var(--gold); box-shadow: 0 0 0 2px var(--gold) inset, 0 1px 2px rgba(0,0,0,0.2); }}
  .pcard.is-classic .pcard-stripe {{ background: var(--gold) !important; height: 5px; }}
  .tag-classic {{ background: var(--gold); color: #241c00; font-weight: 800; }}
  .tag-classic::before {{ content: '\\25C6'; margin-right: 3px; }}
  .tag-inseason {{ background: rgba(94,201,255,0.16); color: #5ec9ff; }}
  /* CARTA GIA' COPIATA (rivisto 08/08 su richiesta utente). Prima si spegneva
     a opacity 0.38: illeggibile, e "non mi piace, diventano bui". Ora resta
     LEGGIBILE (0.72) e il segnale di "fatto" e' il contorno verde piu' la
     spunta, non il buio. Serve a sapere dove si era arrivati, non a
     cancellare la carta: i numeri si devono poter ancora rileggere. */
  .pcard.copiata {{ opacity: 0.72; }}
  .pcard.copiata .pcard-avatar {{ border-style: dashed; }}
  .pcard-fatto {{
    position: absolute; top: 5px; right: 5px; width: 16px; height: 16px; border-radius: 50%;
    background: #4caf50; color: #06210a; font-size: 0.62rem; font-weight: 800;
    display: none; align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--surface);
  }}
  .pcard.copiata .pcard-fatto {{ display: flex; }}
  /* Contorno verde: si vede a colpo d'occhio anche senza spegnere la carta.
     outline (non box-shadow) per non cancellare il bordo dorato delle
     Classic, che usa gia' box-shadow inset. */
  .pcard.copiata {{ outline: 2px solid #4caf50; outline-offset: -2px; }}
  /* Se la carta e' capitano, la spunta si sposta a fianco invece di finirgli
     sotto. Con browser senza :has() resta sovrapposta, ma il capitano ha
     z-index 2 e resta comunque visibile: nessun peggioramento. */
  .pcard:has(.pcard-captain) .pcard-fatto {{ right: 25px; }}
  .lineup-block.schierata {{ opacity: 0.42; }}
  .lineup-block.schierata .lineup-title::after {{ content: ' — SCHIERATA'; color: #4caf50; font-weight: 800; }}
  .btn-schierata {{
    margin-left: 10px; font-size: 0.6rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; padding: 3px 8px; border-radius: 5px; cursor: pointer;
    background: var(--surface-2); color: var(--muted); border: 1px solid var(--border);
  }}
  .btn-schierata:hover {{ color: var(--text); border-color: var(--gold); }}
  .lineup-block.schierata .btn-schierata {{ background: rgba(76,175,80,0.18); color: #4caf50; border-color: #4caf50; }}
  .lineup-total {{
    margin-top: 12px; display: inline-flex; align-items: center; gap: 14px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px; padding: 10px 16px; flex-wrap: wrap;
    max-width: 100%;
  }}
  .lineup-total .figure {{ font-size: 1.3rem; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .lineup-total .figure.with-captain {{ color: var(--gold); }}
  .lineup-total .label {{ font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); display: block; margin-bottom: 2px; }}
  .lineup-total .divider {{ width: 1px; height: 30px; background: var(--border); }}
  .lineup-total .captain-note {{ font-size: 0.74rem; color: var(--muted); }}
  .lineup-total .captain-note b {{ color: var(--gold); font-weight: 700; }}
  .error-block {{ font-size: 0.82rem; color: var(--muted); padding: 12px 0; }}
  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); font-size: 0.7rem; color: var(--muted-2); line-height: 1.6; }}
</style>
</head>
<body>
<h1>{page_title}</h1>
<p class="subhead">{page_subhead}</p>
{lineup_html}
<footer>{footer}</footer>
<script>
// Drag&drop (28/07, richiesta esplicita utente): scambia un giocatore fra
// una pcard schierata e un'alternativa (o un'altra pcard), stesso ruolo.
// Puro swap di HTML/attributi gia' pronti lato server (data-body) -- NESSUN
// ricalcolo di formula, NESSUNA persistenza (un refresh della pagina
// riporta tutto allo stato generato). Limite noto: le note L10/cap/anti-stack
// sotto ogni formazione restano quelle calcolate al momento della run, non
// si aggiornano con lo scambio (solo totale e bonus capitano lo fanno).
(function () {{
  var dragEl = null;

  function isDraggable(el) {{
    return el && (el.classList.contains('pcard') || el.classList.contains('alt-chip'))
      && el.getAttribute('draggable') === 'true';
  }}

  document.addEventListener('dragstart', function (e) {{
    var el = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!el) return;
    dragEl = el;
    e.dataTransfer.effectAllowed = 'move';
    try {{ e.dataTransfer.setData('text/plain', 'x'); }} catch (err) {{}}
  }});

  document.addEventListener('dragover', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!dragEl || !target || target === dragEl || target.dataset.role !== dragEl.dataset.role) return;
    e.preventDefault();
  }});

  document.addEventListener('dragenter', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (dragEl && target && target !== dragEl && target.dataset.role === dragEl.dataset.role) {{
      target.classList.add('drop-target');
    }}
  }});

  document.addEventListener('dragleave', function (e) {{
    var target = e.target.closest('.pcard, .alt-chip');
    if (target) target.classList.remove('drop-target');
  }});

  document.addEventListener('dragend', function () {{
    document.querySelectorAll('.drop-target').forEach(function (el) {{ el.classList.remove('drop-target'); }});
    dragEl = null;
  }});

  document.addEventListener('drop', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!dragEl || !target || target === dragEl || target.dataset.role !== dragEl.dataset.role) return;
    e.preventDefault();
    target.classList.remove('drop-target');
    swapPlayers(dragEl, target);
    dragEl = null;
  }});

  function initials(name) {{
    return (name || '').split(' ').filter(Boolean).slice(0, 2)
      .map(function (w) {{ return w[0].toUpperCase(); }}).join('') || '??';
  }}

  function refresh(el) {{
    if (el.classList.contains('pcard')) {{
      var body = el.querySelector('.pcard-body');
      if (body) body.innerHTML = el.dataset.body;
    }} else {{
      var circle = el.querySelector('.alt-circle');
      var name = el.querySelector('.alt-name');
      var score = el.querySelector('.alt-score');
      if (circle) circle.textContent = initials(el.dataset.name);
      if (name) name.textContent = el.dataset.name;
      if (score) score.textContent = (parseFloat(el.dataset.score) || 0).toFixed(1) + ' pt · ' + el.dataset.role;
    }}
  }}

  function swapPlayers(a, b) {{
    ['slug', 'score', 'name', 'body', 'xpFrac'].forEach(function (k) {{
      var tmp = a.dataset[k];
      a.dataset[k] = b.dataset[k];
      b.dataset[k] = tmp;
    }});
    refresh(a);
    refresh(b);
    [a, b].forEach(function (el) {{
      var block = el.closest('.lineup-block');
      if (block) recomputeTotal(block);
    }});
  }}

  function recomputeTotal(block) {{
    var total = 0;
    block.querySelectorAll('.pcard').forEach(function (c) {{ total += parseFloat(c.dataset.score) || 0; }});
    var totalEl = block.querySelector('.lineup-total');
    if (!totalEl) return;
    var figure = totalEl.querySelector('.figure:not(.with-captain)');
    if (figure) figure.textContent = total.toFixed(1) + ' pt';
    var capBadge = block.querySelector('.pcard-captain');
    var capPct = parseFloat(totalEl.dataset.captainPct || '0.5');
    var bonus = 0, capName = '';
    if (capBadge) {{
      var capCard = capBadge.closest('.pcard');
      // FIX 28/07 sera: data-score include GIA' il bonus xp/collezione/
      // stagione (se applicabile) -- calcolare il +50% capitano su quel
      // valore gonfiato lo applica in cascata invece che addizionato
      // (stesso bug fixato lato Python in render_lineup_html). Si riporta
      // al valore raw dividendo per (1+xpFrac) prima di applicare capPct.
      var capScore = parseFloat(capCard.dataset.score) || 0;
      var xpFrac = parseFloat(capCard.dataset.xpFrac) || 0;
      var capRaw = xpFrac ? capScore / (1 + xpFrac) : capScore;
      bonus = Math.round(capRaw * capPct);
      capName = capCard.dataset.name || '';
    }}
    var withCap = totalEl.querySelector('.figure.with-captain');
    if (withCap) withCap.textContent = (total + bonus).toFixed(1) + ' pt';
    var capNameEl = totalEl.querySelector('.cap-name');
    if (capNameEl && capName) capNameEl.textContent = capName;
    var capBonusEl = totalEl.querySelector('.cap-bonus');
    if (capBonusEl) capBonusEl.textContent = '(+' + bonus + ' pt, +' + Math.round(capPct * 100) + '%)';
  }}
}})();
</script>
<script>
(function () {{
  // Click sul nome del giocatore = nome negli appunti, da incollare nella
  // ricerca di Sorare (01/08, richiesta utente: i nomi coreani sono difficili
  // da riscrivere a mano).
  function copia(testo, el) {{
    var vecchio = el.textContent;
    var ok = function () {{
      el.textContent = 'copiato!';
      setTimeout(function () {{ el.textContent = vecchio; }}, 800);
    }};
    var fallback = function () {{
      var riuscito = false;
      var ta = document.createElement('textarea');
      ta.value = testo; document.body.appendChild(ta); ta.select();
      try {{ riuscito = document.execCommand('copy'); }} catch (e) {{}}
      document.body.removeChild(ta);
      if (riuscito) {{
        ok();
      }} else {{
        el.style.color = 'red';
        el.textContent = 'copia non riuscita';
        setTimeout(function () {{ el.textContent = vecchio; el.style.color = ''; }}, 1200);
      }}
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(testo).then(ok, fallback);
    }} else {{
      fallback();
    }}
  }}
  document.addEventListener('click', function (ev) {{
    // Si copia cliccando il CERCHIO con le iniziali oppure il nome (07/08,
    // richiesta utente): il cerchio e' molto piu' grande e piu' facile da
    // centrare quando si compongono decine di formazioni. Restano validi
    // entrambi, cosi' chi e' abituato al nome non perde niente.
    if (!ev.target || !ev.target.closest) return;
    var punto = ev.target.closest('.pcard-avatar, .pcard-name');
    if (!punto) return;
    ev.preventDefault(); ev.stopPropagation();
    var card = punto.closest('[data-name]') || punto.closest('[data-slug]')
               || punto.closest('.pcard');
    // Il messaggio ('copiato!'/'copia non riuscita') va SEMPRE sul nome, mai
    // sul cerchio: li' dentro ci stanno due lettere e non si leggerebbe.
    var el = (card && card.querySelector('.pcard-name')) || punto;
    var testo = (card && (card.dataset.name || card.dataset.slug)) || el.textContent;
    copia(testo.trim(), el);
    segnaCopiata(card);   // avanzamento: da qui in poi si sa dove si era arrivati
  }}, true);
  /* AVANZAMENTO (07/08). Il problema non e' copiare un nome, e' NON PERDERE
     IL SEGNO: ~300 giocatori a giornata, avanti e indietro con Sorare, con il
     rischio di rimettere un difensore nella formazione di un altro portiere.
     Due memorie, per GIORNATA, in localStorage (un refresh non le perde):
       - carta copiata -> si spegne e prende la spunta verde
       - formazione schierata -> si spegne tutta, col tasto FATTA
     Niente di tutto questo tocca i punteggi: e' solo stato di avanzamento. */
  var CHIAVE = 'sorare-avanzamento::' + (document.title || 'gw');
  function statoLeggi() {{
    try {{ return JSON.parse(localStorage.getItem(CHIAVE) || '{{}}'); }}
    catch (e) {{ return {{}}; }}
  }}
  function statoScrivi(s) {{
    try {{ localStorage.setItem(CHIAVE, JSON.stringify(s)); }} catch (e) {{}}
  }}
  function idCarta(card) {{
    var blocco = card.closest('.lineup-block');
    var titolo = blocco ? (blocco.querySelector('.lineup-title') || {{}}).textContent : '';
    return (titolo || '') + '|' + (card.dataset.slug || '') + '|' + (card.dataset.role || '');
  }}
  function idBlocco(blocco) {{
    var t = blocco.querySelector('.lineup-title');
    return 'BLOCCO|' + ((t && t.textContent) || '');
  }}
  function applicaStato() {{
    var s = statoLeggi();
    document.querySelectorAll('.pcard').forEach(function (c) {{
      c.classList.toggle('copiata', !!s[idCarta(c)]);
    }});
    document.querySelectorAll('.lineup-block').forEach(function (b) {{
      b.classList.toggle('schierata', !!s[idBlocco(b)]);
    }});
  }}
  function segnaCopiata(card) {{
    if (!card) return;
    var s = statoLeggi();
    s[idCarta(card)] = 1;
    statoScrivi(s);
    card.classList.add('copiata');
  }}
  // Un tasto FATTA per formazione, piu' il ripristino
  document.querySelectorAll('.lineup-block').forEach(function (b) {{
    var t = b.querySelector('.lineup-title');
    if (!t) return;
    var btn = document.createElement('span');
    btn.className = 'btn-schierata';
    btn.textContent = 'fatta';
    btn.title = 'Segna questa formazione come gia\\' schierata su Sorare';
    btn.addEventListener('click', function (ev) {{
      ev.preventDefault(); ev.stopPropagation();
      var s = statoLeggi();
      var k = idBlocco(b);
      if (s[k]) {{ delete s[k]; }} else {{ s[k] = 1; }}
      statoScrivi(s);
      applicaStato();
    }});
    t.parentNode.appendChild(btn);
  }});
  applicaStato();
  var st = document.createElement('style');
  st.textContent = '.pcard-name{{cursor:copy}} .pcard-name:hover{{text-decoration:underline dotted}}'
                 + '.pcard-avatar{{cursor:copy}}'
                 + '.pcard-avatar:hover{{outline:2px solid currentColor;outline-offset:2px}}';
  document.head.appendChild(st);
}})();
</script>
</body>
</html>
"""


def render_report_html(page_title, page_subhead, lineup_html_blocks, footer):
    body = "\n".join(lineup_html_blocks) if lineup_html_blocks else '<p class="error-block">Nessuna formazione generata.</p>'
    return HTML_REPORT_TEMPLATE.format(
        page_title=page_title, page_subhead=page_subhead, lineup_html=body, footer=footer)


# Cap L10 fisso per i tipi Arena dedicati (26/07) -- indipendenti dal tuning
# generico ARENA_L10_CAP (quello resta per il tipo 'ARENA' semplice/legacy).
FIXED_L10_CAP_BY_TYPE = {'ARENA_260': 260.0, 'ARENA_220': 220.0}


def generate_lineups_for_type(tipo, count, role_data, card_pool, lineup_blocks,
                               lineup_html_blocks, print_output=True):
    """Genera fino a 'count' formazioni del tipo 'tipo' (chiave di
    FORMATION_SHAPES), aggiungendo i blocchi di testo a lineup_blocks e i
    blocchi HTML a lineup_html_blocks. Ritorna (generate, totale_punti). Si
    ferma in anticipo (senza errore globale) se il pool si esaurisce per
    questo tipo, ma NON impedisce la generazione del tipo successivo in
    ordine di priorita'.

    ATTENZIONE (accertato 31/07, audit completo): questa funzione NON gira
    nella pipeline di produzione. Le formazioni reali le costruisce
    generatore_formazioni/build_formazione_globale.py, che ha una PROPRIA
    generate_lineups_for_type e importa da qui solo le funzioni generiche
    (CardPool, build_one_lineup, synergy_sort_key, pick_captain, render_*).
    Il workflow formazione_giornata.yml lancia solo quel file.

    Conseguenza pratica gia' costata un bug reale: le decisioni di
    configurazione scritte QUI (variance_mode, scelta del synergy_bonus_dict,
    gate apply_positive_synergy, stack_guard) non arrivano in produzione --
    e' successo il 30/07 con IN_SEASON_SYNERGY_BONUS_BY_PAIR, calibrata e
    poi mai eseguita. Qualunque modifica al COMPORTAMENTO va fatta nel
    generatore globale, o in entrambi se si vuole tenere allineato anche
    l'uso standalone/da libreria di questo file."""
    shape = FORMATION_SHAPES[tipo]
    cap = FIXED_L10_CAP_BY_TYPE.get(tipo)
    # Anti-stack e cap-bonus (26/07, confermato dall'utente): valgono per
    # In Season E All Stars (soglie/percentuali diverse ma stesso meccanismo),
    # non per Arena (che ha il suo cap L10 obbligatorio separato, nessun bonus).
    stack_guard = tipo in ('IN_SEASON', 'ALLSTARS')
    # Sinergia da correlazione misurata: ABILITATA anche per In Season dal
    # 30/07 (richiesta esplicita utente, vedi IN_SEASON_SYNERGY_BONUS_BY_PAIR
    # sopra per il perche' -- il vecchio "il target e' fisso quindi nessun
    # beneficio" era incompleto, misurato con Monte Carlo su dati reali che
    # la correlazione cambia comunque la probabilita' di superare il target).
    # Tabella diversa per tipo: In Season usa bonus molto piu' piccoli
    # (6 vite diluiscono il beneficio marginale per formazione).
    variance_mode = True
    synergy_bonus_dict = IN_SEASON_SYNERGY_BONUS_BY_PAIR if tipo == 'IN_SEASON' else SAME_TEAM_SYNERGY_BONUS_BY_PAIR
    # 27/07, richiesta esplicita utente: quando si richiedono 2+ In Season,
    # SOLO la prima usa la sinergia GK-DEF soft (comportamento storico); dalla
    # seconda in poi e' greedy puro (solo punteggio, nessuna priorita' di
    # ruolo/sinergia). In ENTRAMBI i casi, se sono 2+, il vincolo di
    # schieramento portiere-vs-avversario diventa DURO (mai piu' un'ultima
    # risorsa) invece che un forte scoraggiamento. Con 1 sola In Season
    # richiesta, o per Arena/All Stars, comportamento INVARIATO.
    in_season_multi = tipo == 'IN_SEASON' and count >= 2
    # Varianza capitano (27/07, richiesta esplicita utente): scope PER TIPO,
    # naturale qui dato che generate_lineups_for_type gia' genera un tipo per
    # chiamata -- evita di rinominare capitano un giocatore gia' capitanato
    # in una formazione precedente DELLO STESSO TIPO, a meno che non ci sia
    # nessuna alternativa valida nella lineup corrente (pick_captain ripiega
    # sul punteggio piu' alto assoluto in quel caso). Un giocatore con 1 sola
    # copia non puo' comunque comparire in due lineup dello stesso tipo (il
    # CardPool lo impedirebbe), quindi non serve un controllo esplicito
    # "2+ copie": la condizione e' gia' garantita dal pool.
    captained_slugs = set()
    generated = 0
    totale = 0
    for idx in range(1, count + 1):
        strict_gk_anti_synergy = in_season_multi
        apply_positive_synergy = not in_season_multi or idx == 1
        formazione, error, l10_ok, stack_perso = build_one_lineup(
            shape, role_data, card_pool, l10_cap=cap, apply_stack_guard=stack_guard,
            variance_mode=variance_mode, apply_positive_synergy=apply_positive_synergy,
            strict_gk_anti_synergy=strict_gk_anti_synergy, synergy_bonus_dict=synergy_bonus_dict)
        if error:
            msg = f"Formazione {shape['label']} #{idx}: NON GENERATA — {error}"
            if print_output:
                print(f"\n{msg}")
            lineup_blocks.append(msg)
            lineup_html_blocks.append(f'<p class="error-block">{msg}</p>')
            break
        check_cap260 = tipo in CAP260_L10_THRESHOLD_BY_TYPE
        block_text, punti = format_lineup(shape['label'], idx, formazione, card_pool,
                                           l10_cap=cap, l10_cap_rispettato=l10_ok,
                                           stack_bonus_perso=stack_perso, check_cap260=check_cap260,
                                           tipo=tipo, apply_stack_guard=stack_guard,
                                           avoid_captain_slugs=captained_slugs)
        lineup_blocks.append(block_text)
        lineup_html_blocks.append(render_lineup_html(shape['label'], idx, formazione, card_pool,
                                                       l10_cap=cap, l10_cap_rispettato=l10_ok,
                                                       stack_bonus_perso=stack_perso,
                                                       avoid_captain_slugs=captained_slugs,
                                                       check_cap260=check_cap260, tipo=tipo,
                                                       apply_stack_guard=stack_guard))
        _cap_slot, cap_row, _cap_type = pick_captain(formazione, captained_slugs)
        captained_slugs.add(cap_row['slug'])
        totale += punti
        generated += 1
        if print_output:
            print("\n" + block_text)
    return generated, totale


def main():
    counts, num_totale = get_formation_counts()
    role_data, role_files, role_counts, counts_files = load_all_roles()

    print(f"Formazioni richieste: totale={num_totale} "
          f"(In Season={counts['IN_SEASON']}, Arena cap260={counts['ARENA_260']}, "
          f"Arena cap220={counts['ARENA_220']}, Arena uncapped={counts['ARENA_UNCAPPED']}, "
          f"All Stars={counts['ALLSTARS']})")
    print()
    for role, path in role_files.items():
        n = len(role_data.get(role) or [])
        print(f"[{role}] {path or 'NESSUN FILE TROVATO'} -> {n} giocatori disponibili")
    for role, path in counts_files.items():
        print(f"[{role}] player_card_counts.json: {path or 'MANCANTE (default 1 copia in_season/giocatore)'}")

    if not all(role_data.get(r) for r in ROLES):
        print("\nERRORE: almeno un ruolo non ha consiglio disponibile, impossibile generare formazioni.")
        return

    card_pool = CardPool(role_counts)

    # Numero di run GitHub Actions (GITHUB_RUN_NUMBER, incrementale per workflow):
    # incluso nel nome file e nell'header per distinguere a colpo d'occhio
    # l'output di run diversi, che altrimenti si differenzierebbero solo per
    # pochi minuti nel timestamp. Assente nei run locali (fuori CI).
    run_number = os.environ.get('GITHUB_RUN_NUMBER')

    header_lines = []
    header_lines.append("=" * 70)
    header_lines.append("FORMAZIONE OTTIMALE — FUSIONE FINALE")
    if run_number:
        header_lines.append(f"Run GitHub Actions: #{run_number}")
    header_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    header_lines.append(f"Formazioni richieste: totale={num_totale} (In Season={counts['IN_SEASON']}, "
                         f"Arena cap260={counts['ARENA_260']}, Arena cap220={counts['ARENA_220']}, "
                         f"Arena uncapped={counts['ARENA_UNCAPPED']}, All Stars={counts['ALLSTARS']})")
    header_lines.append("=" * 70)
    header_lines.append("")
    header_lines.append("Fonte consigli di ruolo (piu' recenti in repo):")
    for role, path in role_files.items():
        header_lines.append(f"  {role}: {path or 'MANCANTE'}")
    header_lines.append("")
    header_lines.append("Fonte copie possedute per giocatore (player_card_counts.json):")
    for role, path in counts_files.items():
        header_lines.append(f"  {role}: {path or 'MANCANTE (assunta 1 copia in_season per ogni giocatore)'}")
    header_lines.append("")
    header_lines.append("-" * 70)

    lineup_blocks = []
    lineup_html_blocks = []
    generated_by_type = {}
    grand_total = 0
    # Ordine di priorita' FISSO (26/07): In Season -> Arena cap260 -> Arena
    # cap220 -> Arena uncapped -> All Stars.
    for tipo in ('IN_SEASON', 'ARENA_260', 'ARENA_220', 'ARENA_UNCAPPED', 'ALLSTARS'):
        n_richieste = counts[tipo]
        if n_richieste <= 0:
            generated_by_type[tipo] = 0
            continue
        generated, totale = generate_lineups_for_type(
            tipo, n_richieste, role_data, card_pool, lineup_blocks, lineup_html_blocks)
        generated_by_type[tipo] = generated
        grand_total += totale

    total_generated = sum(generated_by_type.values())

    footer_lines = []
    footer_lines.append("-" * 70)
    footer_lines.append(f"Formazioni generate: {total_generated}/{num_totale} "
                         f"(In Season {generated_by_type.get('IN_SEASON', 0)}/{counts['IN_SEASON']}, "
                         f"Arena cap260 {generated_by_type.get('ARENA_260', 0)}/{counts['ARENA_260']}, "
                         f"Arena cap220 {generated_by_type.get('ARENA_220', 0)}/{counts['ARENA_220']}, "
                         f"Arena uncapped {generated_by_type.get('ARENA_UNCAPPED', 0)}/{counts['ARENA_UNCAPPED']}, "
                         f"All Stars {generated_by_type.get('ALLSTARS', 0)}/{counts['ALLSTARS']})")
    if total_generated > 1:
        footer_lines.append(f"TOTALE COMPLESSIVO (tutte le formazioni): {grand_total} pt")
    footer_lines.append("=" * 70)
    footer_lines.append("")
    footer_lines.append("NOTA: max 1 carta CLASSIC per formazione SOLO per In Season (contrassegnata")
    footer_lines.append("[CLASSIC]) -- Arena e All Stars non hanno questo vincolo. Preferenza")
    footer_lines.append("automatica per copie IN_SEASON quando disponibili. Un giocatore e' riusato")
    footer_lines.append("in piu' lineup (anche di tipo diverso) solo se se ne possiedono piu' copie")
    footer_lines.append("(player_card_counts.json).")

    full_text = "\n".join(header_lines) + "\n\n" + "\n\n".join(lineup_blocks) + "\n\n" + "\n".join(footer_lines)
    print("\n" + "\n".join(footer_lines))

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    run_suffix = f"_run{run_number}" if run_number else ""
    out_path = os.path.join(OUTPUT_DIR, f'formazione_finale{run_suffix}_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"\nSalvato in: {out_path}")

    # Report visivo HTML (26/07, richiesta esplicita dell'utente): stesso
    # contenuto del .txt, presentazione a carte -- apribile con un doppio
    # click, nessun server/download necessario (vedi HTML_REPORT_TEMPLATE).
    page_title = f"Formazioni{' — run #' + run_number if run_number else ''}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                    f"totale={num_totale} (In Season={counts['IN_SEASON']}, "
                    f"Arena cap260={counts['ARENA_260']}, Arena cap220={counts['ARENA_220']}, "
                    f"Arena uncapped={counts['ARENA_UNCAPPED']}, All Stars={counts['ALLSTARS']})")
    footer_html = ("Nessuna carta CLASSIC oltre il limite per In Season (max 1) -- Arena e All Stars "
                   "non hanno questo vincolo. Un giocatore e' riusato in piu' lineup solo se se ne "
                   "possiedono piu' copie.")
    html_text = render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_path = os.path.join(OUTPUT_DIR, f'formazione_finale{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"Report visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
