# Mídia Hub — spec

Um lugar só pra comprimir/converter/melhorar qualquer mídia no Windows, substituindo os .bat
espalhados (`E:\rayna\Games\RealESRGAN\Executar.bat`, `comprimir - muito.bat`,
`comprimir_imagem_sem perda.bat`).

Decidido em 2026-08-15 com Ray: **A→B em fases, motor compartilhado**.

## Estrutura

```
Soltos\midia-hub\        ← código (repo git RaymundoJMSN/midia-hub, público)
  midia.py               ← CLI única: midia.py <preset> <arquivos...>  (Python stdlib pura)
  presets.json           ← todos os presets, editável na mão
  instalar.ps1           ← registra menu de contexto (HKCU, sem UAC), copia binários pro X:
  spec.md, README.md
X:\midia-hub\            ← binários + modelos (C: lotou em 2026-08)
  bin\gs\                ← Ghostscript portátil (instalador oficial extraído com 7-Zip)
  bin\realesrgan\        ← realesrgan-ncnn-vulkan + models\ (copiado de E:\rayna\Games\RealESRGAN)
```

Ferramentas já no sistema (não vendorizar): ffmpeg 8.1 full (winget, no PATH) com
av1_amf/hevc_amf/h264_amf (GPU RX 9070 XT), libaom (AVIF), libwebp, libopus, libmp3lame;
7-Zip em `C:\Program Files\7-Zip`.

## Fase 1 — motor + menu de contexto

`midia.py <preset> <arquivos...>`:
- Preset declara extensões aceitas; arquivo incompatível é pulado com aviso.
- Saída na mesma pasta, sufixo `_<preset>`; nunca sobrescreve (acrescenta ` (2)`).
- Sequencial; erro num arquivo não para os outros; resumo no fim (ok/falhou, tamanho antes→depois).
- `midia.py --check` valida binários e presets.
- `midia.py --listar` lista presets.

Presets iniciais:

| Categoria | Preset | Como |
|---|---|---|
| Imagem | webp-leve | cwebp/ffmpeg libwebp q75 |
| | webp-boa | q90 (equivale ao .bat antigo "sem perda", que era lossy) |
| | webp-sem-perda | `-lossless 1` (sem perda DE VERDADE) |
| | avif | libaom crf~28, lento e pequeno |
| | menor-1920 | redimensiona lado maior p/ 1920 + webp q85 |
| IA | upscale-4x | realesrgan-x4plus |
| | upscale-4x-anime | realesrgan-x4plus-anime |
| | restaurar | upscale 4x → downscale pro tamanho original (limpa artefatos) |
| Vídeo | video-leve | libx264 crf28 slow + aac 128k (o .bat antigo) |
| | video-qualidade | libx264 crf20 slow |
| | video-discord | 2-pass com alvo ≤25 MB (áudio 96k, resto pro vídeo) |
| | video-av1-gpu | av1_amf (rápido, usa a GPU) |
| | video-arquivar | libsvtav1 crf 32 (menor arquivo, lento) |
| Áudio | audio-opus | libopus 128k |
| | audio-mp3 | libmp3lame V0 |
| | extrair-audio | vídeo → opus 128k |
| | normalizar | loudnorm 2-pass |
| PDF | pdf-ebook | gs /ebook |
| | pdf-tela | gs /screen (máxima compressão) |
| Compactar | 7z-ultra | 7z -mx9 |
| | zip | zip normal (compatível) |

Menu de contexto (clássico; no Win11 fica em "Mostrar mais opções" — limitação do Windows sem
app empacotado): `Mídia ▸` com submenu por categoria, registrado por extensão em
`HKCU\Software\Classes\SystemFileAssociations`. Pastas ganham só Compactar. Chama
`midia.py` num console visível (progresso), que pausa só em erro.

## Fase 2 — GUI (planejar de novo ao chegar)

Janela pywebview (mesmo stack do Scene Finder) sobre o MESMO motor:
- Drop de arquivos → detecta tipo → painel com presets + sliders pra fugir do preset.
- Fila com progresso (parse do `-progress` do ffmpeg), cancelar.
- Resultado: tamanho antes→depois, % economizado; imagem com comparação lado a lado.
- Download de modelos ncnn extras dentro do app (4x-UltraSharp, waifu2x…).
- Menu de contexto passa a ter "Abrir no Mídia Hub" com os arquivos carregados.

## Fase 3 — pesados

- Upscale de vídeo (frames → realesrgan → remontar com áudio original).
- Tamanho-alvo custom (2-pass, qualquer MB).
- Restaurar rosto (GFPGAN/CodeFormer via onnxruntime-directml) — avaliar custo/benefício na hora.

## Fora de escopo

Watch folder, instalador/auto-update, conversões exóticas. Adicionar se sentir falta.
