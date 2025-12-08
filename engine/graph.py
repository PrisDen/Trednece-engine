from __future__ import annotations

"""Graph models and loaders for the workflow engine."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, ValidationError

from engine.node import Node, build_node
from engine.registry import ToolRegistry

EdgeType = Literal["sequential", "branch", "loop"]


class LoopConfig(BaseModel):
    """Configuration for loop edges."""

    max_iterations: int = Field(default=5, ge=1, le=100)
    until_expression: str | None = None


class EdgeConfig(BaseModel):
    """Declarative edge definition used for JSON ingestion."""

    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    type: EdgeType = "sequential"
    condition: Dict[str, Any] | None = None
    loop: LoopConfig | None = None

    class Config:
        allow_population_by_field_name = True


class NodeConfig(BaseModel):
    """Declarative node definition referencing registry entries."""

    id: str
    callable: str
    name: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphConfig(BaseModel):
    """Top-level graph specification."""

    id: str
    name: str
    start_node: str
    nodes: list[NodeConfig]
    edges: list[EdgeConfig]


@dataclass(slots=True)
class Edge:
    """Concrete runtime edge data."""

    source: str
    target: str
    type: EdgeType
    condition: Dict[str, Any] | None = None
    loop: LoopConfig | None = None


@dataclass
class Graph:
    """Runtime graph composed of nodes and edges."""

    id: str
    name: str
    start_node: str
    nodes: Dict[str, Node]
    edges: list[Edge] = field(default_factory=list)
    adjacency: Dict[str, list[Edge]] = field(default_factory=dict)

    def get_node(self, node_id: str) -> Node:
        """Return the node for the provided identifier."""

        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Node '{node_id}' not found in graph '{self.id}'.") from exc

    def get_edges(self, node_id: str) -> list[Edge]:
        """Return outgoing edges for the node."""

        return self.adjacency.get(node_id, [])

    @classmethod
    def from_dict(cls, data: Dict[str, Any], registry: ToolRegistry) -> "Graph":
        """Build a graph instance from a JSON-like dictionary."""

        try:
            spec = GraphConfig.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid graph definition: {exc}") from exc

        node_map: Dict[str, Node] = {}
        for node_cfg in spec.nodes:
            if registry.has(node_cfg.callable) is False:
                raise ValueError(f"Callable '{node_cfg.callable}' is not registered.")
            node_map[node_cfg.id] = build_node(
                node_cfg.id,
                name=node_cfg.name,
                func=registry.get(node_cfg.callable),
                metadata=node_cfg.metadata,
            )

        if spec.start_node not in node_map:
            raise ValueError(f"Start node '{spec.start_node}' is not defined.")

        edges: list[Edge] = []
        adjacency: Dict[str, list[Edge]] = defaultdict(list)
        for edge_cfg in spec.edges:
            if edge_cfg.from_node not in node_map or edge_cfg.to_node not in node_map:
                raise ValueError(
                    f"Edge references unknown nodes: {edge_cfg.from_node} -> {edge_cfg.to_node}"
                )
            edge = Edge(
                source=edge_cfg.from_node,
                target=edge_cfg.to_node,
                type=edge_cfg.type,
                condition=edge_cfg.condition,
                loop=edge_cfg.loop,
            )
            edges.append(edge)
            adjacency[edge.source].append(edge)

        return cls(
            id=spec.id,
            name=spec.name,
            start_node=spec.start_node,
            nodes=node_map,
            edges=edges,
            adjacency=dict(adjacency),
        )


__all__ = ["Edge", "Graph", "GraphConfig", "NodeConfig", "EdgeConfig", "LoopConfig"]

