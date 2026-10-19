import os

STORAGE_PATH = ".storage"
TEST_FILES_PATH = ".test_files"


def test_files_path():
    os.makedirs(TEST_FILES_PATH, exist_ok=True)
    return TEST_FILES_PATH


def ocr_test_files_path():
    path = f"{test_files_path()}/ocr_test_files"
    os.makedirs(path, exist_ok=True)
    return path


def ocr_test_fails_path():
    path = f"{test_files_path()}/ocr_test_fails"
    os.makedirs(path, exist_ok=True)
    return path


def alingment_test_files_path():
    path = f"{test_files_path()}/alingment_tests"
    os.makedirs(path, exist_ok=True)
    return path


def pdf_test_files_path():
    path = f"{test_files_path()}/pdf_test_files"
    os.makedirs(path, exist_ok=True)
    return path


def pdfs_path():
    path = f"{storage_path()}/pdfs"
    os.makedirs(path, exist_ok=True)
    return path


def storage_path():
    os.makedirs(STORAGE_PATH, exist_ok=True)
    return STORAGE_PATH


def factory_images_path():
    path = f"{storage_path()}/factory_images"
    os.makedirs(path, exist_ok=True)
    return path


def ocr_drawings_path():
    path = f"{storage_path()}/ocr_drawings"
    os.makedirs(path, exist_ok=True)
    return path


def ocr_pdf_images_path():
    path = f"{storage_path()}/ocr_pdf_images"
    os.makedirs(path, exist_ok=True)
    return path


def ocr_cache_path():
    path = f"{storage_path()}/ocr_cache"
    os.makedirs(path, exist_ok=True)
    return path


def files_path():
    path = f"{storage_path()}/files"
    os.makedirs(path, exist_ok=True)
    return path

def failed_drive_files_path():
    path = f"{test_files_path()}/failed-drive"
    os.makedirs(path, exist_ok=True)
    return path



def file_path(file_name):
    return f"{files_path()}/{file_name}"


def save_file(file_name, file_content):
    path = file_path(file_name)
    with open(path, "wb") as f:
        f.write(file_content)

    return path


def serve_file(file_name) -> bytes:
    with open(file_path(file_name), "rb") as f:
        return f.read()
