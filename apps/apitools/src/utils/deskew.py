import cv2
import numpy as np

from src.utils.rotation_calc import calculate_rotated_size
from src.utils.storage import pdf_test_files_path

DEBUGGING_ROTATED_IMAGE_PATH = 'tests/debugging_rotate_image.jpg'
DEBUGGING_DESKEWED_IMAGE_PATH = 'tests/debugging_deskewed_image.jpg'


def deskew(im, max_skew=10):
    print(im.shape)
    o_height, o_width, _ = im.shape
    original_im = im.copy()

    # Resize image to a width of 500, maintaining aspect ratio, unless the image is smaller
    if o_width > 500:
        width = 500
        ratio = width / o_width
        height = int(o_height * ratio)
        im = cv2.resize(original_im, (width, height))
    else:
        width = o_width
        height = o_height

    print("New image size: ", im.shape)

    # Create a grayscale image and denoise it
    im_gs = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    im_gs = cv2.fastNlMeansDenoising(im_gs, h=3)

    # Create an inverted B&W copy using Otsu (automatic) thresholding
    # im_bw = cv2.threshold(im_gs, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    im_bw = cv2.adaptiveThreshold(im_gs, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 2)

    # Detect lines in this image. Parameters here mostly arrived at by trial and error.
    lines = cv2.HoughLinesP(
        im_bw, 1,
        np.pi / 180, 200,
        minLineLength=width / 12,
        maxLineGap=width / 150
    )
    print("Lines: ", lines)

    if lines is None:
        lines = []

    # Collect the angles of these lines (in radians)
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angles.append(np.arctan2(y2 - y1, x2 - x1))

    # If the OVERWHELMING majority of lines are vertical, this is probably a sideways
    # scan. A bare >50% majority mis-fires on portrait pages dominated by table rules
    # and stamps (delivery notes) and rotated them 90 deg, destroying OCR downstream.
    n_vert = np.sum([abs(angle) > np.pi / 4 for angle in angles])
    landscape = len(angles) >= 10 and n_vert > 0.8 * len(angles)
    print("Landscape: ", landscape)

    # Filter the angles to remove outliers based on max_skew
    if landscape:
        angles = [
            angle
            for angle in angles
            if np.deg2rad(90 - max_skew) < abs(angle) < np.deg2rad(90 + max_skew)
        ]
    else:
        angles = [angle for angle in angles if abs(angle) < np.deg2rad(max_skew)]

    print("Angles: ", angles)

    if len(angles) < 5:
        # Insufficient data to deskew
        return original_im

    # Average the angles to a degree offset
    angle_deg = np.rad2deg(np.median(angles))
    print("Angle: ", angle_deg)
    print("Landscape: ", landscape)
    print("OWidth: ", o_width, "OHeight: ", o_height)
    new_width, new_height = calculate_rotated_size(o_width, o_height, angle_deg)

    # If this is landscape image, rotate the entire canvas appropriately
    if landscape:
        if angle_deg < 0:
            original_im = cv2.rotate(original_im, cv2.ROTATE_90_CLOCKWISE)
            angle_deg += 90
        elif angle_deg > 0:
            original_im = cv2.rotate(original_im, cv2.ROTATE_90_COUNTERCLOCKWISE)
            angle_deg -= 90

    print("New Width:", new_width)
    print("New Height:", new_height)

    # Rotate the image by the residual offset
    M = cv2.getRotationMatrix2D((new_width / 2, new_height / 2), angle_deg, 1)
    # cv2.imwrite(DEBUGGING_ROTATED_IMAGE_PATH, original_im)

    original_im = cv2.warpAffine(original_im, M, (new_width, new_height), borderMode=cv2.BORDER_REPLICATE)
    # cv2.imwrite(DEBUGGING_DESKEWED_IMAGE_PATH, original_im)

    return original_im


