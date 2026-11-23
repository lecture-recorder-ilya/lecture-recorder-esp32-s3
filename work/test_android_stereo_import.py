import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


JAVA = Path(__file__).resolve().parents[1] / 'outputs/android/src/ru/ilya/lecturerecorder'
HEADER = b'header'
PROBE = '''package ru.ilya.lecturerecorder;
import java.io.*;
import java.nio.*;
import java.nio.file.*;

public class StereoProbe {
    public static void main(String[] args) throws Exception {
        ByteBuffer input = ByteBuffer.wrap(Files.readAllBytes(Paths.get(args[0]))).order(ByteOrder.LITTLE_ENDIAN);
        File target = new File(args[1]);
        int rate = Integer.parseInt(args[2]);
        String mode = args[3];
        StereoPcmMix mix = new StereoPcmMix();
        try (OutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
            out.write(new byte[]{104, 101, 97, 100, 101, 114});
            PcmResampler resampler = new PcmResampler(out, rate);
            while (input.hasRemaining()) {
                if (mode.equals("candidate")) {
                    ByteBuffer chunk = input.slice();
                    chunk.limit(Math.min(1028, chunk.remaining()));
                    mix.consume(chunk, resampler);
                    input.position(input.position() + chunk.position());
                } else {
                    int left = input.getShort();
                    int right = input.getShort();
                    resampler.sample(mode.equals("left") ? left : (left + right) / 2.0);
                }
            }
            resampler.finish();
        }
        if (mode.equals("candidate")) mix.finish(target, 6);
    }
}
'''


class StereoImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(scratch.cleanup)
        cls.root = Path(scratch.name)
        bindir = Path(os.environ['JAVA_HOME'])/'bin' if os.environ.get('JAVA_HOME') else Path()
        cls.java = str(bindir/'java')
        probe = cls.root/'StereoProbe.java'
        probe.write_text(PROBE)
        subprocess.run([str(bindir/'javac'), '--release', '8', '-d', cls.root,
                        JAVA/'PcmResampler.java', JAVA/'StereoPcmMix.java', probe], check=True)

    def convert(self, audio, mode, rate=16000):
        source = self.root/'input.pcm'
        target = self.root/'output.wav'
        source.write_bytes(audio)
        subprocess.run([self.java, '-cp', self.root, 'ru.ilya.lecturerecorder.StereoProbe',
                        source, target, str(rate), mode], check=True, capture_output=True)
        result = target.read_bytes()
        self.assertEqual(result[:len(HEADER)], HEADER)
        return result[len(HEADER):]

    def test_inverted_signal_is_bit_exact_across_input_chunks(self):
        source = (0, 1, -1, -32767, 32767, 182) * 200
        audio = b''.join(struct.pack('<hh', left, -left) for left in source)
        expected = struct.pack('<' + 'h' * len(source), *source)
        self.assertEqual(self.convert(audio, 'candidate'), expected)
        self.assertEqual(self.convert(audio, 'mean'), bytes(len(expected)))

    def test_downmix_resampler_state_when_only_the_last_frames_differ(self):
        audio = struct.pack('<hh', 32000, -32000) * 34001 + struct.pack('<4h', 7, -6, -30, 125)
        for rate in (8000, 16000, 22050, 44100, 48000, 96000):
            with self.subTest(rate=rate):
                self.assertEqual(self.convert(audio, 'candidate', rate), self.convert(audio, 'mean', rate))

    def test_alternating_phase_stays_on_the_mean_after_first_difference(self):
        audio = struct.pack('<8h', 27, -27, 2, 5, 30000, -30000, -32768, -32768) * 300
        self.assertEqual(self.convert(audio, 'candidate'), self.convert(audio, 'mean'))

    def test_silence_stays_silent(self):
        self.assertEqual(self.convert(bytes(1036), 'candidate'), bytes(518))

    def test_exact_antiphase_is_resampled_like_one_channel(self):
        audio = struct.pack('<6h', 984, -984, 3215, -3215, -32767, 32767) * 341
        for rate in (8000, 44100, 48000):
            with self.subTest(rate=rate):
                self.assertEqual(self.convert(audio, 'candidate', rate), self.convert(audio, 'left', rate))

    def test_partial_stereo_frame_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.convert(b'\x00\x00\x01', 'candidate')


if __name__ == '__main__':
    unittest.main()
