import sys,tempfile,wave,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import qwen_transcribe,study_service
class QwenTests(unittest.TestCase):
 def test_full_record_resume_and_original_backup(self):
  from quality_asr import Decoder
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);audio=root/'lecture.wav';result=root/'result.json';progress=root/'progress.json'
   with wave.open(str(audio),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes((np.ones(41*16000)*300).astype('<i2').tobytes())
   result.with_suffix('.transcript.json').write_text(json.dumps({'engine':'Whisper','complete':True,'segments':[{'text':'original'}]}))
   with patch('speech_gate.strict_speech_ranges',return_value=[(0,1)]),patch('speech_gate.speech_ranges',return_value=[(0,1)]),patch.object(Decoder,'transcribe',return_value='Историческая лекция.' ) as decode,patch('power_budget.Budget.checkpoint'):
    qwen_transcribe.run(audio,result,progress);self.assertEqual(decode.call_count,3)
    qwen_transcribe.run(audio,result,progress);self.assertEqual(decode.call_count,3)
   data=json.loads(result.with_suffix('.transcript.json').read_text())
   self.assertTrue(data['complete']);self.assertEqual(data['completed_frames'],41*16000);self.assertEqual(len(data['segments']),3)
   backups=list(root.glob('*before-quality*'));self.assertEqual(len(backups),1);self.assertEqual(json.loads(backups[0].read_text())['engine'],'Whisper')
 def test_live_once_per_excerpt(self):
  study_service.QUALITY_CURSOR.update(file=None,end=0)
  pcm=(np.ones(12*16000)*300).astype('<i2').tobytes()
  with patch.object(study_service,'quality_ready',return_value=True),patch.object(study_service,'read_pcm',return_value=pcm),patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'strict_speech_ranges',return_value=[(0,12)]),patch.object(study_service,'speech_ranges',return_value=[(0,12)]),patch.object(study_service.QUALITY_DECODER,'transcribe',return_value='Преподаватель объясняет тему.') as decode:
   a=study_service.monitor_quality('fixture.wav',199200);b=study_service.monitor_quality('fixture.wav',199200)
   self.assertEqual(decode.call_count,1);self.assertEqual(len(a['segments']),1);self.assertEqual(b['segments'],[])
 def test_live_retry_keeps_cursor(self):
  study_service.QUALITY_CURSOR.update(file='fixture.wav',end=0)
  pcm=(np.ones(12*16000)*300).astype('<i2').tobytes()
  with patch.object(study_service,'quality_ready',return_value=True),patch.object(study_service,'read_pcm',return_value=pcm),patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'strict_speech_ranges',return_value=[(0,12)]),patch.object(study_service,'speech_ranges',return_value=[(0,12)]),patch.object(study_service.QUALITY_DECODER,'transcribe',side_effect=RuntimeError('fixture')):
   with self.assertRaises(RuntimeError):study_service.monitor_quality('fixture.wav',199200)
   self.assertEqual(study_service.QUALITY_CURSOR['end'],0)
 def test_live_waits_for_complete_phrase(self):
  study_service.QUALITY_CURSOR.update(file='fixture.wav',end=0)
  with patch.object(study_service,'quality_ready',return_value=True),patch.object(study_service,'read_pcm') as read:
   for total in [64000,128000,192000]:
    row=study_service.monitor_quality('fixture.wav',total);self.assertEqual(row['segments'],[])
   read.assert_not_called();self.assertEqual(study_service.QUALITY_CURSOR['end'],0)
 def test_stopped_recording_flushes_short_tail_once(self):
  study_service.QUALITY_CURSOR.update(file='fixture.wav',end=0)
  pcm=(np.ones(4*16000)*300).astype('<i2').tobytes()
  with patch.object(study_service,'quality_ready',return_value=True),patch.object(study_service,'read_pcm',return_value=pcm),patch.object(study_service.store,'audio',return_value=Path('fixture.wav')),patch.object(study_service,'strict_speech_ranges',return_value=[(0,4)]),patch.object(study_service,'speech_ranges',return_value=[(0,4)]),patch.object(study_service.QUALITY_DECODER,'transcribe',return_value='Конец занятия.') as decode:
   a=study_service.monitor_quality('fixture.wav',64000,flush=True);b=study_service.monitor_quality('fixture.wav',64000,flush=True)
   self.assertEqual(decode.call_count,1);self.assertEqual(len(a['segments']),1);self.assertEqual(b['segments'],[]);self.assertEqual(study_service.QUALITY_CURSOR['end'],64000)
unittest.main()
