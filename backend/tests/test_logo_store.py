"""Image validation and object-store contracts without external services."""

import hashlib
import random
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageOps

from core.config import Settings
from core.logo_store import (
    best_logo,
    logo_storage_configured,
    s3_client,
    upload_logo,
    validate_and_normalize,
)
from pipeline.company_logos import (
    MAX_ATS_BODY_BYTES,
    MAX_BODY_BYTES,
    FetchResult,
    Params,
    wikimedia_logo_url,
)


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue() -> None:
    """Override conftest's database cleanup for this database-free module."""


def patterned_image(size: tuple[int, int]) -> Image.Image:
    content = random.Random(0).randbytes(size[0] * size[1] * 3)
    return Image.frombytes("RGB", size, content).convert("RGBA")


def image_result(
    image: Image.Image,
    *,
    content_type: str = "image/png",
    status: int = 200,
    url: str = "https://acme.example/logo.png",
) -> FetchResult:
    output = BytesIO()
    image.save(output, format="PNG")
    return FetchResult(status, url, {"Content-Type": content_type}, output.getvalue())


class ImageFetcher:
    def __init__(self, responses: dict[str, FetchResult | None]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, *, params: Params | None = None) -> FetchResult | None:
        assert params is None
        self.calls.append(url)
        return self.responses.get(url)


def test_normalized_png_dimensions_hash_padding_and_original_dimensions() -> None:
    result = image_result(patterned_image((256, 128)))
    logo = validate_and_normalize(result)
    assert logo is not None
    assert (logo.width, logo.height, logo.url) == (256, 128, result.url)
    assert logo.sha256 == hashlib.sha256(logo.png_bytes).hexdigest()
    assert validate_and_normalize(result) == logo
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.size == (128, 128)
        assert normalized.format == "PNG"
        assert normalized.mode == "RGBA"
        assert normalized.getchannel("A").getbbox() == (8, 36, 120, 92)


def test_small_valid_logo_fits_canvas() -> None:
    logo = validate_and_normalize(image_result(patterned_image((32, 32))))
    assert logo is not None
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.getchannel("A").getbbox() == (8, 8, 120, 120)


@pytest.mark.parametrize("background", [(255, 255, 255, 255), (250, 251, 252, 255), (0, 0, 0, 0)])
def test_large_blank_margins_are_trimmed(background: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (512, 512), background)
    image.paste(patterned_image((32, 24)), (240, 244))
    logo = validate_and_normalize(image_result(image))
    assert logo is not None
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        bounds = normalized.getchannel("A").getbbox()
        assert bounds is not None
        assert max(bounds[2] - bounds[0], bounds[3] - bounds[1]) >= 128 * 0.85
        assert bounds == (8, 22, 120, 106)


def test_near_uniform_white_border_is_trimmed() -> None:
    image = Image.new("RGBA", (128, 128), (255, 255, 255, 255))
    for y in range(1, 128, 2):
        ImageDraw.Draw(image).line((0, y, 127, y), fill=(249, 250, 251, 255))
    image.paste(patterned_image((32, 32)), (48, 48))
    logo = validate_and_normalize(image_result(image))
    assert logo is not None
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.getchannel("A").getbbox() == (8, 8, 120, 120)


@pytest.mark.parametrize("touch_corner", [False, True])
def test_corner_colour_does_not_crop_an_edge_touching_mark(touch_corner: bool) -> None:
    image = Image.new("RGBA", (64, 64), "white")
    ImageDraw.Draw(image).rectangle((0, 0 if touch_corner else 8, 39, 55), fill="blue")
    logo = validate_and_normalize(image_result(image))
    assert logo is not None
    expected = Image.new("RGBA", (128, 128))
    expected.paste(ImageOps.contain(image, (112, 112), Image.Resampling.LANCZOS), (8, 8))
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.tobytes() == expected.tobytes()


def test_full_bleed_logo_keeps_proportions_and_pixels() -> None:
    image = patterned_image((256, 128))
    logo = validate_and_normalize(image_result(image))
    assert logo is not None
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert (
            normalized.crop((8, 36, 120, 92)).tobytes()
            == image.resize((112, 56), Image.Resampling.LANCZOS).tobytes()
        )


@pytest.mark.parametrize("size", [(16, 16), (31, 64), (320, 64), (64, 320)])
def test_small_or_wide_images_rejected(size: tuple[int, int]) -> None:
    result = image_result(patterned_image(size))
    assert len(result.content) >= 100
    assert validate_and_normalize(result) is None


