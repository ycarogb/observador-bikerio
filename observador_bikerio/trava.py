"""Impede duas coletas ao mesmo tempo. A interface não usa esta trava."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class ColetorJaEmExecucao(Exception):
    def __init__(self, pid: int | None):
        self.pid = pid
        detalhe = f" (PID {pid})" if pid else ""
        super().__init__(
            "Já existe um coletor em execução"
            f"{detalhe}. A segunda instância foi encerrada para não duplicar a coleta."
        )


class TravaColetor:
    def __init__(self, diretorio: Path):
        self.diretorio = diretorio
        self.adquirida = False

    def __enter__(self) -> "TravaColetor":
        self.diretorio.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                self.diretorio.mkdir()
            except FileExistsError:
                pid = _ler_pid(self.diretorio)
                if _pid_ativo(pid):
                    raise ColetorJaEmExecucao(pid) from None
                _remover(self.diretorio)
                continue
            (self.diretorio / "pid").write_text(str(os.getpid()), encoding="utf-8")
            self.adquirida = True
            return self
        raise ColetorJaEmExecucao(_ler_pid(self.diretorio))

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.adquirida:
            return
        pid = _ler_pid(self.diretorio)
        if pid == os.getpid():
            _remover(self.diretorio)
        self.adquirida = False


def _ler_pid(diretorio: Path) -> int | None:
    arquivo = diretorio / "pid"
    try:
        return int(arquivo.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_ativo(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        return _pid_ativo_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_ativo_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    codigo = wintypes.DWORD()
    ok = kernel.GetExitCodeProcess(handle, ctypes.byref(codigo))
    kernel.CloseHandle(handle)
    # 259 = STILL_ACTIVE. Processo encerrado continua abrível por um instante, mas já tem código de saída.
    return bool(ok) and codigo.value == 259


def _remover(diretorio: Path) -> None:
    shutil.rmtree(diretorio, ignore_errors=True)
