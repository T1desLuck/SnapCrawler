from __future__ import annotations
from typing import Callable, List, Optional, Tuple

class BKTree:
    def __init__(self, distance: Callable[[str, str], int]) -> None:
        self.distance = distance
        self.root: Optional[Tuple[str, dict[int, any]]] = None

    def add(self, item: str) -> None:
        if self.root is None:
            self.root = (item, {})
            return
        node_item, children = self.root
        current = self.root
        while True:
            node_item, children = current
            d = self.distance(item, node_item)
            child = children.get(d)
            if child is None:
                children[d] = (item, {})
                return
            current = child

    def build(self, items: List[str]) -> None:
        for it in items:
            self.add(it)

    def search(self, query: str, max_dist: int) -> List[str]:
        if self.root is None:
            return []
        results: List[str] = []
        stack = [self.root]
        while stack:
            node_item, children = stack.pop()
            d = self.distance(query, node_item)
            if d <= max_dist:
                results.append(node_item)
            # explore children in range
            for k, child in children.items():
                if d - max_dist <= k <= d + max_dist:
                    stack.append(child)
        return results
