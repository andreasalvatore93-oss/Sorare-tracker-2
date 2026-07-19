name: Test Firma Starkware (isolato, NESSUN acquisto reale)
on:
  workflow_dispatch:
    inputs:
      test_fingerprint:
        description: "Fingerprint da una prenotazione gia' fatta (vedi log di una run precedente di AutoBuy, es. caso Sergey Pinyaev)"
        required: true
      test_authorization_request:
        description: "Oggetto 'request' completo in JSON (vedi log, campo 'request' dentro authorizations[0]) -- includere currency/amount/mangopayWalletId/nonce/operationHash"
        required: true
permissions:
  contents: read
jobs:
  test-signature:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install sorare-sign dependencies
        run: |
          cd sorare-sign
          npm install
      - run: pip install requests
      - name: Test firma (isolato, nessun acquisto)
        env:
          SORARE_COOKIE: ${{ secrets.SORARE_COOKIE }}
          SORARE_CSRF: ${{ secrets.SORARE_CSRF }}
          SORARE_WALLET_PASSWORD: ${{ secrets.SORARE_WALLET_PASSWORD }}
          TEST_FINGERPRINT: ${{ github.event.inputs.test_fingerprint }}
          TEST_AUTHORIZATION_REQUEST: ${{ github.event.inputs.test_authorization_request }}
        run: python test_signature_isolated.py
