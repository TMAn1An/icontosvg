"""Skeleton graph: nodes, edges, and tangent-continuous stroke assembly.

The previous reconstruction fitted every skeleton branch independently.
A junction silently cut a stroke in half, so the dollar sign's S-curve
arrived as several unrelated fragments and each was fitted on its own —
producing arcs where a cubic belonged, stray zero-length pieces, and
open fragments closed with `Z` because their ends happened to be near
each other.

Topology is therefore decided *first* and geometry second. This module
builds the skeleton as a proper graph, then reassembles logical strokes
by pairing branches that continue each other through a junction:

    at a crossing, the vertical branch continues into the vertical
    branch and the curved branch continues into the curved branch,
    chosen by tangent continuity, not by traversal order.

Only after a stroke is whole does anything try to fit geometry to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

Pixel = tuple[int, int]  # (row, col)

_NEIGHBOR_OFFSETS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)

ENDPOINT = "endpoint"
JUNCTION = "junction"


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return np.array([1.0, 0.0])
    return np.asarray(vector, dtype=float) / norm


def _neighbors(skeleton: np.ndarray, pixel: Pixel) -> list[Pixel]:
    row, col = pixel
    height, width = skeleton.shape
    found = []
    for d_row, d_col in _NEIGHBOR_OFFSETS:
        r, c = row + d_row, col + d_col
        if 0 <= r < height and 0 <= c < width and skeleton[r, c]:
            found.append((r, c))
    return found


# The 8-neighbourhood walked in circular order, starting north.
_RING_OFFSETS = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)


def crossing_number(skeleton: np.ndarray, pixel: Pixel) -> int:
    """Topological degree: how many arms leave this pixel.

    Counted as the number of 0->1 transitions around the ordered
    8-neighbour ring (Rutovitz crossing number). 1 is a free end, 2 a
    path pixel, 3 or more a junction.

    Clustering the neighbours by 8-adjacency instead — the obvious
    approach, and the one this replaced — silently loses every crossing:
    at the centre of a `+` the four arm pixels are mutually diagonally
    adjacent, so they collapse into a single cluster and a four-way
    junction is reported as a free end. That is why the dollar sign's
    crossing was invisible to the graph.
    """
    row, col = pixel
    height, width = skeleton.shape
    ring = []
    for d_row, d_col in _RING_OFFSETS:
        r, c = row + d_row, col + d_col
        ring.append(bool(skeleton[r, c]) if 0 <= r < height and 0 <= c < width else False)
    return sum(
        1 for i in range(8) if not ring[i] and ring[(i + 1) % 8]
    )


def neighbor_group_count(skeleton: np.ndarray, pixel: Pixel) -> int:
    """Backwards-compatible alias for :func:`crossing_number`."""
    return crossing_number(skeleton, pixel)


@dataclass
class Node:
    index: int
    pixel: Pixel
    degree: int

    @property
    def kind(self) -> str:
        return ENDPOINT if self.degree <= 1 else JUNCTION

    @property
    def xy(self) -> np.ndarray:
        return np.array([float(self.pixel[1]), float(self.pixel[0])])


@dataclass
class Edge:
    """One branch between two nodes, or a standalone closed cycle."""

    index: int
    node_a: int | None
    node_b: int | None
    samples: np.ndarray  # (N, 2) in x/y, ordered node_a -> node_b
    is_cycle: bool = False

    @property
    def length(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return float(np.sum(np.hypot(*np.diff(self.samples, axis=0).T)))

    def tangent_leaving(self, node_index: int, window: int = 5) -> np.ndarray:
        """Unit direction travelling away from `node_index` along this edge."""
        pts = self.samples
        if len(pts) < 2:
            return np.array([1.0, 0.0])
        span = min(window, len(pts) - 1)
        if node_index == self.node_a:
            return _unit(pts[span] - pts[0])
        return _unit(pts[-1 - span] - pts[-1])


@dataclass
class Stroke:
    """A logical, topologically whole path: one or more chained edges."""

    edge_indices: list[int]
    samples: np.ndarray
    closed: bool
    start_node: int | None = None
    end_node: int | None = None
    crossed_junctions: int = 0

    @property
    def length(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return float(np.sum(np.hypot(*np.diff(self.samples, axis=0).T)))


@dataclass
class SkeletonGraph:
    nodes: dict[int, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def incident(self, node_index: int) -> list[Edge]:
        return [
            e for e in self.edges
            if e.node_a == node_index or e.node_b == node_index
        ]

    def component_count(self) -> int:
        """Connected components over edges (nodes joined by shared edges)."""
        parent: dict[int, int] = {}

        def find(x: int) -> int:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        count = 0
        for edge in self.edges:
            if edge.is_cycle:
                count += 1
                continue
            for n in (edge.node_a, edge.node_b):
                if n is not None:
                    parent.setdefault(n, n)
            if edge.node_a is not None and edge.node_b is not None:
                union(edge.node_a, edge.node_b)
        roots = {find(n) for n in parent}
        return count + len(roots)


def build_graph(skeleton: np.ndarray) -> SkeletonGraph:
    """Trace a skeleton mask into a graph of nodes and edges."""
    skeleton = skeleton.astype(bool)
    pixels = [(int(r), int(c)) for r, c in zip(*np.where(skeleton))]
    graph = SkeletonGraph()
    if not pixels:
        return graph

    degrees = {p: neighbor_group_count(skeleton, p) for p in pixels}
    node_pixels = {p for p, d in degrees.items() if d != 2}

    index_of: dict[Pixel, int] = {}
    for pixel in sorted(node_pixels):
        node = Node(index=len(graph.nodes), pixel=pixel, degree=degrees[pixel])
        graph.nodes[node.index] = node
        index_of[pixel] = node.index

    visited_edges: set[frozenset[Pixel]] = set()

    def walk(start: Pixel, first: Pixel) -> list[Pixel]:
        path = [start, first]
        visited_edges.add(frozenset((start, first)))
        previous, current = start, first
        while current not in node_pixels:
            candidates = [
                c for c in _neighbors(skeleton, current)
                if c != previous and frozenset((current, c)) not in visited_edges
            ]
            if not candidates:
                break
            # Step into a node whenever one is adjacent. Without this the
            # "advance past diagonal staircases" preference below routes
            # around a junction's centre pixel, fusing two arms into one
            # through-going edge and leaving the centre as a stray loop.
            node_candidates = [c for c in candidates if c in node_pixels]
            if node_candidates:
                nxt = node_candidates[0]
            else:
                candidates.sort(
                    key=lambda c: (
                        abs(c[0] - previous[0]) <= 1 and abs(c[1] - previous[1]) <= 1
                    )
                )
                nxt = candidates[0]
            visited_edges.add(frozenset((current, nxt)))
            path.append(nxt)
            previous, current = current, nxt
        return path

    for pixel in sorted(node_pixels):
        for neighbor in _neighbors(skeleton, pixel):
            if frozenset((pixel, neighbor)) in visited_edges:
                continue
            path = walk(pixel, neighbor)
            if len(path) < 2:
                continue
            end_pixel = path[-1]
            if end_pixel not in node_pixels:
                # The walk can run out of unvisited steps while standing
                # right next to a node — typically after going all the way
                # around a closed outline. Attaching it there is what makes
                # that outline a cycle instead of a dangling open edge.
                adjacent = [n for n in _neighbors(skeleton, end_pixel) if n in node_pixels]
                if adjacent:
                    end_pixel = adjacent[0]
                    path.append(end_pixel)
            # A "loop" of a couple of pixels back onto the same node is a
            # traversal artifact at a crossing, not geometry.
            if end_pixel == pixel and len(path) <= 4:
                continue
            samples = np.array([(c, r) for r, c in path], dtype=float)
            start_index = index_of[pixel]
            end_index = index_of.get(end_pixel)
            graph.edges.append(
                Edge(
                    index=len(graph.edges),
                    node_a=start_index,
                    node_b=end_index,
                    samples=samples,
                    is_cycle=(end_index is not None and end_index == start_index),
                )
            )

    # Closed loops containing no node at all (a clean circle).
    covered = {
        (int(y), int(x))
        for edge in graph.edges
        for x, y in edge.samples
    }
    remaining = [p for p in pixels if p not in covered]
    while remaining:
        start = remaining[0]
        neighbors = _neighbors(skeleton, start)
        if not neighbors:
            remaining.pop(0)
            continue
        loop = walk(start, neighbors[0])
        if loop[-1] != start:
            loop.append(start)
        samples = np.array([(c, r) for r, c in loop], dtype=float)
        graph.edges.append(
            Edge(
                index=len(graph.edges),
                node_a=None,
                node_b=None,
                samples=samples,
                is_cycle=True,
            )
        )
        covered.update(loop)
        remaining = [p for p in remaining if p not in covered]

    return graph


def pair_at_junctions(
    graph: SkeletonGraph,
    min_continuation_degrees: float = 115.0,
    window: int = 5,
) -> dict[tuple[int, int], int]:
    """Pair branches that continue each other through each junction.

    Returns a map from (node index, edge index) to the partner edge index.

    At a crossing, the pair whose tangents are most nearly opposite is
    the pair that actually continues: a vertical stroke passing straight
    through keeps going vertically, and a curve keeps curving. Pairs are
    taken greedily by continuation strength, and a pair whose turn is
    sharper than `min_continuation_degrees` is rejected outright — that
    is a genuine corner meeting, not a stroke passing through.
    """
    pairing: dict[tuple[int, int], int] = {}

    for node_index, node in graph.nodes.items():
        incident = [e for e in graph.incident(node_index) if not e.is_cycle]
        if len(incident) < 2:
            continue

        scored: list[tuple[float, int, int]] = []
        for i, edge_i in enumerate(incident):
            for edge_j in incident[i + 1:]:
                t_i = edge_i.tangent_leaving(node_index, window)
                t_j = edge_j.tangent_leaving(node_index, window)
                # Both tangents point away from the node, so a stroke
                # passing straight through has them ~180 degrees apart.
                cos = float(np.clip(np.dot(t_i, t_j), -1.0, 1.0))
                angle = float(np.degrees(np.arccos(cos)))
                scored.append((angle, edge_i.index, edge_j.index))

        scored.sort(reverse=True)
        used: set[int] = set()
        for angle, a, b in scored:
            if angle < min_continuation_degrees:
                break
            if a in used or b in used:
                continue
            pairing[(node_index, a)] = b
            pairing[(node_index, b)] = a
            used.update((a, b))

    return pairing


def assemble_strokes(
    graph: SkeletonGraph,
    pairing: dict[tuple[int, int], int] | None = None,
) -> list[Stroke]:
    """Chain edges into whole strokes using the junction pairing."""
    if pairing is None:
        pairing = pair_at_junctions(graph)

    strokes: list[Stroke] = []
    consumed: set[int] = set()

    for edge in graph.edges:
        if edge.is_cycle:
            strokes.append(
                Stroke(
                    edge_indices=[edge.index],
                    samples=edge.samples.copy(),
                    closed=True,
                )
            )
            consumed.add(edge.index)

    by_index = {e.index: e for e in graph.edges}

    def other_node(edge: Edge, node: int | None) -> int | None:
        return edge.node_b if edge.node_a == node else edge.node_a

    def oriented(edge: Edge, from_node: int | None) -> np.ndarray:
        if edge.node_a == from_node:
            return edge.samples
        return edge.samples[::-1]

    def trace_from(edge: Edge, from_node: int | None) -> Stroke:
        chain = [edge.index]
        pieces = [oriented(edge, from_node)]
        current = edge
        node = other_node(edge, from_node)
        crossings = 0
        while node is not None:
            partner_index = pairing.get((node, current.index))
            if partner_index is None or partner_index in consumed:
                break
            partner = by_index[partner_index]
            consumed.add(partner.index)
            chain.append(partner.index)
            pieces.append(oriented(partner, node)[1:])
            crossings += 1
            current = partner
            node = other_node(partner, node)
            if node == from_node and partner.index == chain[0]:
                break
        samples = np.vstack(pieces)
        return Stroke(
            edge_indices=chain,
            samples=samples,
            closed=False,
            start_node=from_node,
            end_node=node,
            crossed_junctions=crossings,
        )

    # Start from free ends first, so an open stroke is traced whole.
    for node_index, node in sorted(graph.nodes.items()):
        for edge in graph.incident(node_index):
            if edge.index in consumed or edge.is_cycle:
                continue
            if (node_index, edge.index) in pairing:
                continue  # not a free end; reached by traversal instead
            consumed.add(edge.index)
            strokes.append(trace_from(edge, node_index))

    # Anything still unconsumed is a closed chain through junctions.
    for edge in graph.edges:
        if edge.index in consumed or edge.is_cycle:
            continue
        consumed.add(edge.index)
        stroke = trace_from(edge, edge.node_a)
        if (
            stroke.end_node is not None
            and stroke.start_node is not None
            and stroke.end_node == stroke.start_node
            and len(stroke.samples) > 3
        ):
            stroke.closed = True
        strokes.append(stroke)

    return strokes


def topology_signature(graph: SkeletonGraph) -> dict[str, int]:
    """Structural fingerprint used by the safety gate."""
    return {
        "components": graph.component_count(),
        "endpoints": sum(1 for n in graph.nodes.values() if n.kind == ENDPOINT),
        "junctions": sum(1 for n in graph.nodes.values() if n.kind == JUNCTION),
        "edges": len(graph.edges),
        "cycles": sum(1 for e in graph.edges if e.is_cycle),
    }


def prune_graph_spurs(graph: SkeletonGraph, max_length: float) -> SkeletonGraph:
    """Drop short dead-end stubs, then heal the nodes they leave behind.

    Skeletonizing a sharp corner sheds two- and three-pixel stubs. Each
    one turns its corner into a junction, which splits an otherwise
    continuous outline into separate strokes — a triangle arrives as
    three unrelated pieces. Removing the stub leaves a degree-2 node,
    which is then merged away so the outline is continuous again.
    """
    edges = {e.index: e for e in graph.edges}
    nodes = dict(graph.nodes)

    def incidence() -> dict[int, list[int]]:
        table: dict[int, list[int]] = {n: [] for n in nodes}
        for edge in edges.values():
            for n in (edge.node_a, edge.node_b):
                if n is not None and n in table:
                    table[n].append(edge.index)
        return table

    outer = True
    while outer:
        outer = False

        changed = True
        while changed:
            changed = False
            table = incidence()
            for edge in list(edges.values()):
                # A micro-loop shorter than a stroke width is a
                # skeletonization artifact at a corner. Left in place it
                # holds that corner's node at degree 3, so the real
                # outline never closes and never qualifies as a polygon.
                if edge.is_cycle:
                    if edge.length < max_length:
                        del edges[edge.index]
                        changed = outer = True
                        break
                    continue
                if edge.length >= max_length:
                    continue

                real = [n for n in (edge.node_a, edge.node_b) if n is not None]
                # A dangling end counts as free, and a stub can be a chain
                # of short edges, so this runs to convergence and unravels
                # one link per pass. A detail free at *both* ends (a dash,
                # a tick) has free_count 2 and is never touched.
                free = [n for n in real if len(table.get(n, [])) == 1]
                free_count = len(free) + (1 if len(real) == 1 else 0)

                if free_count == 1:
                    del edges[edge.index]
                    for n in free:
                        nodes.pop(n, None)
                    changed = outer = True
                    break

        # Heal: a node with exactly two edges is no longer a junction.
        changed = True
        while changed:
            changed = False
            table = incidence()
            for node_index, incident in table.items():
                # A self-loop appears twice in this node's list; merging it
                # with itself concatenates the loop onto itself and traces
                # the outline twice.
                if len(incident) != 2 or len(set(incident)) != 2:
                    continue
                first, second = (edges[i] for i in incident)
                if first.is_cycle or second.is_cycle:
                    continue

                def ending_at(edge: Edge, tail: int) -> np.ndarray:
                    return edge.samples if edge.node_b == tail else edge.samples[::-1]

                def starting_at(edge: Edge, head: int) -> np.ndarray:
                    return edge.samples if edge.node_a == head else edge.samples[::-1]

                head_a = first.node_a if first.node_b == node_index else first.node_b
                head_b = second.node_b if second.node_a == node_index else second.node_a
                # The first piece must arrive at the node and the second
                # must leave it; orienting both to end there joins
                # tail-to-tail and inserts a jump across the shape.
                merged = np.vstack([
                    ending_at(first, node_index),
                    starting_at(second, node_index)[1:],
                ])

                del edges[second.index]
                edges[first.index] = Edge(
                    index=first.index, node_a=head_a, node_b=head_b,
                    samples=merged,
                    is_cycle=(head_a is not None and head_a == head_b),
                )
                nodes.pop(node_index, None)
                changed = outer = True
                break

    rebuilt = SkeletonGraph(nodes=nodes, edges=list(edges.values()))
    for node_index, incident in incidence().items():
        if node_index in rebuilt.nodes:
            rebuilt.nodes[node_index].degree = len(incident)
    return rebuilt
