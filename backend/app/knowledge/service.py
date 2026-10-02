import hashlib
import os
import re
from typing import List, Optional, Tuple
import uuid
from fastapi import HTTPException, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import (
    ResourceNotFoundError,
    TenantIsolationError,
    YavuraException,
)
from app.core.logging import get_logger
from app.knowledge.chunking import ChunkingService
from app.knowledge.embeddings import (
    EmbeddingDimensionMismatchError,
    EmbeddingProvider,
    EmbeddingProviderFactory,
)
from app.knowledge.extraction import (
    FileTooLargeError,
    InvalidFileError,
    OCRRequiredError,
    TextExtractionError,
    TextExtractionService,
    UnsupportedFileTypeError,
)
from app.knowledge.models import (
    Document,
    DocumentChunk,
    DocumentSourceType,
    DocumentStatus,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    KnowledgeBaseStatus,
    ProcessingStatus,
)
from app.knowledge.schemas import (
    DocumentCreateTextRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
)
from app.models.audit import AuditLog

logger = get_logger("yavura.knowledge.service")


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes untrusted user filenames to prevent directory traversal and path manipulation.
    Strips directory separators, null bytes, and non-printable characters.
    """
    if not filename:
        return "unnamed_document.txt"

    # Strip directory paths
    base = os.path.basename(filename).replace("\\", "/").split("/")[-1]
    # Remove control characters and null bytes
    cleaned = "".join(ch for ch in base if ord(ch) >= 32 and ch not in ('\0', '<', '>', ':', '"', '|', '?', '*'))
    cleaned = cleaned.strip(". ")
    if not cleaned:
        return "unnamed_document.txt"
    return cleaned[:255]


class KnowledgeService:
    """
    Domain service orchestrating Knowledge Base management, secure document ingestion,
    text extraction, chunking, and vector persistence with strict tenant isolation.
    """
    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.extraction_service = TextExtractionService()
        self.chunking_service = ChunkingService()
        self.embedding_provider = embedding_provider or EmbeddingProviderFactory.get_provider()

    # ==========================================================================
    # KNOWLEDGE BASE OPERATIONS
    # ==========================================================================

    async def create_knowledge_base(
        self,
        tenant_id: uuid.UUID,
        request: KnowledgeBaseCreateRequest,
        actor_id: Optional[uuid.UUID] = None,
    ) -> KnowledgeBase:
        """Creates a new tenant-owned Knowledge Base."""
        name = request.name.strip()

        # Check duplicate name within tenant
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.name == name,
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Knowledge base with name '{name}' already exists in your organization.",
            )

        kb = KnowledgeBase(
            tenant_id=tenant_id,
            name=name,
            description=request.description.strip() if request.description else None,
            status=KnowledgeBaseStatus.ACTIVE.value,
        )
        self.db.add(kb)
        await self.db.flush()

        audit = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="knowledge_base.created",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
            details={"name": kb.name},
        )
        self.db.add(audit)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def get_knowledge_base(
        self,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> KnowledgeBase:
        """Retrieves a specific Knowledge Base strictly within tenant boundary."""
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == tenant_id,
        )
        kb = (await self.db.execute(stmt)).scalar_one_or_none()
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge base not found.",
            )
        return kb

    async def list_knowledge_bases(
        self,
        tenant_id: uuid.UUID,
    ) -> List[Tuple[KnowledgeBase, int]]:
        """Lists all Knowledge Bases for a tenant with document counts."""
        stmt = (
            select(
                KnowledgeBase,
                func.count(Document.id).label("doc_count"),
            )
            .outerjoin(Document, Document.knowledge_base_id == KnowledgeBase.id)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .group_by(KnowledgeBase.id)
            .order_by(KnowledgeBase.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def update_knowledge_base(
        self,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        request: KnowledgeBaseUpdateRequest,
        actor_id: Optional[uuid.UUID] = None,
    ) -> KnowledgeBase:
        """Updates Knowledge Base metadata strictly within tenant boundary."""
        kb = await self.get_knowledge_base(tenant_id, kb_id)

        if request.name is not None:
            new_name = request.name.strip()
            if new_name != kb.name:
                # Check uniqueness
                dup_stmt = select(KnowledgeBase).where(
                    KnowledgeBase.tenant_id == tenant_id,
                    KnowledgeBase.name == new_name,
                    KnowledgeBase.id != kb_id,
                )
                if (await self.db.execute(dup_stmt)).scalar_one_or_none():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Knowledge base with name '{new_name}' already exists.",
                    )
                kb.name = new_name

        if request.description is not None:
            kb.description = request.description.strip() if request.description else None

        if request.status is not None:
            kb.status = request.status

        audit = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="knowledge_base.updated",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
            details={"status": kb.status, "name": kb.name},
        )
        self.db.add(audit)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def delete_knowledge_base(
        self,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Deletes a Knowledge Base and cascades deletion of all documents, chunks, and embeddings."""
        kb = await self.get_knowledge_base(tenant_id, kb_id)

        audit = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="knowledge_base.deleted",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
            details={"name": kb.name},
        )
        self.db.add(audit)
        await self.db.delete(kb)
        await self.db.commit()

    # ==========================================================================
    # DOCUMENT INGESTION & MANAGEMENT
    # ==========================================================================

    async def ingest_document(
        self,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str,
        source_type: DocumentSourceType = DocumentSourceType.UPLOAD,
        document_name: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Document:
        """
        Executes the full modular document ingestion pipeline:
        Validation -> Version Creation -> Text Extraction -> Normalization -> Chunking -> Embedding -> Persistence
        """
        # 1. Verify Knowledge Base exists and is active within tenant
        kb = await self.get_knowledge_base(tenant_id, kb_id)
        if kb.status != KnowledgeBaseStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot ingest documents into an archived knowledge base.",
            )

        # 2. File size validation
        size = len(content)
        if size > self.settings.MAX_UPLOAD_SIZE_BYTES:
            raise FileTooLargeError(size, self.settings.MAX_UPLOAD_SIZE_BYTES)
        if size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

        # 3. Filename sanitation & validation
        safe_filename = sanitize_filename(filename)
        doc_name = (document_name or safe_filename).strip()

        # 4. Content Type & Signature validation
        clean_content_type = content_type.lower().split(";")[0].strip()
        if clean_content_type not in self.settings.ALLOWED_DOCUMENT_TYPES:
            # Fallback check based on extension
            if safe_filename.endswith(".txt") and clean_content_type in ("text/plain", "application/octet-stream"):
                clean_content_type = "text/plain"
            elif safe_filename.endswith(".pdf") and clean_content_type in ("application/pdf", "application/octet-stream"):
                clean_content_type = "application/pdf"
            else:
                raise UnsupportedFileTypeError(clean_content_type)

        # 5. Compute content hash
        content_hash = hashlib.sha256(content).hexdigest()

        # 6. Initialize Document and DocumentVersion entities
        stmt = (
            select(Document)
            .where(
                and_(
                    Document.tenant_id == tenant_id,
                    Document.knowledge_base_id == kb.id,
                    Document.name == doc_name,
                )
            )
            .options(selectinload(Document.versions))
        )
        res = await self.db.execute(stmt)
        existing_doc = res.scalar_one_or_none()

        if existing_doc:
            doc = existing_doc
            doc.status = DocumentStatus.PROCESSING.value
            doc.original_filename = safe_filename
            doc.content_type = clean_content_type
            doc.source_type = source_type.value
            version_number = (max([v.version_number for v in doc.versions], default=0)) + 1
        else:
            doc = Document(
                tenant_id=tenant_id,
                knowledge_base_id=kb.id,
                name=doc_name,
                original_filename=safe_filename,
                content_type=clean_content_type,
                source_type=source_type.value,
                status=DocumentStatus.PROCESSING.value,
                created_by=actor_id,
            )
            self.db.add(doc)
            await self.db.flush()
            version_number = 1

        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=doc.id,
            version_number=version_number,
            content_hash=content_hash,
            processing_status=ProcessingStatus.PROCESSING.value,
            created_by=actor_id,
        )
        self.db.add(version)
        await self.db.flush()

        try:
            # 7. Extract text safely
            extracted = self.extraction_service.extract(content, clean_content_type, safe_filename)
            version.extracted_text_hash = hashlib.sha256(extracted.normalized_text.encode("utf-8")).hexdigest()

            # 8. Chunk text
            raw_chunks = self.chunking_service.chunk_document(extracted)
            if not raw_chunks:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document produced zero text chunks.")

            # 9. Batch generate embeddings
            chunk_texts = [c.content for c in raw_chunks]
            embeddings = await self.embedding_provider.embed_texts(chunk_texts)

            # 10. Persist chunks and embeddings
            for raw_chunk, emb_vector in zip(raw_chunks, embeddings):
                if len(emb_vector) != self.settings.EMBEDDING_DIMENSION:
                    raise EmbeddingDimensionMismatchError(self.settings.EMBEDDING_DIMENSION, len(emb_vector))

                chunk_record = DocumentChunk(
                    tenant_id=tenant_id,
                    knowledge_base_id=kb.id,
                    document_id=doc.id,
                    document_version_id=version.id,
                    chunk_index=raw_chunk.chunk_index,
                    content=raw_chunk.content,
                    content_hash=raw_chunk.content_hash,
                    token_count=raw_chunk.token_count,
                    chunk_metadata=raw_chunk.metadata,
                )
                self.db.add(chunk_record)
                await self.db.flush()

                emb_record = Embedding(
                    tenant_id=tenant_id,
                    document_chunk_id=chunk_record.id,
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                    dimension=self.embedding_provider.dimension,
                    vector=emb_vector,
                )
                self.db.add(emb_record)

            # 11. Finalize Document and Version status
            version.processing_status = ProcessingStatus.COMPLETED.value
            doc.status = DocumentStatus.READY.value
            doc.current_version_id = version.id

            audit = AuditLog(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="document.ingested",
                resource_type="document",
                resource_id=str(doc.id),
                details={
                    "filename": safe_filename,
                    "chunks_count": len(raw_chunks),
                    "version_number": version.version_number,
                },
            )
            self.db.add(audit)

            await self.db.commit()
            await self.db.refresh(doc)
            logger.info(f"Successfully ingested document {doc.id} with {len(raw_chunks)} chunks for tenant {tenant_id}")
            return doc

        except Exception as e:
            await self.db.rollback()
            # Record failure status
            err_code = getattr(e, "code", "INGESTION_FAILED")
            err_msg = str(e)
            logger.error(f"Ingestion failed for document '{safe_filename}' (tenant {tenant_id}): {err_msg}", exc_info=True)

            # Update document to FAILED in a clean transaction
            doc.status = DocumentStatus.FAILED.value
            version.processing_status = ProcessingStatus.FAILED.value
            version.error_code = err_code
            version.error_message = err_msg

            self.db.add(doc)
            self.db.add(version)
            await self.db.commit()
            await self.db.refresh(doc)

            if isinstance(e, YavuraException):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
            elif isinstance(e, HTTPException):
                raise e
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Document processing failed: {err_msg}",
                )

    async def get_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> Document:
        """Retrieves a specific Document strictly within tenant boundary."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
        doc = (await self.db.execute(stmt)).scalar_one_or_none()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )
        return doc

    async def list_documents(
        self,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> List[Document]:
        """Lists all documents in a Knowledge Base strictly within tenant boundary."""
        # Verify KB ownership
        await self.get_knowledge_base(tenant_id, kb_id)

        stmt = (
            select(Document)
            .where(
                Document.knowledge_base_id == kb_id,
                Document.tenant_id == tenant_id,
            )
            .order_by(Document.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_document_versions(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> List[DocumentVersion]:
        """Lists historical audit versions of a document strictly within tenant boundary."""
        # Verify Document ownership
        await self.get_document(tenant_id, document_id)

        stmt = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.tenant_id == tenant_id,
            )
            .order_by(DocumentVersion.version_number.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def delete_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Deletes a Document and cascades deletion of versions, chunks, and embeddings."""
        doc = await self.get_document(tenant_id, document_id)

        audit = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="document.deleted",
            resource_type="document",
            resource_id=str(doc.id),
            details={"name": doc.name},
        )
        self.db.add(audit)
        await self.db.delete(doc)
        await self.db.commit()
