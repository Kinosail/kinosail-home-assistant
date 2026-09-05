from pathlib import Path
from struct import unpack

ROOT = Path(__file__).parents[1]
BRAND = ROOT / "custom_components" / "kinosail" / "brand"


def test_logo_is_centered_inside_the_shared_kinosail_ring() -> None:
    svg = (BRAND / "icon.svg").read_text()
    assert '<circle cx="256" cy="256" r="138"' in svg
    assert 'd="m190 247 66-59 66 59v80H190v-80z"' in svg
    assert 'd="m236 242 60 42-60 42z"' in svg

    for name, size in {"icon.png": 256, "icon@2x.png": 512}.items():
        data = (BRAND / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert unpack(">II", data[16:24]) == (size, size)
