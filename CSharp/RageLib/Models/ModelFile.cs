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
using RageLib.Common.Resources;
using RageLib.Models.Data;
using RageLib.Models.Resource;
using RageLib.Textures;

namespace RageLib.Models
{
    public class ModelFile : IModelFile
    {
        internal File<DrawableModel> File { get; private set; }
        private TextureFile _embeddedTextureFile;
        private ResourceFile _resourceFile;

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

        public void Open(Stream stream)
        {
            var resource = new ResourceFile();
            resource.Read(stream);

            try
            {
                File = new File<DrawableModel>();
                File.Open(resource);
                _embeddedTextureFile = File.Data.ShaderGroup.TextureDictionary;
                _resourceFile = resource;
            }
            catch
            {
                if (File != null)
                {
                    File.Dispose();
                    File = null;
                }

                _embeddedTextureFile = TextureOnlyModelReader.ReadEmbeddedTexture(resource);
                _resourceFile = resource;
                if (_embeddedTextureFile == null)
                {
                    resource.Dispose();
                    throw;
                }
            }
        }

        public void Save(string filename)
        {
            using (var fs = new FileStream(filename, FileMode.Create, FileAccess.Write))
            {
                Save(fs);
            }
        }

        public void Save(Stream stream)
        {
            if (_embeddedTextureFile == null || _resourceFile == null)
            {
                throw new InvalidOperationException("No embedded texture resource is loaded.");
            }

            using (var systemMemory = new MemoryStream())
            using (var graphicsMemory = new MemoryStream())
            {
                systemMemory.Write(_resourceFile.SystemMemData, 0, _resourceFile.SystemMemData.Length);
                graphicsMemory.Write(_resourceFile.GraphicsMemData, 0, _resourceFile.GraphicsMemData.Length);
                systemMemory.Seek(0, SeekOrigin.Begin);
                graphicsMemory.Seek(0, SeekOrigin.Begin);

                _embeddedTextureFile.Save(systemMemory, graphicsMemory);
                _resourceFile.SystemMemData = systemMemory.ToArray();
                _resourceFile.GraphicsMemData = graphicsMemory.ToArray();
            }

            _resourceFile.Write(stream);
        }

        public void SaveDecompressed(string filename)
        {
            if (_resourceFile == null)
            {
                throw new InvalidOperationException("No drawable resource is loaded.");
            }

            using (var fs = new FileStream(filename, FileMode.Create, FileAccess.Write))
            {
                fs.Write(_resourceFile.SystemMemData, 0, _resourceFile.SystemMemData.Length);
                fs.Write(_resourceFile.GraphicsMemData, 0, _resourceFile.GraphicsMemData.Length);
            }
        }

        public void SaveDecompressedParts(string systemFilename, string graphicsFilename)
        {
            if (_resourceFile == null)
            {
                throw new InvalidOperationException("No drawable resource is loaded.");
            }

            System.IO.File.WriteAllBytes(systemFilename, _resourceFile.SystemMemData);
            System.IO.File.WriteAllBytes(graphicsFilename, _resourceFile.GraphicsMemData);
        }

        public TextureFile EmbeddedTextureFile
        {
            get { return _embeddedTextureFile; }
        }

        public bool IsBigEndian
        {
            get { return _resourceFile != null && _resourceFile.IsBigEndian; }
        }

        public ResourceType ResourceType
        {
            get
            {
                if (_resourceFile == null)
                {
                    throw new InvalidOperationException("No drawable resource is loaded.");
                }

                return _resourceFile.Type;
            }
        }

        public ModelNode GetModel(TextureFile[] textures)
        {
            return ModelGenerator.GenerateModel(File.Data, textures);
        }

        public Drawable GetDataModel()
        {
            return new Drawable(File.Data);
        }

        #region Implementation of IDisposable

        public void Dispose()
        {
            var textureFile = _embeddedTextureFile;

            if (File != null)
            {
                File.Dispose();
                File = null;
                if (ReferenceEquals(textureFile, _embeddedTextureFile))
                {
                    textureFile = null;
                }
            }

            _embeddedTextureFile = null;

            if (textureFile != null)
            {
                textureFile.Dispose();
            }

            if (_resourceFile != null)
            {
                _resourceFile.Dispose();
                _resourceFile = null;
            }

        }

        #endregion
    }
}
