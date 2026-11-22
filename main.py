"""File -> Markdown converter. Run: uvicorn main:app --reload"""
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from markitdown import MarkItDown

MAX_BYTES = 20 * 1024 * 1024  # 20 MB per file
ALLOWED = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".json", ".xml", ".epub", ".txt", ".zip",
}

# Token counting: tiktoken if available, rough estimate otherwise.
try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text, disallowed_special=()))

except Exception:  # offline or tiktoken missing

    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)


app = FastAPI(title="Markdown Converter")
converter = MarkItDown()
BASE = Path(__file__).parent


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/convert")
def convert(file: UploadFile = File(...)):
    # Plain `def` so FastAPI runs this in a threadpool (conversion is blocking).
    name = file.filename or "upload"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(
            415, f"{ext or 'This file type'} isn't supported. Try: {', '.join(sorted(ALLOWED))}"
        )

    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)} MB.")

    tmp_path = None
    try:
        # Write to a temp file, convert, then always delete it.
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        result = converter.convert(tmp_path)
        markdown = result.text_content or ""
    except Exception as exc:
        raise HTTPException(422, f"Couldn't convert this file: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if not markdown.strip():
        raise HTTPException(
            422, "No text found. If this is a scanned PDF or an image, it needs OCR first."
        )

    return {
        "filename": Path(name).stem + ".md",
        "markdown": markdown,
        "tokens": count_tokens(markdown),
        "chars": len(markdown),
        "source_bytes": len(data),
    }


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
