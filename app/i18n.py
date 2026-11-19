"""Idiomas de la interfaz.

Los textos se escriben en español en el código y se envuelven con T():

    T("Analizando {path}…", path=p)

El español es la clave: cada idioma tiene un diccionario {texto en español: traducción} en locales/<código>.py.
Si falta una traducción se muestra el texto en español. El idioma se fija al arrancar (cambiarlo reinicia la
app), así que T() también vale en constantes de módulo.
"""
from __future__ import annotations

import json
import os
import sys

LANGS = [("es", "Español"), ("en", "English"), ("fr", "Français"), ("de", "Deutsch"), ("it", "Italiano"),
         ("zh", "简体中文"), ("ja", "日本語")]
CODES = [c for c, _ in LANGS]


def _settings_path() -> str:
    """Mismo archivo que core.load_settings() (aquí sin importar core para evitar el ciclo)."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "DesktopFreeSpace", "settings.json")


def _system_lang() -> str:
    """Idioma del sistema (código de 2 letras) o "" si no se sabe."""
    names = []
    if sys.platform == "win32":
        try:
            import ctypes
            import locale
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            names.append(locale.windows_locale.get(lcid, ""))
        except Exception:  # noqa: BLE001
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=2).stdout
            names += [x.strip(' "\n,()') for x in out.split("\n") if x.strip(' "\n,()')]
        except Exception:  # noqa: BLE001
            pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        names += os.environ.get(var, "").split(":")
    try:
        import locale
        names.append(locale.getlocale()[0] or "")
    except Exception:  # noqa: BLE001
        pass
    for n in names:
        code = n.replace("-", "_").split("_")[0].lower()
        if code in CODES:
            return code
        if n.lower().startswith(("chinese", "japanese", "english", "french", "german", "italian", "spanish")):
            return {"ch": "zh", "ja": "ja", "en": "en", "fr": "fr", "ge": "de", "it": "it", "sp": "es"}[n[:2].lower()]
    return ""


def saved_lang() -> str:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            v = json.load(fh).get("lang", "")
        return v if v in CODES else ""
    except (OSError, ValueError, AttributeError):
        return ""


def _load(code: str) -> dict:
    # Importaciones explícitas: así PyInstaller incluye los idiomas en el ejecutable.
    try:
        if code == "en":
            from locales import en as m
        elif code == "fr":
            from locales import fr as m
        elif code == "de":
            from locales import de as m
        elif code == "it":
            from locales import it as m
        elif code == "zh":
            from locales import zh as m
        elif code == "ja":
            from locales import ja as m
        else:
            return {}
    except ImportError:
        return {}
    return getattr(m, "T", {})


_forced = os.environ.get("DFS_LANG", "")  # para pruebas: fuerza un idioma sin tocar los ajustes
LANG = (_forced if _forced in CODES else "") or saved_lang() or _system_lang() or "en"


def system_lang() -> str:
    """Idioma que se usa en modo automático."""
    return _system_lang() or "en"


def choice() -> str:
    """Lo elegido por el usuario: un código de idioma o "auto" (sigue al sistema; es lo predeterminado)."""
    return saved_lang() or "auto"
_TABLE = _load(LANG)


def T(text: str, **kw) -> str:
    """Texto traducido. Con argumentos, rellena los {campos} después de traducir."""
    s = _TABLE.get(text) or text
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)
    return s


def texts(code: str):
    """Traductor de otro idioma (sin cambiar el actual): para avisar en el idioma que se acaba de elegir."""
    table = _TABLE if code == LANG else _load(code)
    return lambda text: table.get(text) or text


_SEP = {"es": ".", "de": ".", "it": ".", "fr": " ", "en": ",", "zh": ",", "ja": ","}


def num(n) -> str:
    """Entero con separador de miles del idioma (1.234.567 / 1,234,567 / 1 234 567)."""
    return f"{int(n):,}".replace(",", _SEP.get(LANG, ","))


def date_text(y: int, m: int, d: int) -> str:
    """Fecha corta del idioma: 5 ene 2026 / Jan 5, 2026 / 2026年1月5日…"""
    if LANG in ("zh", "ja"):
        return f"{y}年{m}月{d}日"
    months = {
        "es": "ene feb mar abr may jun jul ago sep oct nov dic",
        "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
        "fr": "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.",
        "de": "Jan. Feb. März Apr. Mai Juni Juli Aug. Sep. Okt. Nov. Dez.",
        "it": "gen feb mar apr mag giu lug ago set ott nov dic",
    }.get(LANG, "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec").split()
    mon = months[m - 1]
    if LANG == "en":
        return f"{mon} {d}, {y}"
    if LANG == "de":
        return f"{d}. {mon} {y}"
    return f"{d} {mon} {y}"


def set_lang(code: str) -> None:
    """Guarda el idioma elegido ("auto" = el del sistema). Se aplica al reiniciar."""
    path = _settings_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["lang"] = code
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
