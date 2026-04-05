using System;
using System.IO;
using RageLib.Textures.Resource;

namespace RageLib.Textures
{
    public static class DdsCodec
    {
        private const uint DdsMagic = 0x20534444;
        private const uint DdsdCaps = 0x00000001;
        private const uint DdsdHeight = 0x00000002;
        private const uint DdsdWidth = 0x00000004;
        private const uint DdsdPitch = 0x00000008;
        private const uint DdsdPixelFormat = 0x00001000;
        private const uint DdsdMipmapCount = 0x00020000;
        private const uint DdsdLinearSize = 0x00080000;
        private const uint DdpfAlphaPixels = 0x00000001;
        private const uint DdpfFourCc = 0x00000004;
        private const uint DdpfRgb = 0x00000040;
        private const uint DdpfLuminance = 0x00020000;
        private const uint DdpfBumpDuDv = 0x00080000;
        private const uint DdscapsComplex = 0x00000008;
        private const uint DdscapsTexture = 0x00001000;
        private const uint DdscapsMipmap = 0x00400000;

        private static readonly uint FourCcDxt1 = MakeFourCc('D', 'X', 'T', '1');
        private static readonly uint FourCcDxt3 = MakeFourCc('D', 'X', 'T', '3');
        private static readonly uint FourCcDxt5 = MakeFourCc('D', 'X', 'T', '5');

        public static void Export(Texture texture, string path)
        {
            using (var stream = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None))
            using (var writer = new BinaryWriter(stream))
            {
                WriteHeader(writer, texture);
                writer.Write(texture.TextureData, 0, GetTotalDataSize(texture));
            }
        }

