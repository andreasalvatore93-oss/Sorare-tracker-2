// decrypt_and_sign.js
//
// Input (via stdin, JSON): {
//   "password": "...",              // password del wallet Sorare
//   "encryptedPrivateKey": "...",    // base64, da FetchEncryptedPrivateKey
//   "iv": "...",                     // base64, da FetchEncryptedPrivateKey
//   "salt": "...",                   // base64, da FetchEncryptedPrivateKey
//   "authorizationRequest": {        // l'intero oggetto "request" cosi' com'e' restituito
//     "__typename": "MangopayWalletTransferAuthorizationRequest",
//     "nonce": 12345,
//     "amount": ...,
//     "currency": "EUR",
//     "operationHash": "0x...",
//     "mangopayWalletId": "..."
//   }
// }
//
// Output (stdout, JSON): { "signature": "..." } oppure { "error": "..." }
//
// Algoritmo di decrypt confermato ispezionando wallet.sorare.com/src/lib/encryption.ts:
//   1) PBKDF2(password, salt, iterations=50000, hash=SHA-256) -> chiave AES-GCM-256
//   2) AES-GCM-decrypt(encryptedPrivateKey, iv, chiave) -> chiave privata Starkware in chiaro
// Poi @sorare/crypto.signAuthorizationRequest(privateKey, authorizationRequest) firma --
// funzione CONFERMATA nel repo ufficiale github.com/sorare/api/examples/authorizations.js,
// gestisce internamente qualsiasi tipo di authorization (Starkex transfer/limit order,
// Mangopay wallet transfer) in base al campo __typename dell'oggetto passato.
//
// Uso: echo '{"password":"...", ...}' | node decrypt_and_sign.js

const { webcrypto } = require('crypto');
const subtle = webcrypto.subtle;

let sorareCrypto;
try {
  sorareCrypto = require('@sorare/crypto');
} catch (e) {
  // gestito piu' sotto: errore chiaro se il pacchetto non e' installato
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
  // La chiave privata Starkware decriptata e' testo (probabilmente hex con prefisso 0x,
  // da confermare contro un caso reale) -- decodifichiamo come UTF-8.
  return new TextDecoder().decode(plainBuf);
}

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  let params;
  try {
    params = JSON.parse(input);
  } catch (e) {
    console.log(JSON.stringify({ error: `input JSON non valido: ${e.message}` }));
    process.exit(1);
  }

  const { password, encryptedPrivateKey, iv, salt, authorizationRequest } = params;
  if (!password || !encryptedPrivateKey || !iv || !salt || !authorizationRequest) {
    console.log(JSON.stringify({ error: 'parametri mancanti (servono password, encryptedPrivateKey, iv, salt, authorizationRequest)' }));
    process.exit(1);
  }

  let privateKey;
  try {
    privateKey = await decryptPrivateKey({ password, encryptedPrivateKey, iv, salt });
  } catch (e) {
    // Con AES-GCM una password sbagliata fa fallire la verifica del tag di autenticazione
    // (decrypt lancia eccezione), quindi questo blocco copre anche "password errata".
    console.log(JSON.stringify({ error: `decrypt fallito (password errata o dati corrotti): ${e.message}` }));
    process.exit(1);
  }

  if (!sorareCrypto || typeof sorareCrypto.signAuthorizationRequest !== 'function') {
    console.log(JSON.stringify({
      error: '@sorare/crypto non e\' installato o non espone signAuthorizationRequest -- verificare "npm install @sorare/crypto" e la versione installata'
    }));
    process.exit(1);
  }

  try {
    const signature = sorareCrypto.signAuthorizationRequest(privateKey, authorizationRequest);
    console.log(JSON.stringify({ signature }));
  } catch (e) {
    console.log(JSON.stringify({ error: `firma fallita: ${e.message}` }));
    process.exit(1);
  }
}

main();
