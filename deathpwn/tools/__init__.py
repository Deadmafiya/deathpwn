"""Tool registry — import side-effects register tools."""
import deathpwn.tools.dirb as _dirb  # noqa: F401
import deathpwn.tools.subfinder as _subfinder  # noqa: F401
from deathpwn.tools.registry import TOOL_REGISTRY, get_tool, register
__all__ = ["TOOL_REGISTRY", "get_tool", "register"]
