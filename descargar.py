#!/usr/bin/env python3
"""
Descarga los documentos enlazados en:
  - enlaces.txt  (una URL por línea; las líneas que empiezan por # se ignoran)
  - cualquier archivo dentro de la carpeta entrada/ (.txt, .md, .csv, .html, .htm, .pdf, .docx)

Los archivos se guardan en descargas/ y se genera descargas/_INFORME.csv
con el resultado de cada enlace.

Nunca sobrescribe: si un nombre ya existe, añade (1), (2)...
No borra nada.
"""

import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import requests

RAIZ = Path(__file__).resolve().parent
ARCHIVO_ENLACES = RAIZ / "enlaces.txt"
CARPETA_ENTRADA = RAIZ / "entrada"
CARPETA_SALIDA = RAIZ / "descargas"

TAMANO_MAXIMO = 200 * 1024 * 1024  # 200 MB por archivo
TIEMPO_ESPERA = 60  # segundos
PATRON_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
CABECERAS = {"User-Agent": "Mozilla/5.0 (descargador de documentos)"}


# ---------- 1. Recoger enlaces ----------

def limpiar_url(url: str) -> str:
    return url.rstrip(".,;:!?»”’")


def urls_de_texto(texto: str) -> list[str]:
    return [limpiar_url(u) for u in PATRON_URL.findall(texto)]


def urls_de_pdf(ruta: Path) -> list[str]:
    from pypdf import PdfReader

    urls = []
    lector = PdfReader(str(ruta))
    for pagina in lector.pages:
        urls += urls_de_texto(pagina.extract_text() or "")
        for anot in pagina.get("/Annots") or []:
            obj = anot.get_object()
            accion = obj.get("/A")
            if accion and accion.get("/URI"):
                urls.append(str(accion["/URI"]))
    return urls


def urls_de_docx(ruta: Path) -> list[str]:
    from docx import Document

    doc = Document(str(ruta))
    urls = [rel.target_ref for rel in doc.part.rels.values()
            if "hyperlink" in rel.reltype and rel.target_ref.startswith("http")]
    texto = "\n".join(p.text for p in doc.paragraphs)
    for tabla in doc.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                texto += "\n" + celda.text
    return urls + urls_de_texto(texto)


