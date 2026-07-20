// decrypt_and_sign.js
//
// OTTIMIZZAZIONE VELOCITA' SNIPING (21/07, richiesta esplicita utente -- "trova il
// modo di aumentare la velocita' di sniping"): questo script NON e' piu' un
// processo "usa e getta" avviato ad ogni singola firma. Ora resta VIVO per tutta
// la durata della run del bot Python e riceve richieste ripetute via un protocollo
// a righe su stdin/stdout: una riga JSON in input = una richiesta, una riga JSON in
// output = una risposta. Il motivo: avviare Node da zero e caricare il modulo
// @sorare/crypto (require, parsing, inizializzazione) costa tipicamente qualche
// centinaio di millisecondi -- costo fisso pagato ad OGNI acquisto/offerta nella
// vecchia modalita' one-shot, anche quando la chiave privata era gia' cachata lato
// Python e non serviva rifare il decrypt. Con il processo persistente questo costo
// si paga UNA SOLA VOLTA all'avvio del bot, non ad ogni tentativo -- diretto
// beneficio sulla velocita' di reazione quando si compete con altri bot sullo
// stesso annuncio.
//
// La logica crittografica (decrypt PBKDF2+AES-GCM, firma via @sorare/crypto) e'
// IDENTICA a prima, byte per byte -- questo cambio tocca SOLO il meccanismo di
// I/O (un loop che processa una richiesta alla volta invece di leggere tutto lo
// stdin una volta sola e uscire), non la logica di business.
//
// Protocollo (per riga, NDJSON):
//   Richiesta identica al vecchio payload one-shot:
//     {"password": "...", "encryptedPrivateKey": "...", "iv": "...", "salt": "...",
//      "authorizationRequest": {...}}
//   oppure, dalla seconda richiesta della sessione in poi (chiave gia' cachata
//   lato Python in _decrypted_key_cache):
//     {"decryptedPrivateKey": "0x...", "authorizationRequest": {...}}
//   Risposta (una riga JSON, sempre e comunque -- mai piu' righe, mai meno):
//     {"signature": "...", "decryptedPrivateKey": "0x..."} in caso di successo
//     {"error": "..."} in caso di fallimento
//   Un errore su una richiesta NON termina il processo: il loop continua e resta
//   pronto per la richiesta successiva (fail-safe, stesso principio "mai un
//   crash silenzioso" gia' seguito lato Python).
//
// Algoritmo di decrypt confermato ispezionando wallet.sorare.com/src/lib/encryption.ts:
//   1) PBKDF2(password, salt, iterations=50000, hash=SHA-256) -> chiave AES-GCM-256
//   2) AES-GCM-decrypt(encryptedPrivateKey, iv, chiave) -> chiave privata Starkware in chiaro
// Poi @sorare/crypto.signAuthorizationRequest(privateKey, authorizationRequest) firma --
// funzione CONFERMATA nel repo ufficiale github.com/sorare/api/examples/authorizations.js,
// gestisce internamente qualsiasi tipo di authorization (Starkex transfer/limit order,
// Mangopay wallet transfer) in base al campo __typename dell'oggetto passato.
//
// Uso (protocollo persistente, come lanciato dal bot Python):
//   node decrypt_and_sign.js
//   (poi una riga JSON in stdin per ogni richiesta, per tutta la vita del processo)

const { webcrypto } = require('crypto');
const readline = require('readline');
const subtle = webcrypto.subtle;

let sorareCrypto;
let sorareCryptoError = null;
try {
  sorareCrypto = require('@sorare/crypto');
} catch (e) {
  // Non usciamo subito: registriamo l'errore e lo restituiamo alla PRIMA richiesta
  // che arriva (invece che morire silenziosamente prima ancora di poter rispondere
  // qualcosa al chiamante Python, che altrimenti resterebbe in attesa su una riga
  // che non arrivera' mai).
  sorareCryptoError = e;
}

function base64ToBuffer(b64) {
  return Uint8Array.from(Buffer.from(b64, 'base64'));
}

async function deriveAesKey(password, saltB64) {
  const salt = base64ToBuffer(saltB64);
  const passwordKey = await subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );
  return subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: 50000, hash: { name: 'SHA-256' } },
    passwordKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );
}

async function decryptPrivateKey({ password, encryptedPrivateKey, iv, salt }) {
  const aesKey = await deriveAesKey(password, salt);
  const ivBuf = base64ToBuffer(iv);
  const ciphertext = base64ToBuffer(encryptedPrivateKey);
  const plainBuf = await subtle.decrypt(
    { name: 'AES-GCM', iv: ivBuf, tagLength: 128 },
    aesKey,
    ciphertext
  );
  // FIX 19/07 (confermato dal vivo con firma generata con successo): il buffer
  // decriptato e' di 64 byte, non testo UTF-8 -- la chiave privata Starkware valida
  // (32 byte) sono gli ULTIMI 32 byte del buffer (i primi 32 byte sono altro, probabile
  // padding/prefisso interno del formato usato da Sorare, non ancora identificato nel
  // dettaglio ma non necessario: gli ultimi 32 byte producono una firma valida e
  // accettata dalla libreria @sorare/crypto).
  const bytes = new Uint8Array(plainBuf).slice(-32);
  const hex = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
  return '0x' + hex;
}

