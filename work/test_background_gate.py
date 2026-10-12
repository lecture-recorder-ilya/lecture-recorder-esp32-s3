import sys,unittest,wave
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import numpy as np
from unittest.mock import patch
import study_service
class BackgroundTest(unittest.TestCase):
 def test_weak_vad_does_not_decode(self):
  pcm=(np.ones(30*16000)*300).astype('<i2').tobytes()
  with patch.object(study_service,'read_pcm',return_value=pcm),patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'speech_ranges',return_value=[(28,30)]),patch.object(study_service,'strict_speech_ranges',return_value=[]),patch('mlx_whisper.transcribe',side_effect=AssertionError('Unexpected decode')):
   result=study_service.monitor_chunk('fixture.wav',480000)
  self.assertEqual(result['segments'],[]);self.assertFalse(result['speech_detected'])
 def test_real_noise_fixtures(self):
  from speech_gate import strict_speech_ranges
  for name in ('short-noise','noise-thanks','quiet-background'):
   with wave.open('work/asr-benchmark/'+name+'.wav') as w:x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
   self.assertEqual(strict_speech_ranges(x),[],name)
 def test_lecture_kept(self):
  from speech_gate import strict_speech_ranges
  with wave.open('work/asr-benchmark/history-names.wav') as w:x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
  self.assertGreater(sum(b-a for a,b in strict_speech_ranges(x)),20)
unittest.main()
