"""Mídia Hub — comprime/converte/melhora imagem, vídeo, áudio, PDF e arquivos.

Uso:
    midia.py <preset> <arquivos...>      processa direto
    midia.py --spool <preset> <arquivo>  usado pelo menu de contexto (agrupa numa janela só)
    midia.py --listar                    lista presets
    midia.py --check                     valida ferramentas e presets

Saída sempre ao lado do original com sufixo _<preset>, nunca sobrescreve.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ_BIN = Path("X:/midia-hub/bin")
FERRAMENTAS = {
    "ffmpeg": shutil.which("ffmpeg") or "ffmpeg",
    "ffprobe": shutil.which("ffprobe") or "ffprobe",
    "7z": r"C:\Program Files\7-Zip\7z.exe",
    "gs": str(RAIZ_BIN / "gs/bin/gswin64c.exe"),
    "realesrgan": str(RAIZ_BIN / "realesrgan/realesrgan-ncnn-vulkan.exe"),
}
MODELOS = str(RAIZ_BIN / "realesrgan/models")
SPOOL_DIR = Path(tempfile.gettempdir()) / "midia-hub-jobs"
LOCK = Path(tempfile.gettempdir()) / "midia-hub.lock"


def carregar_presets():
    with open(AQUI / "presets.json", encoding="utf-8") as f:
        return json.load(f)


def fmt_tamanho(n):
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n} B" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024


def saida_para(caminho, preset_nome, preset):
    """Caminho de saída único: <nome>_<preset><ext>, com (2), (3)... se existir."""
    ext = preset.get("saida_ext") or caminho.suffix
    stem = caminho.name if caminho.is_dir() else caminho.stem
    destino = caminho.parent / f"{stem}_{preset_nome}{ext}"
    n = 2
    while destino.exists():
        destino = caminho.parent / f"{stem}_{preset_nome} ({n}){ext}"
        n += 1
    return destino


PROC_ATUAL = None  # processo em execução, p/ cancelar pela GUI


def rodar(cmd, progresso=None, dur=0, **kw):
    """subprocess.run com as chaves {ferramenta}/{in}/{out} expandidas.

    progresso: callback(0..1) — só funciona em comandos ffmpeg com dur conhecida.
    """
    global PROC_ATUAL
    expandido = [c.format(**FERRAMENTAS, modelos=MODELOS, **kw) for c in cmd]
    if progresso and dur and expandido[0] == FERRAMENTAS["ffmpeg"]:
        expandido[1:1] = ["-progress", "pipe:1", "-nostats"]
        p = subprocess.Popen(expandido, stdout=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace")
        PROC_ATUAL = p
        for linha in p.stdout:
            if linha.startswith("out_time_ms="):  # na verdade é microssegundo
                try:
                    progresso(min(0.99, int(linha.split("=")[1]) / 1e6 / dur))
                except ValueError:
                    pass
        cod = p.wait()
    else:
        p = subprocess.Popen(expandido)
        PROC_ATUAL = p
        cod = p.wait()
    PROC_ATUAL = None
    return cod


def cancelar_atual():
    p = PROC_ATUAL
    if p and p.poll() is None:
        p.kill()


def duracao_de(caminho):
    info = ffprobe_json(caminho, "-show_entries", "format=duration")
    return float(info.get("format", {}).get("duration", 0) or 0)


def ffprobe_json(caminho, *args):
    r = subprocess.run(
        [FERRAMENTAS["ffprobe"], "-v", "error", "-of", "json", *args, str(caminho)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return json.loads(r.stdout) if r.returncode == 0 else {}


# ---------------------------------------------------------------- handlers

def h_restaurar(caminho, destino, preset, ajustes):
    """Upscale 4x e volta ao tamanho original — limpa artefatos de compressão."""
    info = ffprobe_json(caminho, "-select_streams", "v:0", "-show_entries", "stream=width,height")
    streams = info.get("streams") or []
    if not streams:
        return "não consegui ler as dimensões"
    w, h = streams[0]["width"], streams[0]["height"]
    modelo = ajustes.get("modelo") or "realesrgan-x4plus"
    tmp = destino.with_name(destino.stem + "_tmp4x.png")
    try:
        if rodar(["{realesrgan}", "-i", "{in}", "-o", "{out}", "-n", modelo,
                  "-m", "{modelos}"], **{"in": str(caminho), "out": str(tmp)}) != 0:
            return "upscale falhou"
        if rodar(["{ffmpeg}", "-hide_banner", "-loglevel", "warning", "-i", "{in}",
                  "-vf", f"scale={w}:{h}:flags=lanczos", "-y", "{out}"],
                 **{"in": str(tmp), "out": str(destino)}) != 0:
            return "downscale falhou"
    finally:
        tmp.unlink(missing_ok=True)
    return None


def h_video_alvo(caminho, destino, preset, ajustes):
    """2-pass libx264 com tamanho alvo em MB (preset ou ajuste da GUI)."""
    alvo_mb = float(ajustes.get("alvo_mb") or preset.get("alvo_mb") or 25)
    if caminho.stat().st_size <= alvo_mb * 1024 * 1024:
        return f"já cabe em {alvo_mb:g} MB, nada a fazer"
    info = ffprobe_json(caminho, "-show_entries", "format=duration")
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    if not dur:
        return "não consegui ler a duração"
    alvo_bits = alvo_mb * 1024 * 1024 * 0.97 * 8
    audio_bps = 96_000
    video_bps = int(alvo_bits / dur - audio_bps)
    if video_bps < 150_000:
        video_bps = 150_000
        print(f"  aviso: vídeo longo demais p/ {alvo_mb:g} MB, usando bitrate mínimo (vai passar do limite)")
    with tempfile.TemporaryDirectory() as td:
        plog = os.path.join(td, "2pass")
        base = ["{ffmpeg}", "-hide_banner", "-loglevel", "warning", "-stats", "-i", "{in}",
                "-c:v", "libx264", "-b:v", str(video_bps), "-preset", "slow",
                "-pix_fmt", "yuv420p", "-passlogfile", plog]
        if rodar(base + ["-pass", "1", "-an", "-f", "null", "-y", "NUL"],
                 **{"in": str(caminho)}) != 0:
            return "passada 1 falhou"
        if rodar(base + ["-pass", "2", "-c:a", "aac", "-b:a", "96k", "-y", "{out}"],
                 **{"in": str(caminho), "out": str(destino)}) != 0:
            return "passada 2 falhou"
    return None


# reencode por extensão ao normalizar (mantém a família do codec original)
CODEC_POR_EXT = {
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
    ".flac": ["-c:a", "flac"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
    ".aac": ["-c:a", "aac", "-b:a", "192k"],
    ".ogg": ["-c:a", "libopus", "-b:a", "160k"],
    ".opus": ["-c:a", "libopus", "-b:a", "160k"],
}


def h_normalizar(caminho, destino, preset, ajustes):
    """loudnorm 2-pass (EBU R128, I=-16)."""
    alvo = "I=-16:TP=-1.5:LRA=11"
    r = subprocess.run(
        [FERRAMENTAS["ffmpeg"], "-hide_banner", "-i", str(caminho),
         "-af", f"loudnorm={alvo}:print_format=json", "-f", "null", "NUL"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ini = r.stderr.rfind("{")
    if r.returncode != 0 or ini == -1:
        return "medição loudnorm falhou"
    m = json.loads(r.stderr[ini:r.stderr.rfind("}") + 1])
    filtro = (f"loudnorm={alvo}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
              f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
              f":offset={m['target_offset']}:linear=true")
    codec = CODEC_POR_EXT.get(caminho.suffix.lower(), ["-c:a", "aac", "-b:a", "192k"])
    if rodar(["{ffmpeg}", "-hide_banner", "-loglevel", "warning", "-i", "{in}",
              "-af", filtro, *codec, "-y", "{out}"],
             **{"in": str(caminho), "out": str(destino)}) != 0:
        return "reencode falhou"
    return None


def h_compactar(caminho, destino, preset, ajustes):
    """7z/zip de arquivo ou pasta; "partes" divide em volumes (.7z.001, .002...)."""
    formato = "-tzip" if destino.suffix == ".zip" else "-t7z"
    nivel = "-mx9" if destino.suffix == ".7z" else "-mx5"
    cmd = [FERRAMENTAS["7z"], "a", formato, nivel]
    if preset.get("partes"):
        cmd.append(f"-v{preset['partes']}")
    r = subprocess.run(cmd + [str(destino), str(caminho)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return None if r.returncode == 0 else "7z falhou: " + (r.stderr or r.stdout).strip()[:200]


def h_video_upscale(caminho, destino, preset, ajustes):
    """Upscale 2x de vídeo: frames -> realesr-animevideov3 -> remonta com o áudio.

    Lento e usa bastante disco temporário (no X:). Pensado p/ vídeos curtos.
    """
    import shutil as _shutil
    info = ffprobe_json(caminho, "-select_streams", "v:0",
                        "-show_entries", "stream=r_frame_rate")
    streams = info.get("streams") or []
    if not streams:
        return "não consegui ler o vídeo"
    fps = streams[0]["r_frame_rate"]
    tem_audio = bool(ffprobe_json(caminho, "-select_streams", "a",
                                  "-show_entries", "stream=index").get("streams"))
    raiz_tmp = RAIZ_BIN.parent / "tmp"  # disco X: — o C: não tem espaço p/ frames
    raiz_tmp.mkdir(exist_ok=True)
    td = raiz_tmp / f"upscale-{uuid.uuid4().hex[:8]}"
    (td / "in").mkdir(parents=True)
    (td / "out").mkdir()
    try:
        if rodar(["{ffmpeg}", "-hide_banner", "-loglevel", "warning", "-stats", "-i", "{in}",
                  "-fps_mode", "passthrough", "{out}"],
                 **{"in": str(caminho), "out": str(td / "in" / "%08d.png")}) != 0:
            return "extração de frames falhou"
        n = len(list((td / "in").glob("*.png")))
        print(f"  {n} frames, subindo 2x na GPU...")
        if rodar(["{realesrgan}", "-i", str(td / "in"), "-o", str(td / "out"),
                  "-n", "realesr-animevideov3-x2", "-s", "2", "-m", "{modelos}"]) != 0:
            return "upscale dos frames falhou"
        if len(list((td / "out").glob("*.png"))) != n:
            return "upscale não gerou todos os frames"
        cmd = ["{ffmpeg}", "-hide_banner", "-loglevel", "warning", "-stats",
               "-framerate", fps, "-i", str(td / "out" / "%08d.png")]
        if tem_audio:
            cmd += ["-i", "{in}", "-map", "0:v", "-map", "1:a", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-shortest", "-y", "{out}"]
        if rodar(cmd, **{"in": str(caminho), "out": str(destino)}) != 0:
            return "remontagem falhou"
    finally:
        _shutil.rmtree(td, ignore_errors=True)
    return None


HANDLERS = {
    "restaurar": h_restaurar,
    "video_alvo": h_video_alvo,
    "video_upscale": h_video_upscale,
    "normalizar": h_normalizar,
    "compactar": h_compactar,
}


# ---------------------------------------------------------------- núcleo

def tamanho_de(caminho):
    if caminho.is_dir():
        return sum(f.stat().st_size for f in caminho.rglob("*") if f.is_file())
    return caminho.stat().st_size


def processar(preset_nome, preset, caminho, ajustes=None, progresso=None):
    """Devolve (destino|None, erro|None, antes, depois).

    ajustes: {"qualidade": int, "modelo": str} — sobrescreve o valor do preset (GUI).
    progresso: callback(0..1) p/ vídeo (GUI).
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return None, "não existe", 0, 0
    exts = preset["exts"]
    if caminho.is_dir():
        if preset.get("handler") != "compactar":
            return None, "preset não aceita pasta", 0, 0
    elif "*" not in exts and caminho.suffix.lower() not in exts:
        return None, f"extensão {caminho.suffix} não é aceita por este preset", 0, 0

    antes = tamanho_de(caminho)
    destino = saida_para(caminho, preset_nome, preset)
    if "handler" in preset:
        erro = HANDLERS[preset["handler"]](caminho, destino, preset, ajustes or {})
    else:
        cmd = list(preset["cmd"])
        if ajustes:
            if ajustes.get("modelo") and "-n" in cmd:
                cmd[cmd.index("-n") + 1] = ajustes["modelo"]
            q = ajustes.get("qualidade")
            if q is not None:
                for flag in ("-quality", "-crf", "-qvbr_quality_level"):
                    if flag in cmd:
                        cmd[cmd.index(flag) + 1] = str(q)
                        break
        dur = duracao_de(caminho) if progresso and preset["categoria"] == "video" else 0
        cod = rodar(cmd, progresso=progresso, dur=dur,
                    **{"in": str(caminho), "out": str(destino)})
        erro = None if cod == 0 else f"ferramenta saiu com código {cod}"
    if erro is None and not destino.exists():
        # 7z com volumes gera destino.001, .002...
        volumes = sorted(destino.parent.glob(destino.name + ".0*"))
        if volumes:
            return volumes[0], None, antes, sum(v.stat().st_size for v in volumes)
        erro = "ferramenta não gerou a saída"
    if erro:
        destino.unlink(missing_ok=True)
        return None, erro, antes, 0
    return destino, None, antes, destino.stat().st_size


