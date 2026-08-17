# Mídia Hub

Um lugar só pra comprimir, converter e melhorar **imagem, vídeo, áudio, PDF e arquivos**
no Windows — menu de botão direito + janela com fila, tudo sobre o mesmo motor.
Substitui os .bat espalhados (comprimir imagem, Real-ESRGAN, comprimir vídeo).

## O que faz

31 presets com **nome de gente** — o resultado está no nome, não o parâmetro
("Comprimir muito (bem menor, perde um pouco)" em vez de "crf30"):

| Categoria | Presets |
|---|---|
| Imagem | Comprimir pouco/recomendado/muito, sem perda nenhuma, menor possível (AVIF), diminuir p/ tela 1920 / zap 1280, converter p/ JPG, GIF→vídeo |
| IA (GPU) | Aumentar 4x (foto e anime), melhorar sem aumentar, aumentar vídeo 2x |
| Vídeo | Comprimir pouco/recomendado/muito, rápido pela placa de vídeo, guardar no mínimo, caber em 25 MB (Discord) / 15 MB (WhatsApp), tirar o som |
| Áudio | Comprimir (Opus), converter p/ MP3, tirar o som do vídeo, nivelar volume |
| PDF | Comprimir p/ leitura / só tela / qualidade de impressão |
| Compactar | 7z máximo, ZIP compatível, 7z em partes de 1 GB |

Na janela, o ajuste fino é um slider único **"arquivo menor ⟵⟶ mais qualidade"**
(a direção é sempre essa, independente do formato por trás). Tudo em
[presets.json](presets.json) — editável na mão; reinstalar o menu atualiza.

## Usar

- **Botão direito** num arquivo → `Mídia ▸ preset` (Win11: em "Mostrar mais opções").
  Vários arquivos selecionados viram uma fila numa janela só.
- **Janela** (Menu Iniciar → "Mídia Hub", ou `Mídia ▸ Abrir no Mídia Hub…`): arrastar
  arquivos, escolher preset, **slider de qualidade**, **MB alvo livre**, **modelo de IA**
  (com download de modelos extras), fila com %, comparação antes/depois, abrir pasta.
- **Linha de comando**: `python midia.py <preset> <arquivos...>` · `--listar` · `--check`

Saída sempre ao lado do original com sufixo `_<preset>`; nunca sobrescreve.

## Instalar (PC novo)

Pré-requisitos manuais: Python 3.x, 7-Zip e ffmpeg no PATH (`winget install ffmpeg`).
O resto o instalador resolve:

```bash
git clone https://github.com/RaymundoJMSN/midia-hub && cd midia-hub && pwsh -File instalar.ps1
```

O `instalar.ps1` é idempotente: instala pywebview via pip, baixa Ghostscript portátil e
Real-ESRGAN pro `X:\midia-hub\bin\` se faltarem, registra o menu de contexto (HKCU, sem
UAC) e cria o atalho no Menu Iniciar. `-Desinstalar` remove menu e atalho.

## Atualização automática

Ao abrir a janela, o app faz `git fetch` em background; se o GitHub tiver versão mais
nova, faz `pull --ff-only`, reinstala o menu sozinho e avisa na interface ("feche e abra
pra aplicar"). Sem rede ou sem novidade, não faz nada.

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
