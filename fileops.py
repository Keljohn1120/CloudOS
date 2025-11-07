import os
import tempfile
import sys
import subprocess

def set_windows_permissions(path):
    if sys.platform == 'win32':
        try:
            username = os.environ.get('USERNAME', None)
            if username:
                # Use icacls to grant full permissions to the current user
                result = subprocess.run(['icacls', path, '/grant', f'{username}:(F)'], 
                                     capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"icacls error: {result.stderr}")
                    # Try alternative approach with takeown
                    takeown = subprocess.run(['takeown', '/F', path], 
                                          capture_output=True, text=True)
                    print(f"takeown result: {takeown.stderr if takeown.returncode != 0 else 'success'}")
        except Exception as e:
            print(f"Permission setting error for {path}: {str(e)}")

def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
        # Ensure directory is readable and writable
        try:
            os.chmod(parent, 0o755)
        except Exception:
            pass  # Best effort

def safe_write(path: str, data: str | bytes, encoding='utf-8'):
    ensure_parent_dir(path)
    
    # Ensure the directory is writable
    dirpath = os.path.dirname(path) or '.'
    if not os.access(dirpath, os.W_OK):
        set_windows_permissions(dirpath)
        if not os.access(dirpath, os.W_OK):
            raise PermissionError(f"No write permission for directory: {dirpath}")
    
    # Create or fix permissions on the target file
    if not os.path.exists(path):
        try:
            # Create empty file
            with open(path, 'a') as f:
                pass
        except Exception as e:
            raise PermissionError(f"Cannot create file {path}: {e}")
    
    # Set proper permissions for the file
    set_windows_permissions(path)
    if not os.access(path, os.W_OK):
        raise PermissionError(f"Cannot set write permissions on {path}")
    
    # Write to temp file in same directory then atomic replace
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix='.tmp-')
        try:
            mode = 'wb' if isinstance(data, (bytes, bytearray)) else 'w'
            with os.fdopen(fd, mode, encoding=None if mode == 'wb' else encoding) as f:
                f.write(data)
            # Set permissions on temp file before replacing
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, path)
        except Exception as e:
            raise IOError(f"Error writing to {path}: {e}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    except Exception as e:
        raise IOError(f"Cannot create temporary file in {dirpath}: {e}")

def safe_read(path: str, encoding='utf-8') -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
        
    try:
        # Check and fix directory permissions
        dirpath = os.path.dirname(path) or '.'
        if not os.access(dirpath, os.R_OK):
            set_windows_permissions(dirpath)
            if not os.access(dirpath, os.R_OK):
                raise PermissionError(f"Cannot access directory {dirpath}")
        
        # Check and fix file permissions
        if not os.access(path, os.R_OK):
            set_windows_permissions(path)
            if not os.access(path, os.R_OK):
                raise PermissionError(f"Cannot access file {path}")
        
        # Try to read the file
        try:
            with open(path, 'r', encoding=encoding) as f:
                return f.read()
        except PermissionError:
            # One last attempt to fix permissions
            set_windows_permissions(path)
            with open(path, 'r', encoding=encoding) as f:
                return f.read()
    except PermissionError as e:
        raise PermissionError(f"Permission denied reading {path}. Please check file permissions: {e}")
    except Exception as e:
        raise Exception(f"Error reading {path}: {e}")