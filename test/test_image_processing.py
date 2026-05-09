import base64
import io
import pytest
from PIL import Image
from cogs._helpers import process_scramble_image


@pytest.fixture
def sample_b64_png():
    """Generate a small valid PNG encoded as base64."""
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class TestProcessScrambleImage:
    """Tests for process_scramble_image helper."""

    def test_returns_bytesio_at_position_zero(self, sample_b64_png):
        result = process_scramble_image(sample_b64_png)
        assert isinstance(result, io.BytesIO)
        assert result.tell() == 0

    def test_output_is_valid_png(self, sample_b64_png):
        result = process_scramble_image(sample_b64_png)
        img = Image.open(result)
        assert img.format == "PNG"

    def test_output_is_resized_to_500x300(self, sample_b64_png):
        result = process_scramble_image(sample_b64_png)
        img = Image.open(result)
        assert img.size == (500, 300)

    def test_invalid_base64_raises(self):
        with pytest.raises(Exception):
            process_scramble_image("not-valid-base64!!!")
