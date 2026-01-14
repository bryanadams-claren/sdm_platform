"""
Graph Registry - Factory pattern for graph selection.

This module provides a centralized registry for all graph modes,
enabling both static (settings-based) and dynamic (runtime) selection.
"""

import logging
from collections.abc import Callable
from enum import Enum

from django.conf import settings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.base import get_postgres_checkpointer
from sdm_platform.llmchat.utils.graphs.builders.assistant import build_assistant_graph
from sdm_platform.llmchat.utils.graphs.builders.autonomous import build_autonomous_graph

logger = logging.getLogger(__name__)


class GraphMode(str, Enum):
    """Available graph modes."""

    ASSISTANT = "assistant"  # Responds only to @llm
    AUTONOMOUS = "autonomous"  # Responds to every message
    # Future modes:
    # AUDIT = "audit"          # Logging only, no responses  #noqa: ERA001
    # CMS_INTRO = "cms_intro"  # Content introduction mode   #noqa: ERA001


# Type alias for graph builder functions
GraphBuilder = Callable[[PostgresSaver, BaseStore | None], CompiledStateGraph]


class GraphRegistry:
    """
    Registry for graph builders with factory method.

    Supports:
    - Static mode selection via Django settings
    - Dynamic mode selection at runtime
    - Easy extensibility for new modes
    """

    _builders: dict[GraphMode, GraphBuilder] = {
        GraphMode.ASSISTANT: build_assistant_graph,
        GraphMode.AUTONOMOUS: build_autonomous_graph,
    }

    @classmethod
    def register(cls, mode: GraphMode, builder: GraphBuilder) -> None:
        """
        Register a new graph builder.

        Allows extending the registry without modifying this file.
        """
        cls._builders[mode] = builder
        logger.info("Registered graph builder for mode: %s", mode.value)

    @classmethod
    def get_builder(cls, mode: GraphMode) -> GraphBuilder:
        """Get a graph builder by mode."""
        if mode not in cls._builders:
            available = [m.value for m in cls._builders]
            msg = f"Unknown graph mode: {mode}. Available: {available}"
            raise ValueError(msg)
        return cls._builders[mode]

    @classmethod
    def build_graph(
        cls,
        mode: GraphMode,
        checkpointer: PostgresSaver,
        store: BaseStore | None = None,
    ) -> CompiledStateGraph:
        """
        Build a graph for the specified mode.

        This is the main factory method.
        """
        builder = cls.get_builder(mode)
        return builder(checkpointer, store)

    @classmethod
    def available_modes(cls) -> list[GraphMode]:
        """List all available graph modes."""
        return list(cls._builders.keys())


def get_graph_mode_from_settings() -> GraphMode:
    """
    Get the configured graph mode from Django settings.

    Reads from settings.LLM_GRAPH_MODE, defaults to ASSISTANT.
    """
    mode_str = getattr(settings, "LLM_GRAPH_MODE", "assistant")
    try:
        return GraphMode(mode_str.lower())
    except ValueError:
        logger.warning(
            "Invalid LLM_GRAPH_MODE '%s', falling back to 'assistant'",
            mode_str,
        )
        return GraphMode.ASSISTANT


def get_compiled_graph(
    checkpointer: PostgresSaver,
    store: BaseStore | None = None,
    mode: GraphMode | None = None,
) -> CompiledStateGraph:
    """
    Get a compiled graph for the specified or configured mode.

    This is the main entry point for graph retrieval.

    Args:
        checkpointer: PostgresSaver for state persistence
        store: Optional BaseStore for memory
        mode: Optional explicit mode. If None, reads from settings.

    Returns:
        Compiled LangGraph ready for invocation
    """
    if mode is None:
        mode = get_graph_mode_from_settings()

    logger.debug("Building graph for mode: %s", mode.value)
    return GraphRegistry.build_graph(mode, checkpointer, store)


# Public API exports
__all__ = [
    "GraphMode",
    "GraphRegistry",
    "SdmState",
    "get_compiled_graph",
    "get_graph_mode_from_settings",
    "get_postgres_checkpointer",
]
