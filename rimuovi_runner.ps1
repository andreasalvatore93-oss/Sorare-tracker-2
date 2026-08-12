# Toglie dei runner self-hosted dal PC di casa: ferma il servizio, li
# scollega da GitHub e cancella la cartella.
#
# DA LANCIARE IN POWERSHELL COME AMMINISTRATORE (disinstallare un servizio
# Windows richiede l'elevazione, non c'e' modo di aggirarla).
#
#   .\rimuovi_runner.ps1 3 10      -> toglie dal 3 al 10
#
# Il runner 1 (C:\actions-runner) NON si tocca mai: e' quello registrato per
# primo. Chi non risulta registrato viene solo cancellato come cartella.
#
# PERCHE' (12/08/2026): ne erano stati montati 10 per far girare il generatore
# di formazioni in casa. Misurato che non conviene (le "dieci macchine" sono un
# PC solo: un disco, 16 GB di RAM, e dieci copie da 337 MB della stessa cache),
# il generatore e' tornato su ubuntu-latest. Restano utili SOLO a
# bot_definitivo, che e' un job unico e lungo dove conta la latenza verso
# Sorare (82 ms da casa contro 168 da GitHub). Per un job solo ne bastano due
# -- il secondo e' la scorta se il primo resta appeso.
#
# ATTENZIONE: lanciarlo mentre una run sta usando quei runner la fa fallire.
# Controllare prima che non ci sia niente in corso.

param([int]$Da, [int]$A)

$ErrorActionPreference = 'Continue'
$repo = 'andreasalvatore93-oss/Sorare-tracker-2'

if (-not $Da -or -not $A) {
    Write-Host "Uso: .\rimuovi_runner.ps1 <da> <a>   (esempio: .\rimuovi_runner.ps1 3 20)" -ForegroundColor Yellow
    exit 1
}

Write-Host "Tolgo i runner $Da..$A dal repo $repo" -ForegroundColor Cyan
Write-Host ""

foreach ($i in $Da..$A) {
    $dir = "C:\actions-runner-$i"
    if (-not (Test-Path $dir)) { continue }

    if (Test-Path "$dir\.runner") {
        $token = (gh api -X POST "repos/$repo/actions/runners/remove-token" --jq .token)
        if ($token) {
            Push-Location $dir
            & .\config.cmd remove --token $token
            Pop-Location
        } else {
            Write-Host "  runner $i : nessun token (gh e' autenticato?), cancello solo la cartella" -ForegroundColor Yellow
        }
    }

    Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $dir) {
        Write-Host "  runner $i : cartella NON cancellata (file in uso?)" -ForegroundColor Red
    } else {
        Write-Host "  runner $i : tolto" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Runner ancora registrati su GitHub:" -ForegroundColor Cyan
gh api "repos/$repo/actions/runners" --jq '.runners[] | "  \(.name)  \(.status)"'
Write-Host ""
Write-Host "Spazio libero su C: $([math]::Round((Get-PSDrive C).Free/1GB)) GB" -ForegroundColor Cyan
