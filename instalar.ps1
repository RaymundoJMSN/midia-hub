# Instala o menu de contexto "Mídia" do Mídia Hub (HKCU, sem UAC).
# Rodar de novo atualiza (relê presets.json). -Desinstalar remove tudo.
# Usar pwsh (não o PowerShell 5.1 antigo): pwsh -File instalar.ps1
param([switch]$Desinstalar)

$ErrorActionPreference = 'Stop'
$aqui = $PSScriptRoot
$python = (Get-Command python).Source
$midia = Join-Path $aqui 'midia.py'
# reg.exe em vez do provider HKCU: por causa da chave literal "*" (PS trata * como wildcard)
$classes = 'HKCU\Software\Classes'

$presets = Get-Content (Join-Path $aqui 'presets.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$todasExts = $presets.PSObject.Properties.Value.exts | Where-Object { $_ -ne '*' } | Sort-Object -Unique

# limpa instalação anterior (também é o caminho do -Desinstalar)
foreach ($ext in $todasExts) {
    reg delete "$classes\SystemFileAssociations\$ext\shell\MidiaHub" /f 2>$null | Out-Null
}
reg delete "$classes\*\shell\MidiaHubCompactar" /f 2>$null | Out-Null
reg delete "$classes\Directory\shell\MidiaHubCompactar" /f 2>$null | Out-Null
if ($Desinstalar) { Write-Host 'Menu removido.'; exit 0 }

function New-Verbo($chavePai, $nome, $rotulo, $preset) {
    $k = "$chavePai\shell\$nome"
    reg add $k /v MUIVerb /t REG_SZ /d $rotulo /f | Out-Null
    reg add "$k\command" /ve /t REG_SZ /f /d `
        "cmd /d /c chcp 65001>nul & `"$python`" `"$midia`" --spool $preset `"%1`"" | Out-Null
}

function New-Submenu($raiz, $rotulo, $propriedades) {
    reg add $raiz /v MUIVerb /t REG_SZ /d $rotulo /f | Out-Null
    reg add $raiz /v SubCommands /t REG_SZ /d '' /f | Out-Null
    $i = 0
    foreach ($p in $propriedades) {
        # prefixo numérico: o submenu ordena alfabeticamente pelo nome da chave
        New-Verbo $raiz ('{0:d2}-{1}' -f $i, $p.Name) $p.Value.rotulo $p.Name
        $i++
    }
}

# menu "Mídia" por extensão, só com os presets que aceitam aquela extensão
foreach ($ext in $todasExts) {
    $doExt = $presets.PSObject.Properties | Where-Object { $_.Value.exts -contains $ext }
    if ($doExt) {
        New-Submenu "$classes\SystemFileAssociations\$ext\shell\MidiaHub" 'Mídia' $doExt
    }
}

# menu "Compactar" em qualquer arquivo e em pastas (separado pra não duplicar "Mídia")
$compactar = $presets.PSObject.Properties | Where-Object { $_.Value.categoria -eq 'compactar' }
New-Submenu "$classes\*\shell\MidiaHubCompactar" 'Compactar' $compactar
New-Submenu "$classes\Directory\shell\MidiaHubCompactar" 'Compactar' $compactar

$n = ($todasExts | Measure-Object).Count
Write-Host "Menu 'Mídia' instalado para $n extensões + 'Compactar' em arquivos e pastas."
Write-Host "No Win11 fica em 'Mostrar mais opções'. Rodar de novo atualiza; -Desinstalar remove."
