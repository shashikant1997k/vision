"""Password hashing (PBKDF2-HMAC-SHA256, stdlib only) and a password policy.

Stored format:  pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
No plaintext is ever stored. PBKDF2 avoids native build deps and is portable
across macOS/Windows; bcrypt/argon2 can be swapped in later behind this module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGO = "pbkdf2_sha256"
ITERATIONS = 200_000


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGO}${iterations}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt_b64), int(iters))
        return hmac.compare_digest(dk, _unb64(hash_b64))
    except (ValueError, TypeError):
        return False


class PasswordPolicy:
    """Minimal configurable policy. Tighten per customer SOP during validation."""

    def __init__(
        self, min_length: int = 8, require_digit: bool = True, require_letter: bool = True
    ) -> None:
        self.min_length = min_length
        self.require_digit = require_digit
        self.require_letter = require_letter

    def validate(self, password: str) -> None:
        if len(password) < self.min_length:
            raise ValueError(f"password must be at least {self.min_length} characters")
        if self.require_digit and not any(c.isdigit() for c in password):
            raise ValueError("password must contain a digit")
        if self.require_letter and not any(c.isalpha() for c in password):
            raise ValueError("password must contain a letter")
