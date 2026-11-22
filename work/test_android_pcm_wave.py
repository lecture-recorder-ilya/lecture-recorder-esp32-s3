import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PCM = bytes.fromhex('0100000000001000800000aa00389b71')


def make_wav(tag=0xfffe, channels=1, rate=16000, bits=16, valid=16, subformat=PCM, extension=22):
    alignment = channels * bits // 8
    fmt = struct.pack('<HHIIHH', tag, channels, rate, rate * alignment, alignment, bits)
    if tag == 0xfffe:
        fmt += struct.pack('<HHI', extension, valid, 4) + subformat
    audio = struct.pack('<4h', 1, -1, 12, -12)
    chunks = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + (b'\0' if len(fmt) % 2 else b'')
    chunks += b'JUNK\x03\x00\x00\x00abc\0data' + struct.pack('<I', len(audio)) + audio
    return b'RIFF' + struct.pack('<I', 4 + len(chunks)) + b'WAVE' + chunks


class PcmWaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(scratch.cleanup)
        cls.folder = Path(scratch.name)
        cls.java = str(Path(os.environ['JAVA_HOME'])/'bin/java') if os.environ.get('JAVA_HOME') else 'java'
        javac = str(Path(os.environ['JAVA_HOME'])/'bin/javac') if os.environ.get('JAVA_HOME') else 'javac'
        probe = cls.folder/'PcmCheck.java'
        probe.write_text('''package ru.ilya.lecturerecorder;
import java.io.*;
public class PcmCheck {
    public static void main(String[] args) throws Exception {
        try (RandomAccessFile in = new RandomAccessFile(args[0], "r")) {
            in.seek(7);
            try {
                long count = PcmWave.seekData(in);
                System.out.print(count + " " + in.readUnsignedByte());
            } catch (IOException ex) { System.out.print("invalid"); }
        }
    }
}''')
        subprocess.run([javac, '--release', '8', '-d', cls.folder,
                        ROOT/'outputs/android/src/ru/ilya/lecturerecorder/PcmWave.java', probe], check=True)

    def check(self, wav):
        path = self.folder/'input.wav'
        path.write_bytes(wav)
        return subprocess.check_output([self.java, '-cp', self.folder, 'ru.ilya.lecturerecorder.PcmCheck', path], text=True)

    def test_classic_and_extensible_find_the_same_pcm(self):
        for tag in (1, 0xfffe):
            with self.subTest(tag=tag):
                self.assertEqual(self.check(make_wav(tag=tag)), '8 1')

    def test_float_and_other_subformats_are_rejected(self):
        for change in [dict(tag=3), dict(subformat=b'\x03'+PCM[1:]), dict(subformat=PCM[:-1]+b'\x00')]:
            with self.subTest(change=change):
                self.assertEqual(self.check(make_wav(**change)), 'invalid')

    def test_truncated_extensions_and_incompatible_formats_are_rejected(self):
        for change in [dict(valid=12), dict(channels=2), dict(rate=48000), dict(bits=24),
                       dict(extension=23), dict(extension=20), dict(subformat=PCM[:12])]:
            with self.subTest(change=change):
                self.assertEqual(self.check(make_wav(**change)), 'invalid')


if __name__ == '__main__':
    unittest.main()
