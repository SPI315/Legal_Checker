from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, byref, c_char, c_void_p, wintypes


class DATA_BLOB(Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]


class DpapiCipher:
    def __init__(self, entropy: bytes = b"") -> None:
        self._entropy = entropy
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def encrypt(self, data: bytes) -> bytes:
        return self._protect(data)

    def decrypt(self, data: bytes) -> bytes:
        return self._unprotect(data)

    def _protect(self, data: bytes) -> bytes:
        in_blob = self._to_blob(data)
        entropy_blob = self._to_blob(self._entropy) if self._entropy else None
        out_blob = DATA_BLOB()

        if not self._crypt32.CryptProtectData(
            byref(in_blob),
            "LegalChecker",
            byref(entropy_blob) if entropy_blob else None,
            None,
            None,
            0,
            byref(out_blob),
        ):
            raise OSError("Failed to encrypt data with Windows DPAPI")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def _unprotect(self, data: bytes) -> bytes:
        in_blob = self._to_blob(data)
        entropy_blob = self._to_blob(self._entropy) if self._entropy else None
        out_blob = DATA_BLOB()
        description = c_void_p()

        if not self._crypt32.CryptUnprotectData(
            byref(in_blob),
            byref(description),
            byref(entropy_blob) if entropy_blob else None,
            None,
            None,
            0,
            byref(out_blob),
        ):
            raise OSError("Failed to decrypt data with Windows DPAPI")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def _to_blob(self, data: bytes) -> DATA_BLOB:
        buffer = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buffer, POINTER(c_char)))
