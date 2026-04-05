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

namespace RageLib.Models.Resource
{
    class File<T> : IDisposable where T : IFileAccess, IDataReader, IDisposable, new()
    {
        private bool _ownsResource;

        internal ResourceFile Resource { get; private set; }

        public T Data { get; private set; }

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
            var res = new ResourceFile();
            res.Read(stream);
            Open(res, true);
        }

        internal void Open(ResourceFile res)
        {
            Open(res, false);
        }

        private void Open(ResourceFile res, bool ownsResource)
        {
            _ownsResource = ownsResource;
            Resource = res;

            if (res.Type != ResourceType.Model && res.Type != ResourceType.ModelFrag)
            {
                throw new Exception("Not a supported file type.");
            }

            var systemMemory = new MemoryStream(res.SystemMemData);
            var graphicsMemory = new MemoryStream(res.GraphicsMemData);

            Data = new T();

            // Read System Memory
            
            var systemMemoryBR = res.IsBigEndian
                ? (BinaryReader)new BigEndianBinaryReader(systemMemory)
                : new BinaryReader(systemMemory);

            Data.Read(systemMemoryBR);

            // Read Graphics Memory

            var graphicsMemoryBR = res.IsBigEndian
                ? (BinaryReader)new BigEndianBinaryReader(graphicsMemory)
                : new BinaryReader(graphicsMemory);

            Data.ReadData(graphicsMemoryBR);

            // Read Embedded Resource Files

            var embeddedReader = Data as IEmbeddedResourceReader;
            if (embeddedReader != null)
            {
                embeddedReader.ReadEmbeddedResources(systemMemory, graphicsMemory, res.IsBigEndian);
            }

            systemMemory.Close();
            graphicsMemory.Close();
        }

        #region Implementation of IDisposable

        public void Dispose()
        {
            if (Data != null)
            {
                Data.Dispose();
            }

            if (Resource != null)
            {
                if (_ownsResource)
                {
                    Resource.Dispose();
                }
                Resource = null;
            }
        }

        #endregion
    }
}
