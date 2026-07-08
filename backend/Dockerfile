FROM python:3.11-slim

# tesseract-ocr / poppler-utils: system packages pytesseract and pdf2image
# need for the OCR fallback path (scanned PDFs) -- pip alone can't install
# these, they have to come from apt. build-essential covers native builds
# some Python packages fall back to when a prebuilt wheel isn't available
# for this platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime -- must bind to it, not a hardcoded port.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
