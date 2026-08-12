"""
Misura la latenza verso Sorare da questa macchina, per confrontare due
connessioni diverse (13/08/2026, richiesta dell'utente).

PERCHE' ESISTE: bot definitivo vince o perde una gara di sniping per
millisecondi. Il PC di casa e' stato scelto proprio perche' ha meta' della
latenza di un runner GitHub (82 ms contro 168, misurato il 12/08). Se in casa
ci sono due connessioni, tanto vale usare quella piu' veloce -- ma va MISURATO,
non deciso a occhio: la piu' veloce a scaricare non e' per forza la piu' pronta
a rispondere, e per lo sniping conta la SECONDA cosa.

COME SI USA (una volta per connessione, cambiando rete in mezzo):

    python misura_latenza_sorare.py fibra
    python misura_latenza_sorare.py 4g

Ogni run si aggiunge a un file di misure e alla fine RISTAMPA il confronto fra
tutte le connessioni misurate, quindi il verdetto si legge dall'ultima run.
Per rivedere il confronto senza misurare di nuovo:

    python misura_latenza_sorare.py --confronto

COSA MISURA, e perche' due numeri invece di uno:

  1. APERTURA DI CONNESSIONE (TCP + TLS) verso api.sorare.com:443.
     E' la latenza PURA della rete, senza il tempo di lavoro del server.
     Non consuma quota API, quindi si possono fare tanti campioni e il
     numero e' stabile. E' questo il numero su cui si decide.

  2. RICHIESTA VERA (POST GraphQL). Include il tempo del server, che e'
     UGUALE per entrambe le connessioni e quindi non aiuta a sceglierle,
     ma serve a vedere il numero "di mondo reale". Pochi campioni, perche'
     senza chiave l'API accetta 20 richieste al minuto.

COSA GUARDARE, in ordine:
  - la MEDIANA: il caso tipico;
  - il 90esimo percentile e il MASSIMO: i momenti brutti. Una connessione con
    mediana piu' bassa ma picchi doppi puo' essere peggiore per lo sniping,
    perche' e' proprio nel picco che si perde l'annuncio;
  - il TREMOLIO (differenza fra p90 e mediana): quanto e' regolare.
"""

import json
import os
import socket
import ssl
import statistics
import sys
import time

HOST = "api.sorare.com"
PORT = 443

# 40 campioni di apertura connessione: costano solo tempo (~15 secondi in
# tutto), non consumano quota API, e con questo numero la mediana non balla
# piu' da una run all'altra.
CAMPIONI_CONNESSIONE = 40

# Poche richieste vere: senza chiave API il tetto e' 20 al minuto, e questo
# script deve poter girare due volte di fila mentre si cambia rete.
CAMPIONI_RICHIESTA = 8

# Query volutamente minuscola: chiede uno slug e basta. Piu' e' leggera, piu'
# il numero misura la RETE invece del lavoro del server.
QUERY = '{"query":"query Sonda { so5 { so5Fixture(slug: \\"football-11-14-aug-2026\\") { slug } } }"}'

FILE_MISURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "misure_latenza_sorare.json")


def _percentile(valori_ordinati, frazione):
    """Percentile col metodo del 'nearest rank': niente interpolazione, cosi'
    il numero e' sempre uno dei campioni davvero misurati."""
    if not valori_ordinati:
        return float("nan")
    i = max(0, min(len(valori_ordinati) - 1,
                   int(round(frazione * len(valori_ordinati) + 0.5)) - 1))
    return valori_ordinati[i]


def _riassumi(campioni):
    c = sorted(campioni)
    return {
        "n": len(c),
        "min": c[0],
        "mediana": statistics.median(c),
        "p90": _percentile(c, 0.90),
        "max": c[-1],
    }


def misura_apertura_connessione():
    """Tempo per aprire TCP + fare l'handshake TLS, in millisecondi.

    Ogni giro apre una connessione NUOVA e la chiude: e' il costo che paga
    ogni richiesta che non trova una connessione gia' aperta, ed e' la misura
    piu' pulita della latenza di rete che si possa fare senza toccare l'API.
    """
    ctx = ssl.create_default_context()
    tempi = []
    falliti = 0
    for i in range(CAMPIONI_CONNESSIONE):
        inizio = time.perf_counter()
        try:
            with socket.create_connection((HOST, PORT), timeout=10) as grezzo:
                with ctx.wrap_socket(grezzo, server_hostname=HOST):
                    tempi.append((time.perf_counter() - inizio) * 1000)
        except OSError:
            falliti += 1
        # Respiro fra un campione e l'altro: una raffica di aperture di fila
        # misurerebbe anche quanto si intasa da sola, non la latenza vera.
        time.sleep(0.15)
        if (i + 1) % 10 == 0:
            print(f"    ...{i + 1}/{CAMPIONI_CONNESSIONE}", flush=True)
    return tempi, falliti


