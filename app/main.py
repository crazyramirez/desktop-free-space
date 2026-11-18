"""PC Free Space: interfaz gráfica para ver y liberar espacio en disco en Windows."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, font as tkfont, ttk

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
from core import human  # noqa: E402

APP_NAME = "PC Free Space"
VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# Sistema visual
# ---------------------------------------------------------------------------
C = {
    "bg": "#0b0d12",          # fondo de la ventana
    "side": "#0f1218",        # barra lateral
    "surface": "#141821",     # tarjetas
    "surface2": "#1a1f2a",    # elementos dentro de tarjetas
    "hover": "#222836",
    "border": "#232a37",
    "text": "#e8ebf2",
    "muted": "#8b93a5",
    "faint": "#5d6577",
    "accent": "#7c6cff",      # violeta
    "accent_h": "#6a59f5",
    "accent_soft": "#211d3d",
    "ok": "#34d399",
    "warn": "#fbbf24",
    "bad": "#f87171",
    "bad_h": "#ef4444",
    "bad_soft": "#2a1619",
    "sel": "#2a2550",
}
RADIUS = 14
CHECK_ON, CHECK_OFF = "☑", "☐"
UI_FONT = "Segoe UI"
ICON_FONT = None
ICONS_MDL2 = {"home": "\uE80F", "clean": "\uE75C", "folder": "\uE8B7", "file": "\uE7C3", "ai": "\uE99A",
              "apps": "\uE71D", "shield": "\uEA18", "trash": "\uE74D", "drive": "\uEDA2", "check": "\uE73E",
              "info": "\uE946", "warn": "\uE7BA"}
ICONS_FALLBACK = {"home": "⌂", "clean": "✦", "folder": "▤", "file": "▦", "ai": "◈", "apps": "▣", "shield": "⛨",
                  "trash": "✕", "drive": "◉", "check": "✓", "info": "i", "warn": "!"}


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
    "primary": dict(fg_color=C["accent"], hover_color=C["accent_h"], text_color="#ffffff", border_width=0),
    "secondary": dict(fg_color=C["surface2"], hover_color=C["hover"], text_color=C["text"],
                      border_width=1, border_color=C["border"]),
    "danger": dict(fg_color=C["bad_soft"], hover_color="#3a1c21", text_color=C["bad"],
                   border_width=1, border_color="#4a2229"),
    "danger_solid": dict(fg_color=C["bad_h"], hover_color="#dc2626", text_color="#ffffff", border_width=0),
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
        col = ctypes.c_int(0x00120D0B)  # color de la barra (BGR de C["bg"]) en Windows 11
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
                              button_color=C["hover"], button_hover_color="#2e3546")
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        sb.grid(row=0, column=1, sticky="ns", padx=(2, 6), pady=12)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.tv.tag_configure("odd", background="#171c26")
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
        box = ctk.CTkTextbox(self.body, font=ctk.CTkFont(family="Consolas", size=12), fg_color=C["bg"],
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
# Anillo de uso del disco
# ---------------------------------------------------------------------------
class Ring(tk.Canvas):
    def __init__(self, master, size=180, thickness=16, bg=C["surface"]):
        try:
            self.k = ctk.ScalingTracker.get_widget_scaling(master)
        except Exception:  # noqa: BLE001
            self.k = 1.0
        s = int(size * self.k)
        super().__init__(master, width=s, height=s, bg=bg, highlightthickness=0, bd=0)
        self.s, self.t = s, int(thickness * self.k)

    def draw(self, pct, big, small):
        self.delete("all")
        s, t = self.s, self.t
        p = t / 2 + 2
        self.create_oval(p, p, s - p, s - p, outline=C["surface2"], width=t)
        if pct > 0:
            self.create_arc(p, p, s - p, s - p, start=90, extent=-359.9 * min(pct, 1.0), style="arc",
                            outline=level_color(pct), width=t)
        self.create_text(s / 2, s / 2 - 9 * self.k, text=big, fill=C["text"], font=(UI_FONT, 22, "bold"))
        self.create_text(s / 2, s / 2 + 18 * self.k, text=small, fill=C["muted"], font=(UI_FONT, 10))


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
PAGES = [("summary", "Resumen", "home"), ("clean", "Limpieza", "clean"), ("analyzer", "Analizar carpetas", "folder"),
         ("big", "Archivos grandes", "file"), ("models", "Modelos IA", "ai"), ("apps", "Aplicaciones", "apps")]
EMPTY_SCAN = "Analiza un disco o una carpeta en «Analizar carpetas» para ver aquí sus archivos"


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
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav: dict[str, tuple] = {}
        self._style()
        self._build()
        self.show("summary")
        self.after(100, self._poll)
        self.after(200, self.refresh_summary)
        self.after(50, lambda: set_dark_titlebar(self))

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
        logo.pack(fill="x", padx=20, pady=(26, 28))
        ctk.CTkLabel(logo, text=icon("drive"), font=IF(18), width=40, height=40, corner_radius=12,
                     fg_color=C["accent"], text_color="#ffffff").pack(side="left")
        lt = ctk.CTkFrame(logo, fg_color="transparent")
        lt.pack(side="left", padx=12)
        ctk.CTkLabel(lt, text="PC Free Space", font=F(15, "bold"), text_color=C["text"]).pack(anchor="w")
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
        # tarjeta de permisos
        adm = ctk.CTkFrame(side, fg_color=C["surface"], corner_radius=12, border_width=1, border_color=C["border"])
        adm.pack(side="bottom", fill="x", padx=14, pady=18)
        is_admin = core.is_admin()
        hdr = ctk.CTkFrame(adm, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(14, 0))
        ctk.CTkLabel(hdr, text=icon("shield"), font=IF(14), text_color=C["ok"] if is_admin else C["warn"]
                     ).pack(side="left")
        ctk.CTkLabel(hdr, text="Administrador" if is_admin else "Modo estándar", font=F(13, "bold"),
                     text_color=C["text"]).pack(side="left", padx=8)
        ctk.CTkLabel(adm, text=("Puedes limpiar también las carpetas de Windows." if is_admin else
                                "Para limpiar Windows Temp y Windows Update hacen falta permisos."),
                     font=F(11), text_color=C["muted"], wraplength=186, justify="left"
                     ).pack(anchor="w", padx=14, pady=(4, 12))
        if core.IS_WIN and not is_admin:
            btn(adm, "Reiniciar como admin", self._relaunch_admin, "secondary").pack(fill="x", padx=12, pady=(0, 12))

        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)
        for key, _l, _i in PAGES:
            f = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew", padx=30, pady=(26, 0))
            self.pages[key] = f
        self._build_summary(self.pages["summary"])
        self._build_clean(self.pages["clean"])
        self._build_analyzer(self.pages["analyzer"])
        self._build_bigfiles(self.pages["big"])
        self._build_models(self.pages["models"])
        self._build_apps(self.pages["apps"])

        foot = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0, height=48)
        foot.grid(row=1, column=0, sticky="ew", padx=30, pady=(8, 12))
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
        actions = ctk.CTkFrame(h, fg_color="transparent")
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
    def run_task(self, label, fn, done=None):
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
                self.q.put(("done", (done, fn(report), None)))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.q.put(("done", (done, None, e)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        last_status = None
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    last_status = payload
                elif kind == "done":
                    done, res, err = payload
                    last_status = None
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress.set(0)
                    self.progress.grid_remove()
                    self.cancel_btn.grid_remove()
                    if err:
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

    def after_delete(self, res: core.DeleteResult):
        msg = f"{res.deleted:,} archivos borrados.".replace(",", ".")
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
            os.startfile(target)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            self.alert(str(e), "No se pudo abrir", "error")

    def _relaunch_admin(self):
        if core.relaunch_as_admin():
            self.destroy()

    # =====================================================================
    # Resumen
    # =====================================================================
    def _build_summary(self, page):
        actions = self.page_header(page, "Resumen", "Estado de tus discos y por dónde empezar a liberar espacio")
        btn(actions, "Actualizar", self.refresh_summary, "secondary", width=110).pack(side="right")
        self.sum_body = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=C["hover"],
                                               scrollbar_button_hover_color="#2e3546")
        self.sum_body.pack(fill="both", expand=True)
        self.sum_body.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")

    def _tile(self, parent, col, title, value, sub, action=None, kind="secondary", row=1):
        t = card(parent)
        t.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 7, 0 if col == 2 else 7), pady=(0, 14))
        ctk.CTkLabel(t, text=title.upper(), font=F(11, "bold"), text_color=C["faint"]).pack(anchor="w", padx=22,
                                                                                          pady=(20, 2))
        ctk.CTkLabel(t, text=value, font=F(28, "bold"), text_color=C["text"]).pack(anchor="w", padx=22)
        ctk.CTkLabel(t, text=sub, font=F(12), text_color=C["muted"], wraplength=300, justify="left"
                     ).pack(anchor="w", padx=22, pady=(2, 14 if action else 22))
        if action:
            btn(t, action[0], action[1], kind, width=130).pack(anchor="w", padx=22, pady=(0, 20))

    def refresh_summary(self):
        body = self.sum_body
        for w in body.winfo_children():
            w.destroy()
        drives = core.list_drives()
        sysdrive = next((d for d in drives if d.path.upper().startswith(core.SYSDRIVE[:2].upper())), None) \
            or (drives[0] if drives else None)
        if sysdrive:
            hero = card(body)
            hero.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 14))
            hero.grid_columnconfigure(1, weight=1)
            ring = Ring(hero, size=180, thickness=16)
            ring.grid(row=0, column=0, rowspan=3, padx=(30, 34), pady=26)
            ring.draw(sysdrive.pct, f"{sysdrive.pct * 100:.0f}%", "en uso")
            ctk.CTkLabel(hero, text=f"DISCO DEL SISTEMA  ·  {sysdrive.path}", font=F(11, "bold"),
                         text_color=C["faint"]).grid(row=0, column=1, sticky="sw", pady=(34, 0))
            ctk.CTkLabel(hero, text=f"{human(sysdrive.free)} libres", font=F(38, "bold"), text_color=C["text"]
                         ).grid(row=1, column=1, sticky="w")
            info = ctk.CTkFrame(hero, fg_color="transparent")
            info.grid(row=2, column=1, sticky="nw", pady=(6, 26))
            for label, val in (("Usado", human(sysdrive.used)), ("Capacidad", human(sysdrive.total))):
                f = ctk.CTkFrame(info, fg_color=C["surface2"], corner_radius=10)
                f.pack(side="left", padx=(0, 10))
                ctk.CTkLabel(f, text=label, font=F(11), text_color=C["faint"]).pack(anchor="w", padx=16, pady=(8, 0))
                ctk.CTkLabel(f, text=val, font=F(15, "bold"), text_color=C["text"]).pack(anchor="w", padx=16,
                                                                                        pady=(0, 8))
            acts = ctk.CTkFrame(hero, fg_color="transparent")
            acts.grid(row=0, column=2, rowspan=3, padx=30)
            btn(acts, "Buscar qué borrar", lambda: (self.show("clean"), self.scan_categories()), "primary",
                width=200).pack(pady=5)
            btn(acts, "Analizar el disco", lambda p=sysdrive.path: self.start_scan(p), "secondary",
                width=200).pack(pady=5)

        size, n = core.recycle_bin_size()
        self._tile(body, 0, "Papelera de reciclaje", human(size), f"{n} elementos · ocupan espacio hasta vaciarla",
                   ("Vaciar", self._empty_bin) if size else None, "danger")
        scanned = [c for c in self.categories if getattr(c, "_scanned", False)]
        if scanned:
            safe = sum(c.size for c in scanned if c.risk == core.SAFE)
            rev = sum(c.size for c in scanned if c.risk == core.REVIEW)
            self._tile(body, 1, "Recuperable", human(safe + rev), f"{human(safe)} seguro · {human(rev)} a revisar",
                       ("Ir a Limpieza", lambda: self.show("clean")))
        else:
            self._tile(body, 1, "Recuperable", "—", "Temporales, cachés y modelos de IA sin calcular",
                       ("Calcular", lambda: (self.show("clean"), self.scan_categories())))
        sysfiles = core.system_files_info()
        self._tile(body, 2, "Archivos del sistema", human(sum(x[2] for x in sysfiles)) if sysfiles else "—",
                   " · ".join(f"{os.path.basename(p)} {human(s)}" for _l, p, s, _t in sysfiles) or
                   "Hibernación y memoria virtual")
        row = 2
        others = [d for d in drives if d is not sysdrive]
        if others:
            ctk.CTkLabel(body, text="Otros discos", font=F(15, "bold"), text_color=C["text"]
                         ).grid(row=row, column=0, sticky="w", pady=(6, 10))
            row += 1
            dc = card(body)
            dc.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 14))
            dc.grid_columnconfigure(1, weight=1)
            for i, d in enumerate(others):
                ctk.CTkLabel(dc, text=d.path, font=F(15, "bold"), text_color=C["text"], width=60
                             ).grid(row=i, column=0, padx=(22, 10), pady=14)
                bar = ctk.CTkProgressBar(dc, height=8, corner_radius=4, fg_color=C["surface2"],
                                         progress_color=level_color(d.pct))
                bar.grid(row=i, column=1, sticky="ew", padx=10)
                bar.set(d.pct)
                ctk.CTkLabel(dc, text=f"{human(d.free)} libres de {human(d.total)}", font=F(12),
                             text_color=C["muted"], width=210, anchor="e").grid(row=i, column=2, padx=10)
                btn(dc, "Analizar", lambda p=d.path: self.start_scan(p), "ghost", width=90
                    ).grid(row=i, column=3, padx=(0, 14))
            row += 1
        ctk.CTkLabel(body, text="Herramientas de Windows", font=F(15, "bold"), text_color=C["text"]
                     ).grid(row=row, column=0, sticky="w", pady=(6, 10))
        row += 1
        tools = [("Liberador de espacio", "Restos de actualizaciones y del sistema", "cleanmgr.exe"),
                 ("Sensor de almacenamiento", "Limpieza automática programada", "ms-settings:storagesense"),
                 ("Puntos de restauración", "Cuánto ocupan las copias del sistema", "SystemPropertiesProtection.exe")]
        for i, (t1, t2, target) in enumerate(tools):
            t = card(body)
            t.grid(row=row, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            ctk.CTkLabel(t, text=t1, font=F(13, "bold"), text_color=C["text"]).pack(anchor="w", padx=22, pady=(18, 0))
            ctk.CTkLabel(t, text=t2, font=F(12), text_color=C["muted"]).pack(anchor="w", padx=22)
            btn(t, "Abrir  ↗", lambda x=target: self._launch(x), "ghost", width=80).pack(anchor="w", padx=12,
                                                                                         pady=(6, 14))
        if any("hiberfil" in p for _l, p, _s, _t in sysfiles):
            row += 1
            ctk.CTkLabel(body, text="Consejo: si no usas la hibernación, ejecuta «powercfg /h off» como "
                                    "administrador y recuperarás el espacio de hiberfil.sys.",
                         font=F(12), text_color=C["faint"]).grid(row=row, column=0, columnspan=3, sticky="w",
                                                                pady=(14, 0))

    def _empty_bin(self):
        size, n = core.recycle_bin_size()
        if self.confirm("¿Vaciar la Papelera?", f"{human(size)} en {n} elementos. No se podrá recuperar.",
                        "Vaciar", danger=True):
            core.empty_recycle_bin()
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
            box = ctk.CTkTextbox(d.body, font=ctk.CTkFont(family="Consolas", size=12), fg_color=C["bg"],
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
            self.after_delete(res)
        self.run_task("Limpiando…", work, done)

    # =====================================================================
    # Analizador de carpetas
    # =====================================================================
    def _build_analyzer(self, page):
        actions = self.page_header(page, "Analizar carpetas", "Descubre qué carpetas ocupan más espacio")
        self.scan_info = ctk.CTkLabel(actions, text="", font=F(13, "bold"), text_color=C["accent"])
        self.scan_info.pack(side="right")
        bar = card(page)
        bar.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=12)
        self.scan_path = ctk.CTkEntry(inner, height=38, corner_radius=10, font=F(13), fg_color=C["bg"],
                                      border_color=C["border"], text_color=C["text"])
        self.scan_path.insert(0, core.SYSDRIVE if core.IS_WIN else os.path.expanduser("~"))
        self.scan_path.pack(side="left", fill="x", expand=True)
        btn(inner, "Examinar…", self._pick_folder, "secondary", width=110).pack(side="left", padx=8)
        btn(inner, "Mi usuario", lambda: self.start_scan(core.HOME), "secondary", width=110).pack(side="left")
        btn(inner, "Analizar", lambda: self.start_scan(self.scan_path.get()), "primary", width=120
            ).pack(side="left", padx=(8, 0))
        self.tree = Table(page, [("size", "TAMAÑO", 110, "e"), ("pct", "% DEL PADRE", 110, "e"),
                                 ("files", "ARCHIVOS", 100, "e"), ("path", "RUTA", 420, "w")],
                          tree=True, height=16, on_open=self._open_node,
                          empty_text="Elige un disco o una carpeta y pulsa «Analizar»")
        self.tree.pack(fill="both", expand=True)
        self.tree.tv.bind("<<TreeviewOpen>>", self._expand_node, add="+")
        self.tree.context_menu([("Abrir en el Explorador", lambda: self._open_node(self.tree.focused())),
                                ("Copiar ruta", self._copy_node_path), ("-", None),
                                ("Borrar…", self._delete_nodes)])
        self.hint(page, "Despliega con la flecha · doble clic abre la carpeta · clic derecho para borrar. "
                        "Las carpetas de Windows y del sistema están protegidas.")

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
        self.scan_path.delete(0, "end")
        self.scan_path.insert(0, path)
        self.show("analyzer")

        def work(report):
            return core.scan_tree(path, self.cancel,
                                  lambda n, b, p: report(f"Analizando · {n:,} archivos · {human(b)} · {p}"))

        def done(res: core.ScanResult):
            self.scan_result = res
            self._fill_tree()
            self._fill_bigfiles()
            self._fill_model_files()
            r = res.root
            txt = f"{human(r.size)} en {r.files:,} archivos".replace(",", ".")
            self.scan_info.configure(text=txt + (" (parcial)" if self.cancel.is_set() else ""))
        self.run_task(f"Analizando {path}…", work, done)

    def _fill_tree(self):
        self.tree.clear()
        r = self.scan_result.root
        self._insert_node("", r, r.size, open_=True)

    def _insert_node(self, parent, node: core.Node, parent_size, open_=False):
        pct = node.size / parent_size * 100 if parent_size else 0
        iid = node.path
        if self.tree.tv.exists(iid):
            return
        self.tree.add(iid, [human(node.size), f"{pct:.1f} %", f"{node.files:,}".replace(",", "."), node.path],
                      obj=node, text="  " + node.name, parent=parent,
                      sort={"size": node.size, "files": node.files, "pct": pct},
                      tags=("warn",) if pct >= 25 and parent else ())
        if node.children:
            if open_:
                self._populate(iid, node)
                self.tree.tv.item(iid, open=True)
            else:
                self.tree.tv.insert(iid, "end", iid=iid + "<dummy>", text="…")

    def _populate(self, iid, node: core.Node):
        for ch in self.tree.tv.get_children(iid):
            if ch.endswith("<dummy>"):
                self.tree.tv.delete(ch)
        shown = rest = 0
        for c in node.children:
            if shown < 300 and c.size > 0:
                self._insert_node(iid, c, node.size)
                shown += 1
            else:
                rest += c.size
        if node.own_files:
            fid = iid + "<files>"
            if not self.tree.tv.exists(fid):
                self.tree.tv.insert(iid, "end", iid=fid, text="  (archivos sueltos)",
                                    values=[human(node.own_files),
                                            f"{node.own_files / node.size * 100 if node.size else 0:.1f} %", "", ""],
                                    tags=("muted",))
        if rest:
            self.tree.tv.insert(iid, "end", text="  … otras carpetas pequeñas", values=[human(rest), "", "", ""],
                                tags=("muted",))

    def _expand_node(self, _e):
        iid = self.tree.tv.focus()
        node = self.tree.data.get(iid)
        if node and any(ch.endswith("<dummy>") for ch in self.tree.tv.get_children(iid)):
            self._populate(iid, node)

    def _open_node(self, node):
        if node is not None:
            path = node.path if isinstance(node, core.Node) else node[1] if isinstance(node, tuple) else str(node)
            core.open_in_explorer(path)

    def _copy_node_path(self):
        n = self.tree.focused()
        if n:
            self.clipboard_clear()
            self.clipboard_append(n.path)
            self.set_status("Ruta copiada")

    def _delete_nodes(self):
        nodes = [n for n in self.tree.selected() if isinstance(n, core.Node)]
        self._delete_paths_ui([(n.path, n.size) for n in nodes], on_done=self._after_tree_delete)

    def _after_tree_delete(self, paths):
        for p in paths:
            if self.tree.tv.exists(p):
                self.tree.tv.delete(p)

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
            self.after_delete(res)
        self.run_task("Borrando…", work, done)

    # =====================================================================
    # Archivos grandes
    # =====================================================================
    def _build_bigfiles(self, page):
        actions = self.page_header(page, "Archivos grandes", "Los archivos más pesados del último análisis")
        btn(actions, "Borrar marcados…", lambda: self._delete_checked(self.big_table), "danger_solid", width=170
            ).pack(side="right")
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
        self.big_table = Table(page, [("name", "ARCHIVO", 280, "w"), ("size", "TAMAÑO", 110, "e"),
                                      ("type", "TIPO", 100, "center"), ("path", "CARPETA", 480, "w")],
                               checkable=True, height=16, on_open=self._open_node, empty_text=EMPTY_SCAN)
        self.big_table.pack(fill="both", expand=True)
        self.big_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.big_table, self.big_info))
        self.big_table.context_menu([("Mostrar en el Explorador", lambda: self._open_node(self.big_table.focused())),
                                     ("Borrar…", lambda: self._delete_rows(self.big_table))])
        self.hint(page, "Clic en la casilla para marcar · doble clic lo muestra en el Explorador.")

    def _fill_bigfiles(self):
        t = self.big_table
        t.clear()
        if not self.scan_result:
            return
        mins = {"50 MB": 50, "100 MB": 100, "500 MB": 500, "1 GB": 1024, "5 GB": 5120}[self.min_size.get()] * 1024 ** 2
        flt = self.ext_filter.get().strip().lower()
        n = total = 0
        for size, path in self.scan_result.big_files:
            if size < mins or (flt and flt not in path.lower()):
                continue
            t.add(path, [os.path.basename(path), human(size), os.path.splitext(path)[1].lower() or "—",
                         os.path.dirname(path)], obj=(size, path), sort={"size": size})
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
        self.model_table = Table(page, [("name", "ARCHIVO", 300, "w"), ("size", "TAMAÑO", 110, "e"),
                                        ("app", "ORIGEN", 140, "w"), ("path", "CARPETA", 420, "w")],
                                 checkable=True, height=9, on_open=self._open_node,
                                 empty_text="Pulsa «Buscar en mi usuario» (o analiza C:\\) para encontrarlos")
        self.model_table.pack(fill="both", expand=True)
        self.model_table.bind("<<CheckChanged>>",
                              lambda e: self._update_checked_info(self.model_table, self.model_info))
        self.model_table.context_menu([("Mostrar en el Explorador", lambda: self._open_node(self.model_table.focused())),
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
        btn(top, "Aplicaciones de Windows  ↗", lambda: self._launch("ms-settings:appsfeatures"), "ghost", width=200
            ).pack(side="right")
        self.apps_table = Table(page, [("name", "APLICACIÓN", 320, "w"), ("size", "TAMAÑO", 110, "e"),
                                       ("publisher", "EDITOR", 190, "w"), ("date", "INSTALADA", 100, "center"),
                                       ("path", "UBICACIÓN", 320, "w")], height=9,
                                on_open=lambda a: a and a.location and core.open_in_explorer(a.location),
                                empty_text="Pulsa «Cargar aplicaciones»")
        self.apps_table.pack(fill="both", expand=True)
        self.apps_table.context_menu([("Abrir ubicación", self._open_app), ("Desinstalar…", self._uninstall)])
        mid, self.res_info = self.section(page, "Posibles restos",
                                          "Carpetas ≥ 20 MB que no coinciden con ninguna app instalada", (18, 8))
        btn(mid, "Borrar marcados…", lambda: self._delete_checked(self.res_table), "danger", width=160
            ).pack(side="right")
        btn(mid, "Buscar restos", self.find_residues, "secondary", width=130).pack(side="right", padx=8)
        self.res_table = Table(page, [("name", "CARPETA", 300, "w"), ("size", "TAMAÑO", 110, "e"),
                                      ("where", "DÓNDE", 180, "w"), ("path", "RUTA", 420, "w")],
                               checkable=True, height=7, on_open=self._open_node, empty_text="Pulsa «Buscar restos»")
        self.res_table.pack(fill="both", expand=True)
        self.res_table.bind("<<CheckChanged>>", lambda e: self._update_checked_info(self.res_table, self.res_info))
        self.res_table.context_menu([("Abrir en el Explorador", lambda: self._open_node(self.res_table.focused())),
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
        if not self.confirm(f"¿Desinstalar {a.name}?", "Se abrirá el desinstalador oficial del programa.",
                            "Desinstalar", danger=True):
            return
        try:
            core.run_uninstaller(a.uninstall)
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


def _pick_fonts():
    global UI_FONT, ICON_FONT
    probe = tk.Tk()
    probe.withdraw()
    fams = set(tkfont.families(probe))
    probe.destroy()
    UI_FONT = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Roboto", "DejaVu Sans")
                    if f in fams), "TkDefaultFont")
    ICON_FONT = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), None)


def main():
    if core.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCFreeSpace.App")
        except Exception:  # noqa: BLE001
            pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    _pick_fonts()
    app = App()
    base = getattr(sys, "_MEIPASS", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
    ico = os.path.join(base, "icon.ico")
    if core.IS_WIN and os.path.exists(ico):
        try:
            app.iconbitmap(ico)
        except tk.TclError:
            pass
    app.mainloop()


if __name__ == "__main__":
    main()
