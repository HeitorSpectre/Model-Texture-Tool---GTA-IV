/**********************************************************************\

 RageLib - Textures
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
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace RageLib.Textures.Decoder
{
    internal class TextureDecoder
    {
        private static byte Expand5To8(int value)
        {
            return (byte)((value << 3) | (value >> 2));
        }

        private static byte Expand6To8(int value)
        {
            return (byte)((value << 2) | (value >> 4));
        }

        private static byte Expand4To8(int value)
        {
            return (byte)((value << 4) | value);
        }

        private static void ConvertRgbaToBgra(byte[] data)
        {
            for (int i = 0; i < data.Length; i += 4)
            {
                byte red = data[i + 0];
                data[i + 0] = data[i + 2];
                data[i + 2] = red;
            }
        }

        internal static Image Decode(Texture texture, int level)
        {
            var width = texture.GetWidth(level);
            var height = texture.GetHeight(level);
            var data = texture.GetTextureData(level);
            var validLength = texture.GetValidTextureDataLength(level);
            
            switch(texture.TextureType)
            {
                case TextureType.DXT1:
                    data = DXTDecoder.DecodeDXT1(data, (int)width, (int)height, validLength);
                    ConvertRgbaToBgra(data);
                    break;
                case TextureType.DXT3:
                    data = DXTDecoder.DecodeDXT3(data, (int)width, (int)height, validLength);
                    ConvertRgbaToBgra(data);
                    break;
                case TextureType.DXT5:
                    data = DXTDecoder.DecodeDXT5(data, (int)width, (int)height, validLength);
                    ConvertRgbaToBgra(data);
                    break;
                case TextureType.A8R8G8B8:
                    // D3D A8R8G8B8 is stored as BGRA bytes on little-endian platforms,
                    // which already matches Format32bppArgb memory layout.
                    break;
                case TextureType.X8R8G8B8:
                    for (int i = 0; i < data.Length; i += 4)
                    {
                        data[i + 3] = 255;
                    }
                    break;
                case TextureType.R8G8B8:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 3, dst += 4)
                        {
                            newData[dst + 0] = data[src + 2];
                            newData[dst + 1] = data[src + 1];
                            newData[dst + 2] = data[src + 0];
                            newData[dst + 3] = 255;
                        }
                        data = newData;
                    }
                    break;
                case TextureType.R5G6B5:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 2, dst += 4)
                        {
                            int packed = data[src] | (data[src + 1] << 8);
                            newData[dst + 0] = Expand5To8(packed & 0x1F);
                            newData[dst + 1] = Expand6To8((packed >> 5) & 0x3F);
                            newData[dst + 2] = Expand5To8((packed >> 11) & 0x1F);
                            newData[dst + 3] = 255;
                        }
                        data = newData;
                    }
                    break;
                case TextureType.A1R5G5B5:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 2, dst += 4)
                        {
                            int packed = data[src] | (data[src + 1] << 8);
                            newData[dst + 0] = Expand5To8(packed & 0x1F);
                            newData[dst + 1] = Expand5To8((packed >> 5) & 0x1F);
                            newData[dst + 2] = Expand5To8((packed >> 10) & 0x1F);
                            newData[dst + 3] = ((packed & 0x8000) != 0) ? (byte)255 : (byte)0;
                        }
                        data = newData;
                    }
                    break;
                case TextureType.A4R4G4B4:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 2, dst += 4)
                        {
                            int packed = data[src] | (data[src + 1] << 8);
                            newData[dst + 0] = Expand4To8(packed & 0xF);
                            newData[dst + 1] = Expand4To8((packed >> 4) & 0xF);
                            newData[dst + 2] = Expand4To8((packed >> 8) & 0xF);
                            newData[dst + 3] = Expand4To8((packed >> 12) & 0xF);
                        }
                        data = newData;
                    }
                    break;
                case TextureType.A8L8:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 2, dst += 4)
                        {
                            byte luminance = data[src];
                            byte alpha = data[src + 1];
                            newData[dst + 0] = luminance;
                            newData[dst + 1] = luminance;
                            newData[dst + 2] = luminance;
                            newData[dst + 3] = alpha;
                        }
                        data = newData;
                    }
                    break;
                case TextureType.V8U8:
                    {
                        var newData = new byte[(int)width * (int)height * 4];
                        for (int src = 0, dst = 0; src < data.Length; src += 2, dst += 4)
                        {
                            int u = (sbyte)data[src];
                            int v = (sbyte)data[src + 1];
                            newData[dst + 0] = (byte)(u + 128);
                            newData[dst + 1] = (byte)(v + 128);
                            newData[dst + 2] = 255;
                            newData[dst + 3] = 255;
                        }
                        data = newData;
                    }
                    break;
                case TextureType.L8:
                    {
                        var newData = new byte[data.Length*4];
                        for (int i = 0; i < data.Length; i++)
                        {
                            newData[i*4 + 0] = data[i];
                            newData[i*4 + 1] = data[i];
                            newData[i*4 + 2] = data[i];
                            newData[i*4 + 3] = 255;
                        }
                        data = newData;
                    }
                    break;
                default:
                    throw new ArgumentOutOfRangeException();
            }

            var bmp = new Bitmap((int) width, (int) height, PixelFormat.Format32bppArgb);

            var rect = new Rectangle(0, 0, (int) width, (int) height);
            var bmpdata = bmp.LockBits(rect, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);

            Marshal.Copy(data, 0, bmpdata.Scan0, (int) width*(int) height*4);
            
            bmp.UnlockBits(bmpdata);

            return bmp;
        }
    }
}