def misura_richiesta_vera():
    """Andata e ritorno di una POST GraphQL vera, in millisecondi.

    Riusa la STESSA connessione per tutti i campioni (come fa il bot durante
    una run), quindi non paga l'handshake ogni volta: qui si vede il tempo di
    reazione a bot avviato.
    """
    try:
        import requests
    except ImportError:
        return [], "requests non installato: salto le richieste vere"

    sessione = requests.Session()
    intestazioni = {"Content-Type": "application/json"}
    tempi = []
    errori = []
    # Prima richiesta a vuoto: apre la connessione e scalda la sessione, il
    # suo tempo comprende l'handshake e falserebbe la media.
    try:
        sessione.post(f"https://{HOST}/graphql", data=QUERY,
                      headers=intestazioni, timeout=20)
    except Exception as e:
        return [], f"non raggiungibile: {e}"

    for _ in range(CAMPIONI_RICHIESTA):
        inizio = time.perf_counter()
        try:
            r = sessione.post(f"https://{HOST}/graphql", data=QUERY,
                              headers=intestazioni, timeout=20)
            tempi.append((time.perf_counter() - inizio) * 1000)
            if r.status_code == 429:
                errori.append("429 (tetto anonimo di 20 richieste/minuto)")
                break
        except Exception as e:
            errori.append(str(e)[:80])
        time.sleep(0.4)
    return tempi, ("; ".join(errori) if errori else None)


