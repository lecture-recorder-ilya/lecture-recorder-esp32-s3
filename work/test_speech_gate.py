import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from speech_gate import speech_ranges,overlaps_speech,clips
class GateTest(unittest.TestCase):
 def test_silence(self):self.assertEqual(speech_ranges(np.zeros(16000,dtype=np.float32)),[])
 def test_constant_background(self):self.assertEqual(speech_ranges(np.ones(32000,dtype=np.float32)*.005),[])
 def test_noise(self):self.assertEqual(speech_ranges(np.random.default_rng(5).normal(0,.005,32000).astype(np.float32)),[])
 def test_profiles_share_one_inference_and_clip_final_frame(self):
  from unittest.mock import patch
  from speech_gate import speech_profile
  samples=np.zeros(33*512+13,dtype=np.float32)
  with patch('speech_gate._probabilities',return_value=[0.0]*3+[.97]*31) as infer:
   profile=speech_profile(samples)
   infer.assert_called_once_with(samples)
  self.assertEqual(profile.strict,[(3*512/16000,len(samples)/16000)])
  self.assertEqual(profile.padded,[(0,len(samples)/16000)])
  self.assertEqual(profile.anchored,profile.strict)
 def test_speech_boundaries(self):
  self.assertFalse(overlaps_speech(0,2,[(4,7)]));self.assertTrue(overlaps_speech(4,4.3,[(4,7)]));self.assertEqual(clips([(4,7)]),[4,7])
 def test_monitor_does_not_decode_noise(self):
  from unittest.mock import patch
  import study_service
  pcm=np.random.default_rng(2).normal(0,160,30*16000).astype('<i2').tobytes()
  with patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'read_pcm',return_value=pcm),patch('mlx_whisper.transcribe',side_effect=AssertionError('Decoder must not run')):
   result=study_service.monitor_chunk('fixture.wav',30*16000)
  self.assertEqual(result['segments'],[]);self.assertFalse(result['speech_detected'])
unittest.main()