def executar_fila(fila):
    """fila = [(preset_nome, caminho)]; devolve lista de (caminho, erro|None, antes, depois)."""
    presets = carregar_presets()
    resultados = []
    for i, (pnome, caminho) in enumerate(fila, 1):
        print(f"\n[{i}/{len(fila)}] {pnome}: {Path(caminho).name}")
        if pnome not in presets:
            resultados.append((caminho, f"preset '{pnome}' não existe", 0, 0))
            print(f"  ERRO: preset '{pnome}' não existe")
            continue
        t0 = time.time()
        destino, erro, antes, depois = processar(pnome, presets[pnome], caminho)
        if erro:
            resultados.append((caminho, erro, antes, 0))
            print(f"  ERRO: {erro}")
        else:
            resultados.append((caminho, None, antes, depois))
            econ = (1 - depois / antes) * 100 if antes else 0
            rumo = "menor" if econ >= 0 else "maior"
            print(f"  ok em {time.time() - t0:.0f}s: {fmt_tamanho(antes)} -> "
                  f"{fmt_tamanho(depois)} ({abs(econ):.0f}% {rumo}) -> {destino.name}")
    return resultados


def resumir(resultados, pausa):
    falhas = [r for r in resultados if r[1]]
    print(f"\n{'-' * 50}\n{len(resultados) - len(falhas)} ok, {len(falhas)} falha(s)")
    for caminho, erro, *_ in falhas:
        print(f"  FALHOU {Path(caminho).name}: {erro}")
    if pausa:
        if falhas:
            input("\nEnter para fechar...")
        else:
            print("fechando em 3s...")
            time.sleep(3)
    return 1 if falhas else 0