# Current critical detection code, 
# Currently not in used, before furthere development check difrences from deskew
def deskew_01(im, max_skew=10):
    """
    Deskews an image by detecting and analyzing both thin (table) and thick (text) lines.
    Gives more weight to text lines in determining orientation.

    Args:
        im: Input image (BGR format)
        max_skew: Maximum skew angle to correct (degrees)

    Returns:
        Deskewed image
    """
    print(im.shape)
    o_height, o_width, _ = im.shape
    original_im = im.copy()

    # Resize image to a width of 500, maintaining aspect ratio, unless the image is smaller
    if o_width > 500:
        width = 500
        ratio = width / o_width
        height = int(o_height * ratio)
        im = cv2.resize(original_im, (width, height))
    else:
        width = o_width
        height = o_height

    print("New image size: ", im.shape)

    # Create a grayscale image and denoise it
    im_gs = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    im_gs = cv2.fastNlMeansDenoising(im_gs, h=3)

    # Create an inverted B&W copy using adaptive thresholding
    im_bw = cv2.adaptiveThreshold(im_gs, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY_INV, 11, 2)

    # First pass: Detect thin lines (likely table lines)
    thin_lines = cv2.HoughLinesP(
        im_bw, 1, np.pi / 180, 200,
        minLineLength=width / 12,
        maxLineGap=width / 150
    )

    # Prepare image for thick line detection
    kernel_vertical = np.ones((3, 1), np.uint8)
    kernel_horizontal = np.ones((1, 3), np.uint8)

    # Erode and dilate to enhance text lines
    eroded = cv2.erode(im_bw, kernel_vertical, iterations=1)
    eroded = cv2.erode(eroded, kernel_horizontal, iterations=1)
    dilated = cv2.dilate(eroded, kernel_vertical, iterations=2)
    dilated = cv2.dilate(dilated, kernel_horizontal, iterations=2)

    # Second pass: Detect thick lines (likely text lines)
    thick_lines = cv2.HoughLinesP(
        dilated, 1, np.pi / 180, 150,
        minLineLength=width / 20,
        maxLineGap=width / 50
    )

    # Process detected lines and collect angles
    angles = []

    # Process thin lines (weight = 1)
    if thin_lines is not None:
        for line in thin_lines:
            x1, y1, x2, y2 = line[0]
            # Filter out very short lines
            if np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) > width / 20:
                angle = np.arctan2(y2 - y1, x2 - x1)
                angles.extend([angle])  # Weight of 1 for thin lines

    # Process thick lines (weight = 3)
    if thick_lines is not None:
        for line in thick_lines:
            x1, y1, x2, y2 = line[0]
            # Filter out very short lines
            if np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) > width / 30:
                angle = np.arctan2(y2 - y1, x2 - x1)
                angles.extend([angle] * 3)  # Weight of 3 for thick lines

    print("Total angles detected:", len(angles))

    if len(angles) < 5:
        print("Insufficient lines detected")
        return original_im

    # Count vertical and horizontal components
    vertical_count = np.sum([abs(angle) > np.pi / 4 for angle in angles])
    horizontal_count = len(angles) - vertical_count

    # More stringent landscape detection
    landscape = (vertical_count > horizontal_count * 1.5 and
                 vertical_count > len(angles) * 0.6)

    print("Vertical count:", vertical_count)
    print("Horizontal count:", horizontal_count)
    print("Landscape:", landscape)

    # Filter angles based on orientation
    if landscape:
        angles = [
            angle
            for angle in angles
            if np.deg2rad(90 - max_skew) < abs(angle) < np.deg2rad(90 + max_skew)
        ]
    else:
        angles = [angle for angle in angles if abs(angle) < np.deg2rad(max_skew)]

    if len(angles) < 5:
        print("Insufficient angles after filtering")
        return original_im

    # Calculate the median angle
    angle_deg = np.rad2deg(np.median(angles))
    print("Final rotation angle:", angle_deg)

    # Calculate new dimensions
    new_width, new_height = calculate_rotated_size(o_width, o_height, angle_deg)

    # Handle landscape rotation
    if landscape:
        print("Applying landscape rotation")
        if angle_deg < 0:
            original_im = cv2.rotate(original_im, cv2.ROTATE_90_CLOCKWISE)
            angle_deg += 90
        elif angle_deg > 0:
            original_im = cv2.rotate(original_im, cv2.ROTATE_90_COUNTERCLOCKWISE)
            angle_deg -= 90

    print("New dimensions:", new_width, new_height)
    print("Final adjustment angle:", angle_deg)

    # Apply final rotation
    M = cv2.getRotationMatrix2D((new_width / 2, new_height / 2), angle_deg, 1)
    original_im = cv2.warpAffine(
        original_im, M, (new_width, new_height),
        borderMode=cv2.BORDER_REPLICATE
    )

    return original_im


if __name__ == '__main__':
    from src.pdf_core.pdf_to_jpg import pdf_to_jpg_from_path

    filename = f"{pdf_test_files_path()}/centerlized_invoce-1.jpg"
    jpg_filename = f"{pdf_test_files_path()}/under_line_test.jpg"
    output_file = f"{pdf_test_files_path()}/deskewed1.jpg"
    # jpg_bytes = pdf_to_jpg_from_path(filename)
    # with open(jpg_filename, "wb") as f:
    #     f.write(jpg_bytes.read())

    im = cv2.imread(filename)
    deskewed_im = deskew(im)
    cv2.imwrite(output_file, deskewed_im)
    print("Done")
