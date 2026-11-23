"""Плотная 90-минутная проба не подменяется файлом с длинной тишиной."""
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from benchmark_asr_resume import build_wav


class Tests(unittest.TestCase):
    def test_dense_wav_has_exact_duration_and_unchanged_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav';payload=(b'\x34\x12'*16000)
            with wave.open(str(source),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(payload)
            output=root/'dense.wav';seconds=build_wav(output,[source],1,True,.01)
            with wave.open(str(output)) as stream:
                self.assertEqual(stream.getnframes(),60*16000)
                self.assertEqual(stream.readframes(16000),payload)
            self.assertGreater(seconds,59)

    def test_old_sparse_mode_stays_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav'
            with wave.open(str(source),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(b'\x01\x00'*1600)
            self.assertAlmostEqual(build_wav(root/'sparse.wav',[source],1),.1)


if __name__=='__main__':unittest.main()
