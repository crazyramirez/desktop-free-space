<div align="center">

<img src="docs/hero.png" alt="PC Free Space" width="100%">

# PC Free Space

**Descubre qué está llenando tu disco C: y libera espacio sin miedo a romper nada.**

App de escritorio para Windows que te enseña cuánto espacio libre tienes, qué lo está ocupando (temporales, cachés de navegadores y herramientas de desarrollo, modelos de IA, restos de programas desinstalados…) y te deja borrarlo con seguridad, siempre viendo antes la lista y confirmando.

[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](#-descarga)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#-instalación-desde-el-código)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-7c6cff)](LICENSE)

[Descarga](#-descarga) · [Funcionalidades](#-funcionalidades) · [Instalación](#-instalación-desde-el-código) · [Seguridad](#-seguridad)

</div>

---

## ✨ Funcionalidades

### 🏠 Resumen

- Espacio libre y usado de **cada disco**, con un anillo de uso.
- Tamaño de la **Papelera** y botón para vaciarla.
- `hiberfil.sys`, `pagefile.sys` y `swapfile.sys` con su tamaño y **consejos** para reducirlos.
- Accesos directos al **Liberador de espacio**, al **Sensor de almacenamiento** y a los **Puntos de restauración** de Windows.

### 🧹 Limpieza por categorías

Cada categoría muestra su tamaño y viene marcada como **Seguro** (se puede borrar sin pensarlo) o **Revisar** (mejor mirar antes qué hay).

| Grupo | Qué limpia |
|---|---|
| **Sistema** | Temporales de usuario y de Windows, descargas de Windows Update, Optimización de distribución, volcados e informes de errores, miniaturas, cachés de GPU (DirectX, NVIDIA, AMD). |
| **Navegadores y apps** | Cachés de Chrome, Edge, Brave, Opera y Firefox **sin tocar contraseñas, historial ni sesiones**; cachés de apps Electron como VS Code, Cursor, Discord, Slack, Teams y Spotify. |
| **Desarrollo** | pip, uv, Conda, npm, yarn, pnpm, bun, Gradle, Android (AVD e imágenes del sistema), Maven, NuGet, Cargo, Go, PlatformIO, Electron, Playwright, Cypress, Unity y Visual Studio. |
| **IA / Modelos** | Hugging Face, Ollama, LM Studio, PyTorch Hub, Whisper, Keras, DeepFace, rembg, ModelScope, InsightFace, EasyOCR, GPT4All y Jan. |

### 📂 Analizar carpetas

Recorre `C:\` (o la carpeta que elijas) y muestra un **árbol ordenado por tamaño**, con el porcentaje que ocupa cada elemento respecto a su carpeta padre. Puedes abrir cualquier carpeta en el Explorador o borrarla con **clic derecho**.

### 📄 Archivos grandes

Los **1000 archivos más pesados** del último análisis, con filtro por tamaño mínimo (de 50 MB a 5 GB) y por extensión.

### 🤖 Modelos IA

- Modelos de **Ollama** con su nombre real, y borrado limpio con `ollama rm`.
- Todos los archivos `.gguf`, `.safetensors`, `.ckpt`, `.pt`, `.pth`, `.onnx`, `.bin` y `.h5` de **50 MB o más**, con su **origen probable**.

### 🧩 Aplicaciones

- Programas instalados (leídos del registro) con **tamaño, editor y fecha** de instalación.
- Botón para **calcular el tamaño real** en disco.
- Acceso al **desinstalador oficial** de cada programa.
- Búsqueda de **posibles restos** de 20 MB o más en `AppData`, `ProgramData` y Archivos de programa de aplicaciones que ya no están instaladas.

---

## 🛡 Seguridad

PC Free Space está pensado para que no puedas romper Windows por accidente:

- **Nada se borra sin ver antes la lista** completa y confirmar.
- Puedes elegir **Papelera** (recuperable) o **eliminar definitivamente**. Ojo: lo que va a la Papelera sigue ocupando espacio hasta que la vacías.
- **Rutas protegidas** que nunca se borran:
  - `C:\Windows`, salvo `Temp`, las descargas de Windows Update y los volcados de memoria.
  - La raíz de los discos.
  - `System Volume Information`, `Recovery`, `Boot`, `EFI` y `ProgramData\Microsoft`.
  - `pagefile.sys` y `hiberfil.sys`.
  - Las carpetas base de tu usuario (Escritorio, Documentos, Descargas…): se puede borrar su contenido, pero no la carpeta.
- En **Archivos de programa** avisa de que es mejor usar el desinstalador.
- **No sigue enlaces simbólicos ni *junctions***, así que no puede “escaparse” a otras carpetas.
- Los archivos de **OneDrive que solo están en la nube** cuentan 0 bytes (no ocupan disco).
- Los **archivos en uso se saltan** sin error.
- Los **restos de aplicaciones son una estimación**: revísalos antes de borrar.

---

## 📥 Descarga

1. Descarga **`PCFreeSpace.exe`** desde [Releases](../../releases/latest).
2. Ejecútalo. Es un **solo archivo** y **no requiere instalación**.

> [!NOTE]
> Windows SmartScreen puede avisar la primera vez porque el .exe no está firmado: pulsa **Más información → Ejecutar de todas formas**.

> [!TIP]
> Para limpiar los temporales de Windows y las descargas de Windows Update usa el botón **Reiniciar como admin** de la pestaña Resumen.

---

## 🛠 Instalación desde el código

Necesitas **Python 3.10 o superior**.

```powershell
git clone https://github.com/crazyramirez/PCFreeSpace.git
cd PCFreeSpace
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app\main.py
```

### Generar el .exe

- **En tu PC:** haz doble clic en `build.bat`. Al terminar tendrás `dist\PCFreeSpace.exe`.
- **Con GitHub Actions:** el workflow [`build.yml`](.github/workflows/build.yml) genera el .exe como *artifact* en cada push a `main` (pestaña *Actions* → *Artifacts*).

---

## 🚀 Uso rápido

1. **Resumen**: mira cuánto espacio libre tienes y si la Papelera o la hibernación ocupan mucho.
2. **Limpieza**: pulsa **Calcular espacio**, luego **Marcar las seguras** y por último **Limpiar seleccionadas**.
3. **Analizar carpetas**: busca qué carpetas ocupan más y bórralas con clic derecho si no las necesitas.
4. **Modelos IA** y **Archivos grandes**: localiza modelos y archivos enormes que ya no usas.
5. **Aplicaciones**: desinstala lo que sobra y revisa los posibles restos.

---

## 🧱 Estructura del proyecto

```text
PCFreeSpace/
├── app/
│   ├── core.py          # lógica: escaneo, categorías y borrado seguro (sin interfaz)
│   └── main.py          # interfaz gráfica con customtkinter
├── assets/
│   └── icon.ico         # icono de la app
├── docs/
│   └── hero.png         # imagen de portada del README
├── .github/workflows/
│   └── build.yml        # compila el .exe en GitHub Actions
├── build.bat            # genera dist\PCFreeSpace.exe en local
└── requirements.txt
```

**Tecnologías:** [Python](https://www.python.org/) · [customtkinter](https://github.com/TomSchimansky/CustomTkinter) · [Send2Trash](https://github.com/arsenetar/send2trash) · [PyInstaller](https://pyinstaller.org/)

---

## 📄 Licencia

[MIT](LICENSE) © 2026 crazyramirez
