from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


DDS_MAGIC = 0x20534444
DDSD_CAPS = 0x00000001
DDSD_HEIGHT = 0x00000002
DDSD_WIDTH = 0x00000004
DDSD_PITCH = 0x00000008
DDSD_PIXELFORMAT = 0x00001000
DDSD_MIPMAPCOUNT = 0x00020000
DDSD_LINEARSIZE = 0x00080000

DDPF_ALPHAPIXELS = 0x00000001
DDPF_FOURCC = 0x00000004
DDPF_RGB = 0x00000040
DDPF_LUMINANCE = 0x00020000
DDPF_BUMPDUDV = 0x00080000

DDSCAPS_COMPLEX = 0x00000008
DDSCAPS_TEXTURE = 0x00001000
DDSCAPS_MIPMAP = 0x00400000

FOURCC_DXT1 = b"DXT1"
FOURCC_DXT3 = b"DXT3"
FOURCC_DXT5 = b"DXT5"


@dataclass(frozen=True)
class TextureDescriptor:
    width: int
    height: int
    levels: int
    texture_type: str
    data_size: int
    top_level_size: int


def export_dds(descriptor: TextureDescriptor, texture_data: bytes, target_path: str | Path) -> None:
    Path(target_path).write_bytes(build_dds(descriptor, texture_data))


def build_dds(descriptor: TextureDescriptor, texture_data: bytes) -> bytes:
    if len(texture_data) != descriptor.data_size:
        raise ValueError(
            f"Texture data size mismatch. Expected {descriptor.data_size} bytes, got {len(texture_data)}."
        )

    flags, pitch_or_linear_size, pixel_format = _describe_format(descriptor)
    if descriptor.levels > 1:
        flags |= DDSD_MIPMAPCOUNT

    header = bytearray()
    header += struct.pack("<I", DDS_MAGIC)
    header += struct.pack("<I", 124)
    header += struct.pack("<I", flags)
    header += struct.pack("<I", descriptor.height)
    header += struct.pack("<I", descriptor.width)
    header += struct.pack("<I", pitch_or_linear_size)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", descriptor.levels)

    for _ in range(11):
        header += struct.pack("<I", 0)

    header += struct.pack("<I", 32)
    header += struct.pack("<I", pixel_format["flags"])
    header += struct.pack("<I", pixel_format["fourcc"])
    header += struct.pack("<I", pixel_format["bit_count"])
    header += struct.pack("<I", pixel_format["red_mask"])
    header += struct.pack("<I", pixel_format["green_mask"])
    header += struct.pack("<I", pixel_format["blue_mask"])
    header += struct.pack("<I", pixel_format["alpha_mask"])

    caps = DDSCAPS_TEXTURE
    if descriptor.levels > 1:
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP

    header += struct.pack("<IIIII", caps, 0, 0, 0, 0)
    return bytes(header) + texture_data


def import_dds(descriptor: TextureDescriptor, source_path: str | Path) -> bytes:
    raw = Path(source_path).read_bytes()
    if len(raw) < 128:
        raise ValueError("The selected file is not a valid DDS texture.")

    magic, header_size = struct.unpack_from("<II", raw, 0)
    if magic != DDS_MAGIC:
        raise ValueError("The selected file is not a DDS texture.")
    if header_size != 124:
        raise ValueError("Unsupported DDS header size.")

    flags, height, width, _pitch_or_linear, _depth, mip_count = struct.unpack_from("<IIIIII", raw, 8)
    pixel_format_size = struct.unpack_from("<I", raw, 76)[0]
    if pixel_format_size != 32:
        raise ValueError("Unsupported DDS pixel format header.")

    pixel_flags, fourcc, bit_count, red_mask, green_mask, blue_mask, alpha_mask = struct.unpack_from(
        "<IIIIIII", raw, 80
    )

    if width != descriptor.width or height != descriptor.height:
        raise ValueError(
            f"DDS dimensions do not match the target texture. Expected {descriptor.width}x{descriptor.height}, "
            f"found {width}x{height}."
        )

    declared_mip_count = mip_count if flags & DDSD_MIPMAPCOUNT else 1
    if declared_mip_count != descriptor.levels:
        raise ValueError(
            f"DDS mip count does not match the target texture. Expected {descriptor.levels}, "
            f"found {declared_mip_count}."
        )

    _validate_format(
        descriptor.texture_type,
        pixel_flags,
        fourcc,
        bit_count,
        red_mask,
        green_mask,
        blue_mask,
        alpha_mask,
    )

    payload = raw[128:]
    if len(payload) != descriptor.data_size:
        raise ValueError(
            f"DDS payload size mismatch. Expected {descriptor.data_size} bytes but found {len(payload)}. "
            "Save the DDS with the original format, dimensions, and mipmaps."
        )
    return payload


