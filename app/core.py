"""Lógica de PC Free Space: análisis de disco, categorías de limpieza y borrado seguro.

No depende de la interfaz gráfica, así que se puede probar por separado.
"""
from __future__ import annotations

import glob
import heapq
import json
import os
import re
import shutil
import stat
import string
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OS_NAME = "Windows" if IS_WIN else "macOS" if IS_MAC else "Linux"

# Atributos de archivo de Windows
FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

MODEL_EXTENSIONS = {
    ".gguf", ".ggml", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx",
    ".h5", ".keras", ".tflite", ".pb", ".bin", ".mlmodel", ".pkl", ".npz",
}
MODEL_MIN_SIZE = 50 * 1024 * 1024  # 50 MB


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def human(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


HOME = os.path.expanduser("~")
LOCAL = env("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
ROAMING = env("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
PROGRAMDATA = env("PROGRAMDATA", r"C:\ProgramData")
WINDIR = env("WINDIR", r"C:\Windows")
SYSDRIVE = (env("SystemDrive", "C:") + os.sep) if IS_WIN else "/"
TEMP = env("TEMP", os.path.join(LOCAL, "Temp")) if IS_WIN else __import__("tempfile").gettempdir()
MAC_LIB = os.path.join(HOME, "Library")
XDG_CACHE = env("XDG_CACHE_HOME", os.path.join(HOME, ".cache"))
XDG_CONFIG = env("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
XDG_DATA = env("XDG_DATA_HOME", os.path.join(HOME, ".local", "share"))
PROGRAM_FILES = [p for p in {env("ProgramFiles", r"C:\Program Files"),
                             env("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             env("ProgramW6432", r"C:\Program Files")} if p]


def norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p)).rstrip("\\/")


def is_inside(path: str, parent: str) -> bool:
    p, q = norm(path), norm(parent)
    return p == q or p.startswith(q + os.sep)


def _entry_size(entry: os.DirEntry) -> tuple[int, bool]:
    """Devuelve (tamaño, es_enlace). Los archivos solo-nube de OneDrive cuentan 0."""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return 0, False
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(st.st_mode):
        return 0, True
    if attrs & CLOUD_ONLY:
        return 0, False
    return st.st_size, False


def _is_link_dir(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        if hasattr(entry, "is_junction") and entry.is_junction():
            return True
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def dir_size(path: str, cancel: threading.Event | None = None) -> tuple[int, int]:
    """Tamaño total y número de archivos de una carpeta (sin seguir enlaces/junctions)."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    total = files = 0
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not _is_link_dir(e):
                                stack.append(e.path)
                        else:
                            s, _ = _entry_size(e)
                            total += s
                            files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, files


# --------------------------------------------------------------------------
# Discos
# --------------------------------------------------------------------------
@dataclass
class DriveInfo:
    path: str
    total: int
    used: int
    free: int

    @property
    def pct(self) -> float:
        return self.used / self.total if self.total else 0.0


def list_drives() -> list[DriveInfo]:
    roots: list[str] = []
    if IS_WIN:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << i):
                root = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                if dtype in (2, 3, 4, 6):  # extraíble, fijo, red, RAM
                    roots.append(root)
    else:
        roots = _posix_mounts()
    out = []
    for r in roots:
        try:
            u = shutil.disk_usage(r)
            out.append(DriveInfo(r, u.total, u.used, u.free))
        except OSError:
            pass
    return out


REAL_FS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "zfs", "f2fs", "jfs", "reiserfs", "ntfs", "ntfs3",
           "fuseblk", "vfat", "exfat", "hfsplus", "apfs", "bcachefs"}


def _posix_mounts() -> list[str]:
    roots = ["/"]
    if IS_LINUX:
        try:
            with open("/proc/mounts", encoding="utf-8") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    mnt, fs = parts[1].replace("\\040", " "), parts[2]
                    if fs in REAL_FS and mnt != "/" and not mnt.startswith(("/snap", "/boot", "/var/lib", "/run/user")):
                        roots.append(mnt)
        except OSError:
            pass
    elif IS_MAC:
        try:
            for e in os.scandir("/Volumes"):
                if e.is_dir() and not os.path.islink(e.path):
                    roots.append(e.path)
        except OSError:
            pass
    out, seen = [], set()
    for r in roots:
        try:
            st = os.stat(r)
            u = shutil.disk_usage(r)
        except OSError:
            continue
        key = (st.st_dev, u.total)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def system_files_info() -> list[tuple[str, str, int, str]]:
    if not IS_WIN:
        items = []
        cands = [("Memoria de intercambio", "/swapfile", "Lo gestiona el sistema. Se puede reducir con swapoff/fallocate."),
                 ("Memoria de intercambio", "/swap.img", "Lo gestiona el sistema. Se puede reducir con swapoff/fallocate."),
                 ("Imagen de reposo", "/private/var/vm/sleepimage", "La gestiona macOS. Se puede desactivar con: sudo pmset -a hibernatemode 0")]
        for label, p, tip in cands:
            try:
                items.append((label, p, os.stat(p).st_size, tip))
            except OSError:
                pass
        return items
    """Archivos grandes del sistema que no se pueden borrar a mano, con consejo."""
    items = []
    tips = {
        "hiberfil.sys": ("Hibernación", "Si no usas la hibernación, ejecuta como administrador: powercfg /h off"),
        "pagefile.sys": ("Memoria virtual", "Lo gestiona Windows. Se puede reducir en Sistema > Configuración avanzada > Rendimiento."),
        "swapfile.sys": ("Memoria de apps", "Lo gestiona Windows. No se debe borrar."),
    }
    for fname, (label, tip) in tips.items():
        p = os.path.join(SYSDRIVE, fname)
        try:
            size = os.stat(p).st_size
        except OSError:
            continue
        items.append((label, p, size, tip))
    return items


# --------------------------------------------------------------------------
# Protección de rutas
# --------------------------------------------------------------------------
BLOCK, WARN, OK = "block", "warn", "ok"


def _protected_exact() -> list[str]:
    roots = [HOME, LOCAL, ROAMING, os.path.join(HOME, "AppData"), os.path.dirname(HOME),
             PROGRAMDATA, *PROGRAM_FILES]
    for sub in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive"):
        roots.append(os.path.join(HOME, sub))
    return [norm(r) for r in roots if r]


def protection_level(path: str) -> tuple[str, str]:
    """Indica si una ruta se puede borrar desde el analizador.

    BLOCK: nunca (Windows, raíz de disco, carpetas base de usuario...).
    WARN: posible, pero con aviso (Program Files: mejor desinstalar).
    OK: se puede enviar a la Papelera.
    """
    if not IS_WIN:
        return _posix_protection(path)
    p = norm(path)
    drive, rest = os.path.splitdrive(p)
    if rest in ("", os.sep):
        return BLOCK, "Es la raíz de un disco."
    if p in _protected_exact():
        return BLOCK, "Es una carpeta base del sistema o de tu usuario (puedes borrar su contenido, no la carpeta)."
    name = os.path.basename(p).lower()
    if name in {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr", "dumpstack.log.tmp"}:
        return BLOCK, "Archivo del sistema gestionado por Windows."
    allowed_in_windows = [os.path.join(WINDIR, "Temp"),
                          os.path.join(WINDIR, "SoftwareDistribution", "Download"),
                          os.path.join(WINDIR, "Minidump"),
                          os.path.join(WINDIR, "MEMORY.DMP")]
    if is_inside(p, WINDIR):
        if any(is_inside(p, a) and norm(p) != norm(a) for a in allowed_in_windows[:3]) or norm(p) == norm(allowed_in_windows[3]):
            return OK, ""
        return BLOCK, "Está dentro de la carpeta de Windows."
    for sysdir in ("System Volume Information", "$Recycle.Bin", "Recovery", "Boot", "EFI",
                   "$WinREAgent", "$Windows.~BT", "$Windows.~WS", "Config.Msi"):
        if is_inside(p, os.path.join(drive + os.sep, sysdir)):
            return BLOCK, "Carpeta protegida del sistema."
    if is_inside(p, os.path.join(PROGRAMDATA, "Microsoft")):
        return BLOCK, "Datos internos de Windows."
    for pf in PROGRAM_FILES:
        if is_inside(p, pf):
            return WARN, ("Está en Archivos de programa. Si la app sigue instalada, desinstálala desde la "
                          "pestaña Aplicaciones en lugar de borrar la carpeta.")
    return OK, ""


def _posix_protection(path: str) -> tuple[str, str]:
    p = norm(os.path.realpath(path)) if not os.path.islink(path) else norm(path)
    if p in ("/", ""):
        return BLOCK, "Es la raíz del disco."
    if p in [norm(x) for x in _posix_mounts()]:
        return BLOCK, "Es la raíz de un disco."
    base = [HOME, os.path.dirname(HOME), MAC_LIB, XDG_CACHE, XDG_CONFIG, XDG_DATA, os.path.join(HOME, ".local"),
            "/Applications", "/Users", "/home", "/Volumes", "/tmp", "/var/tmp", "/private", "/private/tmp", "/opt",
            "/media", "/mnt", "/srv"]
    for sub in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "Movies", "Public",
                "Escritorio", "Documentos", "Descargas", "Imágenes", "Música", "Vídeos"):
        base.append(os.path.join(HOME, sub))
    if p in [norm(b) for b in base]:
        return BLOCK, "Es una carpeta base del sistema o de tu usuario (puedes borrar su contenido, no la carpeta)."
    for sysdir in ("/System", "/usr", "/bin", "/sbin", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/boot",
                   "/dev", "/proc", "/sys", "/run", "/snap", "/var/lib", "/var/db", "/Library", "/private/etc",
                   "/private/var/db", "/cores", os.path.join(MAC_LIB, "Keychains"), os.path.join(HOME, ".ssh"),
                   os.path.join(HOME, ".gnupg")):
        if is_inside(p, sysdir):
            return BLOCK, "Carpeta protegida del sistema."
    if is_inside(p, "/Applications") or is_inside(p, "/opt"):
        return WARN, "Es una aplicación instalada. Mejor desinstálala desde la sección Aplicaciones."
    return OK, ""


# --------------------------------------------------------------------------
# Borrado
# --------------------------------------------------------------------------
@dataclass
class DeleteResult:
    freed: int = 0
    deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, o: "DeleteResult") -> None:
        self.freed += o.freed
        self.deleted += o.deleted
        self.failed += o.failed
        self.errors.extend(o.errors[:20])


def _clear_readonly(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _delete_permanent(path: str) -> DeleteResult:
    r = DeleteResult()
    if os.path.islink(path) or (os.path.isfile(path)):
        try:
            size = os.lstat(path).st_size
            try:
                os.remove(path)
            except PermissionError:
                _clear_readonly(path)
                os.remove(path)
            r.freed += size
            r.deleted += 1
        except OSError as e:
            r.failed += 1
            r.errors.append(f"{path}: {e.strerror or e}")
        return r
    # carpeta: borrar de abajo arriba saltando lo bloqueado, sin seguir enlaces
    for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                size = os.lstat(fp).st_size
                try:
                    os.remove(fp)
                except PermissionError:
                    _clear_readonly(fp)
                    os.remove(fp)
                r.freed += size
                r.deleted += 1
            except OSError as e:
                r.failed += 1
                if len(r.errors) < 20:
                    r.errors.append(f"{fp}: {e.strerror or e}")
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if os.path.islink(dp) or (hasattr(os.path, "isjunction") and os.path.isjunction(dp)):
                    os.unlink(dp) if os.path.islink(dp) else os.rmdir(dp)
                else:
                    os.rmdir(dp)
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
    return r


def _delete_recycle(path: str) -> DeleteResult:
    from send2trash import send2trash
    r = DeleteResult()
    size, n = dir_size(path)
    try:
        send2trash(path)
        r.freed += size
        r.deleted += max(n, 1)
    except Exception as e:  # noqa: BLE001
        r.failed += 1
        r.errors.append(f"{path}: {e}")
    return r


def delete_paths(paths: Iterable[str], permanent: bool,
                 progress: Callable[[str], None] | None = None,
                 trusted: bool = False) -> DeleteResult:
    """Borra rutas. Si `trusted` es False se comprueba la protección de cada ruta."""
    total = DeleteResult()
    for p in paths:
        if not os.path.lexists(p):
            continue
        if not trusted and protection_level(p)[0] == BLOCK:
            total.failed += 1
            total.errors.append(f"{p}: ruta protegida, no se ha tocado")
            continue
        if progress:
            progress(p)
        total.merge(_delete_permanent(p) if permanent else _delete_recycle(p))
    return total


# --------------------------------------------------------------------------
# Papelera de reciclaje (Windows)
# --------------------------------------------------------------------------
def _trash_dirs() -> list[str]:
    if IS_MAC:
        return [os.path.join(HOME, ".Trash")]
    return [os.path.join(XDG_DATA, "Trash", "files")]


def recycle_bin_size() -> tuple[int, int]:
    if not IS_WIN:
        size = n = 0
        for d in _trash_dirs():
            try:
                n += len(os.listdir(d))
            except OSError:
                continue
            size += dir_size(d)[0]
        return size, n
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
        return info.i64Size, info.i64NumItems
    return 0, 0


def empty_recycle_bin() -> bool:
    if not IS_WIN:
        ok = True
        dirs = _trash_dirs() + ([os.path.join(XDG_DATA, "Trash", "info")] if IS_LINUX else [])
        for d in dirs:
            try:
                entries = [e.path for e in os.scandir(d)]
            except OSError:
                continue
            ok &= delete_paths(entries, True, trusted=True).failed == 0
        return ok
    import ctypes
    res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return res in (0, -2147418113)  # S_OK o E_UNEXPECTED (ya vacía)


def is_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> bool:
    if not IS_WIN:
        return False
    import ctypes
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe, params = sys.executable, f'"{os.path.abspath(sys.argv[0])}"'
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32


def open_in_explorer(path: str) -> None:
    if IS_WIN:
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])


def launch(target: str) -> None:
    """Abre una herramienta del sistema, una URL de ajustes o un programa."""
    if IS_WIN:
        os.startfile(target)  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.Popen(["open", target])
    else:
        exe = shutil.which(target.split()[0])
        if exe:
            subprocess.Popen(target.split())
        else:
            subprocess.Popen(["xdg-open", target])


def system_tools() -> list[tuple[str, str, str]]:
    """Herramientas nativas del sistema para la página de Resumen: (título, descripción, destino)."""
    if IS_WIN:
        return [("Liberador de espacio", "Restos de actualizaciones y del sistema", "cleanmgr.exe"),
                ("Sensor de almacenamiento", "Limpieza automática programada", "ms-settings:storagesense"),
                ("Puntos de restauración", "Cuánto ocupan las copias del sistema", "SystemPropertiesProtection.exe")]
    if IS_MAC:
        return [("Almacenamiento", "Recomendaciones de espacio de macOS",
                 "x-apple.systempreferences:com.apple.settings.Storage"),
                ("Monitor de Actividad", "Procesos y uso de disco", "/System/Applications/Utilities/Activity Monitor.app"),
                ("Utilidad de Discos", "Volúmenes, particiones e instantáneas", "/System/Applications/Utilities/Disk Utility.app")]
    tools = []
    for exe, t1, t2 in (("baobab", "Analizador de uso de disco", "Herramienta de GNOME para ver el uso del disco"),
                        ("gnome-system-monitor", "Monitor del sistema", "Procesos y sistemas de archivos"),
                        ("filelight", "Filelight", "Analizador de disco de KDE"),
                        ("gnome-disks", "Discos", "Volúmenes y particiones")):
        if shutil.which(exe):
            tools.append((t1, t2, exe))
    return tools[:3]


# --------------------------------------------------------------------------
# Categorías de limpieza
# --------------------------------------------------------------------------
SAFE, REVIEW = "Seguro", "Revisar"


@dataclass
class Category:
    id: str
    group: str
    name: str
    description: str
    patterns: list[str]           # rutas o globs; se borra su CONTENIDO (o el archivo)
    risk: str = SAFE
    admin: bool = False
    close_apps: str = ""
    exclude: set[str] = field(default_factory=set)   # nombres a excluir de los globs
    min_age_days: int = 0                             # solo elementos sin tocar desde hace N días
    targets: list[str] = field(default_factory=list)
    target_sizes: dict[str, int] = field(default_factory=dict)
    size: int = 0
    files: int = 0

    def resolve(self) -> list[str]:
        out: list[str] = []
        seen = set()
        for pat in self.patterns:
            pat = os.path.expandvars(os.path.expanduser(pat))
            matches = glob.glob(pat) if any(c in pat for c in "*?[") else [pat]
            for m in matches:
                if self.exclude and os.path.basename(m).lower() in self.exclude:
                    continue
                if os.path.lexists(m) and norm(m) not in seen:
                    seen.add(norm(m))
                    out.append(m)
        return out

    def items(self) -> list[str]:
        """Elementos concretos que se borrarían (contenido de cada carpeta objetivo)."""
        items = []
        for t in self.targets:
            if os.path.isdir(t) and not os.path.islink(t):
                try:
                    items.extend(e.path for e in os.scandir(t))
                except OSError:
                    pass
            else:
                items.append(t)
        if self.min_age_days:
            import time
            limit = time.time() - self.min_age_days * 86400
            fresh = []
            for it in items:
                try:
                    if os.lstat(it).st_mtime < limit:
                        fresh.append(it)
                except OSError:
                    pass
            items = fresh
        return items


def _hf_home() -> str:
    return env("HF_HOME", os.path.join(HOME, ".cache", "huggingface"))


def _ollama_models() -> str:
    return env("OLLAMA_MODELS", os.path.join(HOME, ".ollama", "models"))


CHROMIUM_CACHE_DIRS = ["Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
                       "DawnWebGPUCache", "GrShaderCache", "ShaderCache"]


def _chromium(base: str) -> list[str]:
    pats = []
    for prof in (r"Default", r"Profile *", r"Guest Profile"):
        for c in CHROMIUM_CACHE_DIRS:
            pats.append(os.path.join(base, prof, c))
    for c in ("GrShaderCache", "ShaderCache", "component_crx_cache"):
        pats.append(os.path.join(base, c))
    return pats


def _electron_apps() -> list[str]:
    pats = []
    for base in (ROAMING, LOCAL):
        for c in ("Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
                  "DawnWebGPUCache", "CachedData", "CachedExtensionVSIXs", "Crashpad\\completed"):
            pats.append(os.path.join(base, "*", c))
    return pats


def build_categories() -> list[Category]:
    return _windows_categories() if IS_WIN else _posix_categories()


def _windows_categories() -> list[Category]:
    L, R, H, W = LOCAL, ROAMING, HOME, WINDIR
    cats = [
        # --- Sistema ---
        Category("tmp_user", "Sistema", "Temporales de usuario",
                 "Archivos temporales que dejan los programas (%TEMP%). Lo que esté en uso se salta.",
                 [TEMP]),
        Category("tmp_win", "Sistema", "Temporales de Windows",
                 r"C:\Windows\Temp. Necesita permisos de administrador.", [os.path.join(W, "Temp")], admin=True),
        Category("wu", "Sistema", "Descargas de Windows Update",
                 "Instaladores de actualizaciones ya aplicadas. Windows los vuelve a descargar si hacen falta.",
                 [os.path.join(W, "SoftwareDistribution", "Download")], admin=True),
        Category("do", "Sistema", "Caché de Optimización de distribución",
                 "Copias de actualizaciones compartidas con otros PCs.",
                 [os.path.join(W, r"ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache")],
                 admin=True),
        Category("dumps", "Sistema", "Volcados de errores e informes",
                 "Volcados de memoria tras cuelgues e informes de errores de Windows (WER).",
                 [os.path.join(L, "CrashDumps"), os.path.join(W, "Minidump"), os.path.join(W, "MEMORY.DMP"),
                  os.path.join(L, r"Microsoft\Windows\WER\ReportArchive"),
                  os.path.join(L, r"Microsoft\Windows\WER\ReportQueue"),
                  os.path.join(PROGRAMDATA, r"Microsoft\Windows\WER\ReportArchive"),
                  os.path.join(PROGRAMDATA, r"Microsoft\Windows\WER\ReportQueue")]),
        Category("thumbs", "Sistema", "Caché de miniaturas",
                 "Miniaturas de imágenes del Explorador. Se regeneran solas.",
                 [os.path.join(L, r"Microsoft\Windows\Explorer\thumbcache_*.db"),
                  os.path.join(L, r"Microsoft\Windows\Explorer\iconcache_*.db")]),
        Category("gpu", "Sistema", "Cachés de sombreadores de la GPU",
                 "Cachés de DirectX y NVIDIA/AMD. Se regeneran (los juegos pueden tardar algo más la primera vez).",
                 [os.path.join(L, "D3DSCache"), os.path.join(L, r"NVIDIA\DXCache"), os.path.join(L, r"NVIDIA\GLCache"),
                  os.path.join(L, r"NVIDIA Corporation\NV_Cache"), os.path.join(L, r"AMD\DxCache"),
                  os.path.join(L, r"AMD\DxcCache"), os.path.join(L, r"AMD\VkCache")]),
        # --- Navegadores ---
        Category("chrome", "Navegadores", "Caché de Google Chrome", "No borra contraseñas, historial ni sesiones.",
                 _chromium(os.path.join(L, r"Google\Chrome\User Data")), close_apps="Chrome"),
        Category("edge", "Navegadores", "Caché de Microsoft Edge", "No borra contraseñas, historial ni sesiones.",
                 _chromium(os.path.join(L, r"Microsoft\Edge\User Data")), close_apps="Edge"),
        Category("brave", "Navegadores", "Caché de Brave", "No borra contraseñas, historial ni sesiones.",
                 _chromium(os.path.join(L, r"BraveSoftware\Brave-Browser\User Data")), close_apps="Brave"),
        Category("opera", "Navegadores", "Caché de Opera", "No borra contraseñas, historial ni sesiones.",
                 [os.path.join(L, r"Opera Software\*\Cache"), os.path.join(R, r"Opera Software\*\Code Cache")],
                 close_apps="Opera"),
        Category("firefox", "Navegadores", "Caché de Firefox", "No borra contraseñas, historial ni sesiones.",
                 [os.path.join(L, r"Mozilla\Firefox\Profiles\*\cache2")], close_apps="Firefox"),
        Category("electron", "Navegadores", "Cachés de apps de escritorio",
                 "Cachés de apps tipo VS Code, Discord, Slack, Teams, Spotify, Cursor... Se regeneran solas.",
                 _electron_apps(), close_apps="esas aplicaciones"),
        # --- Desarrollo ---
        Category("pip", "Desarrollo", "Caché de pip (Python)", "Paquetes descargados. pip los vuelve a bajar si hacen falta.",
                 [os.path.join(L, r"pip\Cache"), os.path.join(L, r"pip\cache"), os.path.join(H, r".cache\pip")]),
        Category("uv", "Desarrollo", "Caché de uv (Python)", "Paquetes descargados por uv.",
                 [os.path.join(L, r"uv\cache"), os.path.join(H, r".cache\uv")]),
        Category("conda", "Desarrollo", "Paquetes descargados de Conda",
                 "Equivale a 'conda clean --all'. Revisa si usas entornos sin conexión.",
                 [os.path.join(H, r".conda\pkgs"), os.path.join(H, r"anaconda3\pkgs"),
                  os.path.join(H, r"miniconda3\pkgs"), os.path.join(PROGRAMDATA, r"anaconda3\pkgs"),
                  os.path.join(PROGRAMDATA, r"miniconda3\pkgs")], risk=REVIEW),
        Category("npm", "Desarrollo", "Caché de npm / yarn / pnpm / bun", "Paquetes de Node descargados.",
                 [os.path.join(L, "npm-cache"), os.path.join(R, "npm-cache"), os.path.join(L, r"Yarn\Cache"),
                  os.path.join(L, r"pnpm-cache"), os.path.join(H, r".bun\install\cache")]),
        Category("pnpm_store", "Desarrollo", "Almacén de pnpm",
                 "Paquetes compartidos por tus proyectos pnpm. Tendrás que hacer 'pnpm install' de nuevo.",
                 [os.path.join(L, r"pnpm\store")], risk=REVIEW),
        Category("gradle", "Desarrollo", "Caché de Gradle", "Dependencias y builds de Gradle/Android.",
                 [os.path.join(H, r".gradle\caches"), os.path.join(H, r".gradle\wrapper\dists"),
                  os.path.join(H, r".gradle\daemon")]),
        Category("android", "Desarrollo", "Emuladores e imágenes de Android",
                 "Emuladores (AVD) e imágenes de sistema del SDK. Ocupan mucho; bórralos si no los usas.",
                 [os.path.join(H, r".android\avd"), os.path.join(L, r"Android\Sdk\system-images")], risk=REVIEW),
        Category("maven", "Desarrollo", "Repositorio local de Maven", "Dependencias Java descargadas.",
                 [os.path.join(H, r".m2\repository")], risk=REVIEW),
        Category("nuget", "Desarrollo", "Cachés de NuGet (.NET)", "Paquetes .NET descargados.",
                 [os.path.join(L, r"NuGet\v3-cache"), os.path.join(L, r"NuGet\plugins-cache"),
                  os.path.join(H, r".nuget\packages")], risk=REVIEW),
        Category("cargo", "Desarrollo", "Caché de Cargo (Rust)", "Crates descargados.",
                 [os.path.join(H, r".cargo\registry\cache"), os.path.join(H, r".cargo\registry\src"),
                  os.path.join(H, r".cargo\git\checkouts")]),
        Category("go", "Desarrollo", "Caché de Go", "Caché de compilación y módulos de Go.",
                 [os.path.join(L, "go-build"), os.path.join(H, r"go\pkg\mod\cache")]),
        Category("platformio", "Desarrollo", "Caché de PlatformIO", "Descargas temporales de PlatformIO.",
                 [os.path.join(H, r".platformio\.cache")]),
        Category("electron_dl", "Desarrollo", "Cachés de Electron / Playwright / Cypress",
                 "Binarios descargados por herramientas de desarrollo.",
                 [os.path.join(L, r"electron\Cache"), os.path.join(L, r"electron-builder\Cache"),
                  os.path.join(L, r"Cypress\Cache"), os.path.join(L, "ms-playwright")], risk=REVIEW),
        Category("unity", "Desarrollo", "Caché de Unity", "Caché de assets y paquetes de Unity.",
                 [os.path.join(L, r"Unity\cache"), os.path.join(R, r"Unity\Asset Store-5.x")], risk=REVIEW),
        Category("vs", "Desarrollo", "Caché de instaladores de Visual Studio",
                 "Paquetes de instalación de Visual Studio.",
                 [os.path.join(PROGRAMDATA, r"Microsoft\VisualStudio\Packages")], risk=REVIEW, admin=True),
        # --- IA / Modelos ---
        Category("hf", "IA / Modelos", "Modelos de Hugging Face",
                 "Modelos y datasets descargados (transformers, diffusers...). Se vuelven a descargar al usarlos.",
                 [os.path.join(_hf_home(), "hub"), os.path.join(_hf_home(), "datasets"),
                  os.path.join(_hf_home(), "xet")], risk=REVIEW),
        Category("ollama", "IA / Modelos", "Modelos de Ollama",
                 "TODOS los modelos de Ollama. Para borrar solo algunos usa la pestaña 'Modelos IA'.",
                 [_ollama_models()], risk=REVIEW),
        Category("lmstudio", "IA / Modelos", "Modelos de LM Studio", "Modelos GGUF/MLX descargados en LM Studio.",
                 [os.path.join(H, r".lmstudio\models"), os.path.join(H, r".cache\lm-studio\models")], risk=REVIEW),
        Category("torch", "IA / Modelos", "Caché de PyTorch / Whisper",
                 "Pesos descargados por torch.hub, Whisper, etc.",
                 [os.path.join(H, r".cache\torch"), os.path.join(H, r".cache\whisper")], risk=REVIEW),
        Category("ml_misc", "IA / Modelos", "Otros modelos (Keras, DeepFace, rembg, ModelScope...)",
                 "Pesos descargados por librerías de IA. Se vuelven a descargar al usarlas.",
                 [os.path.join(H, r".keras\models"), os.path.join(H, r".deepface\weights"),
                  os.path.join(H, ".rembg"), os.path.join(H, ".u2net"), os.path.join(H, ".modelscope"),
                  os.path.join(H, r".cache\modelscope"), os.path.join(H, ".pkuseg"),
                  os.path.join(H, r".cache\insightface"), os.path.join(H, ".insightface"),
                  os.path.join(H, r".cache\clip"), os.path.join(H, r".cache\paddle"),
                  os.path.join(H, r".EasyOCR\model")], risk=REVIEW),
        Category("gpt4all", "IA / Modelos", "Modelos de GPT4All / Jan",
                 "Modelos descargados por GPT4All o Jan.",
                 [os.path.join(L, r"nomic.ai\GPT4All"), os.path.join(H, r"jan\models"),
                  os.path.join(R, r"Jan\data\models")], risk=REVIEW),
    ]
    return cats


def _posix_categories() -> list[Category]:
    H, C, L, CFG, DATA = HOME, XDG_CACHE, MAC_LIB, XDG_CONFIG, XDG_DATA
    mc = os.path.join(L, "Caches")          # ~/Library/Caches (macOS)
    sup = os.path.join(L, "Application Support")
    user_cache = mc if IS_MAC else C

    def uc(*names):  # caché de usuario según el sistema
        return [os.path.join(user_cache, n) for n in names]

    # Subcarpetas de la caché de usuario que ya cubren otras categorías (para no contarlas dos veces)
    handled = {"pip", "uv", "yarn", "pnpm", "go-build", "ms-playwright", "cypress", "electron", "electron-builder",
               "huggingface", "torch", "whisper", "lm-studio", "modelscope", "insightface", "clip", "paddle",
               "jetbrains", "homebrew", "com.apple.dt.xcode", "bun", "node-gyp", "deno", "thumbnails",
               "conda", "pypoetry", "typescript", "mesa_shader_cache", "nvidia", "fontconfig"}
    cats = [
        Category("tmp_user", "Sistema", "Temporales antiguos",
                 f"Archivos temporales de más de 2 días en {TEMP}. Los recientes no se tocan.",
                 [os.path.join(TEMP, "*")], min_age_days=2),
        Category("app_cache", "Navegadores", "Cachés de apps y navegadores",
                 ("Cachés de ~/Library/Caches (Safari, Chrome, Spotify, Slack...). Se regeneran solas."
                  if IS_MAC else "Cachés de ~/.cache (Chrome, Firefox, Spotify, Slack...). Se regeneran solas."),
                 [os.path.join(user_cache, "*")], exclude=handled, close_apps="los navegadores y apps abiertas"),
        Category("electron", "Navegadores", "Cachés de apps de escritorio",
                 "Cachés de apps tipo VS Code, Discord, Slack, Teams, Cursor... Se regeneran solas.",
                 [os.path.join(sup if IS_MAC else CFG, "*", c) for c in
                  ("Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache",
                   "CachedData", "CachedExtensionVSIXs", "Service Worker/CacheStorage")]
                 + [os.path.join(sup if IS_MAC else CFG, d, "Default", c)
                    for d in ("Google/Chrome", "google-chrome", "chromium", "BraveSoftware/Brave-Browser",
                              "Microsoft Edge", "microsoft-edge")
                    for c in ("Code Cache", "GPUCache", "Service Worker/CacheStorage")],
                 close_apps="esas aplicaciones"),
        Category("logs", "Sistema", "Registros de usuario",
                 "Logs de aplicaciones (~/Library/Logs)." if IS_MAC else "Registros de aplicaciones y volcados de errores.",
                 [os.path.join(L, "Logs", "*")] if IS_MAC else
                 [os.path.join(DATA, "xorg", "*.log*"), os.path.join(H, ".xsession-errors.old"),
                  "/var/crash/*", os.path.join(DATA, "recently-used.xbel.bak")], min_age_days=1),
        Category("thumbs", "Sistema", "Caché de miniaturas", "Miniaturas de imágenes. Se regeneran solas.",
                 [os.path.join(C, "thumbnails"), os.path.join(H, ".thumbnails")] if IS_LINUX else
                 [os.path.join(L, "Caches", "com.apple.QuickLook.thumbnailcache")]),
        Category("gpu", "Sistema", "Cachés de sombreadores de la GPU", "Se regeneran (los juegos pueden tardar algo más).",
                 [os.path.join(C, "mesa_shader_cache"), os.path.join(C, "nvidia"), os.path.join(H, ".nv", "GLCache"),
                  os.path.join(C, "radv_builtin_shaders64")]),
        # --- Desarrollo ---
        Category("pip", "Desarrollo", "Caché de pip / Poetry (Python)", "Paquetes descargados. Se vuelven a bajar si hacen falta.",
                 uc("pip", "pypoetry") + [os.path.join(C, "pip")]),
        Category("uv", "Desarrollo", "Caché de uv (Python)", "Paquetes descargados por uv.",
                 [os.path.join(C, "uv")] + uc("uv")),
        Category("conda", "Desarrollo", "Paquetes descargados de Conda",
                 "Equivale a 'conda clean --all'. Revisa si usas entornos sin conexión.",
                 [os.path.join(H, d, "pkgs") for d in (".conda", "anaconda3", "miniconda3", "miniforge3", "mambaforge")]
                 + ["/opt/anaconda3/pkgs", "/opt/miniconda3/pkgs", "/opt/homebrew/Caskroom/miniconda/base/pkgs"],
                 risk=REVIEW),
        Category("npm", "Desarrollo", "Caché de npm / yarn / pnpm / bun / deno", "Paquetes de Node descargados.",
                 [os.path.join(H, ".npm", "_cacache"), os.path.join(H, ".npm", "_npx"), os.path.join(H, ".bun", "install", "cache"),
                  os.path.join(H, ".yarn", "berry", "cache")] + uc("yarn", "Yarn", "node-gyp", "deno", "typescript", "bun")),
        Category("pnpm_store", "Desarrollo", "Almacén de pnpm",
                 "Paquetes compartidos por tus proyectos pnpm. Tendrás que hacer 'pnpm install' de nuevo.",
                 [os.path.join(DATA, "pnpm", "store"), os.path.join(L, "pnpm", "store")] + uc("pnpm"), risk=REVIEW),
        Category("gradle", "Desarrollo", "Caché de Gradle", "Dependencias y builds de Gradle/Android.",
                 [os.path.join(H, ".gradle", d) for d in ("caches", "wrapper/dists", "daemon")]),
        Category("android", "Desarrollo", "Emuladores e imágenes de Android",
                 "Emuladores (AVD) e imágenes de sistema del SDK. Ocupan mucho; bórralos si no los usas.",
                 [os.path.join(H, ".android", "avd"), os.path.join(H, "Android", "Sdk", "system-images"),
                  os.path.join(L, "Android", "sdk", "system-images")], risk=REVIEW),
        Category("xcode", "Desarrollo", "Xcode: DerivedData y simuladores",
                 "Compilaciones intermedias, cachés de simuladores y soporte de dispositivos antiguos.",
                 [os.path.join(L, "Developer", "Xcode", "DerivedData"), os.path.join(L, "Developer", "Xcode", "iOS DeviceSupport"),
                  os.path.join(L, "Developer", "Xcode", "watchOS DeviceSupport"),
                  os.path.join(L, "Developer", "CoreSimulator", "Caches"), os.path.join(mc, "com.apple.dt.Xcode")]),
        Category("xcode_arch", "Desarrollo", "Xcode: archivos de apps (Archives)", "Builds archivados para publicar en la App Store.",
                 [os.path.join(L, "Developer", "Xcode", "Archives")], risk=REVIEW),
        Category("brew", "Desarrollo", "Caché de Homebrew", "Descargas de Homebrew. Equivale a 'brew cleanup'.",
                 uc("Homebrew")),
        Category("maven", "Desarrollo", "Repositorio local de Maven", "Dependencias Java descargadas.",
                 [os.path.join(H, ".m2", "repository")], risk=REVIEW),
        Category("nuget", "Desarrollo", "Cachés de NuGet (.NET)", "Paquetes .NET descargados.",
                 [os.path.join(H, ".nuget", "packages"), os.path.join(DATA, "NuGet", "v3-cache")], risk=REVIEW),
        Category("cargo", "Desarrollo", "Caché de Cargo (Rust)", "Crates descargados.",
                 [os.path.join(H, ".cargo", "registry", "cache"), os.path.join(H, ".cargo", "registry", "src"),
                  os.path.join(H, ".cargo", "git", "checkouts")]),
        Category("go", "Desarrollo", "Caché de Go", "Caché de compilación y módulos de Go.",
                 uc("go-build") + [os.path.join(H, "go", "pkg", "mod", "cache")]),
        Category("platformio", "Desarrollo", "Caché de PlatformIO", "Descargas temporales de PlatformIO.",
                 [os.path.join(H, ".platformio", ".cache")]),
        Category("electron_dl", "Desarrollo", "Cachés de Electron / Playwright / Cypress",
                 "Binarios descargados por herramientas de desarrollo.",
                 uc("electron", "electron-builder", "Cypress", "ms-playwright") + [os.path.join(C, "Cypress")], risk=REVIEW),
        Category("jetbrains", "Desarrollo", "Cachés de JetBrains", "Índices y cachés de IntelliJ, PyCharm, WebStorm...",
                 uc("JetBrains")),
        Category("unity", "Desarrollo", "Caché de Unity", "Caché de assets y paquetes de Unity.",
                 uc("unity3d") + [os.path.join(C, "unity3d"), os.path.join(L, "Unity", "cache")], risk=REVIEW),
        # --- IA / Modelos ---
        Category("hf", "IA / Modelos", "Modelos de Hugging Face",
                 "Modelos y datasets descargados (transformers, diffusers...). Se vuelven a descargar al usarlos.",
                 [os.path.join(_hf_home(), "hub"), os.path.join(_hf_home(), "datasets"),
                  os.path.join(_hf_home(), "xet")], risk=REVIEW),
        Category("ollama", "IA / Modelos", "Modelos de Ollama",
                 "TODOS los modelos de Ollama. Para borrar solo algunos usa la sección «Modelos IA».",
                 [_ollama_models()], risk=REVIEW),
        Category("lmstudio", "IA / Modelos", "Modelos de LM Studio", "Modelos GGUF/MLX descargados en LM Studio.",
                 [os.path.join(H, ".lmstudio", "models"), os.path.join(C, "lm-studio", "models")], risk=REVIEW),
        Category("torch", "IA / Modelos", "Caché de PyTorch / Whisper", "Pesos descargados por torch.hub, Whisper, etc.",
                 [os.path.join(C, "torch"), os.path.join(C, "whisper")], risk=REVIEW),
        Category("ml_misc", "IA / Modelos", "Otros modelos (Keras, DeepFace, rembg, ModelScope...)",
                 "Pesos descargados por librerías de IA. Se vuelven a descargar al usarlas.",
                 [os.path.join(H, ".keras", "models"), os.path.join(H, ".deepface", "weights"), os.path.join(H, ".rembg"),
                  os.path.join(H, ".u2net"), os.path.join(H, ".modelscope"), os.path.join(C, "modelscope"),
                  os.path.join(H, ".pkuseg"), os.path.join(C, "insightface"), os.path.join(H, ".insightface"),
                  os.path.join(C, "clip"), os.path.join(C, "paddle"), os.path.join(H, ".EasyOCR", "model")], risk=REVIEW),
        Category("gpt4all", "IA / Modelos", "Modelos de GPT4All / Jan", "Modelos descargados por GPT4All o Jan.",
                 [os.path.join(DATA, "nomic.ai", "GPT4All"), os.path.join(sup, "nomic.ai", "GPT4All"),
                  os.path.join(H, "jan", "models"), os.path.join(sup, "Jan", "data", "models")], risk=REVIEW),
    ]
    if IS_MAC:
        cats = [c for c in cats if c.id not in ("gpu",)]
    else:
        cats = [c for c in cats if c.id not in ("xcode", "xcode_arch")]
        cats.insert(2, Category("pkg_cache", "Sistema", "Caché de paquetes del sistema",
                                "Paquetes .deb/.rpm ya instalados (apt/dnf/pacman). Necesita permisos de administrador.",
                                ["/var/cache/apt/archives/*.deb", "/var/cache/pacman/pkg/*", "/var/cache/dnf/*"],
                                admin=True))
    return cats


def scan_category(cat: Category, cancel: threading.Event | None = None) -> Category:
    cat.targets = cat.resolve()
    cat.size = cat.files = 0
    cat.target_sizes = {}
    if cat.min_age_days:
        for it in cat.items():
            s, n = dir_size(it, cancel)
            cat.size += s
            cat.files += n
        cat.target_sizes = {t: 0 for t in cat.targets}
        return cat
    for t in cat.targets:
        s, n = dir_size(t, cancel)
        cat.target_sizes[t] = s
        cat.size += s
        cat.files += n
    return cat


def clean_category(cat: Category, permanent: bool,
                   progress: Callable[[str], None] | None = None) -> DeleteResult:
    # Las rutas de las categorías son fijas y conocidas: se borra su contenido.
    return delete_paths(cat.items(), permanent, progress, trusted=True)


# --------------------------------------------------------------------------
# Analizador de carpetas (un solo recorrido: árbol + archivos grandes + modelos)
# --------------------------------------------------------------------------
class Node:
    __slots__ = ("name", "path", "size", "files", "children", "own_files", "top_files", "is_file")

    def __init__(self, name: str, path: str, is_file: bool = False):
        self.name = name
        self.path = path
        self.size = 0
        self.files = 0
        self.own_files = 0  # bytes de archivos directamente en esta carpeta
        self.children: list[Node] = []
        self.top_files: list[Node] = []  # archivos grandes de esta carpeta (para dibujarlos en el mapa)
        self.is_file = is_file


TOP_FILE_MIN = 1024 * 1024   # archivos de 1 MB o más se guardan uno a uno en el árbol
TOP_FILES_PER_DIR = 30


@dataclass
class ScanResult:
    root: Node
    big_files: list[tuple[int, str]]
    model_files: list[tuple[int, str]]
    errors: int
    ext_stats: dict[str, list[int]] = field(default_factory=dict)      # ext -> [bytes, files]
    size_buckets: dict[int, list[str]] = field(default_factory=dict)  # tamaño -> rutas (≥ 1 MB)
    mtimes: dict[str, float] = field(default_factory=dict)            # ruta -> fecha (archivos grandes)

    def kinds(self) -> list[tuple[str, int, int]]:
        """Uso por tipo de archivo: [(tipo, bytes, archivos)] de mayor a menor."""
        agg: dict[str, list[int]] = {}
        for ext, (b, n) in self.ext_stats.items():
            k = kind_of(ext)
            a = agg.setdefault(k, [0, 0])
            a[0] += b
            a[1] += n
        return sorted(((k, b, n) for k, (b, n) in agg.items()), key=lambda x: x[1], reverse=True)


KINDS = {
    "Vídeo": "mp4 mkv avi mov wmv flv webm m4v mpg mpeg ts m2ts 3gp vob",
    "Imágenes": "jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 nef arw dng psd svg ico avif exr hdr",
    "Audio": "mp3 wav flac aac ogg m4a wma opus aiff alac mid midi",
    "Documentos": "pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf md csv epub mobi pages numbers key",
    "Comprimidos y discos": "zip rar 7z tar gz tgz bz2 xz zst iso img dmg vhd vhdx vmdk qcow2 cab wim esd",
    "Modelos de IA": "gguf ggml safetensors ckpt pt pth onnx h5 keras tflite pb mlmodel npz",
    "Programas e instaladores": "exe msi dll sys app pkg deb rpm appimage apk ipa so dylib jar msix appx snap flatpak",
    "Código y desarrollo": "py js ts tsx jsx java c cpp h hpp cs go rs rb php swift kt json xml yml yaml html css "
                           "scss lock map pyc class o obj lib a pdb wasm ipynb",
    "Bases de datos y caché": "db sqlite sqlite3 ldb log tmp cache dat idx pack bin",
    "Juegos y 3D": "pak vpk unity3d assets fbx obj blend glb gltf uasset umap bsa ba2",
}
_KIND_BY_EXT = {e: k for k, exts in KINDS.items() for e in exts.split()}


def kind_of(ext: str) -> str:
    return _KIND_BY_EXT.get(ext.lower().lstrip("."), "Otros")


def _physical_size(entry: os.DirEntry, seen: set[tuple[int, int]]) -> int:
    """Espacio que ocupa de verdad: bloques reservados en macOS/Linux y enlaces duros una sola vez."""
    if IS_WIN:
        return _entry_size(entry)[0]
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return 0
    if stat.S_ISLNK(st.st_mode):
        return 0
    if st.st_nlink > 1:
        key = (st.st_dev, st.st_ino)
        if key in seen:
            return 0
        seen.add(key)
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def files_inside(node: Node) -> list[Node]:
    """Archivos grandes guardados uno a uno de una carpeta (ya ordenados de mayor a menor)."""
    return node.top_files


def loose_bytes(node: Node) -> int:
    """Bytes de archivos de la carpeta que no se guardan uno a uno (pequeños)."""
    return max(0, node.own_files - sum(f.size for f in node.top_files))


def local_snapshots() -> list[str]:
    """Instantáneas locales de Time Machine (macOS). Pueden ocupar mucho sin verse en Finder."""
    if not IS_MAC:
        return []
    try:
        out = subprocess.run(["tmutil", "listlocalsnapshots", "/"], capture_output=True, text=True,
                             timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in out.splitlines() if "com.apple" in ln]


SKIP_ROOT_DIRS = {"/proc", "/sys", "/dev", "/run", "/System/Volumes", "/Volumes", "/private/var/vm", "/snap"}


def scan_tree(root_path: str, cancel: threading.Event | None = None,
              progress: Callable[[int, int, str], None] | None = None,
              top_n: int = 1000) -> ScanResult:
    root = Node(root_path, root_path)
    big: list[tuple[int, str]] = []  # min-heap
    exts: dict[str, list[int]] = {}
    buckets: dict[int, list[str]] = {}
    skip = {norm(p) for p in SKIP_ROOT_DIRS} if not IS_WIN else set()
    models: list[tuple[int, str]] = []
    errors = 0
    count = 0
    total_bytes = 0
    seen_links: set[tuple[int, int]] = set()  # enlaces duros: solo cuentan una vez
    # recorrido iterativo en pre-orden; luego se suman tamaños en post-orden
    order: list[Node] = []
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        node = stack.pop()
        order.append(node)
        try:
            with os.scandir(node.path) as it:
                entries = list(it)
        except OSError:
            errors += 1
            continue
        tops: list[tuple[int, str, str]] = []
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if _is_link_dir(e) or (skip and norm(e.path) in skip):
                        continue
                    child = Node(e.name, e.path)
                    node.children.append(child)
                    stack.append(child)
                else:
                    s = _physical_size(e, seen_links)
                    if s >= TOP_FILE_MIN:
                        tops.append((s, e.name, e.path))
                    node.own_files += s
                    node.files += 1
                    count += 1
                    total_bytes += s
                    dot = e.name.rfind(".")
                    ext = e.name[dot + 1:].lower() if 0 < dot < len(e.name) - 1 else ""
                    st = exts.get(ext)
                    if st is None:
                        exts[ext] = [s, 1]
                    else:
                        st[0] += s
                        st[1] += 1
                    if s >= 1024 * 1024:
                        buckets.setdefault(s, []).append(e.path)
                    if len(big) < top_n:
                        heapq.heappush(big, (s, e.path))
                    elif s > big[0][0]:
                        heapq.heapreplace(big, (s, e.path))
                    if s >= MODEL_MIN_SIZE and os.path.splitext(e.name)[1].lower() in MODEL_EXTENSIONS:
                        models.append((s, e.path))
                    elif s >= MODEL_MIN_SIZE and "blobs" in e.path.lower() and e.name.startswith("sha256"):
                        models.append((s, e.path))
            except OSError:
                errors += 1
        if tops:
            tops.sort(reverse=True)
            for s, name, path in tops[:TOP_FILES_PER_DIR]:
                f = Node(name, path, True)
                f.size, f.files = s, 1
                node.top_files.append(f)
        if progress and len(order) % 200 == 0:
            progress(count, total_bytes, node.path)
    for node in reversed(order):
        node.size = node.own_files + sum(c.size for c in node.children)
        node.files += sum(c.files for c in node.children)
        node.children.sort(key=lambda c: c.size, reverse=True)
    big.sort(reverse=True)
    models.sort(reverse=True)
    mtimes = {}
    for _s, p in big:
        try:
            mtimes[p] = os.stat(p).st_mtime
        except OSError:
            pass
    buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    return ScanResult(root, big, models, errors, exts, buckets, mtimes)


# --------------------------------------------------------------------------
# Duplicados (mismo tamaño -> mismo hash parcial -> mismo hash completo)
# --------------------------------------------------------------------------
def _hash(path: str, partial: bool, cancel=None) -> str | None:
    import hashlib
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as fh:
            if partial:
                h.update(fh.read(65536))
                try:
                    fh.seek(-65536, os.SEEK_END)
                except OSError:
                    pass
                h.update(fh.read(65536))
            else:
                while True:
                    if cancel is not None and cancel.is_set():
                        return None
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


@dataclass
class DupGroup:
    size: int
    paths: list[str]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.paths) - 1)


def find_duplicates(res: "ScanResult", min_size: int = 1024 * 1024, cancel=None,
                    progress: Callable[[str], None] | None = None) -> list[DupGroup]:
    groups: list[DupGroup] = []
    cands = sorted(((s, p) for s, p in res.size_buckets.items() if s >= min_size), reverse=True)
    for size, paths in cands:
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(paths[0])
        seen_ino, uniq = set(), []
        for p in paths:  # los enlaces duros no son duplicados reales
            try:
                st = os.stat(p)
                key = (st.st_dev, st.st_ino)
            except OSError:
                continue
            if key[1] and key in seen_ino:
                continue
            seen_ino.add(key)
            uniq.append(p)
        by_part: dict[str, list[str]] = {}
        for p in uniq:
            hp = _hash(p, True)
            if hp:
                by_part.setdefault(hp, []).append(p)
        for same in by_part.values():
            if len(same) < 2:
                continue
            if size <= 131072:
                groups.append(DupGroup(size, same))
                continue
            by_full: dict[str, list[str]] = {}
            for p in same:
                hf = _hash(p, False, cancel)
                if hf:
                    by_full.setdefault(hf, []).append(p)
            groups.extend(DupGroup(size, g) for g in by_full.values() if len(g) > 1)
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups


def export_csv(res: "ScanResult", path: str) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["tipo", "ruta", "bytes", "tamaño", "archivos"])
        stack = [(res.root, 0)]
        while stack:
            n, depth = stack.pop()
            w.writerow(["carpeta", n.path, n.size, human(n.size), n.files])
            if depth < 3:
                stack.extend((c, depth + 1) for c in reversed(n.children[:50]))
        for s, p in res.big_files:
            w.writerow(["archivo", p, s, human(s), 1])


# --------------------------------------------------------------------------
# Ollama: nombres de modelos a partir de los manifiestos
# --------------------------------------------------------------------------
@dataclass
class OllamaModel:
    name: str
    size: int
    blobs: list[str]
    manifest: str


def list_ollama_models() -> list[OllamaModel]:
    base = _ollama_models()
    mroot = os.path.join(base, "manifests")
    out: list[OllamaModel] = []
    if not os.path.isdir(mroot):
        return out
    for root, _dirs, files in os.walk(mroot):
        for f in files:
            mp = os.path.join(root, f)
            try:
                with open(mp, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            rel = os.path.relpath(mp, mroot).replace("\\", "/").split("/")
            # registry.ollama.ai/library/llama3/latest -> llama3:latest
            if len(rel) >= 2:
                name = ("/".join(rel[2:-1]) if rel[1] == "library" else "/".join(rel[1:-1])) + ":" + rel[-1]
                if rel[0] != "registry.ollama.ai":
                    name = rel[0] + "/" + name
            else:
                name = f
            blobs, size = [], 0
            for layer in [data.get("config", {})] + data.get("layers", []):
                dg = layer.get("digest", "")
                if dg:
                    bp = os.path.join(base, "blobs", dg.replace(":", "-"))
                    blobs.append(bp)
                    size += layer.get("size", 0)
            out.append(OllamaModel(name, size, blobs, mp))
    out.sort(key=lambda m: m.size, reverse=True)
    return out


def ollama_remove(name: str) -> tuple[bool, str]:
    exe = shutil.which("ollama")
    if not exe:
        return False, "No se encuentra el comando 'ollama'."
    flags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
    try:
        p = subprocess.run([exe, "rm", name], capture_output=True, text=True, timeout=120, creationflags=flags)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


# --------------------------------------------------------------------------
# Aplicaciones instaladas y posibles residuos
# --------------------------------------------------------------------------
@dataclass
class InstalledApp:
    name: str
    publisher: str
    version: str
    size: int            # bytes (estimado por el instalador o calculado)
    location: str
    uninstall: str
    install_date: str
    source: str


def _run(cmd: list[str], timeout=60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _mac_apps() -> list[InstalledApp]:
    import plistlib
    apps = []
    for base in ("/Applications", os.path.join(HOME, "Applications"), "/Applications/Utilities"):
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith(".app") or not e.is_dir():
                continue
            info = {}
            try:
                with open(os.path.join(e.path, "Contents", "Info.plist"), "rb") as fh:
                    info = plistlib.load(fh)
            except Exception:  # noqa: BLE001
                pass
            name = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or e.name[:-4])
            try:
                date = __import__("time").strftime("%Y%m%d", __import__("time").localtime(e.stat().st_mtime))
            except OSError:
                date = ""
            apps.append(InstalledApp(name=name, publisher=str(info.get("CFBundleIdentifier", "")),
                                     version=str(info.get("CFBundleShortVersionString", "")), size=0,
                                     location=e.path, uninstall="trash:" + e.path, install_date=date,
                                     source="Usuario" if base.startswith(HOME) else "Sistema"))
    return apps


def _linux_apps() -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    out = _run(["dpkg-query", "-W", "-f=${Package}\t${Installed-Size}\t${Version}\t${Maintainer}\n"]) \
        if shutil.which("dpkg-query") else ""
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            size = int(parts[1]) * 1024 if parts[1].isdigit() else 0
            apps.append(InstalledApp(parts[0], parts[3] if len(parts) > 3 else "", parts[2], size, "",
                                     f"sudo apt remove {parts[0]}", "", "apt"))
    if not apps and shutil.which("rpm"):
        for line in _run(["rpm", "-qa", "--queryformat", "%{NAME}\t%{SIZE}\t%{VERSION}\t%{VENDOR}\n"]).splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                mgr = "dnf" if shutil.which("dnf") else "zypper" if shutil.which("zypper") else "rpm -e"
                cmd = f"sudo {mgr} remove {parts[0]}" if mgr != "rpm -e" else f"sudo rpm -e {parts[0]}"
                apps.append(InstalledApp(parts[0], parts[3] if len(parts) > 3 else "", parts[2],
                                         int(parts[1]) if parts[1].isdigit() else 0, "", cmd, "", "rpm"))
    if not apps and shutil.which("pacman"):
        name = ver = ""
        size = 0
        for line in _run(["pacman", "-Qi"], timeout=120).splitlines() + [""]:
            if line.startswith("Name"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Version"):
                ver = line.split(":", 1)[1].strip()
            elif line.startswith("Installed Size"):
                val = line.split(":", 1)[1].strip().split()
                try:
                    mult = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}.get(val[1], 1)
                    size = int(float(val[0].replace(",", ".")) * mult)
                except (IndexError, ValueError):
                    size = 0
            elif not line.strip() and name:
                apps.append(InstalledApp(name, "", ver, size, "", f"sudo pacman -R {name}", "", "pacman"))
                name, ver, size = "", "", 0
    if shutil.which("flatpak"):
        for line in _run(["flatpak", "list", "--app", "--columns=name,application,version,size,installation"]).splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                apps.append(InstalledApp(parts[0], parts[1], parts[2] if len(parts) > 2 else "",
                                         _parse_size(parts[3]) if len(parts) > 3 else 0,
                                         os.path.join(XDG_DATA, "flatpak", "app", parts[1])
                                         if len(parts) > 4 and parts[4] == "user" else
                                         os.path.join("/var/lib/flatpak/app", parts[1]),
                                         f"flatpak uninstall {parts[1]}", "", "flatpak"))
    if shutil.which("snap"):
        for line in _run(["snap", "list"]).splitlines()[1:]:
            parts = line.split()
            if parts:
                loc = os.path.join("/snap", parts[0])
                apps.append(InstalledApp(parts[0], parts[4] if len(parts) > 4 else "", parts[1] if len(parts) > 1 else "",
                                         0, loc, f"sudo snap remove {parts[0]}", "", "snap"))
    return apps


def _parse_size(txt: str) -> int:
    m = re.match(r"([\d.,]+)\s*([kMGT]?B)", txt.strip().replace("\xa0", " "))
    if not m:
        return 0
    mult = {"B": 1, "kB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4}[m.group(2)]
    return int(float(m.group(1).replace(",", ".")) * mult)


def list_installed_apps() -> list[InstalledApp]:
    if not IS_WIN:
        apps = _mac_apps() if IS_MAC else _linux_apps()
        return sorted(apps, key=lambda a: a.size, reverse=True)
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    ]
    apps: dict[tuple[str, str], InstalledApp] = {}
    for hive, path, flag in keys:
        try:
            k = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as sk:
                        def val(n, d=""):
                            try:
                                return winreg.QueryValueEx(sk, n)[0]
                            except OSError:
                                return d
                        name = str(val("DisplayName")).strip()
                        if not name or val("SystemComponent", 0) == 1 or val("ParentKeyName"):
                            continue
                        rtype = str(val("ReleaseType"))
                        if rtype in ("Update", "Hotfix", "Security Update"):
                            continue
                        loc = str(val("InstallLocation")).strip().strip('"')
                        app = InstalledApp(
                            name=name, publisher=str(val("Publisher")), version=str(val("DisplayVersion")),
                            size=int(val("EstimatedSize", 0) or 0) * 1024, location=loc,
                            uninstall=str(val("UninstallString")),
                            install_date=str(val("InstallDate")),
                            source="Usuario" if hive == winreg.HKEY_CURRENT_USER else "Sistema")
                        key = (name.lower(), app.version)
                        if key not in apps or app.size > apps[key].size:
                            apps[key] = app
                except OSError:
                    continue
    return sorted(apps.values(), key=lambda a: a.size, reverse=True)


def list_store_apps_dirs() -> list[str]:
    if not IS_WIN:
        return []
    p = os.path.join(LOCAL, "Packages")
    try:
        return [e.name for e in os.scandir(p) if e.is_dir()]
    except OSError:
        return []


_IGNORE_RESIDUE = {
    "microsoft", "windows", "packages", "temp", "programs", "connecteddevicesplatform", "d3dscache",
    "crashdumps", "comms", "history", "publishers", "virtualstore", "placeholdertilelogofolder",
    "peerdistrepub", "ssh", "package cache", "packagecache", "regid1991-06comMicrosoft".lower(),
    "microsoft help", "windowsapps", "common files", "windows defender", "windows mail",
    "windows media player", "windows nt", "windows photo viewer", "windows sidebar",
    "windowspowershell", "internet explorer", "modifiablewindowsapps", "reference assemblies",
    "msbuild", "uninstall information", "microsoft.net", "dotnet", "application data", "desktop",
    "documents", "start menu", "templates", "favorites", "ntuser", "usoshared", "usoprivate",
    "softwaredistribution", "ssh", "regid.1991-06.com.microsoft", "intel", "nvidia", "nvidia corporation",
    "amd", "realtek", "lenovo", "iconcache.db", "fontcache", "identities", "igfxcache",
    "pip", "npm-cache", "npm", "nuget", "yarn", "pnpm", "go-build", "uv", "tempfiles", "low",
    "google", "mozilla", "apple", "apple computer", "adobe", "oracle", "java", "python", "node",
    "github", "jetbrains", "programdata", "package", "cache", "caches", "logs", "lockdown",
    "mozilla maintenance service", "windows kits", "windows sdks", "sxs", "sxsback", "winsxs",
    "speech", "speech engines", "ssh", "openssh", "git", "dbg", "symbols",
}


def _tok(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


@dataclass
class Residue:
    path: str
    size: int
    where: str


def find_residues(apps: list[InstalledApp], cancel: threading.Event | None = None,
                  min_size: int = 20 * 1024 * 1024,
                  progress: Callable[[str], None] | None = None) -> list[Residue]:
    """Carpetas de AppData/ProgramData/Program Files que no se parecen a ninguna app instalada.

    Es una heurística: el resultado son *posibles* residuos que el usuario debe revisar.
    """
    known: set[str] = set()
    words: set[str] = set()
    for a in apps:
        for s in (a.name, a.publisher, os.path.basename(a.location.rstrip("\\/"))):
            t = _tok(s)
            if len(t) >= 3:
                known.add(t)
            for w in re.split(r"[\s\-_.,()]+", s.lower()):
                w = _tok(w)
                if len(w) >= 4 and w not in {"microsoft", "windows", "version", "edition", "update",
                                              "runtime", "redistributable", "corporation", "software",
                                              "studio", "tools", "driver", "package", "for", "and"}:
                    words.add(w)
    for pkg in list_store_apps_dirs():
        words.update(_tok(x) for x in pkg.split(".") if len(_tok(x)) >= 4)
    # Ejecutables en PATH también cuentan como "instalados"
    for d in env("PATH").split(os.pathsep):
        for part in d.replace("/", "\\").split("\\"):
            t = _tok(part)
            if len(t) >= 4:
                words.add(t)

    def looks_installed(name: str) -> bool:
        t = _tok(name)
        if not t or name.lower() in _IGNORE_RESIDUE or t in {_tok(x) for x in _IGNORE_RESIDUE}:
            return True
        if name.startswith((".", "{", "$")) or name.lower().startswith(("microsoft", "windows", "msbuild", "nvidia", "intel")):
            return True
        if t in known or any(t in k or (len(k) >= 4 and k in t) for k in known):
            return True
        return any(w in t or (len(t) >= 4 and t in w) for w in words)

    if IS_WIN:
        bases = [(ROAMING, "AppData\\Roaming"), (LOCAL, "AppData\\Local"),
                 (os.path.join(LOCAL, "Programs"), "AppData\\Local\\Programs"),
                 (PROGRAMDATA, "ProgramData")] + [(p, os.path.basename(p)) for p in PROGRAM_FILES]
    elif IS_MAC:
        bases = [(os.path.join(MAC_LIB, "Application Support"), "Library/Application Support"),
                 (os.path.join(MAC_LIB, "Containers"), "Library/Containers"),
                 (os.path.join(MAC_LIB, "Group Containers"), "Library/Group Containers"),
                 (os.path.join(MAC_LIB, "Caches"), "Library/Caches"),
                 (os.path.join(MAC_LIB, "Preferences"), "Library/Preferences")]
    else:
        bases = [(XDG_CONFIG, "~/.config"), (XDG_DATA, "~/.local/share"),
                 (os.path.join(HOME, ".var", "app"), "~/.var/app (Flatpak)")]
    out: list[Residue] = []
    seen = set()
    for base, label in bases:
        try:
            entries = [e for e in os.scandir(base) if e.is_dir(follow_symlinks=False) and not _is_link_dir(e)]
        except OSError:
            continue
        for e in entries:
            if cancel is not None and cancel.is_set():
                return out
            if norm(e.path) in seen or looks_installed(e.name):
                continue
            seen.add(norm(e.path))
            if progress:
                progress(e.path)
            size, _ = dir_size(e.path, cancel)
            if size >= min_size:
                out.append(Residue(e.path, size, label))
    out.sort(key=lambda r: r.size, reverse=True)
    return out


def run_uninstaller(cmd: str) -> None:
    """Windows: abre el desinstalador oficial. macOS: manda la .app a la Papelera.
    Linux: no se ejecuta nada aquí (la interfaz muestra y copia el comando)."""
    if not cmd:
        raise ValueError("Esta aplicación no tiene desinstalador registrado.")
    if cmd.startswith("trash:"):
        from send2trash import send2trash
        send2trash(cmd[6:])
        return
    if not IS_WIN:
        raise ValueError(cmd)
    subprocess.Popen(cmd, shell=True)
