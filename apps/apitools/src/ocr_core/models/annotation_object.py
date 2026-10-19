from dataclasses import dataclass
import logging
import math
from copy import deepcopy
from typing import List, Tuple, Optional

from src.ocr_core.models.alingment_position import AlignmentPosition
from src.ocr_core.models.bounding_box import BTBAlignment, BoundingBox
from src.utils.storage import ocr_test_fails_path, ocr_test_files_path

logger = logging.getLogger(__name__)

from collections import Counter



@dataclass
class AlignedAnnotation:
    annotation: 'AnnotationObject'
    btb_alignment: BTBAlignment

class AlignedAnnotations:
    _alinged_annotations : List[AlignedAnnotation]

    def __init__(self, alinged_annotations: List[AlignedAnnotation] = []):
        self._alinged_annotations = alinged_annotations
        self.sorted_by_distance()

    @property
    def alinged_annotations(self):
        return self._alinged_annotations
    
    def sorted_by_distance(self):
        # Perpendicular alignment must dominate raw distance. Sorting by btb_distance alone
        # lets a DIAGONAL neighbour beat a same-row value when it is merely closer: on
        # "סה\"כ לתשלום | 4,626.00" with "מע\"מ | 705.66" one row up, 705.66 wins by
        # center-to-center distance (57 vs 63) despite 14px of vertical drift, and the
        # extractor returns the VAT instead of the total. Bucket the normalized
        # perpendicular error first (rounded, so near-equal drifts still fall through to
        # the distance tie-break), then sort by distance within a bucket.
        self._alinged_annotations = sorted(
            self._alinged_annotations,
            key=lambda x: (round(x.btb_alignment.alignment_error * 2) / 2.0,   # 0.5-wide buckets
                           x.btb_alignment.btb_distance))
        
    def filter_position(self, position: AlignmentPosition) -> List[AlignedAnnotation]:
        return [x for x in self._alinged_annotations if x.btb_alignment.alignment_position == position]
    
    

class AnnotationObject:
    def __init__(self, annotation_dict: dict, sub_annotations: List['AnnotationObject'] = None):
        self.sub_annotations: List['AnnotationObject'] = sub_annotations or []
        self.annotation_dict = annotation_dict
        self.bounding_box = BoundingBox(self.vertices)
        self.fix_missing()

    def __str__(self):
        return str(f"Annotation {self.annotation_dict}")

    # when print object
    def __repr__(self):
        return str(f"Annotation {self.annotation_dict}")

    def fix_missing(self):
        vertices = deepcopy(self.vertices)
        vertices = [{"x": v.get("x", 0), "y": v.get("y", 0)} for v in vertices]
        self.vertices = vertices

    @property
    def description(self) -> str:
        return self.annotation_dict.get("description", "")
    
    @description.setter
    def description(self, value: str):
        self.annotation_dict["description"] = value

    @property
    def vertices(self) -> List[dict[str, float]]:
        return self.annotation_dict.get("boundingPoly", {}).get("vertices", [])


    # property set vertices (sets in the annotation_dict)
    @vertices.setter
    def vertices(self, value):
        self.annotation_dict["boundingPoly"]["vertices"] = value


    def in_annotation(self, other: 'AnnotationObject') -> bool:
        """Check if this annotation is inside another annotation. if center point is inside the other annotation"""
        return self.bounding_box.in_other_bbox(other.bounding_box)


    @classmethod
    def combine_annotations(cls, annotations: List['AnnotationObject']) -> 'AnnotationObject':
        first_ano = annotations[0].copy()
        first_ano.bounding_box.add_bboxes([ano.bounding_box for ano in annotations[1:]])
        
        new_vertices = first_ano.bounding_box.vertices
        new_vertices = [{"x": int(pt.x), "y": int(pt.y)} for pt in new_vertices]
        new_description = " ".join([anno.description for anno in annotations])
        return cls({
            "boundingPoly": {
                "vertices": new_vertices
            },
            "description": new_description
        }, sub_annotations=annotations)


    def aligned_annotations(self, annotations: List['AnnotationObject'], position: AlignmentPosition=None) -> AlignedAnnotations:
        """Filter a list of annotations for vertical or horizontal alignment with this annotation."""

        alinged_annotations_list = []
        self_bbox = self.bounding_box
        # When the caller names a direction — which every extraction path does, via
        # `annotations_aligned_with_annotation` — screen candidates with the cheap
        # NECESSARY condition first. `may_align` only ever answers "provably not aligned";
        # anything it lets through is still decided by `check_alingment` below, whose
        # result is used verbatim. Without it, a single anchor built ~250 full BTBAlignment
        # objects through numpy to keep the handful actually on its line.
        prefilter = self_bbox.alignment_prefilter(position) if position is not None else None
        for annotation in annotations:
            other_bbox = annotation.bounding_box
            if prefilter is not None and not prefilter(other_bbox):
                continue
            btb_alingment = self_bbox.check_alingment(other_bbox, alingment_position=position)
            if btb_alingment.is_aligned:
                alinged_annotations_list.append(AlignedAnnotation(annotation, btb_alingment))

        alinged_annotations = AlignedAnnotations(alinged_annotations_list)
        return alinged_annotations


    
    def is_intro(self) -> bool:
        intro_characters = [':', '-', '=', '|', '->', '=>', '~', ' ', '\t', ';', '/', '_', '(', ')', '[', ']', '{', '}',
                            '*', "'", '"', '`']
        annotation_text = self.description.strip()
        return annotation_text in intro_characters

    def is_rtl(self) -> bool:
        """Check if the annotation contains RTL characters."""
        rtl_characters = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ', 'ק',
                          'ר', 'ש', 'ת']
        return any(char in self.description for char in rtl_characters)
    
    def copy(self) -> 'AnnotationObject':
        """Create a copy of the annotation object."""
        return AnnotationObject(deepcopy(self.annotation_dict), deepcopy(self.sub_annotations))
    