        public static void Import(Texture texture, string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var reader = new BinaryReader(stream))
            {
                ValidateHeader(reader, texture);

                int expectedSize = GetTotalDataSize(texture);
                int remainingSize = (int)(stream.Length - stream.Position);
                if (remainingSize != expectedSize)
                {
                    throw new InvalidDataException(string.Format(
                        "DDS payload size mismatch. Expected {0} bytes but found {1}. Save the DDS with the original format, dimensions, and mipmaps.",
                        expectedSize, remainingSize));
                }

                texture.ReplaceTextureData(reader.ReadBytes(expectedSize));
            }
        }

        private static void WriteHeader(BinaryWriter writer, Texture texture)
        {
            writer.Write(DdsMagic);
            writer.Write(124u);

            uint flags = DdsdCaps | DdsdHeight | DdsdWidth | DdsdPixelFormat;
            uint pitchOrLinearSize;
            uint pixelFormatFlags;
            uint fourCc = 0;
            uint bitCount = 0;
            uint redMask = 0;
            uint greenMask = 0;
            uint blueMask = 0;
            uint alphaMask = 0;

            switch (texture.TextureType)
            {
                case TextureType.DXT1:
                    flags |= DdsdLinearSize;
                    pitchOrLinearSize = texture.GetTextureDataSize(0);
                    pixelFormatFlags = DdpfFourCc;
                    fourCc = FourCcDxt1;
                    break;
                case TextureType.DXT3:
                    flags |= DdsdLinearSize;
                    pitchOrLinearSize = texture.GetTextureDataSize(0);
                    pixelFormatFlags = DdpfFourCc;
                    fourCc = FourCcDxt3;
                    break;
                case TextureType.DXT5:
                    flags |= DdsdLinearSize;
                    pitchOrLinearSize = texture.GetTextureDataSize(0);
                    pixelFormatFlags = DdpfFourCc;
                    fourCc = FourCcDxt5;
                    break;
                case TextureType.A8R8G8B8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 4;
                    pixelFormatFlags = DdpfRgb | DdpfAlphaPixels;
                    bitCount = 32;
                    redMask = 0x00FF0000;
                    greenMask = 0x0000FF00;
                    blueMask = 0x000000FF;
                    alphaMask = 0xFF000000;
                    break;
                case TextureType.X8R8G8B8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 4;
                    pixelFormatFlags = DdpfRgb;
                    bitCount = 32;
                    redMask = 0x00FF0000;
                    greenMask = 0x0000FF00;
                    blueMask = 0x000000FF;
                    break;
                case TextureType.R8G8B8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 3;
                    pixelFormatFlags = DdpfRgb;
                    bitCount = 24;
                    redMask = 0x00FF0000;
                    greenMask = 0x0000FF00;
                    blueMask = 0x000000FF;
                    break;
                case TextureType.R5G6B5:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 2;
                    pixelFormatFlags = DdpfRgb;
                    bitCount = 16;
                    redMask = 0x0000F800;
                    greenMask = 0x000007E0;
                    blueMask = 0x0000001F;
                    break;
                case TextureType.A1R5G5B5:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 2;
                    pixelFormatFlags = DdpfRgb | DdpfAlphaPixels;
                    bitCount = 16;
                    redMask = 0x00007C00;
                    greenMask = 0x000003E0;
                    blueMask = 0x0000001F;
                    alphaMask = 0x00008000;
                    break;
                case TextureType.A4R4G4B4:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 2;
                    pixelFormatFlags = DdpfRgb | DdpfAlphaPixels;
                    bitCount = 16;
                    redMask = 0x00000F00;
                    greenMask = 0x000000F0;
                    blueMask = 0x0000000F;
                    alphaMask = 0x0000F000;
                    break;
                case TextureType.A8L8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 2;
                    pixelFormatFlags = DdpfLuminance | DdpfAlphaPixels;
                    bitCount = 16;
                    redMask = 0x000000FF;
                    alphaMask = 0x0000FF00;
                    break;
                case TextureType.V8U8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width * 2;
                    pixelFormatFlags = DdpfBumpDuDv;
                    bitCount = 16;
                    redMask = 0x000000FF;
                    greenMask = 0x0000FF00;
                    break;
                case TextureType.L8:
                    flags |= DdsdPitch;
                    pitchOrLinearSize = texture.Width;
                    pixelFormatFlags = DdpfLuminance;
                    bitCount = 8;
                    redMask = 0x000000FF;
                    break;
                default:
                    throw new InvalidOperationException("Unsupported texture type for DDS export.");
            }

            if (texture.Levels > 1)
            {
                flags |= DdsdMipmapCount;
            }

            writer.Write(flags);
            writer.Write(texture.Height);
            writer.Write(texture.Width);
            writer.Write(pitchOrLinearSize);
            writer.Write(0u);
            writer.Write((uint)texture.Levels);

            for (int i = 0; i < 11; i++)
            {
                writer.Write(0u);
            }

            writer.Write(32u);
            writer.Write(pixelFormatFlags);
            writer.Write(fourCc);
            writer.Write(bitCount);
            writer.Write(redMask);
            writer.Write(greenMask);
            writer.Write(blueMask);
            writer.Write(alphaMask);

            uint caps = DdscapsTexture;
            if (texture.Levels > 1)
            {
                caps |= DdscapsComplex | DdscapsMipmap;
            }

            writer.Write(caps);
            writer.Write(0u);
            writer.Write(0u);
            writer.Write(0u);
            writer.Write(0u);
        }

        private static void ValidateHeader(BinaryReader reader, Texture texture)
        {
            if (reader.ReadUInt32() != DdsMagic)
            {
                throw new InvalidDataException("The selected file is not a DDS texture.");
            }

            if (reader.ReadUInt32() != 124)
            {
                throw new InvalidDataException("Unsupported DDS header size.");
            }

            uint flags = reader.ReadUInt32();
            uint height = reader.ReadUInt32();
            uint width = reader.ReadUInt32();
            reader.ReadUInt32();
            reader.ReadUInt32();
            uint mipMapCount = reader.ReadUInt32();

            for (int i = 0; i < 11; i++)
            {
                reader.ReadUInt32();
            }

            uint pixelFormatSize = reader.ReadUInt32();
            uint pixelFormatFlags = reader.ReadUInt32();
            uint fourCc = reader.ReadUInt32();
            uint bitCount = reader.ReadUInt32();
            uint redMask = reader.ReadUInt32();
            uint greenMask = reader.ReadUInt32();
            uint blueMask = reader.ReadUInt32();
            uint alphaMask = reader.ReadUInt32();

            reader.ReadUInt32();
            reader.ReadUInt32();
            reader.ReadUInt32();
            reader.ReadUInt32();
            reader.ReadUInt32();

            if (pixelFormatSize != 32)
            {
                throw new InvalidDataException("Unsupported DDS pixel format header.");
            }

            if (width != texture.Width || height != texture.Height)
            {
                throw new InvalidDataException(string.Format(
                    "DDS dimensions do not match the target texture. Expected {0}x{1}, found {2}x{3}.",
                    texture.Width, texture.Height, width, height));
            }

            uint declaredMipMaps = (flags & DdsdMipmapCount) != 0 ? mipMapCount : 1u;
            if (declaredMipMaps != texture.Levels)
            {
                throw new InvalidDataException(string.Format(
                    "DDS mip count does not match the target texture. Expected {0}, found {1}.",
                    texture.Levels, declaredMipMaps));
            }

            switch (texture.TextureType)
            {
                case TextureType.DXT1:
                    ValidateCompressed(pixelFormatFlags, fourCc, FourCcDxt1, "DXT1");
                    break;
                case TextureType.DXT3:
                    ValidateCompressed(pixelFormatFlags, fourCc, FourCcDxt3, "DXT3");
                    break;
                case TextureType.DXT5:
                    ValidateCompressed(pixelFormatFlags, fourCc, FourCcDxt5, "DXT5");
                    break;
                case TextureType.A8R8G8B8:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || (pixelFormatFlags & DdpfAlphaPixels) == 0 ||
                        bitCount != 32 || redMask != 0x00FF0000 || greenMask != 0x0000FF00 ||
                        blueMask != 0x000000FF || alphaMask != 0xFF000000)
                    {
                        throw new InvalidDataException("DDS format does not match the target A8R8G8B8 texture.");
                    }
                    break;
                case TextureType.X8R8G8B8:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || bitCount != 32 ||
                        redMask != 0x00FF0000 || greenMask != 0x0000FF00 || blueMask != 0x000000FF)
                    {
                        throw new InvalidDataException("DDS format does not match the target X8R8G8B8 texture.");
                    }
                    break;
                case TextureType.R8G8B8:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || bitCount != 24 ||
                        redMask != 0x00FF0000 || greenMask != 0x0000FF00 || blueMask != 0x000000FF)
                    {
                        throw new InvalidDataException("DDS format does not match the target R8G8B8 texture.");
                    }
                    break;
                case TextureType.R5G6B5:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || bitCount != 16 ||
                        redMask != 0x0000F800 || greenMask != 0x000007E0 || blueMask != 0x0000001F)
                    {
                        throw new InvalidDataException("DDS format does not match the target R5G6B5 texture.");
                    }
                    break;
                case TextureType.A1R5G5B5:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || (pixelFormatFlags & DdpfAlphaPixels) == 0 ||
                        bitCount != 16 || redMask != 0x00007C00 || greenMask != 0x000003E0 ||
                        blueMask != 0x0000001F || alphaMask != 0x00008000)
                    {
                        throw new InvalidDataException("DDS format does not match the target A1R5G5B5 texture.");
                    }
                    break;
                case TextureType.A4R4G4B4:
                    if ((pixelFormatFlags & DdpfRgb) == 0 || (pixelFormatFlags & DdpfAlphaPixels) == 0 ||
                        bitCount != 16 || redMask != 0x00000F00 || greenMask != 0x000000F0 ||
                        blueMask != 0x0000000F || alphaMask != 0x0000F000)
                    {
                        throw new InvalidDataException("DDS format does not match the target A4R4G4B4 texture.");
                    }
                    break;
                case TextureType.A8L8:
                    if ((pixelFormatFlags & DdpfLuminance) == 0 || (pixelFormatFlags & DdpfAlphaPixels) == 0 ||
                        bitCount != 16 || redMask != 0x000000FF || alphaMask != 0x0000FF00)
                    {
                        throw new InvalidDataException("DDS format does not match the target A8L8 texture.");
                    }
                    break;
                case TextureType.V8U8:
                    if ((pixelFormatFlags & DdpfBumpDuDv) == 0 || bitCount != 16 ||
                        redMask != 0x000000FF || greenMask != 0x0000FF00)
                    {
                        throw new InvalidDataException("DDS format does not match the target V8U8 texture.");
                    }
                    break;
                case TextureType.L8:
                    if ((pixelFormatFlags & DdpfLuminance) == 0 || bitCount != 8 || redMask != 0x000000FF)
                    {
                        throw new InvalidDataException("DDS format does not match the target L8 texture.");
                    }
                    break;
                default:
                    throw new InvalidOperationException("Unsupported texture type for DDS import.");
            }
        }

        private static void ValidateCompressed(uint pixelFormatFlags, uint fourCc, uint expectedFourCc, string formatName)
        {
            if ((pixelFormatFlags & DdpfFourCc) == 0 || fourCc != expectedFourCc)
            {
                throw new InvalidDataException("DDS format does not match the target " + formatName + " texture.");
            }
        }

        private static int GetTotalDataSize(Texture texture)
        {
            int totalSize = 0;
            for (int level = 0; level < texture.Levels; level++)
            {
                totalSize += (int)texture.GetTextureDataSize(level);
            }

            return totalSize;
        }

        private static uint MakeFourCc(char a, char b, char c, char d)
        {
            return (uint)(byte)a |
                   ((uint)(byte)b << 8) |
                   ((uint)(byte)c << 16) |
                   ((uint)(byte)d << 24);
        }
    }
}
