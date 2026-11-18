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
SYSDRIVE = env("SystemDrive", "C:") + os.sep
TEMP = env("TEMP", os.path.join(LOCAL, "Temp"))
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
        roots = ["/"]
    out = []
    for r in roots:
        try:
            u = shutil.disk_usage(r)
            out.append(DriveInfo(r, u.total, u.used, u.free))
        except OSError:
            pass
    return out


def system_files_info() -> list[tuple[str, str, int, str]]:
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
def recycle_bin_size() -> tuple[int, int]:
    if not IS_WIN:
        return 0, 0
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
        return False
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
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])


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


def scan_category(cat: Category, cancel: threading.Event | None = None) -> Category:
    cat.targets = cat.resolve()
    cat.size = cat.files = 0
    cat.target_sizes = {}
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
    __slots__ = ("name", "path", "size", "files", "children", "own_files")

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.size = 0
        self.files = 0
        self.own_files = 0  # bytes de archivos directamente en esta carpeta
        self.children: list[Node] = []


@dataclass
class ScanResult:
    root: Node
    big_files: list[tuple[int, str]]
    model_files: list[tuple[int, str]]
    errors: int


def scan_tree(root_path: str, cancel: threading.Event | None = None,
              progress: Callable[[int, int, str], None] | None = None,
              top_n: int = 1000) -> ScanResult:
    root = Node(root_path, root_path)
    big: list[tuple[int, str]] = []  # min-heap
    models: list[tuple[int, str]] = []
    errors = 0
    count = 0
    total_bytes = 0
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
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if _is_link_dir(e):
                        continue
                    child = Node(e.name, e.path)
                    node.children.append(child)
                    stack.append(child)
                else:
                    s, _ = _entry_size(e)
                    node.own_files += s
                    node.files += 1
                    count += 1
                    total_bytes += s
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
        if progress and len(order) % 200 == 0:
            progress(count, total_bytes, node.path)
    for node in reversed(order):
        node.size = node.own_files + sum(c.size for c in node.children)
        node.files += sum(c.files for c in node.children)
        node.children.sort(key=lambda c: c.size, reverse=True)
    big.sort(reverse=True)
    models.sort(reverse=True)
    return ScanResult(root, big, models, errors)


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


def list_installed_apps() -> list[InstalledApp]:
    if not IS_WIN:
        return []
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

    bases = [(ROAMING, "AppData\\Roaming"), (LOCAL, "AppData\\Local"),
             (os.path.join(LOCAL, "Programs"), "AppData\\Local\\Programs"),
             (PROGRAMDATA, "ProgramData")] + [(p, os.path.basename(p)) for p in PROGRAM_FILES]
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
    if not cmd:
        raise ValueError("Esta aplicación no tiene desinstalador registrado.")
    subprocess.Popen(cmd, shell=True)
