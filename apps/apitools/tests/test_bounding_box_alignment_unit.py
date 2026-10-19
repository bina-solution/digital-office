"""Regression guards for the BoundingBox geometry cache and the alignment pre-filter.

Both exist purely to make `find_texts_matching_annotations_via_alignment` cheaper, and
both are only safe under an invariant that is easy to break silently later:

  * the per-box cache must be dropped whenever `vertices` is replaced — `add_bboxes` and
    `match_bbox_orientation` do exactly that, and a stale width/centre would move which
    neighbour an extraction picks;
  * `may_align` must never reject a pair that `check_alingment` would call aligned — a
    false rejection drops a real match, which in this pipeline means a misfiled document.

No fixtures or stack needed; runs anywhere.
"""
import math
import random
import unittest

from src.ocr_core.models.alingment_position import AlignmentPosition
from src.ocr_core.models.bounding_box import BoundingBox, bbox_factory
from src.ocr_core.models.point import Point

POSITIONS = [AlignmentPosition.LEFT, AlignmentPosition.RIGHT,
             AlignmentPosition.ABOVE, AlignmentPosition.BELOW]


def rect(x, y, w, h):
    return BoundingBox([{"x": x, "y": y}, {"x": x + w, "y": y},
                        {"x": x + w, "y": y + h}, {"x": x, "y": y + h}])


class TestGeometryCacheInvalidation(unittest.TestCase):
    def test_add_bboxes_refreshes_cached_geometry(self):
        box = rect(10, 10, 40, 20)
        # prime every cached value
        self.assertAlmostEqual(box.width, 40.0)
        self.assertAlmostEqual(box.height, 20.0)
        first_center = (box.center.x, box.center.y)
        box._local_axes()
        box._center_vector()
        box._axis_bounds()

        box.add_bboxes([rect(100, 10, 40, 20)])

        self.assertGreater(box.width, 40.0, "width still reports the pre-merge value")
        self.assertNotEqual((box.center.x, box.center.y), first_center,
                            "centre still reports the pre-merge value")
        min_x, max_x, _, _ = box._axis_bounds()
        self.assertLessEqual(min_x, 10)
        self.assertGreaterEqual(max_x, 140)
        # the cached numpy centre vector must agree with the cached Point
        self.assertAlmostEqual(float(box._center_vector()[0]), float(box.center.x))
        self.assertAlmostEqual(float(box._center_vector()[1]), float(box.center.y))

    def test_match_bbox_orientation_leaves_no_stale_geometry(self):
        """After a vertex reorder every cached value must equal a freshly built box's.

        Asserting "the axes changed" would be wrong — for some orientations the reorder is
        a no-op. The invariant that actually matters is that nothing is STALE.
        """
        reordered_any = False
        for angle in (0, 30, 95, 150, 200, 300):
            box = bbox_factory(Point(200, 200), angle=angle, size=(60, 20))
            matcher = bbox_factory(Point(200, 200), angle=0, size=(60, 20))
            before_vertices = [(p.x, p.y) for p in box.vertices]
            box._local_axes_xy()          # prime
            box.width, box.height, box.center  # noqa: B018 — prime

            box.match_bbox_orientation(matcher)
            if [(p.x, p.y) for p in box.vertices] != before_vertices:
                reordered_any = True

            fresh = BoundingBox([{"x": p.x, "y": p.y} for p in box.vertices])
            self.assertEqual(box._local_axes_xy(), fresh._local_axes_xy(), f"angle={angle}")
            self.assertEqual(box.width, fresh.width, f"angle={angle}")
            self.assertEqual(box.height, fresh.height, f"angle={angle}")
            self.assertEqual((box.center.x, box.center.y), (fresh.center.x, fresh.center.y),
                             f"angle={angle}")
            self.assertEqual(box._axis_bounds(), fresh._axis_bounds(), f"angle={angle}")
        self.assertTrue(reordered_any, "no orientation in this set actually reordered vertices")

    def test_cached_values_match_a_freshly_built_box(self):
        for angle in (0, 7, 30, 90, 180, 271):
            src = bbox_factory(Point(300, 250), angle=angle, size=(80, 24))
            fresh = BoundingBox([{"x": p.x, "y": p.y} for p in src.vertices])
            # touch everything twice: second read must come from the cache and be equal
            for _ in range(2):
                self.assertEqual(src.width, fresh.width)
                self.assertEqual(src.height, fresh.height)
                self.assertEqual(src.center.x, fresh.center.x)
                self.assertEqual(src.center.y, fresh.center.y)