def urls_de_archivo(ruta: Path) -> list[str]:
    ext = ruta.suffix.lower()
    try:
        if ext == ".pdf":
            return urls_de_pdf(ruta)
        if ext == ".docx":
            return urls_de_docx(ruta)
        if ext in {".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json"}:
            return urls_de_texto(ruta.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:  # un archivo dañado no para el resto
        print(f"  ! No se pudo leer {ruta.name}: {e}")
    return []


def recoger_enlaces() -> list[tuple[str, str]]:
    """Devuelve [(url, origen)] sin duplicados, en el orden en que aparecen."""
    encontrados = []
    if ARCHIVO_ENLACES.exists():
        for linea in ARCHIVO_ENLACES.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#"):
                encontrados += [(u, "enlaces.txt") for u in urls_de_texto(linea)]
    extra = os.environ.get("ENLACES_EXTRA", "")
    encontrados += [(u, "formulario") for u in urls_de_texto(extra)]
    if CARPETA_ENTRADA.exists():
        for ruta in sorted(CARPETA_ENTRADA.rglob("*")):
            if ruta.is_file() and not ruta.name.startswith("."):
                encontrados += [(u, ruta.name) for u in urls_de_archivo(ruta)]

    vistos, unicos = set(), []
    for url, origen in encontrados:
        if url not in vistos:
            vistos.add(url)
            unicos.append((url, origen))
    return unicos


# ---------- 2. Ajustar enlaces de servicios conocidos ----------

def url_directa(url: str) -> str:
    p = urlparse(url)
    host = p.netloc.lower()
    # Google Drive: /file/d/ID/view  o  open?id=ID
    if "drive.google.com" in host:
        m = re.search(r"/file/d/([^/]+)", p.path)
        id_ = m.group(1) if m else parse_qs(p.query).get("id", [None])[0]
        if id_:
            return f"https://drive.usercontent.google.com/download?id={id_}&export=download&confirm=t"
    # Google Docs/Sheets/Slides -> exportar a PDF
    m = re.search(r"docs\.google\.com/(document|spreadsheets|presentation)/d/([^/]+)", url)
    if m:
        return f"https://docs.google.com/{m.group(1)}/d/{m.group(2)}/export?format=pdf"
    # Dropbox: forzar descarga
    if "dropbox.com" in host:
        return re.sub(r"([?&])dl=0", r"\1dl=1", url) if "dl=0" in url else url + ("&" if "?" in url else "?") + "dl=1"
    # OneDrive / SharePoint: forzar descarga
    if "sharepoint.com" in host or "1drv.ms" in host or "onedrive.live.com" in host:
        return url + ("&" if "?" in url else "?") + "download=1"
    return url


# ---------- 3. Descargar ----------

def nombre_seguro(nombre: str) -> str:
    nombre = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", nombre).strip(" .")
    return nombre[:150] or "documento"


def nombre_desde_respuesta(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.IGNORECASE) or \
        re.search(r'filename="?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return nombre_seguro(unquote(m.group(1)))
    ultimo = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    return nombre_seguro(ultimo)


def ruta_libre(nombre: str) -> Path:
    """No sobrescribe nunca: si existe, añade (1), (2)..."""
    ruta = CARPETA_SALIDA / nombre
    base, ext = os.path.splitext(nombre)
    n = 1
    while ruta.exists():
        ruta = CARPETA_SALIDA / f"{base} ({n}){ext}"
        n += 1
    return ruta


def descargar(url: str) -> tuple[str, str, int]:
    """Devuelve (estado, archivo, bytes)."""
    directa = url_directa(url)
    try:
        with requests.get(directa, headers=CABECERAS, stream=True,
                          timeout=TIEMPO_ESPERA, allow_redirects=True) as r:
            if r.status_code != 200:
                return f"Error HTTP {r.status_code}", "", 0
            tipo = r.headers.get("Content-Type", "").lower()
            if "text/html" in tipo:
                return "Omitido: es una página web, no un documento (o pide inicio de sesión)", "", 0
            nombre = nombre_desde_respuesta(r, r.url)
            if "." not in nombre:
                ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png",
                       "application/zip": ".zip"}.get(tipo.split(";")[0], "")
                nombre += ext
            destino = ruta_libre(nombre)
            total = 0
            with open(destino, "wb") as f:
                for trozo in r.iter_content(chunk_size=1024 * 256):
                    total += len(trozo)
                    if total > TAMANO_MAXIMO:
                        f.close()
                        destino.rename(destino.with_name(destino.name + ".INCOMPLETO"))
                        return "Omitido: supera 200 MB", destino.name + ".INCOMPLETO", total
                    f.write(trozo)
            return "OK", destino.name, total
    except requests.RequestException as e:
        return f"Error de conexión: {e.__class__.__name__}", "", 0


def main() -> int:
    CARPETA_SALIDA.mkdir(exist_ok=True)
    enlaces = recoger_enlaces()
    if not enlaces:
        print("No hay enlaces. Añádelos a enlaces.txt o pon documentos en entrada/.")
        return 1

    print(f"Enlaces encontrados: {len(enlaces)}\n")
    filas, correctos = [], 0
    for i, (url, origen) in enumerate(enlaces, 1):
        print(f"[{i}/{len(enlaces)}] {url}")
        estado, archivo, tam = descargar(url)
        print(f"    -> {estado} {archivo}")
        correctos += estado == "OK"
        filas.append([i, origen, url, estado, archivo, round(tam / 1024, 1)])

    with open(CARPETA_SALIDA / "_INFORME.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["N.º", "Origen", "Enlace", "Resultado", "Archivo", "Tamaño (KB)"])
        w.writerows(filas)

    print(f"\nDescargados: {correctos} de {len(enlaces)}. Detalle en descargas/_INFORME.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
