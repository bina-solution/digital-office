from enum import StrEnum


class AlignmentPosition(StrEnum):
    """
    Enum for the 4 positions relative to a 2d object. (left, right, above, below)
    """
    LEFT = "left"
    RIGHT = "right"
    ABOVE = "above"
    BELOW = "below"