import pytest
from app.agents.llm_provider import LLMMessage, MockLLMProvider
from app.voice.text_chunker import TextChunker


def test_text_chunker_sentence_splitting():
    chunker = TextChunker(min_chunk_chars=10, max_chunk_chars=100)

    # Feed tokens piece by piece
    tokens = ["Hello, ", "your ", "order ", "is ", "confirmed. ", "It ", "will ", "arrive ", "tomorrow!"]
    emitted = []
    for token in tokens:
        clauses = chunker.feed(token)
        emitted.extend(clauses)

    remaining = chunker.flush()
    emitted.extend(remaining)

    assert len(emitted) == 2
    assert "order is confirmed" in emitted[0]
    assert "arrive tomorrow" in emitted[1]


def test_text_chunker_clause_splitting_on_comma():
    chunker = TextChunker(min_chunk_chars=15, max_chunk_chars=100)

    # Clause boundary with enough characters
    tokens = ["Based on the retrieved business records, ", "we found your active account."]
    emitted = []
    for token in tokens:
        emitted.extend(chunker.feed(token))
    emitted.extend(chunker.flush())

    assert len(emitted) >= 2
    assert "Based on the retrieved business records" in emitted[0]
    assert "active account" in emitted[1]


def test_text_chunker_max_length_forced_split():
    # If a sentence has no punctuation but reaches max_chunk_chars
    chunker = TextChunker(min_chunk_chars=10, max_chunk_chars=40)

    long_text = "This is a very long run-on sentence without any punctuation marks anywhere inside it"
    emitted = chunker.feed(long_text)
    emitted.extend(chunker.flush())

    assert len(emitted) > 1
    # Verify no chunk exceeds max_chunk_chars significantly
    for c in emitted:
        assert len(c) <= 60


@pytest.mark.asyncio
async def test_llm_stream_response_integration_with_chunker():
    llm = MockLLMProvider(fixed_response="Your appointment is scheduled for Monday at 10 AM. Please arrive 10 minutes early.")
    messages = [LLMMessage(role="user", content="When is my appointment?")]

    chunker = TextChunker()
    all_clauses = []

    async for chunk in llm.stream_response(messages=messages, model="mock-model"):
        if chunk.text:
            clauses = chunker.feed(chunk.text)
            all_clauses.extend(clauses)

    all_clauses.extend(chunker.flush())

    assert len(all_clauses) >= 2
    assert any("Monday" in c for c in all_clauses)
    assert any("arrive" in c for c in all_clauses)
