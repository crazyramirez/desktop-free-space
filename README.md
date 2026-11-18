<div align="center">

[Español](README.es.md) · **English**

<img src="docs/hero.png" alt="Desktop Free Space" width="100%">

# Desktop Free Space

**Find out what is filling up your disk and free up space without fear of breaking anything.**

A dark-themed desktop app for **Windows, macOS and Linux** that draws an interactive map of your disks, finds temp files, caches, AI models, duplicates and leftovers from uninstalled apps, and lets you delete them safely.

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-12%2B-000000?logo=apple&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-x86__64-FCC624?logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-7c6cff)

[Download](#-download) · [Screenshots](#-screenshots) · [Features](#-features) · [Install](#-install-from-source) · [Safety](#-safety)

</div>

> The app's interface is currently in Spanish. Button names below are given in English with the Spanish label in brackets.

---

## 📸 Screenshots

<p align="center">
  <img src="docs/screenshots/disk-map.png" alt="Disk map with the context menu" width="100%">
  <br><sub><b>Disk map</b>: interactive rings, a list coloured like each sector and the context menu.</sub>
</p>

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/disks.png" alt="Disks"><br><sub><b>Disks</b>: live free space and where to start.</sub></td>
    <td width="50%"><img src="docs/screenshots/cleanup.png" alt="Cleanup"><br><sub><b>Cleanup</b>: temp files and caches by category, with a risk level.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/large-files.png" alt="Large files"><br><sub><b>Large files</b>: filters, checkboxes and quick actions.</sub></td>
    <td width="50%"><img src="docs/screenshots/file-types.png" alt="File types"><br><sub><b>File types</b>: what kind of files fill your disk.</sub></td>
  </tr>
</table>

## ✨ Features

### Disks (Discos)
- Free, used and total space of the system disk with a usage ring, plus a row with a capacity bar for every other disk. **Updates in real time**, no scan needed.
- **Space freed**: how many GB you have freed with the app since you installed it (permanent deletions, emptied Trash and removed models).
- Size of the **Trash / Recycle Bin**, with a button to empty it.
- Hibernation and virtual memory files (`hiberfil.sys`, `pagefile.sys`, `/swapfile`, `sleepimage`) with tips to shrink them, and local Time Machine snapshots on macOS.
- Shortcuts to the system tools: Disk Cleanup and Storage Sense on Windows, Storage and Disk Utility on macOS, Disk Usage Analyzer on Linux.

### Disk map (Mapa del disco)
- **Interactive, smooth, animated sunburst map**: each ring is a folder level, each arc's size is the space it takes, and colours follow a rainbow by position.
- **Large files** (1 MB or more) appear as their own segments inside their folder.
- **Hidden space**: when you scan a whole disk, the difference between used space and what could be read shows as a grey segment (system files, folders without permission, snapshots).
- Hover to see size and percentage; click to enter a folder and click the centre to go up. Progress animation while scanning.
- **Quick Look** (Space key or click a file on the map): images, text or folder contents, with buttons to reveal it or send it to the Collector.
- Breadcrumbs, a list sorted by size with percentage bars, and a context menu (preview, show in file manager, copy path, add to Collector, delete).
- **Export to CSV**.
- On macOS and Linux it counts real on-disk size (allocated blocks) and hard links only once.

### Collector (Colector)
- A basket in the sidebar: **drag** map segments or rows from any list (map, large files, duplicates, models, leftovers) into it and delete them all at the end, after reviewing the full list.

### File types (Tipos de archivo)
- How much space videos, images, AI models, archives, code, documents… take, with a stacked bar and a table of the largest extensions.
- Double-click an extension to see its largest files.

### Cleanup by category (Limpieza)
Calculates the size of each category and labels it **Safe** (regenerates by itself) or **Review** (would need to be downloaded again). Categories adapt to each system:

| Group | What it cleans |
|---|---|
| **System** | Temp files, Windows Update, memory dumps, thumbnail cache, logs, GPU shader caches, package caches (apt, dnf, pacman) |
| **Browsers & apps** | Chrome, Edge, Brave, Opera, Firefox and Safari caches (passwords, history and sessions are never touched) and Electron apps such as VS Code, Cursor, Discord, Slack, Teams or Spotify |
| **Development** | pip, uv, Poetry, Conda, npm, yarn, pnpm, bun, Deno, Gradle, Android, Maven, NuGet, Cargo, Go, PlatformIO, Homebrew, Xcode (DerivedData, simulators and archives), JetBrains and Unity |
| **AI / Models** | Hugging Face, Ollama, LM Studio, PyTorch Hub, Whisper, Keras, DeepFace, rembg, ModelScope, InsightFace, EasyOCR, GPT4All and Jan |

### Large files (Archivos grandes)
- The 1000 heaviest files from the last scan, with modification date.
- Filters by minimum size, extension or name, and **age** (untouched for 6 months, 1 year or 2 years).

### Duplicates (Duplicados)
- Finds identical files by size and content fingerprint (BLAKE2): no false positives, and hard links are not counted twice.
- **Mark copies** keeps the original and marks the rest so you can send them to the Collector.

### AI models (Modelos IA)
- Lists **Ollama models by name** (`llama3:latest`…) with their real size and removes them with `ollama rm`.
- Finds model files of 50 MB or more (`.gguf`, `.safetensors`, `.ckpt`, `.pt`, `.onnx`, `.bin`…) and shows where they probably come from.

### Applications (Aplicaciones)
- Installed programs: Windows registry, `/Applications` on macOS, and `dpkg`, `rpm`, `pacman`, Flatpak and Snap packages on Linux.
- Opens the official uninstaller (Windows), moves the app to the Trash (macOS) or gives you the uninstall command (Linux).
- **Possible leftovers**: folders of 20 MB or more in AppData and ProgramData, `~/Library`, or `~/.config` and `~/.local/share` that don't match any installed app.

---

## 🔄 Automatic updates

- A few seconds after starting, the app checks in the background for a new version in the [GitHub releases](https://github.com/crazyramirez/desktop-free-space/releases). Offline, it stays quiet.
- If there is one, a banner offers **Update now**, **What's new** and **Skip this version**. It never updates on its own: you always have to click.
- The download is verified against the **SHA-256** published on GitHub; if it doesn't match, nothing is installed.
- **Restart to finish** installs the new version the same way you installed the app, and reopens it:
  - **Windows installer:** the new `Setup.exe` runs silently over the current installation.
  - **Windows portable:** the `.exe` is swapped in place (a `.old` backup is kept).
  - **macOS:** the new `.app` is copied over the current one (without permission, the `.dmg` opens so you can drag it to Applications).
  - **Linux .deb:** the new package opens in your system's software installer; click *Install/Update*.
  - **Linux .tar.gz:** the binary is replaced.
- **Check for updates**, in the system card of the sidebar, checks whenever you want.
- The skipped version is stored in `settings.json` in `%APPDATA%\DesktopFreeSpace` (Windows), `~/Library/Application Support/DesktopFreeSpace` (macOS) or `~/.config/DesktopFreeSpace` (Linux).

---

## 🛡 Safety

Desktop Free Space is designed so you can't break your system by accident:

- **Nothing is deleted without confirmation.** You always see the full list of what will be removed and its size first.
- **Trash or permanent delete**, your choice every time.
- **Protected paths** are never deleted: drive roots, `C:\Windows` (except temp files, Windows Update and dumps), `System Volume Information`, `Recovery`, `EFI`; on macOS and Linux `/System`, `/usr`, `/bin`, `/etc`, `/lib`, `/boot`, `/var/lib`, `/Library`, your keys (`~/.ssh`, `~/.gnupg`, Keychains), and your base user folders (Desktop, Documents, Downloads…). You can delete their contents, but not the folders themselves.
- **Warning in Program Files, `/Applications` and `/opt`**: it recommends uninstalling instead of deleting the folder.
- It doesn't follow symbolic links or *junctions* and never enters `/proc`, `/sys` or `/dev`.
- OneDrive cloud-only files count as 0 bytes.
- Files in use are skipped without errors.
- "Possible leftovers" are an estimate. Review them before deleting.

---

## 📥 Download

Get the latest version from [**Releases**](../../releases/latest):

| System | File | How to install |
|---|---|---|
| **Windows** (recommended) | `DesktopFreeSpace-Setup.exe` | Run the installer. It installs for your user only (no admin rights) in `%LOCALAPPDATA%\Programs\Desktop Free Space`, adds a Start menu shortcut (and a desktop one if you want) and shows up in *Settings → Apps* so you can uninstall it like any other program. |
| Windows (portable) | `DesktopFreeSpace-Windows.exe` | No installation: double-click to run. Handy on a USB stick. |
| **macOS** | `DesktopFreeSpace-macOS.dmg` | Open the .dmg and drag the app to Applications. To uninstall, move it to the Trash. |
| **Linux** (Ubuntu/Debian, recommended) | `DesktopFreeSpace-Linux-amd64.deb` | Double-click it or run `sudo apt install ./DesktopFreeSpace-Linux-amd64.deb`. It appears in the app menu and as the `desktop-free-space` command. Uninstall with `sudo apt remove desktop-free-space`. |
| Linux (any distro) | `DesktopFreeSpace-Linux-x86_64.tar.gz` | `tar xzf DesktopFreeSpace-Linux-x86_64.tar.gz && ./DesktopFreeSpace/DesktopFreeSpace` |

> **Note.** The executables are not signed. On Windows, SmartScreen may warn you: click *More info* and *Run anyway*. On macOS, the first time right-click the app and choose *Open*.

Cleaning system temp files needs administrator rights. On Windows use **Restart as admin** (Reiniciar como admin) in the sidebar; on macOS and Linux, the categories that need it say so.

---

## 🛠 Install from source

You need **Python 3.10 or newer** with tkinter (on Ubuntu/Debian: `sudo apt install python3-tk`).

```bash
git clone https://github.com/crazyramirez/desktop-free-space.git
cd desktop-free-space
python -m venv .venv
# Windows: .venv\Scripts\activate    ·    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

### Build the executable

- **Windows:** double-click **`build.bat`** → `dist\DesktopFreeSpace.exe`.
- **Windows installer:** with [Inno Setup 6](https://jrsoftware.org/isinfo.php), build the `--onedir` version and run `iscc /DMyAppVersion=X.Y.Z /DSourceDir=..\dist\DesktopFreeSpace installer\DesktopFreeSpace.iss` → `out\DesktopFreeSpace-Setup.exe`.
- **macOS / Linux:** `./build.sh` → `dist/DesktopFreeSpace.app` or `dist/DesktopFreeSpace`.

**GitHub Actions** (`.github/workflows/build.yml`) builds everything on every push to `main` and publishes a **Release** `v<version>` with the Windows installer and portable exe, the macOS .dmg, and the Linux .deb and .tar.gz. Only the latest release is kept: older releases, their tags, old Actions runs and artifacts are deleted automatically.

---

## 🚀 Quick start

1. Open **Disks** to see how much free space you have. From there, **Clean temp files and caches** (Limpiar temporales y cachés) calculates what can be safely deleted, and **See what takes up space** (Ver qué ocupa espacio) opens the disk map.
2. In **Disk map**, scan your disk or your user folder and explore the rings to see what takes the most space.
3. Go to **Cleanup**, click **Calculate space**, then **Mark safe ones** and **Clean selected**.
4. Check **Duplicates**, **Large files** (filter by age) and **AI models**: they usually free the most space.
5. Drop whatever you want to delete into the **Collector** and delete it all at once at the end.

---

## 🧱 Project structure

```
desktop-free-space/
├── app/
│   ├── core.py        # Logic: scanning, per-OS categories, duplicates, path protection and deletion
│   └── main.py        # GUI (customtkinter + sunburst map)
├── assets/            # Icons (icon.ico, icon.png)
├── docs/              # Cover (hero.png), screenshots (screenshots/) and social preview image (social-preview.jpg)
├── installer/         # Windows installer script (Inno Setup)
├── build.bat          # Builds the .exe (Windows)
├── build.sh           # Builds the app (macOS) or binary (Linux)
├── requirements.txt
└── .github/workflows/build.yml
```

**Built with:** Python, [customtkinter](https://github.com/TomSchimansky/CustomTkinter), [Send2Trash](https://github.com/arsenetar/send2trash) and [PyInstaller](https://pyinstaller.org).

---

## 📄 License

[MIT](LICENSE) © 2026 crazyramirez
