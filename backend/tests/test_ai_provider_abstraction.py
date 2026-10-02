import pytest
from app.agents.ai_provider import (
    AIProviderFactory,
    AIProviderInterface,
    AIResponse,
    MockAIProvider,
)


@pytest.mark.asyncio
async def test_ai_provider_factory_and_mock_response():
    """Verifies that the AI provider factory instantiates the abstracted provider."""
    provider = AIProviderFactory.get_provider("mock")
    assert isinstance(provider, AIProviderInterface)

    response = await provider.generate_response(
        messages=[{"role": "user", "content": "Hello YAVURA"}],
        system_prompt="You are a helpful agent.",
    )
    assert isinstance(response, AIResponse)
    assert response.content is not None
    assert "Hello YAVURA" in response.content
    assert response.provider == "mock-provider"


@pytest.mark.asyncio
async def test_ai_provider_streaming_abstraction():
    """Verifies that the streaming generator interface works properly."""
    provider = AIProviderFactory.get_provider("mock")
    chunks = []
    async for chunk in provider.stream_response(messages=[]):
        chunks.append(chunk)

    assert len(chunks) > 0
    full_text = "".join(chunks)
    assert "mock voice stream" in full_text
