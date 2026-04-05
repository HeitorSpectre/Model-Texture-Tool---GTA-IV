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
using System.Collections.Generic;
using System.IO;
using RageLib.Common;
using RageLib.Common.Resources;

namespace RageLib.Textures.Resource
{
    internal class File : IDisposable
    {
        private ResourceFile _resourceFile;
        internal bool IsBigEndian { get; private set; }

        public Header Header { get; private set; }

        public Dictionary<uint, TextureInfo> TexturesByHash { get; private set; }
        public List<TextureInfo> Textures { get; private set; }

        public void Open(string filename)
        {
            var fs = new FileStream(filename, FileMode.Open, FileAccess.ReadWrite);
            try
            {
                Open(fs);
            }
            finally
            {
                fs.Close();
            }
        }

        public void Open(Stream systemMemory, Stream graphicsMemory)
        {
            Open(systemMemory, graphicsMemory, false, ResourceType.Texture);
        }

        public void Open(Stream systemMemory, Stream graphicsMemory, bool isBigEndian)
        {
            Open(systemMemory, graphicsMemory, isBigEndian, ResourceType.Texture);
        }

        public void Open(Stream systemMemory, Stream graphicsMemory, bool isBigEndian, ResourceType resourceType)
        {
            bool isXbox = resourceType == ResourceType.TextureXBOX || resourceType == ResourceType.ModelXBOX;
            IsBigEndian = isBigEndian;

            // Sys

            var ms = systemMemory;
            var br = isBigEndian
                ? (BinaryReader)new BigEndianBinaryReader(ms)
                : new BinaryReader(ms);

            Header = new Header();
            Header.Read(br);

            TexturesByHash = new Dictionary<uint, TextureInfo>(Header.TextureCount);
            Textures = new List<TextureInfo>(Header.TextureCount);

            var textureHashes = new uint[Header.TextureCount];
            var infoOffsets = new uint[Header.TextureCount];

            ms.Seek(Header.HashTableOffset, SeekOrigin.Begin);
            for (int i = 0; i < Header.TextureCount; i++)
            {
                textureHashes[i] = br.ReadUInt32();
            }

            ms.Seek(Header.TextureListOffset, SeekOrigin.Begin);
            for (int i = 0; i < Header.TextureCount; i++)
            {
                infoOffsets[i] = ResourceUtil.ReadOffset(br);
            }

            for (int i = 0; i < Header.TextureCount; i++)
            {
                ms.Seek(infoOffsets[i], SeekOrigin.Begin);

                var info = new TextureInfo { File = this };
                if (isXbox)
                {
                    try
                    {
                        info.ReadXbox(br);
                    }
                    catch (NotSupportedException)
                    {
                        info.SetAsExternalReference();
                    }
                }
                else
                {
                    info.Read(br);
                }

                Textures.Add(info);
                TexturesByHash.Add(textureHashes[i], info);
            }

            if (isBigEndian && !isXbox)
            {
                ResolvePs3TextureFormats(graphicsMemory.Length);
            }

            // Gfx

            ms = graphicsMemory;
            br = isBigEndian
                ? (BinaryReader)new BigEndianBinaryReader(ms)
                : new BinaryReader(ms);

            for (int i = 0; i < Header.TextureCount; i++)
            {
                try
                {
                    Textures[i].ReadData(br);
                }
                catch (EndOfStreamException)
                {
                    if (!isXbox)
                    {
                        throw;
                    }

                    Textures[i].SetAsExternalReference();
                }
            }
        }

        private void ResolvePs3TextureFormats(long graphicsMemoryLength)
        {
            if (Textures == null || Textures.Count == 0)
            {
                return;
            }

            var texturesByOffset = new List<TextureInfo>();
            foreach (var texture in Textures)
            {
                if (!texture.IsExternalReference)
                {
                    texturesByOffset.Add(texture);
                }
            }

            texturesByOffset.Sort(delegate(TextureInfo left, TextureInfo right)
            {
                return left.RawDataOffset.CompareTo(right.RawDataOffset);
            });

            for (int i = 0; i < texturesByOffset.Count - 1; i++)
            {
                var current = texturesByOffset[i];
                var next = texturesByOffset[i + 1];
                if (next.RawDataOffset <= current.RawDataOffset)
                {
                    continue;
                }

                var gap = next.RawDataOffset - current.RawDataOffset;
                var dxt1Size = (uint)current.GetTotalDataSizeForFormat(D3DFormat.DXT1);
                var dxt5Size = (uint)current.GetTotalDataSizeForFormat(D3DFormat.DXT5);

                if (gap == dxt1Size)
                {
                    current.Format = D3DFormat.DXT1;
                }
                else if (gap == dxt5Size)
                {
                    current.Format = D3DFormat.DXT5;
                }
            }

            long totalDxt1Size = 0;
            long totalDxt5Size = 0;
            foreach (var texture in texturesByOffset)
            {
                totalDxt1Size += texture.GetTotalDataSizeForFormat(D3DFormat.DXT1);
                totalDxt5Size += texture.GetTotalDataSizeForFormat(D3DFormat.DXT5);
            }

            if (totalDxt1Size == graphicsMemoryLength && totalDxt5Size != graphicsMemoryLength)
            {
                foreach (var texture in texturesByOffset)
                {
                    texture.Format = D3DFormat.DXT1;
                }
            }
            else if (totalDxt5Size == graphicsMemoryLength && totalDxt1Size != graphicsMemoryLength)
            {
                foreach (var texture in texturesByOffset)
                {
                    texture.Format = D3DFormat.DXT5;
                }
            }
        }

        public void Open(Stream stream)
        {
            var res = new ResourceFile();
            res.Read(stream);

            if (res.Type != ResourceType.Texture && res.Type != ResourceType.TextureXBOX)
            {
                throw new Exception("Not a valid texture resource.");
            }

            // Read

            var systemMem = new MemoryStream(res.SystemMemData);
            var graphicsMem = new MemoryStream(res.GraphicsMemData);

            Open(systemMem, graphicsMem, res.IsBigEndian, res.Type);

            systemMem.Close();
            graphicsMem.Close();

            // Save the resource file for later
            _resourceFile = res;
        }

        public void Save(Stream stream)
        {
            var res = _resourceFile;

            // Save to the Resource file stream

            var systemMem = new MemoryStream(res.SystemMemData);
            var graphicsMem = new MemoryStream(res.GraphicsMemData);

            Save(systemMem, graphicsMem);

            systemMem.Close();
            graphicsMem.Close();

            // Now write the Resource data back to the stream

            res.Write(stream);
        }

        public void Save(Stream systemMemory, Stream graphicsMemory)
        {
            var ms = graphicsMemory;
            var bw = new BinaryWriter(ms);

            for (int i = 0; i < Header.TextureCount; i++)
            {
                Textures[i].WriteData(bw);
            }           
        }

        #region Implementation of IDisposable

        public void Dispose()
        {
            if (_resourceFile != null)
            {
                _resourceFile.Dispose();
            }

            if (TexturesByHash != null)
            {
                TexturesByHash.Clear();
            }

            if (Textures != null)
            {
                Textures.Clear();
            }
        }

        #endregion
    }
}
