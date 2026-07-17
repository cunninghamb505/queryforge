"""Encrypts saved connection URLs at rest so credentials aren't stored as plaintext in the metadata DB.

This protects against casual disclosure (e.g. someone opening data/app_metadata.db in a text
editor) but the key lives on the same disk as the ciphertext, so it is not a substitute for a
real secrets manager if this app is ever exposed beyond a single local user.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet

DATA_DIR = Path(os.environ.get("SQL_OPTIMIZER_DATA_DIR", "data"))
KEY_PATH = DATA_DIR / "secret.key"


def _load_or_create_key() -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_str(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_str(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
