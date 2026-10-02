from abc import ABC, abstractmethod
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional
import pypdf

from app.core.config import get_settings
from app.core.exceptions import YavuraException
from app.core.logging import get_logger

logger = get_logger("yavura.knowledge.extraction")


class TextExtractionError(YavuraException):
    """Base exception for text extraction failures."""
    def __init__(self, message: str, code: str = "TEXT_EXTRACTION_FAILED"):
        super().__init__(message=message, code=code)


class DocumentEmptyError(TextExtractionError):
    """Raised when extracted document contains no textual content."""
    def __init__(self, message: str = "Document contains no extractable text."):
        super().__init__(message=message, code="DOCUMENT_EMPTY")


class OCRRequiredError(TextExtractionError):
    """Raised when PDF appears to be scanned or image-only, requiring OCR."""
    def __init__(self, message: str = "Document contains no extractable text. Scanned/image-only PDFs requiring OCR are not supported."):
        super().__init__(message=message, code="OCR_REQUIRED")


class UnsupportedFileTypeError(TextExtractionError):
    """Raised when uploaded file format is not supported."""
    def __init__(self, content_type: str):
        super().__init__(
            message=f"Unsupported file format '{content_type}'. Supported formats: TXT, PDF.",
            code="UNSUPPORTED_FILE_TYPE",
        )


class FileTooLargeError(YavuraException):
    """Raised when file exceeds maximum allowed size."""
    def __init__(self, size: int, max_size: int):
        super().__init__(
            message=f"File size ({size} bytes) exceeds maximum limit of {max_size} bytes.",
            code="FILE_TOO_LARGE",
        )


class InvalidFileError(YavuraException):
    """Raised when file signature or structure is invalid."""
    def __init__(self, message: str = "File signature does not match declared MIME type."):
        super().__init__(message=message, code="INVALID_FILE")


@dataclass
class ExtractedPage:
    page_number: int
    text: str


@dataclass
class ExtractedDocument:
    raw_text: str
    normalized_text: str
    pages: List[ExtractedPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def normalize_text(text: str) -> str:
    """
    Normalizes extracted document text for high-fidelity retrieval and citations.
    - Normalizes Unicode (NFKC)
    - Normalizes line endings (\r\n -> \n, \r -> \n)
    - Removes non-printable/control characters (preserving tabs and newlines)
    - Collapses repeated blank lines (>2 into 2)
    - Preserves structural elements (headings, paragraphs, bullet points, numbers)
    """
    if not text:
        return ""

    # Unicode normalization
    text = unicodedata.normalize("NFKC", text)

    # Line ending standardization
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Strip control characters (preserve \t, \n)
    text = "".join(ch for ch in text if ch in ("\n", "\t") or (ord(ch) >= 32 and ord(ch) != 127))

    # Collapse multiple horizontal whitespace within lines while preserving newlines
    lines = text.split("\n")
    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    text = "\n".join(cleaned_lines)

    # Collapse excessive blank lines (more than 2 consecutive newlines to 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


class TextExtractor(ABC):
    @abstractmethod
    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        pass


class PlainTextExtractor(TextExtractor):
    """Safe plain text extractor supporting valid UTF-8 text."""
    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        # Prevent binary files disguised as text
        if b"\x00" in content:
            raise InvalidFileError("Binary files containing null bytes cannot be ingested as plain text.")

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidFileError("File content is not valid UTF-8 plain text.")

        norm = normalize_text(text)
        if not norm:
            raise DocumentEmptyError("Text document is empty.")

        page = ExtractedPage(page_number=1, text=norm)
        return ExtractedDocument(
            raw_text=text,
            normalized_text=norm,
            pages=[page],
            metadata={"format": "txt", "char_count": len(norm)},
        )


class PDFTextExtractor(TextExtractor):
    """
    Safe PDF text extractor using pypdf.
    Extracts text page by page with structural metadata.
    Detects empty/scanned PDFs and explicitly raises OCRRequiredError.
    Enforces maximum allowed page limits to protect against resource exhaustion DoS.
    """
    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        # Validate PDF signature
        if not content.startswith(b"%PDF"):
            raise InvalidFileError("File does not start with valid PDF signature (%PDF).")

        settings = get_settings()

        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
        except Exception as e:
            logger.warning(f"PDF parsing error on '{filename}': {str(e)}")
            raise TextExtractionError(f"Malformed or unreadable PDF: {str(e)}", code="INVALID_PDF")

        if reader.is_encrypted:
            raise TextExtractionError("Password-protected or encrypted PDFs are not supported.", code="ENCRYPTED_PDF")

        page_count = len(reader.pages)
        if page_count > settings.MAX_DOCUMENT_PAGES:
            raise TextExtractionError(
                f"PDF page count ({page_count}) exceeds maximum allowable limit of {settings.MAX_DOCUMENT_PAGES} pages.",
                code="PAGE_LIMIT_EXCEEDED",
            )

        pages: List[ExtractedPage] = []
        raw_parts: List[str] = []

        for idx, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"Error extracting page {idx} of '{filename}': {str(e)}")
                page_text = ""

            page_norm = normalize_text(page_text)
            if page_norm:
                pages.append(ExtractedPage(page_number=idx, text=page_norm))
                raw_parts.append(page_norm)

        if not raw_parts:
            # Document exists, but no extractable text found (likely scanned or image-only)
            raise OCRRequiredError(
                "PDF contains no extractable text. Scanned or image-only documents requiring OCR are not supported in this version."
            )

        full_raw = "\n\n".join(raw_parts)
        full_norm = normalize_text(full_raw)

        if not full_norm:
            raise DocumentEmptyError("PDF contains only blank pages.")

        return ExtractedDocument(
            raw_text=full_raw,
            normalized_text=full_norm,
            pages=pages,
            metadata={
                "format": "pdf",
                "page_count": len(reader.pages),
                "extracted_page_count": len(pages),
                "char_count": len(full_norm),
            },
        )


class TextExtractionService:
    """Dispatches extraction based on verified MIME type and content."""
    def __init__(self):
        self._extractors = {
            "text/plain": PlainTextExtractor(),
            "application/pdf": PDFTextExtractor(),
        }

    def extract(self, content: bytes, content_type: str, filename: str) -> ExtractedDocument:
        extractor = self._extractors.get(content_type.lower())
        if not extractor:
            raise UnsupportedFileTypeError(content_type)
        return extractor.extract(content, filename)
