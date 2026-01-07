import hashlib
from typing import Union


def sha256_hex(data: Union[str, bytes]) -> str:
    """
    Compute a SHA-256 hash and return it as a hex string.

    Usage:
    - Evidence bundle integrity verification
    - Prompt / response hashing (future LLM use)
    - Reproducibility guarantees

    IMPORTANT:
    - Always hash the *uncompressed* payload
    - Sort keys before hashing JSON to ensure stability
    """

    if isinstance(data, str):
        data = data.encode("utf-8")

    return hashlib.sha256(data).hexdigest()
