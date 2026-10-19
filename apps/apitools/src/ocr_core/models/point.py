
import math


class Point:
    """A class representing a point in 2D space."""
    def __init__(self, x=None, y=None):
        self.x = x or 0
        self.y = y or 0

    def __repr__(self):
        return f"Point({self.x}, {self.y})"

    def __tuple__(self):
        return self.x, self.y

    
    def next_point(self, distance: float, degree: float) -> 'Point':
        """Generate a new point from the current point by moving a certain distance at a given angle."""
        x = self.x + distance * math.cos(math.radians(degree))
        y = self.y + distance * math.sin(math.radians(degree))
        return Point(x, y)