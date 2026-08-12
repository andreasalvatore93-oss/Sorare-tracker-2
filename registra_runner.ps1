# Registra e avvia i runner self-hosted sul PC di casa.
#
# L'intervallo si passa come argomento:  .
egistra_runner.ps1 11 12
# Senza argomenti fa 2..10 (il primo giro, 12/08/2026).
# Chi e' gia' registrato viene saltato, quindi rilanciarlo non fa danno.
# DA LANCIARE IN POWERSHELL COME AMMINISTRATORE: l'installazione di un
# servizio Windows richiede l'elevazione, e non c'e' modo di aggirarla.
#
# Il runner numero 1 (C:\actions-runner) esiste gia' e non viene toccato.
#
# Cosa fa, per ciascuno dei nove:
#   - chiede a GitHub un token di registrazione nuovo (scadono in un'ora)
#   - registra il runner sul repo con nome pc-andrea-N ed etichetta "casa"
#   - lo installa come servizio Windows che parte da solo all'accensione
#
# Per disfare tutto: vedi in fondo.

param([int]$Da = 2, [int]$A = 10)

$ErrorActionPreference = 'Stop'
$repo = 'andreasalvatore93-oss/Sorare-tracker-2'
$url  = "https://github.com/$repo"

Write-Host "Registro i runner $Da..$A sul repo $repo" -ForegroundColor Cyan
Write-Host ""

foreach ($i in $Da..$A) {
    $dir = "C:\actions-runner-$i"
    $nome = "pc-andrea-$i"

    if (-not (Test-Path "$dir\config.cmd")) {
        Write-Host "  $nome : cartella mancante, salto" -ForegroundColor Yellow
        continue
    }
    if (Test-Path "$dir\.runner") {
        Write-Host "  $nome : gia' registrato, salto" -ForegroundColor DarkGray
        continue
    }

    # token nuovo per ognuno: e' a uso singolo e dura un'ora
    $token = (gh api -X POST "repos/$repo/actions/runners/registration-token" --jq .token)
    if (-not $token) {
        Write-Host "  $nome : non sono riuscito a ottenere il token (gh e' autenticato?)" -ForegroundColor Red
        continue
    }

    Push-Location $dir
    & .\config.cmd --url $url --token $token --name $nome --labels casa `
                   --work _work --unattended --replace `
                   --runasservice --windowslogonaccount "NT AUTHORITY\NETWORK SERVICE"
    Pop-Location

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  $nome : registrato e avviato" -ForegroundColor Green
    } else {
        Write-Host "  $nome : errore (codice $LASTEXITCODE)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Runner ora registrati su GitHub:" -ForegroundColor Cyan
gh api "repos/$repo/actions/runners" --jq '.runners[] | "  \(.name)  \(.status)"'

# ---------------------------------------------------------------------------
# PER DISFARE TUTTO (sempre da amministratore):
#   foreach ($i in 2..10) {
#     $d = "C:\actions-runner-$i"
#     $t = (gh api -X POST "repos/andreasalvatore93-oss/Sorare-tracker-2/actions/runners/remove-token" --jq .token)
#     Push-Location $d; & .\config.cmd remove --token $t; Pop-Location
#     Remove-Item $d -Recurse -Force
#   }
# ---------------------------------------------------------------------------
