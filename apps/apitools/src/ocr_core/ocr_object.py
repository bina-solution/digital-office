from src.ocr_core.models.annotation_object import AnnotationObject
from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_drawings import OcrDrawings
from src.ocr_core.ocr_json_query import OcrJsonQuery
from src.ocr_core.ocr_query import OcrQuery
from src.utils.storage import ocr_test_files_path, ocr_test_fails_path


class OcrObject:

    def __init__(self, ocr_data: OcrData):
        self.ocr_data = ocr_data

        self.drawing = OcrDrawings(ocr_data=self.ocr_data)
        self.query = OcrQuery(ocr_data=self.ocr_data, ocr_drawer=self.drawing)
        self.json_query = OcrJsonQuery(ocr_query=self.query)

    @classmethod
    def from_file_id(cls, file_id: int, ocr_engine: str = None):
        ocr_data = OcrData.from_file_id(file_id, ocr_engine=ocr_engine)
        return cls(ocr_data)

    @classmethod
    def from_file_path(cls, file_path: str, cache: bool = True, ocr_engine: str = None):
        ocr_data = OcrData.from_file_path(file_path, cache=cache, ocr_engine=ocr_engine)
        return cls(ocr_data)


def ocr_object_example():
    filename = f"{ocr_test_files_path()}/file8.jpg"
    ocr = OcrObject.from_file_path(filename)
    ocr.drawing.draw_annotations(ocr.ocr_data.text_annotations, color="blue", width=2)

    print(ocr.ocr_data.full_text)
    # vals = ocr.query.find_value_by_relative_position(["חשבונית מס"], relative_position=RelativePosition.AFTER,
    # rtl=True, draw=True)
    json_query_results = ocr.json_query.json_query({"action": "find after", "action_value": ["חשבונית מס"], "is_rtl": True})
    print(json_query_results)

    process_context = json_query_results["process_context"]

    match_anno = process_context.get("find_results", {}).get("aligned_annotation", {})

    print(match_anno)
    if match_anno:
        anno = AnnotationObject(match_anno)
        ocr.drawing.draw_annotations([anno], color="red", width=3)

    ocr.drawing.show()


if __name__ == "__main__":
    ocr_object_example()
