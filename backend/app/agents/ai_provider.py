from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AIResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    usage: Dict[str, int] = Field(default_factory=dict)
    finish_reason: Optional[str] = None
    provider: str
    model: str


class AIProviderInterface(ABC):
    """
    Modular AI Provider Interface.
    Decouples YAVURA business logic from specific vendors (OpenAI, Anthropic, Gemini, DeepSeek, etc.)
    """
    @abstractmethod
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generates a conversational response or tool call requests."""
        pass

    @abstractmethod
    async def stream_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Streams text chunks for real-time voice synthesis."""
        pass

    @abstractmethod
    async def generate_embedding(self, text: str) -> List[float]:
        """Generates embedding vector for RAG knowledge retrieval."""
        pass


class MockAIProvider(AIProviderInterface):
    """
    Mock AI Provider for tests and initial foundation validation.
    Never calls external billable APIs during local testing.
    """
    def __init__(self, provider_name: str = "mock-provider"):
        self.provider_name = provider_name

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AIResponse:
        last_message = messages[-1]["content"] if messages else ""
        return AIResponse(
            content=f"Mock response acknowledging: '{last_message}'",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            finish_reason="stop",
            provider=self.provider_name,
            model="mock-v1",
        )

    async def stream_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        chunks = ["Hello, ", "this ", "is ", "a ", "mock ", "voice ", "stream."]
        for chunk in chunks:
            yield chunk

    async def generate_embedding(self, text: str) -> List[float]:
        # Return standard 1536-dim mock vector
        return [0.01] * 1536


class AIProviderFactory:
    """Factory to retrieve configured AI provider without vendor coupling."""
    _providers: Dict[str, AIProviderInterface] = {
        "mock": MockAIProvider(),
    }

    @classmethod
    def register_provider(cls, name: str, provider: AIProviderInterface) -> None:
        cls._providers[name.lower()] = provider

    @classmethod
    def get_provider(cls, name: Optional[str] = None) -> AIProviderInterface:
        provider_name = (name or "mock").lower()
        if provider_name not in cls._providers:
            # Fallback to mock for initial foundation
            return cls._providers["mock"]
        return cls._providers[provider_name]
