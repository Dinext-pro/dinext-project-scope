from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from hashlib import sha256
from json import dumps

REQUIREMENT = "Project Requirement"


class CompositionError(ValueError):
	pass


def content_digest(value: object) -> str:
	return sha256(
		dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
	).hexdigest()


def walk_composition(
	items: Sequence[tuple[str, str]],
	load_items: Callable[[str], Sequence[tuple[str, str]] | None],
	specification_type: str,
	*,
	root: str | None = None,
) -> dict[str, list[list[str]]]:
	"""Expand an ordered graph into unique requirements with every permitted inclusion path."""

	def checked_edges(edges):
		if any(doctype not in (REQUIREMENT, specification_type) or not name for doctype, name in edges):
			raise CompositionError("target")
		if len(set(edges)) != len(edges):
			raise CompositionError("duplicate")
		return edges

	@cache
	def children(name):
		edges = load_items(name)
		return checked_edges(edges) if edges is not None else ()

	paths = defaultdict(list)
	stack = [(edge, ()) for edge in reversed(checked_edges(items))]
	while stack:
		(doctype, name), path = stack.pop()
		if doctype == REQUIREMENT:
			paths[name].append(list(path))
			continue
		if name == root or name in path:
			raise CompositionError("cycle")
		branch = (*path, name)
		stack.extend((edge, branch) for edge in reversed(children(name)))
	return dict(paths)


def display_order(parents: Mapping[str, str | None]) -> list[tuple[str, str | None]]:
	"""Sort included requirements parent-first, preserving sibling order."""
	children = defaultdict(list)
	for name, parent in parents.items():
		children[parent if parent in parents else None].append(name)

	order = []
	stack = [(name, None) for name in reversed(children[None])]
	while stack:
		name, parent = stack.pop()
		order.append((name, parent))
		stack.extend((child, name) for child in reversed(children[name]))
	if len(order) != len(parents):
		raise CompositionError("cycle")
	return order


def next_revision(previous: int, before: dict | None, current: dict) -> int:
	return max(1, previous or 0) + int(before is not None and before != current)
