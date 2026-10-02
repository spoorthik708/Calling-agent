from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type
import uuid
from pydantic import BaseModel


@dataclass
class ToolExecutionContext:
    """Security and tenant execution context passed to any tool invocation."""
    tenant_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    correlation_id: str = ""


class BaseTool(ABC):
    """
    Base class for all business tools callable by AI agents.
    Every tool must define strict input/output schemas and authorization requirements.
    """
    name: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    required_permissions: List[str] = []

    @abstractmethod
    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> BaseModel:
        """Executes the tool with validated arguments within explicit tenant boundary."""
        pass

    def get_declaration(self) -> Dict[str, Any]:
        """Returns JSON schema for AI model function calling registration."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema.model_json_schema(),
        }
