"""Normalize avatar pixels before storing them in the local account database."""
import base64
import binascii
import io
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field
from auth.schemas import StrictModel


class AvatarUpload(StrictModel):
    data: str = Field(max_length=2_800_000)


class AvatarPreset(StrictModel):
    preset: int = Field(ge=1, le=8, strict=True)


def normalize_avatar(data):
    try:
        prefix, encoded = data.split(",", 1)
        if prefix not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("头像图片不能超过 2 MB。")
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"} or source.width * source.height > 20_000_000:
                raise ValueError()
            source.seek(0)
            image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (256, 256))
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85)
        return "data:image/webp;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        if str(error) == "头像图片不能超过 2 MB。":
            raise
        raise ValueError("请上传有效的 PNG、JPG 或 WebP 图片（不超过 2 MB）。") from error
