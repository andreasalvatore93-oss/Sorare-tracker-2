// decrypt_and_sign.js

const { webcrypto } = require('crypto');
const subtle = webcrypto.subtle;

let sorareCrypto;
try {
  sorareCrypto = require('@sorare/crypto');
} catch (e) {
  // gestito più sotto
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
    {
      name: 'PBKDF2',
      salt,
      iterations: 50000,
      hash: { name: 'SHA-256' }
    },
    passwordKey,
    {
      name: 'AES-GCM',
      length: 256
    },
    false,
    ['encrypt', 'decrypt']
  );
}

async function decryptPrivateKey({ password, encryptedPrivateKey, iv, salt }) {
  const aesKey = await deriveAesKey(password, salt);

  const ivBuf = base64ToBuffer(iv);
  const ciphertext = base64ToBuffer(encryptedPrivateKey);

  const plainBuf = await subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: ivBuf,
      tagLength: 128
    },
    aesKey,
    ciphertext
  );

  return new TextDecoder().decode(plainBuf);
}

async function main() {
  let input = '';

  for await (const chunk of process.stdin) {
    input += chunk;
  }

  let params;

  try {
    params = JSON.parse(input);
  } catch (e) {
    console.log(JSON.stringify({
      error: `input JSON non valido: ${e.message}`
    }));
    process.exit(1);
  }

  const {
    password,
    encryptedPrivateKey,
    iv,
    salt,
    authorizationRequest
  } = params;

  if (!password || !encryptedPrivateKey || !iv || !salt || !authorizationRequest) {
    console.log(JSON.stringify({
      error: 'parametri mancanti'
    }));
    process.exit(1);
  }

  let privateKey;

  try {
    privateKey = await decryptPrivateKey({
      password,
      encryptedPrivateKey,
      iv,
      salt
    });

    // ================= DEBUG =================

    console.error("[debug] privateKey length:", privateKey.length);
    console.error("[debug] privateKey preview:", privateKey.slice(0, 12));
    console.error("[debug] privateKey:", JSON.stringify(privateKey));

    console.error("[debug] encryptedPrivateKey length:", encryptedPrivateKey.length);
    console.error("[debug] iv length:", iv.length);
    console.error("[debug] salt length:", salt.length);

    // =========================================

  } catch (e) {

    console.error("[debug] decrypt exception:");
    console.error(e.stack);

    console.log(JSON.stringify({
      error: `decrypt fallito (password errata o dati corrotti): ${e.message}`
    }));
    process.exit(1);
  }

  if (!sorareCrypto || typeof sorareCrypto.signAuthorizationRequest !== 'function') {
    console.log(JSON.stringify({
      error: "@sorare/crypto non installato o versione errata"
    }));
    process.exit(1);
  }

  try {

    console.error("[debug] authorizationRequest:");
    console.error(JSON.stringify(authorizationRequest, null, 2));

    const signature = sorareCrypto.signAuthorizationRequest(
      privateKey,
      authorizationRequest
    );

    console.log(JSON.stringify({
      signature
    }));

  } catch (e) {

    console.error("[debug] signAuthorizationRequest exception:");
    console.error(e.stack);

    console.log(JSON.stringify({
      error: `firma fallita: ${e.message}`
    }));

    process.exit(1);
  }
}

main();