@pytest.mark.parametrize("alpha", [0, 15])
def test_fully_transparent_images_rejected(alpha: int) -> None:
    image = patterned_image((64, 64))
    image.putalpha(alpha)
    assert validate_and_normalize(image_result(image)) is None


@pytest.mark.parametrize("variation", [0, 11])
def test_single_colour_and_near_uniform_images_rejected(variation: int) -> None:
    image = Image.new("RGBA", (64, 64), (120, 120, 120, 255))
    image.putpixel((20, 20), (120 + variation, 120, 120, 255))
    assert validate_and_normalize(image_result(image)) is None


def test_hidden_rgb_does_not_make_a_uniform_opaque_image_valid() -> None:
    image = patterned_image((64, 64))
    # Hidden RGB varies in a transparent border, while uniform opaque pixels cover >95%.
    image.putalpha(0)
    ImageDraw.Draw(image).rectangle((1, 1, 63, 63), fill=(120, 120, 120, 255))
    assert validate_and_normalize(image_result(image)) is None


def test_single_colour_glyph_on_transparent_background_is_valid() -> None:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((8, 8, 55, 55), fill=(0, 0, 0, 255))
    assert validate_and_normalize(image_result(image)) is not None


def test_single_opaque_pixel_is_practically_empty() -> None:
    image = patterned_image((64, 64))
    image.putalpha(0)
    image.putpixel((32, 32), (0, 0, 0, 255))
    result = image_result(image)
    assert len(result.content) >= 100
    assert validate_and_normalize(result) is None


def test_twelve_level_channel_range_is_valid() -> None:
    image = Image.new("RGBA", (64, 64), (120, 120, 120, 255))
    image.putpixel((20, 20), (132, 120, 120, 255))
    assert validate_and_normalize(image_result(image)) is not None


@pytest.mark.parametrize(
    "content_type", ["image/png", "Image/PNG; charset=binary", "application/octet-stream"]
)
def test_allowed_content_types(content_type: str) -> None:
    assert (
        validate_and_normalize(image_result(patterned_image((64, 64)), content_type=content_type))
        is not None
    )


@pytest.mark.parametrize(
    "content_type", ["text/html", "application/json", "", "application/octet-streamish"]
)
def test_unexpected_content_types_rejected(content_type: str) -> None:
    assert (
        validate_and_normalize(image_result(patterned_image((64, 64)), content_type=content_type))
        is None
    )


@pytest.mark.parametrize("status", [201, 302, 404, 500])
def test_only_http_200_is_valid(status: int) -> None:
    assert validate_and_normalize(image_result(patterned_image((64, 64)), status=status)) is None


@pytest.mark.parametrize(
    "content",
    [b"x" * 99, b"x" * 100, b"x" * (MAX_BODY_BYTES + 1)],
    ids=["99-bytes", "100-bytes", "over-cap"],
)
def test_size_limits_and_corrupt_bytes(content: bytes) -> None:
    result = FetchResult(200, "https://acme.example/logo", {"content-type": "image/png"}, content)
    assert validate_and_normalize(result) is None


@pytest.mark.parametrize("pixel_cap", [3000, 100])
def test_decompression_bomb_warning_and_error_rejected(
    monkeypatch: pytest.MonkeyPatch, pixel_cap: int
) -> None:
    result = image_result(patterned_image((64, 64)))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", pixel_cap)
    assert validate_and_normalize(result) is None


def test_ico_uses_largest_frame() -> None:
    output = BytesIO()
    patterned_image((64, 64)).save(output, format="ICO", sizes=[(16, 16), (32, 32), (64, 64)])
    result = FetchResult(
        200, "https://acme.example/icon.ico", {"content-type": "image/x-icon"}, output.getvalue()
    )
    logo = validate_and_normalize(result)
    assert logo is not None
    assert (logo.width, logo.height) == (64, 64)


def test_ddg_google_404_placeholders_ignored() -> None:
    urls = [
        "https://icons.duckduckgo.com/ip3/acme.example.ico",
        "https://www.google.com/s2/favicons?domain=acme.example&sz=128",
    ]
    placeholder = image_result(patterned_image((128, 128)), status=404)
    fetcher = ImageFetcher({url: placeholder for url in urls})
    assert best_logo(fetcher, urls) is None
    assert fetcher.calls == urls


