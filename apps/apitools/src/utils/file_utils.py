

def get_mime_type_from_bytes(file_bytes):
# Check first few bytes for common signatures
    if file_bytes.startswith(b'\xFF\xD8\xFF'):
        return 'image/jpeg'            
    elif file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    elif file_bytes.startswith(b'GIF87a') or file_bytes.startswith(b'GIF89a'):
        return 'image/gif'
    elif file_bytes.startswith(b'%PDF'):
        return 'application/pdf'
    elif file_bytes.startswith(b'PK\x03\x04'):
        return 'application/zip'  # Could also be docx, xlsx, etc.
    elif file_bytes.startswith(b'\x00\x00\x00\x18ftypmp4') or file_bytes.startswith(b'\x00\x00\x00\x20ftypiso'):
        return 'video/mp4'  
    
    return 'application/octet-stream'  # Default for unknown