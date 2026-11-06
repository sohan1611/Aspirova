"""Validate raster logos and store immutable normalized PNGs."""

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import boto3
import httpx
from PIL import Image, ImageOps, IcoImagePlugin

from core.config import Settings
from core.domains import http_url
from pipeline.company_logos import MAX_BODY_BYTES, Fetcher, FetchResult

Image.MAX_IMAGE_PIXELS = 16_000_000


@dataclass(frozen=True)
class NormalizedLogo:
    png_bytes: bytes
    sha256: str
    width: int
    height: int
    url: str


def validate_and_normalize(
    result: FetchResult, *, max_aspect: float = 4.0
) -> NormalizedLogo | None:
    content_type = (
        httpx.Headers(result.headers).get("content-type", "").lower().split(";")[0].strip()
    )
    if (
        result.status != 200
        or not (content_type.startswith("image/") or content_type == "application/octet-stream")
        or not 100 <= len(result.content) <= MAX_BODY_BYTES
    ):
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(result.content)) as source:
                if isinstance(source, IcoImagePlugin.IcoImageFile):
                    size = max(source.ico.sizes(), key=lambda size: (min(size), max(size)))
                    source_image = source.ico.getimage(size)
                else:
                    source_image = source
                source_image.load()
                image = source_image.convert("RGBA")
            width, height = image.size
            if min(width, height) < 32 or max(width, height) / min(width, height) > max_aspect:
                return None
            # Ignore transparent padding and its hidden RGB values in the range check.
            opaque_mask = image.getchannel("A").point(lambda alpha: 255 if alpha >= 16 else 0)
            coverage = opaque_mask.histogram()[255] / (width * height)
            if coverage < 0.01:
                return None
            histogram = image.convert("RGB").histogram(mask=opaque_mask)
            ranges = []
            for channel in range(3):
                values = [value for value in range(256) if histogram[channel * 256 + value]]
                ranges.append(values[-1] - values[0])
            if coverage >= 0.95 and max(ranges) < 12:
                return None
            image = ImageOps.contain(image, (128, 128), Image.Resampling.LANCZOS)
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
        if not http_url(url):
            continue
        result = fetcher.get(url)
        if result is None or result.status != 200:
            continue
        existing += 1
        logo = validate_and_normalize(result, max_aspect=1.6 if url == p154_url else 4.0)
        if logo is not None and (
            best is None or min(logo.width, logo.height) > min(best.width, best.height)
        ):
            best = logo
        if existing == 4:
            break
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