@pytest.mark.parametrize(
    ("size", "accepted"),
    [((192, 64), True), ((64, 64), True), ((160, 100), True), ((320, 64), False)],
)
def test_p154_aspect_gate(size: tuple[int, int], accepted: bool) -> None:
    url = wikimedia_logo_url("Acme logo.png")
    result = image_result(patterned_image(size), url=url)
    logo = best_logo(ImageFetcher({url: result}), [url], p154_url=url)
    assert (logo is not None) == accepted


def test_wide_p154_is_used_only_after_domain_icons_fail() -> None:
    icon = "https://acme.example/icon.png"
    p154 = wikimedia_logo_url("Acme.svg")
    responses = {
        icon: image_result(patterned_image((32, 32)), url=icon),
        p154: image_result(patterned_image((384, 128)), url=p154),
    }
    fetcher = ImageFetcher(responses)
    logo = best_logo(fetcher, [icon, p154], p154_url=p154)
    assert logo and logo.url == icon
    assert fetcher.calls == [icon]
    responses[icon] = image_result(patterned_image((16, 16)), url=icon)
    fetcher.calls.clear()
    logo = best_logo(fetcher, [icon, p154], p154_url=p154)
    assert logo and logo.url == p154
    assert fetcher.calls == [icon, p154]


def test_p154_is_not_lost_after_four_invalid_icons() -> None:
    icons = [f"https://acme.example/{index}.png" for index in range(4)]
    p154 = wikimedia_logo_url("Acme.svg")
    responses = {url: image_result(patterned_image((16, 16)), url=url) for url in icons}
    responses[p154] = image_result(patterned_image((192, 64)), url=p154)
    logo = best_logo(ImageFetcher(responses), [*icons, p154], p154_url=p154)
    assert logo and logo.url == p154


def test_large_cmyk_jpeg_is_accepted_only_for_ats_board() -> None:
    image = patterned_image((1024, 1024)).convert("CMYK")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    assert MAX_BODY_BYTES < len(output.getvalue()) < MAX_ATS_BODY_BYTES
    result = FetchResult(
        200, "https://cdn.example/logo.jpg", {"content-type": "image/jpeg"}, output.getvalue()
    )
    assert validate_and_normalize(result) is None
    assert validate_and_normalize(result, source="source_payload") is None
    logo = validate_and_normalize(result, source="ats_board")
    assert logo and (logo.width, logo.height) == (1024, 1024)
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.mode == "RGBA"


@pytest.mark.parametrize("mode", ["P", "LA", "CMYK"])
def test_non_rgb_ats_images_convert_before_normalizing(mode: str) -> None:
    image = patterned_image((64, 64)).convert(mode)
    output = BytesIO()
    image.save(output, format="JPEG" if mode == "CMYK" else "PNG")
    result = FetchResult(
        200, "https://cdn.example/logo", {"content-type": "image/png"}, output.getvalue()
    )
    assert validate_and_normalize(result, source="ats_board") is not None


def test_ats_images_retain_download_and_pixel_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    result = image_result(patterned_image((64, 64)))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 3000)
    assert validate_and_normalize(result, source="ats_board") is None
    assert (
        validate_and_normalize(
            replace(result, content=b"x" * (MAX_ATS_BODY_BYTES + 1)), source="ats_board"
        )
        is None
    )


@pytest.mark.parametrize("content_type", ["image/svg+xml", "image/png", "application/octet-stream"])
def test_svg_is_sniffed_and_rasterized(content_type: str) -> None:
    content = (Path(__file__).parent / "fixtures/logos/board_square.svg").read_bytes()
    result = FetchResult(
        200, "https://cdn.example/logo.png", {"content-type": content_type}, content
    )
    logo = validate_and_normalize(result)
    assert logo and (logo.width, logo.height) == (256, 256)
    with Image.open(BytesIO(logo.png_bytes)) as normalized:
        assert normalized.size == (128, 128)
        assert normalized.format == "PNG"


@pytest.mark.parametrize(
    "resource",
    [
        '<image href="https://example.com/logo.png"/>',
        '<image xlink:href="http://example.com/logo.png"/>',
        '<image href="file:///private/logo.png"/>',
        '<image href="&#104;ttps://example.com/logo.png"/>',
        '<image href="//example.com/logo.png"/>',
        '<image href="relative.png"/>',
        "<style>path { fill: url(file:///private/logo.svg); }</style>",
        '<style>@import "https://example.com/style.css";</style>',
    ],
)
def test_svg_external_resources_are_refused_before_rendering(resource, monkeypatch) -> None:
    calls = []

    def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("unsafe SVG must never reach resvg")

    monkeypatch.setattr("core.logo_store.resvg_py.svg_to_bytes", forbidden)
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 64 64">'
        + resource
        + "</svg>"
    ).encode()
    result = FetchResult(
        200, "https://cdn.example/logo.png", {"content-type": "image/svg+xml"}, content
    )
    assert validate_and_normalize(result) is None
    assert calls == []


