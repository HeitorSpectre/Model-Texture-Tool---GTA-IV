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
using RageLib.Common;
using RageLib.Common.Resources;

namespace RageLib.Textures.Resource
{
    internal class TextureInfo : IFileAccess
    {
        private const uint XboxTextureReferenceVTable = 0x941A6300;
        private const uint Ps3IntroPage2SpecialRawOffset = 0x56000;
        private const uint Ps3Rom1aPage7RawOffset = 0x102000;
        private const uint Ps3Rom1aPage7EffectiveRawOffset = 0xBB800;

        public File File { get; set; }

        public uint VTable { get; private set; }

        private uint BlockMapOffset { get; set; } // 0 in file

        private uint Unknown1 { get; set; } // 1 / 0x10000 on PC (really composed of a BYTE, BYTE, WORD)
        private uint Unknown2 { get; set; } // 0
        private uint Unknown3 { get; set; } // 0

        public string Name { get; private set; }
        private uint Unknown4 { get; set; } // 0;   // set in memory by game

        public ushort Width { get; private set; }
        public ushort Height { get; private set; }

        public D3DFormat Format;
        internal bool IsXbox { get; private set; }
        internal bool IsExternalReference { get; private set; }
        internal bool RequiresPs3ReferenceRepair { get; private set; }

        private ushort StrideSize { get; set; }
        private byte Type { get; set; }   // 0 = normal, 1 = cube, 3 = volume
        public byte Levels { get; set; } // MipMap levels

        private float UnknownFloat1 { get; set; } // 1.0f
        private float UnknownFloat2 { get; set; } // 1.0f
        private float UnknownFloat3 { get; set; } // 1.0f
        private float UnknownFloat4 { get; set; } // 0
        private float UnknownFloat5 { get; set; } // 0
        private float UnknownFloat6 { get; set; } // 0

        private uint PrevTextureInfoOffset { get; set; }    // sometimes not always accurate
        private uint NextTextureInfoOffset { get; set; }    // always 0

        internal uint RawDataOffset { get; set; }
        public byte[] TextureData { get; private set; }
        internal int ValidTextureDataLength { get; private set; }
        internal bool IsDirty { get; private set; }
        internal bool HasUnsupportedPs3WriteLayout { get; private set; }

        private uint WriteSegment1Offset { get; set; }
        private int WriteSegment1Length { get; set; }
        private uint WriteSegment2Offset { get; set; }
        private int WriteSegment2Length { get; set; }

        private uint Unknown6 { get; set; }
        private uint BitmapOffset { get; set; }
        private int XboxEndianMode { get; set; }
        private bool XboxIsTiled { get; set; }

        private static D3DFormat MapPs3TextureFormat(byte textureType)
        {
            switch (textureType)
            {
                case 133:
                    return D3DFormat.A8R8G8B8;
                case 134:
                case 166:
                    return D3DFormat.DXT1;
                case 135:
                case 167:
                    return D3DFormat.DXT3;
                case 136:
                case 168:
                    return D3DFormat.DXT5;
                case 129:
                case 161:
                    return D3DFormat.L8;
                default:
                    throw new NotSupportedException("Unsupported PS3 texture format code 0x" + textureType.ToString("X2") + ".");
            }
        }