class TestPrefilterNeverDropsAnAlignedPair(unittest.TestCase):
    def test_random_geometry(self):
        rng = random.Random(20260810)
        anchors = [bbox_factory(Point(rng.uniform(0, 600), rng.uniform(0, 800)),
                                angle=rng.choice([0, 0, 0, 3, -4, 25, 90, 180]),
                                size=(rng.uniform(8, 120), rng.uniform(6, 40)))
                   for _ in range(40)]
        others = [bbox_factory(Point(rng.uniform(0, 600), rng.uniform(0, 800)),
                               angle=rng.choice([0, 0, 0, 2, -3, 25, 90, 180]),
                               size=(rng.uniform(8, 120), rng.uniform(6, 40)))
                  for _ in range(60)]

        checked = aligned = 0
        for a in anchors:
            for b in others:
                for pos in POSITIONS:
                    checked += 1
                    exact = a.check_alingment(b, alingment_position=pos).is_aligned
                    if exact:
                        aligned += 1
                        self.assertTrue(
                            a.may_align(b, pos),
                            f"pre-filter rejected an aligned pair ({pos}): {a} vs {b}")
        self.assertGreater(checked, 5000)
        self.assertGreater(aligned, 0, "test geometry produced no aligned pairs at all")

    def test_near_boundary_pairs_are_passed_through(self):
        """A candidate sitting exactly on the tolerance boundary must not be pre-rejected."""
        anchor = rect(100, 100, 40, 20)
        # perpendicular drift equal to half the average height -> right at the band edge
        for dy in (0.0, 9.999, 10.0, 10.001):
            other = rect(200, 100 + dy, 40, 20)
            if anchor.check_alingment(other, alingment_position=AlignmentPosition.RIGHT).is_aligned:
                self.assertTrue(anchor.may_align(other, AlignmentPosition.RIGHT),
                                f"pre-filter rejected a boundary pair at dy={dy}")

    def test_prefilter_actually_rejects_the_obvious_cases(self):
        """Guard against the pre-filter degenerating into `return True`."""
        anchor = rect(100, 100, 40, 20)
        far_below = rect(100, 900, 40, 20)
        self.assertFalse(anchor.may_align(far_below, AlignmentPosition.RIGHT))
        self.assertFalse(anchor.may_align(far_below, AlignmentPosition.ABOVE))
        self.assertTrue(anchor.may_align(rect(200, 100, 40, 20), AlignmentPosition.RIGHT))

    def test_zero_distance_pair_is_rejected_like_the_exact_check(self):
        a = rect(10, 10, 40, 20)
        b = rect(10, 10, 40, 20)
        for pos in POSITIONS:
            self.assertFalse(a.check_alingment(b, alingment_position=pos).is_aligned)
            self.assertFalse(a.may_align(b, pos))


class TestInOtherBboxFastReject(unittest.TestCase):
    def test_matches_ray_casting_on_rotated_boxes(self):
        rng = random.Random(4242)
        boxes = [bbox_factory(Point(rng.uniform(0, 200), rng.uniform(0, 200)),
                              angle=rng.uniform(-180, 180),
                              size=(rng.uniform(5, 90), rng.uniform(5, 60)))
                 for _ in range(60)]
        hits = 0
        for a in boxes:
            for b in boxes:
                if a is b:
                    continue
                # reference implementation: ray casting with no axis-aligned shortcut
                center = a.center
                vs = b.vertices
                inside = False
                j = len(vs) - 1
                for i in range(len(vs)):
                    if (((vs[i].y > center.y) != (vs[j].y > center.y)) and
                            (center.x < (vs[j].x - vs[i].x) * (center.y - vs[i].y) /
                             (vs[j].y - vs[i].y) + vs[i].x)):
                        inside = not inside
                    j = i
                self.assertEqual(inside, a.in_other_bbox(b))
                hits += 1 if inside else 0
        self.assertGreater(hits, 0, "no containment cases exercised")

    def test_empty_vertices_is_not_contained(self):
        a = rect(0, 0, 10, 10)
        empty = BoundingBox([])
        self.assertFalse(a.in_other_bbox(empty))


if __name__ == "__main__":
    unittest.main()
