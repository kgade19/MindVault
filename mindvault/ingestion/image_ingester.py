"""Image ingestion — Pillow open/validate + vision model description."""
from __future__ import annotations

import io

from PIL import Image

from mindvault.llm.claude_client import describe_image

# Cap pixel count before Pillow decodes the full raster to prevent decompression
# bomb attacks (a crafted image claiming a tiny file size but huge pixel area).
# Pillow's built-in threshold is ~178 MP; we lower it to a practical upload limit.
_MAX_IMAGE_PIXELS = 50_000_000  # ~50 megapixels
Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS

# Vision models cap the longest edge at 2048 px on the server side; resize
# proactively to avoid needlessly large payloads.
_MAX_DIMENSION = 2048
_SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def ingest_image(image_bytes: bytes, filename: str = "") -> str:
    """
    Validate, optionally resize, and send an image to the vision model.
    Returns a detailed textual description of the image content.

    Raises PIL.Image.DecompressionBombError for images that exceed _MAX_IMAGE_PIXELS.
    """
    img = Image.open(io.BytesIO(image_bytes))

    fmt = img.format or "JPEG"
    if fmt not in _SUPPORTED_FORMATS:
        # Convert unsupported formats to PNG
        fmt = "PNG"

    # Resize if either dimension exceeds limit
    if img.width > _MAX_DIMENSION or img.height > _MAX_DIMENSION:
        img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)

    # Re-encode to bytes
    buf = io.BytesIO()
    save_format = fmt if fmt != "GIF" else "PNG"
    img.save(buf, format=save_format)
    processed_bytes = buf.getvalue()

    media_type_map = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "WEBP": "image/webp",
    }
    media_type = media_type_map.get(fmt, "image/jpeg")

    prompt = (
        f"This image was uploaded as '{filename}'. "
        "Please provide a comprehensive description: extract all visible text verbatim, "
        "describe all diagrams/charts/tables with their data, identify any key entities "
        "(people, systems, processes) shown, and summarise the overall content and purpose."
    )
    return describe_image(processed_bytes, media_type=media_type, prompt=prompt)
