from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.rbac import Permission
from app.database.session import get_db
from app.knowledge.models import DocumentSourceType
from app.knowledge.retrieval import RetrievalService
from app.knowledge.schemas import (
    DocumentCreateTextRequest,
    DocumentResponse,
    DocumentVersionResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    RetrievalRequest,
    RetrievalResponse,
)
from app.knowledge.service import KnowledgeService
from app.users.models import User

router = APIRouter(tags=["Knowledge & RAG"])


# ==============================================================================
# KNOWLEDGE BASE ENDPOINTS
# ==============================================================================

@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Knowledge Base",
    description="Creates a new tenant-owned Knowledge Base collection. Requires 'knowledge:create'.",
)
async def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    service = KnowledgeService(db)
    kb = await service.create_knowledge_base(
        tenant_id=current_user.tenant_id,
        request=request,
        actor_id=current_user.id,
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.get(
    "/knowledge-bases",
    response_model=List[KnowledgeBaseResponse],
    status_code=status.HTTP_200_OK,
    summary="List Knowledge Bases",
    description="Lists all Knowledge Bases belonging to the authenticated tenant. Requires 'knowledge:read'.",
)
async def list_knowledge_bases(
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[KnowledgeBaseResponse]:
    service = KnowledgeService(db)
    rows = await service.list_knowledge_bases(tenant_id=current_user.tenant_id)
    responses = []
    for kb, count in rows:
        resp = KnowledgeBaseResponse.model_validate(kb)
        resp.document_count = count
        responses.append(resp)
    return responses


@router.get(
    "/knowledge-bases/{kb_id}",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Knowledge Base Details",
    description="Retrieves a specific Knowledge Base strictly within tenant boundary. Requires 'knowledge:read'.",
)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    service = KnowledgeService(db)
    kb = await service.get_knowledge_base(tenant_id=current_user.tenant_id, kb_id=kb_id)
    return KnowledgeBaseResponse.model_validate(kb)


@router.patch(
    "/knowledge-bases/{kb_id}",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Knowledge Base",
    description="Updates Knowledge Base name, description, or status. Requires 'knowledge:update'.",
)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    request: KnowledgeBaseUpdateRequest,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    service = KnowledgeService(db)
    kb = await service.update_knowledge_base(
        tenant_id=current_user.tenant_id,
        kb_id=kb_id,
        request=request,
        actor_id=current_user.id,
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.delete(
    "/knowledge-bases/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Knowledge Base",
    description="Deletes a Knowledge Base and all associated documents and embeddings. Requires 'knowledge:delete'.",
)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = KnowledgeService(db)
    await service.delete_knowledge_base(
        tenant_id=current_user.tenant_id,
        kb_id=kb_id,
        actor_id=current_user.id,
    )


# ==============================================================================
# DOCUMENT INGESTION & MANAGEMENT ENDPOINTS
# ==============================================================================

@router.post(
    "/knowledge-bases/{kb_id}/documents/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and Ingest Document",
    description="Ingests an uploaded document file (TXT, PDF). Validates, chunks, and embeds atomically. Requires 'knowledge:create'.",
)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    document_name: Optional[str] = Form(None),
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    service = KnowledgeService(db)
    file_bytes = await file.read()
    content_type = file.content_type or "application/octet-stream"

    doc = await service.ingest_document(
        tenant_id=current_user.tenant_id,
        kb_id=kb_id,
        filename=file.filename or "uploaded_file",
        content=file_bytes,
        content_type=content_type,
        source_type=DocumentSourceType.UPLOAD,
        document_name=document_name,
        actor_id=current_user.id,
    )
    return DocumentResponse.model_validate(doc)


@router.post(
    "/knowledge-bases/{kb_id}/documents/text",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Direct Text Document",
    description="Ingests direct text content into the Knowledge Base. Requires 'knowledge:create'.",
)
async def ingest_text_document(
    kb_id: uuid.UUID,
    request: DocumentCreateTextRequest,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    service = KnowledgeService(db)
    content_bytes = request.content.encode("utf-8")

    doc = await service.ingest_document(
        tenant_id=current_user.tenant_id,
        kb_id=kb_id,
        filename=f"{request.name}.txt",
        content=content_bytes,
        content_type="text/plain",
        source_type=DocumentSourceType.TEXT,
        document_name=request.name,
        actor_id=current_user.id,
    )
    return DocumentResponse.model_validate(doc)


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=List[DocumentResponse],
    status_code=status.HTTP_200_OK,
    summary="List Knowledge Base Documents",
    description="Lists all documents in a Knowledge Base. Requires 'knowledge:read'.",
)
async def list_documents(
    kb_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[DocumentResponse]:
    service = KnowledgeService(db)
    docs = await service.list_documents(tenant_id=current_user.tenant_id, kb_id=kb_id)
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Document Details",
    description="Retrieves a specific Document strictly within tenant boundary. Requires 'knowledge:read'.",
)
async def get_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    service = KnowledgeService(db)
    doc = await service.get_document(tenant_id=current_user.tenant_id, document_id=doc_id)
    return DocumentResponse.model_validate(doc)


@router.get(
    "/documents/{doc_id}/versions",
    response_model=List[DocumentVersionResponse],
    status_code=status.HTTP_200_OK,
    summary="List Document Versions",
    description="Retrieves audit history of all versions for a document. Requires 'knowledge:read'.",
)
async def list_document_versions(
    doc_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[DocumentVersionResponse]:
    service = KnowledgeService(db)
    versions = await service.list_document_versions(tenant_id=current_user.tenant_id, document_id=doc_id)
    return [DocumentVersionResponse.model_validate(v) for v in versions]


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Document",
    description="Deletes a Document, including its versions, chunks, and embeddings. Requires 'knowledge:delete'.",
)
async def delete_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = KnowledgeService(db)
    await service.delete_document(
        tenant_id=current_user.tenant_id,
        document_id=doc_id,
        actor_id=current_user.id,
    )


# ==============================================================================
# RETRIEVAL ENDPOINT (RAG FOUNDATION)
# ==============================================================================

@router.post(
    "/knowledge-bases/{kb_id}/retrieve",
    response_model=RetrievalResponse,
    status_code=status.HTTP_200_OK,
    summary="Semantic Knowledge Retrieval",
    description=(
        "Executes semantic similarity search over verified Knowledge Base documents. "
        "Returns citations with confidence evaluation (FOUND, LOW_CONFIDENCE, NOT_FOUND). "
        "Requires 'knowledge:retrieve'."
    ),
)
async def retrieve_knowledge(
    kb_id: uuid.UUID,
    request: RetrievalRequest,
    current_user: User = Depends(require_permission(Permission.KNOWLEDGE_RETRIEVE.value)),
    db: AsyncSession = Depends(get_db),
) -> RetrievalResponse:
    # Verify Knowledge Base belongs to authenticated tenant
    kb_service = KnowledgeService(db)
    await kb_service.get_knowledge_base(tenant_id=current_user.tenant_id, kb_id=kb_id)

    retrieval_service = RetrievalService(db)
    return await retrieval_service.retrieve(
        tenant_id=current_user.tenant_id,
        knowledge_base_id=kb_id,
        query=request.query,
        top_k=request.top_k,
        min_similarity=request.min_similarity,
    )
