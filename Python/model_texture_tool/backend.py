from __future__ import annotations

import base64
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from types import SimpleNamespace

from .dds_codec import TextureDescriptor, export_dds, import_dds


class BackendUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class TextureSummary:
    index: int
    name: str
    title_name: str
    width: int
    height: int
    levels: int
    texture_type: str
    is_external_reference: bool
    requires_ps3_reference_repair: bool
    has_unsupported_ps3_write_layout: bool

    @property
    def list_label(self) -> str:
        format_label = "External Reference" if self.is_external_reference else self.texture_type
        return f"{self.title_name} | {self.width}x{self.height} | {format_label}"


class RageBackend:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.vendor_dir = self._resolve_vendor_dir(self.project_root)

        self._model_file = None
        self._texture_file = None
        self._current_path: Path | None = None
        self._modified_indexes: set[int] = set()
        self._ps3_header_state: dict[str, int | bytes] | None = None
        self._ps3_payload: bytes | None = None
        self._helper_mode: str | None = None
        self._xbox_texture_summaries: list[TextureSummary] = []
        self._xbox_descriptors: dict[int, TextureDescriptor] = {}
        self._xbox_modified_payloads: dict[int, bytes] = {}
        self._xbox_thumbnail_png: dict[int, str] = {}
        self._xbox_preview_cache: dict[tuple[int, int, str, int], str] = {}
        self._xbox_revision = 0

        self._runtime = self._load_runtime()

    def _resolve_vendor_dir(self, project_root: Path) -> Path:
        candidates = [project_root / "vendor"]

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "vendor")

        module_root = Path(__file__).resolve().parents[1]
        candidates.append(module_root / "vendor")

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        return candidates[0].resolve()

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def has_unsaved_changes(self) -> bool:
        return bool(self._modified_indexes)

    def close(self) -> None:
        if self._model_file is not None:
            self._model_file.Dispose()
        self._model_file = None
        self._texture_file = None
        self._current_path = None
        self._modified_indexes.clear()
        self._ps3_header_state = None
        self._ps3_payload = None
        self._helper_mode = None
        self._xbox_texture_summaries = []
        self._xbox_descriptors = {}
        self._xbox_modified_payloads = {}
        self._xbox_thumbnail_png = {}
        self._xbox_preview_cache = {}
        self._xbox_revision = 0

    def open_model(self, path: str | Path) -> list[TextureSummary]:
        self.close()

        path = Path(path).resolve()
        if path.suffix.lower() == ".xdr":
            return self._open_xbox_model(path)

        model_file = self._runtime.ModelFile()
        try:
            model_file.Open(str(path))
        except Exception:
            model_file.Dispose()
            raise

        texture_file = model_file.EmbeddedTextureFile
        if texture_file is None or texture_file.Count == 0:
            model_file.Dispose()
            raise ValueError("No embedded textures were found in this drawable.")

        self._model_file = model_file
        self._texture_file = texture_file
        self._current_path = path
        self._modified_indexes.clear()
        self._ps3_header_state = None
        self._ps3_payload = None

        if self.get_platform_label() == "PS3":
            self._ps3_header_state = self._read_ps3_header_state(path)
            self._ps3_payload = self._decompress_ps3_resource_payload(path)
            self._repair_ps3_resource_from_zlib(path)

        return self.get_textures()

    def get_textures(self) -> list[TextureSummary]:
        if self._helper_mode == "xbox":
            return list(self._xbox_texture_summaries)
        self._ensure_model_loaded()
        return [self._summarize_texture(index) for index in range(self._texture_file.Count)]

    def get_texture(self, index: int) -> TextureSummary:
        if self._helper_mode == "xbox":
            if index < 0 or index >= len(self._xbox_texture_summaries):
                raise IndexError("Texture index is out of range.")
            return self._xbox_texture_summaries[index]
        self._ensure_model_loaded()
        return self._summarize_texture(index)

    def get_platform_label(self) -> str:
        if self._helper_mode == "xbox":
            return "Xbox"
        self._ensure_model_loaded()
        if self._model_file.IsBigEndian:
            return "PS3"

        resource_type = self._model_file.ResourceType
        if resource_type == self._runtime.ResourceType.ModelXBOX:
            return "Xbox"
        if resource_type in (self._runtime.ResourceType.Model, self._runtime.ResourceType.ModelFrag):
            return "PC"
        return "Unknown"

    def export_texture(self, index: int, target_path: str | Path) -> None:
        if self._helper_mode == "xbox":
            summary = self.get_texture(index)
            if summary.is_external_reference:
                raise ValueError(
                    "This entry is only an external texture reference. There is no embedded Xbox surface to export from this .xdr."
                )

            descriptor = self._xbox_descriptors[index]
            payload = self._get_xbox_texture_payload(index)
            export_dds(descriptor, payload, target_path)
            return

        texture = self._get_runtime_texture(index)
        if texture.IsExternalReference:
            raise ValueError(
                "This entry is only an external texture reference. There is no embedded Xbox surface to export from this .xdr."
            )

        descriptor = self._describe_texture(texture)
        export_dds(descriptor, bytes(bytearray(texture.TextureData)), target_path)

    def export_all(self, output_dir: str | Path) -> int:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported = 0
        if self._helper_mode == "xbox":
            for summary in self._xbox_texture_summaries:
                if summary.is_external_reference:
                    continue
                self.export_texture(summary.index, output_dir / f"{summary.title_name}.dds")
                exported += 1
        else:
            for index, texture in self._enumerate_textures():
                if texture.IsExternalReference:
                    continue
                self.export_texture(index, output_dir / f"{texture.TitleName}.dds")
                exported += 1
        return exported

    def import_texture(self, index: int, source_path: str | Path) -> None:
        if self._helper_mode == "xbox":
            summary = self.get_texture(index)
            if summary.is_external_reference:
                raise ValueError("External texture references cannot be replaced from this drawable.")

            descriptor = self._xbox_descriptors[index]
            payload = import_dds(descriptor, source_path)
            self._xbox_descriptors[index] = TextureDescriptor(
                width=descriptor.width,
                height=descriptor.height,
                levels=descriptor.levels,
                texture_type=descriptor.texture_type,
                data_size=len(payload),
                top_level_size=descriptor.top_level_size,
            )
            self._set_xbox_modified_payload(index, payload)
            self._modified_indexes.add(index)
            return

        texture = self._get_runtime_texture(index)
        if texture.IsExternalReference:
            raise ValueError("External texture references cannot be replaced from this drawable.")

        descriptor = self._describe_texture(texture)
        payload = import_dds(descriptor, source_path)
        self._replace_texture_data(texture, payload)
        self._modified_indexes.add(index)

    def save(self, target_path: str | Path | None = None) -> Path:
        if self._helper_mode != "xbox":
            self._ensure_model_loaded()

        target = Path(target_path).resolve() if target_path else self._current_path
        if target is None:
            raise ValueError("No drawable path is loaded.")

        blocked_message = self.get_save_blocker()
        if blocked_message:
            raise ValueError(blocked_message)

        if self._helper_mode == "xbox":
            self._save_xbox_with_helper(target)
        elif self.get_platform_label() == "PS3":
            self._save_ps3_with_zlib_level_9(target)
        else:
            self._model_file.Save(str(target))
        self._current_path = target
        self._modified_indexes.clear()
        return target

    def get_save_blocker(self) -> str | None:
        if self._helper_mode == "xbox":
            return None
        self._ensure_model_loaded()
        if self.get_platform_label() == "PS3":
            return None
        for index in self._modified_indexes:
            texture = self._get_runtime_texture(index)
            if texture.HasUnsupportedPs3WriteLayout:
                return (
                    "One or more modified PS3 textures use a wrapped storage layout that the tool still cannot "
                    "rebuild safely. Saving now would corrupt the file, so the operation was cancelled."
                )
            if texture.RequiresPs3ReferenceRepair:
                return (
                    "This modified PS3 texture uses a storage layout that the tool still cannot rebuild "
                    "safely. Saving was cancelled to avoid corrupting the file."
                )
        return None

    def get_preview_png_base64(self, index: int, mip_level: int = 0, channel: str = "all") -> str:
        if self._helper_mode == "xbox":
            return self._get_xbox_preview_png_base64(index, mip_level, channel)

        texture = self._get_runtime_texture(index)
        original_image = texture.Decode(mip_level)
        bitmap = self._ensure_bitmap(original_image)
        preview_bitmap = None

        try:
            preview_bitmap = self._clone_bitmap(bitmap)
            self._swap_red_blue_channels(preview_bitmap)
            if channel != "all":
                self._apply_channel_filter(preview_bitmap, channel)
            return self._bitmap_to_base64_png(preview_bitmap)
        finally:
            if preview_bitmap is not None:
                preview_bitmap.Dispose()
            if bitmap is not None and bitmap is not original_image:
                bitmap.Dispose()
            if original_image is not None:
                original_image.Dispose()

    def _summarize_texture(self, index: int) -> TextureSummary:
        texture = self._get_runtime_texture(index)
        return TextureSummary(
            index=index,
            name=str(texture.Name),
            title_name=self._normalize_texture_name(str(texture.Name)),
            width=int(texture.Width),
            height=int(texture.Height),
            levels=int(texture.Levels),
            texture_type=str(texture.TextureType),
            is_external_reference=bool(texture.IsExternalReference),
            requires_ps3_reference_repair=bool(texture.RequiresPs3ReferenceRepair),
            has_unsupported_ps3_write_layout=bool(texture.HasUnsupportedPs3WriteLayout),
        )

    def _describe_texture(self, texture) -> TextureDescriptor:
        return TextureDescriptor(
            width=int(texture.Width),
            height=int(texture.Height),
            levels=int(texture.Levels),
            texture_type=str(texture.TextureType),
            data_size=len(bytes(bytearray(texture.TextureData))),
            top_level_size=int(texture.GetTextureDataSize(0)),
        )

    @staticmethod
    def _normalize_texture_name(name: str) -> str:
        value = name or ""
        if value.lower().startswith("pack:/"):
            value = value[6:]
        if value.lower().endswith(".dds"):
            value = value[:-4]
        value = re.sub(r"\s+\[PS3 repaired\]$", "", value, flags=re.IGNORECASE)
        return value

    def _replace_texture_data(self, texture, payload: bytes) -> None:
        texture.ReplaceTextureData(self._runtime.ByteArray(payload))

    def get_thumbnail_png_base64(self, index: int) -> str:
        if self._helper_mode == "xbox":
            cached = self._xbox_thumbnail_png.get(index, "")
            if cached:
                return cached

            generated = self._run_xbox_helper(
                {
                    "command": "thumbnail",
                    "path": str(self._current_path),
                    "index": index,
                    "modifications": [
                        {"index": key, "payload_base64": base64.b64encode(value).decode("ascii")}
                        for key, value in sorted(self._get_xbox_modified_payloads().items())
                    ],
                }
            )
            if generated:
                self._xbox_thumbnail_png[index] = generated
            return generated
        return self.get_preview_png_base64(index, mip_level=0, channel="all")

    def _open_xbox_model(self, path: Path) -> list[TextureSummary]:
        payload = self._run_xbox_helper(
            {
                "command": "summaries",
                "path": str(path),
            },
            expect_json=True,
        )
        items = payload.get("textures", [])
        if not items:
            raise ValueError("No embedded textures were found in this drawable.")

        self._current_path = path
        self._helper_mode = "xbox"
        self._xbox_texture_summaries = []
        self._xbox_descriptors = {}
        self._xbox_thumbnail_png = {}
        self._xbox_preview_cache = {}
        self._xbox_modified_payloads = {}
        self._xbox_revision = 0
        self._modified_indexes.clear()

        for item in items:
            summary = TextureSummary(
                index=int(item["index"]),
                name=str(item["name"]),
                title_name=self._normalize_texture_name(str(item["name"])),
                width=int(item["width"]),
                height=int(item["height"]),
                levels=int(item["levels"]),
                texture_type=str(item["texture_type"]),
                is_external_reference=bool(item["is_external_reference"]),
                requires_ps3_reference_repair=False,
                has_unsupported_ps3_write_layout=False,
            )
            self._xbox_texture_summaries.append(summary)
            self._xbox_descriptors[summary.index] = TextureDescriptor(
                width=summary.width,
                height=summary.height,
                levels=summary.levels,
                texture_type=summary.texture_type,
                data_size=int(item["data_size"]),
                top_level_size=int(item["top_level_size"]),
            )
            thumbnail_base64 = str(item.get("thumbnail_png_base64", "") or "")
            if thumbnail_base64:
                self._xbox_thumbnail_png[summary.index] = thumbnail_base64

        return list(self._xbox_texture_summaries)

    def _set_xbox_modified_payload(self, index: int, payload: bytes) -> None:
        descriptor = self._xbox_descriptors[index]
        self._xbox_descriptors[index] = TextureDescriptor(
            width=descriptor.width,
            height=descriptor.height,
            levels=descriptor.levels,
            texture_type=descriptor.texture_type,
            data_size=len(payload),
            top_level_size=descriptor.top_level_size,
        )
        self._xbox_modified_payloads[index] = payload
        self._xbox_revision += 1
        self._xbox_preview_cache.clear()
        self._xbox_thumbnail_png.pop(index, None)
        try:
            preview = self._get_xbox_preview_png_base64(index, 0, "all")
            if preview:
                self._xbox_thumbnail_png[index] = preview
        except Exception:
            pass

    def _get_xbox_modified_payloads(self) -> dict[int, bytes]:
        return self._xbox_modified_payloads

    def _get_xbox_texture_payload(self, index: int) -> bytes:
        modified = self._get_xbox_modified_payloads()
        if index in modified:
            return modified[index]

        encoded = self._run_xbox_helper(
            {
                "command": "raw",
                "path": str(self._current_path),
                "index": index,
            }
        )
        if not encoded:
            raise ValueError("The Xbox texture payload could not be read.")
        return base64.b64decode(encoded)

    def _get_xbox_preview_png_base64(self, index: int, mip_level: int, channel: str) -> str:
        cache_key = (index, mip_level, channel, self._xbox_revision)
        cached = self._xbox_preview_cache.get(cache_key)
        if cached:
            return cached

        modified = [
            {"index": key, "payload_base64": base64.b64encode(value).decode("ascii")}
            for key, value in sorted(self._get_xbox_modified_payloads().items())
        ]
        preview = self._run_xbox_helper(
            {
                "command": "preview",
                "path": str(self._current_path),
                "index": index,
                "mip_level": mip_level,
                "channel": channel,
                "modifications": modified,
            }
        )
        self._xbox_preview_cache[cache_key] = preview
        return preview

    def _save_xbox_with_helper(self, target: Path) -> None:
        modified = [
            {"index": key, "payload_base64": base64.b64encode(value).decode("ascii")}
            for key, value in sorted(self._get_xbox_modified_payloads().items())
        ]
        self._run_xbox_helper(
            {
                "command": "save",
                "path": str(self._current_path),
                "target_path": str(target),
                "modifications": modified,
            }
        )
        self._current_path = target
        self._modified_indexes.clear()
        self._get_xbox_modified_payloads().clear()

    def _run_xbox_helper(self, request: dict[str, object], expect_json: bool = False):
        helper_exe = Path(r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
        if not helper_exe.exists():
            raise BackendUnavailableError("32-bit Windows PowerShell was not found, so Xbox .xdr files cannot be opened.")

        request = {
            "vendor_dir": str(self.vendor_dir),
            **request,
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(request, handle)
            request_path = handle.name

        try:
            completed = subprocess.run(
                [str(helper_exe), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", self._xbox_helper_script(request_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
                cwd=str(self.vendor_dir),
            )
        finally:
            try:
                os.unlink(request_path)
            except OSError:
                pass

        if completed.returncode != 0:
            error_output = (completed.stderr or completed.stdout or "").strip()
            raise ValueError(error_output or "The Xbox helper failed to process the .xdr file.")

        output = (completed.stdout or "").strip()
        if expect_json:
            return json.loads(output or "{}")
        return output

    @staticmethod
    def _xbox_helper_script(request_path: str) -> str:
        escaped_request_path = request_path.replace("'", "''")
        script = r"""
$ErrorActionPreference = 'Stop'
$requestPath = '__REQUEST_PATH__'
$request = Get-Content -Raw -LiteralPath $requestPath | ConvertFrom-Json
$vendor = [string]$request.vendor_dir
[Environment]::SetEnvironmentVariable('PATH', $vendor + ';' + [Environment]::GetEnvironmentVariable('PATH', 'Process'), 'Process')
[Reflection.Assembly]::LoadFrom((Join-Path $vendor 'RageLib.Common.dll')) | Out-Null
[Reflection.Assembly]::LoadFrom((Join-Path $vendor 'RageLib.Textures.dll')) | Out-Null
[Reflection.Assembly]::LoadFrom((Join-Path $vendor 'RageLib.Models.dll')) | Out-Null
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class XCompressNative
{
    public const int XMEMCODEC_LZX = 1;

    [StructLayout(LayoutKind.Sequential)]
    public struct XMEMCODEC_PARAMETERS_LZX
    {
        public UInt32 Flags;
        public UInt32 WindowSize;
        public UInt32 CompressionPartitionSize;
    }

    [DllImport("xcompress.dll", CallingConvention = CallingConvention.Winapi, ExactSpelling = true)]
    public static extern int XMemCreateCompressionContext(
        int codecType,
        ref XMEMCODEC_PARAMETERS_LZX codecParams,
        UInt32 flags,
        out IntPtr context
    );

    [DllImport("xcompress.dll", CallingConvention = CallingConvention.Winapi, ExactSpelling = true)]
    public static extern void XMemDestroyCompressionContext(IntPtr context);

    [DllImport("xcompress.dll", CallingConvention = CallingConvention.Winapi, ExactSpelling = true)]
    public static extern int XMemResetCompressionContext(IntPtr context);

    [DllImport("xcompress.dll", CallingConvention = CallingConvention.Winapi, ExactSpelling = true)]
    public static extern int XMemCompress(
        IntPtr context,
        byte[] destination,
        ref UInt32 destSize,
        byte[] source,
        UInt32 srcSize
    );
}

public static class XboxSurfaceUtil
{
    public static byte[] BuildStoredTopLevel(byte[] linearData, int width, int height, string format, bool isTiled, int endianMode)
    {
        int expectedLinearSize = GetLinearTopLevelSize(width, height, format);
        if (linearData == null || linearData.Length != expectedLinearSize)
        {
            throw new ArgumentException("The imported DDS payload size does not match the expected Xbox top-level size.");
        }

        int texelPitch = GetTexelPitch(format);
        int internalWidth = Math.Max(128, width);
        int internalHeight = Math.Max(128, height);
        int targetBlockWidth = width / 4;
        int targetBlockHeight = height / 4;
        int internalBlockWidth = internalWidth / 4;
        int internalBlockHeight = internalHeight / 4;

        byte[] linearSurface = new byte[GetStoredSurfaceSize(width, height, format)];
        for (int y = 0; y < targetBlockHeight; y++)
        {
            Buffer.BlockCopy(
                linearData,
                y * targetBlockWidth * texelPitch,
                linearSurface,
                y * internalBlockWidth * texelPitch,
                targetBlockWidth * texelPitch);
        }

        byte[] stored;
        if (isTiled)
        {
            stored = new byte[linearSurface.Length];
            for (int y = 0; y < internalBlockHeight; y++)
            {
                for (int x = 0; x < internalBlockWidth; x++)
                {
                    int sourceIndex = ((y * internalBlockWidth) + x) * texelPitch;
                    int targetBlock = XGAddress2DTiledOffset(x, y, internalBlockWidth, texelPitch);
                    Buffer.BlockCopy(linearSurface, sourceIndex, stored, targetBlock * texelPitch, texelPitch);
                }
            }
        }
        else
        {
            stored = linearSurface;
        }

        ApplyEndian(stored, endianMode);
        return stored;
    }

    private static int GetTexelPitch(string format)
    {
        switch (format)
        {
            case "DXT1":
                return 8;
            case "DXT3":
            case "DXT5":
                return 16;
            default:
                throw new NotSupportedException("Unsupported Xbox texture format for save: " + format);
        }
    }

    private static int GetLinearTopLevelSize(int width, int height, string format)
    {
        switch (format)
        {
            case "DXT1":
                return (width * height) / 2;
            case "DXT3":
            case "DXT5":
                return width * height;
            default:
                throw new NotSupportedException("Unsupported Xbox texture format for save: " + format);
        }
    }

    private static int GetStoredSurfaceSize(int width, int height, string format)
    {
        int texelPitch = GetTexelPitch(format);
        int internalWidth = Math.Max(128, width);
        int internalHeight = Math.Max(128, height);
        return (internalWidth / 4) * (internalHeight / 4) * texelPitch;
    }

    private static void ApplyEndian(byte[] data, int endianMode)
    {
        int stride;
        switch (endianMode)
        {
            case 0:
                return;
            case 1:
                stride = 2;
                break;
            case 2:
            case 3:
                stride = 4;
                break;
            default:
                return;
        }

        for (int i = 0; i + stride <= data.Length; i += stride)
        {
            Array.Reverse(data, i, stride);
        }
    }

    private static int XGAddress2DTiledOffset(int x, int y, int widthInBlocks, int texelPitch)
    {
        int alignedWidth = (widthInBlocks + 31) & ~31;
        int logBpp = (texelPitch >> 2) + (((texelPitch >> 1) >> (texelPitch >> 2)));
        int macro = ((x >> 5) + (y >> 5) * (alignedWidth >> 5)) << (logBpp + 7);
        int micro = ((x & 7) + ((y & 6) << 2)) << logBpp;
        int offset = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + logBpp)) + ((y & 1) << 4);
        return (((offset & ~511) << 3) + ((offset & 448) << 2) + (offset & 63) + ((y & 16) << 7) + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> logBpp;
    }
}
"@

function Open-Model([string]$path) {
    $model = New-Object RageLib.Models.ModelFile
    $model.Open($path)
    return $model
}

function Apply-Modifications($model, $mods) {
    if ($null -eq $mods) { return }
    foreach ($mod in @($mods)) {
        if ($null -eq $mod) { continue }
        $index = [int]$mod.index
        $bytes = [Convert]::FromBase64String([string]$mod.payload_base64)
        $model.EmbeddedTextureFile.Textures[$index].ReplaceTextureData($bytes)
    }
}

function Assert-HResult([int]$result, [string]$message) {
    if ($result -lt 0) {
        $code = [uint32]$result
        throw ("{0} (HRESULT 0x{1:X8})" -f $message, $code)
    }
}

function Write-BigEndianUInt32($stream, [uint32]$value) {
    $bytes = [BitConverter]::GetBytes($value)
    [Array]::Reverse($bytes)
    $stream.Write($bytes, 0, $bytes.Length)
}

function Bitmap-ToPngBase64([System.Drawing.Image]$image) {
    $stream = New-Object System.IO.MemoryStream
    try {
        $image.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return [Convert]::ToBase64String($stream.ToArray())
    }
    finally {
        $stream.Dispose()
    }
}

function Normalize-PreviewBitmap([System.Drawing.Bitmap]$bitmap) {
    for ($y = 0; $y -lt $bitmap.Height; $y++) {
        for ($x = 0; $x -lt $bitmap.Width; $x++) {
            $pixel = $bitmap.GetPixel($x, $y)
            $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($pixel.A, $pixel.B, $pixel.G, $pixel.R))
        }
    }
    return $bitmap
}

function Compress-XboxLzxPayload([byte[]]$payload) {
    if ($null -eq $payload -or $payload.Length -eq 0) {
        throw 'The Xbox resource payload is empty.'
    }

    $params = New-Object XCompressNative+XMEMCODEC_PARAMETERS_LZX
    $params.Flags = 0
    $params.WindowSize = 131072
    $params.CompressionPartitionSize = 0

    $context = [IntPtr]::Zero
    Assert-HResult (
        [XCompressNative]::XMemCreateCompressionContext(
            [XCompressNative]::XMEMCODEC_LZX,
            [ref]$params,
            0,
            [ref]$context
        )
    ) 'Could not create the Xbox LZX compression context.'

    try {
        Assert-HResult ([XCompressNative]::XMemResetCompressionContext($context)) 'Could not reset the Xbox LZX compression context.'

        $capacity = [Math]::Max(($payload.Length * 2) + 4096, 65536)
        $compressed = New-Object byte[] $capacity
        $compressedSize = [uint32]$compressed.Length
        Assert-HResult (
            [XCompressNative]::XMemCompress(
                $context,
                $compressed,
                [ref]$compressedSize,
                $payload,
                [uint32]$payload.Length
            )
        ) 'Could not compress the Xbox resource payload with LZX.'

        if ($compressedSize -eq 0) {
            throw 'Xbox LZX compression returned an empty payload.'
        }

        $result = New-Object byte[] ([int]$compressedSize)
        [Array]::Copy($compressed, 0, $result, 0, [int]$compressedSize)
        return $result
    }
    finally {
        if ($context -ne [IntPtr]::Zero) {
            [XCompressNative]::XMemDestroyCompressionContext($context)
        }
    }
}

function Save-XboxModel($model, [string]$sourcePath, [string]$targetPath) {
    $resourceField = $model.GetType().GetField('_resourceFile', [Reflection.BindingFlags]'Instance, NonPublic')
    if ($null -eq $resourceField) {
        throw 'Could not access the Xbox resource stream from RageLib.'
    }

    $resource = $resourceField.GetValue($model)
    if ($null -eq $resource) {
        throw 'The loaded Xbox resource is not available.'
    }

    $originalSourceBytes = [System.IO.File]::ReadAllBytes($sourcePath)
    if ($originalSourceBytes.Length -lt 14) {
        throw 'The source Xbox resource is too small to contain a valid resource header.'
    }

    $header = New-Object byte[] 14
    [Array]::Copy($originalSourceBytes, 0, $header, 0, 14)

    $systemBytes = New-Object byte[] $resource.SystemMemData.Length
    [Array]::Copy($resource.SystemMemData, 0, $systemBytes, 0, $systemBytes.Length)
    $graphicsBytes = New-Object byte[] $resource.GraphicsMemData.Length
    [Array]::Copy($resource.GraphicsMemData, 0, $graphicsBytes, 0, $graphicsBytes.Length)

    Apply-XboxTextureModifications $model $graphicsBytes $request.modifications

    $payload = New-Object byte[] ($systemBytes.Length + $graphicsBytes.Length)
    [Array]::Copy($systemBytes, 0, $payload, 0, $systemBytes.Length)
    [Array]::Copy($graphicsBytes, 0, $payload, $systemBytes.Length, $graphicsBytes.Length)

    $compressed = Compress-XboxLzxPayload $payload

    $output = New-Object System.IO.MemoryStream
    try {
        $output.Write($header, 0, $header.Length)
        $output.WriteByte(0x12)
        $output.WriteByte(0xEF)
        Write-BigEndianUInt32 $output ([uint32]$compressed.Length)
        $output.Write($compressed, 0, $compressed.Length)
        [System.IO.File]::WriteAllBytes($targetPath, $output.ToArray())
    }
    finally {
        $output.Dispose()
    }
}

function Get-TextureInfoObject($texture) {
    $prop = $texture.GetType().GetProperty('Info', [Reflection.BindingFlags]'Instance, NonPublic')
    if ($null -eq $prop) {
        throw 'Could not access Xbox texture metadata.'
    }
    return $prop.GetValue($texture, $null)
}

function Get-TextureInfoValue($info, [string]$name) {
    $flags = [Reflection.BindingFlags]'Instance, NonPublic, Public'
    $field = $info.GetType().GetField($name, $flags)
    if ($null -ne $field) {
        return $field.GetValue($info)
    }

    $backingField = $info.GetType().GetField(('<{0}>k__BackingField' -f $name), $flags)
    if ($null -ne $backingField) {
        return $backingField.GetValue($info)
    }

    $prop = $info.GetType().GetProperty($name, $flags)
    if ($null -ne $prop) {
        return $prop.GetValue($info, $null)
    }

    throw ("Could not read Xbox texture metadata field '{0}'." -f $name)
}

function Apply-XboxTextureModifications($model, [byte[]]$graphicsBytes, $mods) {
    if ($null -eq $mods) {
        return
    }

    foreach ($mod in @($mods)) {
        if ($null -eq $mod) {
            continue
        }

        $index = [int]$mod.index
        $payload = [Convert]::FromBase64String([string]$mod.payload_base64)
        $texture = $model.EmbeddedTextureFile.Textures[$index]
        if ($texture.IsExternalReference) {
            continue
        }

        $info = Get-TextureInfoObject $texture
        $rawDataOffset = [int](Get-TextureInfoValue $info 'RawDataOffset')
        $width = [int](Get-TextureInfoValue $info 'Width')
        $height = [int](Get-TextureInfoValue $info 'Height')
        $format = [string](Get-TextureInfoValue $info 'Format')
        $endianMode = [int](Get-TextureInfoValue $info 'XboxEndianMode')
        $isTiled = [bool](Get-TextureInfoValue $info 'XboxIsTiled')

        $storedSurface = [XboxSurfaceUtil]::BuildStoredTopLevel($payload, $width, $height, $format, $isTiled, $endianMode)
        if ($rawDataOffset -lt 0 -or ($rawDataOffset + $storedSurface.Length) -gt $graphicsBytes.Length) {
            throw ("The Xbox texture surface at index {0} does not fit inside graphics memory." -f $index)
        }

        [Array]::Copy($storedSurface, 0, $graphicsBytes, $rawDataOffset, $storedSurface.Length)
    }
}

function Convert-Channel([System.Drawing.Bitmap]$bitmap, [string]$channel) {
    if ($channel -eq 'all') { return $bitmap }
    for ($y = 0; $y -lt $bitmap.Height; $y++) {
        for ($x = 0; $x -lt $bitmap.Width; $x++) {
            $pixel = $bitmap.GetPixel($x, $y)
            switch ($channel) {
                'red'   { $value = $pixel.R; break }
                'green' { $value = $pixel.G; break }
                'blue'  { $value = $pixel.B; break }
                'alpha' { $value = $pixel.A; break }
                default { $value = $pixel.R; break }
            }
            $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, $value, $value, $value))
        }
    }
    return $bitmap
}

$model = Open-Model([string]$request.path)
try {
    if ([string]$request.command -ne 'save') {
        Apply-Modifications $model $request.modifications
    }

    switch ([string]$request.command) {
        'summaries' {
            $items = @()
            for ($index = 0; $index -lt $model.EmbeddedTextureFile.Count; $index++) {
                $texture = $model.EmbeddedTextureFile.Textures[$index]
                $items += [ordered]@{
                    index = $index
                    name = [string]$texture.Name
                    width = [int]$texture.Width
                    height = [int]$texture.Height
                    levels = [int]$texture.Levels
                    texture_type = [string]$texture.TextureType
                    is_external_reference = [bool]$texture.IsExternalReference
                    data_size = [int]$texture.TextureData.Length
                    top_level_size = [int]$texture.GetTextureDataSize(0)
                    thumbnail_png_base64 = ''
                }
                if (-not $texture.IsExternalReference) {
                    $thumbnailImage = $texture.DecodeAsThumbnail()
                    $thumbnail = New-Object System.Drawing.Bitmap($thumbnailImage)
                    try {
                        $thumbnail = Normalize-PreviewBitmap $thumbnail
                        $items[$items.Count - 1].thumbnail_png_base64 = Bitmap-ToPngBase64 $thumbnail
                    }
                    finally {
                        $thumbnail.Dispose()
                        $thumbnailImage.Dispose()
                    }
                }
            }
            [Console]::Out.Write((@{ textures = $items } | ConvertTo-Json -Compress -Depth 5))
        }
        'raw' {
            $texture = $model.EmbeddedTextureFile.Textures[[int]$request.index]
            [Console]::Out.Write([Convert]::ToBase64String($texture.TextureData))
        }
        'preview' {
            $texture = $model.EmbeddedTextureFile.Textures[[int]$request.index]
            $image = $texture.Decode([int]$request.mip_level)
            $bitmap = New-Object System.Drawing.Bitmap($image)
            try {
                $bitmap = Normalize-PreviewBitmap $bitmap
                $bitmap = Convert-Channel $bitmap ([string]$request.channel)
                [Console]::Out.Write((Bitmap-ToPngBase64 $bitmap))
            }
            finally {
                $bitmap.Dispose()
                $image.Dispose()
            }
        }
        'thumbnail' {
            $texture = $model.EmbeddedTextureFile.Textures[[int]$request.index]
            $image = $texture.DecodeAsThumbnail()
            $bitmap = New-Object System.Drawing.Bitmap($image)
            try {
                $bitmap = Normalize-PreviewBitmap $bitmap
                [Console]::Out.Write((Bitmap-ToPngBase64 $bitmap))
            }
            finally {
                $bitmap.Dispose()
                $image.Dispose()
            }
        }
        'save' {
            Save-XboxModel $model ([string]$request.path) ([string]$request.target_path)
            [Console]::Out.Write('OK')
        }
        default {
            throw "Unsupported Xbox helper command: $($request.command)"
        }
    }
}
finally {
    $model.Dispose()
}
"""
        return script.replace("__REQUEST_PATH__", escaped_request_path)

    def _enumerate_textures(self) -> Iterable[tuple[int, object]]:
        self._ensure_model_loaded()
        for index in range(self._texture_file.Count):
            yield index, self._texture_file.Textures[index]

    def _get_runtime_texture(self, index: int):
        self._ensure_model_loaded()
        if index < 0 or index >= self._texture_file.Count:
            raise IndexError("Texture index is out of range.")
        return self._texture_file.Textures[index]

    def _ensure_model_loaded(self) -> None:
        if self._model_file is None or self._texture_file is None:
            raise ValueError("No drawable resource is loaded.")

    def _get_private_field(self, target, name: str):
        field = target.GetType().GetField(name, self._runtime.BindingFlags.Instance | self._runtime.BindingFlags.NonPublic)
        if field is None:
            raise AttributeError(f"Could not find private field {name!r} on {target.GetType().FullName}.")
        return field.GetValue(target)

    def _set_private_field(self, target, name: str, value) -> None:
        field = target.GetType().GetField(name, self._runtime.BindingFlags.Instance | self._runtime.BindingFlags.NonPublic)
        if field is None:
            raise AttributeError(f"Could not find private field {name!r} on {target.GetType().FullName}.")
        field.SetValue(target, value)

    def _get_member_value(self, target, name: str):
        member_flags = (
            self._runtime.BindingFlags.Instance
            | self._runtime.BindingFlags.Public
            | self._runtime.BindingFlags.NonPublic
        )
        prop = target.GetType().GetProperty(name, member_flags)
        if prop is not None:
            return prop.GetValue(target, None)

        field = target.GetType().GetField(name, member_flags)
        if field is not None:
            return field.GetValue(target)

        raise AttributeError(f"Could not find member {name!r} on {target.GetType().FullName}.")

    def _read_ps3_header_state(self, path: Path) -> dict[str, int | bytes]:
        raw = path.read_bytes()
        if len(raw) < 12:
            raise ValueError("The PS3 drawable is too small to contain a valid resource header.")

        flags = int.from_bytes(raw[8:12], "big")
        return {
            "file_header": raw[:12],
            "header_prefix": raw[:8],
            "flags": flags,
            "system_size": self._decode_system_mem_size(flags),
            "graphics_size": self._decode_graphics_mem_size(flags),
        }

    def _decode_system_mem_size(self, flags: int) -> int:
        return (flags & 0x7FF) << (((flags >> 11) & 0xF) + 8)

    def _decode_graphics_mem_size(self, flags: int) -> int:
        return ((flags >> 15) & 0x7FF) << (((flags >> 26) & 0xF) + 8)

    def _encode_ps3_flags(self, system_size: int, graphics_size: int, base_flags: int) -> int:
        def encode_size(size: int) -> tuple[int, int]:
            a = size >> 8
            b = 0
            while a > 0x7FF:
                if (a & 1) != 0:
                    a += 2
                a >>= 1
                b += 1
            return a, b

        sys_a, sys_b = encode_size(system_size)
        gfx_a, gfx_b = encode_size(graphics_size)
        return (base_flags & 0xC0000000) | sys_a | (sys_b << 11) | (gfx_a << 15) | (gfx_b << 26)

    def _decompress_ps3_resource_payload(self, path: Path) -> bytes:
        raw = path.read_bytes()
        if len(raw) < 14:
            raise ValueError("The PS3 drawable is too small to contain compressed resource data.")

        try:
            return zlib.decompress(raw[12:])
        except zlib.error:
            try:
                return zlib.decompress(raw[14:], -zlib.MAX_WBITS)
            except zlib.error as exc:
                raise ValueError(
                    "Could not decompress the PS3 resource using the expected ZLIB settings (offset 12 / level 9 layout)."
                ) from exc

    def _create_memory_stream(self, payload: bytes):
        stream = self._runtime.MemoryStream()
        stream.Write(self._runtime.ByteArray(payload), 0, len(payload))
        stream.Position = 0
        return stream

    def _reopen_model_from_ps3_payload(self, header_state: dict[str, int | bytes], system_data: bytes, graphics_data: bytes):
        flags = self._encode_ps3_flags(len(system_data), len(graphics_data), int(header_state["flags"]))
        resource_bytes = bytes(header_state["header_prefix"]) + struct.pack(">I", flags) + zlib.compress(system_data + graphics_data, 9)
        stream = self._create_memory_stream(resource_bytes)
        model_file = self._runtime.ModelFile()

        try:
            model_file.Open(stream)
            return model_file, flags
        finally:
            stream.Dispose()

    def _repair_ps3_resource_from_zlib(self, path: Path) -> None:
        self._ensure_model_loaded()
        header_state = self._ps3_header_state or self._read_ps3_header_state(path)
        payload = self._decompress_ps3_resource_payload(path)

        system_size = int(header_state["system_size"])
        declared_graphics_size = int(header_state["graphics_size"])
        if len(payload) < system_size:
            raise ValueError("The PS3 ZLIB payload is smaller than the declared system-memory block.")

        system_data = payload[:system_size]
        graphics_data = payload[system_size:]
        if not graphics_data and declared_graphics_size > 0:
            return

        current_resource = self._get_private_field(self._model_file, "_resourceFile")
        current_graphics_data = bytes(bytearray(current_resource.GraphicsMemData))
        if graphics_data == current_graphics_data:
            return

        current_model = self._model_file
        try:
            repaired_model, updated_flags = self._reopen_model_from_ps3_payload(header_state, system_data, graphics_data)
        except Exception:
            return

        self._model_file = repaired_model
        self._texture_file = repaired_model.EmbeddedTextureFile
        current_model.Dispose()

        self._ps3_header_state = {
            "file_header": header_state["file_header"],
            "header_prefix": header_state["header_prefix"],
            "flags": int(header_state["flags"]),
            "system_size": len(system_data),
            "graphics_size": len(graphics_data),
        }
        self._ps3_payload = system_data + graphics_data

    def _get_ps3_texture_info(self, texture):
        return self._get_member_value(texture, "Info")

    def _get_ps3_raw_data_offset(self, texture) -> int:
        info = self._get_ps3_texture_info(texture)
        return int(self._get_member_value(info, "RawDataOffset"))

    def _save_ps3_with_zlib_level_9(self, target: Path) -> None:
        resource = self._get_private_field(self._model_file, "_resourceFile")
        system_bytes = bytes(bytearray(resource.SystemMemData))
        header_state = self._ps3_header_state or self._read_ps3_header_state(self._current_path)
        payload = self._ps3_payload or (system_bytes + bytes(bytearray(resource.GraphicsMemData)))
        stored_system_size = int(header_state["system_size"])
        if len(payload) < stored_system_size:
            payload = system_bytes

        graphics_data = bytearray(payload[stored_system_size:])

        for index in sorted(self._modified_indexes):
            texture = self._get_runtime_texture(index)
            texture_data = bytes(bytearray(texture.TextureData))
            raw_offset = self._get_ps3_raw_data_offset(texture)
            required_size = raw_offset + len(texture_data)
            if required_size > len(graphics_data):
                graphics_data.extend(b"\x00" * (required_size - len(graphics_data)))
            graphics_data[raw_offset:required_size] = texture_data

        payload = system_bytes + bytes(graphics_data)
        resource.SystemMemData = self._runtime.ByteArray(system_bytes)
        resource.GraphicsMemData = self._runtime.ByteArray(bytes(graphics_data))

        compressed_payload = zlib.compress(payload, 9)
        original_header = bytes(header_state["file_header"])
        target.write_bytes(original_header + compressed_payload)

        self._ps3_header_state = {
            "file_header": header_state["file_header"],
            "header_prefix": header_state["header_prefix"],
            "flags": int(header_state["flags"]),
            "system_size": len(system_bytes),
            "graphics_size": len(graphics_data),
        }
        self._ps3_payload = payload

    def _load_runtime(self):
        if not self.vendor_dir.exists():
            raise BackendUnavailableError(f"Vendor directory not found: {self.vendor_dir}")

        try:
            import clr
        except Exception as exc:
            raise BackendUnavailableError(
                "pythonnet is required to run the Python version of the tool. Install it with "
                "`pip install pythonnet` after installing Python 3."
            ) from exc

        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(self.vendor_dir))

        vendor_path = str(self.vendor_dir)
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)

        clr.AddReference(str(self.vendor_dir / "RageLib.Common.dll"))
        clr.AddReference(str(self.vendor_dir / "RageLib.Textures.dll"))
        clr.AddReference(str(self.vendor_dir / "RageLib.Models.dll"))
        clr.AddReference("System.Drawing")

        from System import Array, Byte
        from System.Drawing import Bitmap, Rectangle
        from System.Drawing.Imaging import ImageFormat, ImageLockMode, PixelFormat
        from System.IO import MemoryStream
        from System.Reflection import BindingFlags
        from System.Runtime.InteropServices import Marshal
        from RageLib.Common.Resources import ResourceType
        from RageLib.Models import ModelFile

        return SimpleNamespace(
            BindingFlags=BindingFlags,
            ByteArray=lambda data: Array[Byte](list(data)),
            Bitmap=Bitmap,
            Rectangle=Rectangle,
            ImageFormat=ImageFormat,
            ImageLockMode=ImageLockMode,
            MemoryStream=MemoryStream,
            Marshal=Marshal,
            ModelFile=ModelFile,
            PixelFormat=PixelFormat,
            ResourceType=ResourceType,
            SystemArray=Array,
            SystemByte=Byte,
        )

    def _ensure_bitmap(self, image):
        bitmap_type = self._runtime.Bitmap
        return image if isinstance(image, bitmap_type) else bitmap_type(image)

    def _clone_bitmap(self, image):
        return self._runtime.Bitmap(image)

    def _bitmap_to_base64_png(self, bitmap) -> str:
        stream = self._runtime.MemoryStream()
        try:
            bitmap.Save(stream, self._runtime.ImageFormat.Png)
            raw = bytes(bytearray(stream.ToArray()))
        finally:
            stream.Dispose()
        return base64.b64encode(raw).decode("ascii")

    def _apply_channel_filter(self, bitmap, channel: str) -> None:
        masks = {
            "red": (0x00FF0000, 16),
            "green": (0x0000FF00, 8),
            "blue": (0x000000FF, 0),
            "alpha": (0xFF000000, 24),
        }
        if channel not in masks:
            raise ValueError(f"Unsupported image channel: {channel}")

        mask, shift = masks[channel]
        rect = self._runtime.Rectangle(0, 0, bitmap.Width, bitmap.Height)
        bitmap_data = bitmap.LockBits(
            rect,
            self._runtime.ImageLockMode.ReadWrite,
            self._runtime.PixelFormat.Format32bppArgb,
        )

        try:
            total_bytes = abs(bitmap_data.Stride) * bitmap.Height
            managed = self._runtime.SystemArray.CreateInstance(self._runtime.SystemByte, total_bytes)
            self._runtime.Marshal.Copy(bitmap_data.Scan0, managed, 0, total_bytes)
            buffer = bytearray(list(managed))
            stride = abs(bitmap_data.Stride)

            for y in range(bitmap.Height):
                row_start = y * stride
                for x in range(bitmap.Width):
                    offset = row_start + (x * 4)
                    pixel = (
                        buffer[offset]
                        | (buffer[offset + 1] << 8)
                        | (buffer[offset + 2] << 16)
                        | (buffer[offset + 3] << 24)
                    )
                    value = (pixel & mask) >> shift
                    buffer[offset + 0] = value
                    buffer[offset + 1] = value
                    buffer[offset + 2] = value
                    buffer[offset + 3] = 255

            self._runtime.Marshal.Copy(self._runtime.ByteArray(bytes(buffer)), 0, bitmap_data.Scan0, total_bytes)
        finally:
            bitmap.UnlockBits(bitmap_data)

    def _swap_red_blue_channels(self, bitmap) -> None:
        rect = self._runtime.Rectangle(0, 0, bitmap.Width, bitmap.Height)
        bitmap_data = bitmap.LockBits(
            rect,
            self._runtime.ImageLockMode.ReadWrite,
            self._runtime.PixelFormat.Format32bppArgb,
        )

        try:
            total_bytes = abs(bitmap_data.Stride) * bitmap.Height
            managed = self._runtime.SystemArray.CreateInstance(self._runtime.SystemByte, total_bytes)
            self._runtime.Marshal.Copy(bitmap_data.Scan0, managed, 0, total_bytes)
            buffer = bytearray(list(managed))
            stride = abs(bitmap_data.Stride)

            for y in range(bitmap.Height):
                row_start = y * stride
                for x in range(bitmap.Width):
                    offset = row_start + (x * 4)
                    buffer[offset + 0], buffer[offset + 2] = buffer[offset + 2], buffer[offset + 0]

            self._runtime.Marshal.Copy(self._runtime.ByteArray(bytes(buffer)), 0, bitmap_data.Scan0, total_bytes)
        finally:
            bitmap.UnlockBits(bitmap_data)
