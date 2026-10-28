import os
import time
from os import PathLike
from secrets import token_hex


def verify_file_type(file_type: str | None, required_types: list[str]) -> str:
    """Validate a declared MIME type against types allowed by the caller."""
    if file_type is None or file_type not in required_types:
        raise ValueError("unsupported file type")
    return file_type


def build_filename(suffix: str) -> str:
    """Return a server-generated filename from a caller-verified suffix."""
    normalized_suffix = suffix.lower()
    if (
        not normalized_suffix.startswith(".")
        or normalized_suffix == "."
        or "/" in normalized_suffix
        or "\\" in normalized_suffix
    ):
        raise ValueError("file suffix must be an extension without path separators")
    return f"{time.time_ns()}-{token_hex(16)}{normalized_suffix}"


def check_file_exists(file_path: str | PathLike[str]) -> bool:
    return os.path.isfile(file_path)


def delete_file(file_path: str | PathLike[str]) -> None:
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass
