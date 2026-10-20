"""Stop a digest run when its unsubscribe signing key differs from the API's."""

import httpx

from core.config import get_settings
from core.unsubscribe import key_fingerprint

_TIMEOUT_SECONDS = 5.0


def check_unsubscribe_key() -> int:
    """Return 1 only when sending would knowingly produce unusable links."""
    local_fingerprint = key_fingerprint()
    if not local_fingerprint:
        print("ERROR: no local unsubscribe signing key is available; digest send blocked.")
        return 1

    settings = get_settings()
    health_url = f"{settings.api_base_url.rstrip('/')}/health"
    try:
        response = httpx.get(health_url, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        # The digest reads the database directly; API availability is not a
        # dependency, so an outage must not turn one missed health check into a
        # missed digest.
        print(
            "WARNING: unsubscribe key could not be checked because the API is "
            f"unreachable ({type(exc).__name__}); digest send will continue."
        )
        return 0

    if response.status_code != 200:
        print(
            "WARNING: unsubscribe key could not be checked because "
            f"{health_url} returned HTTP {response.status_code}; digest send will continue."
        )
        return 0

    try:
        payload = response.json()
    except ValueError:
        print(
            "WARNING: unsubscribe key could not be checked because /health returned "
            "invalid JSON; digest send will continue."
        )
        return 0

    if not isinstance(payload, dict) or "unsubscribe_key" not in payload:
        # During the first deploy the API may not expose the new field yet.
        # Sending can continue because the digest itself does not use the API.
        print(
            "WARNING: unsubscribe key could not be checked because /health has no "
            "unsubscribe_key; digest send will continue."
        )
        return 0

    api_fingerprint = payload["unsubscribe_key"]
    if not isinstance(api_fingerprint, str):
        print(
            "WARNING: unsubscribe key could not be checked because /health returned an "
            "invalid unsubscribe_key; digest send will continue."
        )
        return 0

    if local_fingerprint != api_fingerprint:
        # Forty production users received links that returned 200 but changed
        # nothing. Missing one digest is safer than repeating that silent lie.
        print(
            "ERROR: unsubscribe signing key mismatch: "
            f"local={local_fingerprint} api={api_fingerprint}; digest send blocked."
        )
        return 1

    print(f"unsubscribe signing key matches API ({local_fingerprint}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_unsubscribe_key())
