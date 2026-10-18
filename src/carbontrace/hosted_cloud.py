"""Lazy Google Cloud adapters; importing this module performs no cloud operations."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from urllib.parse import quote

import google.auth
from google import genai
from google.auth.transport.requests import AuthorizedSession

from carbontrace.hosted import Conflict, HostedError, HostedLedger, HostedSettings
from carbontrace.live_smoke import GeminiProvider, Provider, client_http_options


def settings() -> HostedSettings:
    try:
        return HostedSettings(
            os.environ["CARBONTRACE_QUOTE_KEY"].encode(),
            datetime.fromisoformat(os.environ["CARBONTRACE_POOL_EXPIRES"]),
        )
    except (KeyError, ValueError) as exc:
        raise HostedError("Hosted execution is not configured") from exc


class CloudObjects:
    """Private GCS XML objects, using documented generation-match preconditions."""

    def __init__(self, bucket: str):
        self.bucket = bucket
        self.session: AuthorizedSession | None = None

    def request(self, method: str, name: str, **kwargs: Any) -> Any:
        if self.session is None:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.session = AuthorizedSession(credentials)  # type: ignore[no-untyped-call]
        try:
            return self.session.request(  # type: ignore[no-untyped-call]
                method,
                f"https://storage.googleapis.com/{self.bucket}/{quote(name, safe='/')}",
                timeout=15,
                allow_redirects=False,
                **kwargs,
            )
        except Exception as exc:
            raise HostedError(
                "Private run storage is unavailable; execution is stopped"
            ) from exc

    def read(self, name: str) -> tuple[dict[str, Any], int] | None:
        response = self.request("GET", name)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise HostedError("Private run storage could not be read")
        try:
            value = response.json()
            generation = int(response.headers["x-goog-generation"])
            if not isinstance(value, dict) or generation < 1:
                raise ValueError
            return value, generation
        except (ValueError, KeyError) as exc:
            raise HostedError("Private run storage returned invalid data") from exc

    def write(
        self, name: str, value: dict[str, Any], generation: int | None = None
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if generation is not None:
            headers["x-goog-if-generation-match"] = str(generation)
        response = self.request(
            "PUT", name, data=json.dumps(value).encode(), headers=headers
        )
        if response.status_code == 412:
            raise Conflict("Storage generation changed")
        if response.status_code not in (200, 201):
            raise HostedError("Private run storage could not be written")


def cloud_ledger() -> HostedLedger:
    bucket = os.environ.get("CARBONTRACE_LEDGER_BUCKET")
    if not bucket:
        raise HostedError("Public allowance storage is not configured")
    return HostedLedger(CloudObjects(bucket))


@asynccontextmanager
async def cloud_provider() -> AsyncIterator[Provider]:
    async with genai.Client(
        enterprise=True,
        project="carbontrace-511814",
        location="global",
        http_options=client_http_options(),
    ).aio as client:
        yield GeminiProvider(client)