        public void ReadData(BinaryReader br)
        {
            WriteSegment1Offset = 0;
            WriteSegment1Length = 0;
            WriteSegment2Offset = 0;
            WriteSegment2Length = 0;
            HasUnsupportedPs3WriteLayout = false;

            if (IsExternalReference)
            {
                return;
            }

            if (IsXbox)
            {
                TextureData = XboxTextureDataUtil.ReadTopLevel(br, RawDataOffset, Width, Height, Format, XboxIsTiled, XboxEndianMode);
                ValidTextureDataLength = TextureData.Length;
                Levels = 1;
                return;
            }

            int dataSize = GetTotalDataSize();
            uint effectiveRawDataOffset = GetEffectiveRawDataOffset(br.BaseStream.Length, dataSize);
            long streamLength = br.BaseStream.Length;

            if (br is BigEndianBinaryReader && streamLength > 0 && effectiveRawDataOffset >= streamLength)
            {
                RequiresPs3ReferenceRepair = true;
                effectiveRawDataOffset = (uint)(effectiveRawDataOffset % streamLength);
            }

            long available = br.BaseStream.Length - effectiveRawDataOffset;

            if (br is BigEndianBinaryReader && dataSize > 0 && available > 0 && available < dataSize)
            {
                RequiresPs3ReferenceRepair = true;
                br.BaseStream.Seek(effectiveRawDataOffset, SeekOrigin.Begin);

                TextureData = new byte[dataSize];
                int firstChunkSize = (int)Math.Min((long)available, dataSize);
                long continuationOffset = 0;
                bool allowContinuation = TryGetPs3ContinuationOffset(streamLength, dataSize, out continuationOffset);

                // Observed PS3 title-page CDRs can split a 512x512 DXT5 texture
                // across the end of graphics memory and continue at another aligned block.
                // For cstitlesintroa3 page2, every continuation candidate observed so far
                // leaks unrelated texture data into the missing tail. Prefer showing the
                // valid leading region and leave the missing bytes zeroed instead of mixing
                // in page1/pageX data.
                if (dataSize == 0x40000 && br.BaseStream.Length == 0x80000 && RawDataOffset == Ps3IntroPage2SpecialRawOffset)
                {
                    allowContinuation = false;
                }

                int read = br.Read(TextureData, 0, firstChunkSize);
                int remaining = dataSize - read;
                if (allowContinuation)
                {
                    br.BaseStream.Seek(continuationOffset, SeekOrigin.Begin);
                    while (remaining > 0)
                    {
                        int chunk = br.Read(TextureData, read, remaining);
                        if (chunk <= 0)
                        {
                            break;
                        }

                        read += chunk;
                        remaining -= chunk;
                    }
                }

                ValidTextureDataLength = read;
                if (read == dataSize)
                {
                    SetWriteSegments(effectiveRawDataOffset, firstChunkSize, (uint)continuationOffset, dataSize - firstChunkSize);
                    return;
                }

                if (!allowContinuation)
                {
                    HasUnsupportedPs3WriteLayout = true;
                    return;
                }
            }

            br.BaseStream.Seek(effectiveRawDataOffset, SeekOrigin.Begin);
            TextureData = br.ReadBytes(dataSize);
            ValidTextureDataLength = TextureData.Length;

            if (br is BigEndianBinaryReader && TextureData.Length < dataSize && streamLength > 0)
            {
                RequiresPs3ReferenceRepair = true;

                var wrappedData = new byte[dataSize];
                if (TextureData.Length > 0)
                {
                    Array.Copy(TextureData, wrappedData, TextureData.Length);
                }

                int read = TextureData.Length;
                long continuationOffset;
                bool allowContinuation = TryGetPs3ContinuationOffset(streamLength, dataSize, out continuationOffset);
                if (allowContinuation)
                {
                    br.BaseStream.Seek(continuationOffset, SeekOrigin.Begin);
                    while (read < dataSize)
                    {
                        int chunk = br.Read(wrappedData, read, dataSize - read);
                        if (chunk <= 0)
                        {
                            break;
                        }

                        read += chunk;
                    }
                }

                TextureData = wrappedData;
                ValidTextureDataLength = read;
                if (allowContinuation)
                {
                    SetWriteSegments(effectiveRawDataOffset, (int)(streamLength - effectiveRawDataOffset), (uint)continuationOffset, dataSize - (int)(streamLength - effectiveRawDataOffset));
                }
                else
                {
                    SetWriteSegments(effectiveRawDataOffset, (int)(streamLength - effectiveRawDataOffset), 0, 0);
                }

                if (read < dataSize || !allowContinuation)
                {
                    HasUnsupportedPs3WriteLayout = true;
                }
                return;
            }

            SetWriteSegments(effectiveRawDataOffset, dataSize, 0, 0);
        }

