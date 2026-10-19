import hashlib


def md5_hash_string(bytes_content: bytes):
    """Generate MD5 hash for a string."""
    return hashlib.md5(bytes_content).hexdigest()


def get_file_md5_hash(file_path):
    """Generate MD5 hash for a file."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    return md5_hash_string(file_bytes)