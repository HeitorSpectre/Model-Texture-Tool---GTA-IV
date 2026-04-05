/**********************************************************************\

 RageLib - Models
 Copyright (C) 2009  Arushan/Aru <oneforaru at gmail.com>

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
using RageLib.Textures;

namespace RageLib.Models.Resource
{
    internal static class TextureOnlyModelReader
    {
        public static TextureFile ReadEmbeddedTexture(Stream stream)
        {
            var resource = new ResourceFile();
            resource.Read(stream);
            return ReadEmbeddedTexture(resource, true);
        }

        internal static TextureFile ReadEmbeddedTexture(ResourceFile resource)
        {
            return ReadEmbeddedTexture(resource, false);
        }

        private static TextureFile ReadEmbeddedTexture(ResourceFile resource, bool disposeResourceWhenDone)
        {

            try
            {
                if (resource.Type != ResourceType.Model &&
                    resource.Type != ResourceType.ModelFrag &&
                    resource.Type != ResourceType.ModelXBOX)
                {
                    throw new Exception("Not a supported file type.");
                }

                var systemMemory = new MemoryStream(resource.SystemMemData);
                var graphicsMemory = new MemoryStream(resource.GraphicsMemData);

                try
                {
                    var reader = resource.IsBigEndian
                        ? (BinaryReader)new BigEndianBinaryReader(systemMemory)
                        : new BinaryReader(systemMemory);

                    uint shaderGroupOffset = resource.Type == ResourceType.Model || resource.Type == ResourceType.ModelXBOX
                        ? ReadDrawableShaderGroupOffset(reader)
                        : ReadFragDrawableShaderGroupOffset(reader);

                    if (shaderGroupOffset == 0)
                    {
                        return null;
                    }

                    var textureDictionaryOffset = ReadShaderGroupTextureDictionaryOffset(reader, shaderGroupOffset);
                    if (textureDictionaryOffset == 0)
                    {
                        return null;
                    }

                    systemMemory.Seek(textureDictionaryOffset, SeekOrigin.Begin);

                    var textureFile = new TextureFile();
                    textureFile.Open(systemMemory, graphicsMemory, resource.IsBigEndian, resource.Type);
                    return textureFile;
                }
                finally
                {
                    systemMemory.Close();
                    graphicsMemory.Close();
                }
            }
            finally
            {
                if (disposeResourceWhenDone)
                {
                    resource.Dispose();
                }
            }
        }

        private static uint ReadDrawableShaderGroupOffset(BinaryReader reader)
        {
            reader.BaseStream.Seek(8, SeekOrigin.Begin);
            return ResourceUtil.ReadOffset(reader);
        }

        private static uint ReadFragDrawableShaderGroupOffset(BinaryReader reader)
        {
            reader.BaseStream.Seek(0xB4, SeekOrigin.Begin);
            var drawableOffset = ResourceUtil.ReadOffset(reader);
            if (drawableOffset == 0)
            {
                return 0;
            }

            reader.BaseStream.Seek(drawableOffset + 8, SeekOrigin.Begin);
            return ResourceUtil.ReadOffset(reader);
        }

        private static uint ReadShaderGroupTextureDictionaryOffset(BinaryReader reader, uint shaderGroupOffset)
        {
            reader.BaseStream.Seek(shaderGroupOffset + 4, SeekOrigin.Begin);
            return ResourceUtil.ReadOffset(reader);
        }
    }
}
