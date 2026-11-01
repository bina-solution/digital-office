from functools import cached_property
import os
from typing import List

from src.ocr_core.models.annotation_object import AnnotationObject
from src.ocr_core.ocr_processor import OcrProcessor
from src.utils.storage import factory_images_path, pdf_test_files_path


class OcrData:
    def __init__(self, ocr_dict: dict) -> None:
        self._ocr_dict = ocr_dict

    @property
    def file_id(self):
        return self.ocr_dict.get('file_id', None)

    @property
    def original_filepath(self):
        return self.ocr_dict.get('original_file_path', None)

    @property
    def image_filepath(self):
        return self.ocr_dict.get('image_path', None)

    @classmethod
    def from_file_id(cls, file_id: int, ocr_engine: str = None):
        ocr_processor = OcrProcessor(ocr_engine=ocr_engine) if ocr_engine else OcrProcessor()
        ocr_json = ocr_processor.load_file_ocr_by_id(file_id)
        return cls(ocr_json)

    @classmethod
    def from_file_path(cls, file_path: str, cache: bool = True, ocr_engine: str = None):
        if os.path.exists(file_path):
            ocr_processor = OcrProcessor(ocr_engine=ocr_engine) if ocr_engine else OcrProcessor()
            ocr_json = ocr_processor.get_ocr(file_path, cache=cache)
            ocr_json['file_path'] = file_path
            return cls(ocr_json)
        raise FileNotFoundError(f"Ocr Image file not found at {file_path}")

    @property
    def ocr_dict(self) -> dict:
        return self._ocr_dict

    @ocr_dict.setter
    def ocr_dict(self, new_ocr_dict: dict) -> None:
        if self._ocr_dict != new_ocr_dict:
            self._ocr_dict = new_ocr_dict
            # Invalidate the cache for text_annotations when ocr_dict changes
            if hasattr(self, '_text_annotations'):
                del self._text_annotations

    @cached_property
    def text_annotations(self) -> List[AnnotationObject]:
        text_annotations = self.ocr_dict.get('textAnnotations', [])

        # Convert each annotation to an AnnotationObject, preprocess it, and return the list of AnnotationObjects
        annotation_objects = [AnnotationObject(annotation) for annotation in text_annotations]

        return annotation_objects

    @property
    def full_text(self):
        return self.ocr_dict.get('fullTextAnnotation', {}).get('text', '')


def ocr_object_factory(image_size: tuple[int, int]) -> OcrData:
    """
    Factory function to create an Image and ocr_dict object with image path and file path.
    
    """
    from PIL import Image
    img = Image.new('RGB', image_size, color='white')
    img_path = f"{factory_images_path()}/test_image.png"
    img.save(img_path)
    ocr_dict = {
        'file_path': img_path,
        'image_path': img_path,
        'file_id': "factory_image_1973987",
        'fullTextAnnotation': {
            'text': 'Sample text',
            'pages': []
        },
        'textAnnotations': []
    }
    return OcrData(ocr_dict)

def ocr_object_example():
    file_path = f"{pdf_test_files_path()}/test1.pdf"
    ocr_object = OcrData.from_file_path(file_path)
    print(ocr_object.full_text)

    for annotation in ocr_object.text_annotations:
        print(annotation.description)
        print(annotation.vertices)
        print("----")


if __name__ == '__main__':
    ocr_object_example()