        internal int GetTotalDataSize()
        {
            return GetTotalDataSizeForFormat(Format);
        }

        internal int GetTotalDataSizeForFormat(D3DFormat format)
        {
            uint width = Width;
            uint height = Height;

            int dataSize;
            switch (format)
            {
                case D3DFormat.DXT1:
                    dataSize = (int) (width*height/2);
                    break;
                case D3DFormat.DXT3:
                case D3DFormat.DXT5:
                    dataSize = (int) (width*height);
                    break;
                case D3DFormat.A8R8G8B8:
                    dataSize = (int) (width*height*4);
                    break;
                case D3DFormat.X8R8G8B8:
                    dataSize = (int) (width*height*4);
                    break;
                case D3DFormat.R8G8B8:
                    dataSize = (int)(width * height * 3);
                    break;
                case D3DFormat.R5G6B5:
                case D3DFormat.A1R5G5B5:
                case D3DFormat.A4R4G4B4:
                case D3DFormat.A8L8:
                case D3DFormat.V8U8:
                    dataSize = (int)(width * height * 2);
                    break;
                case D3DFormat.L8:
                    dataSize = (int) (width*height);
                    break;
                default:
                    throw new ArgumentOutOfRangeException();
            }

            int levels = Levels;
            int levelDataSize = dataSize;
            while(levels > 1)
            {
                dataSize += (levelDataSize/4);
                
                levelDataSize /= 4;

                // clamp to 16 bytes
                if (levelDataSize < 16)
                {
                    if (format == D3DFormat.DXT1 && levelDataSize < 8)
                    {
                        levelDataSize = 8;
                    }
                    else
                    {
                        levelDataSize = 16;
                    }
                }

                levels--;
            }
            return dataSize;
        }

        public void WriteData(BinaryWriter bw)
        {
            if (IsExternalReference || TextureData == null || !IsDirty)
            {
                return;
            }

            int dataSize = GetTotalDataSize();
            if (HasUnsupportedPs3WriteLayout)
            {
                throw new InvalidOperationException("This PS3 texture uses an unresolved wrapped storage layout and cannot be saved safely yet.");
            }

            if (WriteSegment1Length <= 0)
            {
                uint effectiveRawDataOffset = GetEffectiveRawDataOffset(bw.BaseStream.Length, dataSize);
                bw.BaseStream.Seek(effectiveRawDataOffset, SeekOrigin.Begin);
                bw.Write(TextureData, 0, dataSize);
                return;
            }

            bw.BaseStream.Seek(WriteSegment1Offset, SeekOrigin.Begin);
            bw.Write(TextureData, 0, WriteSegment1Length);

            if (WriteSegment2Length > 0)
            {
                bw.BaseStream.Seek(WriteSegment2Offset, SeekOrigin.Begin);
                bw.Write(TextureData, WriteSegment1Length, WriteSegment2Length);
            }
        }

        internal void MarkDirty()
        {
            IsDirty = true;
        }

        private void SetWriteSegments(uint segment1Offset, int segment1Length, uint segment2Offset, int segment2Length)
        {
            WriteSegment1Offset = segment1Offset;
            WriteSegment1Length = Math.Max(0, segment1Length);
            WriteSegment2Offset = segment2Offset;
            WriteSegment2Length = Math.Max(0, segment2Length);
        }

        private uint GetEffectiveRawDataOffset(long streamLength, int dataSize)
        {
            uint effectiveRawDataOffset = RawDataOffset;

            if (File == null || !File.IsBigEndian || streamLength <= 0)
            {
                return effectiveRawDataOffset;
            }

            uint adjustedOffset;
            if (TryGetPs3AdjustedRawDataOffset(streamLength, dataSize, out adjustedOffset))
            {
                RequiresPs3ReferenceRepair = true;
                return adjustedOffset;
            }

            if (effectiveRawDataOffset >= streamLength)
            {
                RequiresPs3ReferenceRepair = true;
                return (uint)(effectiveRawDataOffset % streamLength);
            }

            return effectiveRawDataOffset;
        }

