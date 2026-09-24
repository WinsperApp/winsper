from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from .storage import atomic_write_bytes


class SecureStore(Protocol):
    def load(self) -> bytes | None: ...

    def save(self, data: bytes) -> None: ...

    def delete(self) -> None: ...


class SecureStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class DpapiFileStore:
    """User-bound encrypted storage backed by Windows DPAPI."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(
        self,
        path: Path,
        *,
        entropy: bytes = b"Winsper protected data v1",
        description: str = "Winsper protected data",
        data_label: str = "protected data",
    ) -> None:
        self.path = path
        self.entropy = entropy
        self.description = description
        self.data_label = data_label

    def load(self) -> bytes | None:
        if not self.path.exists():
            return None
        try:
            encrypted = self.path.read_bytes()
        except OSError as exc:
            raise SecureStoreError(f"Winsper could not read {self.data_label}.") from exc
        if not encrypted:
            raise SecureStoreError(f"{self.data_label.capitalize()} is empty.")
        return self._unprotect(encrypted)

    def save(self, data: bytes) -> None:
        if not isinstance(data, bytes) or not data:
            raise ValueError("Protected data must be non-empty bytes.")
        protected = self._protect(data)
        try:
            atomic_write_bytes(self.path, protected)
        except OSError as exc:
            raise SecureStoreError(f"Winsper could not save {self.data_label}.") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecureStoreError(f"Winsper could not remove {self.data_label}.") from exc

    def _protect(self, data: bytes) -> bytes:
        self._require_windows()
        source, source_buffer = _blob(data)
        entropy, entropy_buffer = _blob(self.entropy)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        result = crypt32.CryptProtectData(
            ctypes.byref(source),
            self.description,
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not result:
            raise SecureStoreError(f"Windows could not protect {self.data_label}.") from ctypes.WinError()
        del source_buffer, entropy_buffer
        return _take_blob(output)

    def _unprotect(self, data: bytes) -> bytes:
        self._require_windows()
        source, source_buffer = _blob(data)
        entropy, entropy_buffer = _blob(self.entropy)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        result = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not result:
            raise SecureStoreError(
                f"{self.data_label.capitalize()} could not be opened for this Windows user."
            ) from ctypes.WinError()
        del source_buffer, entropy_buffer
        return _take_blob(output)

    def _require_windows(self) -> None:
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            raise SecureStoreError(f"Windows DPAPI is required for {self.data_label}.")


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def _take_blob(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)
