import sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from speech_gate import anchored_speech_ranges,speech_ranges,overlaps_speech,clips
class GateTest(unittest.TestCase):
 def test_silence(self):self.assertEqual(speech_ranges(np.zeros(16000,dtype=np.float32)),[])
 def test_constant_background(self):self.assertEqual(speech_ranges(np.ones(32000,dtype=np.float32)*.005),[])
 def test_noise(self):self.assertEqual(speech_ranges(np.random.default_rng(5).normal(0,.005,32000).astype(np.float32)),[])
 def test_speech_boundaries(self):
  self.assertFalse(overlaps_speech(0,2,[(4,7)]));self.assertTrue(overlaps_speech(4,4.3,[(4,7)]));self.assertEqual(clips([(4,7)]),[4,7])
 def test_quiet_speech_near_confirmed_phrase(self):
  audio=np.zeros(6*16000,dtype=np.float32)
  rows=[{'start':1920,'end':5120},{'start':80000,'end':85440}]
  with patch('speech_gate._MODEL',object()),patch('silero_vad.get_speech_timestamps',return_value=rows) as detect:
   self.assertEqual(anchored_speech_ranges(audio,[]),[])
   detect.assert_not_called()
   self.assertEqual(anchored_speech_ranges(audio,[(.9,2.6)],recover_quiet=True),[(.12,.32),(.9,2.6)])
   self.assertEqual(detect.call_args.kwargs['threshold'],.50)
   self.assertEqual(detect.call_args.kwargs['min_speech_duration_ms'],160)
 def test_monitor_does_not_decode_noise(self):
  import study_service
  pcm=np.random.default_rng(2).normal(0,160,30*16000).astype('<i2').tobytes()
  with patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'read_pcm',return_value=pcm),patch('mlx_whisper.transcribe',side_effect=AssertionError('Decoder must not run')):
   result=study_service.monitor_chunk('fixture.wav',30*16000)
  self.assertEqual(result['segments'],[]);self.assertFalse(result['speech_detected'])
unittest.main()
