
class OCRQueryException(Exception):
    pass


class MatchNotFound(OCRQueryException):
    pass


class AlignmentNotFound(OCRQueryException):
    pass
