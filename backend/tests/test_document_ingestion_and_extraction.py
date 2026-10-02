import io
import uuid
import pytest
import pypdf
from httpx import AsyncClient

from app.core.security import create_access_token
from app.knowledge.chunking import ChunkingService
from app.knowledge.extraction import (
    DocumentEmptyError,
    ExtractedDocument,
    ExtractedPage,
    InvalidFileError,
    OCRRequiredError,
    PDFTextExtractor,
    PlainTextExtractor,
    UnsupportedFileTypeError,
    normalize_text,
)


def create_sample_pdf(pages_text: list[str]) -> bytes:
    """Helper creating an in-memory PDF using pypdf with specific page contents."""
    writer = pypdf.PdfWriter()
    for text in pages_text:
        # Create a page and add text annotation or stream
        page = writer.add_blank_page(width=612, height=792)
        # In pypdf, to add extractable text, write text onto page
        # Alternative: use pypdf's canvas or annotation or page content stream
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ==============================================================================
# 1. TEXT EXTRACTION UNIT TESTS
# ==============================================================================

def test_plain_text_extraction_and_normalization():
    extractor = PlainTextExtractor()
    sample = "Hello   world!\r\n\r\n\r\n\r\nThis is a paragraph.\x07"
    doc = extractor.extract(sample.encode("utf-8"), "test.txt")

    assert "Hello world!" in doc.normalized_text
    assert "\r" not in doc.normalized_text
    assert "\x07" not in doc.normalized_text
    assert len(doc.pages) == 1
    assert doc.pages[0].page_number == 1


def test_empty_text_raises_error():
    extractor = PlainTextExtractor()
    with pytest.raises(DocumentEmptyError):
        extractor.extract(b"   \n\n\t  ", "empty.txt")


def test_pdf_invalid_signature_raises_error():
    extractor = PDFTextExtractor()
    with pytest.raises(InvalidFileError):
        extractor.extract(b"NOT_A_PDF_FILE", "fake.pdf")


def test_pdf_scanned_image_only_raises_ocr_required():
    """
    SECTION 9: Explicit OCR Detection.
    If a PDF contains no extractable text (e.g. blank/scanned pages),
    must raise OCRRequiredError rather than pretending extraction succeeded.
    """
    extractor = PDFTextExtractor()
    # Create blank PDF
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    with pytest.raises(OCRRequiredError):
        extractor.extract(pdf_bytes, "scanned.pdf")


# ==============================================================================
# 2. CHUNKING UNIT TESTS
# ==============================================================================

def test_chunking_service_deterministic_output():
    service = ChunkingService(chunk_size=100, chunk_overlap=20)
    text = (
        "YAVURA provides enterprise conversational AI agents. "
        "The system strictly prevents hallucinations by verifying all business facts. "
        "Every price, discount, policy, and deadline must be grounded in verified documentation. "
        "If verified knowledge is absent, the agent must decline to guess."
    )
    doc = ExtractedDocument(raw_text=text, normalized_text=text, pages=[ExtractedPage(1, text)])
    chunks1 = service.chunk_document(doc)
    chunks2 = service.chunk_document(doc)

    assert len(chunks1) > 1
    # Verify deterministic output
    assert [c.content_hash for c in chunks1] == [c.content_hash for c in chunks2]
    assert [c.chunk_index for c in chunks1] == list(range(len(chunks1)))
    assert all(c.metadata["page_number"] == 1 for c in chunks1)


# ==============================================================================
# 3. END-TO-END DOCUMENT INGESTION API TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_text_document_ingestion_api(async_client: AsyncClient, seed_tenants):
    """
    Verifies ingesting a direct text document into a Knowledge Base.
    Generates chunks, embeddings, and sets status to READY.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create KB
    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Text Ingestion Test KB"},
    )
    kb_id = kb_res.json()["id"]

    # 2. Ingest text document
    doc_payload = {
        "name": "Refund Policy 2026",
        "content": (
            "YAVURA Refund Policy:\n"
            "Customers may request a full refund within 30 days of initial subscription purchase.\n"
            "After 30 days, subscriptions are non-refundable.\n"
            "Enterprise tier plans require 60 days written notice for cancellation."
        ),
    }
    doc_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/text",
        headers=headers,
        json=doc_payload,
    )
    assert doc_res.status_code == 201
    doc_data = doc_res.json()
    assert doc_data["name"] == "Refund Policy 2026"
    assert doc_data["status"] == "ready"
    assert doc_data["current_version_id"] is not None
    doc_id = doc_data["id"]

    # 3. List versions
    versions_res = await async_client.get(f"/api/v1/documents/{doc_id}/versions", headers=headers)
    assert versions_res.status_code == 200
    versions = versions_res.json()
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["processing_status"] == "completed"


@pytest.mark.asyncio
async def test_file_upload_document_ingestion_api(async_client: AsyncClient, seed_tenants):
    """
    Verifies multipart file upload document ingestion (TXT).
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "File Upload KB"},
    )
    kb_id = kb_res.json()["id"]

    file_content = b"Pricing tiers:\nStandard: $99/mo\nProfessional: $299/mo\nEnterprise: Custom quote."
    files = {"file": ("pricing_guide.txt", file_content, "text/plain")}

    upload_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files=files,
    )
    assert upload_res.status_code == 201
    assert upload_res.json()["status"] == "ready"
    assert upload_res.json()["original_filename"] == "pricing_guide.txt"


