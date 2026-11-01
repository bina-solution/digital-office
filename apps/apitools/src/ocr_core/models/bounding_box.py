from dataclasses import dataclass
import math
from enum import StrEnum
from typing import List, Dict, Optional, Tuple

import cv2
import numpy as np

from src.ocr_core.models.alingment_position import AlignmentPosition
from src.utils.storage import alingment_test_files_path
from src.ocr_core.models.point import Point




class PointPosition(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT = "bottom_left"




SKEW_TOLERANCE_VERTICAL = 0.6
SKEW_TOLERANCE_HORIZONTAL = 0.35
SKEW_TOLERANCE_CAP_MULTIPLIER = 2.0

# Head-room used by `BoundingBox.may_align` (the cheap pre-filter) so it can never reject a
# pair that the exact numpy path would have accepted. Sized ~10 orders of magnitude above
# the measured scalar-vs-numpy disagreement (~1 ULP on ~6 % of real pairs) while still
# rejecting the overwhelming majority of candidates, which sit nowhere near the boundary.
_PREFILTER_SLACK = 1e-6


@dataclass
class BTBAlignment():
    is_aligned: bool = False
    alignment_error: float = 0.0
    alignment_confidence: float = 0.0
    btb_distance: float = 0.0
    alignment_position: Optional[AlignmentPosition] = None
    alignment_angle: float = 0.0
    primary_projection: float = 0.0
    perpendicular_projection: float = 0.0
    perpendicular_band: float = 0.0
    perpendicular_band_base: float = 0.0
    tolerance_ratio: float = 1.0
    normalized_primary: float = 0.0
    normalized_perpendicular: float = 0.0
    primary_axis_vector: Optional[Tuple[float, float]] = None
    perpendicular_axis_vector: Optional[Tuple[float, float]] = None
    bbox1: 'BoundingBox' = None
    bbox2: 'BoundingBox' = None
    


class BoundingBox:
    """Bounding box class that represents a rectangle with 4 vertices. Each vertex is a Point object.
    The rule is that the first point is top left of the rectangle relative to the text direction."""

    def __init__(self, vertices: List[Dict[str, int]]):
        self.vertices: List[Point] = [Point(**vertex) for vertex in vertices]

    # ── PER-BOX GEOMETRY CACHE ────────────────────────────────────────────────────
    # MEASURED HOTSPOT (in-container cProfile over 8 real `base` extractions, 2026-08-10):
    # `check_alingment` ran 84,047 times for 27.5 s of a 51.5 s run — and 12.3 s of that
    # was `_local_axes`, which is the ANCHOR's OWN axes, rebuilt from scratch against
    # every one of the ~250 candidates the anchor is compared with. `center` (594,928
    # calls), `width`/`height` (911,304 edge-length calls) were recomputed per pair the
    # same way.
    #
    # All of it is a pure function of `vertices`, and vertices are only ever REPLACED
    # WHOLESALE — `__init__`, `match_bbox_orientation`, `add_bboxes`, and nothing in the
    # tree mutates a Point in place (verified by grep) — so the setter below is the
    # complete invalidation point. Every cached value is the identical float the old code
    # produced: this changes HOW OFTEN geometry is computed, never WHAT it computes.
    @property
    def vertices(self) -> List[Point]:
        return self._vertices

    @vertices.setter
    def vertices(self, value: List[Point]):
        self._vertices = value
        self._cache_center = None
        self._cache_center_xy = None
        self._cache_center_vec = None
        self._cache_width = None
        self._cache_height = None
        self._cache_axes = None
        self._cache_axes_xy = None
        self._cache_aabb = None

    @property
    def p1(self) -> Point:
        return self._vertices[0]

    @property
    def p2(self) -> Point:
        return self._vertices[1]

    @property
    def p3(self) -> Point:
        return self._vertices[2]

    @property
    def p4(self) -> Point:
        return self._vertices[3]

    @property
    def height(self) -> float:
        """
        Calculate the true height of the bounding box, even when rotated.
        Returns the longer of the two vertical edges.
        """
        h = self._cache_height
        if h is None:
            # Calculate lengths of both potential height edges
            left_edge = self._calculate_edge_length(self.p1, self.p4)
            right_edge = self._calculate_edge_length(self.p2, self.p3)

            # Return the longer edge as height
            h = self._cache_height = max(left_edge, right_edge)
        return h

    @property
    def width(self) -> float:
        """
        Calculate the true width of the bounding box, even when rotated.
        Returns the longer of the two horizontal edges.
        """
        w = self._cache_width
        if w is None:
            # Calculate lengths of both potential width edges
            top_edge = self._calculate_edge_length(self.p1, self.p2)
            bottom_edge = self._calculate_edge_length(self.p3, self.p4)

            # Return the longer edge as width
            w = self._cache_width = max(top_edge, bottom_edge)
        return w

    @property
    def center_x(self) -> float:
        return self.center.x

    @property
    def center_y(self) -> float:
        return self.center.y

    @property
    def center(self) -> Point:
        """Returns the center of the bounding box"""
        c = self._cache_center
        if c is None:
            # Same expression as before, same Point constructor (which maps a falsy
            # coordinate to 0) — only computed once per box now.
            c = self._cache_center = Point((self.p1.x + self.p3.x) / 2,
                                           (self.p1.y + self.p3.y) / 2)
        return c

    def _center_vector(self) -> np.ndarray:
        """Cached `_point_to_vector(self.center)` — the exact array the old per-pair code built."""
        v = self._cache_center_vec
        if v is None:
            v = self._cache_center_vec = self._point_to_vector(self.center)
        return v

    def _center_xy(self) -> Tuple[float, float]:
        """Cached centre as two plain floats (used by the per-candidate pre-filter)."""
        xy = self._cache_center_xy
        if xy is None:
            c = self.center
            xy = self._cache_center_xy = (float(c.x), float(c.y))
        return xy

    def _local_axes_xy(self) -> Tuple[float, float, float, float]:
        """`_local_axes` as four plain floats. Pulling scalars out of a numpy array costs
        more than the arithmetic that consumes them, and the pre-filter runs once per
        candidate — so the conversion is done once per box instead."""
        f = self._cache_axes_xy
        if f is None:
            width_axis, height_axis = self._local_axes()
            f = self._cache_axes_xy = (float(width_axis[0]), float(width_axis[1]),
                                       float(height_axis[0]), float(height_axis[1]))
        return f

    def _axis_bounds(self):
        """(min_x, max_x, min_y, max_y) over the vertices, or None when there are none."""
        box = self._cache_aabb
        if box is None:
            vs = self._vertices
            if not vs:
                return None
            xs = [p.x for p in vs]
            ys = [p.y for p in vs]
            box = self._cache_aabb = (min(xs), max(xs), min(ys), max(ys))
        return box

    @property
    def angel(self):
        """Returns angel between top points (p1 and p2)"""
        angel = math.degrees(math.atan2(self.p2.y - self.p1.y, self.p2.x - self.p1.x)) 
        return angel

    def distance(self, other_bbox: 'BoundingBox'):
        return max(abs(self.center.x - other_bbox.center.x), abs(self.center.y - other_bbox.center.y))

    def b2b_angle(self, other_bbox: 'BoundingBox'):
        btb_angel = math.degrees(math.atan2(other_bbox.center.y - self.center.y, other_bbox.center.x - self.center.x))
        return btb_angel

    def points_position_relative_to_page(self) -> List[PointPosition]:
        """ Calculates the position of each point in the rectangle relative to the page.
        This can be used to match the orientation of the bounding box with another bounding box.

        :return: list of PointPosition Enum representing the position of each point in the rectangle 
        """

        # Sort the points by x (so first points are left points)
        sorted_by_x_points = sorted(self.vertices, key=lambda p: p.x)

        half_points_idx = int(len(sorted_by_x_points) // 2)
        left_points = sorted_by_x_points[:half_points_idx]
        right_points = sorted_by_x_points[half_points_idx:]

        # Sort the left and right points by y (so first points are top points)
        left_points = sorted(left_points, key=lambda p: p.y)
        right_points = sorted(right_points, key=lambda p: p.y)

        points_place = []

        top_left = left_points[0]
        top_left_index = self.vertices.index(top_left)
        points_place.append((PointPosition.TOP_LEFT, top_left_index))

        top_right = right_points[0]
        top_right_index = self.vertices.index(top_right)
        points_place.append((PointPosition.TOP_RIGHT, top_right_index))

        if len(left_points) > 1:
            bottom_left = left_points[-1]
            bottom_left_index = self.vertices.index(bottom_left)
            points_place.append((PointPosition.BOTTOM_LEFT, bottom_left_index))

        if len(right_points) > 1:
            bottom_right = right_points[-1]
            bottom_right_index = self.vertices.index(bottom_right)
            points_place.append((PointPosition.BOTTOM_RIGHT, bottom_right_index))

        # Sort the points by the index, so it matches the original points order
        points_place = sorted(points_place, key=lambda pp: pp[1])
        points_place = [p[0] for p in points_place]
        return points_place

    def match_bbox_orientation(self, bbox_matcher: 'BoundingBox'):
        """ Gets bounding box and a bounding box matcher and rotates the bounding box to match the matcher points order
        For example if matcher order is (top-left, top-right, bottom-right, bottom-left) the bbox order will be changed
        to match it
        used for when combining bboxs, and we want the generated bbox to have the same orientation as the sub bboxs
        """

        matcher_points_place = bbox_matcher.points_position_relative_to_page()

        points_place = self.points_position_relative_to_page()
        new_points = []
        for point_position in matcher_points_place:
            matching_point_index = points_place.index(point_position)
            point = self.vertices[matching_point_index]
            new_points.append(point)

        self.vertices = new_points
        # To fully support 3 points bounding box we need to think a little more
        return new_points

    def add_bboxes(self, bboxes: List['BoundingBox']):
        """Grow the bbox to fit all the bboxes using minAreaRect."""
        self_copy = self.copy()
        all_bboxes = [self] + bboxes
        all_points = []
        for bbox in all_bboxes:
            all_points.extend([(p.x, p.y) for p in bbox.vertices])

        # Convert to numpy array for minAreaRect computation
        all_points = np.array(all_points, dtype=np.float32)

        # Compute the minimum area rectangle
        rect = cv2.minAreaRect(all_points)  # rect contains (center, (width, height), angle)
        box = cv2.boxPoints(rect)  # Get 4 points of the rectangle
        box = np.intp(box)  # Convert to integer coordinates

        # Update the current bounding box vertices
        self.vertices = [Point(x=x, y=y) for x, y in box]
        self.match_bbox_orientation(self_copy)

    def in_other_bbox(self, other_bbox: 'BoundingBox') -> bool:
        """Check if self.center is inside other_bbox space in rotated environment"""
        center = self.center
        vertices = other_bbox._vertices

        # AXIS-ALIGNED FAST REJECT. A point outside the other box's axis-aligned bounds is
        # necessarily outside its polygon, so this can only skip ray casts that were always
        # going to return False — the answer is unchanged. Measured: the candidate filter in
        # `annotations_aligned_with_annotation` ran 312,213 ray casts (4.4 s) per 8-document
        # profile, nearly all of them against boxes elsewhere on the page.
        bounds = other_bbox._axis_bounds()
        if bounds is None:
            return False
        min_x, max_x, min_y, max_y = bounds
        cx, cy = center.x, center.y
        if cx < min_x or cx > max_x or cy < min_y or cy > max_y:
            return False

        # Ray casting algorithm
        inside = False
        j = len(vertices) - 1
        for i in range(len(vertices)):
            # Check if ray crosses the edge from vertices[j] to vertices[i]
            if (((vertices[i].y > center.y) != (vertices[j].y > center.y)) and
                (center.x < (vertices[j].x - vertices[i].x) * (center.y - vertices[i].y) / 
                 (vertices[j].y - vertices[i].y) + vertices[i].x)):
                inside = not inside
            j = i
        
        return inside
    
    def check_alingment(
        self,
        bbox2: 'BoundingBox',
        alingment_position: Optional[AlignmentPosition] = None,
        tolerance_ratio: float = 1.0,
    ) -> BTBAlignment:
        """Check if bbox2 is aligned with self using vector projections in the box-local frame.

        The algorithm projects the center-to-center vector onto the box axes, measures the
        perpendicular drift in normalized units, and evaluates it against a tolerance band that
        grows with the distance travelled along the dominant axis. This preserves predictable
        behaviour for near-perfect alignments while allowing a controlled amount of diagonal skew
        for misaligned table columns and similar layouts.

        :param bbox2: BoundingBox to check alignment against.
        :param alingment_position: Optional direction filter (LEFT/RIGHT/ABOVE/BELOW).
        :param tolerance_ratio: Multiplier for the half-dimension tolerance band (default 1.0).
        :return: BTBAlignment object describing the relationship between the two boxes.
        """

        tolerance_ratio = max(tolerance_ratio, 0.0)

        # Identical arithmetic to `_point_to_vector(bbox2.center) - _point_to_vector(self.center)`
        # — numpy subtraction is element-wise, so caching the two operands per box changes
        # nothing about the resulting floats.
        delta_vec = bbox2._center_vector() - self._center_vector()
        btb_dist = float(np.linalg.norm(delta_vec))

        if btb_dist == 0:
            return BTBAlignment(
                is_aligned=False,
                alignment_error=0.0,
                alignment_confidence=0.0,
                btb_distance=0.0,
                alignment_position=None,
                alignment_angle=0.0,
                primary_projection=0.0,
                perpendicular_projection=0.0,
                perpendicular_band=0.0,
                perpendicular_band_base=0.0,
                tolerance_ratio=tolerance_ratio,
                normalized_primary=0.0,
                normalized_perpendicular=0.0,
                primary_axis_vector=None,
                perpendicular_axis_vector=None,
                bbox1=self,
                bbox2=bbox2,
            )

        width_axis, height_axis = self._local_axes()
        local_x = float(np.dot(delta_vec, width_axis))
        local_y = float(np.dot(delta_vec, height_axis))

        avg_width = (self.width + bbox2.width) / 2.0
        avg_height = (self.height + bbox2.height) / 2.0
        width_scale = max(avg_width, 1e-6)
        height_scale = max(avg_height, 1e-6)

        angle_deg = (math.degrees(math.atan2(local_y, local_x)) + 360.0) % 360.0

        normalized_x = local_x / width_scale
        normalized_y = local_y / height_scale
        horizontal_dominant = abs(normalized_x) >= abs(normalized_y)

        if horizontal_dominant:
            alignment_position_calc = AlignmentPosition.RIGHT if normalized_x >= 0 else AlignmentPosition.LEFT
            primary_axis_vector = (float(width_axis[0]), float(width_axis[1]))
            perpendicular_axis_vector = (float(height_axis[0]), float(height_axis[1]))
            primary_projection = local_x
            primary_scale = width_scale
            perpendicular_projection = local_y
            perpendicular_band_base = max(avg_height / 2.0, 1e-6)
        else:
            alignment_position_calc = AlignmentPosition.BELOW if normalized_y >= 0 else AlignmentPosition.ABOVE
            primary_axis_vector = (float(height_axis[0]), float(height_axis[1]))
            perpendicular_axis_vector = (float(width_axis[0]), float(width_axis[1]))
            primary_projection = local_y
            primary_scale = height_scale
            perpendicular_projection = local_x
            perpendicular_band_base = max(avg_width / 2.0, 1e-6)

        normalized_primary = primary_projection / primary_scale

        if alignment_position_calc in (AlignmentPosition.ABOVE, AlignmentPosition.BELOW):
            skew_factor = SKEW_TOLERANCE_VERTICAL
        else:
            skew_factor = SKEW_TOLERANCE_HORIZONTAL

        skew_cap = perpendicular_band_base * SKEW_TOLERANCE_CAP_MULTIPLIER
        skew_adjustment = skew_factor * min(abs(primary_projection), skew_cap)
        perpendicular_band = max(perpendicular_band_base + skew_adjustment, 1e-6)

        normalized_perpendicular = abs(perpendicular_projection) / perpendicular_band
        alignment_error = normalized_perpendicular
        confidence_denominator = max(tolerance_ratio, 1e-6)
        alignment_confidence = max(0.0, 1.0 - (normalized_perpendicular / confidence_denominator))

        is_aligned = normalized_perpendicular <= tolerance_ratio
        if alingment_position and alignment_position_calc != alingment_position:
            is_aligned = False

        return BTBAlignment(
            is_aligned=is_aligned,
            alignment_error=alignment_error,
            alignment_confidence=alignment_confidence,
            btb_distance=btb_dist,
            alignment_position=alignment_position_calc,
                alignment_angle=angle_deg,
            primary_projection=primary_projection,
            perpendicular_projection=perpendicular_projection,
                perpendicular_band=perpendicular_band,
                perpendicular_band_base=perpendicular_band_base,
            tolerance_ratio=tolerance_ratio,
            normalized_primary=normalized_primary,
            normalized_perpendicular=normalized_perpendicular,
            primary_axis_vector=primary_axis_vector,
            perpendicular_axis_vector=perpendicular_axis_vector,
            bbox1=self,
            bbox2=bbox2,
        )

    def may_align(
        self,
        bbox2: 'BoundingBox',
        alingment_position: AlignmentPosition,
        tolerance_ratio: float = 1.0,
    ) -> bool:
        """Cheap NECESSARY condition for `check_alingment(...).is_aligned` in a known direction.

        Returns False only when the exact check provably cannot report is_aligned=True for
        this pair and this direction; a True answer decides nothing — the caller still runs
        `check_alingment` and uses its result verbatim. So this can only skip work, never
        change an outcome.

        WHY IT IS SAFE DESPITE USING PLAIN FLOATS. numpy's 2-element `dot` is not
        bit-identical to `a*b + c*d` in Python — measured on this container's numpy 1.26.4
        over 239,024 real annotation pairs, 6.3 % differ, by ~1 ULP (it is FMA/SIMD-backed,
        scalar Python is not). Every comparison below therefore carries `_PREFILTER_SLACK`
        of head-room, which is ~10 orders of magnitude larger than that discrepancy, so a
        pair anywhere near a decision boundary is passed through to the exact code rather
        than judged here.

        WHY IT PAYS. `aligned_annotations` compares one anchor against up to
        APITOOLS_ALIGNMENT_MAX_CANDIDATES (250) boxes and keeps the handful that are
        genuinely on the same line/column. Before this, every one of those 250 built a
        full 20-field BTBAlignment through numpy just to be discarded.
        """

        return self.alignment_prefilter(alingment_position, tolerance_ratio)(bbox2)

    def alignment_prefilter(
        self,
        alingment_position: AlignmentPosition,
        tolerance_ratio: float = 1.0,
    ):
        """Build `may_align` as a one-argument predicate with THIS box's geometry resolved once.

        A scan compares one anchor against hundreds of candidates, so every anchor-side
        value (centre, axes, own width/height) and every branch decision is lifted out of
        the per-candidate path here. See `may_align` for what the predicate guarantees.
        """
        if alingment_position not in (AlignmentPosition.LEFT, AlignmentPosition.RIGHT,
                                      AlignmentPosition.ABOVE, AlignmentPosition.BELOW):
            # No direction constraint means both the horizontal and the vertical branch of
            # the exact check are reachable, so nothing can be ruled out cheaply.
            return lambda bbox2: True

        c1x, c1y = self._center_xy()
        wx, wy, hx, hy = self._local_axes_xy()
        self_width = self.width
        self_height = self.height
        slack = _PREFILTER_SLACK
        horizontal = alingment_position in (AlignmentPosition.LEFT, AlignmentPosition.RIGHT)
        # RIGHT and BELOW are the branches the exact code reaches on a non-negative
        # normalized projection; LEFT and ABOVE on a negative one.
        want_positive = alingment_position in (AlignmentPosition.RIGHT, AlignmentPosition.BELOW)
        skew_factor = SKEW_TOLERANCE_HORIZONTAL if horizontal else SKEW_TOLERANCE_VERTICAL

        def _may_align(bbox2: 'BoundingBox') -> bool:
            c2x, c2y = bbox2._center_xy()
            dx = c2x - c1x
            dy = c2y - c1y
            if dx == 0.0 and dy == 0.0:
                # zero centre-to-centre distance short-circuits to is_aligned=False upstream
                return False

            local_x = dx * wx + dy * wy
            local_y = dx * hx + dy * hy

            avg_width = (self_width + bbox2.width) / 2.0
            avg_height = (self_height + bbox2.height) / 2.0
            norm_x = local_x / (avg_width if avg_width > 1e-6 else 1e-6)
            norm_y = local_y / (avg_height if avg_height > 1e-6 else 1e-6)
            abs_x = -norm_x if norm_x < 0.0 else norm_x
            abs_y = -norm_y if norm_y < 0.0 else norm_y

            if horizontal:
                # LEFT/RIGHT is only reachable when the horizontal projection dominates
                if abs_x < abs_y - slack * (abs_y + 1.0):
                    return False
                if want_positive:
                    if norm_x < -slack:
                        return False
                elif norm_x > slack:
                    return False
                primary, perpendicular = local_x, local_y
                band_base = avg_height / 2.0
            else:
                # ABOVE/BELOW is only reachable when the vertical projection dominates
                if abs_y < abs_x - slack * (abs_x + 1.0):
                    return False
                if want_positive:
                    if norm_y < -slack:
                        return False
                elif norm_y > slack:
                    return False
                primary, perpendicular = local_y, local_x
                band_base = avg_width / 2.0

            if band_base < 1e-6:
                band_base = 1e-6
            abs_primary = -primary if primary < 0.0 else primary
            cap = band_base * SKEW_TOLERANCE_CAP_MULTIPLIER
            band = band_base + skew_factor * (abs_primary if abs_primary < cap else cap)
            if band < 1e-6:
                band = 1e-6
            limit = band * tolerance_ratio
            abs_perp = -perpendicular if perpendicular < 0.0 else perpendicular
            return abs_perp <= limit + slack * (limit + 1.0)

        return _may_align

    def is_aligned(
        self,
        bbox2: 'BoundingBox',
        alingment_position: Optional[AlignmentPosition] = None,
        tolerance_ratio: float = 1.0,
    ) -> bool:
        """Shortcut that returns only the boolean alignment result."""

        return self.check_alingment(
            bbox2,
            alingment_position=alingment_position,
            tolerance_ratio=tolerance_ratio,
        ).is_aligned

    def copy(self):
        return BoundingBox([{'x': p.x, 'y': p.y} for p in self.vertices])

    def __repr__(self):
        return f"BoundingBox({self.vertices})"

    @staticmethod
    def _calculate_edge_length(point1: Point, point2: Point) -> float:
        """Calculate the length between two points using Pythagorean theorem."""
        return ((point2.x - point1.x) ** 2 + (point2.y - point1.y) ** 2) ** 0.5

    @staticmethod
    def _point_to_vector(point: Point) -> np.ndarray:
        """Convert a Point to a numpy vector for linear algebra operations."""

        return np.array([float(point.x), float(point.y)], dtype=np.float64)

    @staticmethod
    def _normalize_vector(vector: np.ndarray) -> np.ndarray:
        """Return a unit vector, keeping zeros intact to avoid NaNs."""

        norm = np.linalg.norm(vector)
        if norm < 1e-6:
            return vector
        return vector / norm

    def _local_axes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return orthonormal width/height axes anchored at the first vertex.

        Cached: this is the single largest cost in the alignment scan (12.3 s of a 51.5 s
        profile) purely because the anchor's axes were rebuilt for every candidate it was
        compared against. The arrays are treated as read-only by every caller.
        """

        axes = self._cache_axes
        if axes is not None:
            return axes

        p1_vec = self._point_to_vector(self.p1)
        width_vec = self._point_to_vector(self.p2) - p1_vec
        height_vec = self._point_to_vector(self.p4) - p1_vec

        width_axis = self._normalize_vector(width_vec)
        if np.linalg.norm(width_axis) < 1e-6:
            width_axis = np.array([1.0, 0.0], dtype=np.float64)

        height_vec_orth = height_vec - np.dot(height_vec, width_axis) * width_axis
        height_axis = self._normalize_vector(height_vec_orth)
        if np.linalg.norm(height_axis) < 1e-6:
            height_axis = np.array([-width_axis[1], width_axis[0]], dtype=np.float64)
        elif np.dot(height_axis, height_vec) < 0:
            height_axis = -height_axis

        self._cache_axes = (width_axis, height_axis)
        return width_axis, height_axis



def bbox_factory(center: Point = Point(250, 250), angle: float = 0, size: tuple = (50, 25)) -> BoundingBox:
    """Generate a bounding box from center, angle and size"""
    # Unpack size
    width, height = size
    # Convert angle to radians
    angle_radians = math.radians(angle)
    # Calculate half-width and half-height
    half_width = width / 2
    half_height = height / 2
    # Define the four corner points of the rectangle before rotation
    corners = [
        (-half_width, -half_height),  # bottom-left
        (half_width, -half_height),  # bottom-right
        (half_width, half_height),  # top-right
        (-half_width, half_height)  # top-left
    ]
    # Rotation matrix
    rotation_matrix = np.array([
        [np.cos(angle_radians), -np.sin(angle_radians)],
        [np.sin(angle_radians), np.cos(angle_radians)]
    ])
    # Rotate and translate corners
    rotated_corners = []
    for corner in corners:
        # Rotate
        rotated_corner = np.dot(rotation_matrix, corner)

        # Translate
        final_x = rotated_corner[0] + center.x
        final_y = rotated_corner[1] + center.y

        # Convert to dictionary and add to list
        rotated_corners.append({
            "x": final_x,
            "y": final_y
        })
    # Create a BoundingBox object from the rotated corners
    return BoundingBox(rotated_corners)

def test_get_points_place():
    from src.ocr_core.ocr_drawings import ocr_drawings_factory
    ocr_draw = ocr_drawings_factory(im_size=(800, 600), color="white")
    bbox_matcher = BoundingBox([{'x': 100, 'y': 100}, {'x': 200, 'y': 100}, {'x': 200, 'y': 150}, {'x': 100, 'y': 150}])
    print(bbox_matcher.points_position_relative_to_page())

    bbox = BoundingBox([{'x': 400, 'y': 500}, {'x': 500, 'y': 450}, {'x': 500, 'y': 500}, {'x': 400, 'y': 450}])
    print(bbox.points_position_relative_to_page())

    ocr_draw.draw_bbox(bbox_matcher, color="red")
    ocr_draw.draw_bbox(bbox, color="blue")

    ocr_draw.show()
    input("Press Enter to continue...")

    res = bbox.match_bbox_orientation(bbox_matcher)
    print(res)
    print(bbox.points_position_relative_to_page())

    ocr_draw.draw_bbox(bbox)
    ocr_draw.draw_bbox(bbox_matcher, color="red")

    bbox_matcher.add_bboxes([bbox])
    print(bbox_matcher)
    ocr_draw.draw_bbox(bbox_matcher, color="orange")
    ocr_draw.show()

def test_alingments_via_img(alingment_img: str):
    from src.ocr_core.ocr_object import OcrObject
    
    ocr_obj = OcrObject.from_file_path(alingment_img)
    annos = ocr_obj.ocr_data.text_annotations
    

    center_anno = [a for a in annos if a.description == "טקסט"]
    assert len(center_anno) == 1, "No center anno found"
    center_bbox = center_anno[0].bounding_box

    left_anno = [a for a in annos if a.description == "שמאל"]
    left_alingment = center_bbox.check_alingment(left_anno[0].bounding_box)
    print(
        "left alingment",
        left_alingment.alignment_position,
        left_alingment.alignment_error,
        left_alingment.alignment_confidence,
        left_alingment.btb_distance,
        left_alingment.perpendicular_projection,
    )
    ocr_obj.drawing.draw_alignment_check(left_alingment)
    assert left_alingment.is_aligned, "Left alignment is not aligned"
    assert left_alingment.alignment_position == AlignmentPosition.LEFT, f"Left alignment is not left its {left_alingment.alignment_position}"
    
    
    right_anno = [a for a in annos if a.description == "ימין"]
    right_alingment = center_bbox.check_alingment(right_anno[0].bounding_box)
    print(
        "right alingment",
        right_alingment.alignment_position,
        right_alingment.alignment_error,
        right_alingment.alignment_confidence,
        right_alingment.btb_distance,
        right_alingment.perpendicular_projection,
    )
    ocr_obj.drawing.draw_alignment_check(right_alingment)
    assert right_alingment.is_aligned, "Right alignment is not aligned"
    assert right_alingment.alignment_position == AlignmentPosition.RIGHT, "Right alignment is not right"
    
    above_anno = [a for a in annos if a.description == "למעלה"]
    above_alingment = center_bbox.check_alingment(above_anno[0].bounding_box)
    print(
        "above alingment",
        above_alingment.alignment_position,
        above_alingment.alignment_error,
        above_alingment.alignment_confidence,
        above_alingment.btb_distance,
        above_alingment.perpendicular_projection,
    )
    ocr_obj.drawing.draw_alignment_check(above_alingment)
    assert above_alingment.is_aligned, "Above alignment is not aligned"
    assert above_alingment.alignment_position == AlignmentPosition.ABOVE, "Above alignment is not above"
    
    below_anno = [a for a in annos if a.description == "למטה"]
    below_alingment = center_bbox.check_alingment(below_anno[0].bounding_box)
    print(
        "below alingment",
        below_alingment.alignment_position,
        below_alingment.alignment_error,
        below_alingment.alignment_confidence,
        below_alingment.btb_distance,
        below_alingment.perpendicular_projection,
    )
    ocr_obj.drawing.draw_alignment_check(below_alingment)
    assert below_alingment.is_aligned, "Below alignment is not aligned"
    assert below_alingment.alignment_position == AlignmentPosition.BELOW, "Below alignment is not below"
    
    ocr_obj.drawing.show()

def test_alingments_via_images():
    alingment_img = f"{alingment_test_files_path()}/alingment_test.jpg"
    test_alingments_via_img(alingment_img)
    print("Test using alingment image passed successfully")
    
    rotated_up = f"{alingment_test_files_path()}/alingment_test_rotated_up.jpg"
    test_alingments_via_img(rotated_up)
    print("Test using rotated up image passed successfully")
    
    rotated_down = f"{alingment_test_files_path()}/alingment_test_rotated_down.jpg"
    test_alingments_via_img(rotated_down)
    print("Test using rotated down image passed successfully")
    
    upside_down = f"{alingment_test_files_path()}/alingment_test_upsidedown.jpg"
    test_alingments_via_img(upside_down)
    print("Test using upside down image passed successfully")
    



if __name__ == "__main__":
    test_get_points_place()
    
    input("Press Enter to continue...")
    test_alingments_via_images()
    # check_is_aligned()
