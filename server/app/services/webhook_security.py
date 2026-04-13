import hashlib
import hmac


def compute_github_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_github_signature(secret: str, body: bytes, provided_signature: str | None) -> bool:
    if not secret or not provided_signature:
        return False

    expected_signature = compute_github_signature(secret, body)
    return hmac.compare_digest(expected_signature, provided_signature)
