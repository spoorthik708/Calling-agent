from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from app.core.exceptions import (
    TenantIsolationError,
    ToolExecutionSecurityError,
    ToolNotFoundError,
)
from app.core.logging import get_logger
from app.security.input_validation import validate_tool_arguments
from app.tools.base import BaseTool, ToolExecutionContext

logger = get_logger("yavura.tools")


class ToolRegistry:
    """
    Central, secure registry of tools accessible to AI agents.
    Enforces tenant context, schema validation, and injection prevention before execution.
    """
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Registers a tool in the registry."""
        if not tool.name or not tool.input_schema or not tool.output_schema:
            raise ValueError(f"Tool {tool} must specify name, input_schema, and output_schema.")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get_tool(self, name: str) -> BaseTool:
        """Retrieves a registered tool or raises ToolNotFoundError."""
        tool = self._tools.get(name)
        if not tool:
            raise ToolNotFoundError(f"Requested tool '{name}' is not registered.")
        return tool

    def list_declarations(self) -> List[Dict[str, Any]]:
        """Returns schemas of all registered tools for AI agent capabilities."""
        return [tool.get_declaration() for tool in self._tools.values()]

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> Dict[str, Any]:
        """
        Executes a tool under strict security controls:
        1. Tenant boundary must be present.
        2. Prohibited shell/code/SQL patterns are rejected.
        3. Arguments validated strictly against tool's Pydantic schema.
        4. Tool executed within tenant scope.
        """
        if not context.tenant_id:
            raise TenantIsolationError("Tool execution forbidden without explicit tenant context.")

        # Security check: Prohibit arbitrary commands, scripts, code injections
        validate_tool_arguments(arguments)

        tool = self.get_tool(tool_name)

        # Validate inputs against Pydantic schema
        try:
            validated_input = tool.input_schema.model_validate(arguments)
        except ValidationError as e:
            raise ToolExecutionSecurityError(
                f"Tool '{tool_name}' argument validation failed: {str(e)}"
            )

        logger.info(
            f"Executing tool '{tool_name}' for tenant={context.tenant_id} session={context.session_id}"
        )

        # Execute
        result = await tool.execute(validated_input, context)

        # Output serialization
        return result.model_dump()
