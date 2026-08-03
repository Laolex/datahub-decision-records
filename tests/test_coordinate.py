import pytest

from dhdr.coordinate import AspectVersion, read_aspect

URN = "urn:li:dataset:(urn:li:dataPlatform:hive,probe_orders2,PROD)"


@pytest.mark.integration
def test_read_aspect_returns_version_and_stamp():
    av = read_aspect(URN, "upstreamlineage", version=1)
    assert isinstance(av, AspectVersion)
    assert av.version == 1
    assert av.last_observed_ms > 0
    assert "upstreams" in av.value
