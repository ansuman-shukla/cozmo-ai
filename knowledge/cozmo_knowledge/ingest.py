"""Knowledge ingestion entrypoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from .chunker import chunk_documents, chunk_text
from .models import KnowledgeDocument, KnowledgeFaqItem, KnowledgeFileInput


def faq_items_to_documents(
    *,
    collection_name: str,
    document_prefix: str,
    faq_items: Sequence[KnowledgeFaqItem],
) -> list[KnowledgeDocument]:
    """Normalize FAQ entries into text documents."""

    documents: list[KnowledgeDocument] = []
    for index, item in enumerate(faq_items):
        item_id = item.item_id or f"{document_prefix}:faq:{index}"
        documents.append(
            KnowledgeDocument(
                document_id=item_id,
                collection_name=collection_name,
                title=item.question.strip(),
                text=f"Question: {item.question.strip()}\nAnswer: {item.answer.strip()}",
                source_type="faq",
                metadata={**item.metadata, "question": item.question.strip()},
            )
        )
    return documents


def parse_file_content(
    *,
    collection_name: str,
    file_input: KnowledgeFileInput,
) -> list[KnowledgeDocument]:
    """Normalize a file-like payload into one or more text documents."""

    suffix = Path(file_input.file_name).suffix.lower()
    metadata = {**file_input.metadata, "file_name": file_input.file_name}
    if suffix == ".json":
        parsed = json.loads(file_input.content)
        if isinstance(parsed, list) and all(
            isinstance(item, dict) and "question" in item and "answer" in item for item in parsed
        ):
            faq_items = [
                KnowledgeFaqItem(
                    question=str(item["question"]),
                    answer=str(item["answer"]),
                    item_id=str(item.get("item_id", "") or "") or None,
                    metadata={k: v for k, v in item.items() if k not in {"question", "answer", "item_id"}},
                )
                for item in parsed
            ]
            return faq_items_to_documents(
                collection_name=collection_name,
                document_prefix=file_input.document_id,
                faq_items=faq_items,
            )
        if isinstance(parsed, dict):
            candidate_items = parsed.get("items") or parsed.get("faqs")
            if isinstance(candidate_items, list) and all(
                isinstance(item, dict) and "question" in item and "answer" in item for item in candidate_items
            ):
                faq_items = [
                    KnowledgeFaqItem(
                        question=str(item["question"]),
                        answer=str(item["answer"]),
                        item_id=str(item.get("item_id", "") or "") or None,
                        metadata={
                            k: v for k, v in item.items() if k not in {"question", "answer", "item_id"}
                        },
                    )
                    for item in candidate_items
                ]
                return faq_items_to_documents(
                    collection_name=collection_name,
                    document_prefix=file_input.document_id,
                    faq_items=faq_items,
                )
            text = json.dumps(parsed, indent=2, sort_keys=True)
        else:
            text = json.dumps(parsed, indent=2, sort_keys=True)
    else:
        text = file_input.content

    return [
        KnowledgeDocument(
            document_id=file_input.document_id,
            collection_name=collection_name,
            title=file_input.file_name,
            text=text.strip(),
            source_type="file",
            metadata=metadata,
        )
    ]


def build_documents_from_payload(
    *,
    collection_name: str,
    documents: Sequence[KnowledgeDocument] = (),
    faq_items: Sequence[KnowledgeFaqItem] = (),
    files: Sequence[KnowledgeFileInput] = (),
) -> list[KnowledgeDocument]:
    """Combine all supported source inputs into one normalized document list."""

    normalized = list(documents)
    if faq_items:
        normalized.extend(
            faq_items_to_documents(
                collection_name=collection_name,
                document_prefix=f"{collection_name}:faq",
                faq_items=faq_items,
            )
        )
    for file_input in files:
        normalized.extend(parse_file_content(collection_name=collection_name, file_input=file_input))
    return normalized


def ingest_text(document_id: str, text: str, chunk_size: int = 400, overlap: int = 40) -> dict[str, Any]:
    """Chunk text and return a backwards-compatible ingestion payload skeleton."""

    document = KnowledgeDocument(document_id=document_id, collection_name="default", text=text)
    chunks = chunk_documents([document], chunk_size=chunk_size, overlap=overlap)
    return {
        "document_id": document_id,
        "chunks": [chunk.text for chunk in chunks] or chunk_text(text=text, chunk_size=chunk_size, overlap=overlap),
    }
