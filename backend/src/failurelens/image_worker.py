"""Bounded image codec subprocess; artifacts arrive only through standard input.

stdin: one JSON options line, then the image bytes. stdout: one JSON result
line, optionally followed by a canonical PNG. Never echo decoder exceptions:
plugins can include untrusted artifact text in their error messages.
Process/resource and import isolation are not an OS filesystem/network sandbox.
"""

from __future__ import annotations

import io
import json
import sys
import warnings


def main() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except ImportError:  # The parent still enforces a wall-clock deadline on Windows.
        pass
    from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

    def fail(code: str) -> None:
        sys.stdout.buffer.write(json.dumps({"error": code}).encode() + b"\n")

    try:
        options = json.loads(sys.stdin.buffer.readline(32_768))
        maximum = int(options["max_bytes"])
        content = sys.stdin.buffer.read(maximum + 1)
        if not content or len(content) > maximum:
            fail("limit_exceeded")
            return
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=["PNG", "JPEG"]) as probe:
                if probe.width * probe.height > options["max_pixels"]:
                    fail("limit_exceeded")
                    return
                if getattr(probe, "n_frames", 1) != 1:
                    fail("unsupported_image_frames")
                    return
                if probe.format is None:
                    fail("malformed_image")
                    return
                media_type = Image.MIME[probe.format]
                probe.verify()
            with Image.open(io.BytesIO(content), formats=["PNG", "JPEG"]) as decoded:
                decoded.load()  # Header parsing and verify() do not decode pixels.
                oriented = ImageOps.exif_transpose(decoded)
                rgba = oriented.convert("RGBA")
                # Fresh opaque RGB storage removes EXIF/text/ICC and hidden alpha RGB.
                image = Image.new("RGB", rgba.size, (255, 255, 255))
                image.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
                oriented.close()
        width, height = image.size
        masks = options.get("masks", [])
        if len(masks) > 64:
            fail("invalid_mask")
            return
        draw = ImageDraw.Draw(image)
        for mask in masks:
            x, y, w, h = (mask[key] for key in ("x", "y", "width", "height"))
            if (
                any(type(v) is not int for v in (x, y, w, h))
                or x < 0
                or y < 0
                or w <= 0
                or h <= 0
                or x + w > width
                or y + h > height
            ):
                fail("invalid_mask")
                return
            draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(0, 0, 0))
        if options.get("preview_size"):
            image.thumbnail(
                (options["preview_size"], options["preview_size"]),
                Image.Resampling.LANCZOS,
            )
        grey = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(grey.getdata())
        dhash = 0
        for y in range(8):
            for x in range(8):
                dhash = (dhash << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
        result = {
            "width": width,
            "height": height,
            "pixels": width * height,
            "media_type": media_type,
            "coordinate_system": "exif-transposed-pixels-v1",
            "dhash": f"{dhash:016x}",
            "codec_version": "pillow-" + Image.__version__,
        }
        output = b""
        if options.get("encode"):
            target = io.BytesIO()
            image.save(target, format="PNG", compress_level=6)
            output = target.getvalue()
            if len(output) > maximum:
                fail("limit_exceeded")
                return
        result["encoded_bytes"] = len(output)
        sys.stdout.buffer.write(json.dumps(result).encode() + b"\n" + output)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError):
        fail("limit_exceeded")
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
    ):
        fail("malformed_image")


if __name__ == "__main__":
    main()