        private bool TryGetPs3AdjustedRawDataOffset(long streamLength, int dataSize, out uint adjustedOffset)
        {
            adjustedOffset = 0;

            if (dataSize == 0x40000 &&
                streamLength == 0x100000 &&
                RawDataOffset == Ps3Rom1aPage7RawOffset &&
                string.Equals(Name, "page7_apage7_a", StringComparison.OrdinalIgnoreCase))
            {
                adjustedOffset = Ps3Rom1aPage7EffectiveRawOffset;
                return true;
            }

            return false;
        }

        private bool TryGetPs3ContinuationOffset(long streamLength, int dataSize, out long continuationOffset)
        {
            continuationOffset = 0;

            if (File == null || !File.IsBigEndian || streamLength <= 0)
            {
                return false;
            }

            // Only continue wrapped PS3 reads when we have an explicit mapping.
            // Generic wrap-to-zero mixes unrelated texture rows for many model textures.
            uint adjustedOffset;
            if (TryGetPs3AdjustedRawDataOffset(streamLength, dataSize, out adjustedOffset))
            {
                continuationOffset = adjustedOffset;
                return true;
            }

            return false;
        }

        #region IFileAccess Members

        public void Read(BinaryReader br)
        {
            if (br is BigEndianBinaryReader)
            {
                ReadPs3(br);
                return;
            }

            // Full structure of rage::grcTexturePC

            // rage::datBase
            VTable = br.ReadUInt32(); 

            // rage::pgBase
            BlockMapOffset = ResourceUtil.ReadOffset(br);
            
            // Texture Info struct:
            Unknown1 = br.ReadUInt32(); // BYTE, BYTE, WORD
            Unknown2 = br.ReadUInt32();
            Unknown3 = br.ReadUInt32();
            
            uint nameOffset = ResourceUtil.ReadOffset(br);
            
            Unknown4 = br.ReadUInt32();

            // Texture Data struct:
            Width = br.ReadUInt16();
            Height = br.ReadUInt16();
            Format = (D3DFormat) br.ReadInt32();

            StrideSize = br.ReadUInt16();
            Type = br.ReadByte();
            Levels = br.ReadByte();

            UnknownFloat1 = br.ReadSingle();
            UnknownFloat2 = br.ReadSingle();
            UnknownFloat3 = br.ReadSingle();
            UnknownFloat4 = br.ReadSingle();
            UnknownFloat5 = br.ReadSingle();
            UnknownFloat6 = br.ReadSingle();

            PrevTextureInfoOffset = ResourceUtil.ReadOffset(br);
            NextTextureInfoOffset = ResourceUtil.ReadOffset(br);

            RawDataOffset = ResourceUtil.ReadDataOffset(br);

            Unknown6 = br.ReadUInt32();

            // Read texture name
            br.BaseStream.Seek(nameOffset, SeekOrigin.Begin);
            Name = ResourceUtil.ReadNullTerminatedString(br);
        }

        private void ReadPs3(BinaryReader br)
        {
            var start = br.BaseStream.Position;

            VTable = br.ReadUInt32();
            BlockMapOffset = br.ReadUInt32();
            Unknown1 = br.ReadUInt32();
            Unknown2 = br.ReadUInt32();
            Unknown3 = br.ReadUInt32();

            br.BaseStream.Seek(start + 0x1C, SeekOrigin.Begin);
            Width = br.ReadUInt16();
            Height = br.ReadUInt16();

            br.BaseStream.Seek(start + 0x14, SeekOrigin.Begin);
            byte textureType = br.ReadByte();

            br.BaseStream.Seek(start + 0x2C, SeekOrigin.Begin);
            uint nameOffset = ResourceUtil.ReadOffset(br);

            br.BaseStream.Seek(start + 0x30, SeekOrigin.Begin);
            RawDataOffset = ResourceUtil.ReadDataOffset(br);

            Format = MapPs3TextureFormat(textureType);
            Levels = 1;

            br.BaseStream.Seek(nameOffset, SeekOrigin.Begin);
            Name = ResourceUtil.ReadNullTerminatedString(br);
        }

