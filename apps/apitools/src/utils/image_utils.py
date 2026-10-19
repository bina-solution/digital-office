from typing import List

from PIL import ImageColor
import os

from src.ocr_core.models.annotation_object import AnnotationObject


def add_file_name(filepath, addname):
    # Split the file path into the root and extension
    root, ext = os.path.splitext(filepath)
    # Return the modified file path
    return f"{root}_{addname}{ext}"


def draw_annotations(image_path, annotations: List[AnnotationObject], output_path=None, color="red"):
    if output_path is None:
        output_path = add_file_name(image_path, "draw")
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    for annotation in annotations:
        vertices = annotation.vertices
        draw.polygon(
            [(vertex["x"], vertex["y"]) for vertex in vertices],
            outline=color,
            width=3
        )
    image.save(output_path)


from typing import List


def darker_color(color, factor=0.9):
    """Return a darker version of the given color by reducing the brightness."""

    # Convert hex color to RGB
    # if color is  string
    if isinstance(color, str):
        color = ImageColor.getrgb(color)

    r, g, b = color
    r,g,b = r or 1, g or 1, b or 1
    print(r, g, b)

    # Darken the color by reducing each channel's intensity
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    print(r, g, b)
    return (r, g, b)


def draw_annotations(image_path, annotations: List['AnnotationObject'], output_path=None, color="red"):
    if output_path is None:
        output_path = add_file_name(image_path, "draw")

    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)

    for annotation in annotations:
        vertices = annotation.vertices

        # Add dot at the first vertex (beginning of the bbox)
        first_vertex = vertices[0]
        dot_radius = 5
        draw.ellipse(
            [(first_vertex["x"] - dot_radius, first_vertex["y"] - dot_radius),
             (first_vertex["x"] + dot_radius, first_vertex["y"] + dot_radius)],
            fill=color, outline=color
        )

        # Draw the polygon with darker lines to show direction
        for i in range(len(vertices)):
            start = (vertices[i]["x"], vertices[i]["y"])
            end = (vertices[(i + 1) % len(vertices)]["x"], vertices[(i + 1) % len(vertices)]["y"])

            # Darken the color for each line
            print(color)
            color = darker_color(color, factor=2)

            # Draw the line from current vertex to the next
            draw.line([start, end], fill=color, width=3)

    image.save(output_path)


from PIL import Image, ImageDraw
from typing import List


# Helper function to darken a color
def darken_color(color: str, factor: float) -> str:
    r, g, b = ImageColor.getrgb(color)
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f"rgb({r},{g},{b})"


def draw_annotations(image_path, annotations: List[AnnotationObject], output_path=None, color="red"):
    if output_path is None:
        output_path = add_file_name(image_path, "draw")

    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)

    # Define initial light color
    base_color = "lightgray"
    darken_factors = [1, 0.8, 0.6, 0.4]  # Darken color in 4 steps

    for annotation in annotations:
        vertices = annotation.vertices

        # Draw a dot at the first vertex
        first_vertex = vertices[0]
        draw.ellipse(
            (first_vertex["x"] - 3, first_vertex["y"] - 3, first_vertex["x"] + 3, first_vertex["y"] + 3),
            fill="red"
        )

        # Draw the bounding box with progressively darker colors
        for i in range(len(vertices)):
            start_vertex = vertices[i]
            end_vertex = vertices[(i + 1) % len(vertices)]  # Loop back to the first vertex at the end
            color = darken_color(base_color, darken_factors[i % 4])  # Darken the color based on the line index

            draw.line(
                [start_vertex["x"], start_vertex["y"], end_vertex["x"], end_vertex["y"]],
                fill=color,
                width=3
            )

    image.save(output_path)

# Example usage
# Assuming AnnotationObject has a "vertices" attribute with [{"x": value, "y": value}, ...]