def carica_misure():
    if not os.path.exists(FILE_MISURE):
        return []
    try:
        with open(FILE_MISURE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def stampa_confronto(misure):
    if not misure:
        print("\nNessuna misura ancora salvata.")
        return

    # Se una connessione e' stata misurata piu' volte, vince l'ultima: si
    # rimisura proprio quando la precedente non convince piu'.
    ultima_per_nome = {}
    for m in misure:
        ultima_per_nome[m["connessione"]] = m

    print("\n" + "=" * 74)
    print("CONFRONTO FRA LE CONNESSIONI MISURATE")
    print("=" * 74)
    print("\nAPERTURA DI CONNESSIONE (latenza pura di rete -- e' su questa che si decide)")
    print(f"  {'connessione':<16} {'mediana':>9} {'minimo':>9} {'p90':>9} {'massimo':>9} {'tremolio':>9}")
    for nome, m in sorted(ultima_per_nome.items(),
                          key=lambda kv: kv[1]["connessione_tcp_tls"]["mediana"]):
        s = m["connessione_tcp_tls"]
        tremolio = s["p90"] - s["mediana"]
        print(f"  {nome:<16} {s['mediana']:>7.0f}ms {s['min']:>7.0f}ms "
              f"{s['p90']:>7.0f}ms {s['max']:>7.0f}ms {tremolio:>7.0f}ms")

    print("\nRICHIESTA VERA (comprende il lavoro del server, uguale per tutte)")
    print(f"  {'connessione':<16} {'mediana':>9} {'minimo':>9} {'p90':>9} {'massimo':>9}")
    for nome, m in sorted(ultima_per_nome.items(),
                          key=lambda kv: (kv[1].get("richiesta_graphql") or {}).get("mediana", 1e9)):
        s = m.get("richiesta_graphql")
        if not s:
            print(f"  {nome:<16}   (non misurata: {m.get('nota_richiesta') or 'ignoto'})")
            continue
        print(f"  {nome:<16} {s['mediana']:>7.0f}ms {s['min']:>7.0f}ms "
              f"{s['p90']:>7.0f}ms {s['max']:>7.0f}ms")

    print("\nPer riferimento, misurato il 12/08/2026:")
    print("  runner GitHub    mediana 168ms, picchi 382ms  (richiesta vera)")
    print("  PC di casa       mediana  82ms, picchi 189ms  (richiesta vera)")

    if len(ultima_per_nome) < 2:
        print("\nUna sola connessione misurata: rifai la misura sull'altra rete")
        print("per avere il confronto.")
        return

    ordinate = sorted(ultima_per_nome.items(),
                      key=lambda kv: kv[1]["connessione_tcp_tls"]["mediana"])
    prima_nome, prima = ordinate[0]
    seconda_nome, seconda = ordinate[1]
    scarto = seconda["connessione_tcp_tls"]["mediana"] - prima["connessione_tcp_tls"]["mediana"]
    tremolio_prima = prima["connessione_tcp_tls"]["p90"] - prima["connessione_tcp_tls"]["mediana"]
    tremolio_seconda = seconda["connessione_tcp_tls"]["p90"] - seconda["connessione_tcp_tls"]["mediana"]

    print("\n" + "-" * 74)
    print("VERDETTO")
    print("-" * 74)
    # Soglia dichiarata invece che implicita: sotto i 5 ms di scarto due
    # connessioni non si distinguono da una sola misurata due volte.
    if abs(scarto) < 5:
        print(f"  {prima_nome} e {seconda_nome} sono equivalenti ({abs(scarto):.0f}ms di")
        print("  differenza, meno del tremolio normale fra due misure).")
        print("  Scegli in base alla regolarita': ", end="")
        print(f"{prima_nome} tremola {tremolio_prima:.0f}ms, {seconda_nome} {tremolio_seconda:.0f}ms.")
    else:
        print(f"  Vince {prima_nome}: {scarto:.0f}ms in meno di {seconda_nome} su ogni")
        print("  apertura di connessione.")
        if tremolio_prima > tremolio_seconda * 1.5:
            print(f"  ATTENZIONE pero': {prima_nome} e' piu' ballerina ({tremolio_prima:.0f}ms di")
            print(f"  tremolio contro {tremolio_seconda:.0f}ms). Nello sniping si perde proprio nei")
            print("  momenti brutti, quindi vale la pena rimisurare prima di decidere.")


def main():
    argomenti = [a for a in sys.argv[1:] if a.strip()]

    if argomenti and argomenti[0] in ("--confronto", "-c"):
        stampa_confronto(carica_misure())
        return 0

    if not argomenti:
        print(__doc__)
        print("\nManca il nome della connessione. Esempio:")
        print("    python misura_latenza_sorare.py fibra")
        return 1

    nome = argomenti[0].strip().lower()

    print(f"Misuro la latenza verso {HOST} sulla connessione '{nome}'.")
    print("Non cambiare rete e non scaricare niente di pesante fino alla fine.\n")

    print(f"  1/2  apertura di connessione, {CAMPIONI_CONNESSIONE} campioni "
          f"(~{CAMPIONI_CONNESSIONE * 0.2:.0f} secondi)")
    tempi_conn, falliti = misura_apertura_connessione()
    if not tempi_conn:
        print("\n  NESSUNA connessione riuscita: la rete non raggiunge Sorare.")
        return 1
    riassunto_conn = _riassumi(tempi_conn)
    if falliti:
        print(f"    {falliti} tentativi su {CAMPIONI_CONNESSIONE} FALLITI "
              f"-- una connessione che perde colpi e' gia' un motivo per scartarla.")
    print(f"    mediana {riassunto_conn['mediana']:.0f}ms | "
          f"minimo {riassunto_conn['min']:.0f}ms | "
          f"p90 {riassunto_conn['p90']:.0f}ms | "
          f"massimo {riassunto_conn['max']:.0f}ms")

    print(f"\n  2/2  richieste vere, {CAMPIONI_RICHIESTA} campioni")
    tempi_req, nota = misura_richiesta_vera()
    riassunto_req = _riassumi(tempi_req) if tempi_req else None
    if riassunto_req:
        print(f"    mediana {riassunto_req['mediana']:.0f}ms | "
              f"minimo {riassunto_req['min']:.0f}ms | "
              f"p90 {riassunto_req['p90']:.0f}ms | "
              f"massimo {riassunto_req['max']:.0f}ms")
    if nota:
        print(f"    nota: {nota}")

    misure = carica_misure()
    misure.append({
        "connessione": nome,
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "connessione_tcp_tls": riassunto_conn,
        "aperture_fallite": falliti,
        "richiesta_graphql": riassunto_req,
        "nota_richiesta": nota,
    })
    with open(FILE_MISURE, "w", encoding="utf-8") as f:
        json.dump(misure, f, indent=2, ensure_ascii=False)
    print(f"\n  salvato in {os.path.basename(FILE_MISURE)}")

    stampa_confronto(misure)
    return 0


if __name__ == "__main__":
    sys.exit(main())