# ---------------------------------------------------------------- spool (menu de contexto)

def _pid_vivo(pid):
    """os.kill(pid, 0) no Windows MATA o processo — checar via OpenProcess."""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        codigo = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(codigo))
        return codigo.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def pegar_lock(lock=LOCK):
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if _pid_vivo(int(lock.read_text() or 0)):
                    return False
                lock.unlink(missing_ok=True)  # lock órfão de processo morto
            except (OSError, ValueError):
                return False
    return False


def spool(preset_nome, caminho):
    SPOOL_DIR.mkdir(exist_ok=True)
    (SPOOL_DIR / f"{uuid.uuid4().hex}.job").write_text(
        f"{preset_nome}\n{caminho}", encoding="utf-8")
    if not pegar_lock():
        return 0  # outra janela já é o worker e vai pegar este job
    try:
        print("Mídia Hub — juntando arquivos selecionados...")
        resultados = []
        while True:
            time.sleep(1.2)  # espera os irmãos da mesma seleção depositarem
            jobs = sorted(SPOOL_DIR.glob("*.job"))
            if not jobs:
                break
            fila = []
            for j in jobs:
                linhas = j.read_text(encoding="utf-8").splitlines()
                j.unlink()
                if len(linhas) == 2:
                    fila.append((linhas[0], linhas[1]))
            resultados += executar_fila(fila)
        return resumir(resultados, pausa=True)
    finally:
        LOCK.unlink(missing_ok=True)


