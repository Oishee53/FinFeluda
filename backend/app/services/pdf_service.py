"""
PDF text/table extraction. pymupdf (fitz) is the fast path; falls
back to OCR (pytesseract + pdf2image) only when pymupdf extracts
suspiciously little text, which signals a scanned/image-based PDF --
matches the spec's "extract text using OCR if necessary" requirement
without paying the OCR cost on every normal text-based PDF.
"""
import os
import tempfile
import logging
import fitz  # pymupdf
import pdfplumber

logger = logging.getLogger(__name__)

TEMP_PDF_DIR = os.path.join(tempfile.gettempdir(), "due_diligence_uploads")
os.makedirs(TEMP_PDF_DIR, exist_ok=True)

# If pymupdf extracts less than this many chars per page on average,
# assume it's a scanned PDF and fall back to OCR.
OCR_FALLBACK_CHARS_PER_PAGE = 50

# extract_text alone loses financial tables whenever a caller truncates
# the flat text (see content_fetch_utils.py's MAX_PDF_CHARS) --
# truncating from the start always keeps the cover page / AGM notice /
# chairman's message and drops the balance sheet / income statement that
# live 40-150 pages into a real annual report. This locates the pages
# that actually look like financial statements first (fast pymupdf
# keyword scan across all pages), then runs pdfplumber's much slower
# table extraction ONLY on those specific pages -- running pdfplumber
# over every page of a 200+ page report would be needlessly slow.
FINANCIAL_STATEMENT_KEYWORDS = [
    "balance sheet", "statement of financial position",
    "profit and loss", "income statement", "statement of comprehensive income",
    "statement of cash flows", "cash flow statement",
    "statement of changes in equity",
]
MAX_FINANCIAL_TABLE_PAGES = 25


def save_temp_pdf(content: bytes, filename: str) -> str:
    path = os.path.join(TEMP_PDF_DIR, filename)
    with open(path, "wb") as f:
        f.write(content)
    return path


def extract_text_and_financial_tables(file_path: str) -> tuple[str, str]:
    """
    Combined replacement for what used to be two separate functions
    (extract_text_from_pdf + extract_financial_tables) -- every real
    caller (gather_pdf_documents, content_fetch_utils._fetch_pdf) always
    needs both, and each used to open the file via fitz and iterate
    every page independently, doing the same page.get_text() work
    twice per PDF for no benefit. This does that pass once and reuses
    it for both the full text and the financial-statement keyword scan.

    Returns (full_text, financial_tables_text). financial_tables_text is
    "" if no financial-statement-looking pages were found.
    """
    doc = fitz.open(file_path)
    page_texts = [page.get_text() for page in doc]
    page_count = len(doc)
    doc.close()

    full_text = "\n".join(page_texts)
    avg_chars_per_page = len(full_text) / max(page_count, 1)

    if avg_chars_per_page < OCR_FALLBACK_CHARS_PER_PAGE:
        logger.info(
            "PDF %s looks scanned (%.0f chars/page) -- falling back to OCR",
            file_path, avg_chars_per_page,
        )
        ocr_text = _extract_text_via_ocr(file_path)
        if len(ocr_text.strip()) > len(full_text.strip()):
            full_text = ocr_text

    candidate_pages = [
        i for i, text in enumerate(page_texts)
        if any(kw in text.lower() for kw in FINANCIAL_STATEMENT_KEYWORDS)
    ][:MAX_FINANCIAL_TABLE_PAGES]

    tables_text = ""
    if candidate_pages:
        blocks = []
        with pdfplumber.open(file_path) as pdf:
            for i in candidate_pages:
                if i >= len(pdf.pages):
                    continue
                for table in pdf.pages[i].extract_tables():
                    rows = [" | ".join(cell or "" for cell in row) for row in table]
                    if rows:
                        blocks.append("\n".join(rows))
        tables_text = "\n\n".join(blocks)

    return full_text, tables_text


def _extract_text_via_ocr(file_path: str) -> str:
    """OCR fallback for scanned/image-based PDFs. Requires the
    tesseract-ocr and poppler-utils system packages to be installed
    in the deploy environment (Render/Hugging Face Spaces Dockerfile)."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        logger.warning("OCR libraries not available -- skipping OCR fallback")
        return ""

    try:
        images = convert_from_path(file_path)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as exc:
        logger.warning("OCR extraction failed for %s: %s", file_path, exc)
        return ""


# NOTE: chunking now lives in app/sources/chunking.py (chunk_text_by_boundary),
# which respects sentence/paragraph boundaries and sizes chunks per source
# confidence tier. The old flat chunk_text() here has been removed -- don't
# recreate a character-slicing chunker, it cuts facts off mid-sentence.
