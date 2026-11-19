"""Desktop Free Space: interfaz gráfica para ver y liberar espacio en disco (Windows, macOS y Linux)."""
from __future__ import annotations

import colorsys
import math
import os
import queue
import random
import shutil
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, font as tkfont, ttk

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
from core import human  # noqa: E402
import i18n  # noqa: E402
from i18n import T, num, date_text  # noqa: E402,F401

APP_NAME = "Desktop Free Space"
VERSION = "2.8.1"

# ---------------------------------------------------------------------------
# Sistema visual
# ---------------------------------------------------------------------------
C = {
    "bg": "#0a0f1e",          # fondo de la ventana (azul noche)
    "side": "#0c1224",        # barra lateral
    "surface": "#111933",     # tarjetas
    "surface2": "#172142",    # elementos dentro de tarjetas
    "hover": "#1d2a52",
    "border": "#1e2a4c",
    "track": "#1a2547",       # fondo de anillos y barras
    "odd": "#131c39",
    "scroll": "#22305a",
    "scroll_h": "#2c3d70",
    "text": "#eef2ff",
    "muted": "#97a3c7",
    "faint": "#5f6c94",
    "accent": "#3d7bfd",      # azul
    "accent2": "#8b5cf6",     # violeta (degradados)
    "accent_h": "#2f6bf0",
    "accent_soft": "#16295c",
    "ok": "#3ddc97",
    "warn": "#ffc145",
    "bad": "#ff6b6b",
    "bad_h": "#f04452",
    "bad_hh": "#d93644",
    "bad_soft": "#2a1430",
    "bad_soft_h": "#3a1a3c",
    "bad_border": "#4d1f40",
    "bad_off": "#7a2e45",     # botón rojo desactivado (texto blanco legible)
    "sel": "#1f3a85",
    "row_hover": "#1a2651",   # fila bajo el ratón
    "row_hover_on": "#1c3170",  # fila marcada bajo el ratón
    "check_off": "#53618f",   # borde de la casilla sin marcar
    "menu": "#131c3a",        # menú contextual
    "menu_border": "#2b3a68",
    "menu_hover": "#223164",
}
RADIUS = 16
UI_FONT = "Segoe UI"
MONO_FONT = "Consolas"
FILE_MANAGER = T("Explorador") if core.IS_WIN else "Finder" if core.IS_MAC else T("gestor de archivos")
ICON_FONT = None
ICONS_MDL2 = {"home": "\uE80F", "clean": "\uE75C", "folder": "\uE8B7", "file": "\uE7C3", "ai": "\uE99A",
              "apps": "\uE71D", "shield": "\uEA18", "trash": "\uE74D", "drive": "\uEDA2", "check": "\uE73E",
              "info": "\uE946", "warn": "\uE7BA", "map": "\uE81E", "list": "\uE8FD", "copy": "\uE8C8",
              "eye": "\uE890", "open": "\uE838", "add": "\uE710", "link": "\uE71B", "search": "\uE721",
              "enter": "\uE76C", "globe": "\uE774"}
ICONS_FALLBACK = {"home": "⌂", "clean": "✦", "folder": "▤", "file": "▦", "ai": "◈", "apps": "▣", "shield": "⛨",
                  "trash": "✕", "drive": "◉", "check": "✓", "info": "i", "warn": "!", "map": "◔", "list": "≡",
                  "copy": "⧉", "eye": "◉", "open": "▤", "add": "+", "link": "⧉", "search": "⌕", "enter": "›", "globe": "◍"}


def icon(name: str) -> str:
    return (ICONS_MDL2 if ICON_FONT else ICONS_FALLBACK).get(name, "•")


def F(size=13, weight="normal"):
    return ctk.CTkFont(family=UI_FONT, size=size, weight=weight)


def IF(size=16):
    return ctk.CTkFont(family=ICON_FONT or UI_FONT, size=size)


def level_color(pct: float) -> str:
    return C["bad"] if pct >= 0.9 else C["warn"] if pct >= 0.75 else C["ok"]


def card(master, **kw):
    return ctk.CTkFrame(master, fg_color=C["surface"], corner_radius=RADIUS, border_width=1,
                        border_color=C["border"], **kw)


BTN_STYLES = {
    # Radio 8 en botones y controles: a 125 % y 150 % son píxeles enteros (sin escalón en los cantos).
    "primary": dict(fg_color=C["accent"], hover_color=C["accent_h"], text_color="#ffffff",
                    text_color_disabled="#ffffff", border_width=0),
    "secondary": dict(fg_color=C["surface2"], hover_color=C["hover"], text_color=C["text"],
                      border_width=1, border_color=C["border"]),
    "danger": dict(fg_color=C["bad_soft"], hover_color=C["bad_soft_h"], text_color=C["bad"],
                   border_width=1, border_color=C["bad_border"]),
    "danger_solid": dict(fg_color=C["bad_h"], hover_color=C["bad_hh"], text_color="#ffffff",
                         text_color_disabled="#ffffff", border_width=0),
    "ghost": dict(fg_color="transparent", hover_color=C["hover"], text_color=C["muted"], border_width=0),
}


def btn(master, text, command=None, kind="secondary", width=0):
    return ctk.CTkButton(master, text=text, command=command, corner_radius=8, height=36, font=F(13, "bold"),
                         width=width, **BTN_STYLES[kind])


def set_dark_titlebar(win):
    if not core.IS_WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        r, g, b = _rgb(C["bg"])
        col = ctypes.c_int((b << 16) | (g << 8) | r)  # color de la barra (BGR) en Windows 11
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Imágenes pequeñas con suavizado (casillas y puntos de color de las tablas)
# ---------------------------------------------------------------------------
_IMG_CACHE: dict = {}


def _aa_image(key, size, draw, fallback, height=None):
    """Dibuja a 4x y reduce para tener bordes suaves (sin Pillow, un dibujo simple). key=None: sin caché."""
    img = _IMG_CACHE.get(key) if key is not None else None
    if img is None:
        w, h = size, height or size
        if Image is None:
            img = fallback(w) if height is None else fallback(w, h)
        else:
            im = Image.new("RGBA", (w * 4, h * 4), (0, 0, 0, 0))
            draw(ImageDraw.Draw(im), w * 4) if height is None else draw(ImageDraw.Draw(im), w * 4, h * 4)
            img = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
        if key is not None:
            _IMG_CACHE[key] = img
    return img


def _pi_box(size, fill=None, border=None):
    img = tk.PhotoImage(width=size, height=size)
    if fill:
        img.put(fill, to=(0, 0, size, size))
    if border:
        for box in ((0, 0, size, 1), (0, size - 1, size, size), (0, 0, 1, size), (size - 1, 0, size, size)):
            img.put(border, to=box)
    return img


def check_image(state: str, k: float):
    """Casilla de verificación: 'off', 'on' o 'mixed'."""
    size = max(14, round(18 * k))

    def draw(d, s):
        r = s * 0.27
        white = (255, 255, 255, 255)
        if state == "off":
            lw = max(4, round(s * 0.09))
            d.rounded_rectangle((lw / 2, lw / 2, s - 1 - lw / 2, s - 1 - lw / 2), r - lw / 2,
                                fill=(255, 255, 255, 10), outline=_rgb(C["check_off"]) + (255,), width=lw)
            return
        d.rounded_rectangle((0, 0, s - 1, s - 1), r, fill=_rgb(C["accent"]) + (255,))
        w = round(s * 0.12)
        if state == "on":
            pts = [(s * 0.27, s * 0.52), (s * 0.44, s * 0.68), (s * 0.74, s * 0.34)]
            d.line(pts, fill=white, width=w, joint="curve")
            for x, y in (pts[0], pts[-1]):
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=white)
        else:
            d.rounded_rectangle((s * 0.27, s * 0.5 - w / 2, s * 0.73, s * 0.5 + w / 2), w / 2, fill=white)

    def fallback(n):
        if state == "off":
            return _pi_box(n, border=C["check_off"])
        img = _pi_box(n, fill=C["accent"])
        q = n // 4
        img.put("#ffffff", to=(q, q, n - q, n - q) if state == "on" else (q, n // 2 - 1, n - q, n // 2 + 1))
        return img

    return _aa_image(("chk", state, size), size, draw, fallback)


def share_image(color: str, shape: str, frac: float, k: float):
    """Marcador de fila: punto del color de su sector (cuadrado = carpeta, círculo = archivo, anillo = resto)
    y una barra fina con la parte que ocupa."""
    w, h = round(86 * k), max(10, round(12 * k))

    def draw(d, W, H):
        rgb = _rgb(color) + (255,)
        s_ = H
        if shape == "dir":
            d.rounded_rectangle((0, 0, s_ - 1, s_ - 1), s_ * 0.3, fill=rgb)
        elif shape == "file":
            d.ellipse((s_ * 0.06, s_ * 0.06, s_ * 0.94, s_ * 0.94), fill=rgb)
        else:
            lw = round(s_ * 0.16)
            d.ellipse((lw / 2, lw / 2, s_ - 1 - lw / 2, s_ - 1 - lw / 2), outline=rgb, width=lw)
        x0, x1 = s_ + H * 0.9, W - 1
        bh = H * 0.42
        y0, y1 = (H - bh) / 2, (H + bh) / 2
        d.rounded_rectangle((x0, y0, x1, y1), bh / 2, fill=_rgb(C["track"]) + (255,))
        if frac > 0:
            xf = x0 + max(bh, (x1 - x0) * min(frac, 1.0))
            d.rounded_rectangle((x0, y0, xf, y1), bh / 2, fill=rgb)

    def fallback(W, H):
        img = tk.PhotoImage(width=W, height=H)
        img.put(color, to=(0, 0, H, H))
        x0 = H + H
        img.put(C["track"], to=(x0, H // 3, W, H - H // 3))
        if frac > 0:
            img.put(color, to=(x0, H // 3, x0 + max(2, int((W - x0) * min(frac, 1.0))), H - H // 3))
        return img

    return _aa_image(None, w, draw, fallback, height=h)


# ---------------------------------------------------------------------------
# Menú contextual propio (sustituye al menú nativo, que no se puede estilizar)
# ---------------------------------------------------------------------------
def mi(label, fn, ico="", hint="", danger=False):
    """Entrada de menú: texto, acción, icono, atajo a la derecha y si es destructiva."""
    return (label, fn, ico, hint, danger)


SEP = ("-", None)


def _win11() -> bool:
    try:
        return core.IS_WIN and sys.getwindowsversion().build >= 22000
    except Exception:  # noqa: BLE001
        return False


def _work_area(x, y, widget):
    """Área útil del monitor que contiene el punto (sin barra de tareas)."""
    if core.IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = ctypes.c_void_p
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
            mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def _dwm_popup(win, border: str):
    """Windows 11: esquinas redondeadas, borde fino y sombra del sistema en una ventana sin marco."""
    try:
        import ctypes

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        r, g, b = _rgb(border)

        def put(attr, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        put(33, 2)                          # DWMWA_WINDOW_CORNER_PREFERENCE = ROUND
        put(34, (b << 16) | (g << 8) | r)   # DWMWA_BORDER_COLOR
        put(2, 2)                           # DWMWA_NCRENDERING_POLICY = ENABLED (sombra)
        m = MARGINS(1, 1, 1, 1)
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
        return True
    except Exception:  # noqa: BLE001
        return False


class PopupMenu(tk.Toplevel):
    """Menú flotante oscuro: cabecera con lo seleccionado, iconos, atajos, resaltado redondeado y teclado."""

    current: "PopupMenu | None" = None

    def __init__(self, master, items, x, y, title="", subtitle="", min_width=0, above=False):
        self.above = above
        if PopupMenu.current is not None:
            PopupMenu.current.close()
        super().__init__(master)
        PopupMenu.current = self
        self.withdraw()
        self.overrideredirect(True)
        self.k = k = _scale_of(master)
        self._native = _win11()
        self.configure(bg=C["menu"] if self._native else C["menu_border"])
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        px = lambda v: round(v * k)  # noqa: E731
        body = tk.Frame(self, bg=C["menu"], bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=0 if self._native else 1, pady=0 if self._native else 1)
        inner = tk.Frame(body, bg=C["menu"], bd=0, highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=px(6), pady=px(6))
        tk.Frame(inner, bg=C["menu"], height=0,  # ancho mínimo
                 width=max(0 if min_width else px(236), min_width - 2 * px(6))).pack()

        if title:
            hd = tk.Frame(inner, bg=C["menu"])
            hd.pack(fill="x", padx=px(12), pady=(px(6), px(8)))
            ctk.CTkLabel(hd, text=title, font=F(13, "bold"), text_color=C["text"], anchor="w", height=20,
                         fg_color=C["menu"]).pack(fill="x")
            if subtitle:
                ctk.CTkLabel(hd, text=subtitle, font=F(11), text_color=C["muted"], anchor="w", height=16,
                             fg_color=C["menu"]).pack(fill="x", pady=(1, 0))
            self._sep(inner)

        self.rows: list[dict] = []
        for it in items:
            if not it or it[0] == "-":
                if self.rows:
                    self._sep(inner)
                continue
            label, fn, ico, hint, danger = (tuple(it) + ("", "", False))[:5]
            row = ctk.CTkFrame(inner, fg_color=C["menu"], bg_color=C["menu"], corner_radius=8)
            row.pack(fill="x", pady=1)
            fg = C["bad"] if danger else C["text"]
            ic = ctk.CTkLabel(row, text=icon(ico) if ico else "", font=IF(15), width=22, height=34,
                              text_color=C["bad"] if danger else C["muted"], fg_color="transparent")
            ic.pack(side="left", padx=(12, 10))
            lb = ctk.CTkLabel(row, text=label, font=F(13), text_color=fg, anchor="w", height=34,
                              fg_color="transparent")
            hl = None
            if hint:
                hl = ctk.CTkLabel(row, text=hint, font=F(11), text_color=C["faint"], height=34,
                                  fg_color="transparent")
                hl.pack(side="right", padx=(16, 12))
            lb.pack(side="left", fill="x", expand=True, padx=(0, 0 if hint else 18))
            self.rows.append(dict(frame=row, icon=ic, label=lb, hint=hl, fn=fn, danger=danger))
        self._active = None

        self.bind("<Motion>", self._track)
        self.bind("<Leave>", self._track)
        self.bind("<ButtonPress>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Tab>", lambda e: (self._step(1), "break")[1])
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self._invoke(self._active))
        self.bind("<FocusOut>", lambda e: self.after(60, self._check_focus))
        self._place(x, y)

    # -- construcción y colocación --
    def _sep(self, parent):
        tk.Frame(parent, bg=C["border"], height=max(1, round(self.k))).pack(fill="x", padx=round(10 * self.k),
                                                                          pady=round(5 * self.k))

    def _place(self, x, y):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        left, top, right, bottom = _work_area(x, y, self)
        nx = x + 2 if x + 2 + w <= right else max(left, x - w - 2)
        if self.above:
            ny = y - h - 4 if y - h - 4 >= top else min(y + 2, bottom - h)
        else:
            ny = y + 2 if y + 2 + h <= bottom else max(top, y - h - 2)
        self.geometry(f"+{nx}+{ny}")
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.deiconify()
        self.update_idletasks()
        if self._native:
            _dwm_popup(self, C["menu_border"])
        self.lift()
        self._fade(0)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()

    def _fade(self, i, n=5):
        try:
            self.attributes("-alpha", min(1.0, (i + 1) / n))
        except tk.TclError:
            return
        if i + 1 < n:
            self.after(14, lambda: self._fade(i + 1, n))

    # -- interacción --
    def _row_at(self, x_root, y_root):
        w = self.winfo_containing(x_root, y_root)
        while w is not None and w is not self:
            for i, r in enumerate(self.rows):
                if w is r["frame"]:
                    return i
            w = getattr(w, "master", None)
        return None

    def _inside(self, x_root, y_root):
        return (self.winfo_rootx() <= x_root < self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y_root < self.winfo_rooty() + self.winfo_height())

    def _track(self, e):
        self._activate(self._row_at(e.x_root, e.y_root) if self._inside(e.x_root, e.y_root) else None)

    def _activate(self, i):
        if i == self._active:
            return
        for j in (self._active, i):
            if j is None:
                continue
            r, on = self.rows[j], j == i
            bg = (C["bad_soft_h"] if r["danger"] else C["menu_hover"]) if on else C["menu"]
            r["frame"].configure(fg_color=bg)
            r["icon"].configure(text_color=C["bad"] if r["danger"] else (C["text"] if on else C["muted"]))
            if r["hint"] is not None:
                r["hint"].configure(text_color=C["muted"] if on else C["faint"])
        self._active = i

    def _step(self, d):
        if self.rows:
            self._activate(((self._active if self._active is not None else (-1 if d > 0 else 0)) + d)
                           % len(self.rows))
        return "break"

    def _press(self, e):
        if not self._inside(e.x_root, e.y_root):
            self.close()

    def _release(self, e):
        if self._inside(e.x_root, e.y_root):
            self._invoke(self._row_at(e.x_root, e.y_root))

    def _invoke(self, i):
        if i is None:
            return
        fn = self.rows[i]["fn"]
        master = self.master
        self.close()
        if fn:
            master.after(15, fn)

    def _check_focus(self):
        try:
            if self.winfo_exists() and self.focus_get() is None:
                self.close()
        except (tk.TclError, KeyError):
            self.close()

    def close(self):
        if PopupMenu.current is self:
            PopupMenu.current = None
        try:
            self.grab_release()
            self.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Estado vacío: insignia grande con degradado, título, explicación y acción directa
# ---------------------------------------------------------------------------
def _icon_font_file():
    """Archivo de la fuente de iconos para dibujarla con Pillow (Segoe Fluent Icons / MDL2 en Windows)."""
    if not core.IS_WIN or not ICON_FONT:
        return None
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in (("SegoeIcons.ttf", "segmdl2.ttf") if "Fluent" in ICON_FONT else ("segmdl2.ttf", "SegoeIcons.ttf")):
        path = os.path.join(fonts, name)
        if os.path.exists(path):
            return path
    return None


def badge_image(ico: str, k: float, size: int = 92):
    """Círculo con degradado azul → violeta, halo suave y el icono en blanco. None si no se puede dibujar."""
    if Image is None:
        return None
    font_file = _icon_font_file()
    if not font_file:
        return None
    px = round(size * k)
    key = ("badge", ico, px)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    try:
        from PIL import ImageFont
        S = px * 4
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        a1, a2 = _rgb(C["accent"]), _rgb(C["accent2"])
        d.ellipse((0, 0, S - 1, S - 1), fill=a1 + (22,))                        # halo exterior
        m = S * 0.09
        d.ellipse((m, m, S - 1 - m, S - 1 - m), fill=a1 + (34,))                # halo interior
        r0 = S * 0.2
        n = int(S - 2 * r0)
        grad = Image.new("RGBA", (n, n))
        gd = ImageDraw.Draw(grad)
        for i in range(2 * n):                                                 # degradado diagonal
            t = i / (2 * n - 1)
            col = tuple(int(a + (b - a) * t) for a, b in zip(a1, a2)) + (255,)
            gd.line((i, 0, 0, i), fill=col, width=2)
        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, n - 1, n - 1), fill=255)
        im.paste(grad, (int(r0), int(r0)), mask)
        d = ImageDraw.Draw(im)
        d.ellipse((r0, r0, S - 1 - r0, S - 1 - r0), outline=(255, 255, 255, 40), width=max(2, S // 90))
        font = ImageFont.truetype(font_file, int(S * 0.27))
        d.text((S / 2, S / 2), ICONS_MDL2.get(ico, ICONS_MDL2["info"]), font=font, fill=(255, 255, 255, 255),
               anchor="mm")
        img = ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))
    except Exception:  # noqa: BLE001
        return None
    _IMG_CACHE[key] = img
    return img


class EmptyState(ctk.CTkFrame):
    """Mensaje para listas vacías. Se compacta solo (quita botón, texto…) si no cabe en su sitio."""

    def __init__(self, master, ico="info", title="", text="", action=None, bg=None):
        self.bgc = bg or C["surface"]
        super().__init__(master, fg_color=self.bgc, corner_radius=0)
        self.k = _scale_of(master)
        self._level = None
        self.badge_img = tk.Label(self, bg=self.bgc, bd=0, highlightthickness=0)
        self.badge_ctk = ctk.CTkLabel(self, text="", font=IF(28), width=68, height=68, corner_radius=34,
                                      fg_color=C["accent_soft"], text_color=C["accent"])
        self.badge = self.badge_img
        self.title = ctk.CTkLabel(self, text="", font=F(16, "bold"), text_color=C["text"], fg_color=self.bgc)
        self.text = ctk.CTkLabel(self, text="", font=F(12), text_color=C["muted"], fg_color=self.bgc,
                                 wraplength=520, justify="center")
        self.button = btn(self, "", None, "primary")
        self.set(ico, title, text, action)

    def set(self, ico="info", title="", text="", action=None):
        img = badge_image(ico, self.k)
        self.badge.pack_forget()
        if img is not None:
            self.badge_img.configure(image=img)
            self.badge = self.badge_img
        else:  # sin Pillow o sin fuente de iconos: círculo dibujado por CustomTkinter
            self.badge_ctk.configure(text=icon(ico))
            self.badge = self.badge_ctk
        self.title.configure(text=title)
        self.text.configure(text=text)
        self._has_text, self._action = bool(text), action
        if action:
            self.button.configure(text=f"  {action[0]}  ", command=action[1])
        self._level = None
        self.fit(10 ** 6)

    def fit_width(self, width):
        """El texto se ajusta al ancho del panel (paneles estrechos como el del Mapa)."""
        self.text.configure(wraplength=max(200, min(520, int(width / self.k) - 70)))

    def fit(self, avail):
        """Muestra todo lo que quepa en `avail` píxeles de alto: insignia, título, texto y botón."""
        k = self.k
        need = {"badge": 98 * k, "title": 30 * k, "text": 44 * k if self._has_text else 0,
                "button": 56 * k if self._action else 0}
        level = 0
        for parts in (("badge", "title", "text", "button"), ("badge", "title", "text"), ("title", "text"),
                      ("title",)):
            if sum(need[p] for p in parts) <= avail or parts == ("title",):
                break
            level += 1
        if level == self._level:
            return
        self._level = level
        show = [("badge", "title", "text", "button"), ("badge", "title", "text"), ("title", "text"),
                ("title",)][level]
        for w in (self.badge_img, self.badge_ctk, self.title, self.text, self.button):
            w.pack_forget()
        if "badge" in show:
            self.badge.pack(pady=(0, 10))
        self.title.pack()
        if "text" in show and self._has_text:
            self.text.pack(pady=(4, 0))
        if "button" in show and self._action:
            self.button.pack(pady=(16, 0))


class Select(ctk.CTkOptionMenu):
    """Desplegable que abre el mismo menú flotante que el resto de la app (en vez del menú nativo)."""

    def _open_dropdown_menu(self):
        cur = self.get()
        items = [mi(v, lambda v=v: self._dropdown_callback(v), "check" if v == cur else "") for v in self._values]
        PopupMenu(self, items, self.winfo_rootx() - 2, self.winfo_rooty() + self.winfo_height() + 2,
                  min_width=self.winfo_width())


# ---------------------------------------------------------------------------
# Tabla (Treeview oscuro, orden por columnas, casillas reales y fila resaltada al pasar el ratón)
# ---------------------------------------------------------------------------
class Table(ctk.CTkFrame):
    def __init__(self, master, columns, checkable=False, height=14, on_open=None, on_select=None,
                 empty=None, icons=False):
        super().__init__(master, fg_color=C["surface"], corner_radius=RADIUS, border_width=1,
                         border_color=C["border"])
        self.k = _scale_of(self)
        self.checkable = checkable
        self.icons = icons and not checkable
        self.checked: set[str] = set()
        self.data: dict[str, object] = {}
        self.sort_keys: dict[str, dict[str, object]] = {}
        self.base_tags: dict[str, tuple] = {}
        self._hover: str | None = None
        self._cursor = ""
        self._head_job = None
        self._menu_items: list = []
        self._images: dict[str, object] = {}
        self.ids = [c[0] for c in columns]
        self.titles = {c[0]: c[1] for c in columns}
        lead = checkable or self.icons
        self.tv = ttk.Treeview(self, columns=self.ids, show="tree headings" if lead else "headings",
                               height=max(4, round(height * 0.62)), selectmode="extended",
                               style="Dark.Treeview")  # pide poco alto: se expande con la ventana
        if lead:
            w = round((48 if checkable else 112) * self.k)
            self.tv.column("#0", width=w, minwidth=w, stretch=False, anchor="center")
            if checkable:
                self.tv.heading("#0", text="", image=check_image("off", self.k), anchor="center",
                                command=self._toggle_all)
            else:
                self.tv.heading("#0", text="", anchor="center")
        for cid, title, width, anchor in columns:
            self.tv.heading(cid, text=title, anchor=anchor, command=lambda c=cid: self.sort_by(c))
            self.tv.column(cid, width=width, anchor=anchor, stretch=cid in ("name", "path"))
        sb = ctk.CTkScrollbar(self, command=self.tv.yview, fg_color="transparent",
                              button_color=C["scroll"], button_hover_color=C["scroll_h"])
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        sb.grid(row=0, column=1, sticky="ns", padx=(2, 6), pady=12)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        for tag, bg in (("odd", C["odd"]), ("checked", C["accent_soft"]), ("hover", C["row_hover"]),
                        ("hover_on", C["row_hover_on"])):
            self.tv.tag_configure(tag, background=bg)
        self.tv.tag_configure("warn", foreground=C["warn"])
        self.tv.tag_configure("muted", foreground=C["faint"])
        self.empty = EmptyState(self, *empty) if empty else None
        if self.empty is not None:
            self.bind("<Configure>", lambda e: (self.empty.fit_width(e.width),
                                                self.empty.fit(e.height - 70 * self.k)), add="+")
        self._update_empty()
        if checkable:
            self.tv.bind("<Button-1>", self._on_click, add="+")
            self.tv.bind("<space>", self._on_space, add="+")
        self.tv.bind("<Motion>", self._on_motion, add="+")
        self.tv.bind("<Leave>", lambda e: self._set_hover(None), add="+")
        if on_open:
            self.tv.bind("<Double-1>", lambda e: self._on_double(e, on_open), add="+")
        if on_select:
            self.tv.bind("<<TreeviewSelect>>", lambda e: on_select(self.focused()), add="+")
        self._sort_state: dict[str, bool] = {}

    # -- filas --
    def _update_empty(self):
        if self.empty is None:
            return
        if self.tv.get_children():
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.53, anchor="center")

    def set_empty(self, ico, title, text="", action=None):
        """Cambia el mensaje de lista vacía (p. ej. «sin resultados» tras filtrar)."""
        if self.empty is None:
            self.empty = EmptyState(self, ico, title, text, action)
            self.bind("<Configure>", lambda e: (self.empty.fit_width(e.width),
                                                self.empty.fit(e.height - 70 * self.k)), add="+")
        else:
            self.empty.set(ico, title, text, action)
        self.empty.fit(self.winfo_height() - 70 * self.k if self.winfo_height() > 1 else 10 ** 6)
        self._update_empty()

    def clear(self):
        self.tv.delete(*self.tv.get_children())
        self.checked.clear()
        self.data.clear()
        self.sort_keys.clear()
        self.base_tags.clear()
        self._images.clear()
        self._hover = None
        self._update_empty()
        self._sync_head()

    def add(self, key, values, obj=None, sort=None, tags=(), checked=False, image=None):
        idx = len(self.data)
        self.base_tags[key] = tuple(tags)
        if checked and self.checkable:
            self.checked.add(key)
        kw = {}
        if self.checkable:
            kw["image"] = check_image("on" if checked else "off", self.k)
        elif self.icons and image is not None:
            kw["image"] = self._images[key] = image
        self.tv.insert("", "end", iid=key, values=list(values), tags=self._tags(key, idx), **kw)
        self.data[key] = obj
        self.sort_keys[key] = sort or {}
        if idx == 0:
            self._update_empty()
        if checked:
            self._schedule_head()
        return key

    def remove(self, keys):
        for k in keys:
            if self.tv.exists(k):
                self.tv.delete(k)
            self.checked.discard(k)
            for d in (self.data, self.sort_keys, self.base_tags, self._images):
                d.pop(k, None)
        if self._hover not in self.data:
            self._hover = None
        self.restripe()
        self._update_empty()
        self._sync_head()

    def restripe(self):
        for i, k in enumerate(self.tv.get_children()):
            self.tv.item(k, tags=self._tags(k, i))

    def _tags(self, key, idx):
        on = key in self.checked
        if key == self._hover:
            bg = "hover_on" if on else "hover"
        else:
            bg = "checked" if on else ("odd" if idx % 2 else "even")
        return self.base_tags.get(key, ()) + (bg,)

    def _paint(self, key, idx=None):
        if self.tv.exists(key):
            self.tv.item(key, tags=self._tags(key, self.tv.index(key) if idx is None else idx))

    def focused(self):
        f = self.tv.focus()
        return self.data.get(f) if f else None

    def selected(self):
        return [self.data[i] for i in self.tv.selection() if i in self.data]

    def checked_objs(self):
        return [self.data[k] for k in list(self.checked) if k in self.data]

    # -- casillas --
    def set_checked(self, key, on, idx=None):
        if not self.checkable or not self.tv.exists(key):
            return
        (self.checked.add if on else self.checked.discard)(key)
        self.tv.item(key, image=check_image("on" if on else "off", self.k))
        self._paint(key, idx)
        self._schedule_head()

    def toggle(self, key):
        self.set_checked(key, key not in self.checked)
        self.event_generate("<<CheckChanged>>")

    def check_all(self, on=True):
        for i, k in enumerate(self.tv.get_children()):
            self.set_checked(k, on, i)
        self.event_generate("<<CheckChanged>>")

    def _toggle_all(self):
        n = len(self.tv.get_children())
        self.check_all(not (n and len(self.checked) >= n))

    def _schedule_head(self):
        if self.checkable and self._head_job is None:
            self._head_job = self.after_idle(self._sync_head)

    def _sync_head(self):
        self._head_job = None
        if not self.checkable:
            return
        n, c = len(self.data), len(self.checked)
        state = "off" if not c else "on" if c >= n else "mixed"
        self.tv.heading("#0", image=check_image(state, self.k))

    def _on_click(self, e):
        if self.tv.identify_region(e.x, e.y) not in ("tree", "cell") or self.tv.identify_column(e.x) != "#0":
            return
        row = self.tv.identify_row(e.y)
        if row:
            self.toggle(row)
            return "break"

    def _on_double(self, e, on_open):
        if self.tv.identify_region(e.x, e.y) not in ("cell", "tree"):
            return
        if self.checkable and self.tv.identify_column(e.x) == "#0":
            return self._on_click(e)  # doble clic rápido en la casilla: solo marca/desmarca
        on_open(self.focused())

    def _on_space(self, _e):
        for k in self.tv.selection():
            self.toggle(k)
        return "break"

    # -- ratón --
    def _on_motion(self, e):
        row = self.tv.identify_row(e.y) or None
        self._set_hover(row)
        cur = "hand2" if (self.checkable and row and self.tv.identify_column(e.x) == "#0") else ""
        if cur != self._cursor:
            self._cursor = cur
            self.tv.configure(cursor=cur)

    def _set_hover(self, row):
        if row == self._hover:
            return
        old, self._hover = self._hover, row
        for k in (old, row):
            if k:
                self._paint(k)

    def sort_by(self, col):
        prev = self._sort_state.get(col)
        rev = (not prev) if prev is not None else col in ("size", "files", "pct", "date")
        self._sort_state = {col: rev}
        items = list(self.tv.get_children(""))

        def key(k):
            sk = self.sort_keys.get(k, {})
            if col in sk:
                return sk[col]
            return str(self.tv.set(k, col)).lower()
        items.sort(key=key, reverse=rev)
        for i, k in enumerate(items):
            self.tv.move(k, "", i)
            self.tv.item(k, tags=self._tags(k, i))
        for cid, title in self.titles.items():
            self.tv.heading(cid, text=title + (("  ▼" if rev else "  ▲") if cid == col else ""))

    def enable_drag(self, callback):
        """Arrastrar las filas seleccionadas (al Colector). callback(fase, objetos, evento)."""
        st = {"press": None, "on": False}

        def down(e):
            st["press"], st["on"] = (e.x, e.y), False

        def move(e):
            if not st["press"]:
                return
            if not st["on"]:
                if abs(e.x - st["press"][0]) + abs(e.y - st["press"][1]) < 10:
                    return
                row = self.tv.identify_row(st["press"][1])
                if not row:
                    return
                if row not in self.tv.selection():
                    self.tv.selection_set(row)
                objs = [o for o in self.selected() if o is not None]
                if not objs:
                    return
                st["on"] = True
                callback("start", objs, e)
            else:
                callback("move", None, e)
            return "break"

        def up(e):
            if st["on"]:
                callback("drop", None, e)
            st["press"], st["on"] = None, False

        self.tv.bind("<ButtonPress-1>", down, add="+")
        self.tv.bind("<B1-Motion>", move, add="+")
        self.tv.bind("<ButtonRelease-1>", up, add="+")

    # -- menú contextual --
    def context_menu(self, items):
        """items: lista de mi(...) y SEP. La cabecera del menú muestra la fila (o el número de filas) elegida."""
        self._menu_items = items

        def popup(e):
            row = self.tv.identify_row(e.y)
            if row:
                if row not in self.tv.selection():
                    self.tv.selection_set(row)
                self.tv.focus(row)
                self._open_menu(e.x_root, e.y_root)
        self.tv.bind("<Button-3>", popup, add="+")
        if core.IS_MAC:
            self.tv.bind("<Button-2>", popup, add="+")
            self.tv.bind("<Control-Button-1>", popup, add="+")
        for seq in ("<Shift-F10>", "<App>", "<Menu>"):
            try:
                self.tv.bind(seq, lambda e: self._menu_from_keyboard(), add="+")
            except tk.TclError:
                pass

    def _menu_from_keyboard(self):
        f = self.tv.focus()
        if f and self._menu_items:
            bb = self.tv.bbox(f)
            if bb:
                self._open_menu(self.tv.winfo_rootx() + bb[0] + 60, self.tv.winfo_rooty() + bb[1] + bb[3])
        return "break"

    def _open_menu(self, x, y):
        sel = [k for k in self.tv.selection() if k in self.data]
        sizes = [self.sort_keys.get(k, {}).get("size") for k in sel]
        total = sum(s for s in sizes if isinstance(s, (int, float)))
        if len(sel) > 1:
            title = T("{n} elementos seleccionados", n=len(sel))
            sub = human(total) if total else ""
        else:
            key = sel[0] if sel else self.tv.focus()
            title = str(self.tv.set(key, self.ids[0])).strip() if key else ""
            sub = str(self.tv.set(key, "size")) if key and "size" in self.ids else ""
            sub = "" if sub.strip() in ("—", "-") else sub
        if len(title) > 42:
            title = title[:40] + "…"
        PopupMenu(self, self._menu_items, x, y, title=title, subtitle=sub)


# ---------------------------------------------------------------------------
# Diálogos oscuros (sustituyen a los cuadros blancos de Windows)
# ---------------------------------------------------------------------------
class Dialog(ctk.CTkToplevel):
    def __init__(self, master, title, width=520, height=260):
        super().__init__(master, fg_color=C["bg"])
        self.title(title)
        self.result = None
        self._dw = width
        self.transient(master)
        master.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + (master.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        self.body = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=RADIUS, border_width=1,
                                 border_color=C["border"])
        self.body.pack(fill="both", expand=True, padx=12, pady=12)
        self.after(30, lambda: set_dark_titlebar(self))
        self.after(60, self._grab)
        self.bind("<Escape>", lambda e: self._close(None))

    def _grab(self):
        try:
            self.lift()
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def header(self, kind, title, text=""):
        color = {"info": C["accent"], "ok": C["ok"], "warn": C["warn"], "error": C["bad"],
                 "ask": C["accent"], "danger": C["bad"]}[kind]
        glyph = {"info": "info", "ok": "check", "warn": "warn", "error": "warn", "ask": "info",
                 "danger": "trash"}[kind]
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(24, 6))
        ctk.CTkLabel(top, text=icon(glyph), width=42, height=42, corner_radius=12, font=IF(18),
                     fg_color=C["surface2"], text_color=color).pack(side="left", anchor="n")
        tf = ctk.CTkFrame(top, fg_color="transparent")
        tf.pack(side="left", fill="x", expand=True, padx=16)
        ctk.CTkLabel(tf, text=title, font=F(17, "bold"), text_color=C["text"], anchor="w",
                     justify="left", wraplength=self._dw - 150).pack(anchor="w")
        if text:
            ctk.CTkLabel(tf, text=text, font=F(13), text_color=C["muted"], anchor="w", justify="left",
                         wraplength=self._dw - 150).pack(anchor="w", pady=(4, 0))

    def buttons(self, specs):
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(side="bottom", fill="x", padx=24, pady=(8, 22))
        for text, kind, value in reversed(specs):
            btn(bar, text, lambda v=value: self._close(v), kind, width=120).pack(side="right", padx=(8, 0))
        self.bind("<Return>", lambda e: self._close(specs[-1][2]))

    def _close(self, value):
        self.result = value
        self.destroy()

    @classmethod
    def show(cls, master, kind, title, text, buttons):
        lines = text.count("\n") + len(text) // 55
        d = cls(master, title, height=min(190 + lines * 21, 560))
        d.resizable(False, False)
        d.header(kind, title, text)
        d.buttons(buttons)
        master.wait_window(d)
        return d.result


class ConfirmDelete(Dialog):
    def __init__(self, master, title, items, note="", default_permanent=False):
        super().__init__(master, title, width=840, height=620)
        self.minsize(660, 480)
        total = sum(s for _, s in items)
        self.header("danger", T("Vas a borrar {n} elementos · {size}", n=len(items), size=human(total)), note)
        box = ctk.CTkTextbox(self.body, font=ctk.CTkFont(family=MONO_FONT, size=12), fg_color=C["bg"],
                             text_color=C["muted"], border_width=1, border_color=C["border"], corner_radius=8)
        for p, s in items[:2000]:
            box.insert("end", f"{human(s):>10}   {p}\n")
        if len(items) > 2000:
            box.insert("end", T("… y {n} más", n=len(items) - 2000) + "\n")
        box.configure(state="disabled")
        self.mode = tk.StringVar(value="perm" if default_permanent else "recycle")
        self.buttons([(T("Cancelar"), "secondary", None), (T("Borrar"), "danger_solid", "ok")])
        opts = ctk.CTkFrame(self.body, fg_color="transparent")
        opts.pack(side="bottom", fill="x", padx=24)
        for val, t1, t2 in (("recycle", T("Enviar a la Papelera"), T("Recuperable. El espacio se libera al vaciarla.")),
                            ("perm", T("Eliminar definitivamente"),
                             T("Libera el espacio al momento. No se puede deshacer."))):
            row = ctk.CTkFrame(opts, fg_color=C["surface2"], corner_radius=8)
            row.pack(fill="x", pady=3)
            ctk.CTkRadioButton(row, text=t1, variable=self.mode, value=val, font=F(13, "bold"), width=230,
                               fg_color=C["accent"], hover_color=C["accent_h"], border_color=C["faint"],
                               text_color=C["text"]).pack(side="left", padx=14, pady=11)
            ctk.CTkLabel(row, text=t2, font=F(12), text_color=C["muted"]).pack(side="left")
        box.pack(fill="both", expand=True, padx=24, pady=12)

    def _close(self, value):
        self.result = None if value is None else (self.mode.get() == "perm")
        self.destroy()

    @classmethod
    def ask(cls, master, *a, **kw):
        d = cls(master, *a, **kw)
        master.wait_window(d)
        return d.result


# ---------------------------------------------------------------------------
# Dibujo suavizado (Pillow) y colores
# ---------------------------------------------------------------------------
try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:  # noqa: BLE001
    Image = ImageDraw = ImageTk = None


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _mix(c1: str, c2: str, t: float) -> str:
    a, b = _rgb(c1), _rgb(c2)
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))


def hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, max(0, min(1, l)), max(0, min(1, s)))
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _scale_of(widget) -> float:
    try:
        return ctk.ScalingTracker.get_widget_scaling(widget)
    except Exception:  # noqa: BLE001
        return 1.0


def _arc_pts(cx, cy, r, a0, a1, step=1.2):
    """Puntos de un arco (grados, 0 = arriba, sentido horario)."""
    n = max(2, int(abs(a1 - a0) / step) + 1)
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n - 90)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


# ---------------------------------------------------------------------------
# Anillo de uso del disco (degradado, suavizado)
# ---------------------------------------------------------------------------
class Ring(tk.Canvas):
    SS = 3

    def __init__(self, master, size=180, thickness=16, bg=None):
        self.k = _scale_of(master)
        s = int(size * self.k)
        self.bgc = bg or C["surface"]
        super().__init__(master, width=s, height=s, bg=self.bgc, highlightthickness=0, bd=0)
        self.s, self.t = s, int(thickness * self.k)
        self.f = size / 180
        self._photo = None

    def draw(self, pct, big, small):
        self.delete("all")
        s, t = self.s, self.t
        pct = max(0.0, min(pct, 1.0))
        c1, c2 = (C["accent"], C["accent2"]) if pct < 0.75 else (C["warn"], "#ff8a3d") if pct < 0.9 else \
            (C["bad"], "#ff3d7f")
        if Image is not None:
            ss = self.SS
            img = Image.new("RGB", (s * ss, s * ss), self.bgc)
            d = ImageDraw.Draw(img)
            p = (t / 2 + 2) * ss
            box = (p, p, s * ss - p, s * ss - p)
            d.ellipse(box, outline=C["track"], width=t * ss)
            if pct > 0:
                steps = max(2, int(120 * pct))
                ext = 360 * pct
                for i in range(steps):
                    a0 = -90 + ext * i / steps
                    a1 = -90 + ext * (i + 1) / steps + 0.6
                    d.arc(box, a0, min(a1, -90 + ext), fill=_mix(c1, c2, i / steps), width=t * ss)
                # extremos redondeados
                r = (s * ss - 2 * p) / 2 - t * ss / 2  # PIL dibuja el trazo hacia dentro
                cx = cy = s * ss / 2
                for ang, col in ((-90, c1), (-90 + ext, c2)):
                    x = cx + r * math.cos(math.radians(ang))
                    y = cy + r * math.sin(math.radians(ang))
                    d.ellipse((x - t * ss / 2, y - t * ss / 2, x + t * ss / 2, y + t * ss / 2), fill=col)
            img = img.resize((s, s), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.create_image(0, 0, image=self._photo, anchor="nw")
        else:
            p = t / 2 + 2
            self.create_oval(p, p, s - p, s - p, outline=C["track"], width=t)
            if pct > 0:
                self.create_arc(p, p, s - p, s - p, start=90, extent=-359.9 * pct, style="arc", outline=c1, width=t)
        f = self.f
        if f < 0.7:
            self.create_text(s / 2, s / 2, text=big, fill=C["text"], font=(UI_FONT, max(10, round(21 * f)), "bold"))
            return
        self.create_text(s / 2, s / 2 - 9 * self.k * f, text=big, fill=C["text"], font=(UI_FONT, round(24 * f), "bold"))
        self.create_text(s / 2, s / 2 + 19 * self.k * f, text=small, fill=C["muted"], font=(UI_FONT, 10))


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
PAGES = [("summary", T("Discos"), "home"), ("analyzer", T("Mapa del disco"), "map"),
         ("kinds", T("Tipos de archivo"), "list"), ("clean", T("Limpieza"), "clean"),
         ("big", T("Archivos grandes"), "file"), ("dups", T("Duplicados"), "copy"),
         ("models", T("Modelos IA"), "ai"), ("apps", T("Aplicaciones"), "apps")]
# ---------------------------------------------------------------------------
# Mapa de anillos interactivo (sunburst)
# ---------------------------------------------------------------------------
PALETTE = ["#4f8bff", "#38d0c4", "#5ee08a", "#ffd23f", "#ff9f43", "#ff6b8b", "#c56cf0", "#7f7bff",
           "#3fc1ff", "#a3e635", "#ff7eb6", "#ffb86b"]
SMALL_COLOR = "#2a3558"
HIDDEN_COLOR = "#3a4466"


def seg_color(mid_deg: float, depth: int, is_file: bool = False) -> str:
    """Arcoíris por posición, como un mapa de calor suave: verde → amarillo → naranja → rosa → violeta → azul."""
    hue = 150 - (mid_deg / 360) * 290
    sat = 0.66 - 0.07 * (depth - 1)
    lig = 0.58 + 0.045 * (depth - 1)
    if is_file:
        sat -= 0.2
        lig += 0.03
    return hsl(hue, sat, min(lig, 0.8))


# ---------------------------------------------------------------------------
# Animación del análisis: mapa que crece en vivo, cometas, iconos en órbita y partículas
# ---------------------------------------------------------------------------
SCAN_ORBS = [  # (glifo Segoe Fluent/MDL2, color 1, color 2): tipos de archivo que orbitan mientras se analiza
    ("", "#4f8bff", "#7f7bff"),   # carpeta
    ("", "#38d0c4", "#3fc1ff"),   # imágenes
    ("", "#ff6b8b", "#c56cf0"),   # vídeo
    ("", "#ff9f43", "#ff6b8b"),   # música
    ("", "#5ee08a", "#38d0c4"),   # código
    ("", "#ffd23f", "#ff9f43"),   # comprimidos
    ("", "#7f7bff", "#c56cf0"),   # documentos
    ("", "#c56cf0", "#ff7eb6"),   # modelos de IA
]


def _ease_out_back(t):
    t = min(max(t, 0.0), 1.0) - 1
    return 1 + 2.2 * t ** 3 + 1.2 * t ** 2


def _ease_in_cubic(t):
    return t * t * t


def _spaced(text: str) -> str:
    """Letras separadas por espacios (no en chino ni japonés)."""
    return text if i18n.LANG in ("zh", "ja") else " ".join(text)


class _RingWorker(threading.Thread):
    """Hilo que lleva el árbol vivo de carpetas y dibuja los anillos con suavizado (Pillow, sin tkinter).
    Así el dibujo caro nunca bloquea los fotogramas de la interfaz."""

    FPS = 15

    def __init__(self, root):
        super().__init__(daemon=True)
        self.root = root
        self.q: queue.SimpleQueue = queue.SimpleQueue()
        self.tree = [0, 0.0, {}]      # [bytes, fracción mostrada de su padre, {nombre: nodo}] (3 niveles)
        self.active: list[str] = []
        self.b = 0
        self.geo = None
        self.bg = None                # recorte del fondo (RGB) donde van los anillos: la imagen sale opaca
        self.t0 = time.perf_counter()
        self.lock = threading.Lock()
        self.out = None
        self.paused = False
        self.dirty = True
        self.stop_ev = threading.Event()

    def stop(self):
        self.stop_ev.set()
        self.q.put(("stop", None))

    def run(self):
        period = 1 / self.FPS
        next_t = time.perf_counter()
        while not self.stop_ev.is_set():
            try:
                while True:
                    kind, arg = self.q.get(timeout=max(0.0, next_t - time.perf_counter()))
                    if kind == "p":
                        self._progress(*arg)
                    elif kind == "geo":
                        self.geo, self.bg = arg
                        self.dirty = True
                    elif kind == "stop":
                        return
            except queue.Empty:
                pass
            next_t = time.perf_counter() + period
            intro = min(1.0, (time.perf_counter() - self.t0) / 0.8)
            if self.paused or self.geo is None or not (self.dirty or intro < 1):
                continue
            try:
                img = self._render(intro)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                img = None
            if img is not None:
                with self.lock:
                    self.out = img

    def take(self):
        with self.lock:
            img, self.out = self.out, None
        return img

    def _progress(self, b, p):
        delta = max(0, b - self.b)
        self.b = b
        try:
            rel = os.path.relpath(p, self.root) if p else "."
        except ValueError:
            rel = "."
        parts = [x for x in rel.replace("\\", "/").split("/") if x and x != "."]
        if parts and parts[0] == "..":
            parts = []
        node = self.tree
        node[0] += delta
        for part in parts[:3]:
            node = node[2].setdefault(part, [0, 0.0, {}])
            node[0] += delta
        self.active = parts[:3]
        self.dirty = True

    def _base(self):
        """Nivel que se muestra: si una carpeta lo ocupa casi todo (el análisis va por ella), se baja un
        nivel para que los anillos enseñen variedad; se vuelve arriba en cuanto aparecen hermanas."""
        path, node = [], self.tree
        while len(path) < 2:
            kids = [(k, v) for k, v in node[2].items() if v[0] > 0]
            if len(kids) == 1 and kids[0][1][0] >= node[0] * 0.97 and kids[0][1][2]:
                path.append(kids[0][0])
                node = kids[0][1]
            else:
                break
        return path, node

    def _render(self, intro):
        rad, k, side = self.geo
        ss = 2
        im = Image.new("RGBA", (side * ss, side * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        X = Y = side * ss / 2
        path, base = self._base()
        settled = True
        if base[0] > 0:
            act = self.active[len(path):] if self.active[:len(path)] == path else []
            grow = 0.75 + 0.25 * _ease_out_back(intro)

            def ring(node, depth, a0, span, active):
                nonlocal settled
                a = a0
                for name, v in list(node[2].items()):
                    if v[0] <= 0:
                        continue
                    frac = v[0] / node[0] if node[0] else 0  # la fracción mostrada se acerca a la real
                    v[1] += (frac - v[1]) * 0.22
                    settled &= abs(frac - v[1]) < 0.002
                    sp = span * v[1]
                    if sp >= (0.3 if depth == 1 else 0.6):
                        on = bool(active) and name == active[0]
                        r1 = (rad[depth - 1] + 1.4) * grow
                        r2 = (rad[depth] - 1.4) * grow + ((4 + depth) * k if on else 0)
                        col = seg_color(a + sp / 2, depth)
                        pts = _arc_pts(X, Y, r2 * ss, a, a + sp) + \
                            list(reversed(_arc_pts(X, Y, r1 * ss, a, a + sp)))
                        d.polygon(pts, fill=_mix(col, "#ffffff", 0.18) if on else col, outline=C["surface"],
                                  width=ss)
                        if depth == 1 and v[2]:
                            ring(v, 2, a, sp, active[1:] if on else [])
                    a += sp
            ring(base, 1, 0.0, 360.0 * min(1.0, intro * 1.15), act)
        self.dirty = not settled
        layer = im.resize((side, side), Image.LANCZOS)
        out = self.bg.copy().convert("RGBA")
        out.alpha_composite(layer)
        return out.convert("RGB")


class ScanFX:
    """Animación del visor mientras se analiza.
    - Los anillos (caros) los dibuja otro hilo y llegan ya listos: la interfaz nunca se bloquea.
    - Lo que se mueve (cometas, órbitas, partículas, contadores) son imágenes ya preparadas que solo
      cambian de sitio, a 60 fps con ritmo fijo y temporizador de 1 ms (Windows); si el equipo no llega,
      baja sola a 45 o 30 fps.
    - Se pausa si el Mapa no se ve (otra página o ventana minimizada)."""

    FPS_LEVELS = (60, 45, 30)

    def __init__(self, canvas):
        self.cv = canvas
        self.job = None
        self.items: dict = {}
        self.size = None
        self.worker = None
        self._timer_1ms = False

    # -- ciclo de vida --
    def start(self, root_path):
        self.stop()
        now = time.perf_counter()
        self.root = root_path
        self.n = self.b = 0
        self.shown_n = self.shown_b = 0.0
        self.last_text = 0.0
        self.path = ""
        self.t0 = now
        self.rate_hist = [(now, 0)]
        self.particles: list[dict] = []
        self.spawn_acc = 0.0
        self.last_t = None
        self.size = None
        self.fps_i = 0
        self.slow = 0
        self.next_frame = now
        self.visible = True
        self.resize_since = self.resize_size = None
        self.worker = _RingWorker(root_path)
        self.worker.start()
        self._timer(True)
        self._tick()

    def stop(self):
        if self.job is not None:
            self.cv.after_cancel(self.job)
            self.job = None
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self._timer(False)
        self.items = {}
        self.size = None

    def _timer(self, on):
        """Windows reparte el tiempo en saltos de 15,6 ms: mientras se anima se pide precisión de 1 ms.
        (Bajar el intervalo de cambio de hilo de Python se probó: frena el análisis a la mitad.)"""
        if on == self._timer_1ms:
            return
        self._timer_1ms = on
        if not core.IS_WIN:
            return
        try:
            import ctypes
            (ctypes.windll.winmm.timeBeginPeriod if on else ctypes.windll.winmm.timeEndPeriod)(1)
        except Exception:  # noqa: BLE001
            pass

    @property
    def running(self):
        return self.job is not None

    def progress(self, n, b, p):
        self.n, self.b, self.path = n, b, p or self.path
        if self.worker is not None:
            self.worker.q.put(("p", (b, p)))
        now = time.perf_counter()
        self.rate_hist.append((now, n))
        while len(self.rate_hist) > 2 and now - self.rate_hist[0][0] > 2.5:
            self.rate_hist.pop(0)

    # -- recursos que dependen del tamaño --
    def _build(self):
        cv = self.cv
        cv.delete("all")
        self.items = {}
        w, h = max(cv.winfo_width(), 50), max(cv.winfo_height(), 50)
        cx, cy, rad = cv.geometry_()
        self.k = k = _scale_of(cv)
        self.geo = (w, h, cx, cy, rad)
        self.size = (w, h)
        self.r_comet1 = (rad[2] + rad[3]) / 2
        self.r_orbit = (rad[3] + rad[4]) / 2
        self.r_comet2 = rad[5] - 5 * k
        self.r_spawn = rad[5] + 8 * k
        bg = self._background(w, h, cx, cy, rad)
        self.bg_photo = ImageTk.PhotoImage(bg)
        I = self.items
        I["bg"] = cv.create_image(0, 0, anchor="nw", image=self.bg_photo)
        # zona de los anillos: el hilo de dibujo recibe su trozo de fondo y devuelve una imagen opaca
        side = int(2 * (rad[2] + 8 * k)) + 4
        x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
        I["rings"] = cv.create_image(x0, y0, anchor="nw")
        if self.worker is not None:
            self.worker.q.put(("geo", ((rad, k, side), bg.crop((x0, y0, x0 + side, y0 + side)))))
        # partículas (debajo del núcleo: el centro las «absorbe»)
        self.pal = ["#4f8bff", "#38d0c4", "#5ee08a", "#ffd23f", "#ff9f43", "#ff6b8b", "#c56cf0", "#7f7bff"]
        self.p_sprites = {c: [self._glow(c, max(1.5, (5.2 - 0.5 * i) * k), 0.9 - 0.09 * i) for i in range(8)]
                          for c in self.pal}
        self.p_free = [cv.create_image(-99, -99) for _ in range(36)]
        self.particles = []
        # cometas
        self.c1_sprites = [self._glow(_mix("#dbe7ff", _mix(C["accent"], C["accent2"], i / 24), min(1, i / 4)),
                                      max(1.5, (8.5 - 0.3 * i) * k), (1 - i / 26) ** 1.6) for i in range(24)]
        self.c2_sprites = [self._glow(_mix("#ffe1f0", _mix(C["accent2"], "#ff6b8b", i / 16), min(1, i / 3)),
                                      max(1.4, (8 - 0.4 * i) * k), (1 - i / 18) ** 1.6) for i in range(16)]
        I["c1"] = [cv.create_image(-99, -99, image=im) for im in reversed(self.c1_sprites)][::-1]
        I["c2"] = [cv.create_image(-99, -99, image=im) for im in reversed(self.c2_sprites)][::-1]
        # iconos en órbita
        self.orb_imgs = [self._orb(g, c1, c2, round(40 * k)) for g, c1, c2 in SCAN_ORBS]
        I["orbs"] = [cv.create_image(cx, cy, image=im) for im in self.orb_imgs]
        # núcleo: onda pulsante, disco y textos
        r0 = rad[0] - 3
        self.ripples = [self._ripple(r0, i / 32) for i in range(32)]
        I["ripple"] = cv.create_image(cx, cy)
        self.core_photo = self._core(r0)
        I["core"] = cv.create_image(cx, cy, image=self.core_photo)
        I["t_label"] = cv.create_text(cx, cy - 26 * k, text=_spaced(T("ANALIZANDO")), fill=C["accent"],
                                      font=(UI_FONT, 8, "bold"))
        I["t_big"] = cv.create_text(cx, cy, text="0 B", fill=C["text"], font=(UI_FONT, 19, "bold"))
        I["t_files"] = cv.create_text(cx, cy + 24 * k, text=T("{n} archivos", n=0), fill=C["muted"], font=(UI_FONT, 10))
        self.cache: dict = {}
        if getattr(self, "rings_photo", None) is not None and self.worker is not None:
            self.worker.dirty = True

    def _background(self, w, h, cx, cy, rad):
        ss = 2
        im = Image.new("RGB", (w * ss, h * ss), C["surface"])
        # halo suave detrás del centro
        glow = Image.new("L", (w * ss // 4, h * ss // 4), 0)
        gr = rad[2] * ss / 4
        ImageDraw.Draw(glow).ellipse((cx * ss / 4 - gr, cy * ss / 4 - gr, cx * ss / 4 + gr, cy * ss / 4 + gr), fill=70)
        from PIL import ImageFilter
        glow = glow.filter(ImageFilter.GaussianBlur(gr * 0.45)).resize((w * ss, h * ss), Image.BILINEAR)
        im = Image.composite(Image.new("RGB", im.size, _mix(C["surface"], C["accent"], 0.55)), im, glow)
        d = ImageDraw.Draw(im)
        X, Y = cx * ss, cy * ss
        # huecos de los anillos que se irán llenando
        ghost = _mix(C["surface"], C["track"], 0.7)
        for depth in (1, 2):
            r1, r2 = (rad[depth - 1] + 1.4) * ss, (rad[depth] - 1.4) * ss
            d.ellipse((X - r2, Y - r2, X + r2, Y + r2), fill=ghost)
            d.ellipse((X - r1, Y - r1, X + r1, Y + r1), fill=C["surface"])
        # órbitas punteadas
        for r, step, col in ((self.r_comet1, 3.0, C["border"]), (self.r_orbit, 2.0, _mix(C["border"], C["surface"], .3)),
                             (self.r_comet2, 3.0, C["border"])):
            for i in range(int(360 / step)):
                a = math.radians(i * step)
                px, py = X + r * ss * math.sin(a), Y - r * ss * math.cos(a)
                s = 1.1 * ss
                d.ellipse((px - s, py - s, px + s, py + s), fill=col)
        # dial exterior con marcas, como un instrumento
        R = rad[5] + 3
        for i in range(120):
            a = math.radians(i * 3)
            long_ = i % 10 == 0
            r1 = (R + (2 if long_ else 4)) * ss
            r2 = (R + 10) * ss
            col = _mix(C["faint"], C["surface"], 0.2 if long_ else 0.55)
            d.line((X + r1 * math.sin(a), Y - r1 * math.cos(a), X + r2 * math.sin(a), Y - r2 * math.cos(a)),
                   fill=col, width=ss * (2 if long_ else 1))
        return im.resize((w, h), Image.LANCZOS)

    def _glow(self, color, radius, alpha):
        """Punto luminoso con halo (sprite con transparencia)."""
        r = max(1.0, radius)
        n = int(r * 3) * 2 + 3
        S = 4
        im = Image.new("RGBA", (n * S, n * S), _rgb(color) + (0,))
        d = ImageDraw.Draw(im)
        c = n * S / 2
        for i in range(10, 0, -1):  # halo: círculos concéntricos cada vez más transparentes
            rr = r * S * (1 + 1.6 * i / 10)
            d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=_rgb(color) + (int(255 * alpha * 0.05),))
        rr = r * S
        d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=_rgb(_mix(color, "#ffffff", 0.35)) + (int(255 * alpha),))
        return ImageTk.PhotoImage(im.resize((n, n), Image.LANCZOS))

    def _orb(self, glyph, c1, c2, px):
        """Insignia redonda con degradado, brillo y el icono en blanco."""
        S = px * 4
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        a, b = _rgb(c1), _rgb(c2)
        d = ImageDraw.Draw(im)
        d.ellipse((0, 0, S - 1, S - 1), fill=a + (40,))
        m = S * 0.12
        n = int(S - 2 * m)
        grad = Image.new("RGBA", (n, n))
        gd = ImageDraw.Draw(grad)
        for i in range(2 * n):
            t = i / (2 * n - 1)
            gd.line((i, 0, 0, i), fill=tuple(int(x + (y - x) * t) for x, y in zip(a, b)) + (255,), width=2)
        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, n - 1, n - 1), fill=255)
        im.paste(grad, (int(m), int(m)), mask)
        d = ImageDraw.Draw(im)
        d.ellipse((m, m, S - 1 - m, S - 1 - m), outline=(255, 255, 255, 70), width=max(2, S // 60))
        font_file = _icon_font_file()
        if font_file:
            try:
                from PIL import ImageFont
                d.text((S / 2, S / 2), glyph, font=ImageFont.truetype(font_file, int(S * 0.34)),
                       fill=(255, 255, 255, 255), anchor="mm")
            except Exception:  # noqa: BLE001
                pass
        return ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))

    def _ripple(self, r0, t):
        k = self.k
        rr = r0 * (1.0 + 0.55 * t)
        n = int(r0 * 1.6) * 2 + 4
        S = 2
        im = Image.new("RGBA", (n * S, n * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = n * S / 2
        a = int(150 * (1 - t) ** 1.8)
        col = _rgb(_mix(C["accent"], C["accent2"], t)) + (a,)
        lw = max(2, int(2.2 * k * S * (1 - 0.5 * t)))
        d.ellipse((c - rr * S, c - rr * S, c + rr * S, c + rr * S), outline=col, width=lw)
        return ImageTk.PhotoImage(im.resize((n, n), Image.LANCZOS))

    def _core(self, r0):
        S = 4
        n = int(r0) * 2 + 4
        im = Image.new("RGBA", (n * S, n * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = n * S / 2
        R = r0 * S
        top, bot = _rgb(_mix(C["surface2"], "#ffffff", 0.05)), _rgb(_mix(C["surface"], "#000000", 0.15))
        steps = 24
        for i in range(steps):  # disco con un degradado vertical suave
            t = i / (steps - 1)
            rr = R * (1 - i / steps * 0.04)
            col = tuple(int(x + (y - x) * t) for x, y in zip(top, bot))
            d.ellipse((c - rr, c - rr + i * 0.0, c + rr, c + rr), fill=col + (255,))
        ring = Image.new("RGBA", im.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        a1, a2 = _rgb(C["accent"]), _rgb(C["accent2"])
        lw = max(3, int(2.4 * self.k * S))
        for i in range(36):  # borde con degradado azul → violeta alrededor
            t = abs((i / 36) * 2 - 1)
            col = tuple(int(x + (y - x) * t) for x, y in zip(a1, a2)) + (255,)
            rd.arc((c - R, c - R, c + R, c + R), i * 10 - 90, i * 10 - 80 + 1, fill=col, width=lw)
        im.alpha_composite(ring)
        return ImageTk.PhotoImage(im.resize((n, n), Image.LANCZOS))

    # -- fotograma --
    def _set(self, item, key, **kw):
        """itemconfigure solo si cambia: menos repintados de Tk."""
        val = tuple(kw.values())
        if self.cache.get(key) != val:
            self.cache[key] = val
            self.cv.itemconfigure(item, **kw)

    def _tick(self):
        cv = self.cv
        self.job = None
        try:
            if not cv.winfo_exists():
                return
            shown = cv.is_shown() if cv.is_shown else True
            if not shown:  # en pausa: los datos siguen llegando, pero no se dibuja nada
                if self.visible:
                    self.visible = False
                    if self.worker is not None:
                        self.worker.paused = True
                    self._timer(False)
                self.job = cv.after(200, self._tick)
                return
            if not self.visible:
                self.visible = True
                self.last_t = None
                self.next_frame = time.perf_counter()
                if self.worker is not None:
                    self.worker.paused = False
                    self.worker.dirty = True
                self._timer(True)
            now = time.perf_counter()
            cur = (max(cv.winfo_width(), 50), max(cv.winfo_height(), 50))
            if self.size is None:
                self._build()
            elif abs(cur[0] - self.size[0]) > 6 or abs(cur[1] - self.size[1]) > 6:
                # reconstruir la escena cuesta: se espera a que el tamaño se quede quieto, y se ignoran
                # los vaivenes de uno o dos píxeles de la maquetación
                if self.resize_since is None or self.resize_size != cur:
                    self.resize_since, self.resize_size = now, cur
                elif now - self.resize_since > 0.15:
                    self.resize_since = None
                    self._build()
            else:
                self.resize_since = None
            if self.last_t is not None:  # si no se llega a tiempo de forma sostenida, se bajan los fps
                late = now - self.last_t > 1.6 / self.FPS_LEVELS[self.fps_i]
                self.slow = max(0, self.slow + (1 if late else -1))
                if self.slow > 45 and self.fps_i < len(self.FPS_LEVELS) - 1:
                    self.fps_i += 1
                    self.slow = 0
            dt = min(0.1, now - self.last_t) if self.last_t is not None else 0.0
            self.last_t = now
            t = now - self.t0
            fade = min(1.0, t / 0.5)
            w, h, cx, cy, rad = self.geo
            I = self.items
            # anillos: los entrega ya dibujados el otro hilo
            img = self.worker.take() if self.worker is not None else None
            if img is not None:
                self.rings_photo = ImageTk.PhotoImage(img)
                cv.itemconfigure(I["rings"], image=self.rings_photo)
            # cometas
            for items, r, speed, gap in ((I["c1"], self.r_comet1, 150, 3.2), (I["c2"], self.r_comet2, -70, 3.6)):
                head = (t * speed) % 360
                step = math.copysign(gap, speed)
                for i, it in enumerate(items):
                    ang = math.radians(head - step * i)
                    cv.coords(it, cx + r * math.sin(ang), cy - r * math.cos(ang))
            # iconos en órbita: salen del centro al empezar y flotan
            n = len(I["orbs"])
            for i, it in enumerate(I["orbs"]):
                ang = math.radians(i * 360 / n + t * 14)
                bob = math.sin(t * 2.2 + i * 1.3) * 5 * self.k
                r = rad[0] + (self.r_orbit - rad[0]) * _ease_out_back(max(0.0, (t - i * 0.05) / 0.9)) + bob
                cv.coords(it, cx + r * math.sin(ang), cy - r * math.cos(ang))
            # partículas: cada una conserva su elemento del lienzo; más cuanto más rápido va el análisis
            rate = self.rate()
            self.spawn_acc = min(3.0, self.spawn_acc + dt * (4 + min(14.0, rate / 800)) * fade)
            while self.spawn_acc >= 1 and self.p_free:
                self.spawn_acc -= 1
                self.particles.append(dict(a=random.uniform(0, 360), t0=now, dur=random.uniform(0.9, 1.7),
                                           col=random.choice(self.pal), swirl=random.uniform(25, 70),
                                           item=self.p_free.pop(), step=-1))
            alive = []
            r_end = rad[0] * 0.85
            for p in self.particles:
                pt = (now - p["t0"]) / p["dur"]
                if pt >= 1:
                    cv.coords(p["item"], -99, -99)
                    self.p_free.append(p["item"])
                    continue
                alive.append(p)
                e = _ease_in_cubic(pt)
                r = self.r_spawn + (r_end - self.r_spawn) * e
                ang = math.radians(p["a"] + p["swirl"] * e)
                cv.coords(p["item"], cx + r * math.sin(ang), cy - r * math.cos(ang))
                st = min(7, int(pt * 8))
                if st != p["step"]:
                    p["step"] = st
                    cv.itemconfigure(p["item"], image=self.p_sprites[p["col"]][st])
            self.particles = alive
            # onda del núcleo, etiqueta que late y contadores que «ruedan» (suavizado independiente de los fps)
            self._set(I["ripple"], "ripple", image=self.ripples[int(t * 20) % len(self.ripples)])
            pulse = round((0.5 + 0.5 * math.sin(t * 3)) * 12) / 12
            self._set(I["t_label"], "label", fill=_mix(C["accent"], "#bcd0ff", pulse * 0.6))
            ease = 1 - math.exp(-dt * 9)
            self.shown_n += (self.n - self.shown_n) * ease
            self.shown_b += (self.b - self.shown_b) * ease
            self._set(I["t_big"], "big", text=human(int(self.shown_b)))
            self._set(I["t_files"], "files", text=T("{n} archivos", n=num(int(round(self.shown_n)))))
            if cv.on_scan_text and now - self.last_text >= 0.25:
                self.last_text = now
                m, s_ = divmod(int(t), 60)
                speed = T("{n} archivos/s", n=num(int(rate))) if rate >= 1 else T("preparando…")
                cv.on_scan_text(f"{m}:{s_:02d}   ·   {speed}   ·   {self._short_path()}")
        except tk.TclError:
            return
        # ritmo fijo: el siguiente fotograma se fija en tiempo absoluto (sin deriva acumulada)
        period = 1.0 / self.FPS_LEVELS[self.fps_i]
        self.next_frame += period
        now = time.perf_counter()
        if self.next_frame < now - period:
            self.next_frame = now + period
        self.job = cv.after(max(1, int((self.next_frame - now) * 1000)), self._tick)

    def rate(self):
        if len(self.rate_hist) < 2:
            return 0.0
        (t0, n0), (t1, n1) = self.rate_hist[0], self.rate_hist[-1]
        return (n1 - n0) / (t1 - t0) if t1 > t0 else 0.0

    def _short_path(self):
        p = self.path or self.root
        try:
            rel = os.path.relpath(p, self.root)
        except ValueError:
            rel = p
        parts = [x for x in rel.replace("\\", "/").split("/") if x and x != "."]
        if not parts:
            return os.path.basename(self.root.rstrip("\\/")) or self.root
        if len(parts) > 3:
            parts = parts[:1] + ["…"] + parts[-2:]
        txt = "  ›  ".join(parts)
        return txt if len(txt) <= 90 else "…" + txt[-88:]


class Sunburst(tk.Canvas):
    """Mapa circular por niveles: cada anillo es un nivel de carpetas, el ángulo es su tamaño."""

    DEPTH = 5
    MIN_DEG = 0.9
    SS = 2
    WEIGHTS = (1.0, 0.9, 0.8, 0.7, 0.62)

    def __init__(self, master, on_hover=None, on_navigate=None, on_context=None, on_file=None, on_drag=None,
                 bg=None):
        self.bgc = bg or C["surface"]
        super().__init__(master, bg=self.bgc, highlightthickness=0, bd=0)
        self.root_node: core.Node | None = None
        self.base_root: core.Node | None = None
        self.hidden = 0
        self.history: list[core.Node] = []
        self.segs: list[list] = []        # [depth, a0, a1, node|None, color, label, size, kind]
        self.hover_seg = None
        self.on_hover, self.on_navigate, self.on_context = on_hover, on_navigate, on_context
        self.on_file, self.on_drag = on_file, on_drag
        self._photo = None
        self._job = None
        self._anim = None
        self._spin = None
        self._spin_a = 0
        self.scan_text = ""
        self.fx = ScanFX(self)
        self.on_scan_text = None  # recibe «tiempo · velocidad · ruta» mientras se analiza
        self.is_shown = None      # la animación se pausa si devuelve False (otra página, ventana minimizada)
        self._press = None
        self._dragging = False
        self.bind("<Configure>", lambda e: self._schedule())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<ButtonPress-1>", self._b1_down)
        self.bind("<B1-Motion>", self._b1_move)
        self.bind("<ButtonRelease-1>", self._b1_up)
        for seq in ("<Button-3>",) + (("<Button-2>", "<Control-Button-1>") if core.IS_MAC else ()):
            self.bind(seq, self._right)

    # -- navegación --
    def set_root(self, node, push=True, animate=True):
        if push and self.root_node is not None and node is not self.root_node:
            self.history.append(self.root_node)
        self.root_node = node
        self._layout()
        self.redraw(animate=animate)
        if self.on_navigate:
            self.on_navigate(node)

    def reset(self, node, hidden=0):
        self.stop_scanning()
        self.history.clear()
        self.root_node = None
        self.base_root = node
        self.hidden = hidden
        self.set_root(node, push=False)

    def up(self):
        if self.history:
            self.set_root(self.history.pop(), push=False)

    def go_to(self, node):
        while self.history and self.history[-1] is not node:
            self.history.pop()
        if self.history:
            self.history.pop()
        self.set_root(node, push=False)

    # -- análisis en curso --
    def start_scanning(self, root_path=""):
        self.stop_scanning()
        self.hover_seg = None
        if Image is not None:
            self._spin = "fx"
            self.fx.start(root_path)
        else:  # sin Pillow: indicador sencillo
            self.scan_text = T("Preparando…")
            self._spin_tick()

    def scan_progress(self, n, b, p):
        if self.fx.running:
            self.fx.progress(n, b, p)
        else:
            self.scan_text = T("{n} archivos · {size}", n=num(n), size=human(b))

    def stop_scanning(self):
        if self.fx.running:
            self.fx.stop()
            self.delete("all")
        elif self._spin not in (None, "fx"):
            self.after_cancel(self._spin)
        self._spin = None

    def _spin_tick(self):
        self._spin_a = (self._spin_a + 9) % 360
        self.delete("all")
        cx, cy, rad = self.geometry_()
        R = rad[-1] * 0.62
        self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=C["track"], width=max(6, R * 0.07))
        for i in range(14):
            a0 = self._spin_a - i * 7
            col = _mix(C["accent"], C["track"], i / 14)
            self.create_arc(cx - R, cy - R, cx + R, cy + R, start=-a0 + 90, extent=-8, style="arc", outline=col,
                            width=max(6, R * 0.07))
        self.create_text(cx, cy - 12, text=T("Analizando…"), fill=C["text"], font=(UI_FONT, 15, "bold"))
        self.create_text(cx, cy + 14, text=self.scan_text, fill=C["muted"], font=(UI_FONT, 10))
        self._spin = self.after(40, self._spin_tick)

    # -- geometría --
    def geometry_(self):
        w, h = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        R = min(w, h) / 2 - 12
        r0 = R * 0.27
        tot = sum(self.WEIGHTS[:self.DEPTH])
        rad = [r0]
        for wgt in self.WEIGHTS[:self.DEPTH]:
            rad.append(rad[-1] + (R - r0) * wgt / tot)
        return w / 2, h / 2, rad

    def _layout(self):
        self.segs = []
        node = self.root_node
        if node is None:
            return
        hidden = self.hidden if node is self.base_root else 0
        total = (node.size + hidden) or 1

        def walk(n, depth, a0, a1):
            if depth > self.DEPTH or n.size <= 0:
                return
            span = a1 - a0
            cur = a0
            small = 0
            items = sorted(n.children + n.top_files, key=lambda c: c.size, reverse=True)
            for ch in items:
                ext = span * ch.size / n.size
                if ext < self.MIN_DEG:
                    small += ch.size
                    continue
                col = seg_color(cur + ext / 2, depth, ch.is_file)
                self.segs.append([depth, cur, cur + ext, ch, col, ch.name, ch.size, "file" if ch.is_file else "dir"])
                if not ch.is_file:
                    walk(ch, depth + 1, cur, cur + ext)
                cur += ext
            rest = core.loose_bytes(n) + small
            ext = span * rest / n.size
            if ext >= 0.35:
                self.segs.append([depth, cur, cur + ext, None, _mix(SMALL_COLOR, self.bgc, 0.1 * depth),
                                  T("Archivos pequeños"), rest, "small"])

        walk(node, 1, 0.0, 360.0 * node.size / total)
        if hidden:
            self.segs.append([1, 360.0 * node.size / total, 360.0, None, HIDDEN_COLOR, T("Espacio oculto"), hidden,
                              "hidden"])

    # -- dibujo --
    def _schedule(self):
        if self._spin is not None:
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, lambda: self.redraw(animate=False))

    def redraw(self, animate=False):
        if self._spin is not None:
            return
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
        if animate and Image is not None and self.segs:
            self._animate(0)
        else:
            self._paint(1.0)

    def _animate(self, i, n=11):
        t = i / n
        e = 1 - (1 - t) ** 3  # ease-out
        self._paint(e, fast=i < n)
        if i < n:
            self._anim = self.after(16, lambda: self._animate(i + 1, n))
        else:
            self._anim = None

    def _paint(self, t=1.0, fast=False):
        self.delete("all")
        node = self.root_node
        cx, cy, rad = self.geometry_()
        if node is None:
            self.create_text(cx, cy - 10, text=T("Elige un disco o una carpeta"), fill=C["text"],
                             font=(UI_FONT, 15, "bold"))
            self.create_text(cx, cy + 16, text=T("y pulsa «Analizar» para ver su mapa"), fill=C["muted"],
                             font=(UI_FONT, 11))
            return
        w, h = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        grow = 0.86 + 0.14 * t
        if Image is not None:
            ss = 1 if fast else self.SS
            img = Image.new("RGB", (w * ss, h * ss), self.bgc)
            d = ImageDraw.Draw(img)
            for seg in self.segs:
                depth, a0, a1, _n, col = seg[:5]
                a0, a1 = a0 * t, a1 * t
                if a1 - a0 < 0.05:
                    continue
                self._poly(d, seg, cx, cy, rad, ss, col, a0, a1, grow)
            r0 = rad[0] * grow - 3
            d.ellipse((ss * (cx - r0), ss * (cy - r0), ss * (cx + r0), ss * (cy + r0)), fill=C["surface2"],
                      outline=C["border"], width=ss)
            if ss > 1:
                self._hires = img
                img = img.resize((w, h), Image.LANCZOS)
            self._base = img if not fast else None
            self._img_item = self.create_image(0, 0, anchor="nw")
            self._show_img(img)
            if not fast and self.hover_seg not in (None, "center"):
                self._paint_hover()
        else:
            for seg in self.segs:
                depth, a0, a1, _n, col = seg[:5]
                r1, r2 = rad[depth - 1] + 1.4, rad[depth] - 1.4
                pts = [c for p in _arc_pts(cx, cy, r2, a0, a1) + list(reversed(_arc_pts(cx, cy, r1, a0, a1)))
                       for c in p]
                seg.append(self.create_polygon(pts, fill=col, outline=self.bgc))
            r0 = rad[0] - 3
            self.create_oval(cx - r0, cy - r0, cx + r0, cy + r0, fill=C["surface2"], outline=C["border"])
        self.c_title = self.create_text(cx, cy - 18, fill=C["muted"], font=(UI_FONT, 11, "bold"))
        self.c_size = self.create_text(cx, cy + 4, fill=C["text"], font=(UI_FONT, 19, "bold"))
        self.c_hint = self.create_text(cx, cy + 28, fill=C["faint"], font=(UI_FONT, 9))
        self._refresh_center()

    def _poly(self, d, seg, cx, cy, rad, ss, col, a0, a1, grow=1.0, ox=0, oy=0):
        depth = seg[0]
        r1 = (rad[depth - 1] + 1.4) * grow
        r2 = (rad[depth] - 1.4) * grow
        pts = _arc_pts(cx * ss - ox, cy * ss - oy, r2 * ss, a0, a1) + \
            list(reversed(_arc_pts(cx * ss - ox, cy * ss - oy, r1 * ss, a0, a1)))
        d.polygon(pts, fill=col, outline=self.bgc, width=max(1, ss))
        return pts

    def _show_img(self, img):
        self._photo = ImageTk.PhotoImage(img)
        self.itemconfigure(self._img_item, image=self._photo)

    def _paint_hover(self):
        """Resalta el segmento bajo el ratón redibujando solo su recuadro (rápido)."""
        base = getattr(self, "_base", None)
        if base is None or self.SS < 1:
            return
        seg = self.hover_seg
        if seg in (None, "center"):
            self._show_img(base)
            return
        ss = self.SS
        cx, cy, rad = self.geometry_()
        pts = _arc_pts(cx * ss, cy * ss, rad[seg[0]] * ss, seg[1], seg[2]) + \
            _arc_pts(cx * ss, cy * ss, rad[seg[0] - 1] * ss, seg[1], seg[2])
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0 = max(0, int(min(xs) / ss) - 2) * ss
        y0 = max(0, int(min(ys) / ss) - 2) * ss
        x1 = min(base.width, int(max(xs) / ss) + 3) * ss
        y1 = min(base.height, int(max(ys) / ss) + 3) * ss
        crop = self._hires.crop((x0, y0, x1, y1))
        dd = ImageDraw.Draw(crop)
        self._poly(dd, seg, cx, cy, rad, ss, _mix(seg[4], "#ffffff", 0.38), seg[1], seg[2], ox=x0, oy=y0)
        small = crop.resize(((x1 - x0) // ss, (y1 - y0) // ss), Image.LANCZOS)
        img = base.copy()
        img.paste(small, (x0 // ss, y0 // ss))
        self._show_img(img)

    def _short(self, name, r0):
        maxc = max(8, int(r0 / 5.5))
        return name if len(name) <= maxc else name[:maxc - 1] + "…"

    def _refresh_center(self):
        if not hasattr(self, "c_title") or self.root_node is None:
            return
        seg = self.hover_seg
        n = self.root_node
        if seg and seg != "center":
            size = seg[6]
            base = (n.size + (self.hidden if n is self.base_root else 0)) or 1
            sub = f"{size / base * 100:.1f} %"
            if seg[7] == "dir":
                sub += " · " + T("{n} archivos", n=num(seg[3].files))
            elif seg[7] == "hidden":
                sub = T("sistema, sin permisos, instantáneas…")
            self._center_text(seg[5], human(size), sub)
        else:
            self._center_text(n.name, human(n.size), T("↑ subir") if self.history else
                              T("{n} archivos", n=num(n.files)))

    def _center_text(self, t, s, h):
        _cx, _cy, rad = self.geometry_()
        try:
            self.itemconfigure(self.c_title, text=self._short(t, rad[0]))
            self.itemconfigure(self.c_size, text=s)
            self.itemconfigure(self.c_hint, text=h)
        except tk.TclError:
            pass

    # -- interacción --
    def _hit(self, x, y):
        cx, cy, rad = self.geometry_()
        dx, dy = x - cx, y - cy
        r = math.hypot(dx, dy)
        if r < rad[0]:
            return "center"
        depth = next((i for i in range(1, len(rad)) if r < rad[i]), None)
        if depth is None:
            return None
        ang = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        for seg in self.segs:
            if seg[0] == depth and seg[1] <= ang < seg[2]:
                return seg
        return None

    def _set_hover(self, seg):
        if self._spin is not None or self._anim is not None:
            return
        prev = self.hover_seg
        self.hover_seg = seg
        if Image is not None:
            if (prev not in (None, "center")) or (seg not in (None, "center")):
                self._paint_hover()
            self._refresh_center()
        else:
            if prev not in (None, "center") and len(prev) > 8:
                self.itemconfigure(prev[8], fill=prev[4])
            if seg not in (None, "center") and len(seg) > 8:
                self.itemconfigure(seg[8], fill=_mix(seg[4], "#ffffff", 0.35))
            self._refresh_center()
        node = seg[3] if seg not in (None, "center") else None
        if seg == "center":
            self.configure(cursor="hand2" if self.history else "arrow")
        else:
            self.configure(cursor="hand2" if node is not None else "arrow")
        if self.on_hover:
            self.on_hover(node)

    def _motion(self, e):
        if self._spin is not None:
            return
        if self.root_node is None or self._dragging:
            return
        seg = self._hit(e.x, e.y)
        if seg is not self.hover_seg:
            self._set_hover(seg)

    def _b1_down(self, e):
        if self._spin is not None:
            return
        self._press = (e.x, e.y)
        self._dragging = False

    def _b1_move(self, e):
        if self._spin is not None:
            return
        if not self._press or self.root_node is None:
            return
        if not self._dragging:
            if abs(e.x - self._press[0]) + abs(e.y - self._press[1]) < 8:
                return
            seg = self._hit(*self._press)
            if seg in (None, "center") or seg[3] is None or not self.on_drag:
                return
            self._dragging = True
            self._drag_node = seg[3]
            self.on_drag("start", [seg[3]], e)
        else:
            self.on_drag("move", None, e)

    def _b1_up(self, e):
        if self._spin is not None:
            return
        if self._dragging:
            self._dragging = False
            self._press = None
            self.on_drag("drop", None, e)
            return
        self._press = None
        if self.root_node is None or self._spin is not None:
            return
        seg = self._hit(e.x, e.y)
        if seg == "center":
            self.up()
        elif seg and seg[3] is not None:
            if seg[3].is_file:
                if self.on_file:
                    self.on_file(seg[3])
            elif seg[3].children or seg[3].top_files:
                self.hover_seg = None
                self.set_root(seg[3])

    def _right(self, e):
        if self._spin is not None:
            return
        seg = self._hit(e.x, e.y)
        if seg and seg != "center" and seg[3] is not None and self.on_context:
            self.on_context(seg[3], e)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=C["bg"])
        self.title(APP_NAME)
        self.geometry("1340x860")
        self.minsize(1100, 700)
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.scan_result: core.ScanResult | None = None
        self.categories = core.build_categories()
        self.apps: list[core.InstalledApp] = []
        self.collector: dict[str, int] = {}
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav: dict[str, tuple] = {}
        self._style()
        self._build()
        self.show("summary")
        self.after(100, self._poll)
        self.after(200, self.refresh_summary)
        self.after(50, lambda: set_dark_titlebar(self))
        self.after(3000, self._check_updates)

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        k = self._get_window_scaling() if hasattr(self, "_get_window_scaling") else 1.0
        st.layout("Dark.Treeview", [("Dark.Treeview.treearea", {"sticky": "nswe"})])
        # Columna inicial (casilla o punto de color) sin el triángulo de árbol, con la imagen centrada.
        st.layout("Dark.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"sticky": ""})]})])
        st.configure("Dark.Treeview", background=C["surface"], fieldbackground=C["surface"], foreground=C["text"],
                     rowheight=int(40 * k), borderwidth=0, relief="flat", font=(UI_FONT, 11), indent=0)
        st.configure("Dark.Treeview.Item", padding=0)
        st.layout("Dark.Treeview.Heading", [("Treeheading.cell", {"sticky": "nswe"}),
                                            ("Treeheading.border", {"sticky": "nswe", "children": [
                                                ("Treeheading.padding", {"sticky": "nswe", "children": [
                                                    ("Treeheading.image", {"sticky": ""}),
                                                    ("Treeheading.text", {"sticky": "we"})]})]})])
        st.configure("Dark.Treeview.Cell", padding=(int(6 * k), 0))
        st.configure("Dark.Treeview.Heading", background=C["surface"], foreground=C["muted"], relief="flat",
                     borderwidth=0, font=(UI_FONT, 9, "bold"), padding=(int(9 * k), int(9 * k)))
        st.map("Dark.Treeview", background=[("selected", C["sel"])], foreground=[("selected", "#ffffff")])
        st.map("Dark.Treeview.Heading", background=[("active", C["surface2"])], foreground=[("active", C["text"])])

    # ---------- estructura ----------
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, fg_color=C["side"], corner_radius=0, width=244)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.pack_propagate(False)
        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(fill="x", padx=18, pady=(26, 28))
        Ring(logo, size=34, thickness=6, bg=C["side"]).draw(0.72, "", "")
        logo.winfo_children()[-1].pack(side="left")
        lt = ctk.CTkFrame(logo, fg_color="transparent")
        lt.pack(side="left", padx=10)
        ctk.CTkLabel(lt, text="Desktop Free Space", font=F(14, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(lt, text=T("Gestor de espacio · v{version}", version=VERSION), font=F(11), text_color=C["faint"]
                     ).pack(anchor="w")
        ctk.CTkLabel(side, text=T("MENÚ"), font=F(10, "bold"), text_color=C["faint"]).pack(anchor="w", padx=26,
                                                                                          pady=(0, 6))
        for key, label, ico in PAGES:
            b = ctk.CTkButton(side, text=f"          {label}", anchor="w", height=42, corner_radius=8,
                              font=F(13, "bold"), fg_color="transparent", hover_color=C["hover"],
                              text_color=C["muted"], command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            ic = ctk.CTkLabel(b, text=icon(ico), font=IF(15), fg_color="transparent", text_color=C["muted"],
                              width=22, height=22)
            ic.place(x=16, rely=0.5, anchor="w")
            ic.bind("<Button-1>", lambda e, k=key: self.show(k))
            # el icono sigue el color de fondo del botón (al pasar el ratón y al seleccionarlo): sin cuadrados
            for w in (b, ic):
                w.bind("<Enter>", lambda e, k=key: self._nav_paint(k, True), add="+")
                w.bind("<Leave>", lambda e, k=key: self._nav_paint(k, False), add="+")
            ic.bind("<Enter>", lambda e, b=b: b._on_enter(), add="+")  # el botón no pierde su resaltado
            ic.bind("<Leave>", lambda e, b=b: b._on_leave(), add="+")
            self.nav[key] = (b, ic)
        # selector de idioma: lo último de la barra lateral
        self.lang_btn = ctk.CTkButton(side, text="", command=self._lang_menu, height=34, corner_radius=8, anchor="w",
                                      font=F(12, "bold"), fg_color="transparent", hover_color=C["hover"],
                                      text_color=C["muted"], border_width=1, border_color=C["border"])
        self.lang_btn.pack(side="bottom", fill="x", padx=14, pady=(0, 16))
        lb = self.lang_btn
        g1 = ctk.CTkLabel(lb, text=icon("globe"), font=IF(14), text_color=C["muted"], width=18, height=18)
        g1.place(x=12, rely=0.5, anchor="w")
        g2 = ctk.CTkLabel(lb, text="\uE70E" if ICON_FONT else "⌃", font=IF(10), text_color=C["faint"], width=14,
                          height=18)
        g2.place(relx=1.0, x=-12, rely=0.5, anchor="e")
        for w in (g1, g2):
            w.bind("<Button-1>", lambda e: self._lang_menu())
            w.bind("<Enter>", lambda e: lb._on_enter(), add="+")
            w.bind("<Leave>", lambda e: lb._on_leave(), add="+")
        for w in (lb, g1, g2):  # los iconos siguen el fondo del botón
            w.bind("<Enter>", lambda e: [x.configure(fg_color=C["hover"]) for x in (g1, g2)], add="+")
            w.bind("<Leave>", lambda e: [x.configure(fg_color=C["side"]) for x in (g1, g2)], add="+")
        for x in (g1, g2):
            x.configure(fg_color=C["side"])
        self._lang_text()
        g1.lift()
        g2.lift()  # por encima del texto del botón
        # tarjeta de permisos / sistema
        adm = ctk.CTkFrame(side, fg_color=C["surface"], corner_radius=12, border_width=1, border_color=C["border"])
        adm.pack(side="bottom", fill="x", padx=14, pady=(8, 10))
        is_admin = core.is_admin()
        hdr = ctk.CTkFrame(adm, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(hdr, text=icon("shield"), font=IF(14), text_color=C["ok"] if is_admin else C["warn"]
                     ).pack(side="left")
        ctk.CTkLabel(hdr, text=f"{core.OS_NAME} · " + (T("Administrador") if is_admin else T("Modo estándar")),
                     font=F(12, "bold"), text_color=C["text"], wraplength=150, justify="left"
                     ).pack(side="left", padx=8)
        if core.IS_WIN:
            tip = (T("Puedes limpiar también las carpetas de Windows.") if is_admin else
                   T("Para limpiar Windows Temp y Windows Update hacen falta permisos."))
        else:
            tip = (T("Limpia lo de tu usuario. Lo del sistema necesita sudo.") if not is_admin else
                   T("Ejecutando como root."))
        tip_l = ctk.CTkLabel(adm, text=tip, font=F(11), text_color=C["muted"], wraplength=186, justify="left")
        tip_l.pack(anchor="w", padx=14, pady=(4, 12))
        restart = None
        if core.IS_WIN and not is_admin:
            restart = btn(adm, T("Reiniciar como admin"), self._relaunch_admin, "secondary")
            restart.pack(fill="x", padx=12, pady=(0, 6))
        upd = ctk.CTkButton(adm, text=T("Buscar actualizaciones"), command=lambda: self._check_updates(manual=True),
                            height=28, corner_radius=8, font=F(12, "bold"), **BTN_STYLES["ghost"])
        upd.pack(fill="x", padx=8, pady=(0, 10))
        # en ventanas bajas se ocultan primero el texto y luego «Buscar actualizaciones»
        # Contenido de la tarjeta en orden, y qué se oculta en cada nivel de compactación
        self._adm = adm
        self._adm_items = [(tip_l, dict(anchor="w", padx=14, pady=(4, 12)))]
        if restart is not None:
            self._adm_items.append((restart, dict(fill="x", padx=12, pady=(0, 6))))
        self._adm_items.append((upd, dict(fill="x", padx=8, pady=(0, 10))))
        self._side_hide = [tip_l, upd] + ([restart] if restart is not None else []) + [adm]
        self._side_level = 0
        self._side_job = None
        side.bind("<Configure>", lambda e: self._schedule_fit_side(), add="+")

        # Colector
        col = ctk.CTkFrame(side, fg_color=C["surface"], corner_radius=14, border_width=2, border_color=C["accent_soft"])
        self.col_frame = col
        col.pack(side="bottom", fill="x", padx=14, pady=(8, 0))
        ch = ctk.CTkFrame(col, fg_color="transparent")
        ch.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(ch, text=T("Colector"), font=F(13, "bold"), text_color=C["text"]).pack(side="left")
        self.col_count = ctk.CTkLabel(ch, text="0", font=F(11, "bold"), text_color="#ffffff", width=26, height=20,
                                      corner_radius=8, fg_color=C["surface2"])
        self.col_count.pack(side="right")
        self.col_label = ctk.CTkLabel(col, text="", font=F(11), text_color=C["muted"], wraplength=186,
                                      justify="left", anchor="w")
        self.col_label.pack(fill="x", padx=14, pady=(2, 8))
        cb = ctk.CTkFrame(col, fg_color="transparent")
        cb.pack(fill="x", padx=10, pady=(0, 12))
        self.col_del = btn(cb, T("Revisar y borrar"), self._collector_review, "danger_solid", width=120)
        self.col_del.pack(side="left", fill="x", expand=True)
        self.col_view = btn(cb, T("Vaciar"),self._collector_clear, "ghost", width=60)
        self.col_view.pack(side="left", padx=(6, 0))

        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_update_banner(main)
        for key, _l, _i in PAGES:
            f = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
            f.grid(row=1, column=0, sticky="nsew", padx=30, pady=(26, 0))
            self.pages[key] = f
        self._build_summary(self.pages["summary"])
        self._build_clean(self.pages["clean"])
        self._build_analyzer(self.pages["analyzer"])
        self._build_bigfiles(self.pages["big"])
        self._build_models(self.pages["models"])
        self._build_apps(self.pages["apps"])
        self._build_kinds(self.pages["kinds"])
        self._build_dups(self.pages["dups"])

        foot = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0, height=48)
        foot.grid(row=2, column=0, sticky="ew", padx=30, pady=(8, 12))
        foot.grid_columnconfigure(1, weight=1)
        self.dot = ctk.CTkLabel(foot, text="●", font=F(11), text_color=C["ok"], width=14)
        self.dot.grid(row=0, column=0, padx=(2, 8))
        self.status = ctk.CTkLabel(foot, text=T("Listo"), anchor="w", font=F(12), text_color=C["muted"])
        self.status.grid(row=0, column=1, sticky="ew")
        self.progress = ctk.CTkProgressBar(foot, mode="determinate", width=200, height=4, corner_radius=2,
                                           fg_color=C["surface2"], progress_color=C["accent"])
        self.progress.set(0)
        self.progress.grid(row=0, column=2, padx=12)
        self.cancel_btn = btn(foot, T("Cancelar"), self.cancel.set, "ghost", width=90)
        self.cancel_btn.grid(row=0, column=3)
        self.cancel_btn.grid_remove()
        self.progress.grid_remove()
        self._update_collector()

    def _schedule_fit_side(self):
        if self._side_job is None:
            self._side_job = self.after(30, self._fit_side)

    @staticmethod
    def _pady(w) -> int:
        import re
        vals = [int(float(v)) for v in re.findall(r"\d+(?:\.\d+)?", str(w.pack_info().get("pady", 0)))] or [0]
        return sum(vals) if len(vals) > 1 else 2 * vals[0]

    def _set_side_level(self, level):
        self._side_level = level
        hidden = set(self._side_hide[:level])
        for w, _o in self._adm_items:
            w.pack_forget()
        for w, o in self._adm_items:
            if w not in hidden:
                w.pack(**o)
        if self._adm in hidden:
            self._adm.pack_forget()
        elif not self._adm.winfo_manager():
            self._adm.pack(side="bottom", fill="x", padx=14, pady=(8, 10), before=self.col_frame)

    def _fit_side(self):
        """Mantiene el Colector entero en ventanas bajas compactando la tarjeta de sistema."""
        self._side_job = None
        side = self.col_frame.master
        need = sum(w.winfo_reqheight() + self._pady(w) for w in side.pack_slaves())
        avail = side.winfo_height()
        level = self._side_level
        if need > avail and level < len(self._side_hide):
            self._set_side_level(level + 1)
            self._schedule_fit_side()
        elif level:
            back = self._side_hide[level - 1]
            opts = next((o for w, o in self._adm_items if w is back), {"pady": (8, 18)})
            pad = opts.get("pady", 0)
            pad = sum(pad) if isinstance(pad, tuple) else 2 * pad
            if need + back.winfo_reqheight() + round(pad * _scale_of(side)) <= avail:
                self._set_side_level(level - 1)
                self._schedule_fit_side()

    def _nav_paint(self, key, hover):
        b, ic = self.nav[key]
        on = key == getattr(self, "_page", None)
        bg = C["hover"] if hover else (C["accent_soft"] if on else C["side"])
        ic.configure(fg_color=bg, bg_color=bg)

    def show(self, key):
        self._page = key
        self.pages[key].tkraise()
        for k, (b, ic) in self.nav.items():
            on = k == key
            b.configure(fg_color=C["accent_soft"] if on else "transparent", text_color=C["text"] if on else C["muted"])
            ic.configure(text_color=C["accent"] if on else C["muted"])
            self._nav_paint(k, False)

    def page_header(self, page, title, subtitle):
        h = ctk.CTkFrame(page, fg_color="transparent")
        h.pack(fill="x", pady=(0, 18))
        tf = ctk.CTkFrame(h, fg_color="transparent")
        tf.pack(side="left")
        ctk.CTkLabel(tf, text=title, font=F(26, "bold"), text_color=C["text"]).pack(anchor="w")
        sub = ctk.CTkLabel(tf, text=subtitle, font=F(13), text_color=C["muted"], justify="left")
        sub.pack(anchor="w", pady=(2, 0))
        actions = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        actions.pack(side="right", anchor="s")
        self._wrap_to_fit(h, sub, [actions], 24)
        return actions

    def _wrap_to_fit(self, row, label, others, gap):
        """Ajusta el ancho de línea de `label` al hueco que dejan los demás elementos de la fila (ventanas
        estrechas): el texto pasa a dos líneas en vez de pisar o aplastar los botones."""
        def fit(_e=None):
            k = _scale_of(row)
            used = sum(w.winfo_reqwidth() for w in (others() if callable(others) else others))
            avail = max(140 * k, row.winfo_width() - used - gap * k)
            label.configure(wraplength=int(avail / k))
        row.bind("<Configure>", fit, add="+")

    def hint(self, page, text):
        ctk.CTkLabel(page, text=text, font=F(12), text_color=C["faint"], anchor="w", justify="left",
                     wraplength=1000).pack(fill="x", pady=(10, 0))

    def section(self, page, title, sub="", pady=(0, 8)):
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=pady)
        ctk.CTkLabel(row, text=title, font=F(15, "bold"), text_color=C["text"]).pack(side="left")
        info = ctk.CTkLabel(row, text=sub, font=F(12), text_color=C["muted"], justify="left")
        info.pack(side="left", padx=12)
        self._wrap_to_fit(row, info, lambda: [w for w in row.winfo_children() if w is not info], 40)
        return row, info

    # ---------- diálogos ----------
    def alert(self, text, title=None, kind="info"):
        Dialog.show(self, kind, T("Aviso") if title is None else title, text, [(T("Entendido"), "primary", True)])

    def confirm(self, title, text, ok=None, danger=False):
        ok = T("Aceptar") if ok is None else ok
        return Dialog.show(self, "danger" if danger else "ask", title, text,
                           [(T("Cancelar"), "secondary", False),(ok, "danger_solid" if danger else "primary", True)]
                           ) is True

    # ---------- tareas en segundo plano ----------
    def run_task(self, label, fn, done=None, on_error=None):
        if self.busy:
            self.alert(T("Espera a que termine la tarea actual o cancélala."), T("Tarea en curso"))
            return
        self.busy = True
        self.cancel.clear()
        self.cancel_btn.grid()
        self.progress.grid()
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.dot.configure(text_color=C["accent"])
        self.set_status(label)

        def report(text):
            self.q.put(("status", text))

        def worker():
            try:
                self.q.put(("done", (done, fn(report), None, on_error)))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.q.put(("done", (done, None, e, on_error)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        last_status = None
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    last_status = payload
                elif kind == "scan":
                    self.sun.scan_progress(*payload)
                elif kind == "update":
                    self._on_update_result(*payload)
                elif kind == "done":
                    done, res, err, on_error = payload
                    last_status = None
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress.set(0)
                    self.progress.grid_remove()
                    self.cancel_btn.grid_remove()
                    if err:
                        if on_error:
                            on_error()
                        self.dot.configure(text_color=C["bad"])
                        self.set_status(T("Error: {err}", err=err))
                        self.alert(T("Ha ocurrido un error:\n{err}", err=err), T("Error"), "error")
                    else:
                        self.dot.configure(text_color=C["warn"] if self.cancel.is_set() else C["ok"])
                        self.set_status(T("Cancelado") if self.cancel.is_set() else T("Listo"))
                        if done:
                            done(res)
        except queue.Empty:
            pass
        if last_status:
            self.set_status(last_status)
        self.after(100, self._poll)

    def set_status(self, text):
        text = str(text)
        self.status.configure(text=text if len(text) < 150 else text[:60] + " … " + text[-80:])

    def after_delete(self, res: core.DeleteResult, permanent: bool = True):
        if permanent:
            core.add_freed(res.freed)
        msg = T("{n} archivos borrados.", n=num(res.deleted))
        if not permanent and res.freed:
            msg += "\n" + T("Están en la Papelera: el espacio se libera al vaciarla.")
        kind = "ok"
        if res.failed:
            kind = "warn"
            msg += "\n" + T("{n} elementos no se pudieron borrar (estaban en uso o sin permisos).", n=res.failed)
            if res.errors:
                msg += "\n\n" + "\n".join(e if len(e) < 90 else "…" + e[-88:] for e in res.errors[:4])
        Dialog.show(self, kind, T("Has liberado {size}", size=human(res.freed)), msg,
                    [(T("Perfecto"), "primary", True)])
        self.refresh_summary()

    def _launch(self, target):
        try:
            core.launch(target)
        except Exception as e:  # noqa: BLE001
            self.alert(str(e), T("No se pudo abrir"), "error")

    def _lang_text(self):
        name = dict(i18n.LANGS)[i18n.LANG]
        txt = T("Automático") + " · " + name if i18n.choice() == "auto" else name
        self.lang_btn.configure(text="        " + txt)

    def _lang_menu(self):
        b = self.lang_btn
        cur = i18n.choice()
        sysname = dict(i18n.LANGS)[i18n.system_lang()]
        items = [mi(T("Automático"), lambda: self._set_lang("auto"), "check" if cur == "auto" else "", sysname), SEP]
        items += [mi(name, lambda c=code: self._set_lang(c), "check" if code == cur else "")
                  for code, name in i18n.LANGS]
        PopupMenu(self, items, b.winfo_rootx(), b.winfo_rooty(), title=T("Idioma"),
                  min_width=b.winfo_width(), above=True)

    def _set_lang(self, choice):
        if choice == i18n.choice():
            return
        code = i18n.system_lang() if choice == "auto" else choice
        if code == i18n.LANG:  # mismo idioma que ya se ve: basta con guardarlo
            i18n.set_lang(choice)
            self._lang_text()
            return
        # el aviso sale ya en el idioma elegido
        tt = i18n.texts(code)
        if self.busy:
            self.alert(tt("Espera a que termine la tarea actual o cancélala."), tt("Tarea en curso"))
            return
        if not Dialog.show(self, "ask", tt("Cambiar idioma"),
                           tt("La app se reiniciará para mostrarse en {lang}.").format(lang=dict(i18n.LANGS)[code]),
                           [(tt("Cancelar"), "secondary", False), (tt("Reiniciar"), "primary", True)]) is True:
            return
        i18n.set_lang(choice)
        if core.relaunch_self():
            self.destroy()
            os._exit(0)

    def _relaunch_admin(self):
        if core.relaunch_as_admin():
            self.destroy()

    # =====================================================================
    # Resumen
    # =====================================================================
    def _build_summary(self, page):
        actions = self.page_header(page, T("Discos"), T("Estado de tus discos y por dónde empezar a liberar espacio"))
        btn(actions, T("Actualizar"),self.refresh_summary, "secondary", width=110).pack(side="right")
        self.sum_body = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=C["scroll"],
                                               scrollbar_button_hover_color=C["scroll_h"])
        self.sum_body.pack(fill="both", expand=True)
        self.sum_body.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")

    def _tile(self, parent, col, title, value, sub, action=None, kind="secondary", row=2, dot=None):
        t = card(parent)
        t.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 7, 0 if col == 2 else 7), pady=(0, 14))
        hd = ctk.CTkFrame(t, fg_color="transparent")
        hd.pack(anchor="w", padx=22, pady=(20, 4))
        ctk.CTkLabel(hd, text="●", font=F(11), text_color=dot or C["accent"], width=12).pack(side="left")
        ctk.CTkLabel(hd, text=title.upper(), font=F(11, "bold"), text_color=C["faint"]).pack(side="left", padx=6)
        ctk.CTkLabel(t, text=value, font=F(28, "bold"), text_color=C["text"]).pack(anchor="w", padx=22)
        sl = ctk.CTkLabel(t, text=sub, font=F(12), text_color=C["muted"], wraplength=300, justify="left")
        sl.pack(anchor="w", padx=22, pady=(2, 14 if action else 22))
        t.bind("<Configure>", lambda e: sl.configure(wraplength=max(120, int(e.width / _scale_of(t)) - 48)), add="+")
        if action:
            btn(t, action[0], action[1], kind, width=130).pack(anchor="w", padx=22, pady=(0, 20))

    def _bar(self, parent, pct, height=10):
        b = ctk.CTkProgressBar(parent, height=height, corner_radius=height // 2, fg_color=C["track"],
                               progress_color=level_color(pct) if pct >= 0.75 else C["accent"])
        b.set(max(0.0, min(pct, 1.0)))
        return b

    def refresh_summary(self):
        body = self.sum_body
        for w in body.winfo_children():
            w.destroy()
        self._drive_rows = []
        drives = core.list_drives()
        if core.IS_WIN:
            sysdrive = next((d for d in drives if d.path.upper().startswith(core.SYSDRIVE[:2].upper())), None)
        else:
            sysdrive = next((d for d in drives if d.path == "/"), None)
        sysdrive = sysdrive or (drives[0] if drives else None)
        if sysdrive:
            hero = card(body)
            hero.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 14))
            hero.grid_columnconfigure(1, weight=1)
            ring = Ring(hero, size=196, thickness=18)
            ring.grid(row=0, column=0, rowspan=4, padx=(30, 36), pady=28)
            ring.draw(sysdrive.pct, f"{sysdrive.pct * 100:.0f}%", T("en uso"))
            ctk.CTkLabel(hero, text=T("DISCO DEL SISTEMA") + f"  ·  {sysdrive.path}", font=F(11, "bold"),
                         text_color=C["faint"]).grid(row=0, column=1, sticky="sw", pady=(36, 0))
            big = ctk.CTkLabel(hero, text=T("{size} libres", size=human(sysdrive.free)), font=F(40, "bold"),
                               text_color=C["text"])
            big.grid(row=1, column=1, sticky="w")

            def fit_big(_e=None, big=big, hero=hero):
                """La cifra grande nunca se corta: baja el tamaño de letra si la ventana es estrecha."""
                try:
                    k = _scale_of(hero)
                    avail = hero.grid_bbox(1, 1)[2] - 4 * k
                    if avail <= 0:
                        return
                    for size in (40, 36, 32, 28, 24):
                        f = tkfont.Font(family=UI_FONT, size=-round(size * k), weight="bold")
                        if f.measure(big.cget("text")) <= avail:
                            break
                    if getattr(big, "_size", 40) != size:
                        big._size = size
                        big.configure(font=F(size, "bold"))
                except tk.TclError:
                    pass
            big._fit = fit_big
            hero.bind("<Configure>", lambda e: hero.after_idle(fit_big), add="+")
            bar = self._bar(hero, sysdrive.pct, 10)
            bar.grid(row=2, column=1, sticky="ew", pady=(10, 8))
            info = ctk.CTkLabel(hero, text="", font=F(12), text_color=C["muted"])
            info.grid(row=3, column=1, sticky="nw", pady=(0, 30))
            acts = ctk.CTkFrame(hero, fg_color="transparent")
            acts.grid(row=0, column=2, rowspan=4, padx=30)
            for text, cmd, kind, cap in (
                    (T("Limpiar temporales y cachés"), lambda: (self.show("clean"), self.scan_categories()), "primary",
                     T("Calcula lo que se puede borrar sin riesgo")),
                    (T("Ver qué ocupa espacio"), lambda p=sysdrive.path: self.start_scan(p), "secondary",
                     T("Mapa de todas las carpetas y archivos del disco"))):
                btn(acts, text, cmd, kind, width=250).pack(anchor="w", pady=(8, 0))
                ctk.CTkLabel(acts, text=cap, font=F(11), text_color=C["muted"], height=18, anchor="w"
                             ).pack(anchor="w", padx=4, pady=(3, 6))
            self._drive_rows.append((sysdrive.path, ring, big, bar, info, True))

        freed, since = core.freed_stats()
        y, m, d = (since.split("-") + ["", "", ""])[:3]
        try:
            since_txt = date_text(int(y), int(m), int(d))
        except (ValueError, IndexError):
            since_txt = since
        fb = ctk.CTkFrame(body, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        fb.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(fb, text="✦", font=F(18, "bold"), text_color=C["accent"], width=24).pack(side="left", padx=(22, 8),
                                                                                             pady=16)
        ctk.CTkLabel(fb, text=T("{size} liberados", size=human(freed)) if freed else T("Aún no has liberado espacio"),
                     font=F(18, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(fb, text=T("con Desktop Free Space desde el {date}", date=since_txt), font=F(13),
                     text_color=C["muted"]).pack(side="left", padx=10)

        size, n = core.recycle_bin_size()
        self._tile(body, 0, T("Papelera de reciclaje") if core.IS_WIN else T("Papelera"), human(size),
                   T("{n} elementos · ocupan espacio hasta vaciarla", n=num(n)),
                   (T("Vaciar"), self._empty_bin) if size else None, "danger", dot=C["bad"])
        scanned = [c for c in self.categories if getattr(c, "_scanned", False)]
        if scanned:
            safe = sum(c.size for c in scanned if c.risk == core.SAFE)
            rev = sum(c.size for c in scanned if c.risk == core.REVIEW)
            self._tile(body, 1, T("Recuperable"), human(safe + rev),
                       T("{safe} seguro · {review} a revisar", safe=human(safe), review=human(rev)),
                       (T("Ir a Limpieza"), lambda: self.show("clean")), dot=C["ok"])
        else:
            self._tile(body, 1, T("Recuperable"), "—", T("Temporales, cachés y modelos de IA sin calcular"),
                       (T("Calcular"), lambda:(self.show("clean"), self.scan_categories())), dot=C["ok"])
        sysfiles = core.system_files_info()
        snaps = core.local_snapshots()
        sub = " · ".join(f"{os.path.basename(p)} {human(s)}" for _l, p, s, _t in sysfiles) or \
            T("Hibernación y memoria virtual")
        if snaps:
            sub += " · " + T("{n} instantáneas locales de Time Machine", n=len(snaps))
        self._tile(body, 2, T("Archivos del sistema"),human(sum(x[2] for x in sysfiles)) if sysfiles else "—", sub,
                   dot=C["accent2"])
        row = 3
        others = [d for d in drives if d is not sysdrive]
        if others:
            ctk.CTkLabel(body, text=T("Otros discos"), font=F(15, "bold"), text_color=C["text"]
                         ).grid(row=row, column=0, sticky="w", pady=(6, 10))
            row += 1
            for d in others:
                dc = card(body)
                dc.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
                dc.grid_columnconfigure(1, weight=1)
                ring = Ring(dc, size=64, thickness=8)
                ring.grid(row=0, column=0, rowspan=2, padx=(18, 18), pady=14)
                ring.draw(d.pct, f"{d.pct * 100:.0f}%", "")
                name = d.path if len(d.path) < 40 else "…" + d.path[-38:]
                top = ctk.CTkFrame(dc, fg_color="transparent")
                top.grid(row=0, column=1, sticky="sew", pady=(16, 6))
                ctk.CTkLabel(top, text=name, font=F(14, "bold"), text_color=C["text"]).pack(side="left")
                info = ctk.CTkLabel(top, text="", font=F(12), text_color=C["muted"])
                info.pack(side="right")
                bar = self._bar(dc, d.pct, 8)
                bar.grid(row=1, column=1, sticky="new", pady=(0, 16))
                btn(dc, T("Analizar"), lambda p=d.path: self.start_scan(p), "secondary", width=100
                    ).grid(row=0, column=2, rowspan=2, padx=18)
                self._drive_rows.append((d.path, ring, None, bar, info, False))
                row += 1
        tools = core.system_tools()
        if tools:
            ctk.CTkLabel(body, text=T("Herramientas de {os}", os=core.OS_NAME), font=F(15, "bold"),
                         text_color=C["text"]).grid(row=row, column=0, sticky="w", pady=(10, 10))
            row += 1
        for i, (t1, t2, target) in enumerate(tools):
            t = card(body)
            t.grid(row=row, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            ctk.CTkLabel(t, text=t1, font=F(13, "bold"), text_color=C["text"]).pack(anchor="w", padx=22, pady=(18, 0))
            ctk.CTkLabel(t, text=t2, font=F(12), text_color=C["muted"]).pack(anchor="w", padx=22)
            btn(t, T("Abrir") + "  ↗", lambda x=target: self._launch(x), "ghost", width=80).pack(anchor="w", padx=12,
                                                                                         pady=(6, 14))
        tips = [tip for _l, _p, _s, tip in sysfiles if "powercfg" in tip or "pmset" in tip]
        if snaps:
            tips.append(T("macOS borra las instantáneas locales solo cuando falta espacio. Para quitarlas ya: {cmd}",
                          cmd="tmutil deletelocalsnapshots /"))
        if tips:
            row += 1
            ctk.CTkLabel(body, text=T("Consejo: {tip}", tip=tips[0]), font=F(12), text_color=C["faint"]
                         ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(14, 0))
        self._live_drives(schedule_only=True)

    def _live_drives(self, schedule_only=False):
        """Actualiza en tiempo real el espacio libre de los discos, sin volver a dibujar la pantalla."""
        if getattr(self, "_live_job", None):
            self.after_cancel(self._live_job)
        if not schedule_only:
            for path, ring, big, bar, info, is_sys in list(getattr(self, "_drive_rows", [])):
                try:
                    u = shutil.disk_usage(path)
                    pct = u.used / u.total if u.total else 0
                    if not ring.winfo_exists():
                        continue
                    if abs(pct - getattr(ring, "_pct", -1)) > 0.0005:
                        ring.draw(pct, f"{pct * 100:.0f}%", T("en uso") if is_sys else "")
                        ring._pct = pct
                    bar.set(pct)
                    bar.configure(progress_color=level_color(pct) if pct >= 0.75 else C["accent"])
                    if big is not None:
                        big.configure(text=T("{size} libres", size=human(u.free)))
                        if hasattr(big, "_fit"):
                            big._fit()
                        info.configure(text=T("Usado {used}  ·  Capacidad {total}", used=human(u.used),
                                              total=human(u.total)))
                    else:
                        info.configure(text=T("{free} libres de {total}", free=human(u.free), total=human(u.total)))
                except (OSError, tk.TclError):
                    pass
        else:
            self.after(10, lambda: self._live_drives())
            return
        self._live_job = self.after(4000, self._live_drives)

    def _empty_bin(self):
        size, n = core.recycle_bin_size()
        if self.confirm(T("¿Vaciar la Papelera?"),
                        T("{size} en {n} elementos. No se podrá recuperar.", size=human(size), n=num(n)),
                        T("Vaciar"), danger=True):
            core.empty_recycle_bin()
            after, _n = core.recycle_bin_size()
            core.add_freed(max(0, size - after))
            self.refresh_summary()

    # =====================================================================
    # Limpieza
    # =====================================================================
    def _build_clean(self, page):
        actions = self.page_header(page, T("Limpieza"),
                                   T("Temporales, cachés y modelos que se pueden borrar sin romper nada"))
        btn(actions, T("Limpiar seleccionadas"), self.clean_selected, "danger_solid", width=190).pack(side="right")
        btn(actions, T("Calcular espacio"), self.scan_categories, "primary", width=150).pack(side="right", padx=8)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        self.cat_filter = ctk.CTkSegmentedButton(
            bar, values=[T("Todas"), T("Sistema"), T("Navegadores"), T("Desarrollo"), T("IA / Modelos")],
            command=lambda _v: self._fill_categories(), font=F(12, "bold"), height=34, corner_radius=8,
            fg_color=C["surface"], selected_color=C["accent"], selected_hover_color=C["accent_h"],
            unselected_color=C["surface"], unselected_hover_color=C["hover"], text_color=C["text"])
        self.cat_filter.set(T("Todas"))
        self.cat_filter.pack(side="left")
        btn(bar, T("Marcar las seguras"), self._check_safe, "ghost", width=150).pack(side="left", padx=(12, 0))
        btn(bar, T("Desmarcar"), lambda: self.cat_table.check_all(False), "ghost", width=100).pack(side="left")
        self.cat_total = ctk.CTkLabel(bar, text="", font=F(13, "bold"), text_color=C["accent"])
        self.cat_total.pack(side="right")
        self.cat_table = Table(page, [("name", T("CATEGORÍA"), 360, "w"), ("group", T("GRUPO"), 130, "w"),
                                      ("size", T("TAMAÑO"), 110, "e"), ("files", T("ARCHIVOS"), 100, "e"),
                                      ("risk", T("NIVEL"), 110, "center")],
                               checkable=True, height=13, on_select=self._show_cat)
        self.cat_table.pack(fill="both", expand=True)
        self.cat_table.bind("<<CheckChanged>>", lambda e: self._update_cat_total())
        self.cat_table.context_menu([mi(T("Ver qué se borraría"), self._preview_cat, "search"),
                                     mi(T("Abrir carpeta"), self._open_cat, "open")])
        det = card(page)
        det.pack(fill="x", pady=(12, 0))
        self.cat_title = ctk.CTkLabel(det, text=T("Pulsa «Calcular espacio» para empezar"), font=F(14, "bold"),
                                      text_color=C["text"], anchor="w")
        self.cat_title.pack(fill="x", padx=22, pady=(16, 0))
        self.cat_detail = ctk.CTkLabel(det, text=T("«Seguro»: se regenera solo.   «Revisar»: tendrías que volver a "
                                                   "descargarlo.   Selecciona una fila para ver qué contiene."),
                                       font=F(12), text_color=C["muted"], anchor="w", justify="left", wraplength=1000)
        self.cat_detail.pack(fill="x", padx=22, pady=(2, 16))
        self._fill_categories()

    def _fill_categories(self):
        t = self.cat_table
        keep = set(t.checked)
        t.clear()
        grp = self.cat_filter.get()
        cats = [c for c in self.categories if grp == T("Todas") or c.group == grp]
        if any(getattr(c, "_scanned", False) for c in cats):
            cats.sort(key=lambda c: c.size, reverse=True)
        for c in cats:
            scanned = getattr(c, "_scanned", False)
            tags = ("muted",) if scanned and c.size == 0 else ("warn",) if c.risk == core.REVIEW else ()
            t.add(c.id, [c.name, c.group, human(c.size) if scanned else "—",
                         num(c.files) if scanned else "",
                         "●  " + (T("Seguro") if c.risk == core.SAFE else T("Revisar"))],
                  obj=c, sort={"size": c.size, "files": c.files}, tags=tags, checked=c.id in keep)
        self._update_cat_total()

    def _update_cat_total(self):
        sel = [c for c in self.categories if c.id in self.cat_table.checked]
        self.cat_total.configure(text=T("Seleccionado: {size}", size=human(sum(c.size for c in sel))) if sel else "")

    def _show_cat(self, c):
        if not c:
            return
        extra = []
        if c.admin and not core.is_admin():
            extra.append(T("Necesita ejecutar la app como administrador."))
        if c.close_apps:
            extra.append(T("Cierra {apps} antes de limpiar.", apps=c.close_apps))
        if c.risk == core.REVIEW:
            extra.append(T("Revisa antes de borrar: tendrías que volver a descargarlo."))
        where = "   ·   ".join(c.targets[:3]) if c.targets else T("No existe en este PC o falta calcular.")
        self.cat_title.configure(text=c.name + (f"  ·  {human(c.size)}" if getattr(c, "_scanned", False) else ""))
        self.cat_detail.configure(text=f"{c.description} {' '.join(extra)}\n{where}")

    def _check_safe(self):
        if not any(getattr(c, "_scanned", False) for c in self.categories):
            self.alert(T("Primero pulsa «Calcular espacio»."))
            return
        for c in self.categories:
            if self.cat_table.tv.exists(c.id):
                self.cat_table.set_checked(c.id, getattr(c, "_scanned", False) and c.risk == core.SAFE
                                           and c.size > 0 and (not c.admin or core.is_admin()))
        self._update_cat_total()

    def scan_categories(self):
        cats = self.categories

        def work(report):
            for c in cats:
                if self.cancel.is_set():
                    break
                report(T("Calculando {name}…", name=c.name))
                core.scan_category(c, self.cancel)
                c._scanned = True  # type: ignore[attr-defined]
            return cats

        def done(_):
            self._fill_categories()
            self.cat_title.configure(text=T("Marca lo que quieras limpiar y pulsa «Limpiar seleccionadas»"))
            total = sum(c.size for c in cats)
            safe = sum(c.size for c in cats if c.risk == core.SAFE)
            self.set_status(T("Recuperable: {total} · seguro: {safe}", total=human(total), safe=human(safe)))
            self.refresh_summary()
        self.run_task(T("Calculando categorías…"), work, done)

    def _open_cat(self):
        c = self.cat_table.focused()
        if c:
            c.targets = c.targets or c.resolve()
            if c.targets:
                core.open_in_explorer(c.targets[0])

    def _preview_cat(self):
        c = self.cat_table.focused()
        if not c:
            return
        if not getattr(c, "_scanned", False):
            c.targets = c.resolve()

        def work(report):
            items = []
            for p in c.items()[:5000]:
                if self.cancel.is_set():
                    break
                report(T("Midiendo {path}", path=p))
                items.append((p, core.dir_size(p, self.cancel)[0]))
            items.sort(key=lambda x: x[1], reverse=True)
            return items

        def done(items):
            d = Dialog(self, c.name, width=840, height=580)
            d.header("info", c.name, T("{n} elementos · {size}", n=num(len(items)),
                                         size=human(sum(s for _, s in items))))
            d.buttons([(T("Cerrar"), "primary", None)])
            box = ctk.CTkTextbox(d.body, font=ctk.CTkFont(family=MONO_FONT, size=12), fg_color=C["bg"],
                                 text_color=C["muted"], border_width=1, border_color=C["border"], corner_radius=8)
            box.pack(fill="both", expand=True, padx=24, pady=12)
            for p, s in items:
                box.insert("end", f"{human(s):>10}   {p}\n")
            if not items:
                box.insert("end", T("No hay nada que borrar aquí."))
            box.configure(state="disabled")
        self.run_task(T("Revisando {name}…", name=c.name), work, done)

    def clean_selected(self):
        cats = [c for c in self.categories if c.id in self.cat_table.checked]
        if not cats:
            self.alert(T("Marca al menos una categoría haciendo clic en su casilla."), T("Nada seleccionado"))
            return
        if any(not getattr(c, "_scanned", False) for c in cats):
            self.alert(T("Primero pulsa «Calcular espacio»."))
            return
        need_admin = [c.name for c in cats if c.admin and not core.is_admin()]
        items = [(f"[{c.name}]  {t}", c.target_sizes.get(t, 0)) for c in cats for t in c.targets]
        note = T("Se borra el contenido de estas carpetas. Lo que esté en uso se salta.")
        apps = sorted({c.close_apps for c in cats if c.close_apps})
        if apps:
            note += " " + T("Cierra antes: {apps}.", apps=", ".join(apps))
        if need_admin:
            note += "\n" + T("Sin permisos de administrador no se limpiará: {names}.", names=", ".join(need_admin))
        if any(c.risk == core.REVIEW for c in cats):
            note += "\n" + T("Incluye categorías «Revisar»: tendrías que volver a descargarlas.")
        perm = ConfirmDelete.ask(self, T("Confirmar limpieza"), items, note, default_permanent=True)
        if perm is None:
            return

        def work(report):
            total = core.DeleteResult()
            for c in cats:
                if self.cancel.is_set():
                    break
                report(T("Limpiando {name}…", name=c.name))
                total.merge(core.clean_category(c, perm))
                core.scan_category(c)
            return total

        def done(res):
            self._fill_categories()
            self.after_delete(res, perm)
        self.run_task(T("Limpiando…"), work, done)

    # =====================================================================
    # Mapa del disco (sunburst + lista + migas de pan)
    # =====================================================================
    def _build_analyzer(self, page):
        actions = self.page_header(page, T("Mapa del disco"),
                                   T("Pasa el ratón por los anillos y haz clic para entrar en una carpeta"))
        self.scan_info = ctk.CTkLabel(actions, text="", font=F(13, "bold"), text_color=C["accent"])
        self.scan_info.pack(side="right")
        bar = card(page)
        bar.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=12)
        self.scan_path = ctk.CTkEntry(inner, height=38, corner_radius=8, font=F(13), fg_color=C["bg"],
                                      border_color=C["border"], text_color=C["text"])
        self.scan_path.insert(0, core.SYSDRIVE if core.IS_WIN else core.HOME)
        self.scan_path.pack(side="left", fill="x", expand=True)
        btn(inner, T("Examinar…"), self._pick_folder, "secondary", width=110).pack(side="left", padx=8)
        btn(inner, T("Mi usuario"), lambda: self.start_scan(core.HOME), "secondary", width=110).pack(side="left")
        btn(inner, T("Analizar"), lambda: self.start_scan(self.scan_path.get()), "primary", width=120
            ).pack(side="left", padx=(8, 0))

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=5, uniform="m")
        body.grid_columnconfigure(1, weight=4, uniform="m")
        body.grid_rowconfigure(0, weight=1)
        mcard = card(body)
        mcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.crumbs = ctk.CTkFrame(mcard, fg_color="transparent", height=36)
        self.crumbs.pack(fill="x", padx=14, pady=(12, 0))
        self.sun = Sunburst(mcard, on_hover=self._map_hover, on_navigate=self._map_nav, on_context=self._map_menu,
                            on_file=self.preview, on_drag=self._sun_drag)
        self.sun.on_scan_text = lambda t: self.map_hover.configure(text=t, text_color=C["muted"])
        self.sun.is_shown = lambda: getattr(self, "_page", None) == "analyzer" and self.state() != "iconic"
        self.sun.pack(fill="both", expand=True, padx=10, pady=10)
        self.map_hover = ctk.CTkLabel(mcard, text=T("Clic en un anillo para entrar · clic en el centro para subir · "
                                                    "arrastra al Colector"), font=F(12), text_color=C["faint"],
                                      anchor="w", width=1)  # el texto (rutas largas) no empuja la maquetación
        self.map_hover.pack(fill="x", padx=16, pady=(0, 12))

        side = ctk.CTkFrame(body, fg_color="transparent")
        side.grid(row=0, column=1, sticky="nsew")
        hdr = ctk.CTkFrame(side, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 8))
        self.map_title = ctk.CTkLabel(hdr, text=T("Contenido"), font=F(15, "bold"), text_color=C["text"], anchor="w")
        self.map_title.pack(side="left")
        btn(hdr, "↑ " + T("Subir"), lambda: self.sun.up(), "ghost", width=80).pack(side="right")
        self.map_list = Table(side, [("name", T("NOMBRE"), 200, "w"), ("pct", "%", 64, "e"),
                                     ("size", T("TAMAÑO"), 96, "e")],
                              height=14, on_open=self._map_open_row, icons=True,
                              empty=self._map_empty())
        self.map_list.pack(fill="both", expand=True)
        ml = self.map_list
        self.map_list.context_menu([mi(T("Entrar / abrir"), lambda: self._map_open_row(ml.focused()), "enter",
                                       T("Doble clic")),
                                    mi(T("Vista previa"), lambda: self.preview(ml.focused()), "eye", T("Espacio")),
                                    SEP,
                                    mi(T("Añadir al Colector"), lambda: self._collect_nodes(ml.selected()), "add"),
                                    mi(T("Mostrar en el {fm}", fm=FILE_MANAGER), lambda: self._open_node(ml.focused()),
                                       "open"),
                                    mi(T("Copiar ruta"), lambda: self._copy_path(ml.focused()), "copy"),
                                    SEP,
                                    mi(T("Borrar…"), lambda: self._delete_nodes(ml.selected()), "trash", T("Supr"),
                                       danger=True)])
        self.map_list.tv.bind("<Delete>", lambda e: self._delete_nodes(ml.selected()))
        self.map_list.tv.bind("<space>", lambda e: (self.preview(self.map_list.focused()), "break")[1])
        self.map_list.tv.bind("<BackSpace>", lambda e: self.sun.up())
        self.map_list.enable_drag(self._table_drag)
        acts = ctk.CTkFrame(side, fg_color="transparent")
        acts.pack(fill="x", pady=(10, 0))
        btn(acts, T("Añadir al Colector"), lambda: self._collect_nodes(self.map_list.selected()), "primary"
            ).pack(side="left")
        btn(acts, T("Vista previa"), lambda: self.preview(self.map_list.focused()), "secondary", width=110
            ).pack(side="left", padx=8)
        btn(acts, T("Exportar CSV"), self._export_csv, "ghost", width=110).pack(side="right")

    def _map_empty(self):
        return ("map", T("Todavía no hay mapa"),
                T("Analiza un disco o una carpeta para ver de un vistazo qué ocupa tu espacio."),
                (T("Analizar ahora"), lambda: self.start_scan(self.scan_path.get())))

    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.scan_path.get() or core.HOME)
        if d:
            self.scan_path.delete(0, "end")
            self.scan_path.insert(0, os.path.normpath(d))

    def start_scan(self, path):
        path = os.path.normpath(path.strip()) if path else ""
        if core.IS_WIN and len(path) == 2 and path[1] == ":":
            path += "\\"
        if not os.path.isdir(path):
            self.alert(T("No existe la carpeta:\n{path}", path=path), T("Carpeta no encontrada"), "error")
            return
        if self.busy:
            self.alert(T("Espera a que termine la tarea actual o cancélala."), T("Tarea en curso"))
            return
        self.scan_path.delete(0, "end")
        self.scan_path.insert(0, path)
        self.show("analyzer")
        self.map_list.clear()
        self.map_list.set_empty(
            "search", T("Analizando…"),
            T("El contenido aparecerá aquí, ordenado por tamaño, en cuanto termine el análisis."))
        self.sun.start_scanning(path)

        def work(report):
            def prog(n, b, p):
                self.q.put(("scan", (n, b, p)))
                report(T("Analizando · {n} archivos", n=num(n)) + f" · {human(b)} · {p}")
            return core.scan_tree(path, self.cancel, prog)

        def done(res: core.ScanResult | None):
            self.sun.stop_scanning()
            self._map_hover(None)
            self.map_list.set_empty(*self._map_empty())
            if res is None:
                self.sun.redraw()
                return
            self.scan_result = res
            hidden = 0
            drive = next((d for d in core.list_drives() if core.norm(d.path) == core.norm(path)), None)
            if drive and not self.cancel.is_set():
                hidden = max(0, drive.used - res.root.size)
                if hidden < drive.used * 0.01:
                    hidden = 0
            self.scan_hidden = hidden
            self.sun.reset(res.root, hidden)
            self._fill_bigfiles()
            self._fill_model_files()
            self._fill_kinds()
            self.dup_table.clear()
            r = res.root
            txt = T("{size} en {n} archivos", size=human(r.size), n=num(r.files))
            if hidden:
                txt += "  ·  " + T("{size} ocultos", size=human(hidden))
            self.scan_info.configure(text=txt + (" " + T("(parcial)") if self.cancel.is_set() else ""))
        self.run_task(T("Analizando {path}…", path=path), work, done, on_error=lambda: (self.sun.stop_scanning(),
                                                                            self._map_hover(None),
                                                                            self.map_list.set_empty(
                                                                                *self._map_empty()),
                                                                            self.sun.redraw()))

    def _map_nav(self, node):
        # migas de pan
        for w in self.crumbs.winfo_children():
            w.destroy()
        chain = self.sun.history + [node]
        if len(chain) > 5:
            chain = chain[:1] + [None] + chain[-3:]
        for i, n in enumerate(chain):
            if i:
                ctk.CTkLabel(self.crumbs, text="›", text_color=C["faint"], font=F(13)).pack(side="left", padx=2)
            if n is None:
                ctk.CTkLabel(self.crumbs, text="…", text_color=C["faint"], font=F(12)).pack(side="left")
                continue
            last = n is node
            b = ctk.CTkButton(self.crumbs, text=n.name if len(n.name) < 28 else n.name[:26] + "…", height=28,
                              corner_radius=8, font=F(12, "bold"), width=0,
                              fg_color=C["accent_soft"] if last else "transparent", hover_color=C["hover"],
                              text_color=C["text"] if last else C["muted"],
                              command=(lambda x=n: self.sun.go_to(x)) if not last else None)
            b.pack(side="left")
        # lista
        t = self.map_list
        t.clear()
        hidden = self.sun.hidden if node is self.sun.base_root else 0
        self.map_title.configure(text=f"{node.name}  ·  {human(node.size)}")
        total = (node.size + hidden) or 1
        rows = [(c.size, c.name, c) for c in node.children[:500]] + [(f.size, f.name, f) for f in node.top_files]
        loose = core.loose_bytes(node)
        if loose:
            rows.append((loose, T("(archivos pequeños)"), None))
        if hidden:
            rows.append((hidden, T("(espacio oculto: sistema, sin permisos…)"), "hidden"))
        rows.sort(key=lambda r: r[0], reverse=True)
        # mismo color que su sector en el mapa: la lista y los anillos se leen juntos
        colors = {id(s[3]): s[4] for s in self.sun.segs if s[0] == 1 and s[3] is not None}
        k = t.k
        for size, name, obj in rows:
            frac = size / total
            is_node = isinstance(obj, core.Node)
            key = obj.path if is_node else node.path + ("<hidden>" if obj == "hidden" else "<files>")
            if is_node:
                col = colors.get(id(obj)) or C["faint"]
                img = share_image(col, "file" if obj.is_file else "dir", frac, k)
            else:
                img = share_image(C["faint"], "other", frac, k)
            pct = f"{frac * 100:.1f} %" if 0 < frac < 0.1 else f"{frac * 100:.0f} %"
            t.add(key, [name, pct, human(size)], obj=obj if is_node else None,
                  sort={"size": size, "pct": size}, tags=() if is_node else ("muted",), image=img)

    def _map_hover(self, node):
        if node is not None:
            self.map_hover.configure(text=node.path, text_color=C["muted"])
            if self.map_list.tv.exists(node.path):
                self.map_list.tv.selection_set(node.path)
                self.map_list.tv.see(node.path)
        else:
            self.map_hover.configure(text=T("Clic en un anillo para entrar · clic en el centro para subir · "
                                            "arrastra al Colector"), text_color=C["faint"])

    def _map_open_row(self, node):
        if isinstance(node, core.Node) and not node.is_file and (node.children or node.top_files):
            self.sun.set_root(node)
        elif isinstance(node, core.Node):
            self.preview(node)

    def _map_menu(self, node, e):
        items = []
        if not node.is_file and (node.children or node.top_files):
            items.append(mi(T("Entrar"), lambda: self.sun.set_root(node), "enter", T("Clic")))
        items += [mi(T("Vista previa"), lambda: self.preview(node), "eye"),
                  SEP,
                  mi(T("Añadir al Colector"), lambda: self._collect_nodes([node]), "add"),
                  mi(T("Mostrar en el {fm}", fm=FILE_MANAGER), lambda: core.open_in_explorer(node.path), "open"),
                  mi(T("Copiar ruta"), lambda: self._copy_path(node), "copy"),
                  SEP,
                  mi(T("Borrar…"), lambda: self._delete_nodes([node]), "trash", danger=True)]
        name = node.name if len(node.name) <= 42 else node.name[:40] + "…"
        PopupMenu(self, items, e.x_root, e.y_root, title=name,
                  subtitle=human(node.size) + "  ·  " + (T("archivo") if node.is_file else T("carpeta")))

    def _open_node(self, node):
        if node is not None:
            path = node.path if isinstance(node, core.Node) else node[1] if isinstance(node, tuple) else str(node)
            core.open_in_explorer(path)

    def _copy_path(self, node):
        if node is None:
            return
        path = node.path if isinstance(node, core.Node) else node[1] if isinstance(node, tuple) else str(node)
        self.clipboard_clear()
        self.clipboard_append(path)
        self.set_status(T("Ruta copiada"))

    def _delete_nodes(self, nodes):
        nodes = [n for n in nodes if isinstance(n, core.Node)]
        self._delete_paths_ui([(n.path, n.size) for n in nodes], on_done=self._after_map_delete)

    def _after_map_delete(self, paths):
        if not self.scan_result or not paths:
            return
        gone = {core.norm(p) for p in paths}
        order, stack = [], [self.scan_result.root]
        while stack:
            n = stack.pop()
            order.append(n)
            n.children = [c for c in n.children if core.norm(c.path) not in gone]
            kept = [f for f in n.top_files if core.norm(f.path) not in gone]
            if len(kept) != len(n.top_files):
                removed = [f for f in n.top_files if core.norm(f.path) in gone]
                n.own_files -= sum(f.size for f in removed)
                n.top_files = kept
            stack.extend(n.children)
        for n in reversed(order):
            n.size = n.own_files + sum(c.size for c in n.children)
        root = self.sun.root_node
        if root is not None:
            self.sun.set_root(root, push=False, animate=False)

    # =====================================================================
    # Arrastrar al Colector y vista previa
    # =====================================================================
    @staticmethod
    def _as_items(objs):
        out = []
        for o in objs:
            if isinstance(o, core.Node):
                out.append((o.path, o.size))
            elif isinstance(o, tuple) and len(o) == 2 and isinstance(o[1], str):
                out.append((o[1], o[0]))
        return out

    def _over_collector(self, e):
        f = self.col_frame
        x, y = f.winfo_rootx(), f.winfo_rooty()
        return x <= e.x_root <= x + f.winfo_width() and y <= e.y_root <= y + f.winfo_height()

    def _drag(self, phase, items, e):
        if phase == "start":
            if not items:
                return
            self._drag_items = items
            g = tk.Toplevel(self)
            g.overrideredirect(True)
            try:
                g.attributes("-topmost", True)
                g.attributes("-alpha", 0.94)
            except tk.TclError:
                pass
            g.configure(bg=C["accent"])
            total = sum(s for _, s in items)
            name = os.path.basename(items[0][0].rstrip("\\/")) or items[0][0]
            txt = name if len(items) == 1 else T("{n} elementos", n=num(len(items)))
            tk.Label(g, text=f"  {txt}  ·  {human(total)}  ", bg=C["accent"], fg="#ffffff",
                     font=(UI_FONT, 10, "bold"), padx=6, pady=5).pack()
            self._ghost = g
            phase = "move"
        g = getattr(self, "_ghost", None)
        if g is None:
            return
        over = self._over_collector(e)
        if phase == "move":
            g.geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
            self.col_frame.configure(border_color=C["accent"] if over else C["accent_soft"],
                                     fg_color=C["accent_soft"] if over else C["surface"])
        elif phase == "drop":
            g.destroy()
            self._ghost = None
            self.col_frame.configure(border_color=C["accent_soft"], fg_color=C["surface"])
            if over:
                self._collect(self._drag_items)

    def _sun_drag(self, phase, nodes, e):
        self._drag(phase, self._as_items(nodes) if nodes else None, e)

    def _table_drag(self, phase, objs, e):
        self._drag(phase, self._as_items(objs) if objs else None, e)

    def preview(self, obj):
        """Vista previa rápida (como pulsar Espacio en el Finder): imagen, texto o resumen de la carpeta."""
        if obj is None:
            return
        if isinstance(obj, core.Node):
            path, size, node = obj.path, obj.size, obj
        elif isinstance(obj, tuple) and len(obj) == 2:
            size, path = obj
            node = None
        else:
            return
        import time
        name = os.path.basename(path.rstrip("\\/")) or path
        try:
            st = os.stat(path)
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(st.st_mtime))
        except OSError:
            st, when = None, ""
        is_dir = os.path.isdir(path)
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        kind = T("Carpeta") if is_dir else core.kind_of(ext) + (f" · .{ext}" if ext else "")
        d = Dialog(self, name, width=800, height=600)
        d.minsize(600, 420)
        d.header("info", name, f"{kind}  ·  {human(size)}" +
                 ("  ·  " + T("modificado {date}", date=when) if when else "") + f"\n{path}")
        d.buttons([(T("Mostrar en el {fm}", fm=FILE_MANAGER), "secondary", "show"),
                   (T("Al Colector"), "secondary", "collect"), (T("Cerrar"), "primary", None)])
        box = ctk.CTkFrame(d.body, fg_color=C["bg"], corner_radius=12, border_width=1, border_color=C["border"])
        box.pack(fill="both", expand=True, padx=24, pady=12)
        shown = False
        if not is_dir and Image is not None and ext in {"png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "tif",
                                                          "tiff"} and size < 200 * 1024 * 1024:
            try:
                im = Image.open(path)
                im.thumbnail((int(720 * _scale_of(d)), int(330 * _scale_of(d))))
                cim = ctk.CTkImage(light_image=im, dark_image=im, size=(im.width / _scale_of(d),
                                                                      im.height / _scale_of(d)))
                ctk.CTkLabel(box, image=cim, text="").pack(expand=True, pady=12)
                d._img = cim
                shown = True
            except Exception:  # noqa: BLE001
                pass
        if not shown and not is_dir and size < 4 * 1024 * 1024:
            try:
                with open(path, "rb") as fh:
                    raw = fh.read(16000)
                if b"\x00" not in raw[:4000]:
                    tb = ctk.CTkTextbox(box, font=ctk.CTkFont(family=MONO_FONT, size=12), fg_color=C["bg"],
                                        text_color=C["muted"], border_width=0, corner_radius=8)
                    tb.insert("end", raw.decode("utf-8", errors="replace"))
                    tb.configure(state="disabled")
                    tb.pack(fill="both", expand=True, padx=6, pady=6)
                    shown = True
            except OSError:
                pass
        if not shown and is_dir and node is not None:
            items = sorted(node.children + node.top_files, key=lambda c: c.size, reverse=True)[:14]
            for ch in items:
                r = ctk.CTkFrame(box, fg_color="transparent")
                r.pack(fill="x", padx=16, pady=(8, 0))
                ctk.CTkLabel(r, text=("▸  " if not ch.is_file else "     ") + ch.name, font=F(12), anchor="w",
                             text_color=C["text"]).pack(side="left")
                ctk.CTkLabel(r, text=human(ch.size), font=F(12, "bold"), text_color=C["muted"]).pack(side="right")
                bar = self._bar(box, ch.size / (node.size or 1), 4)
                bar.configure(progress_color=seg_color(0 if not items else 360 * items.index(ch) / len(items), 1))
                bar.pack(fill="x", padx=16, pady=(2, 0))
            shown = bool(items)
        if not shown:
            ctk.CTkLabel(box, text=T("Sin vista previa para este tipo de archivo"), font=F(13),
                         text_color=C["faint"]).pack(expand=True)
        self.wait_window(d)
        if d.result == "show":
            core.open_in_explorer(path)
        elif d.result == "collect":
            self._collect([(path, size)])

    def _export_csv(self):
        if not self.scan_result:
            self.alert(T("Primero analiza un disco o una carpeta."))
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="pc-free-space.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            core.export_csv(self.scan_result, path)
            self.set_status(T("Exportado: {path}", path=path))

    # =====================================================================
    # Colector (cesta de elementos para borrar de una vez)
    # =====================================================================
    def _collect(self, items):
        added = 0
        for p, s in items:
            if p and p not in self.collector:
                self.collector[p] = s
                added += 1
        self._update_collector()
        if added:
            self.set_status(T("Añadido al Colector: {n} elemento(s)", n=num(added)))

    def _collect_nodes(self, nodes):
        self._collect([(n.path, n.size) for n in nodes if isinstance(n, core.Node)])

    def _collect_rows(self, table, checked=True):
        objs = [o for o in (table.checked_objs() if checked else table.selected()) if o]
        if not objs and checked:
            objs = [o for o in table.selected() if o]
        if not objs:
            self.alert(T("Marca o selecciona primero algún elemento."), T("Nada seleccionado"))
            return
        self._collect([(p, s) for s, p in objs])

    def _update_collector(self):
        n = len(self.collector)
        total = sum(self.collector.values())
        self.col_label.configure(text=T("{n} elementos · {size}", n=num(n), size=human(total)) if n else
                                 T("Arrastra aquí carpetas y archivos desde el mapa o las listas"))
        self.col_count.configure(text=str(n), fg_color=C["accent"] if n else C["surface2"])
        state = "normal" if n else "disabled"
        self.col_del.configure(state=state, fg_color=C["bad_h"] if n else C["surface2"],
                               text_color_disabled=C["faint"])
        self.col_view.configure(state=state, text_color_disabled=C["faint"])

    def _collector_review(self):
        if not self.collector:
            return
        items = sorted(self.collector.items(), key=lambda x: x[1], reverse=True)

        def done(paths):
            for p in paths:
                self.collector.pop(p, None)
            self._update_collector()
            self._after_map_delete(paths)
            self._remove_rows(self.big_table, paths)
            self._remove_rows(self.model_table, paths)
        self._delete_paths_ui(items, on_done=done)

    def _collector_clear(self):
        self.collector.clear()
        self._update_collector()

    # =====================================================================
    # Tipos de archivo
    # =====================================================================
    def _build_kinds(self, page):
        self.page_header(page, T("Tipos de archivo"),
                         T("Qué clase de archivos ocupa tu espacio, según el último análisis"))
        top = card(page)
        top.pack(fill="x", pady=(0, 12))
        self.kind_box = ctk.CTkFrame(top, fg_color="transparent")
        self.kind_box.pack(fill="x", padx=20, pady=18)
        self._kinds_placeholder()
        self.section(page, T("Extensiones que más ocupan"))
        self.ext_table = Table(page, [("name", T("EXTENSIÓN"), 160, "w"), ("kind", T("TIPO"), 220, "w"),
                                      ("size", T("TAMAÑO"), 110, "e"), ("files", T("ARCHIVOS"), 110, "e"),
                                      ("pct", T("% DEL TOTAL"), 110, "e")], height=7,
                               empty=("list", T("Sin datos todavía"),
                                      T("Analiza un disco o una carpeta y aquí verás qué extensiones ocupan más."),
                                      (T("Ir al Mapa del disco"), lambda: self.show("analyzer"))),
                               on_open=lambda ext: self._show_ext(ext))
        self.ext_table.pack(fill="both", expand=True)
        self.hint(page, T("Doble clic en una extensión para ver sus archivos más grandes."))

    def _kinds_placeholder(self):
        """Barra apilada «fantasma» mientras no hay análisis: anticipa lo que aparecerá."""
        ph = ctk.CTkFrame(self.kind_box, fg_color="transparent")
        ph.pack(fill="x")
        bar = ctk.CTkFrame(ph, fg_color="transparent", height=18)
        bar.pack(fill="x", pady=(0, 16))
        for i, (w, col) in enumerate(((5, 0.55), (3, 0.42), (2, 0.32), (1, 0.24))):
            bar.grid_columnconfigure(i, weight=w, uniform="ph")
            ctk.CTkFrame(bar, height=18, corner_radius=6, fg_color=_mix(C["track"], C["accent"], col * 0.35)
                         ).grid(row=0, column=i, sticky="ew", padx=(0, 4))
        row = ctk.CTkFrame(ph, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text=icon("info"), font=IF(14), text_color=C["faint"]).pack(side="left", padx=(2, 10))
        ctk.CTkLabel(row, text=T("Aquí verás el reparto por tipo de archivo (vídeos, programas, código…) "
                                 "en cuanto analices un disco o una carpeta."), font=F(12),
                     text_color=C["muted"]).pack(side="left")

    def _fill_kinds(self):
        res = self.scan_result
        for w in self.kind_box.winfo_children():
            w.destroy()
        self.ext_table.clear()
        if not res:
            self._kinds_placeholder()
            return
        total = res.root.size or 1
        kinds = res.kinds()
        colors = {k: PALETTE[i % len(PALETTE)] for i, (k, _b, _n) in enumerate(kinds)}
        # barra apilada
        stack = tk.Canvas(self.kind_box, height=18, bg=C["surface"], highlightthickness=0)
        stack.pack(fill="x", pady=(0, 16))

        def paint(_e=None):
            stack.delete("all")
            w = stack.winfo_width()
            x = 0
            for k, b, _n in kinds:
                dx = w * b / total
                if dx >= 1:
                    stack.create_rectangle(x, 0, x + dx, 18, fill=colors[k], outline=C["surface"], width=2)
                x += dx
        stack.bind("<Configure>", paint)
        grid = ctk.CTkFrame(self.kind_box, fg_color="transparent")
        grid.pack(fill="x")
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1, uniform="k")
        for i, (k, b, n) in enumerate(kinds[:12]):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=i // 3, column=i % 3, sticky="ew", pady=6, padx=(0, 12))
            ctk.CTkLabel(cell, text="●", text_color=colors[k], font=F(14), width=16).pack(side="left")
            ctk.CTkLabel(cell, text=k, font=F(13, "bold"), text_color=C["text"]).pack(side="left", padx=6)
            ctk.CTkLabel(cell, text=f"{human(b)} · {b / total * 100:.0f}%", font=F(12), text_color=C["muted"]
                         ).pack(side="right")
        exts = sorted(res.ext_stats.items(), key=lambda x: x[1][0], reverse=True)[:300]
        for ext, (b, n) in exts:
            label = "." + ext if ext else T("(sin extensión)")
            self.ext_table.add("ext:" + ext, [label, core.kind_of(ext), human(b), num(n),
                                              f"{b / total * 100:.1f} %"], obj=ext,
                               sort={"size": b, "files": n, "pct": b})

    def _show_ext(self, ext):
        if ext is None or not self.scan_result:
            return
        self.show("big")
        self.min_size.set("50 MB")
        self.age_filter.set(self._ages[0][0])
        self.ext_filter.delete(0, "end")
        self.ext_filter.insert(0, "." + ext if ext else "")
        self._fill_bigfiles()

    # =====================================================================
    # Duplicados
    # =====================================================================
    def _build_dups(self, page):
        actions = self.page_header(page, T("Duplicados"),
                                   T("Archivos idénticos (mismo contenido) dentro del último análisis"))
        btn(actions, T("Añadir marcados al Colector"), lambda: self._collect_dups(), "secondary", width=220
            ).pack(side="right")
        btn(actions, T("Buscar duplicados"), self.find_dups, "primary", width=170).pack(side="right", padx=8)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text=T("Tamaño mínimo"), font=F(12), text_color=C["muted"]).pack(side="left", padx=(0, 10))
        self.dup_min = ctk.CTkSegmentedButton(
            bar, values=["1 MB", "10 MB", "100 MB"], font=F(12, "bold"), height=34, corner_radius=8,
            fg_color=C["surface"], selected_color=C["accent"], selected_hover_color=C["accent_h"],
            unselected_color=C["surface"], unselected_hover_color=C["hover"], text_color=C["text"])
        self.dup_min.set("10 MB")
        self.dup_min.pack(side="left")
        btn(bar, T("Marcar copias (deja 1)"), self._dup_mark_copies, "ghost", width=180).pack(side="left", padx=12)
        self.dup_info = ctk.CTkLabel(bar, text="", font=F(13, "bold"), text_color=C["accent"])
        self.dup_info.pack(side="right")
        self.dup_table = Table(page, [("name", T("ARCHIVO"), 320, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                      ("copies", T("COPIAS"), 90, "center"), ("path", T("CARPETA"), 420, "w")],
                               checkable=True, height=16, on_open=self._open_node,
                               empty=("copy", T("Encuentra archivos repetidos"),
                                      T("Compara por contenido los archivos del último análisis para quedarte "
                                        "con una sola copia."), (T("Buscar duplicados"), self.find_dups)))
        self.dup_table.pack(fill="both", expand=True)
        self.dup_table.enable_drag(self._table_drag)
        dt = self.dup_table
        self.dup_table.context_menu([mi(T("Vista previa"), lambda: self.preview(dt.focused()), "eye"),
                                     mi(T("Mostrar en el {fm}", fm=FILE_MANAGER), lambda: self._open_node(dt.focused()),
                                        "open", T("Doble clic")),
                                     SEP,
                                     mi(T("Añadir al Colector"), lambda: self._collect_rows(dt, False), "add")])
        self.hint(page, T("Compara tamaño y huella del contenido (BLAKE2), así que solo lista copias exactas. "
                          "«Marcar copias» deja sin marcar la primera de cada grupo."))
        self._dup_groups: list = []

    def find_dups(self):
        if not self.scan_result:
            self.alert(T("Primero analiza un disco o una carpeta en «Mapa del disco»."))
            return
        mins = {"1 MB": 1, "10 MB": 10, "100 MB": 100}[self.dup_min.get()] * 1024 * 1024
        res = self.scan_result

        def done(groups):
            self._dup_groups = groups
            t = self.dup_table
            t.clear()
            for gi, g in enumerate(groups[:400]):
                for pi, p in enumerate(g.paths):
                    t.add(f"d{gi}:{pi}", [os.path.basename(p), human(g.size), f"{pi + 1}/{len(g.paths)}",
                                          os.path.dirname(p)], obj=(g.size, p),
                          sort={"size": g.size * 1000 - gi}, tags=() if pi else ("warn",))
            wasted = sum(g.wasted for g in groups)
            self.dup_info.configure(text=T("{n} grupos · {size} recuperables", n=num(len(groups)),
                                           size=human(wasted)))
            if not groups:
                t.set_empty("check", T("Sin duplicados"),
                            T("No hay copias exactas por encima del tamaño mínimo elegido. ¡Todo en orden!"),
                            (T("Buscar de nuevo"), self.find_dups))
        self.run_task(T("Buscando duplicados…"), lambda report: core.find_duplicates(
            res, mins, self.cancel, lambda p: report(T("Comparando {path}", path=p))), done)

    def _dup_mark_copies(self):
        for k in self.dup_table.tv.get_children():
            self.dup_table.set_checked(k, not k.endswith(":0"))

    def _collect_dups(self):
        self._collect_rows(self.dup_table)

    def _delete_paths_ui(self, items, on_done=None):
        if not items:
            return
        blocked, rest = [], []
        warn_note = ""
        for p, s in items:
            lvl, why = core.protection_level(p)
            if lvl == core.BLOCK:
                blocked.append((p, why))
            else:
                rest.append((p, s))
                if lvl == core.WARN:
                    warn_note = why
        if blocked:
            self.alert(T("No se borrarán porque están protegidos:") + "\n\n" +
                       "\n".join(f"• {p}\n   {why}" for p, why in blocked[:6]), T("Elementos protegidos"), "warn")
        if not rest:
            return
        perm = ConfirmDelete.ask(self, T("Confirmar borrado"), rest, warn_note)
        if perm is None:
            return
        paths = [p for p, _ in rest]

        def work(report):
            return core.delete_paths(paths, perm, lambda p: report(T("Borrando {path}", path=p)))

        def done(res):
            if on_done:
                on_done([p for p in paths if not os.path.lexists(p)])
            self.after_delete(res, perm)
        self.run_task(T("Borrando…"), work, done)

    # =====================================================================
    # Archivos grandes
    # =====================================================================
    def _build_bigfiles(self, page):
        actions = self.page_header(page, T("Archivos grandes"), T("Los archivos más pesados del último análisis"))
        btn(actions, T("Borrar marcados…"), lambda: self._delete_checked(self.big_table), "danger_solid", width=170
            ).pack(side="right")
        btn(actions, T("Al Colector"), lambda: self._collect_rows(self.big_table), "secondary", width=120
            ).pack(side="right", padx=8)
        self.big_info = ctk.CTkLabel(actions, text="", font=F(13, "bold"), text_color=C["accent"])
        self.big_info.pack(side="right", padx=14)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        self.min_size = ctk.CTkSegmentedButton(
            bar, values=["50 MB", "100 MB", "500 MB", "1 GB", "5 GB"], command=lambda _v: self._fill_bigfiles(),
            font=F(12, "bold"), height=34, corner_radius=8, fg_color=C["surface"], selected_color=C["accent"],
            selected_hover_color=C["accent_h"], unselected_color=C["surface"], unselected_hover_color=C["hover"],
            text_color=C["text"])
        self.min_size.set("100 MB")
        self.min_size.pack(side="left")
        self.ext_filter = ctk.CTkEntry(bar, width=300, height=34, corner_radius=8, font=F(12), fg_color=C["surface"],
                                       border_color=C["border"], text_color=C["text"],
                                       placeholder_text=T("Filtrar: .iso, .zip, .mp4, nombre…"),
                                       placeholder_text_color=C["faint"])
        self.ext_filter.pack(side="left", padx=12)
        self.ext_filter.bind("<KeyRelease>", lambda e: self._fill_bigfiles())
        ctk.CTkLabel(bar, text=T("Sin tocar desde"), font=F(12), text_color=C["muted"]).pack(side="left", padx=(4, 8))
        # texto mostrado (traducido) -> días; el valor se lee de vuelta por el texto
        self._ages = [(T("Cualquiera"), 0), (T("6 meses"), 182), (T("1 año"), 365), (T("2 años"), 730)]
        self.age_filter = Select(bar, values=[a for a, _d in self._ages], width=130,
                                            height=34, corner_radius=8, font=F(12), fg_color=C["surface"],
                                            button_color=C["surface2"], button_hover_color=C["hover"],
                                            dropdown_fg_color=C["surface2"], text_color=C["text"],
                                            command=lambda _v: self._fill_bigfiles())
        self.age_filter.set(self._ages[0][0])
        self.age_filter.pack(side="left")
        self.big_table = Table(page, [("name", T("ARCHIVO"), 280, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                      ("type", T("TIPO"), 100, "center"), ("date", T("MODIFICADO"), 110, "center"),
                                      ("path", T("CARPETA"), 420, "w")],
                               checkable=True, height=16, on_open=self._open_node,
                               empty=("file", T("Sin análisis todavía"),
                                      T("Analiza un disco o una carpeta en «Mapa del disco» y aquí verás sus "
                                        "archivos más pesados."),
                                      (T("Ir al Mapa del disco"), lambda: self.show("analyzer"))))
        self.big_table.pack(fill="both", expand=True)
        self.big_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.big_table, self.big_info))
        self.big_table.enable_drag(self._table_drag)
        bt = self.big_table
        self.big_table.context_menu([mi(T("Vista previa"), lambda: self.preview(bt.focused()), "eye"),
                                     mi(T("Mostrar en el {fm}", fm=FILE_MANAGER), lambda: self._open_node(bt.focused()),
                                        "open", T("Doble clic")),
                                     SEP,
                                     mi(T("Añadir al Colector"), lambda: self._collect_rows(bt, False), "add"),
                                     mi(T("Copiar ruta"), lambda: self._copy_path(bt.focused()), "copy"),
                                     SEP,
                                     mi(T("Borrar…"), lambda: self._delete_rows(bt), "trash", T("Supr"), danger=True)])
        self.big_table.tv.bind("<Delete>", lambda e: self._delete_rows(bt))
        self.hint(page, T("Clic en la casilla para marcar · doble clic lo muestra en el {fm} · arrastra filas al "
                          "Colector.", fm=FILE_MANAGER))

    def _fill_bigfiles(self):
        t = self.big_table
        t.clear()
        if not self.scan_result:
            return
        mins = {"50 MB": 50, "100 MB": 100, "500 MB": 500, "1 GB": 1024, "5 GB": 5120}[self.min_size.get()] * 1024 ** 2
        flt = self.ext_filter.get().strip().lower()
        import time
        days = dict(self._ages).get(self.age_filter.get(), 0)
        limit = time.time() - days * 86400
        mt = self.scan_result.mtimes
        n = total = 0
        for size, path in self.scan_result.big_files:
            if size < mins or (flt and flt not in path.lower()):
                continue
            m = mt.get(path, 0)
            if days and (not m or m > limit):
                continue
            t.add(path, [os.path.basename(path), human(size), os.path.splitext(path)[1].lower() or "—",
                         time.strftime("%d/%m/%Y", time.localtime(m)) if m else "",
                         os.path.dirname(path)], obj=(size, path), sort={"size": size, "date": m})
            n += 1
            total += size
        self.big_info.configure(text=T("{n} archivos · {size}", n=num(n), size=human(total)))
        if not n:
            t.set_empty("search", T("Nada con estos filtros"),
                        T("Prueba con un tamaño mínimo menor, otra antigüedad o borra el texto del filtro."))

    def _update_checked_info(self, table, label):
        objs = [o for o in table.checked_objs() if o]
        if objs:
            label.configure(text=T("Marcados: {n} · {size}", n=num(len(objs)), size=human(sum(o[0] for o in objs))))

    def _delete_checked(self, table):
        objs = [o for o in table.checked_objs() if o]
        if not objs:
            self.alert(T("Marca primero los elementos haciendo clic en su casilla."), T("Nada marcado"))
            return
        self._delete_paths_ui([(p, s) for s, p in objs], on_done=lambda ps: self._remove_rows(table, ps))

    def _delete_rows(self, table):
        objs = [o for o in table.selected() if o]
        self._delete_paths_ui([(p, s) for s, p in objs], on_done=lambda ps: self._remove_rows(table, ps))

    def _remove_rows(self, table, paths):
        gone = set(paths)
        table.remove(paths)
        if self.scan_result:
            self.scan_result.big_files = [x for x in self.scan_result.big_files if x[1] not in gone]
            self.scan_result.model_files = [x for x in self.scan_result.model_files if x[1] not in gone]

    # =====================================================================
    # Modelos de IA
    # =====================================================================
    def _build_models(self, page):
        actions = self.page_header(page, T("Modelos IA"),
                                   T("LLMs y pesos de IA descargados: Ollama, Hugging Face, LM Studio…"))
        btn(actions, T("Buscar en mi usuario"), lambda: self.start_scan(core.HOME), "primary", width=180
            ).pack(side="right")
        top, self.ollama_info = self.section(page, "Ollama")
        btn(top, T("Eliminar modelo"), self._ollama_rm, "danger", width=150).pack(side="right")
        btn(top, T("Actualizar"), self._fill_ollama, "ghost", width=100).pack(side="right", padx=6)
        self.ollama_table = Table(page, [("name", T("MODELO"), 360, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                         ("path", T("MANIFIESTO"), 420, "w")], height=5,
                                  empty=("ai", T("Sin modelos de Ollama"),
                                         T("Si usas Ollama, aquí verás cada modelo y lo que ocupa.")))
        self.ollama_table.pack(fill="both", expand=True)
        mid, self.model_info = self.section(page, T("Archivos de modelos"),
                                            ".gguf · .safetensors · .ckpt · .pt · .onnx · .bin  (≥ 50 MB)", (18, 8))
        btn(mid, T("Borrar marcados…"), lambda: self._delete_checked(self.model_table), "danger", width=160
            ).pack(side="right")
        btn(mid, T("Al Colector"), lambda: self._collect_rows(self.model_table), "secondary", width=110
            ).pack(side="right", padx=8)
        self.model_table = Table(page, [("name", T("ARCHIVO"), 300, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                        ("app", T("ORIGEN"), 140, "w"), ("path", T("CARPETA"), 420, "w")],
                                 checkable=True, height=9, on_open=self._open_node,
                                 empty=("ai", T("Busca modelos descargados"),
                                        T("Pesos .gguf, .safetensors, .ckpt… de Hugging Face, LM Studio y otras "
                                          "apps."),
                                        (T("Buscar en mi usuario"), lambda: self.start_scan(core.HOME))))
        self.model_table.pack(fill="both", expand=True)
        self.model_table.bind("<<CheckChanged>>",
                              lambda e: self._update_checked_info(self.model_table, self.model_info))
        self.model_table.enable_drag(self._table_drag)
        mt = self.model_table
        self.model_table.context_menu([mi(T("Mostrar en el {fm}", fm=FILE_MANAGER),
                                          lambda: self._open_node(mt.focused()), "open", T("Doble clic")),
                                       mi(T("Copiar ruta"), lambda: self._copy_path(mt.focused()), "copy"),
                                       mi(T("Añadir al Colector"), lambda: self._collect_rows(mt, False), "add"),
                                       SEP,
                                       mi(T("Borrar…"), lambda: self._delete_rows(mt), "trash", T("Supr"),
                                          danger=True)])
        self.model_table.tv.bind("<Delete>", lambda e: self._delete_rows(mt))
        self.hint(page, T("Los modelos de Ollama se eliminan con «ollama rm» para no dejar la instalación "
                          "inconsistente."))
        self.after(400, self._fill_ollama)

    def _fill_ollama(self):
        t = self.ollama_table
        t.clear()
        models = core.list_ollama_models()
        for m in models:
            t.add(m.manifest, [m.name, human(m.size), m.manifest], obj=m, sort={"size": m.size})
        self.ollama_info.configure(text=T("{n} modelos · {size}", n=num(len(models)),
                                          size=human(sum(m.size for m in models))) if models else "")

    def _ollama_rm(self):
        m = self.ollama_table.focused()
        if not m:
            self.alert(T("Selecciona un modelo de la lista."), T("Ningún modelo seleccionado"))
            return
        if not self.confirm(T("¿Eliminar {name}?", name=m.name),
                            T("Liberarás {size}. Si lo necesitas otra vez, tendrás que descargarlo con "
                              "«ollama pull».", size=human(m.size)), T("Eliminar"), danger=True):
            return

        def done(res):
            ok, out = res
            if ok:
                core.add_freed(m.size)
                self.alert(T("Has liberado {size}.", size=human(m.size)), T("{name} eliminado", name=m.name), "ok")
            else:
                self.alert(f"{out}\n\n" + T("Comprueba que Ollama está instalado y en ejecución."),
                           T("No se pudo eliminar"), "error")
            self._fill_ollama()
            self.refresh_summary()
        self.run_task(T("Eliminando {name}…", name=m.name), lambda report: core.ollama_remove(m.name), done)

    @staticmethod
    def _guess_origin(path: str) -> str:
        p = path.lower()
        for key, name in ((".ollama", "Ollama"), ("huggingface", "Hugging Face"), ("lm-studio", "LM Studio"),
                          (".lmstudio", "LM Studio"), ("comfyui", "ComfyUI"), ("stable-diffusion", "Stable Diffusion"),
                          ("automatic1111", "Stable Diffusion"), ("gpt4all", "GPT4All"), ("torch", "PyTorch"),
                          ("whisper", "Whisper"), (".keras", "Keras"), ("deepface", "DeepFace"), ("rembg", "rembg"),
                          ("u2net", "rembg"), ("modelscope", "ModelScope"), ("jan", "Jan"), ("invokeai", "InvokeAI"),
                          ("fooocus", "Fooocus"), ("pinokio", "Pinokio"), ("unity", "Unity")):
            if key in p:
                return name
        return ""

    def _fill_model_files(self):
        t = self.model_table
        t.clear()
        if not self.scan_result:
            return
        for size, path in self.scan_result.model_files:
            t.add(path, [os.path.basename(path), human(size), self._guess_origin(path), os.path.dirname(path)],
                  obj=(size, path), sort={"size": size})
        total = sum(s for s, _ in self.scan_result.model_files)
        self.model_info.configure(text=T("{n} archivos · {size}", n=num(len(self.scan_result.model_files)),
                                         size=human(total)))

    # =====================================================================
    # Aplicaciones y restos
    # =====================================================================
    def _build_apps(self, page):
        actions = self.page_header(page, T("Aplicaciones"),
                                   T("Programas instalados y restos de los que ya desinstalaste"))
        btn(actions, T("Desinstalar…"), self._uninstall, "danger_solid", width=140).pack(side="right")
        btn(actions, T("Calcular tamaño real"), self._measure_apps, "secondary", width=170).pack(side="right", padx=8)
        btn(actions, T("Cargar aplicaciones"), self.load_apps, "primary", width=170).pack(side="right")
        top, self.apps_info = self.section(page, T("Instaladas"))
        if core.IS_WIN:
            btn(top, T("Aplicaciones de Windows") + "  ↗", lambda: self._launch("ms-settings:appsfeatures"), "ghost",
                width=200).pack(side="right")
        self.apps_table = Table(page, [("name", T("APLICACIÓN"), 320, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                       ("publisher", T("EDITOR"), 190, "w"), ("date", T("INSTALADA"), 100, "center"),
                                       ("path", T("UBICACIÓN"), 320, "w")], height=9,
                                on_open=lambda a: a and a.location and core.open_in_explorer(a.location),
                                empty=("apps", T("Tus aplicaciones instaladas"),
                                       T("Carga la lista para ver cuánto ocupa cada programa y desinstalar lo que "
                                         "no uses."), (T("Cargar aplicaciones"), self.load_apps)))
        self.apps_table.pack(fill="both", expand=True)
        self.apps_table.context_menu([mi(T("Abrir ubicación"), self._open_app, "open", T("Doble clic")),
                                      SEP,
                                      mi(T("Desinstalar…"), self._uninstall, "trash", danger=True)])
        mid, self.res_info = self.section(page, T("Posibles restos"),
                                          T("Carpetas de 20 MB o más que no coinciden con ninguna app instalada"),
                                          (18, 8))
        btn(mid, T("Borrar marcados…"), lambda: self._delete_checked(self.res_table), "danger", width=160
            ).pack(side="right")
        btn(mid, T("Al Colector"), lambda: self._collect_rows(self.res_table), "secondary", width=110
            ).pack(side="right", padx=8)
        btn(mid, T("Buscar restos"), self.find_residues, "secondary", width=130).pack(side="right")
        self.res_table = Table(page, [("name", T("CARPETA"), 300, "w"), ("size", T("TAMAÑO"), 110, "e"),
                                      ("where", T("DÓNDE"), 180, "w"), ("path", T("RUTA"), 420, "w")],
                               checkable=True, height=7, on_open=self._open_node,
                               empty=("search", T("Restos de apps desinstaladas"),
                                      T("Busca carpetas grandes que ya no pertenecen a ningún programa."),
                                      (T("Buscar restos"), self.find_residues)))
        self.res_table.pack(fill="both", expand=True)
        self.res_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.res_table, self.res_info))
        self.res_table.enable_drag(self._table_drag)
        rt = self.res_table
        self.res_table.context_menu([mi(T("Mostrar en el {fm}", fm=FILE_MANAGER), lambda: self._open_node(rt.focused()),
                                        "open", T("Doble clic")),
                                     mi(T("Copiar ruta"), lambda: self._copy_path(rt.focused()), "copy"),
                                     mi(T("Añadir al Colector"), lambda: self._collect_rows(rt, False), "add"),
                                     SEP,
                                     mi(T("Borrar…"), lambda: self._delete_rows(rt), "trash", T("Supr"),
                                        danger=True)])
        self.res_table.tv.bind("<Delete>", lambda e: self._delete_rows(rt))
        self.hint(page, T("Es una estimación: abre cada carpeta y revísala antes de borrar. Por defecto va a la "
                          "Papelera."))

    def load_apps(self):
        def done(apps):
            self.apps = apps
            self._fill_apps()
        self.run_task(T("Leyendo aplicaciones instaladas…"), lambda report: core.list_installed_apps(), done)

    def _fill_apps(self):
        t = self.apps_table
        t.clear()
        for i, a in enumerate(self.apps):
            d = a.install_date
            date = f"{d[6:8]}/{d[4:6]}/{d[0:4]}" if len(d) == 8 and d.isdigit() else ""
            t.add(f"app{i}", [a.name, human(a.size) if a.size else "—", a.publisher, date, a.location],
                  obj=a, sort={"size": a.size, "date": d})
        self.apps_info.configure(text=T("{n} aplicaciones · {size}", n=num(len(self.apps)),
                                         size=human(sum(a.size for a in self.apps))))

    def _measure_apps(self):
        if not self.apps:
            self.alert(T("Primero pulsa «Cargar aplicaciones»."))
            return
        apps = list(self.apps)

        def work(report):
            for a in apps:
                if self.cancel.is_set():
                    break
                if a.location and os.path.isdir(a.location) and core.protection_level(a.location)[0] != core.BLOCK:
                    report(T("Midiendo {name}…", name=a.name))
                    s, _ = core.dir_size(a.location, self.cancel)
                    if s:
                        a.size = s
            apps.sort(key=lambda a: a.size, reverse=True)
            return apps

        def done(apps_):
            self.apps = apps_
            self._fill_apps()
        self.run_task(T("Midiendo carpetas de instalación…"), work, done)

    def _open_app(self):
        a = self.apps_table.focused()
        if a and a.location and os.path.isdir(a.location):
            core.open_in_explorer(a.location)
        elif a:
            self.alert(T("Esta aplicación no indica su carpeta de instalación."))

    def _uninstall(self):
        a = self.apps_table.focused()
        if not a:
            self.alert(T("Selecciona una aplicación de la lista."), T("Ninguna aplicación seleccionada"))
            return
        if core.IS_LINUX:
            if not a.uninstall:
                self.alert(T("No sé cómo desinstalar este paquete."), T("Sin desinstalador"), "warn")
                return
            self.clipboard_clear()
            self.clipboard_append(a.uninstall)
            self.alert(T("Ejecuta este comando en una terminal (ya está copiado):") + f"\n\n{a.uninstall}",
                       T("Desinstalar {name}", name=a.name), "info")
            return
        msg = (T("Se abrirá el desinstalador oficial del programa.") if core.IS_WIN else
               T("La aplicación se moverá a la Papelera. Sus datos en ~/Library aparecerán luego en "
                 "«Posibles restos»."))
        if not self.confirm(T("¿Desinstalar {name}?", name=a.name), msg, T("Desinstalar"), danger=True):
            return
        try:
            core.run_uninstaller(a.uninstall)
            if core.IS_MAC:
                self.apps = [x for x in self.apps if x is not a]
                self._fill_apps()
        except Exception as e:  # noqa: BLE001
            self.alert(str(e), T("No se pudo desinstalar"), "error")

    def find_residues(self):
        def work(report):
            apps = self.apps or core.list_installed_apps()
            return apps, core.find_residues(apps, self.cancel, progress=lambda p: report(T("Revisando {path}", path=p)))

        def done(r):
            apps, residues = r
            if not self.apps:
                self.apps = apps
                self._fill_apps()
            t = self.res_table
            t.clear()
            for x in residues:
                t.add(x.path, [os.path.basename(x.path), human(x.size), x.where, x.path], obj=(x.size, x.path),
                      sort={"size": x.size})
            self.res_info.configure(text=T("{n} carpetas · {size}", n=num(len(residues)),
                                           size=human(sum(x.size for x in residues))))
        self.run_task(T("Buscando restos de programas…"), work, done)

    # =====================================================================
    # Actualizaciones
    # =====================================================================
    @staticmethod
    def _current_version() -> str:
        # DFS_FAKE_VERSION solo afecta a la comprobación (para probar el aviso)
        return os.environ.get("DFS_FAKE_VERSION") or VERSION

    def _build_update_banner(self, main):
        b = ctk.CTkFrame(main, fg_color=C["accent_soft"], corner_radius=14, border_width=1,
                         border_color=C["accent"])
        b.grid(row=0, column=0, sticky="ew", padx=30, pady=(18, 0))
        b.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(b, text="↑", font=F(18, "bold"), width=36, height=36, corner_radius=8,
                     fg_color=C["accent"], text_color="#ffffff").grid(row=0, column=0, rowspan=2, padx=(14, 12),
                                                                      pady=12)
        self.upd_title = ctk.CTkLabel(b, text="", font=F(14, "bold"), text_color=C["text"], anchor="w")
        self.upd_title.grid(row=0, column=1, sticky="sw", pady=(12, 0))
        self.upd_sub = ctk.CTkLabel(b, text="", font=F(12), text_color=C["muted"], anchor="w")
        self.upd_sub.grid(row=1, column=1, sticky="nw", pady=(0, 12))
        acts = ctk.CTkFrame(b, fg_color="transparent")
        acts.grid(row=0, column=2, rowspan=2, padx=14)
        btn(acts, T("Actualizar ahora"), lambda: self._start_update(self._update_info), "primary", width=150
            ).pack(side="left", padx=(0, 8))
        btn(acts, T("Ver novedades"), lambda: self._show_notes(self._update_info), "secondary", width=130
            ).pack(side="left", padx=(0, 4))
        btn(acts, T("Omitir esta versión"), self._skip_update, "ghost", width=150).pack(side="left")
        btn(acts, "✕", lambda: b.grid_remove(), "ghost", width=36).pack(side="left")
        b.grid_remove()
        self.upd_banner = b
        self._update_info = None

    def _check_updates(self, manual=False):
        if getattr(self, "_checking", False):
            return
        self._checking = True
        if manual:
            self.set_status(T("Buscando actualizaciones…"))
        cur = self._current_version()

        def worker():
            info = core.latest_release()
            self.q.put(("update", (info, cur, manual)))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_result(self, info, cur, manual):
        self._checking = False
        if info is None:
            if manual:
                self.set_status(T("Listo"))
                self.alert(T("No se pudo comprobar si hay una versión nueva. Revisa la conexión a Internet e "
                             "inténtalo más tarde."), T("Sin conexión"), "warn")
            return
        newer = core.parse_version(info.version) > core.parse_version(cur)
        if not newer:
            if manual:
                self.set_status(T("Listo"))
                self.alert(T("Tienes la versión {version}, que es la más reciente.", version=VERSION),
                           T("Ya tienes la última versión"), "ok")
            return
        if not info.asset_url:  # p. ej. la build de macOS aún no está: no se avisa hasta que exista
            if manual:
                self.set_status(T("Listo"))
                self.alert(T("Ya hay una versión v{version}, pero su descarga para {os} todavía no "
                             "está lista. Vuelve a mirarlo en un rato.", version=info.version, os=core.OS_NAME),
                           T("Casi lista"), "info")
            return
        if not manual and core.load_settings().get("skip_version") == info.version:
            return
        self._update_info = info
        self.upd_title.configure(text=T("Nueva versión v{version} disponible", version=info.version))
        self.upd_sub.configure(text=T("Tienes la v{version}.", version=cur) + (
            "  " + T("Descarga de {size}, verificada con SHA-256.", size=human(info.asset_size))
            if info.asset_size else ""))
        self.upd_banner.grid()
        if manual:
            self.set_status(T("Hay una versión nueva: v{version}", version=info.version))

    def _skip_update(self):
        if self._update_info:
            s = core.load_settings()
            s["skip_version"] = self._update_info.version
            core.save_settings(s)
        self.upd_banner.grid_remove()
        self.set_status(T("No se volverá a avisar de esta versión. Puedes buscarla con «Buscar actualizaciones»."))

    def _show_notes(self, info):
        if not info:
            return
        d = Dialog(self, T("Novedades de v{version}", version=info.version), width=720, height=520)
        d.header("info", f"Desktop Free Space v{info.version}", T("Lo nuevo en esta versión"))
        d.buttons([(T("Ver en GitHub"), "secondary", "web"), (T("Cerrar"), "primary", None)])
        tb = ctk.CTkTextbox(d.body, font=F(13), fg_color=C["bg"], text_color=C["muted"], border_width=1,
                            border_color=C["border"], corner_radius=12, wrap="word")
        tb.insert("end", info.notes.strip() or T("Esta versión no incluye notas."))
        tb.configure(state="disabled")
        tb.pack(fill="both", expand=True, padx=24, pady=12)
        self.wait_window(d)
        if d.result == "web" and info.html_url:
            self._launch(info.html_url)

    def _start_update(self, info):
        if not info:
            return
        if not core.is_frozen():
            self.alert(T("Estás ejecutando la app desde el código. Actualízala con «git pull»; te abro la página "
                         "de la versión nueva."), T("Actualizar desde el código"))
            if info.html_url:
                self._launch(info.html_url)
            return
        if self.busy:
            self.alert(T("Espera a que termine la tarea actual o cancélala."), T("Tarea en curso"))
            return
        UpdateDialog(self, info)


class UpdateDialog(Dialog):
    """Descarga la versión nueva con barra de progreso, la verifica y la instala al reiniciar."""

    def __init__(self, app, info):
        super().__init__(app, T("Actualizar"), width=560, height=300)
        self.resizable(False, False)
        self.app, self.info = app, info
        self.cancel = threading.Event()
        self.q: queue.Queue = queue.Queue()
        self.path = None
        self.header("info", T("Actualizando a la v{version}", version=info.version),
                    T("Se descarga {name} ({size}) y se comprueba su huella SHA-256.", name=info.asset_name,
                      size=human(info.asset_size)))
        self.bar = ctk.CTkProgressBar(self.body, height=10, corner_radius=5, fg_color=C["track"],
                                      progress_color=C["accent"])
        self.bar.set(0)
        self.bar.pack(fill="x", padx=24, pady=(14, 6))
        self.msg = ctk.CTkLabel(self.body, text=T("Conectando…"), font=F(12), text_color=C["muted"], anchor="w")
        self.msg.pack(fill="x", padx=24)
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(side="bottom", fill="x", padx=24, pady=(8, 22))
        self.go = btn(bar, T("Reiniciar para terminar"), self._restart, "primary", width=200)
        self.go.configure(state="disabled")
        self.go.pack(side="right", padx=(8, 0))
        self.stop = btn(bar, T("Cancelar"), self._cancel, "secondary", width=110)
        self.stop.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        threading.Thread(target=self._download, daemon=True).start()
        self.after(100, self._poll)

    def _download(self):
        try:
            p = core.download_update(self.info, lambda d, t: self.q.put(("prog", (d, t))), self.cancel)
            self.q.put(("ok", p))
        except Exception as e:  # noqa: BLE001
            self.q.put(("err", str(e)))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "prog":
                    d, t = val
                    if t:
                        self.bar.set(d / t)
                    self.msg.configure(text=T("Descargando… {done} de {total}", done=human(d), total=human(t))
                                       if t else T("Descargando… {done}", done=human(d)))
                elif kind == "ok":
                    self.path = val
                    self.bar.set(1)
                    self.msg.configure(text=T("Descarga verificada (SHA-256 correcto). Reinicia para terminar."),
                                       text_color=C["ok"])
                    self.go.configure(state="normal")
                elif kind == "err":
                    self.bar.configure(progress_color=C["bad"])
                    self.msg.configure(text=val, text_color=C["bad"])
                    self.stop.configure(text=T("Cerrar"))
                    return
                elif kind == "applied":
                    self._finish(val)
                    return
        except queue.Empty:
            pass
        try:
            self.after(100, self._poll)
        except tk.TclError:
            pass

    def _cancel(self):
        self.cancel.set()
        self.destroy()

    def _restart(self):
        self.go.configure(state="disabled")
        self.stop.configure(state="disabled")
        self.msg.configure(text=T("Instalando…"), text_color=C["muted"])

        def work():
            try:
                self.q.put(("applied", core.apply_update(self.path)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", T("No se pudo instalar: {err}", err=e)))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _finish(self, how):
        if how == "opened":
            self.destroy()
            if core.IS_LINUX:
                text = T("He abierto el paquete de la versión nueva en el instalador de tu sistema. Pulsa "
                         "«Instalar» (o «Actualizar») y vuelve a abrir la app.")
            else:
                text = T("He abierto el instalador de la versión nueva. Arrastra la app a Aplicaciones para "
                         "terminar y vuelve a abrirla.")
            self.app.alert(text, T("Termina la instalación"))
            return
        if not core.IS_WIN:
            core.relaunch_after_update()
        self.app.destroy()
        os._exit(0)


def _pick_fonts():
    global UI_FONT, ICON_FONT
    probe = tk.Tk()
    probe.withdraw()
    fams = set(tkfont.families(probe))
    probe.destroy()
    cjk = {"zh": ("Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei"),
           "ja": ("Yu Gothic UI", "Meiryo UI", "Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP")
           }.get(i18n.LANG, ())
    UI_FONT = next((f for f in cjk + ("Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", "SF Pro Text",
                                "Helvetica Neue", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans")
                    if f in fams), "TkDefaultFont")
    global MONO_FONT
    MONO_FONT = next((f for f in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono",
                                  "Ubuntu Mono", "DejaVu Sans Mono") if f in fams), "TkFixedFont")
    ICON_FONT = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), None)


def main():
    if core.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DesktopFreeSpace.App")
        except Exception:  # noqa: BLE001
            pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    _pick_fonts()
    app = App()
    base = getattr(sys, "_MEIPASS", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
    ico = os.path.join(base, "icon.ico")
    try:
        if core.IS_WIN and os.path.exists(ico):
            app.iconbitmap(ico)
        elif os.path.exists(os.path.join(base, "icon.png")):
            app._icon_img = tk.PhotoImage(file=os.path.join(base, "icon.png"))
            app.iconphoto(True, app._icon_img)
    except tk.TclError:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