// Elabora UNA richiesta e ritorna l'oggetto risposta (mai lancia -- ogni eccezione
// e' catturata e trasformata in {error: ...}, cosi' il loop chiamante puo' sempre
// scrivere una riga di risposta e andare avanti, qualunque cosa succeda).
async function handleRequest(params) {
  if (sorareCryptoError || !sorareCrypto || typeof sorareCrypto.signAuthorizationRequest !== 'function') {
    return {
      error: '@sorare/crypto non e\' installato o non espone signAuthorizationRequest -- '
        + 'verificare "npm install @sorare/crypto" e la versione installata'
        + (sorareCryptoError ? ` (dettaglio: ${sorareCryptoError.message})` : '')
    };
  }

  // OTTIMIZZAZIONE VELOCITA' (20/07, invariata): se il payload contiene gia'
  // 'decryptedPrivateKey' (esadecimale, formato "0x..."), SALTIAMO il decrypt
  // PBKDF2(50000 iterazioni)+AES-GCM -- identico ad ogni chiamata nella stessa
  // sessione (stessa password/encryptedPrivateKey/iv/salt, gia' cachati lato
  // Python in _encrypted_key_cache) -- e firmiamo direttamente con la chiave
  // gia' in chiaro.
  if (params.decryptedPrivateKey) {
    try {
      const signature = sorareCrypto.signAuthorizationRequest(
        params.decryptedPrivateKey, params.authorizationRequest);
      return { signature };
    } catch (e) {
      return { error: `firma fallita: ${e.message}` };
    }
  }

  const { password, encryptedPrivateKey, iv, salt, authorizationRequest } = params;
  if (!password || !encryptedPrivateKey || !iv || !salt || !authorizationRequest) {
    return { error: 'parametri mancanti (servono password, encryptedPrivateKey, iv, salt, authorizationRequest)' };
  }

  let privateKey;
  try {
    privateKey = await decryptPrivateKey({ password, encryptedPrivateKey, iv, salt });
  } catch (e) {
    // Con AES-GCM una password sbagliata fa fallire la verifica del tag di autenticazione
    // (decrypt lancia eccezione), quindi questo blocco copre anche "password errata".
    return { error: `decrypt fallito (password errata o dati corrotti): ${e.message}` };
  }

  try {
    const signature = sorareCrypto.signAuthorizationRequest(privateKey, authorizationRequest);
    // Restituiamo ANCHE la chiave decriptata (in chiaro, esadecimale) insieme alla
    // firma -- il chiamante Python la salva in cache e la riusa nelle chiamate
    // successive della stessa sessione (vedi ramo 'decryptedPrivateKey' sopra),
    // saltando il decrypt PBKDF2+AES-GCM dalla seconda chiamata in poi.
    return { signature, decryptedPrivateKey: privateKey };
  } catch (e) {
    return { error: `firma fallita: ${e.message}` };
  }
}

async function main() {
  const rl = readline.createInterface({ input: process.stdin, terminal: false });

  for await (const rawLine of rl) {
    const line = rawLine.trim();
    if (!line) continue;  // riga vuota, la ignoriamo e restiamo in ascolto

    let params;
    try {
      params = JSON.parse(line);
    } catch (e) {
      process.stdout.write(JSON.stringify({ error: `input JSON non valido: ${e.message}` }) + '\n');
      continue;
    }

    let result;
    try {
      result = await handleRequest(params);
    } catch (e) {
      // Rete di sicurezza finale: handleRequest non dovrebbe mai lanciare (ogni
      // ramo interno ha gia' il proprio try/catch), ma se succedesse comunque
      // qualcosa di inatteso, il processo NON deve morire silenziosamente --
      // rispondiamo con un errore esplicito e restiamo pronti per la prossima riga.
      result = { error: `eccezione interna inattesa: ${e.message}` };
    }
    process.stdout.write(JSON.stringify(result) + '\n');
  }
  // stdin chiuso (il processo Python e' terminato o ha chiuso la pipe): usciamo
  // puliti, non c'e' altro da fare.
}

main().catch((e) => {
  // Errore fatale nel loop stesso (non in una singola richiesta): a questo punto
  // non c'e' piu' un ciclo che possa rispondere, quindi logghiamo su stderr (mai
  // su stdout, che e' riservato alle risposte NDJSON) ed usciamo con codice diverso
  // da zero, cosi' il chiamante Python capisce che il processo e' morto e puo'
  // riavviarlo.
  process.stderr.write(`[decrypt_and_sign] errore fatale nel loop principale: ${e && e.stack ? e.stack : e}\n`);
  process.exit(1);
});