@pytest.mark.asyncio
async def test_file_upload_security_validations(async_client: AsyncClient, seed_tenants):
    """
    SECTION 7: File Security Validations:
    - Unsupported file type rejected
    - Path traversal filenames sanitized
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Security Validation KB"},
    )
    kb_id = kb_res.json()["id"]

    # 1. Unsupported executable MIME type
    unsupported_files = {"file": ("payload.exe", b"MZ\x90\x00executable", "application/x-msdownload")}
    res1 = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files=unsupported_files,
    )
    assert res1.status_code == 400
    assert "unsupported" in res1.json()["detail"].lower()

    # 2. Path traversal in filename: ../../../../etc/passwd.txt
    traversal_files = {"file": ("../../../../etc/passwd.txt", b"Safe text content here.", "text/plain")}
    res2 = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files=traversal_files,
    )
    assert res2.status_code == 201
    # Filename must be sanitized, path traversal stripped
    stored_filename = res2.json()["original_filename"]
    assert "/" not in stored_filename
    assert "\\" not in stored_filename
    assert "passwd.txt" in stored_filename


@pytest.mark.asyncio
async def test_cross_tenant_document_isolation(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL SECURITY TEST:
    Tenant A cannot read, list, or delete documents belonging to Tenant B.
    """
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=user_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant B creates KB and Document
    kb_b_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers_b,
        json={"name": "Tenant B Confidential KB"},
    )
    kb_b_id = kb_b_res.json()["id"]

    doc_b_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_b_id}/documents/text",
        headers=headers_b,
        json={"name": "Tenant B Internal Document", "content": "Confidential Tenant B numbers."},
    )
    doc_b_id = doc_b_res.json()["id"]

    # 1. Tenant A attempts to list Tenant B's documents -> 404 (KB not found in Tenant A)
    list_res = await async_client.get(
        f"/api/v1/knowledge-bases/{kb_b_id}/documents",
        headers=headers_a,
    )
    assert list_res.status_code == 404

    # 2. Tenant A attempts to GET Tenant B's document by ID -> 404 Not Found
    get_res = await async_client.get(
        f"/api/v1/documents/{doc_b_id}",
        headers=headers_a,
    )
    assert get_res.status_code == 404

    # 3. Tenant A attempts to DELETE Tenant B's document by ID -> 404 Not Found
    del_res = await async_client.delete(
        f"/api/v1/documents/{doc_b_id}",
        headers=headers_a,
    )
    assert del_res.status_code == 404


@pytest.mark.asyncio
async def test_reingest_creates_new_document_version_increment(async_client: AsyncClient, seed_tenants):
    """
    SECTION 11: DOCUMENT VERSIONING AUDIT
    Verifies that re-ingesting a document with the same name increments version_number
    (v1 -> v2) on the same Document entity, preserving immutable version history.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Version Tracking KB"},
    )
    kb_id = kb_res.json()["id"]

    # 1. Ingest Version 1
    v1_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/text",
        headers=headers,
        json={"name": "Company Handbook", "content": "Handbook Version 1 text."},
    )
    assert v1_res.status_code == 201
    doc_id = v1_res.json()["id"]

    # 2. Ingest Version 2 with same name
    v2_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/text",
        headers=headers,
        json={"name": "Company Handbook", "content": "Handbook Version 2 updated text."},
    )
    assert v2_res.status_code == 201
    assert v2_res.json()["id"] == doc_id  # Same document entity

    # 3. Verify version list
    versions_res = await async_client.get(
        f"/api/v1/documents/{doc_id}/versions",
        headers=headers,
    )
    assert versions_res.status_code == 200
    versions = versions_res.json()
    assert len(versions) == 2
    version_numbers = {v["version_number"] for v in versions}
    assert version_numbers == {1, 2}
    assert all(v["processing_status"] == "completed" for v in versions)


@pytest.mark.asyncio
async def test_null_byte_binary_upload_rejected(async_client: AsyncClient, seed_tenants):
    """
    SECTION 8: FILE SECURITY AUDIT
    Verifies that binary files containing null bytes are strictly rejected
    and cannot bypass plain text validation.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Binary Guard KB"},
    )
    kb_id = kb_res.json()["id"]

    # Binary payload containing null bytes disguised as .txt
    binary_payload = b"Fake text header\x00\x01\x02\xffbinary executable code"
    files = {"file": ("malicious.txt", binary_payload, "text/plain")}

    res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files=files,
    )
    assert res.status_code == 400
    assert "null bytes" in res.json()["detail"].lower()