def test_combining_annotations():
    annotation1 = {
        "boundingPoly": {
            "vertices": [
                {"x": 10, "y": 20},
                {"x": 50, "y": 20},
                {"x": 50, "y": 60},
                {"x": 10, "y": 60}
            ]
        },
        "description": "Test annotation 1"
    }
    annotation2 = {
        "boundingPoly": {
            "vertices": [
                {"x": 30, "y": 40},
                {"x": 70, "y": 40},
                {"x": 70, "y": 80},
                {"x": 30, "y": 80}
            ]
        },
        "description": "Test annotation 2"
    }

    obj1 = AnnotationObject(annotation1)
    obj2 = AnnotationObject(annotation2)

    result = AnnotationObject.combine_annotations([obj1, obj2])
    
    # draw the combined bounding box
    
    print("Results Decription", result.description)
    print("Results Vertices", result.vertices)
    assert result.vertices == [{"x": 10, "y": 20}, {"x": 70, "y": 20}, {"x": 70, "y": 80}, {"x": 10, "y": 80}]
    print("Test case passed")

def test_aligned_annoations() :
    from src.ocr_core.ocr_object import OcrObject

    file = ".test_files/ocr_test_files/file.png"
    file = f"{ocr_test_fails_path()}/rotated.jpg"

    ocr_object = OcrObject.from_file_path(file)
    annotations = ocr_object.ocr_data.text_annotations
    anno = None
    for annotation in annotations:
        if annotation.description == "תעודת":
            print("found")
            print(annotation.vertices)
            anno = annotation
            break
    
    if not anno:
        print("Annotation not found")
        return

    alinged_annotations = anno.aligned_annotations(annotations)
    
    for alinged_anno in alinged_annotations.filter_position(AlignmentPosition.LEFT):
        print("Before")
        print(alinged_anno.annotation.description, alinged_anno.btb_alignment.btb_distance)

    for alinged_anno in alinged_annotations.filter_position(AlignmentPosition.RIGHT):
        print("After")
        print(alinged_anno.annotation.description, alinged_anno.btb_alignment.btb_distance)    


    

    # check with draw 
    bbox1 = anno.bounding_box
    bboxs = [x.bounding_box for x in annotations]
    # use ocr_object.drawing.draw_alignment to draw the alignment check


    # draw all the annotations on the image
    ocr_object.drawing.draw_annotations(annotations, color="blue", width=2)
    ocr_object.drawing.show_drawing_image()


if __name__ == "__main__":
    test_combining_annotations()
    # test_aligned_annoations()
    pass
