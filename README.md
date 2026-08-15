# Mídia Hub

Um lugar só pra comprimir, converter e melhorar **imagem, vídeo, áudio, PDF e arquivos**
no Windows — menu de botão direito + janela com fila, tudo sobre o mesmo motor.
Substitui os .bat espalhados (comprimir imagem, Real-ESRGAN, comprimir vídeo).

## O que faz

| Categoria | Presets |
|---|---|
| Imagem | WebP leve/boa/**sem perda de verdade**, AVIF, reduzir p/ 1920 |
| IA (GPU) | Upscale 4x, 4x anime, restaurar (4x→tamanho original), upscale 2x de vídeo |
| Vídeo | leve (crf28), qualidade (crf20), Discord ≤25 MB (2-pass), AV1 rápido (GPU AMD), arquivar (SVT-AV1) |
| Áudio | Opus 128k, MP3 V0, extrair áudio de vídeo, normalizar volume (loudnorm 2-pass) |
| PDF | ebook, tela (Ghostscript) |
| Compactar | 7z ultra, zip — em qualquer arquivo e em pastas |

Tudo em [presets.json](presets.json) — editável na mão; reinstalar o menu atualiza.

## Usar

- **Botão direito** num arquivo → `Mídia ▸ preset` (Win11: em "Mostrar mais opções").
  Vários arquivos selecionados viram uma fila numa janela só.
- **Janela** (Menu Iniciar → "Mídia Hub", ou `Mídia ▸ Abrir no Mídia Hub…`): arrastar
  arquivos, escolher preset, **slider de qualidade**, **MB alvo livre**, **modelo de IA**
  (com download de modelos extras), fila com %, comparação antes/depois, abrir pasta.
- **Linha de comando**: `python midia.py <preset> <arquivos...>` · `--listar` · `--check`

Saída sempre ao lado do original com sufixo `_<preset>`; nunca sobrescreve.

## Instalar

Pré-requisitos: Python 3.x, ffmpeg no PATH (`winget install ffmpeg`), 7-Zip,
`pip install pywebview`, e binários em `X:\midia-hub\bin\`:
- `gs\` — Ghostscript portátil (instalador oficial extraído com 7-Zip)
- `realesrgan\` — realesrgan-ncnn-vulkan + `models\` (.param/.bin)

Depois:

```bash
pwsh -File instalar.ps1
```

Registra o menu de contexto (HKCU, sem UAC) e cria o atalho no Menu Iniciar.
`-Desinstalar` remove tudo.

## Decisões que importam

- **"Sem perda" antigo era mentira**: o .bat usava WebP `-quality 90` (lossy).
  Aqui `webp-sem-perda` usa `-lossless 1` de verdade.
- **AV1 pela GPU** (av1_amf, RX 9070 XT): `-rc qvbr` — com `hqvbr` o
  `qvbr_quality_level` é ignorado. qvbr 30 ≈ x264 crf28 em gravação de tela, várias
  vezes mais rápido.
- **Menu de contexto chama 1 processo por arquivo** (limitação de verbo estático):
  o `--spool` junta tudo numa janela worker via lock + pasta de jobs.
- **`os.kill(pid, 0)` no Windows MATA o processo** — liveness é via
  `OpenProcess`/`GetExitCodeProcess` (`_pid_vivo`).
- Upscale de vídeo usa temp no **X:** (C: sem espaço) e limpa ao final.
- Restaurar rosto (GFPGAN) ficou de fora de propósito — ver [spec.md](spec.md).

## Testes

`python midia.py --check` valida ferramentas, presets e modelos.