def _describe_format(descriptor: TextureDescriptor) -> tuple[int, int, dict[str, int]]:
    texture_type = descriptor.texture_type.upper()
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT

    if texture_type == "DXT1":
        return (
            flags | DDSD_LINEARSIZE,
            descriptor.top_level_size,
            _pixel_format(DDPF_FOURCC, _fourcc_as_int(FOURCC_DXT1), 0, 0, 0, 0, 0),
        )
    if texture_type == "DXT3":
        return (
            flags | DDSD_LINEARSIZE,
            descriptor.top_level_size,
            _pixel_format(DDPF_FOURCC, _fourcc_as_int(FOURCC_DXT3), 0, 0, 0, 0, 0),
        )
    if texture_type == "DXT5":
        return (
            flags | DDSD_LINEARSIZE,
            descriptor.top_level_size,
            _pixel_format(DDPF_FOURCC, _fourcc_as_int(FOURCC_DXT5), 0, 0, 0, 0, 0),
        )
    if texture_type == "A8R8G8B8":
        return flags | DDSD_PITCH, descriptor.width * 4, _pixel_format(
            DDPF_RGB | DDPF_ALPHAPIXELS, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000
        )
    if texture_type == "X8R8G8B8":
        return flags | DDSD_PITCH, descriptor.width * 4, _pixel_format(
            DDPF_RGB, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0
        )
    if texture_type == "R8G8B8":
        return flags | DDSD_PITCH, descriptor.width * 3, _pixel_format(
            DDPF_RGB, 0, 24, 0x00FF0000, 0x0000FF00, 0x000000FF, 0
        )
    if texture_type == "R5G6B5":
        return flags | DDSD_PITCH, descriptor.width * 2, _pixel_format(
            DDPF_RGB, 0, 16, 0x0000F800, 0x000007E0, 0x0000001F, 0
        )
    if texture_type == "A1R5G5B5":
        return flags | DDSD_PITCH, descriptor.width * 2, _pixel_format(
            DDPF_RGB | DDPF_ALPHAPIXELS, 0, 16, 0x00007C00, 0x000003E0, 0x0000001F, 0x00008000
        )
    if texture_type == "A4R4G4B4":
        return flags | DDSD_PITCH, descriptor.width * 2, _pixel_format(
            DDPF_RGB | DDPF_ALPHAPIXELS, 0, 16, 0x00000F00, 0x000000F0, 0x0000000F, 0x0000F000
        )
    if texture_type == "A8L8":
        return flags | DDSD_PITCH, descriptor.width * 2, _pixel_format(
            DDPF_LUMINANCE | DDPF_ALPHAPIXELS, 0, 16, 0x000000FF, 0, 0, 0x0000FF00
        )
    if texture_type == "V8U8":
        return flags | DDSD_PITCH, descriptor.width * 2, _pixel_format(
            DDPF_BUMPDUDV, 0, 16, 0x000000FF, 0x0000FF00, 0, 0
        )
    if texture_type == "L8":
        return flags | DDSD_PITCH, descriptor.width, _pixel_format(DDPF_LUMINANCE, 0, 8, 0x000000FF, 0, 0, 0)
    raise ValueError("Unsupported texture type for DDS export.")


def _validate_format(
    texture_type: str,
    pixel_flags: int,
    fourcc: int,
    bit_count: int,
    red_mask: int,
    green_mask: int,
    blue_mask: int,
    alpha_mask: int,
) -> None:
    texture_type = texture_type.upper()
    if texture_type == "DXT1":
        _validate_compressed(pixel_flags, fourcc, FOURCC_DXT1, "DXT1")
        return
    if texture_type == "DXT3":
        _validate_compressed(pixel_flags, fourcc, FOURCC_DXT3, "DXT3")
        return
    if texture_type == "DXT5":
        _validate_compressed(pixel_flags, fourcc, FOURCC_DXT5, "DXT5")
        return

    expected = {
        "A8R8G8B8": (DDPF_RGB | DDPF_ALPHAPIXELS, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
        "X8R8G8B8": (DDPF_RGB, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0),
        "R8G8B8": (DDPF_RGB, 24, 0x00FF0000, 0x0000FF00, 0x000000FF, 0),
        "R5G6B5": (DDPF_RGB, 16, 0x0000F800, 0x000007E0, 0x0000001F, 0),
        "A1R5G5B5": (DDPF_RGB | DDPF_ALPHAPIXELS, 16, 0x00007C00, 0x000003E0, 0x0000001F, 0x00008000),
        "A4R4G4B4": (DDPF_RGB | DDPF_ALPHAPIXELS, 16, 0x00000F00, 0x000000F0, 0x0000000F, 0x0000F000),
        "A8L8": (DDPF_LUMINANCE | DDPF_ALPHAPIXELS, 16, 0x000000FF, 0, 0, 0x0000FF00),
        "V8U8": (DDPF_BUMPDUDV, 16, 0x000000FF, 0x0000FF00, 0, 0),
        "L8": (DDPF_LUMINANCE, 8, 0x000000FF, 0, 0, 0),
    }.get(texture_type)

    if expected is None:
        raise ValueError("Unsupported texture type for DDS import.")

    expected_flags, expected_bits, expected_red, expected_green, expected_blue, expected_alpha = expected
    if (
        (pixel_flags & expected_flags) != expected_flags
        or bit_count != expected_bits
        or red_mask != expected_red
        or green_mask != expected_green
        or blue_mask != expected_blue
        or alpha_mask != expected_alpha
    ):
        raise ValueError(f"DDS format does not match the target {texture_type} texture.")


def _validate_compressed(pixel_flags: int, fourcc: int, expected_fourcc: bytes, label: str) -> None:
    if (pixel_flags & DDPF_FOURCC) == 0 or fourcc != _fourcc_as_int(expected_fourcc):
        raise ValueError(f"DDS format does not match the target {label} texture.")


def _pixel_format(
    flags: int,
    fourcc: int,
    bit_count: int,
    red_mask: int,
    green_mask: int,
    blue_mask: int,
    alpha_mask: int,
) -> dict[str, int]:
    return {
        "flags": flags,
        "fourcc": fourcc,
        "bit_count": bit_count,
        "red_mask": red_mask,
        "green_mask": green_mask,
        "blue_mask": blue_mask,
        "alpha_mask": alpha_mask,
    }


def _fourcc_as_int(value: bytes) -> int:
    return value[0] | (value[1] << 8) | (value[2] << 16) | (value[3] << 24)
