"""
Transitive reduction of dense component graphs (render_c4._transitive_reduction).

A dense diagram hides an edge a -> c when a longer path a -> ... -> c still
shows the dependency. Hiding must never lose a dependency: after reduction,
every pair that was connected is still connected.
"""
import random
import unittest

from helpers import write  # noqa: F401  (puts the skill on sys.path)

from scripts.render_c4 import _transitive_reduction


def _closure(edges):
    """{(a, b)} for every pair where b is reachable from a."""
    nodes = set(edges) | {t for targets in edges.values() for t in targets}
    pairs = set()
    for start in nodes:
        seen, stack = set(), list(edges.get(start, []))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            pairs.add((start, node))
            stack += edges.get(node, [])
    return pairs


class TransitiveReductionTest(unittest.TestCase):
    def test_shortcut_is_hidden(self):
        self.assertEqual(_transitive_reduction({"a": ["b", "c"], "b": ["c"]}),
                         {"a": ["b"], "b": ["c"]})

    def test_edge_out_of_a_cycle_is_kept(self):
        # a -> b -> a is a cycle; a -> c has no other path. It used to be
        # dropped because the search came back to a and followed a -> c itself.
        edges = {"a": ["b", "c"], "b": ["a"]}
        self.assertEqual(_transitive_reduction(edges), edges)

    def test_chord_of_a_cycle_is_hidden(self):
        # a -> b -> c -> a; a -> c is shown by a -> b -> c.
        reduced = _transitive_reduction({"a": ["b", "c"], "b": ["c"], "c": ["a"]})
        self.assertEqual(reduced, {"a": ["b"], "b": ["c"], "c": ["a"]})

    def test_reduction_never_loses_a_dependency(self):
        rng = random.Random(1)
        for _ in range(300):
            nodes = [f"n{i}" for i in range(rng.randint(2, 8))]
            edges = {n: sorted({t for t in nodes if t != n and rng.random() < 0.35}) for n in nodes}
            reduced = _transitive_reduction(edges)
            self.assertEqual(_closure(reduced), _closure(edges), edges)
            for node, targets in reduced.items():
                self.assertTrue(set(targets) <= set(edges[node]), "reduction must only remove edges")


if __name__ == "__main__":
    unittest.main()
