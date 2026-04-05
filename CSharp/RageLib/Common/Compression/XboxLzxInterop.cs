using System.Runtime.InteropServices;

namespace RageLib.Common.Compression
{
    internal static class XboxLzxInterop
    {
        [DllImport("xcompress_cpp.dll", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern int LZXinit(int window);

        [DllImport("xcompress_cpp.dll", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern int LZXdecompress(byte[] inData, int inLength, byte[] outData, int outLength);

        public static void Initialize(int windowBits)
        {
            LZXinit(windowBits);
        }

        public static void Decompress(byte[] source, byte[] destination)
        {
            LZXdecompress(source, source.Length, destination, destination.Length);
        }
    }
}
