"""Windows user-scoped protection for small application secrets (for example SMTP tokens)."""
import ctypes
import os
from ctypes import wintypes


class SecureStoreError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data, decrypt=False):
    if os.name != "nt":
        raise SecureStoreError("Credential protection is available only on Windows.")
    raw = bytes(data)
    source_buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = _Blob(len(raw), source_buf)
    output = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                   ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise SecureStoreError("Windows could not protect the email credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output.pbData)


def protect_secret(secret):
    """Return an opaque DPAPI-protected string bound to the current Windows user."""
    return _protect(secret.encode("utf-8")).hex()


def unprotect_secret(value):
    """Decrypt a value previously returned by protect_secret."""
    try:
        return _protect(bytes.fromhex(value), decrypt=True).decode("utf-8")
    except SecureStoreError:
        raise
    except Exception as exc:
        raise SecureStoreError("The saved email credential could not be decrypted.") from exc
