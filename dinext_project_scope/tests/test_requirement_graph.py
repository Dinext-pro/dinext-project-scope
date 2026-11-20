import unittest

from dinext_project_scope.requirement_graph import (
	REQUIREMENT,
	CompositionError,
	display_order,
	next_revision,
	walk_composition,
)


class TestRequirementGraph(unittest.TestCase):
	def test_overlapping_specification_paths_preserve_each_source(self):
		graph = walk_composition(
			[(REQUIREMENT, "r1"), ("specification", "one"), ("specification", "two")],
			{
				"one": [("specification", "nested")],
				"two": [("specification", "nested")],
				"nested": [(REQUIREMENT, "r1"), (REQUIREMENT, "r2")],
			}.__getitem__,
			"specification",
		)
		self.assertEqual(
			graph,
			{"r1": [[], ["one", "nested"], ["two", "nested"]], "r2": [["one", "nested"], ["two", "nested"]]},
		)

	def test_hidden_path_cannot_disclose_accessible_requirement(self):
		graph = walk_composition(
			[("specification", "hidden"), ("specification", "visible")],
			{"hidden": None, "visible": [(REQUIREMENT, "r1")]}.__getitem__,
			"specification",
		)
		self.assertEqual(graph, {"r1": [["visible"]]})

	def test_transitive_cycle_and_direct_duplicate_are_rejected(self):
		with self.assertRaises(CompositionError):
			walk_composition(
				[("specification", "nested")],
				{"nested": [("specification", "root")]}.__getitem__,
				"specification",
				root="root",
			)
		with self.assertRaises(CompositionError):
			walk_composition(
				[(REQUIREMENT, "r1"), (REQUIREMENT, "r1")],
				{}.__getitem__,
				"specification",
			)

	def test_hierarchy_uses_only_the_included_parent(self):
		self.assertEqual(
			display_order({"child": "parent", "orphan": "outside", "parent": None, "grandchild": "child"}),
			[("orphan", None), ("parent", None), ("child", "parent"), ("grandchild", "child")],
		)

	def test_return_to_prior_content_is_a_new_revision(self):
		self.assertEqual(next_revision(0, None, {"title": "A"}), 1)
		self.assertEqual(next_revision(3, {"title": "A"}, {"title": "A"}), 3)
		self.assertEqual(next_revision(3, {"title": "A"}, {"title": "B"}), 4)
		self.assertEqual(next_revision(4, {"title": "B"}, {"title": "A"}), 5)
