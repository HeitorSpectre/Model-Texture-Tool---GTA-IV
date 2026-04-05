/**********************************************************************\

 RageLib
 Copyright (C) 2008  Arushan/Aru <oneforaru at gmail.com>

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.

\**********************************************************************/

using System;
using System.IO;

namespace RageLib.Textures.Resource
{
    internal static class XboxTextureDataUtil
    {
        public static byte[] ReadTopLevel(BinaryReader br, uint baseOffset, ushort width, ushort height, D3DFormat format, bool isTiled, int endianMode)
        {
            int texelPitch = GetTexelPitch(format);
            int internalWidth = width < 128 ? 128 : width;
            int internalHeight = height < 128 ? 128 : height;
            int surfaceSize = GetSurfaceSize(internalWidth, internalHeight, texelPitch);

            br.BaseStream.Seek(baseOffset, SeekOrigin.Begin);
            byte[] stored = br.ReadBytes(surfaceSize);

            if (stored.Length != surfaceSize)
            {
                throw new EndOfStreamException("Unable to read the Xbox texture surface.");
            }

            ApplyEndian(stored, endianMode);

            byte[] linear = isTiled
                ? Untile(stored, internalWidth, internalHeight, texelPitch)
                : stored;

            return TrimSurface(linear, width, height, internalWidth, internalHeight, texelPitch);
        }

        public static int GetTexelPitch(D3DFormat format)
        {
            switch (format)
            {
                case D3DFormat.DXT1:
                    return 8;
                case D3DFormat.DXT3:
                case D3DFormat.DXT5:
                    return 16;
                default:
                    throw new NotSupportedException("Unsupported Xbox texture format.");
            }
        }

        private static int GetSurfaceSize(int width, int height, int texelPitch)
        {
            return (width / 4) * (height / 4) * texelPitch;
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

        private static byte[] Untile(byte[] tiledData, int width, int height, int texelPitch)
        {
            int blockWidth = width / 4;
            int blockHeight = height / 4;
            byte[] linear = new byte[tiledData.Length];

            for (int y = 0; y < blockHeight; y++)
            {
                for (int x = 0; x < blockWidth; x++)
                {
                    int sourceBlock = XGAddress2DTiledOffset(x, y, blockWidth, texelPitch);
                    Buffer.BlockCopy(
                        tiledData,
                        sourceBlock * texelPitch,
                        linear,
                        ((y * blockWidth) + x) * texelPitch,
                        texelPitch);
                }
            }

            return linear;
        }

        private static byte[] TrimSurface(byte[] linearData, int width, int height, int internalWidth, int internalHeight, int texelPitch)
        {
            int targetBlockWidth = width / 4;
            int targetBlockHeight = height / 4;
            int internalBlockWidth = internalWidth / 4;

            byte[] trimmed = new byte[targetBlockWidth * targetBlockHeight * texelPitch];
            for (int y = 0; y < targetBlockHeight; y++)
            {
                Buffer.BlockCopy(
                    linearData,
                    y * internalBlockWidth * texelPitch,
                    trimmed,
                    y * targetBlockWidth * texelPitch,
                    targetBlockWidth * texelPitch);
            }

            return trimmed;
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
}