        internal void ReadXbox(BinaryReader br)
        {
            long start = br.BaseStream.Position;

            VTable = br.ReadUInt32();

            if (VTable == XboxTextureReferenceVTable)
            {
                br.BaseStream.Seek(start + 0x14, SeekOrigin.Begin);
                uint refNameOffset = ResourceUtil.ReadOffset(br);
                uint rawLinkedTextureValue = br.ReadUInt32();
                uint linkedTextureOffset = DecodeXboxReferenceOffset(rawLinkedTextureValue, br.BaseStream.Length);
                if (refNameOffset != 0)
                {
                    br.BaseStream.Seek(refNameOffset, SeekOrigin.Begin);
                    Name = ResourceUtil.ReadNullTerminatedString(br);
                }
                else
                {
                    Name = "xbox_texture_ref_" + start.ToString("X");
                }

                IsXbox = true;

                if (linkedTextureOffset != 0)
                {
                    ParseXboxExternalReference(br, linkedTextureOffset);
                    return;
                }

                SetAsExternalReference();
                return;
            }

            IsXbox = true;
            ParseXboxTextureObject(br, (uint)start, true);
        }

        private void ParseXboxTextureObject(BinaryReader br, uint textureOffset, bool preferObjectName)
        {
            long returnPosition = br.BaseStream.Position;
            br.BaseStream.Seek(textureOffset, SeekOrigin.Begin);

            VTable = br.ReadUInt32();
            Unknown1 = br.ReadUInt32();

            br.BaseStream.Seek(textureOffset + 0x14, SeekOrigin.Begin);
            uint nameOffset = ResourceUtil.ReadOffset(br);
            BitmapOffset = ResourceUtil.ReadOffset(br);
            Width = br.ReadUInt16();
            Height = br.ReadUInt16();

            if (nameOffset != 0 && (preferObjectName || string.IsNullOrEmpty(Name)))
            {
                long nameReturn = br.BaseStream.Position;
                br.BaseStream.Seek(nameOffset, SeekOrigin.Begin);
                Name = ResourceUtil.ReadNullTerminatedString(br);
                br.BaseStream.Seek(nameReturn, SeekOrigin.Begin);
            }

            if (string.IsNullOrEmpty(Name))
            {
                Name = "xbox_texture_" + textureOffset.ToString("X");
            }

            if (BitmapOffset != 0)
            {
                br.BaseStream.Seek(BitmapOffset, SeekOrigin.Begin);
                ParseXboxBitmap(br);
            }

            br.BaseStream.Seek(returnPosition, SeekOrigin.Begin);
        }

        private void ParseXboxBitmap(BinaryReader br)
        {
            byte[] dwords = br.ReadBytes(13 * 4);
            if (dwords.Length != (13 * 4))
            {
                throw new EndOfStreamException("Xbox D3DBaseTexture data is incomplete.");
            }

            uint rawInfo1 = BitConverter.ToUInt32(dwords, 28);
            uint rawInfo2 = BitConverter.ToUInt32(dwords, 32);
            uint rawMipInfo = BitConverter.ToUInt32(dwords, 44);

            XboxIsTiled = true;
            XboxEndianMode = (int)((rawInfo2 >> 6) & 0x3);

            uint xboxFormat = rawInfo2 & 0x3F;
            switch (xboxFormat)
            {
                case 0x12:
                    Format = D3DFormat.DXT1;
                    break;
                case 0x13:
                    Format = D3DFormat.DXT3;
                    break;
                case 0x14:
                    Format = D3DFormat.DXT5;
                    break;
                default:
                    throw new NotSupportedException("Unsupported Xbox texture format 0x" + xboxFormat.ToString("X") + ".");
            }

            RawDataOffset = SwapEndian(DecodeXboxDataOffset(rawInfo2));

            uint maxMipLevel = SwapEndian(((rawMipInfo & 0xC0000000) >> 6) | ((rawMipInfo & 0x00030000) << 10));
            Levels = (byte)Math.Max(1, Math.Min(maxMipLevel + 1, (uint)byte.MaxValue));
        }

