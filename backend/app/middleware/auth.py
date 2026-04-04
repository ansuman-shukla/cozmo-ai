"""Authentication dependency stubs."""

from fastapi import Header, HTTPException, status


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject requests when an API key is required but missing."""

    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