def test_svg_input_and_render_dimensions_are_bounded() -> None:
    content = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100000 100000"><circle cx="50000" cy="50000" r="40000"/></svg>'
    result = FetchResult(
        200, "https://cdn.example/logo", {"content-type": "image/svg+xml"}, content
    )
    logo = validate_and_normalize(result, source="ats_board")
    assert logo and max(logo.width, logo.height) <= 512
    assert (
        validate_and_normalize(
            replace(result, content=content + b" " * MAX_BODY_BYTES), source="ats_board"
        )
        is None
    )


def test_best_logo_largest_smallest_side_and_earlier_ties() -> None:
    sizes = [(300, 80), (128, 128), (256, 128), (192, 96)]
    urls = [f"https://acme.example/{index}.png" for index in range(len(sizes))]
    fetcher = ImageFetcher(
        {url: image_result(patterned_image(size), url=url) for url, size in zip(urls, sizes)}
    )
    logo = best_logo(fetcher, urls)
    assert logo is not None
    assert logo.url == urls[1]
    assert (logo.width, logo.height) == (128, 128)


def test_best_logo_stops_after_four_http_200s_including_invalid_images() -> None:
    urls = [f"https://acme.example/{index}.png" for index in range(7)]
    invalid = FetchResult(200, urls[2], {"content-type": "image/png"}, b"invalid" * 100)
    fetcher = ImageFetcher(
        {
            urls[0]: None,
            urls[1]: image_result(patterned_image((64, 64)), status=404),
            urls[2]: invalid,
            urls[3]: replace(invalid, url=urls[3]),
            urls[4]: image_result(patterned_image((64, 64)), url=urls[4]),
            urls[5]: image_result(patterned_image((96, 96)), url=urls[5]),
            urls[6]: image_result(patterned_image((256, 256)), url=urls[6]),
        }
    )
    logo = best_logo(fetcher, urls)
    assert logo is not None and logo.url == urls[5]
    assert fetcher.calls == urls[:6]


def test_best_logo_validates_urls_and_deduplicates() -> None:
    url = "https://acme.example/icon.png"
    fetcher = ImageFetcher({url: image_result(patterned_image((64, 64)))})
    assert best_logo(fetcher, ["javascript:example.com", "https://[broken", url, url]) is not None
    assert fetcher.calls == [url]


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        logo_s3_endpoint_url="https://storage.example",
        logo_s3_access_key_id="test-access",
        logo_s3_secret_access_key="test-secret",
        logo_s3_bucket="test-logos",
        logo_public_base_url="https://logos.example///",
    )


@pytest.mark.parametrize(
    "field",
    [
        "logo_s3_endpoint_url",
        "logo_s3_access_key_id",
        "logo_s3_secret_access_key",
        "logo_s3_bucket",
        "logo_public_base_url",
    ],
)
def test_storage_requires_every_logo_setting(field: str) -> None:
    settings = configured_settings()
    assert logo_storage_configured(settings)
    assert not logo_storage_configured(settings.model_copy(update={field: ""}))
    assert not logo_storage_configured(settings.model_copy(update={field: " "}))


def test_s3_client_uses_logo_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    stub = object()

    def client(service: str, **kwargs: Any) -> object:
        calls.append((service, kwargs))
        return stub

    monkeypatch.setattr("core.logo_store.boto3.client", client)
    settings = configured_settings()
    assert s3_client(settings) is stub
    assert calls == [
        (
            "s3",
            {
                "endpoint_url": settings.logo_s3_endpoint_url,
                "aws_access_key_id": settings.logo_s3_access_key_id,
                "aws_secret_access_key": settings.logo_s3_secret_access_key,
            },
        )
    ]


def test_upload_key_url_and_immutable_headers() -> None:
    class StubClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def put_object(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

    logo = validate_and_normalize(image_result(patterned_image((64, 64))))
    assert logo is not None
    client = StubClient()
    url = upload_logo(client, configured_settings(), "acme", logo)
    key = f"logos/acme-{logo.sha256[:8]}.png"
    assert url == f"https://logos.example/{key}"
    assert client.calls == [
        {
            "Bucket": "test-logos",
            "Key": key,
            "Body": logo.png_bytes,
            "ContentType": "image/png",
            "CacheControl": "public, max-age=31536000, immutable",
        }
    ]
