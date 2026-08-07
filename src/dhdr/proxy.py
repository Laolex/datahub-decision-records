"""The capture proxy.

It sits between an agent and its context source, forwards reads unchanged, and
stamps each one with the revision in force at read time. The agent is not
modified and does not know the proxy exists — which is what makes this
installable rather than a toy.

Domain-ignorant by construction (invariant 4). It knows tools, urns, aspects and
versions. It does not know what a schema, an owner or a pipeline is. The one
exception is the fact-extraction used for binding, which lives in `coordinate`
and is passed in rather than hardcoded here.
"""

import time
from dataclasses import dataclass, field

from .coordinate import (
    bind_revision,
    default_base_url,
    default_token,
    read_aspect,
    resolve_at,
)


@dataclass
class CapturedRead:
    """One context read, bound to the revision that answered it.

    `resolved=False` means no revision could be bound. That is recorded as
    absence, never silently resolved to the present (invariant 5).
    """

    tool: str
    urn: str
    aspect: str
    revision: int | None
    last_observed_ms: int | None
    value: dict
    resolved: bool
    mcp_response: dict | None = None
    response_received_ms: int = 0
    value_source: str = "aspect_api"


@dataclass
class CaptureProxy:
    base_url: str = field(default_factory=default_base_url)
    reads: list[CapturedRead] = field(default_factory=list)

    def call(
        self,
        tool: str,
        urn: str,
        aspect: str,
        at_ms: int | None = None,
    ) -> CapturedRead:
        """Forward a read and capture its revision coordinate."""
        if at_ms is None:
            aspect_version = read_aspect(urn, aspect, version=0, base_url=self.base_url)
        else:
            aspect_version = resolve_at(urn, aspect, at_ms, base_url=self.base_url)

        if aspect_version is None:
            captured = CapturedRead(
                tool=tool,
                urn=urn,
                aspect=aspect,
                revision=None,
                last_observed_ms=None,
                value={},
                resolved=False,
            )
        else:
            captured = CapturedRead(
                tool=tool,
                urn=urn,
                aspect=aspect,
                revision=aspect_version.version,
                last_observed_ms=aspect_version.last_observed_ms,
                value=aspect_version.value,
                resolved=True,
            )
        self.reads.append(captured)
        return captured

    def now_ms(self) -> int:
        return int(time.time() * 1000)


class McpCaptureProxy(CaptureProxy):
    """A CaptureProxy whose reads go through real MCP transport.

    The MCP response is the decision input (invariant 7). The revision is bound
    by matching facts, not by timestamp proximity (invariant 8) — never by
    re-fetching a value and passing it off as what the agent saw. Between two
    fetches the metadata can move, and then the revision on the record is not
    the revision that decided.

    Uses FastMCP's in-memory client transport: a real client/server round trip
    through the protocol, without spawning a subprocess. Importing a tool
    function and calling it directly would bypass MCP entirely.
    """

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url or default_base_url())
        self._client = None
        self._ctx = None

    async def __aenter__(self) -> "McpCaptureProxy":
        from datahub.sdk.main_client import DataHubClient
        from fastmcp import Client
        from mcp_server_datahub.mcp_server import (
            mcp,
            register_all_tools,
            with_datahub_client,
        )

        # Tools are registered lazily; the module-level `mcp` has none until this runs.
        register_all_tools(is_oss=True)
        # The token comes from the same environment variable the DataHub SDK
        # and MCP server already read. None is correct for an instance with
        # metadata service auth off, which is the OSS default and the only mode
        # this has been exercised against; against an auth-enabled instance the
        # MCP calls 401 without it.
        self._ctx = with_datahub_client(
            DataHubClient(server=self.base_url, token=default_token())
        )
        self._ctx.__enter__()
        self._client = Client(mcp)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None
        if self._ctx is not None:
            self._ctx.__exit__(*exc)
            self._ctx = None

    async def call_lineage(self, urn: str, *, upstream: bool = True) -> CapturedRead:
        """Read lineage over MCP and bind the result to a revision."""
        import json

        result = await self._client.call_tool(
            "get_lineage", {"urn": urn, "upstream": upstream}
        )
        received_ms = self.now_ms()

        raw = result.content[0].text if result.content else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_raw": raw}

        bound = bind_revision(
            urn, "upstreamlineage", payload, received_ms, base_url=self.base_url
        )

        captured = CapturedRead(
            tool="get_lineage",
            urn=urn,
            aspect="upstreamlineage",
            revision=bound.version if bound else None,
            last_observed_ms=bound.last_observed_ms if bound else None,
            value=payload,          # the MCP response IS the decision input
            resolved=bound is not None,
            mcp_response=payload,
            response_received_ms=received_ms,
            value_source="mcp",
        )
        self.reads.append(captured)
        return captured
