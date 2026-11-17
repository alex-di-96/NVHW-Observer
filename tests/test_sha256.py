import ctypes
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest


class Context(ctypes.Structure):
    _fields_ = [('h',ctypes.c_uint32*8),('bytes',ctypes.c_uint64),
                ('used',ctypes.c_size_t),('block',ctypes.c_ubyte*64)]


class HashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        library = Path(cls.temp.name)/'sha.so'
        source = Path(__file__).resolve().parents[1]/'uefi/sha256.c'
        subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                        str(source),'-o',str(library)],check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.nvhw_sha256_update.argtypes = [ctypes.POINTER(Context),ctypes.c_void_p,ctypes.c_size_t]

    def digest(self,data,chunk):
        ctx=Context();self.lib.nvhw_sha256_init(ctypes.byref(ctx))
        for i in range(0,len(data),chunk):
            part=data[i:i+chunk];self.lib.nvhw_sha256_update(ctypes.byref(ctx),part,len(part))
        out=(ctypes.c_ubyte*32)();self.lib.nvhw_sha256_final(ctypes.byref(ctx),out)
        return bytes(out)

    def test_known_vectors(self):
        for data in (b'',b'abc',b'a'*1000000):
            self.assertEqual(self.digest(data,4096),hashlib.sha256(data).digest())

    def test_block_boundaries_and_streaming(self):
        for n in (1,55,56,63,64,65,127,128,129,65536,65537):
            data=bytes(i%251 for i in range(n))
            for chunk in (1,7,64,1024,4096):
                self.assertEqual(self.digest(data,chunk),hashlib.sha256(data).digest(),(n,chunk))


if __name__=='__main__':unittest.main()
