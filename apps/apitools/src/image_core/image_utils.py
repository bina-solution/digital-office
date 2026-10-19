import cv2


def resize_to_width(image, target_width):
    """
    Resizes an image to a specified width while maintaining the aspect ratio.

    Args:
        image: The input image (numpy array).
        target_width: The desired width of the resized image.

    Returns:
        The resized image (numpy array).
    """
    original_height, original_width = image.shape[:2]
    aspect_ratio = original_width / original_height

    new_width = target_width
    new_height = int(new_width / aspect_ratio)  # Maintain aspect ratio

    resized_image = cv2.resize(image, (new_width, new_height),
                               interpolation=cv2.INTER_AREA)  # High-quality interpolation for downscaling

    return resized_image