# ---------------------------------------------------------------- check / listar

def check():
    ok = True
    for nome, caminho in FERRAMENTAS.items():
        existe = bool(caminho and (Path(caminho).exists() or shutil.which(caminho)))
        print(f"  {'ok   ' if existe else 'FALTA'} {nome}: {caminho}")
        ok = ok and existe
    presets = carregar_presets()
    modelos = {p.stem for p in Path(MODELOS).glob("*.param")}
    for nome, p in presets.items():
        problemas = []
        if "handler" in p and p["handler"] not in HANDLERS:
            problemas.append(f"handler '{p['handler']}' não existe")
        if "handler" not in p and "cmd" not in p:
            problemas.append("sem cmd nem handler")
        cmd = p.get("cmd", [])
        if "-n" in cmd and cmd[cmd.index("-n") + 1] not in modelos:
            problemas.append(f"modelo {cmd[cmd.index('-n') + 1]} não está em {MODELOS}")
        if problemas:
            ok = False
            print(f"  PRESET {nome}: {'; '.join(problemas)}")
    print(f"\n{len(presets)} presets. " + ("Tudo certo." if ok else "Tem problema acima."))
    return 0 if ok else 1


def listar():
    cat_atual = None
    for nome, p in carregar_presets().items():
        if p["categoria"] != cat_atual:
            cat_atual = p["categoria"]
            print(f"\n[{cat_atual}]")
        print(f"  {nome:<18} {p['rotulo']}")
    return 0


# ---------------------------------------------------------------- main

def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        return check()
    if argv[0] == "--listar":
        return listar()
    if argv[0] == "--spool":
        if len(argv) != 3:
            print("uso: midia.py --spool <preset> <arquivo>")
            return 2
        return spool(argv[1], argv[2])
    pausa = False
    if argv[0] == "--pausa":
        pausa = True
        argv = argv[1:]
    if len(argv) < 2:
        print("uso: midia.py [--pausa] <preset> <arquivos...>   (--listar para ver presets)")
        return 2
    return resumir(executar_fila([(argv[0], c) for c in argv[1:]]), pausa)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
