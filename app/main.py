"""Desktop Free Space: interfaz gráfica para ver y liberar espacio en disco (Windows, macOS y Linux)."""
from __future__ import annotations

import colorsys
import math
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, font as tkfont, ttk

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
from core import human  # noqa: E402

APP_NAME = "Desktop Free Space"
VERSION = "2.5.1"

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
}
RADIUS = 16
CHECK_ON, CHECK_OFF = "☑", "☐"
UI_FONT = "Segoe UI"
MONO_FONT = "Consolas"
FILE_MANAGER = "Explorador" if core.IS_WIN else "Finder" if core.IS_MAC else "gestor de archivos"
ICON_FONT = None
ICONS_MDL2 = {"home": "\uE80F", "clean": "\uE75C", "folder": "\uE8B7", "file": "\uE7C3", "ai": "\uE99A",
              "apps": "\uE71D", "shield": "\uEA18", "trash": "\uE74D", "drive": "\uEDA2", "check": "\uE73E",
              "info": "\uE946", "warn": "\uE7BA", "map": "\uE81E", "list": "\uE8FD", "copy": "\uE8C8"}
ICONS_FALLBACK = {"home": "⌂", "clean": "✦", "folder": "▤", "file": "▦", "ai": "◈", "apps": "▣", "shield": "⛨",
                  "trash": "✕", "drive": "◉", "check": "✓", "info": "i", "warn": "!", "map": "◔", "list": "≡",
                  "copy": "⧉"}


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
    return ctk.CTkButton(master, text=text, command=command, corner_radius=10, height=36, font=F(13, "bold"),
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
# Tabla (Treeview oscuro, orden por columnas y casillas)
# ---------------------------------------------------------------------------
class Table(ctk.CTkFrame):
    def __init__(self, master, columns, checkable=False, tree=False, height=14, on_open=None, on_select=None,
                 empty_text=""):
        super().__init__(master, fg_color=C["surface"], corner_radius=RADIUS, border_width=1,
                         border_color=C["border"])
        self.checkable = checkable
        self.checked: set[str] = set()
        self.data: dict[str, object] = {}
        self.sort_keys: dict[str, dict[str, object]] = {}
        ids = [c[0] for c in columns]
        self.titles = {c[0]: c[1] for c in columns}
        self.tv = ttk.Treeview(self, columns=ids, show="tree headings" if tree else "headings",
                               height=height, selectmode="extended", style="Dark.Treeview")
        if tree:
            self.tv.column("#0", width=340, stretch=True)
            self.tv.heading("#0", text="CARPETA", anchor="w")
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
        self.tv.tag_configure("odd", background=C["odd"])
        self.tv.tag_configure("warn", foreground=C["warn"])
        self.tv.tag_configure("muted", foreground=C["faint"])
        self.tv.tag_configure("checked", background=C["accent_soft"])
        self.empty = ctk.CTkLabel(self, text=empty_text, text_color=C["faint"], font=F(13), fg_color=C["surface"])
        self._update_empty()
        if checkable:
            self.tv.bind("<Button-1>", self._on_click, add="+")
            self.tv.bind("<space>", self._on_space, add="+")
        if on_open:
            self.tv.bind("<Double-1>", lambda e: on_open(self.focused()), add="+")
        if on_select:
            self.tv.bind("<<TreeviewSelect>>", lambda e: on_select(self.focused()), add="+")
        self._sort_state: dict[str, bool] = {}

    def _update_empty(self):
        if not self.empty.cget("text"):
            return
        if self.tv.get_children():
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

    def clear(self):
        self.tv.delete(*self.tv.get_children())
        self.checked.clear()
        self.data.clear()
        self.sort_keys.clear()
        self._update_empty()

    def add(self, key, values, obj=None, sort=None, tags=(), parent="", text="", checked=False):
        vals = list(values)
        if self.checkable:
            vals[0] = (CHECK_ON if checked else CHECK_OFF) + "   " + str(vals[0])
            if checked:
                self.checked.add(key)
        n = len(self.tv.get_children(parent))
        t = tuple(tags) + (("odd",) if n % 2 else ()) + (("checked",) if checked else ())
        self.tv.insert(parent, "end", iid=key, values=vals, text=text, tags=t)
        self.data[key] = obj
        self.sort_keys[key] = sort or {}
        if not parent:
            self._update_empty()
        return key

    def focused(self):
        f = self.tv.focus()
        return self.data.get(f) if f else None

    def selected(self):
        return [self.data[i] for i in self.tv.selection() if i in self.data]

    def checked_objs(self):
        return [self.data[k] for k in list(self.checked) if k in self.data]

    def set_checked(self, key, on):
        vals = list(self.tv.item(key, "values"))
        if not vals:
            return
        vals[0] = (CHECK_ON if on else CHECK_OFF) + "   " + str(vals[0])[4:]
        tags = [t for t in self.tv.item(key, "tags") if t != "checked"] + (["checked"] if on else [])
        self.tv.item(key, values=vals, tags=tags)
        (self.checked.add if on else self.checked.discard)(key)

    def toggle(self, key):
        self.set_checked(key, key not in self.checked)
        self.event_generate("<<CheckChanged>>")

    def check_all(self, on=True):
        for k in self.tv.get_children():
            self.set_checked(k, on)
        self.event_generate("<<CheckChanged>>")

    def _on_click(self, e):
        if self.tv.identify_region(e.x, e.y) != "cell" or self.tv.identify_column(e.x) != "#1":
            return
        row = self.tv.identify_row(e.y)
        if row:
            self.toggle(row)
            return "break"

    def _on_space(self, _e):
        for k in self.tv.selection():
            self.toggle(k)
        return "break"

    def sort_by(self, col):
        prev = self._sort_state.get(col)
        rev = (not prev) if prev is not None else col in ("size", "files", "pct", "date")
        self._sort_state = {col: rev}
        items = list(self.tv.get_children(""))

        def key(k):
            sk = self.sort_keys.get(k, {})
            if col in sk:
                return sk[col]
            return str(self.tv.set(k, col)).lstrip(CHECK_ON + CHECK_OFF + " ").lower()
        items.sort(key=key, reverse=rev)
        for i, k in enumerate(items):
            self.tv.move(k, "", i)
            tags = [t for t in self.tv.item(k, "tags") if t != "odd"] + (["odd"] if i % 2 else [])
            self.tv.item(k, tags=tags)
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

    def context_menu(self, items):
        menu = tk.Menu(self.tv, tearoff=0, bg=C["surface2"], fg=C["text"], activebackground=C["accent"],
                       activeforeground="#ffffff", bd=0, relief="flat", font=(UI_FONT, 10))
        for label, fn in items:
            if label == "-":
                menu.add_separator()
            else:
                menu.add_command(label="  " + label + "    ", command=fn)

        def popup(e):
            row = self.tv.identify_row(e.y)
            if row:
                if row not in self.tv.selection():
                    self.tv.selection_set(row)
                self.tv.focus(row)
                menu.tk_popup(e.x_root, e.y_root)
        self.tv.bind("<Button-3>", popup, add="+")
        if core.IS_MAC:
            self.tv.bind("<Button-2>", popup, add="+")
            self.tv.bind("<Control-Button-1>", popup, add="+")


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
        self.header("danger", f"Vas a borrar {len(items)} elementos · {human(total)}", note)
        box = ctk.CTkTextbox(self.body, font=ctk.CTkFont(family=MONO_FONT, size=12), fg_color=C["bg"],
                             text_color=C["muted"], border_width=1, border_color=C["border"], corner_radius=10)
        for p, s in items[:2000]:
            box.insert("end", f"{human(s):>10}   {p}\n")
        if len(items) > 2000:
            box.insert("end", f"… y {len(items) - 2000} más\n")
        box.configure(state="disabled")
        self.mode = tk.StringVar(value="perm" if default_permanent else "recycle")
        self.buttons([("Cancelar", "secondary", None), ("Borrar", "danger_solid", "ok")])
        opts = ctk.CTkFrame(self.body, fg_color="transparent")
        opts.pack(side="bottom", fill="x", padx=24)
        for val, t1, t2 in (("recycle", "Enviar a la Papelera", "Recuperable. El espacio se libera al vaciarla."),
                            ("perm", "Eliminar definitivamente", "Libera el espacio al momento. No se puede deshacer.")):
            row = ctk.CTkFrame(opts, fg_color=C["surface2"], corner_radius=10)
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
PAGES = [("summary", "Discos", "home"), ("analyzer", "Mapa del disco", "map"), ("kinds", "Tipos de archivo", "list"),
         ("clean", "Limpieza", "clean"), ("big", "Archivos grandes", "file"), ("dups", "Duplicados", "copy"),
         ("models", "Modelos IA", "ai"), ("apps", "Aplicaciones", "apps")]
EMPTY_SCAN = "Analiza un disco o una carpeta en «Mapa del disco» para ver aquí sus datos"

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
    def start_scanning(self, text=""):
        self.scan_text = text
        if self._spin is None:
            self._spin_tick()

    def stop_scanning(self):
        if self._spin is not None:
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
        self.create_text(cx, cy - 12, text="Analizando…", fill=C["text"], font=(UI_FONT, 15, "bold"))
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
                                  "Archivos pequeños", rest, "small"])

        walk(node, 1, 0.0, 360.0 * node.size / total)
        if hidden:
            self.segs.append([1, 360.0 * node.size / total, 360.0, None, HIDDEN_COLOR, "Espacio oculto", hidden,
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
            self.create_text(cx, cy - 10, text="Elige un disco o una carpeta", fill=C["text"],
                             font=(UI_FONT, 15, "bold"))
            self.create_text(cx, cy + 16, text="y pulsa «Analizar» para ver su mapa", fill=C["muted"],
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
                sub += f" · {seg[3].files:,} archivos".replace(",", ".")
            elif seg[7] == "hidden":
                sub = "sistema, sin permisos, instantáneas…"
            self._center_text(seg[5], human(size), sub)
        else:
            self._center_text(n.name, human(n.size), "↑ subir" if self.history else
                              f"{n.files:,} archivos".replace(",", "."))

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
        if self.root_node is None or self._dragging:
            return
        seg = self._hit(e.x, e.y)
        if seg is not self.hover_seg:
            self._set_hover(seg)

    def _b1_down(self, e):
        self._press = (e.x, e.y)
        self._dragging = False

    def _b1_move(self, e):
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
        st.configure("Dark.Treeview", background=C["surface"], fieldbackground=C["surface"], foreground=C["text"],
                     rowheight=int(34 * k), borderwidth=0, relief="flat", font=(UI_FONT, 10), indent=int(18 * k))
        st.configure("Dark.Treeview.Heading", background=C["surface"], foreground=C["faint"], relief="flat",
                     borderwidth=0, font=(UI_FONT, 9, "bold"), padding=(8, int(8 * k)))
        st.map("Dark.Treeview", background=[("selected", C["sel"])], foreground=[("selected", "#ffffff")])
        st.map("Dark.Treeview.Heading", background=[("active", C["surface2"])], foreground=[("active", C["text"])])
        st.configure("Treeitem.indicator", foreground=C["muted"])

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
        ctk.CTkLabel(lt, text=f"Gestor de espacio · v{VERSION}", font=F(11), text_color=C["faint"]).pack(anchor="w")
        ctk.CTkLabel(side, text="MENÚ", font=F(10, "bold"), text_color=C["faint"]).pack(anchor="w", padx=26, pady=(0, 6))
        for key, label, ico in PAGES:
            b = ctk.CTkButton(side, text=f"          {label}", anchor="w", height=42, corner_radius=10,
                              font=F(13, "bold"), fg_color="transparent", hover_color=C["hover"],
                              text_color=C["muted"], command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            ic = ctk.CTkLabel(b, text=icon(ico), font=IF(15), fg_color="transparent", text_color=C["muted"],
                              width=22, height=22)
            ic.place(x=16, rely=0.5, anchor="w")
            ic.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.nav[key] = (b, ic)
        # tarjeta de permisos / sistema
        adm = ctk.CTkFrame(side, fg_color=C["surface"], corner_radius=12, border_width=1, border_color=C["border"])
        adm.pack(side="bottom", fill="x", padx=14, pady=(8, 18))
        is_admin = core.is_admin()
        hdr = ctk.CTkFrame(adm, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(hdr, text=icon("shield"), font=IF(14), text_color=C["ok"] if is_admin else C["warn"]
                     ).pack(side="left")
        ctk.CTkLabel(hdr, text=f"{core.OS_NAME} · " + ("Administrador" if is_admin else "Modo estándar"),
                     font=F(12, "bold"), text_color=C["text"]).pack(side="left", padx=8)
        if core.IS_WIN:
            tip = ("Puedes limpiar también las carpetas de Windows." if is_admin else
                   "Para limpiar Windows Temp y Windows Update hacen falta permisos.")
        else:
            tip = "Limpia lo de tu usuario. Lo del sistema necesita sudo." if not is_admin else "Ejecutando como root."
        ctk.CTkLabel(adm, text=tip, font=F(11), text_color=C["muted"], wraplength=186, justify="left"
                     ).pack(anchor="w", padx=14, pady=(4, 12))
        if core.IS_WIN and not is_admin:
            btn(adm, "Reiniciar como admin", self._relaunch_admin, "secondary").pack(fill="x", padx=12, pady=(0, 6))
        upd = ctk.CTkButton(adm, text="Buscar actualizaciones", command=lambda: self._check_updates(manual=True),
                            height=28, corner_radius=8, font=F(12, "bold"), **BTN_STYLES["ghost"])
        upd.pack(fill="x", padx=8, pady=(0, 10))

        # Colector
        col = ctk.CTkFrame(side, fg_color=C["surface"], corner_radius=14, border_width=2, border_color=C["accent_soft"])
        self.col_frame = col
        col.pack(side="bottom", fill="x", padx=14, pady=(8, 0))
        ch = ctk.CTkFrame(col, fg_color="transparent")
        ch.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(ch, text="Colector", font=F(13, "bold"), text_color=C["text"]).pack(side="left")
        self.col_count = ctk.CTkLabel(ch, text="0", font=F(11, "bold"), text_color="#ffffff", width=26, height=20,
                                      corner_radius=10, fg_color=C["surface2"])
        self.col_count.pack(side="right")
        self.col_label = ctk.CTkLabel(col, text="", font=F(11), text_color=C["muted"], wraplength=186,
                                      justify="left", anchor="w")
        self.col_label.pack(fill="x", padx=14, pady=(2, 8))
        cb = ctk.CTkFrame(col, fg_color="transparent")
        cb.pack(fill="x", padx=10, pady=(0, 12))
        self.col_del = btn(cb, "Revisar y borrar", self._collector_review, "danger_solid", width=120)
        self.col_del.pack(side="left", fill="x", expand=True)
        self.col_view = btn(cb, "Vaciar", self._collector_clear, "ghost", width=60)
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
        self.status = ctk.CTkLabel(foot, text="Listo", anchor="w", font=F(12), text_color=C["muted"])
        self.status.grid(row=0, column=1, sticky="ew")
        self.progress = ctk.CTkProgressBar(foot, mode="determinate", width=200, height=4, corner_radius=2,
                                           fg_color=C["surface2"], progress_color=C["accent"])
        self.progress.set(0)
        self.progress.grid(row=0, column=2, padx=12)
        self.cancel_btn = btn(foot, "Cancelar", self.cancel.set, "ghost", width=90)
        self.cancel_btn.grid(row=0, column=3)
        self.cancel_btn.grid_remove()
        self.progress.grid_remove()
        self._update_collector()

    def show(self, key):
        self.pages[key].tkraise()
        for k, (b, ic) in self.nav.items():
            on = k == key
            b.configure(fg_color=C["accent_soft"] if on else "transparent", text_color=C["text"] if on else C["muted"])
            ic.configure(text_color=C["accent"] if on else C["muted"], fg_color=C["accent_soft"] if on else C["side"])

    def page_header(self, page, title, subtitle):
        h = ctk.CTkFrame(page, fg_color="transparent")
        h.pack(fill="x", pady=(0, 18))
        tf = ctk.CTkFrame(h, fg_color="transparent")
        tf.pack(side="left")
        ctk.CTkLabel(tf, text=title, font=F(26, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(tf, text=subtitle, font=F(13), text_color=C["muted"]).pack(anchor="w", pady=(2, 0))
        actions = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        actions.pack(side="right", anchor="s")
        return actions

    def hint(self, page, text):
        ctk.CTkLabel(page, text=text, font=F(12), text_color=C["faint"], anchor="w", justify="left",
                     wraplength=1000).pack(fill="x", pady=(10, 0))

    def section(self, page, title, sub="", pady=(0, 8)):
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=pady)
        ctk.CTkLabel(row, text=title, font=F(15, "bold"), text_color=C["text"]).pack(side="left")
        info = ctk.CTkLabel(row, text=sub, font=F(12), text_color=C["muted"])
        info.pack(side="left", padx=12)
        return row, info

    # ---------- diálogos ----------
    def alert(self, text, title="Aviso", kind="info"):
        Dialog.show(self, kind, title, text, [("Entendido", "primary", True)])

    def confirm(self, title, text, ok="Aceptar", danger=False):
        return Dialog.show(self, "danger" if danger else "ask", title, text,
                           [("Cancelar", "secondary", False), (ok, "danger_solid" if danger else "primary", True)]
                           ) is True

    # ---------- tareas en segundo plano ----------
    def run_task(self, label, fn, done=None, on_error=None):
        if self.busy:
            self.alert("Espera a que termine la tarea actual o cancélala.", "Tarea en curso")
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
                    self.sun.scan_text = payload
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
                        self.set_status(f"Error: {err}")
                        self.alert(f"Ha ocurrido un error:\n{err}", "Error", "error")
                    else:
                        self.dot.configure(text_color=C["warn"] if self.cancel.is_set() else C["ok"])
                        self.set_status("Cancelado" if self.cancel.is_set() else "Listo")
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
        msg = f"{res.deleted:,} archivos borrados.".replace(",", ".")
        if not permanent and res.freed:
            msg += "\nEstán en la Papelera: el espacio se libera al vaciarla."
        kind = "ok"
        if res.failed:
            kind = "warn"
            msg += f"\n{res.failed} elementos no se pudieron borrar (estaban en uso o sin permisos)."
            if res.errors:
                msg += "\n\n" + "\n".join(e if len(e) < 90 else "…" + e[-88:] for e in res.errors[:4])
        Dialog.show(self, kind, f"Has liberado {human(res.freed)}", msg, [("Perfecto", "primary", True)])
        self.refresh_summary()

    def _launch(self, target):
        try:
            core.launch(target)
        except Exception as e:  # noqa: BLE001
            self.alert(str(e), "No se pudo abrir", "error")

    def _relaunch_admin(self):
        if core.relaunch_as_admin():
            self.destroy()

    # =====================================================================
    # Resumen
    # =====================================================================
    def _build_summary(self, page):
        actions = self.page_header(page, "Discos", "Estado de tus discos y por dónde empezar a liberar espacio")
        btn(actions, "Actualizar", self.refresh_summary, "secondary", width=110).pack(side="right")
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
        ctk.CTkLabel(t, text=sub, font=F(12), text_color=C["muted"], wraplength=300, justify="left"
                     ).pack(anchor="w", padx=22, pady=(2, 14 if action else 22))
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
            ring.draw(sysdrive.pct, f"{sysdrive.pct * 100:.0f}%", "en uso")
            ctk.CTkLabel(hero, text=f"DISCO DEL SISTEMA  ·  {sysdrive.path}", font=F(11, "bold"),
                         text_color=C["faint"]).grid(row=0, column=1, sticky="sw", pady=(36, 0))
            big = ctk.CTkLabel(hero, text=f"{human(sysdrive.free)} libres", font=F(40, "bold"), text_color=C["text"])
            big.grid(row=1, column=1, sticky="w")
            bar = self._bar(hero, sysdrive.pct, 10)
            bar.grid(row=2, column=1, sticky="ew", pady=(10, 8))
            info = ctk.CTkLabel(hero, text="", font=F(12), text_color=C["muted"])
            info.grid(row=3, column=1, sticky="nw", pady=(0, 30))
            acts = ctk.CTkFrame(hero, fg_color="transparent")
            acts.grid(row=0, column=2, rowspan=4, padx=30)
            for text, cmd, kind, cap in (
                    ("Limpiar temporales y cachés", lambda: (self.show("clean"), self.scan_categories()), "primary",
                     "Calcula lo que se puede borrar sin riesgo"),
                    ("Ver qué ocupa espacio", lambda p=sysdrive.path: self.start_scan(p), "secondary",
                     "Mapa de todas las carpetas y archivos del disco")):
                btn(acts, text, cmd, kind, width=250).pack(anchor="w", pady=(8, 0))
                ctk.CTkLabel(acts, text=cap, font=F(11), text_color=C["muted"], height=18, anchor="w"
                             ).pack(anchor="w", padx=4, pady=(3, 6))
            self._drive_rows.append((sysdrive.path, ring, big, bar, info, True))

        freed, since = core.freed_stats()
        y, m, d = (since.split("-") + ["", "", ""])[:3]
        months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        try:
            since_txt = f"{int(d)} {months[int(m) - 1]} {y}"
        except (ValueError, IndexError):
            since_txt = since
        fb = ctk.CTkFrame(body, fg_color=C["surface"], corner_radius=14, border_width=1, border_color=C["border"])
        fb.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(fb, text="✦", font=F(18, "bold"), text_color=C["accent"], width=24).pack(side="left", padx=(22, 8),
                                                                                             pady=16)
        ctk.CTkLabel(fb, text=f"{human(freed)} liberados" if freed else "Aún no has liberado espacio",
                     font=F(18, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(fb, text=f"con Desktop Free Space desde el {since_txt}", font=F(13), text_color=C["muted"]
                     ).pack(side="left", padx=10)

        size, n = core.recycle_bin_size()
        self._tile(body, 0, "Papelera de reciclaje" if core.IS_WIN else "Papelera", human(size),
                   f"{n} elementos · ocupan espacio hasta vaciarla", ("Vaciar", self._empty_bin) if size else None,
                   "danger", dot=C["bad"])
        scanned = [c for c in self.categories if getattr(c, "_scanned", False)]
        if scanned:
            safe = sum(c.size for c in scanned if c.risk == core.SAFE)
            rev = sum(c.size for c in scanned if c.risk == core.REVIEW)
            self._tile(body, 1, "Recuperable", human(safe + rev), f"{human(safe)} seguro · {human(rev)} a revisar",
                       ("Ir a Limpieza", lambda: self.show("clean")), dot=C["ok"])
        else:
            self._tile(body, 1, "Recuperable", "—", "Temporales, cachés y modelos de IA sin calcular",
                       ("Calcular", lambda: (self.show("clean"), self.scan_categories())), dot=C["ok"])
        sysfiles = core.system_files_info()
        snaps = core.local_snapshots()
        sub = " · ".join(f"{os.path.basename(p)} {human(s)}" for _l, p, s, _t in sysfiles) or \
            "Hibernación y memoria virtual"
        if snaps:
            sub += f" · {len(snaps)} instantáneas locales de Time Machine"
        self._tile(body, 2, "Archivos del sistema", human(sum(x[2] for x in sysfiles)) if sysfiles else "—", sub,
                   dot=C["accent2"])
        row = 3
        others = [d for d in drives if d is not sysdrive]
        if others:
            ctk.CTkLabel(body, text="Otros discos", font=F(15, "bold"), text_color=C["text"]
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
                btn(dc, "Analizar", lambda p=d.path: self.start_scan(p), "secondary", width=100
                    ).grid(row=0, column=2, rowspan=2, padx=18)
                self._drive_rows.append((d.path, ring, None, bar, info, False))
                row += 1
        tools = core.system_tools()
        if tools:
            ctk.CTkLabel(body, text=f"Herramientas de {core.OS_NAME}", font=F(15, "bold"), text_color=C["text"]
                         ).grid(row=row, column=0, sticky="w", pady=(10, 10))
            row += 1
        for i, (t1, t2, target) in enumerate(tools):
            t = card(body)
            t.grid(row=row, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            ctk.CTkLabel(t, text=t1, font=F(13, "bold"), text_color=C["text"]).pack(anchor="w", padx=22, pady=(18, 0))
            ctk.CTkLabel(t, text=t2, font=F(12), text_color=C["muted"]).pack(anchor="w", padx=22)
            btn(t, "Abrir  ↗", lambda x=target: self._launch(x), "ghost", width=80).pack(anchor="w", padx=12,
                                                                                         pady=(6, 14))
        tips = [tip for _l, _p, _s, tip in sysfiles if "powercfg" in tip or "pmset" in tip]
        if snaps:
            tips.append("macOS borra las instantáneas locales solo cuando falta espacio. Para quitarlas ya: "
                        "tmutil deletelocalsnapshots /")
        if tips:
            row += 1
            ctk.CTkLabel(body, text="Consejo: " + tips[0], font=F(12), text_color=C["faint"]
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
                        ring.draw(pct, f"{pct * 100:.0f}%", "en uso" if is_sys else "")
                        ring._pct = pct
                    bar.set(pct)
                    bar.configure(progress_color=level_color(pct) if pct >= 0.75 else C["accent"])
                    if big is not None:
                        big.configure(text=f"{human(u.free)} libres")
                        info.configure(text=f"Usado {human(u.used)}  ·  Capacidad {human(u.total)}")
                    else:
                        info.configure(text=f"{human(u.free)} libres de {human(u.total)}")
                except (OSError, tk.TclError):
                    pass
        else:
            self.after(10, lambda: self._live_drives())
            return
        self._live_job = self.after(4000, self._live_drives)

    def _empty_bin(self):
        size, n = core.recycle_bin_size()
        if self.confirm("¿Vaciar la Papelera?", f"{human(size)} en {n} elementos. No se podrá recuperar.",
                        "Vaciar", danger=True):
            core.empty_recycle_bin()
            after, _n = core.recycle_bin_size()
            core.add_freed(max(0, size - after))
            self.refresh_summary()

    # =====================================================================
    # Limpieza
    # =====================================================================
    def _build_clean(self, page):
        actions = self.page_header(page, "Limpieza", "Temporales, cachés y modelos que se pueden borrar sin romper nada")
        btn(actions, "Limpiar seleccionadas", self.clean_selected, "danger_solid", width=190).pack(side="right")
        btn(actions, "Calcular espacio", self.scan_categories, "primary", width=150).pack(side="right", padx=8)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        self.cat_filter = ctk.CTkSegmentedButton(
            bar, values=["Todas", "Sistema", "Navegadores", "Desarrollo", "IA / Modelos"],
            command=lambda _v: self._fill_categories(), font=F(12, "bold"), height=34, corner_radius=10,
            fg_color=C["surface"], selected_color=C["accent"], selected_hover_color=C["accent_h"],
            unselected_color=C["surface"], unselected_hover_color=C["hover"], text_color=C["text"])
        self.cat_filter.set("Todas")
        self.cat_filter.pack(side="left")
        btn(bar, "Marcar las seguras", self._check_safe, "ghost", width=150).pack(side="left", padx=(12, 0))
        btn(bar, "Desmarcar", lambda: self.cat_table.check_all(False), "ghost", width=100).pack(side="left")
        self.cat_total = ctk.CTkLabel(bar, text="", font=F(13, "bold"), text_color=C["accent"])
        self.cat_total.pack(side="right")
        self.cat_table = Table(page, [("name", "CATEGORÍA", 360, "w"), ("group", "GRUPO", 130, "w"),
                                      ("size", "TAMAÑO", 110, "e"), ("files", "ARCHIVOS", 100, "e"),
                                      ("risk", "NIVEL", 110, "center")],
                               checkable=True, height=13, on_select=self._show_cat)
        self.cat_table.pack(fill="both", expand=True)
        self.cat_table.bind("<<CheckChanged>>", lambda e: self._update_cat_total())
        self.cat_table.context_menu([("Abrir carpeta", self._open_cat), ("Ver qué se borraría", self._preview_cat)])
        det = card(page)
        det.pack(fill="x", pady=(12, 0))
        self.cat_title = ctk.CTkLabel(det, text="Pulsa «Calcular espacio» para empezar", font=F(14, "bold"),
                                      text_color=C["text"], anchor="w")
        self.cat_title.pack(fill="x", padx=22, pady=(16, 0))
        self.cat_detail = ctk.CTkLabel(det, text="«Seguro»: se regenera solo.   «Revisar»: tendrías que volver a "
                                                 "descargarlo.   Selecciona una fila para ver qué contiene.",
                                       font=F(12), text_color=C["muted"], anchor="w", justify="left", wraplength=1000)
        self.cat_detail.pack(fill="x", padx=22, pady=(2, 16))
        self._fill_categories()

    def _fill_categories(self):
        t = self.cat_table
        keep = set(t.checked)
        t.clear()
        grp = self.cat_filter.get()
        cats = [c for c in self.categories if grp == "Todas" or c.group == grp]
        if any(getattr(c, "_scanned", False) for c in cats):
            cats.sort(key=lambda c: c.size, reverse=True)
        for c in cats:
            scanned = getattr(c, "_scanned", False)
            tags = ("muted",) if scanned and c.size == 0 else ("warn",) if c.risk == core.REVIEW else ()
            t.add(c.id, [c.name, c.group, human(c.size) if scanned else "—",
                         f"{c.files:,}".replace(",", ".") if scanned else "",
                         "●  Seguro" if c.risk == core.SAFE else "●  Revisar"],
                  obj=c, sort={"size": c.size, "files": c.files}, tags=tags, checked=c.id in keep)
        self._update_cat_total()

    def _update_cat_total(self):
        sel = [c for c in self.categories if c.id in self.cat_table.checked]
        self.cat_total.configure(text=f"Seleccionado: {human(sum(c.size for c in sel))}" if sel else "")

    def _show_cat(self, c):
        if not c:
            return
        extra = []
        if c.admin and not core.is_admin():
            extra.append("Necesita ejecutar la app como administrador.")
        if c.close_apps:
            extra.append(f"Cierra {c.close_apps} antes de limpiar.")
        if c.risk == core.REVIEW:
            extra.append("Revisa antes de borrar: tendrías que volver a descargarlo.")
        where = "   ·   ".join(c.targets[:3]) if c.targets else "No existe en este PC o falta calcular."
        self.cat_title.configure(text=c.name + (f"  ·  {human(c.size)}" if getattr(c, "_scanned", False) else ""))
        self.cat_detail.configure(text=f"{c.description} {' '.join(extra)}\n{where}")

    def _check_safe(self):
        if not any(getattr(c, "_scanned", False) for c in self.categories):
            self.alert("Primero pulsa «Calcular espacio».")
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
                report(f"Calculando {c.name}…")
                core.scan_category(c, self.cancel)
                c._scanned = True  # type: ignore[attr-defined]
            return cats

        def done(_):
            self._fill_categories()
            total = sum(c.size for c in cats)
            safe = sum(c.size for c in cats if c.risk == core.SAFE)
            self.set_status(f"Recuperable: {human(total)} · seguro: {human(safe)}")
            self.refresh_summary()
        self.run_task("Calculando categorías…", work, done)

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
                report(f"Midiendo {p}")
                items.append((p, core.dir_size(p, self.cancel)[0]))
            items.sort(key=lambda x: x[1], reverse=True)
            return items

        def done(items):
            d = Dialog(self, c.name, width=840, height=580)
            d.header("info", c.name, f"{len(items)} elementos · {human(sum(s for _, s in items))}")
            d.buttons([("Cerrar", "primary", None)])
            box = ctk.CTkTextbox(d.body, font=ctk.CTkFont(family=MONO_FONT, size=12), fg_color=C["bg"],
                                 text_color=C["muted"], border_width=1, border_color=C["border"], corner_radius=10)
            box.pack(fill="both", expand=True, padx=24, pady=12)
            for p, s in items:
                box.insert("end", f"{human(s):>10}   {p}\n")
            if not items:
                box.insert("end", "No hay nada que borrar aquí.")
            box.configure(state="disabled")
        self.run_task(f"Revisando {c.name}…", work, done)

    def clean_selected(self):
        cats = [c for c in self.categories if c.id in self.cat_table.checked]
        if not cats:
            self.alert("Marca al menos una categoría haciendo clic en su casilla.", "Nada seleccionado")
            return
        if any(not getattr(c, "_scanned", False) for c in cats):
            self.alert("Primero pulsa «Calcular espacio».")
            return
        need_admin = [c.name for c in cats if c.admin and not core.is_admin()]
        items = [(f"[{c.name}]  {t}", c.target_sizes.get(t, 0)) for c in cats for t in c.targets]
        note = "Se borra el contenido de estas carpetas. Lo que esté en uso se salta."
        apps = sorted({c.close_apps for c in cats if c.close_apps})
        if apps:
            note += f" Cierra antes: {', '.join(apps)}."
        if need_admin:
            note += f"\nSin permisos de administrador no se limpiará: {', '.join(need_admin)}."
        if any(c.risk == core.REVIEW for c in cats):
            note += "\nIncluye categorías «Revisar»: tendrías que volver a descargarlas."
        perm = ConfirmDelete.ask(self, "Confirmar limpieza", items, note, default_permanent=True)
        if perm is None:
            return

        def work(report):
            total = core.DeleteResult()
            for c in cats:
                if self.cancel.is_set():
                    break
                report(f"Limpiando {c.name}…")
                total.merge(core.clean_category(c, perm))
                core.scan_category(c)
            return total

        def done(res):
            self._fill_categories()
            self.after_delete(res, perm)
        self.run_task("Limpiando…", work, done)

    # =====================================================================
    # Mapa del disco (sunburst + lista + migas de pan)
    # =====================================================================
    def _build_analyzer(self, page):
        actions = self.page_header(page, "Mapa del disco", "Pasa el ratón por los anillos y haz clic para entrar en una carpeta")
        self.scan_info = ctk.CTkLabel(actions, text="", font=F(13, "bold"), text_color=C["accent"])
        self.scan_info.pack(side="right")
        bar = card(page)
        bar.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=12)
        self.scan_path = ctk.CTkEntry(inner, height=38, corner_radius=10, font=F(13), fg_color=C["bg"],
                                      border_color=C["border"], text_color=C["text"])
        self.scan_path.insert(0, core.SYSDRIVE if core.IS_WIN else core.HOME)
        self.scan_path.pack(side="left", fill="x", expand=True)
        btn(inner, "Examinar…", self._pick_folder, "secondary", width=110).pack(side="left", padx=8)
        btn(inner, "Mi usuario", lambda: self.start_scan(core.HOME), "secondary", width=110).pack(side="left")
        btn(inner, "Analizar", lambda: self.start_scan(self.scan_path.get()), "primary", width=120
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
        self.sun.pack(fill="both", expand=True, padx=10, pady=10)
        self.map_hover = ctk.CTkLabel(mcard, text="Clic en un anillo para entrar · clic en el centro para subir · "
                                                  "arrastra al Colector", font=F(12), text_color=C["faint"],
                                      anchor="w")
        self.map_hover.pack(fill="x", padx=16, pady=(0, 12))

        side = ctk.CTkFrame(body, fg_color="transparent")
        side.grid(row=0, column=1, sticky="nsew")
        hdr = ctk.CTkFrame(side, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 8))
        self.map_title = ctk.CTkLabel(hdr, text="Contenido", font=F(15, "bold"), text_color=C["text"], anchor="w")
        self.map_title.pack(side="left")
        btn(hdr, "↑ Subir", lambda: self.sun.up(), "ghost", width=80).pack(side="right")
        self.map_list = Table(side, [("name", "NOMBRE", 220, "w"), ("bar", "", 150, "w"), ("size", "TAMAÑO", 90, "e")],
                              height=14, on_open=self._map_open_row,
                              empty_text="Analiza un disco o una carpeta para ver su mapa")
        self.map_list.pack(fill="both", expand=True)
        self.map_list.context_menu([("Entrar / abrir", lambda: self._map_open_row(self.map_list.focused())),
                                    ("Vista previa   (Espacio)", lambda: self.preview(self.map_list.focused())),
                                    ("Añadir al Colector", lambda: self._collect_nodes(self.map_list.selected())),
                                    ("Mostrar en el " + FILE_MANAGER, lambda: self._open_node(self.map_list.focused())),
                                    ("Copiar ruta", lambda: self._copy_path(self.map_list.focused())), ("-", None),
                                    ("Borrar…", lambda: self._delete_nodes(self.map_list.selected()))])
        self.map_list.tv.bind("<space>", lambda e: (self.preview(self.map_list.focused()), "break")[1])
        self.map_list.tv.bind("<BackSpace>", lambda e: self.sun.up())
        self.map_list.enable_drag(self._table_drag)
        acts = ctk.CTkFrame(side, fg_color="transparent")
        acts.pack(fill="x", pady=(10, 0))
        btn(acts, "Añadir al Colector", lambda: self._collect_nodes(self.map_list.selected()), "primary"
            ).pack(side="left")
        btn(acts, "Vista previa", lambda: self.preview(self.map_list.focused()), "secondary", width=110
            ).pack(side="left", padx=8)
        btn(acts, "Exportar CSV", self._export_csv, "ghost", width=110).pack(side="right")

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
            self.alert(f"No existe la carpeta:\n{path}", "Carpeta no encontrada", "error")
            return
        if self.busy:
            self.alert("Espera a que termine la tarea actual o cancélala.", "Tarea en curso")
            return
        self.scan_path.delete(0, "end")
        self.scan_path.insert(0, path)
        self.show("analyzer")
        self.sun.start_scanning("Preparando…")

        def work(report):
            def prog(n, b, p):
                self.q.put(("scan", f"{n:,} archivos · {human(b)}".replace(",", ".")))
                report(f"Analizando · {n:,} archivos · {human(b)} · {p}")
            return core.scan_tree(path, self.cancel, prog)

        def done(res: core.ScanResult | None):
            self.sun.stop_scanning()
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
            txt = f"{human(r.size)} en {r.files:,} archivos".replace(",", ".")
            if hidden:
                txt += f"  ·  {human(hidden)} ocultos"
            self.scan_info.configure(text=txt + (" (parcial)" if self.cancel.is_set() else ""))
        self.run_task(f"Analizando {path}…", work, done, on_error=lambda: (self.sun.stop_scanning(),
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
            rows.append((loose, "(archivos pequeños)", None))
        if hidden:
            rows.append((hidden, "(espacio oculto: sistema, sin permisos…)", "hidden"))
        rows.sort(key=lambda r: r[0], reverse=True)
        for size, name, obj in rows:
            frac = size / total
            blocks = int(round(frac * 10))
            bar = "█" * blocks + "░" * (10 - blocks)
            is_node = isinstance(obj, core.Node)
            key = obj.path if is_node else node.path + ("<hidden>" if obj == "hidden" else "<files>")
            prefix = ("▸  " if obj.children or obj.top_files else "    ") if is_node and not obj.is_file else \
                "     " if is_node else "    "
            t.add(key, [prefix + name, bar + f"  {frac * 100:.0f}%", human(size)],
                  obj=obj if is_node else None, sort={"size": size}, tags=() if is_node else ("muted",))

    def _map_hover(self, node):
        if node is not None:
            self.map_hover.configure(text=node.path, text_color=C["muted"])
            if self.map_list.tv.exists(node.path):
                self.map_list.tv.selection_set(node.path)
                self.map_list.tv.see(node.path)
        else:
            self.map_hover.configure(text="Clic en un anillo para entrar · clic en el centro para subir · "
                                          "arrastra al Colector", text_color=C["faint"])

    def _map_open_row(self, node):
        if isinstance(node, core.Node) and not node.is_file and (node.children or node.top_files):
            self.sun.set_root(node)
        elif isinstance(node, core.Node):
            self.preview(node)

    def _map_menu(self, node, e):
        menu = tk.Menu(self, tearoff=0, bg=C["surface2"], fg=C["text"], activebackground=C["accent"],
                       activeforeground="#ffffff", bd=0, relief="flat", font=(UI_FONT, 10))
        menu.add_command(label="  Vista previa    ", command=lambda: self.preview(node))
        menu.add_command(label="  Añadir al Colector    ", command=lambda: self._collect_nodes([node]))
        menu.add_command(label=f"  Mostrar en el {FILE_MANAGER}    ", command=lambda: core.open_in_explorer(node.path))
        menu.add_command(label="  Copiar ruta    ", command=lambda: self._copy_path(node))
        menu.add_separator()
        menu.add_command(label="  Borrar…    ", command=lambda: self._delete_nodes([node]))
        menu.tk_popup(e.x_root, e.y_root)

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
        self.set_status("Ruta copiada")

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
            txt = name if len(items) == 1 else f"{len(items)} elementos"
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
        kind = "Carpeta" if is_dir else core.kind_of(ext) + (f" · .{ext}" if ext else "")
        d = Dialog(self, name, width=800, height=600)
        d.minsize(600, 420)
        d.header("info", name, f"{kind}  ·  {human(size)}" + (f"  ·  modificado {when}" if when else "") +
                 f"\n{path}")
        d.buttons([("Mostrar en el " + FILE_MANAGER, "secondary", "show"), ("Al Colector", "secondary", "collect"),
                   ("Cerrar", "primary", None)])
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
                                        text_color=C["muted"], border_width=0, corner_radius=10)
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
            ctk.CTkLabel(box, text="Sin vista previa para este tipo de archivo", font=F(13),
                         text_color=C["faint"]).pack(expand=True)
        self.wait_window(d)
        if d.result == "show":
            core.open_in_explorer(path)
        elif d.result == "collect":
            self._collect([(path, size)])

    def _export_csv(self):
        if not self.scan_result:
            self.alert("Primero analiza un disco o una carpeta.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="pc-free-space.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            core.export_csv(self.scan_result, path)
            self.set_status(f"Exportado: {path}")

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
            self.set_status(f"Añadido al Colector: {added} elemento(s)")

    def _collect_nodes(self, nodes):
        self._collect([(n.path, n.size) for n in nodes if isinstance(n, core.Node)])

    def _collect_rows(self, table, checked=True):
        objs = [o for o in (table.checked_objs() if checked else table.selected()) if o]
        if not objs and checked:
            objs = [o for o in table.selected() if o]
        if not objs:
            self.alert("Marca o selecciona primero algún elemento.", "Nada seleccionado")
            return
        self._collect([(p, s) for s, p in objs])

    def _update_collector(self):
        n = len(self.collector)
        total = sum(self.collector.values())
        self.col_label.configure(text=f"{n} elementos · {human(total)}" if n else
                                 "Arrastra aquí carpetas y archivos desde el mapa o las listas")
        self.col_count.configure(text=str(n), fg_color=C["accent"] if n else C["surface2"])
        state = "normal" if n else "disabled"
        self.col_del.configure(state=state, fg_color=C["bad_h"] if n else C["bad_off"])
        self.col_view.configure(state=state)

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
        self.page_header(page, "Tipos de archivo", "Qué clase de archivos ocupa tu espacio, según el último análisis")
        top = card(page)
        top.pack(fill="x", pady=(0, 12))
        self.kind_box = ctk.CTkFrame(top, fg_color="transparent")
        self.kind_box.pack(fill="x", padx=20, pady=18)
        ctk.CTkLabel(self.kind_box, text=EMPTY_SCAN, font=F(13), text_color=C["faint"]).pack(pady=20)
        self.section(page, "Extensiones que más ocupan")
        self.ext_table = Table(page, [("name", "EXTENSIÓN", 160, "w"), ("kind", "TIPO", 220, "w"),
                                      ("size", "TAMAÑO", 110, "e"), ("files", "ARCHIVOS", 110, "e"),
                                      ("pct", "% DEL TOTAL", 110, "e")], height=7, empty_text=EMPTY_SCAN,
                               on_open=lambda ext: self._show_ext(ext))
        self.ext_table.pack(fill="both", expand=True)
        self.hint(page, "Doble clic en una extensión para ver sus archivos más grandes.")

    def _fill_kinds(self):
        res = self.scan_result
        for w in self.kind_box.winfo_children():
            w.destroy()
        self.ext_table.clear()
        if not res:
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
            label = "." + ext if ext else "(sin extensión)"
            self.ext_table.add("ext:" + ext, [label, core.kind_of(ext), human(b), f"{n:,}".replace(",", "."),
                                              f"{b / total * 100:.1f} %"], obj=ext,
                               sort={"size": b, "files": n, "pct": b})

    def _show_ext(self, ext):
        if ext is None or not self.scan_result:
            return
        self.show("big")
        self.min_size.set("50 MB")
        self.age_filter.set("Cualquiera")
        self.ext_filter.delete(0, "end")
        self.ext_filter.insert(0, "." + ext if ext else "")
        self._fill_bigfiles()

    # =====================================================================
    # Duplicados
    # =====================================================================
    def _build_dups(self, page):
        actions = self.page_header(page, "Duplicados", "Archivos idénticos (mismo contenido) dentro del último análisis")
        btn(actions, "Añadir marcados al Colector", lambda: self._collect_dups(), "secondary", width=220
            ).pack(side="right")
        btn(actions, "Buscar duplicados", self.find_dups, "primary", width=170).pack(side="right", padx=8)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text="Tamaño mínimo", font=F(12), text_color=C["muted"]).pack(side="left", padx=(0, 10))
        self.dup_min = ctk.CTkSegmentedButton(
            bar, values=["1 MB", "10 MB", "100 MB"], font=F(12, "bold"), height=34, corner_radius=10,
            fg_color=C["surface"], selected_color=C["accent"], selected_hover_color=C["accent_h"],
            unselected_color=C["surface"], unselected_hover_color=C["hover"], text_color=C["text"])
        self.dup_min.set("10 MB")
        self.dup_min.pack(side="left")
        btn(bar, "Marcar copias (deja 1)", self._dup_mark_copies, "ghost", width=180).pack(side="left", padx=12)
        self.dup_info = ctk.CTkLabel(bar, text="", font=F(13, "bold"), text_color=C["accent"])
        self.dup_info.pack(side="right")
        self.dup_table = Table(page, [("name", "ARCHIVO", 320, "w"), ("size", "TAMAÑO", 110, "e"),
                                      ("copies", "COPIAS", 90, "center"), ("path", "CARPETA", 420, "w")],
                               checkable=True, tree=False, height=16, on_open=self._open_node,
                               empty_text="Analiza un disco o carpeta y pulsa «Buscar duplicados»")
        self.dup_table.pack(fill="both", expand=True)
        self.dup_table.enable_drag(self._table_drag)
        self.dup_table.context_menu([("Vista previa", lambda: self.preview(self.dup_table.focused())),
                                     ("Mostrar en el " + FILE_MANAGER, lambda: self._open_node(self.dup_table.focused())),
                                     ("Añadir al Colector", lambda: self._collect_rows(self.dup_table, False))])
        self.hint(page, "Compara tamaño y huella del contenido (BLAKE2), así que solo lista copias exactas. "
                        "«Marcar copias» deja sin marcar la primera de cada grupo.")
        self._dup_groups: list = []

    def find_dups(self):
        if not self.scan_result:
            self.alert("Primero analiza un disco o una carpeta en «Mapa del disco».")
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
            self.dup_info.configure(text=f"{len(groups)} grupos · {human(wasted)} recuperables")
        self.run_task("Buscando duplicados…", lambda report: core.find_duplicates(
            res, mins, self.cancel, lambda p: report(f"Comparando {p}")), done)

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
            self.alert("No se borrarán porque están protegidos:\n\n" +
                       "\n".join(f"• {p}\n   {why}" for p, why in blocked[:6]), "Elementos protegidos", "warn")
        if not rest:
            return
        perm = ConfirmDelete.ask(self, "Confirmar borrado", rest, warn_note)
        if perm is None:
            return
        paths = [p for p, _ in rest]

        def work(report):
            return core.delete_paths(paths, perm, lambda p: report(f"Borrando {p}"))

        def done(res):
            if on_done:
                on_done([p for p in paths if not os.path.lexists(p)])
            self.after_delete(res, perm)
        self.run_task("Borrando…", work, done)

    # =====================================================================
    # Archivos grandes
    # =====================================================================
    def _build_bigfiles(self, page):
        actions = self.page_header(page, "Archivos grandes", "Los archivos más pesados del último análisis")
        btn(actions, "Borrar marcados…", lambda: self._delete_checked(self.big_table), "danger_solid", width=170
            ).pack(side="right")
        btn(actions, "Al Colector", lambda: self._collect_rows(self.big_table), "secondary", width=120
            ).pack(side="right", padx=8)
        self.big_info = ctk.CTkLabel(actions, text="", font=F(13, "bold"), text_color=C["accent"])
        self.big_info.pack(side="right", padx=14)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        self.min_size = ctk.CTkSegmentedButton(
            bar, values=["50 MB", "100 MB", "500 MB", "1 GB", "5 GB"], command=lambda _v: self._fill_bigfiles(),
            font=F(12, "bold"), height=34, corner_radius=10, fg_color=C["surface"], selected_color=C["accent"],
            selected_hover_color=C["accent_h"], unselected_color=C["surface"], unselected_hover_color=C["hover"],
            text_color=C["text"])
        self.min_size.set("100 MB")
        self.min_size.pack(side="left")
        self.ext_filter = ctk.CTkEntry(bar, width=300, height=34, corner_radius=10, font=F(12), fg_color=C["surface"],
                                       border_color=C["border"], text_color=C["text"],
                                       placeholder_text="Filtrar: .iso, .zip, .mp4, nombre…",
                                       placeholder_text_color=C["faint"])
        self.ext_filter.pack(side="left", padx=12)
        self.ext_filter.bind("<KeyRelease>", lambda e: self._fill_bigfiles())
        ctk.CTkLabel(bar, text="Sin tocar desde", font=F(12), text_color=C["muted"]).pack(side="left", padx=(4, 8))
        self.age_filter = ctk.CTkOptionMenu(bar, values=["Cualquiera", "6 meses", "1 año", "2 años"], width=130,
                                            height=34, corner_radius=10, font=F(12), fg_color=C["surface"],
                                            button_color=C["surface2"], button_hover_color=C["hover"],
                                            dropdown_fg_color=C["surface2"], text_color=C["text"],
                                            command=lambda _v: self._fill_bigfiles())
        self.age_filter.set("Cualquiera")
        self.age_filter.pack(side="left")
        self.big_table = Table(page, [("name", "ARCHIVO", 280, "w"), ("size", "TAMAÑO", 110, "e"),
                                      ("type", "TIPO", 100, "center"), ("date", "MODIFICADO", 110, "center"),
                                      ("path", "CARPETA", 420, "w")],
                               checkable=True, height=16, on_open=self._open_node, empty_text=EMPTY_SCAN)
        self.big_table.pack(fill="both", expand=True)
        self.big_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.big_table, self.big_info))
        self.big_table.enable_drag(self._table_drag)
        self.big_table.context_menu([("Vista previa", lambda: self.preview(self.big_table.focused())),
                                     ("Mostrar en el " + FILE_MANAGER, lambda: self._open_node(self.big_table.focused())),
                                     ("Borrar…", lambda: self._delete_rows(self.big_table))])
        self.hint(page, "Clic en la casilla para marcar · doble clic lo muestra en el " + FILE_MANAGER +
                        " · arrastra filas al Colector.")

    def _fill_bigfiles(self):
        t = self.big_table
        t.clear()
        if not self.scan_result:
            return
        mins = {"50 MB": 50, "100 MB": 100, "500 MB": 500, "1 GB": 1024, "5 GB": 5120}[self.min_size.get()] * 1024 ** 2
        flt = self.ext_filter.get().strip().lower()
        import time
        days = {"Cualquiera": 0, "6 meses": 182, "1 año": 365, "2 años": 730}[self.age_filter.get()]
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
        self.big_info.configure(text=f"{n} archivos · {human(total)}")

    def _update_checked_info(self, table, label):
        objs = [o for o in table.checked_objs() if o]
        if objs:
            label.configure(text=f"Marcados: {len(objs)} · {human(sum(o[0] for o in objs))}")

    def _delete_checked(self, table):
        objs = [o for o in table.checked_objs() if o]
        if not objs:
            self.alert("Marca primero los elementos haciendo clic en su casilla.", "Nada marcado")
            return
        self._delete_paths_ui([(p, s) for s, p in objs], on_done=lambda ps: self._remove_rows(table, ps))

    def _delete_rows(self, table):
        objs = [o for o in table.selected() if o]
        self._delete_paths_ui([(p, s) for s, p in objs], on_done=lambda ps: self._remove_rows(table, ps))

    def _remove_rows(self, table, paths):
        gone = set(paths)
        for p in paths:
            if table.tv.exists(p):
                table.tv.delete(p)
            table.checked.discard(p)
        if self.scan_result:
            self.scan_result.big_files = [x for x in self.scan_result.big_files if x[1] not in gone]
            self.scan_result.model_files = [x for x in self.scan_result.model_files if x[1] not in gone]

    # =====================================================================
    # Modelos de IA
    # =====================================================================
    def _build_models(self, page):
        actions = self.page_header(page, "Modelos IA", "LLMs y pesos de IA descargados: Ollama, Hugging Face, LM Studio…")
        btn(actions, "Buscar en mi usuario", lambda: self.start_scan(core.HOME), "primary", width=180).pack(side="right")
        top, self.ollama_info = self.section(page, "Ollama")
        btn(top, "Eliminar modelo", self._ollama_rm, "danger", width=150).pack(side="right")
        btn(top, "Actualizar", self._fill_ollama, "ghost", width=100).pack(side="right", padx=6)
        self.ollama_table = Table(page, [("name", "MODELO", 360, "w"), ("size", "TAMAÑO", 110, "e"),
                                         ("path", "MANIFIESTO", 420, "w")], height=5,
                                  empty_text="No se han encontrado modelos de Ollama")
        self.ollama_table.pack(fill="both", expand=True)
        mid, self.model_info = self.section(page, "Archivos de modelos",
                                            ".gguf · .safetensors · .ckpt · .pt · .onnx · .bin  (≥ 50 MB)", (18, 8))
        btn(mid, "Borrar marcados…", lambda: self._delete_checked(self.model_table), "danger", width=160
            ).pack(side="right")
        btn(mid, "Al Colector", lambda: self._collect_rows(self.model_table), "secondary", width=110
            ).pack(side="right", padx=8)
        self.model_table = Table(page, [("name", "ARCHIVO", 300, "w"), ("size", "TAMAÑO", 110, "e"),
                                        ("app", "ORIGEN", 140, "w"), ("path", "CARPETA", 420, "w")],
                                 checkable=True, height=9, on_open=self._open_node,
                                 empty_text="Pulsa «Buscar en mi usuario» (o analiza C:\\) para encontrarlos")
        self.model_table.pack(fill="both", expand=True)
        self.model_table.bind("<<CheckChanged>>",
                              lambda e: self._update_checked_info(self.model_table, self.model_info))
        self.model_table.enable_drag(self._table_drag)
        self.model_table.context_menu([("Mostrar en el " + FILE_MANAGER, lambda: self._open_node(self.model_table.focused())),
                                       ("Borrar…", lambda: self._delete_rows(self.model_table))])
        self.hint(page, "Los modelos de Ollama se eliminan con «ollama rm» para no dejar la instalación inconsistente.")
        self.after(400, self._fill_ollama)

    def _fill_ollama(self):
        t = self.ollama_table
        t.clear()
        models = core.list_ollama_models()
        for m in models:
            t.add(m.manifest, [m.name, human(m.size), m.manifest], obj=m, sort={"size": m.size})
        self.ollama_info.configure(text=f"{len(models)} modelos · {human(sum(m.size for m in models))}"
                                   if models else "")

    def _ollama_rm(self):
        m = self.ollama_table.focused()
        if not m:
            self.alert("Selecciona un modelo de la lista.", "Ningún modelo seleccionado")
            return
        if not self.confirm(f"¿Eliminar {m.name}?", f"Liberarás {human(m.size)}. Si lo necesitas otra vez, "
                                                     "tendrás que descargarlo con «ollama pull».", "Eliminar",
                            danger=True):
            return

        def done(res):
            ok, out = res
            if ok:
                core.add_freed(m.size)
                self.alert(f"Has liberado {human(m.size)}.", f"{m.name} eliminado", "ok")
            else:
                self.alert(f"{out}\n\nComprueba que Ollama está instalado y en ejecución.",
                           "No se pudo eliminar", "error")
            self._fill_ollama()
            self.refresh_summary()
        self.run_task(f"Eliminando {m.name}…", lambda report: core.ollama_remove(m.name), done)

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
        self.model_info.configure(text=f"{len(self.scan_result.model_files)} archivos · {human(total)}")

    # =====================================================================
    # Aplicaciones y restos
    # =====================================================================
    def _build_apps(self, page):
        actions = self.page_header(page, "Aplicaciones", "Programas instalados y restos de los que ya desinstalaste")
        btn(actions, "Desinstalar…", self._uninstall, "danger_solid", width=140).pack(side="right")
        btn(actions, "Calcular tamaño real", self._measure_apps, "secondary", width=170).pack(side="right", padx=8)
        btn(actions, "Cargar aplicaciones", self.load_apps, "primary", width=170).pack(side="right")
        top, self.apps_info = self.section(page, "Instaladas")
        if core.IS_WIN:
            btn(top, "Aplicaciones de Windows  ↗", lambda: self._launch("ms-settings:appsfeatures"), "ghost",
                width=200).pack(side="right")
        self.apps_table = Table(page, [("name", "APLICACIÓN", 320, "w"), ("size", "TAMAÑO", 110, "e"),
                                       ("publisher", "EDITOR", 190, "w"), ("date", "INSTALADA", 100, "center"),
                                       ("path", "UBICACIÓN", 320, "w")], height=9,
                                on_open=lambda a: a and a.location and core.open_in_explorer(a.location),
                                empty_text="Pulsa «Cargar aplicaciones»")
        self.apps_table.pack(fill="both", expand=True)
        self.apps_table.context_menu([("Abrir ubicación", self._open_app), ("Desinstalar…", self._uninstall)])
        mid, self.res_info = self.section(page, "Posibles restos",
                                          "Carpetas de 20 MB o más que no coinciden con ninguna app instalada", (18, 8))
        btn(mid, "Borrar marcados…", lambda: self._delete_checked(self.res_table), "danger", width=160
            ).pack(side="right")
        btn(mid, "Al Colector", lambda: self._collect_rows(self.res_table), "secondary", width=110
            ).pack(side="right", padx=(8, 0))
        btn(mid, "Buscar restos", self.find_residues, "secondary", width=130).pack(side="right", padx=8)
        self.res_table = Table(page, [("name", "CARPETA", 300, "w"), ("size", "TAMAÑO", 110, "e"),
                                      ("where", "DÓNDE", 180, "w"), ("path", "RUTA", 420, "w")],
                               checkable=True, height=7, on_open=self._open_node, empty_text="Pulsa «Buscar restos»")
        self.res_table.pack(fill="both", expand=True)
        self.res_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.res_table, self.res_info))
        self.res_table.enable_drag(self._table_drag)
        self.res_table.context_menu([("Mostrar en el " + FILE_MANAGER, lambda: self._open_node(self.res_table.focused())),
                                     ("Borrar…", lambda: self._delete_rows(self.res_table))])
        self.hint(page, "Es una estimación: abre cada carpeta y revísala antes de borrar. Por defecto va a la Papelera.")

    def load_apps(self):
        def done(apps):
            self.apps = apps
            self._fill_apps()
        self.run_task("Leyendo aplicaciones instaladas…", lambda report: core.list_installed_apps(), done)

    def _fill_apps(self):
        t = self.apps_table
        t.clear()
        for i, a in enumerate(self.apps):
            d = a.install_date
            date = f"{d[6:8]}/{d[4:6]}/{d[0:4]}" if len(d) == 8 and d.isdigit() else ""
            t.add(f"app{i}", [a.name, human(a.size) if a.size else "—", a.publisher, date, a.location],
                  obj=a, sort={"size": a.size, "date": d})
        self.apps_info.configure(text=f"{len(self.apps)} aplicaciones · {human(sum(a.size for a in self.apps))}")

    def _measure_apps(self):
        if not self.apps:
            self.alert("Primero pulsa «Cargar aplicaciones».")
            return
        apps = list(self.apps)

        def work(report):
            for a in apps:
                if self.cancel.is_set():
                    break
                if a.location and os.path.isdir(a.location) and core.protection_level(a.location)[0] != core.BLOCK:
                    report(f"Midiendo {a.name}…")
                    s, _ = core.dir_size(a.location, self.cancel)
                    if s:
                        a.size = s
            apps.sort(key=lambda a: a.size, reverse=True)
            return apps

        def done(apps_):
            self.apps = apps_
            self._fill_apps()
        self.run_task("Midiendo carpetas de instalación…", work, done)

    def _open_app(self):
        a = self.apps_table.focused()
        if a and a.location and os.path.isdir(a.location):
            core.open_in_explorer(a.location)
        elif a:
            self.alert("Esta aplicación no indica su carpeta de instalación.")

    def _uninstall(self):
        a = self.apps_table.focused()
        if not a:
            self.alert("Selecciona una aplicación de la lista.", "Ninguna aplicación seleccionada")
            return
        if core.IS_LINUX:
            if not a.uninstall:
                self.alert("No sé cómo desinstalar este paquete.", "Sin desinstalador", "warn")
                return
            self.clipboard_clear()
            self.clipboard_append(a.uninstall)
            self.alert(f"Ejecuta este comando en una terminal (ya está copiado):\n\n{a.uninstall}",
                       f"Desinstalar {a.name}", "info")
            return
        msg = ("Se abrirá el desinstalador oficial del programa." if core.IS_WIN else
               "La aplicación se moverá a la Papelera. Sus datos en ~/Library aparecerán luego en «Posibles restos».")
        if not self.confirm(f"¿Desinstalar {a.name}?", msg, "Desinstalar", danger=True):
            return
        try:
            core.run_uninstaller(a.uninstall)
            if core.IS_MAC:
                self.apps = [x for x in self.apps if x is not a]
                self._fill_apps()
        except Exception as e:  # noqa: BLE001
            self.alert(str(e), "No se pudo desinstalar", "error")

    def find_residues(self):
        def work(report):
            apps = self.apps or core.list_installed_apps()
            return apps, core.find_residues(apps, self.cancel, progress=lambda p: report(f"Revisando {p}"))

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
            self.res_info.configure(text=f"{len(residues)} carpetas · {human(sum(x.size for x in residues))}")
        self.run_task("Buscando restos de programas…", work, done)

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
        ctk.CTkLabel(b, text="↑", font=F(18, "bold"), width=36, height=36, corner_radius=10,
                     fg_color=C["accent"], text_color="#ffffff").grid(row=0, column=0, rowspan=2, padx=(14, 12),
                                                                      pady=12)
        self.upd_title = ctk.CTkLabel(b, text="", font=F(14, "bold"), text_color=C["text"], anchor="w")
        self.upd_title.grid(row=0, column=1, sticky="sw", pady=(12, 0))
        self.upd_sub = ctk.CTkLabel(b, text="", font=F(12), text_color=C["muted"], anchor="w")
        self.upd_sub.grid(row=1, column=1, sticky="nw", pady=(0, 12))
        acts = ctk.CTkFrame(b, fg_color="transparent")
        acts.grid(row=0, column=2, rowspan=2, padx=14)
        btn(acts, "Actualizar ahora", lambda: self._start_update(self._update_info), "primary", width=150
            ).pack(side="left", padx=(0, 8))
        btn(acts, "Ver novedades", lambda: self._show_notes(self._update_info), "secondary", width=130
            ).pack(side="left", padx=(0, 4))
        btn(acts, "Omitir esta versión", self._skip_update, "ghost", width=150).pack(side="left")
        btn(acts, "✕", lambda: b.grid_remove(), "ghost", width=36).pack(side="left")
        b.grid_remove()
        self.upd_banner = b
        self._update_info = None

    def _check_updates(self, manual=False):
        if getattr(self, "_checking", False):
            return
        self._checking = True
        if manual:
            self.set_status("Buscando actualizaciones…")
        cur = self._current_version()

        def worker():
            info = core.latest_release()
            self.q.put(("update", (info, cur, manual)))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_result(self, info, cur, manual):
        self._checking = False
        if info is None:
            if manual:
                self.set_status("Listo")
                self.alert("No se pudo comprobar si hay una versión nueva. Revisa la conexión a Internet e "
                           "inténtalo más tarde.", "Sin conexión", "warn")
            return
        newer = core.parse_version(info.version) > core.parse_version(cur)
        if not newer:
            if manual:
                self.set_status("Listo")
                self.alert(f"Tienes la versión {VERSION}, que es la más reciente.", "Ya tienes la última versión",
                           "ok")
            return
        if not info.asset_url:  # p. ej. la build de macOS aún no está: no se avisa hasta que exista
            if manual:
                self.set_status("Listo")
                self.alert(f"Ya hay una versión v{info.version}, pero su descarga para {core.OS_NAME} todavía no "
                           "está lista. Vuelve a mirarlo en un rato.", "Casi lista", "info")
            return
        if not manual and core.load_settings().get("skip_version") == info.version:
            return
        self._update_info = info
        self.upd_title.configure(text=f"Nueva versión v{info.version} disponible")
        self.upd_sub.configure(text=f"Tienes la v{cur}." + (f"  Descarga de {human(info.asset_size)}, "
                                                               "verificada con SHA-256." if info.asset_size else ""))
        self.upd_banner.grid()
        if manual:
            self.set_status(f"Hay una versión nueva: v{info.version}")

    def _skip_update(self):
        if self._update_info:
            s = core.load_settings()
            s["skip_version"] = self._update_info.version
            core.save_settings(s)
        self.upd_banner.grid_remove()
        self.set_status("No se volverá a avisar de esta versión. Puedes buscarla con «Buscar actualizaciones».")

    def _show_notes(self, info):
        if not info:
            return
        d = Dialog(self, f"Novedades de v{info.version}", width=720, height=520)
        d.header("info", f"Desktop Free Space v{info.version}", "Lo nuevo en esta versión")
        d.buttons([("Ver en GitHub", "secondary", "web"), ("Cerrar", "primary", None)])
        tb = ctk.CTkTextbox(d.body, font=F(13), fg_color=C["bg"], text_color=C["muted"], border_width=1,
                            border_color=C["border"], corner_radius=12, wrap="word")
        tb.insert("end", info.notes.strip() or "Esta versión no incluye notas.")
        tb.configure(state="disabled")
        tb.pack(fill="both", expand=True, padx=24, pady=12)
        self.wait_window(d)
        if d.result == "web" and info.html_url:
            self._launch(info.html_url)

    def _start_update(self, info):
        if not info:
            return
        if not core.is_frozen():
            self.alert("Estás ejecutando la app desde el código. Actualízala con «git pull»; te abro la página "
                       "de la versión nueva.", "Actualizar desde el código")
            if info.html_url:
                self._launch(info.html_url)
            return
        if self.busy:
            self.alert("Espera a que termine la tarea actual o cancélala.", "Tarea en curso")
            return
        UpdateDialog(self, info)


class UpdateDialog(Dialog):
    """Descarga la versión nueva con barra de progreso, la verifica y la instala al reiniciar."""

    def __init__(self, app, info):
        super().__init__(app, "Actualizar", width=560, height=300)
        self.resizable(False, False)
        self.app, self.info = app, info
        self.cancel = threading.Event()
        self.q: queue.Queue = queue.Queue()
        self.path = None
        self.header("info", f"Actualizando a la v{info.version}",
                    f"Se descarga {info.asset_name} ({human(info.asset_size)}) y se comprueba su huella SHA-256.")
        self.bar = ctk.CTkProgressBar(self.body, height=10, corner_radius=5, fg_color=C["track"],
                                      progress_color=C["accent"])
        self.bar.set(0)
        self.bar.pack(fill="x", padx=24, pady=(14, 6))
        self.msg = ctk.CTkLabel(self.body, text="Conectando…", font=F(12), text_color=C["muted"], anchor="w")
        self.msg.pack(fill="x", padx=24)
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(side="bottom", fill="x", padx=24, pady=(8, 22))
        self.go = btn(bar, "Reiniciar para terminar", self._restart, "primary", width=200)
        self.go.configure(state="disabled")
        self.go.pack(side="right", padx=(8, 0))
        self.stop = btn(bar, "Cancelar", self._cancel, "secondary", width=110)
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
                    self.msg.configure(text=f"Descargando… {human(d)}" + (f" de {human(t)}" if t else ""))
                elif kind == "ok":
                    self.path = val
                    self.bar.set(1)
                    self.msg.configure(text="Descarga verificada (SHA-256 correcto). Reinicia para terminar.",
                                       text_color=C["ok"])
                    self.go.configure(state="normal")
                elif kind == "err":
                    self.bar.configure(progress_color=C["bad"])
                    self.msg.configure(text=val, text_color=C["bad"])
                    self.stop.configure(text="Cerrar")
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
        self.msg.configure(text="Instalando…", text_color=C["muted"])

        def work():
            try:
                self.q.put(("applied", core.apply_update(self.path)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", f"No se pudo instalar: {e}"))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _finish(self, how):
        if how == "opened":
            self.destroy()
            if core.IS_LINUX:
                text = ("He abierto el paquete de la versión nueva en el instalador de tu sistema. Pulsa "
                        "«Instalar» (o «Actualizar») y vuelve a abrir la app.")
            else:
                text = ("He abierto el instalador de la versión nueva. Arrastra la app a Aplicaciones para "
                        "terminar y vuelve a abrirla.")
            self.app.alert(text, "Termina la instalación")
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
    UI_FONT = next((f for f in ("Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", "SF Pro Text",
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
