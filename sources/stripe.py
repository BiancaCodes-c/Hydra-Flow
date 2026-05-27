"""Stripe source: fetch objects from the Stripe API and return a DataFrame.

This implementation keeps imports lazy and accepts either a pre-built
`stripe` client (module) or an API key string. It returns a Polars
DataFrame and supports simple pagination for incremental loading.
"""

from __future__ import annotations

from typing import Any
import importlib

from .base import SourceBase, SourceValidationError


def _polars() -> Any:
    try:
        return importlib.import_module("polars")
    except ModuleNotFoundError as exc:
        raise SourceValidationError("Stripe source requires the 'polars' package.") from exc


class StripeSource(SourceBase):
    def __init__(self, resource: str = "charges", client: Any | None = None, api_key: str | None = None, name: str | None = None) -> None:
        super().__init__(name=name)
        self.resource = resource
        self.client = client
        self.api_key = api_key
        self._owns_client = False

    def validate(self) -> None:
        if not isinstance(self.resource, str) or not self.resource.strip():
            raise SourceValidationError("Stripe resource name required.")

    def connect(self) -> Any:
        if self.client is not None:
            return self.client

        try:
            stripe = importlib.import_module("stripe")
        except ModuleNotFoundError as exc:
            raise SourceValidationError("Stripe source requires the 'stripe' package or a client object.") from exc

        if self.api_key:
            stripe.api_key = self.api_key

        self.client = stripe
        self._owns_client = True
        return stripe

    def close(self) -> None:
        # stripe module does not require explicit close; keep for API parity
        self._owns_client = False

    def extract(self, since: int | None = None, limit: int = 100, **kwargs: Any) -> Any:
        client = self.client or self.connect()
        res = getattr(client, self.resource, None)
        if res is None:
            # try pluralized attribute (e.g. `charges` vs `Charge`)
            res = getattr(client, self.resource.capitalize(), None)
        if res is None:
            raise SourceValidationError(f"Stripe client has no resource '{self.resource}'")

        params = {"limit": limit, **({"created": {"gte": since}} if since else {}), **kwargs}

        items = []
        resp = res.list(**params)
        items.extend([getattr(i, "to_dict", lambda: dict(i))() for i in resp.data])

        # simple pagination
        while getattr(resp, "has_more", False):
            params["starting_after"] = resp.data[-1].id
            resp = res.list(**params)
            items.extend([getattr(i, "to_dict", lambda: dict(i))() for i in resp.data])

        return _polars().DataFrame(items)


def extract(since: int | None = None, client: Any | None = None, api_key: str | None = None, resource: str = "charges") -> Any:
    return StripeSource(resource=resource, client=client, api_key=api_key).extract(since=since)
