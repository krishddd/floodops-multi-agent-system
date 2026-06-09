"""
CausalGraph — watershed flow topology for causal attribution.

A directed graph of upstream→downstream nodes, seeded from
``config.WATERSHED_TOPOLOGY`` (the sole source of topology). FloodPredictAgent
uses it to attribute *why* a downstream zone floods — the ranked upstream
contributors along the flow path — rather than only *what* the probability is.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from floodops.config import DEFAULT_WATERSHED_REGION, WATERSHED_TOPOLOGY


class CausalEdge(BaseModel):
    upstream: str
    downstream: str
    weight: float = 1.0


class CausalGraph(BaseModel):
    region: str
    edges: list[CausalEdge] = Field(default_factory=list)

    @classmethod
    def from_config(cls, region: str | None = None) -> "CausalGraph":
        region = region or DEFAULT_WATERSHED_REGION
        adjacency = WATERSHED_TOPOLOGY.get(region, [])
        return cls(region=region, edges=[
            CausalEdge(upstream=u, downstream=d) for (u, d) in adjacency
        ])

    def nodes(self) -> set[str]:
        ns: set[str] = set()
        for e in self.edges:
            ns.add(e.upstream)
            ns.add(e.downstream)
        return ns

    def upstream_contributors(self, node: str) -> list[str]:
        """All nodes that flow (transitively) into ``node`` — the causal chain."""
        result: list[str] = []
        frontier = [node]
        seen: set[str] = set()
        while frontier:
            cur = frontier.pop()
            for e in self.edges:
                if e.downstream == cur and e.upstream not in seen:
                    seen.add(e.upstream)
                    result.append(e.upstream)
                    frontier.append(e.upstream)
        return result

    def ranked_causal_factors(self, outlet: str | None = None) -> list[str]:
        """Ranked upstream causal factors feeding the basin outlet."""
        if outlet is None:
            # Outlet = node with no outgoing edge (terminal).
            downstreams = {e.downstream for e in self.edges}
            upstreams = {e.upstream for e in self.edges}
            terminals = downstreams - upstreams
            outlet = next(iter(terminals), None)
        if outlet is None:
            return []
        return [f"upstream inflow: {n}" for n in self.upstream_contributors(outlet)]
