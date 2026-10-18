"""Portable web entry point; respects Cloud Run's injected listening port."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    """Start the existing application without creating a provider client."""
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    uvicorn.run(
        "carbontrace.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        access_log=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
