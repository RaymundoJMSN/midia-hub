"""Mídia Hub — janela (pywebview sobre o mesmo motor do midia.py).

pythonw app.py [arquivos...]   — abre com arquivos já na lista.
Instância única: se já houver janela aberta, a nova invocação só deposita o
arquivo em GUI_JOBS e sai; a janela aberta pega sozinha.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import webview

import midia

GUI_JOBS = Path(tempfile.gettempdir()) / "midia-hub-gui-jobs"
GUI_LOCK = Path(tempfile.gettempdir()) / "midia-hub-gui.lock"

BASE_MODELOS = "https://raw.githubusercontent.com/upscayl/custom-models/main/models/"
MODELOS_CURADOS = {
    "RealESRGAN_General_x4_v3": "Geral v3 — fotos e prints, equilibrado",
    "RealESRGAN_General_WDN_x4_v3": "Geral v3 WDN — remove mais ruído",
    "4x_NMKD-Superscale-SP_178000_G": "NMKD Superscale — fotos nítidas",
    "4x_NMKD-Siax_200k": "NMKD Siax — detalhe forte",
    "4xHFA2k": "HFA2k — anime moderno",
    "4xLSDIR": "LSDIR — foto realista",
    "uniscale_restore": "Uniscale Restore — restauração de imagem ruim",
}


class Api:
    def __init__(self, iniciais):
        self._iniciais = list(iniciais)
        self._pendentes = []          # vindos do menu de contexto com a janela aberta
        self.fila = []                # jobs: dict simples, serializável
        self.downloads = {}           # nome -> pct | "ok" | "erro: ..."
        self._trava = threading.Lock()
        self._cancelar = False
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._vigiar_gui_jobs, daemon=True).start()

    # ------------------------------------------------ dados p/ a interface

    def dados_iniciais(self):
        presets = midia.carregar_presets()
        ini, self._iniciais = self._iniciais, []
        return {"presets": presets, "iniciais": ini,
                "modelos": self.modelos()}

    def modelos(self):
        instalados = sorted(p.stem for p in Path(midia.MODELOS).glob("*.param"))
        return {"instalados": instalados, "curados": MODELOS_CURADOS,
            "downloads": self.downloads}

    def pendentes_menu(self):
        with self._trava:
            p, self._pendentes = self._pendentes, []
        return p

    def escolher_arquivos(self):
        r = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True)
        return list(r or [])

    # ------------------------------------------------ fila

    def adicionar(self, caminhos, preset, ajustes=None):
        """Enfileira; devolve os ids."""
        ids = []
        with self._trava:
            for c in caminhos:
                j = {"id": uuid.uuid4().hex[:8], "caminho": c, "nome": Path(c).name,
                     "preset": preset, "ajustes": ajustes or {}, "status": "fila",
                     "pct": 0, "antes": 0, "depois": 0, "saida": None, "erro": None}
                self.fila.append(j)
                ids.append(j["id"])
        return ids

    def estado(self):
        return {"fila": self.fila, "downloads": self.downloads}

    def cancelar_job(self, id):
        with self._trava:
            for j in self.fila:
                if j["id"] == id and j["status"] == "fila":
                    j["status"] = "cancelado"
                elif j["id"] == id and j["status"] == "rodando":
                    self._cancelar = True
                    midia.cancelar_atual()

    def limpar_prontos(self):
        with self._trava:
            self.fila = [j for j in self.fila if j["status"] in ("fila", "rodando")]

    def _worker(self):
        presets_cache = None
        while True:
            job = None
            with self._trava:
                for j in self.fila:
                    if j["status"] == "fila":
                        j["status"] = "rodando"
                        job = j
                        break
            if not job:
                presets_cache = None
                time.sleep(0.3)
                continue
            presets_cache = presets_cache or midia.carregar_presets()
            self._cancelar = False
            p = presets_cache.get(job["preset"])
            if not p:
                job.update(status="erro", erro=f"preset {job['preset']} não existe")
                continue

            def pct(x, job=job):
                job["pct"] = round(x * 100)

            t0 = time.time()
            destino, erro, antes, depois = midia.processar(
                job["preset"], p, job["caminho"], ajustes=job["ajustes"], progresso=pct)
            job["antes"] = antes
            job["t"] = round(time.time() - t0)
            if self._cancelar:
                job.update(status="cancelado", erro=None)
            elif erro:
                job.update(status="erro", erro=erro)
            else:
                job.update(status="ok", depois=depois, saida=str(destino), pct=100)

    # ------------------------------------------------ menu de contexto -> janela aberta

    def _vigiar_gui_jobs(self):
        GUI_JOBS.mkdir(exist_ok=True)
        while True:
            for f in GUI_JOBS.glob("*.job"):
                try:
                    caminho = f.read_text(encoding="utf-8").strip()
                    f.unlink()
                    if caminho:
                        with self._trava:
                            self._pendentes.append(caminho)
                except OSError:
                    pass
            time.sleep(1)

    # ------------------------------------------------ utilidades

    def preview(self, caminho):
        """Miniatura base64 (máx 1000px) de imagem ou 1º frame de vídeo."""
        tmp = Path(tempfile.gettempdir()) / f"midia-hub-prev-{uuid.uuid4().hex[:8]}.jpg"
        try:
            r = subprocess.run(
                [midia.FERRAMENTAS["ffmpeg"], "-hide_banner", "-loglevel", "error",
                 "-i", str(caminho), "-vf", "scale='min(1000,iw)':-2",
                 "-frames:v", "1", "-q:v", "4", "-y", str(tmp)],
                capture_output=True, timeout=30)
            if r.returncode != 0 or not tmp.exists():
                return None
            return "data:image/jpeg;base64," + base64.b64encode(tmp.read_bytes()).decode()
        except subprocess.TimeoutExpired:
            return None
        finally:
            tmp.unlink(missing_ok=True)

    def abrir_pasta(self, caminho):
        subprocess.Popen(["explorer", "/select,", str(Path(caminho))])

    def abrir_arquivo(self, caminho):
        os.startfile(caminho)

    def baixar_modelo(self, nome):
        if nome not in MODELOS_CURADOS or isinstance(self.downloads.get(nome), (int, float)):
            return
        self.downloads[nome] = 0
        threading.Thread(target=self._baixar, args=(nome,), daemon=True).start()

    def _baixar(self, nome):
        try:
            destino = Path(midia.MODELOS)
            for ext in (".param", ".bin"):
                url = BASE_MODELOS + urllib.parse.quote(nome + ext)
                tmp = destino / (nome + ext + ".baixando")
                with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    lido = 0
                    while True:
                        parte = resp.read(256 * 1024)
                        if not parte:
                            break
                        f.write(parte)
                        lido += len(parte)
                        if total and ext == ".bin":  # o .param é minúsculo
                            self.downloads[nome] = round(lido / total * 100)
                tmp.rename(destino / (nome + ext))
            self.downloads[nome] = "ok"
        except Exception as e:  # rede/disco: mostrar na UI em vez de morrer
            self.downloads[nome] = f"erro: {e}"


def instancia_unica(arquivos):
    """True = esta é a instância dona da janela."""
    GUI_JOBS.mkdir(exist_ok=True)
    if not midia.pegar_lock(GUI_LOCK):
        for a in arquivos:
            (GUI_JOBS / f"{uuid.uuid4().hex}.job").write_text(a, encoding="utf-8")
        return False
    return True


def main():
    arquivos = [a for a in sys.argv[1:] if Path(a).exists()]
    if not instancia_unica(arquivos):
        return
    try:
        api = Api(arquivos)
        webview.create_window(
            "Mídia Hub", str(Path(__file__).parent / "gui.html"),
            js_api=api, width=980, height=760, background_color="#14161a")
        webview.start()
    finally:
        GUI_LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
