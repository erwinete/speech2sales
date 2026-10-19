"""Хранилище артефактов. Skeleton: локальный FS; прод: MinIO/S3 (doc 01 §4.3) — тот же интерфейс."""

import hashlib
from pathlib import Path
from typing import Protocol


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> str: ...
    def exists(self, key: str) -> bool: ...
    def open(self, key: str) -> bytes: ...
    def path(self, key: str) -> Path:
        """Локальный путь, если хранилище файловое; иначе — выгрузка во tmp."""

    def open_stream(self, key: str, chunk: int = 1 << 20) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise StorageError(f"ключ вне корня хранилища: {key!r}")
        return p

    def save(self, key: str, data: bytes) -> str:
        p = self._resolve(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def open(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def path(self, key: str) -> Path:
        return self._resolve(key)


def make_storage(settings: object) -> LocalStorage:
    return LocalStorage(settings.storage_dir)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
