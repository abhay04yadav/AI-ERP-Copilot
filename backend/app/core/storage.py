from abc import ABC, abstractmethod

from app.models.ingestion import RawFile


class StorageBackend(ABC):
    """Single swap point for where original uploaded files live. storage_uri
    is the portable pointer every backend must set; only the bytea backend
    also uses RawFile.content. Swapping to S3 later means writing a new
    backend that sets storage_uri to an s3:// URI and leaves content null —
    no change to callers or to RawFile's schema."""

    @abstractmethod
    def save(self, raw_file: RawFile, content: bytes) -> None:
        """Mutates raw_file in place (sets storage_uri, and for in-DB backends
        content). raw_file must already have its id flushed."""

    @abstractmethod
    def load(self, raw_file: RawFile) -> bytes:
        """Returns the original file bytes for a previously-saved RawFile."""


class PostgresByteaStorageBackend(StorageBackend):
    def save(self, raw_file: RawFile, content: bytes) -> None:
        raw_file.content = content
        raw_file.storage_uri = f"pg-bytea://raw_files/{raw_file.id}"

    def load(self, raw_file: RawFile) -> bytes:
        if raw_file.content is None:
            raise ValueError(
                f"RawFile {raw_file.id} has no bytea content (storage_uri={raw_file.storage_uri})"
            )
        return raw_file.content


def get_storage_backend() -> StorageBackend:
    return PostgresByteaStorageBackend()