        private void ParseXboxExternalReference(BinaryReader br, uint linkedTextureOffset)
        {
            long returnPosition = br.BaseStream.Position;
            br.BaseStream.Seek(linkedTextureOffset, SeekOrigin.Begin);

            byte[] dwords = br.ReadBytes(13 * 4);
            br.BaseStream.Seek(returnPosition, SeekOrigin.Begin);

            if (dwords.Length != (13 * 4))
            {
                return;
            }

            uint rawInfo2 = BitConverter.ToUInt32(dwords, 32);
            uint rawSizeInfo = BitConverter.ToUInt32(dwords, 36);
            uint rawMipInfo = BitConverter.ToUInt32(dwords, 44);

            uint logicalInfo2 = SwapEndian(rawInfo2);
            uint logicalSizeInfo = SwapEndian(rawSizeInfo);

            XboxEndianMode = (int)((rawInfo2 >> 6) & 0x3);
            XboxIsTiled = true;

            uint xboxFormat = logicalInfo2 & 0x3F;
            switch (xboxFormat)
            {
                case 0x12:
                    Format = D3DFormat.DXT1;
                    break;
                case 0x13:
                    Format = D3DFormat.DXT3;
                    break;
                case 0x14:
                    Format = D3DFormat.DXT5;
                    break;
            }

            Width = (ushort)((logicalSizeInfo & 0x1FFF) + 1);
            Height = (ushort)(((logicalSizeInfo >> 13) & 0x1FFF) + 1);
            RawDataOffset = SwapEndian(DecodeXboxDataOffset(rawInfo2));

            uint maxMipLevel = SwapEndian(((rawMipInfo & 0xC0000000) >> 6) | ((rawMipInfo & 0x00030000) << 10));
            Levels = (byte)Math.Max(1, Math.Min(maxMipLevel + 1, (uint)byte.MaxValue));
        }

        internal void SetAsExternalReference()
        {
            IsExternalReference = true;
            Format = D3DFormat.A8R8G8B8;
            if (Width == 0)
            {
                Width = 1;
            }
            if (Height == 0)
            {
                Height = 1;
            }
            if (Levels == 0)
            {
                Levels = 1;
            }
            TextureData = new byte[4];
        }

        private static uint DecodeXboxDataOffset(uint rawValue)
        {
            uint value = rawValue >> 8;
            value <<= 16;
            value >>= 8;
            return value;
        }

        private static uint DecodeXboxReferenceOffset(uint rawValue, long streamLength)
        {
            if (rawValue == 0)
            {
                return 0;
            }

            if ((rawValue >> 28) == 5)
            {
                return rawValue & 0x0FFFFFFF;
            }

            uint swapped = SwapEndian(rawValue);
            if ((swapped >> 28) == 5)
            {
                return swapped & 0x0FFFFFFF;
            }

            uint compactOffset = swapped >> 8;
            if (compactOffset > 0 && compactOffset < streamLength)
            {
                return compactOffset;
            }

            uint dataOffset = SwapEndian(DecodeXboxDataOffset(rawValue));
            if (dataOffset > 0 && dataOffset < streamLength)
            {
                return dataOffset;
            }

            return 0;
        }

        private static uint SwapEndian(uint value)
        {
            return DataUtil.SwapEndian(value);
        }

        public void Write(BinaryWriter bw)
        {
            throw new NotImplementedException();
        }

        #endregion
    }
}
