import numpy as np


def calculate_rotated_size(w, h, theta):
    """Calculates the size of the bounding box after rotation."""
    angle_rad = np.deg2rad(theta)

    # Calculate corner points of the original image
    corners = np.array([
        [0, 0],
        [w, 0],
        [w, h],
        [0, h]
    ])

    # Rotation matrix
    rotation_matrix = np.array([
        [np.cos(angle_rad), -np.sin(angle_rad)],
        [np.sin(angle_rad), np.cos(angle_rad)]
    ])

    # Rotate the corner points
    rotated_corners = np.dot(corners, rotation_matrix.T)

    # Find the new bounding box
    x_min = np.min(rotated_corners[:, 0])
    x_max = np.max(rotated_corners[:, 0])
    y_min = np.min(rotated_corners[:, 1])
    y_max = np.max(rotated_corners[:, 1])

    new_width = int(x_max - x_min)
    new_height = int(y_max - y_min)

    return new_width, new_height


# Example usage
original_width = 100
original_height = 50
rotation_angle = 90


# new_width, new_height = calculate_rotated_size(original_width, original_height, rotation_angle)
# print("New Width:", new_width)
# print("New Height:", new_height)