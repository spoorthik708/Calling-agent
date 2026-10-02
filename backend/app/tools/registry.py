from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from app.core.exceptions import (
    TenantIsolationError,
    ToolExecutionSecurityError,
    ToolNotFoundError,
    ToolValidationError,
)
from app.core.logging import get_logger
from app.security.input_validation import validate_tool_arguments
from app.tools.base import (
    BaseTool,
    CreateFollowupTool,
    LookupCustomerTool,
    ToolExecutionContext,
)

logger = get_logger("yavura.tools.registry")


class ToolRegistry:
    """
    Central, secure registry of tools accessible to AI agents.
    Enforces deterministic lookup, explicit registration, tenant context,
    schema validation, and injection prevention before execution.
    """
    def __init__(self, register_builtins: bool = True):
        self._tools: Dict[str, BaseTool] = {}
        if register_builtins:
            self.register_tool(LookupCustomerTool())
            self.register_tool(CreateFollowupTool())

    def register_tool(self, tool: BaseTool) -> None:
        """Registers a tool in the registry."""
        if not tool.name or not tool.input_schema or not tool.output_schema:
            raise ValueError(f"Tool {tool} must specify name, input_schema, and output_schema.")
        self._tools[tool.name] = tool
        logger.info("Registered server-side tool: %s (version=%s)", tool.name, getattr(tool, "version", "1.0.0"))

    # Alias for clean dependency injection
    register = register_tool

    def get_tool(self, name: str) -> BaseTool:
        """Retrieves a registered tool or raises ToolNotFoundError."""
        tool = self._tools.get(name)
        if not tool:
            raise ToolNotFoundError(
                f"Requested tool '{name}' is not registered.",
                details={"tool_name": name},
            )
        return tool

    # Alias for lookup
    get = get_tool

    def has_tool(self, name: str) -> bool:
        """Checks if a tool name is registered."""
        return name in self._tools

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
        if not context or not context.tenant_id:
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
            "Executing tool '%s' for tenant=%s session=%s",
            tool_name,
            context.tenant_id,
            context.session_id,
        )

        # Execute
        result = await tool.execute(validated_input, context)

        # Output serialization
        return result.model_dump()


# Default singleton instance
default_tool_registry = ToolRegistry(register_builtins=True)
