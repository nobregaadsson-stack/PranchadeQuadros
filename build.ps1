# Gera o executável do Prancha de Quadros (Windows 10/11, 64 bits).
#
# Uso (PowerShell, na pasta do projeto):
#   powershell -ExecutionPolicy Bypass -File .\build.ps1            # compila, testa e empacota
#   powershell -ExecutionPolicy Bypass -File .\build.ps1 -SemTestes # pula o pytest
#
# Resultado: dist\PranchaQuadros\PranchaQuadros.exe  e  dist\PranchaQuadros-1.0.0-win64.zip
# A conexão com a internet só é necessária na PRIMEIRA execução deste script (pip install).

param([switch]$SemTestes)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Criando ambiente virtual (.venv) com Python 3.14..."
    py -V:3.14 -m venv .venv
    if (-not $?) { throw "Falha ao criar o ambiente virtual. Instale o Python 3.14 (64 bits) de python.org." }
}

Write-Host "Instalando dependências fixadas..."
& $py -m pip install --disable-pip-version-check --only-binary=:all: -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências." }

if (-not $SemTestes) {
    Write-Host "Executando testes automatizados..."
    $env:QT_QPA_PLATFORM = "offscreen"
    & $py -m pytest -q tests
    Remove-Item Env:\QT_QPA_PLATFORM
    if ($LASTEXITCODE -ne 0) { throw "Os testes falharam; o executável não foi gerado." }
}

Write-Host "Gerando executável com PyInstaller..."
& $py -m PyInstaller --noconfirm --clean PranchaQuadros.spec
if ($LASTEXITCODE -ne 0) { throw "Falha no PyInstaller." }

$exe = "dist\PranchaQuadros\PranchaQuadros.exe"
Write-Host "Executando o autoteste do executável gerado..."
$env:QT_QPA_PLATFORM = "offscreen"
$p = Start-Process -FilePath $exe -ArgumentList "--autoteste" -Wait -PassThru
Remove-Item Env:\QT_QPA_PLATFORM
Get-Content "$env:LOCALAPPDATA\PranchaQuadros\autoteste.txt" -Encoding UTF8
if ($p.ExitCode -ne 0) { throw "O autoteste do executável falhou (código $($p.ExitCode))." }

Copy-Item README.md, LICENSES.md "dist\PranchaQuadros\" -Force
Copy-Item docs\MANUAL_DO_USUARIO.md "dist\PranchaQuadros\" -Force
$zip = "dist\PranchaQuadros-1.0.0-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\PranchaQuadros" -DestinationPath $zip
Write-Host ""
Write-Host "Pronto: $exe"
Write-Host "Pacote para distribuição: $zip"
