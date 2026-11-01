import os
from typing import TYPE_CHECKING, List

import numpy as np
import PIL.Image
from PIL import ImageDraw, Image, ImageFont

from src.ocr_core.models.alingment_position import AlignmentPosition
from src.ocr_core.ocr_data import OcrData, ocr_object_factory
from src.utils.storage import (
    factory_images_path,
    storage_path,
    ocr_drawings_path,
    ocr_test_files_path,
)

if TYPE_CHECKING:
    from ocr_object import OcrObject
    from src.ocr_core.models.bounding_box import BoundingBox
    from src.ocr_core.models.annotation_object import AnnotationObject
    from src.ocr_core.models.bounding_box import BTBAlignment


class OcrDrawings:
    """
    OcrDrawings is a class that provides methods to draw ocr properties and operations on images. (bounding boxes, alingments, etc.)
    Its dependent on the OcrData class, which contains the ocr data and the image path.
    Allows easy-visual debugging of ocr querieng, alingment, and other operations.
    The class manges the image in memory and saves it to a file when needed.
    All functions allow to disable the save to file option, so the image can be manipulated in memory and saved later.

    Raises:
        FileNotFoundError: _description_

    """

    DRAWING_IMAGES_FOLDER = ocr_drawings_path()

    def __init__(self, ocr_data: OcrData):
        self.ocr_data = ocr_data
        self._memory_image = None
        self._memory_drawer = None
        
        # old
        # self.reset_drawing_image()
        # self._memory_image = Image.open(self.drawing_image_path)
        # self._memory_drawer = ImageDraw.Draw(self._memory_image)


    # Class management methods
    @property
    def image_filename(self):
        return os.path.basename(self.ocr_data.image_filepath)
    
    @property
    def drawing_image_path(self):
        return f"{self.DRAWING_IMAGES_FOLDER}/{self.image_filename}"

    @property
    def memory_image(self):
        if self._memory_image is None:
            self.reset_drawing_image()
            self._memory_image = Image.open(self.drawing_image_path)
        return self._memory_image

    @property
    def memory_drawer(self):
        if self._memory_drawer is None:
            self._memory_drawer = ImageDraw.Draw(self.memory_image)
        return self._memory_drawer

    def reset_drawing_image(self):
        if os.path.exists(self.ocr_data.image_filepath):
            image = PIL.Image.open(self.ocr_data.image_filepath)
            image.save(self.drawing_image_path)
            self._memory_image = image
            self._memory_drawer = ImageDraw.Draw(image)
            return
        raise FileNotFoundError(
            f"Ocr Image file not found at {self.ocr_data.image_filepath}"
        )

    def save_drawing_image(self):
        image = self.memory_image
        if image is None:
            return
        image.save(self.drawing_image_path)
        self._memory_drawer = ImageDraw.Draw(image)

    def show(self):
        img = self.memory_image
        img.show()

    # Basic PIL drawing wrappers
    def draw_line(self, start, end, color="orange", width=2, save=True):
        draw = self.memory_drawer
        draw.line(start + end, fill=color, width=width)
        if save:
            self.save_drawing_image()

    def draw_text(self, text, position, color="orange", font_size=20, save=True):
        draw = self.memory_drawer
        fnt = ImageFont.truetype("fonts/arial.ttf", font_size)
        draw.text(position, text, fill=color, font=fnt)
        if save:
            self.save_drawing_image()

    # OCR object and operations drawing methods
    def draw_bbox(
        self,
        bbox: "BoundingBox",
        save=True,
        angle_plus=True,
        angel_text=True,
        angel_color="blue",
        point_index=True,
        point_index_color="lightblue",
        point_text_index_color="black",
        color="gray",
    ):
        """Draw a bounding box on the image.

        Args:
            bbox (BoundingBox): Bounding box to draw.
            save (bool, optional): should save the image or keep changes in memory. Defaults to True.
            angle_plus (bool, optional): should draw + matching the angel in center of bbox. Defaults to True.
            angel_text (bool, optional): should draw the angel in center of bbox. Defaults to True.
            angel_color (str, optional): color of the angel text. Defaults to "blue".
            point_index (bool, optional): should draw the index of the points in the bbox. Defaults to True.
            point_index_color (str, optional): color of the points index. Defaults to "lightblue".
            point_text_index_color (str, optional): color of the points index text. Defaults to "black".
            color (str, optional): color of the bbox. Defaults to "gray".
        """

        draw = self.memory_drawer

        points = bbox.vertices
        bbox_length = len(points)
        for i in range(bbox_length):
            self.draw_line(
                (points[i].x, points[i].y),
                (points[(i + 1) % bbox_length].x, points[(i + 1) % bbox_length].y),
                color=color,
                width=2,
                save=False,
            )

        # draw + in  the center
        if angle_plus:
            self.draw_line(
                (bbox.center.x - 5, bbox.center.y),
                (bbox.center.x + 5, bbox.center.y),
                color=angel_color,
                width=2,
                save=False,
            )
            self.draw_line(
                (bbox.center.x, bbox.center.y - 5),
                (bbox.center.x, bbox.center.y + 5),
                color=angel_color,
                width=2,
                save=False,
            )

        # draw angel near the center
        if angel_text:
            self.draw_text(
                f"{bbox.angel:.2f}°",
                (bbox.center.x + 10, bbox.center.y - 5),
                color=angel_color,
                font_size=8,
                save=False,
            )

        # draw the index of the point in elipse
        if point_index:
            for i, p in enumerate(points):
                draw.ellipse(
                    (p.x - 5, p.y - 5, p.x + 5, p.y + 5), fill=point_index_color
                )
                self.draw_text(
                    f"{i}",
                    (p.x - 2.5, p.y - 5),
                    color=point_text_index_color,
                    font_size=8,
                    save=False,
                )

        # save the image
        if save:
            self.save_drawing_image()

    def draw_alignment_check(
        self,
        alingment_check: "BTBAlignment",
        draw_bboxes=True,
        draw_alingment_info=True,
        draw_alingment_line=True,
        alingment_line_color="lightgray",
        draw_alingment_guidelines=True,
        save=True,
    ):
        """Draw the alignment check between two bounding boxes."""

        bbox1 = alingment_check.bbox1
        bbox2 = alingment_check.bbox2

        if draw_bboxes:
            self.draw_bbox(bbox1, save=False, color="blue")
            self.draw_bbox(bbox2, save=False, color="red")

        # Draw the line between the bboxs centers
        if draw_alingment_line:
            self.draw_line(
                (bbox1.center.x, bbox1.center.y),
                (bbox2.center.x, bbox2.center.y),
                color=alingment_line_color,
                width=2,
                save=False,
            )

        if draw_alingment_info:
            self.draw_text(
                f"dist: {alingment_check.btb_distance:.2f}",
                (bbox2.center.x + 10, bbox2.center.y + 10),
                color="green",
                font_size=8,
                save=False,
            )
            self.draw_text(
                f"perp: {alingment_check.perpendicular_projection:.2f}",
                (bbox2.center.x + 10, bbox2.center.y + 20),
                color="blue",
                font_size=8,
                save=False,
            )
            self.draw_text(
                f"err(n): {alingment_check.alignment_error:.2f}",
                (bbox2.center.x + 10, bbox2.center.y + 30),
                color="red",
                font_size=8,
                save=False,
            )
            self.draw_text(
                f"conf: {alingment_check.alignment_confidence:.2f}",
                (bbox2.center.x + 10, bbox2.center.y + 40),
                color="purple",
                font_size=8,
                save=False,
            )
            self.draw_text(
                f"pos: {alingment_check.alignment_position}",
                (bbox2.center.x + 10, bbox2.center.y + 50),
                color="black",
                font_size=8,
                save=False,
            )

        # Draw visual guidelines for the symmetric tolerance band around the dominant axis
        if draw_alingment_guidelines:
            axis_vec = alingment_check.primary_axis_vector
            perp_vec = alingment_check.perpendicular_axis_vector
            if (
                axis_vec
                and perp_vec
                and alingment_check.perpendicular_band > 0
                and alingment_check.tolerance_ratio > 0
            ):
                axis = np.array(axis_vec, dtype=np.float64)
                perp = np.array(perp_vec, dtype=np.float64)

                axis_norm = np.linalg.norm(axis)
                perp_norm = np.linalg.norm(perp)
                if axis_norm >= 1e-6 and perp_norm >= 1e-6:
                    axis = axis / axis_norm
                    perp = perp / perp_norm

                    tolerance_distance = (
                        alingment_check.perpendicular_band * alingment_check.tolerance_ratio
                    )
                    guideline_half_length = (
                        alingment_check.btb_distance / 2.0
                        + max(
                            bbox1.width,
                            bbox1.height,
                            bbox2.width,
                            bbox2.height,
                        )
                    )

                    center_vec = np.array(
                        [bbox1.center.x, bbox1.center.y], dtype=np.float64
                    )
                    start_main = center_vec - axis * guideline_half_length
                    end_main = center_vec + axis * guideline_half_length

                    upper_start = start_main + perp * tolerance_distance
                    upper_end = end_main + perp * tolerance_distance
                    lower_start = start_main - perp * tolerance_distance
                    lower_end = end_main - perp * tolerance_distance

                    self.draw_line(
                        tuple(map(float, upper_start)),
                        tuple(map(float, upper_end)),
                        color="black",
                        width=1,
                        save=False,
                    )
                    self.draw_line(
                        tuple(map(float, lower_start)),
                        tuple(map(float, lower_end)),
                        color="black",
                        width=1,
                        save=False,
                    )

        # save the image
        if save:
            self.save_drawing_image()

    def draw_annotations(
        self,
        annotations: List["AnnotationObject"],
        save=True,
        color="gray",
        width=2,
        beginning_dot=True,
        beginning_dot_color="green",
    ):
        # Clean overlay style (for /documentDraw demos): a colored box around each match
        # with no angle/point debug decoration, and the matched text labelled above it.
        # Toggle the debug style back on with APITOOLS_DRAW_DEBUG=1.
        if os.getenv("APITOOLS_DRAW_DEBUG", "0") == "1":
            for annotation in annotations:
                self.draw_bbox(annotation.bounding_box, save=False, color=color)
            if save:
                self.save_drawing_image()
            return
        draw = self.memory_drawer
        # Scale the overlay chrome with the image: absolute px sizes tuned for a
        # 600px text-layer raster are invisible on a 2500px phone photo.
        try:
            img_w = self.memory_image.width
        except Exception:
            img_w = 600
        stroke = max(2, round(img_w / 500))
        fsize = max(10, round(img_w / 62))
        for annotation in annotations:
            bb = annotation.bounding_box
            pts = bb.vertices
            xs = [p.x for p in pts]; ys = [p.y for p in pts]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            # tight outline hugging the glyphs — a fat offset box read as
            # "the annotation missed the text" on dense documents
            draw.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline=color, width=stroke)
            txt = (getattr(annotation, 'description', '') or '')[:22]
            if txt.strip():
                try:
                    fnt = ImageFont.truetype("fonts/arial.ttf", fsize)
                except Exception:
                    fnt = ImageFont.load_default()
                try:
                    tw = draw.textlength(txt, font=fnt)
                except Exception:
                    tw = 0.6 * fsize * len(txt)
                # slim tag ATTACHED to the box's top edge (bottom of the tag = top of
                # the box) so it reads as a label, not as a second box on the line above;
                # a token at the very top edge has no room above — attach below instead
                # (an inverted rectangle raises in PIL)
                ly = y0 - (fsize + 2)
                if ly < 0:
                    draw.rectangle([x0 - 1, y1 + 1, x0 - 1 + tw + 6, y1 + fsize + 3], fill=color)
                    draw.text((x0 + 2, y1 + 2), txt, fill="white", font=fnt)
                else:
                    draw.rectangle([x0 - 1, ly, x0 - 1 + tw + 6, y0 - 1], fill=color)
                    draw.text((x0 + 2, ly), txt, fill="white", font=fnt)
        if save:
            self.save_drawing_image()

    def draw_all_annotations(self, save=True):
        # [0] is the page-level full-text annotation — drawing it paints a
        # page-sized box; the token map wants the WORD annotations only
        self.draw_annotations(self.ocr_data.text_annotations[1:], save=save)

    def draw_match_annotations(self, match_annotations, color="green", width=3):
        self.draw_annotations(match_annotations, color=color, width=width)


def ocr_drawings_factory(im_size=(800, 600), color="white"):
    """
    Create a blank image with the specified size and color.
    """

    ocr_object = ocr_object_factory(im_size)
    ocr_drawings = OcrDrawings(ocr_object)
    return ocr_drawings


def test_ocr_drawings_factory():
    ocr_drawer = ocr_drawings_factory(im_size=(800, 600), color="white")
    ocr_drawer.draw_text("Hello World", (100, 100), color="red", font_size=20)
    ocr_drawer.draw_line((50, 50), (200, 200), color="blue", width=5)
    ocr_drawer.show()


def test_ocr_drawings():
    ocr_data = OcrData.from_file_path(f"{ocr_test_files_path()}/file.png")
    ocr_drawing = OcrDrawings(ocr_data)

    print(ocr_data.file_id)
    print(ocr_data.full_text)

    # Draw all the annotations on the image, show the image, and wait for a key press
    ocr_drawing.draw_all_annotations()
    ocr_drawing.show()


if __name__ == "__main__":
    test_ocr_drawings_factory()
    input()
    test_ocr_drawings()
    input("Press Enter to continue...")
