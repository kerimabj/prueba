# Descargador de documentos

Descarga los documentos de los enlaces y te los da en un ZIP.

## Dónde poner los enlaces (cualquiera de las tres)

1. **`enlaces.txt`**: un enlace por línea.
2. **Carpeta `entrada/`**: sube ahí documentos que contengan enlaces (PDF, Word .docx, TXT, CSV, HTML, MD). El programa saca los enlaces de dentro.
3. **Botón manual**: pestaña **Actions → Descargar documentos → Run workflow**, y pega los enlaces en la casilla.

Con las opciones 1 y 2 se ejecuta solo al subir el cambio.

## Dónde recoger los documentos

Pestaña **Actions** → abre la última ejecución → abajo, en **Artifacts**, pulsa **documentos-descargados**. Baja un ZIP con:

- Los documentos.
- `_INFORME.csv`: qué enlace salió bien y cuál no (se abre en Excel).

El ZIP se guarda 7 días en GitHub.

## Qué hace y qué no

- No sobrescribe: si dos archivos se llaman igual, añade (1), (2)…
- No borra nada ni modifica el repositorio (permiso solo de lectura).
- Google Drive, Docs, Dropbox y OneDrive: convierte el enlace a descarga directa. Solo funciona si el archivo está compartido como «cualquiera con el enlace».
- Las páginas web normales y los enlaces que piden usuario y contraseña se marcan como «Omitido» en el informe.
- Límite: 200 MB por archivo.
