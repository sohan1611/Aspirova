"""Validate raster/SVG logos and store immutable normalized PNGs."""

import hashlib
import re
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

import boto3
import httpx
import resvg_py
from PIL import Image, ImageChops, ImageOps, IcoImagePlugin

from core.config import Settings
from core.domains import http_url
from pipeline.company_logos import MAX_ATS_BODY_BYTES, MAX_BODY_BYTES, Fetcher, FetchResult

Image.MAX_IMAGE_PIXELS = 16_000_000


@dataclass(frozen=True)
class NormalizedLogo:
    png_bytes: bytes
    sha256: str
    width: int
    height: int
    url: str


def trim_margins(image: Image.Image) -> Image.Image:
    """Remove empty alpha and a uniform corner-coloured perimeter conservatively."""
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        return image
    image = image.crop(bounds)
    corners = [
        image.getpixel(point)
        for point in (
            (0, 0),
            (image.width - 1, 0),
            (0, image.height - 1),
            (image.width - 1, image.height - 1),
        )
    ]
    corner = corners[0]
    if any(pixel[3] != 255 for pixel in corners):
        return image
    difference = ImageChops.difference(image, Image.new("RGBA", image.size, corner))
    channels = difference.split()
    difference_mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    difference_mask = ImageChops.lighter(difference_mask, channels[3])
    # A small colour tolerance absorbs near-white compression noise. Every
    # perimeter pixel must agree, so marks touching an edge keep that edge.
    foreground = difference_mask.point(lambda value: 255 if value > 8 else 0)
    perimeter = (
        (0, 0, image.width, 1),
        (0, image.height - 1, image.width, image.height),
        (0, 0, 1, image.height),
        (image.width - 1, 0, image.width, image.height),
    )
    if any(foreground.crop(edge).getbbox() for edge in perimeter):
        return image
    bounds = foreground.getbbox()
    if bounds is None:
        return image
    # Retain enough source pixels around small marks to keep a 16 px minimum.
    left, top, right, bottom = bounds
    width, height = max(16, right - left), max(16, bottom - top)
    left = max(0, min(image.width - width, (left + right - width) // 2))
    top = max(0, min(image.height - height, (top + bottom - height) // 2))
    return image.crop((left, top, left + width, top + height))


def rasterize_svg(content: bytes) -> bytes | None:
    """Render bounded, self-contained SVGs without a filesystem resource directory."""
    if len(content) > MAX_BODY_BYTES:
        return None
    text = content.decode("utf-8-sig")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet|@import", text, re.IGNORECASE):
        return None
    root = ElementTree.fromstring(text)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        return None
    for element in root.iter():
        for key, value in element.attrib.items():
            local_name = key.rsplit("}", 1)[-1].lower()
            if local_name == "base":
                return None
            if local_name == "href" and value.strip() and not value.strip().startswith("#"):
                return None
    # CSS can also reference images or local files without an href attribute.
    styles = " ".join(
        [value for element in root.iter() for value in element.attrib.values()]
        + [element.text or "" for element in root.iter()]
    )
    if "\\" in styles or re.search(r"@import", styles, re.IGNORECASE):
        return None
    for match in re.finditer(r"url\s*\((.*?)\)", styles, re.IGNORECASE | re.DOTALL):
        if not match[1].strip().strip("\"'").startswith("#"):
            return None
    return resvg_py.svg_to_bytes(svg_string=text, width=256, height=256)


def validate_and_normalize(
    result: FetchResult, *, max_aspect: float = 4.0, source: str | None = None
) -> NormalizedLogo | None:
    content_type = (
        httpx.Headers(result.headers).get("content-type", "").lower().split(";")[0].strip()
    )
    if (
        result.status != 200
        or not (content_type.startswith("image/") or content_type == "application/octet-stream")
        or not 100
        <= len(result.content)
        <= (MAX_ATS_BODY_BYTES if source == "ats_board" else MAX_BODY_BYTES)
    ):
        return None
    try:
        content = result.content
        if content_type == "image/svg+xml" or re.search(rb"<svg\b", content[:4096], re.I):
            content = rasterize_svg(content)
            if content is None:
                return None
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as opened:
                if isinstance(opened, IcoImagePlugin.IcoImageFile):
                    size = max(opened.ico.sizes(), key=lambda size: (min(size), max(size)))
                    source_image = opened.ico.getimage(size)
                else:
                    source_image = opened
                source_image.load()
                image = source_image.convert("RGBA")
            width, height = image.size
            if min(width, height) < 32 or max(width, height) / min(width, height) > max_aspect:
                return None
            # Ignore transparent padding and its hidden RGB values in the range check.
            opaque_mask = image.getchannel("A").point(lambda alpha: 255 if alpha >= 16 else 0)
            coverage = opaque_mask.histogram()[255] / (width * height)
            if not opaque_mask.getbbox():
                return None
            histogram = image.convert("RGB").histogram(mask=opaque_mask)
            ranges = []
            for channel in range(3):
                values = [value for value in range(256) if histogram[channel * 256 + value]]
                ranges.append(values[-1] - values[0])
            if coverage >= 0.95 and max(ranges) < 12:
                return None
            image = trim_margins(image)
            if min(image.size) < 16:
                return None
            # Eight pixels per side is 6.25% of the final canvas. Always fit
            # the cropped mark, preserving its proportions.
            image = ImageOps.contain(image, (112, 112), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            canvas.paste(image, ((128 - image.width) // 2, (128 - image.height) // 2))
            output = BytesIO()
            canvas.save(output, format="PNG")
            png = output.getvalue()
            return NormalizedLogo(png, hashlib.sha256(png).hexdigest(), width, height, result.url)
    except Exception:
        # Corrupt formats and Pillow's decompression-bomb warnings/errors are misses.
        return None


def best_logo(
    fetcher: Fetcher, urls: list[str], p154_url: str | None = None
) -> NormalizedLogo | None:
    best = None
    existing = 0
    for url in dict.fromkeys(urls):
        if not http_url(url) or url == p154_url:
            continue
        result = fetcher.get(url)
        if result is None or result.status != 200:
            continue
        existing += 1
        logo = validate_and_normalize(result)
        if logo is not None and (
            best is None or min(logo.width, logo.height) > min(best.width, best.height)
        ):
            best = logo
        if existing == 4:
            break
    # An entity's wordmark is evidence only after the domain icon path fails.
    # It must never win over a valid square icon just because it is larger.
    if best is None and p154_url and http_url(p154_url):
        result = fetcher.get(p154_url)
        if result is not None:
            best = validate_and_normalize(result, max_aspect=4.0)
    return best


def logo_storage_configured(settings: Settings) -> bool:
    return all(
        value.strip()
        for value in (
            settings.logo_s3_endpoint_url,
            settings.logo_s3_access_key_id,
            settings.logo_s3_secret_access_key,
            settings.logo_s3_bucket,
            settings.logo_public_base_url,
        )
    )


def s3_client(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.logo_s3_endpoint_url,
        aws_access_key_id=settings.logo_s3_access_key_id,
        aws_secret_access_key=settings.logo_s3_secret_access_key,
    )


def upload_logo(client: Any, settings: Settings, slug: str, logo: NormalizedLogo) -> str:
    key = f"logos/{slug}-{logo.sha256[:8]}.png"
    client.put_object(
        Bucket=settings.logo_s3_bucket,
        Key=key,
        Body=logo.png_bytes,
        ContentType="image/png",
        CacheControl="public, max-age=31536000, immutable",
    )
    return settings.logo_public_base_url.rstrip("/") + "/" + key
