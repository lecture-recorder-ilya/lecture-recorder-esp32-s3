import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from speech_gate import SpeechProfile
from asr_policy import selected_model
from asr_windows import audio_window,central_segment
from transcript_cache import identity,prepare,checkpoint,WHISPER_ENGINE
import ai_worker
import qwen_transcribe
from quality_asr import Decoder,ENGINE


def voiced_profile(samples):
 ranges=[(0,len(samples)/16000)]
 return SpeechProfile(ranges,ranges,ranges)

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'recordings').mkdir();(self.root/'study').mkdir()
  self.audio=self.root/'recordings/lecture-2026-10-12-10-00-00.wav'
  with wave.open(str(self.audio),'wb') as stream:
   stream.setparams((1,2,16000,0,'NONE','none'));stream.writeframes(b'\x2c\x01'*(41*16000))
  self.cache=self.root/'result.transcript.json'
 def tearDown(self):self.tmp.cleanup()
 def test_auto_uses_available_model_and_manual_choice_is_kept(self):
  self.assertEqual(selected_model('auto',True),'qwen')
  self.assertEqual(selected_model('auto',False),'whisper')
  self.assertEqual(selected_model('whisper',True),'whisper')
  self.assertEqual(selected_model('qwen',False),'qwen')
  with self.assertRaises(ValueError):selected_model('unknown',True)
 def test_boundary_word_is_emitted_once(self):
  row={'words':[{'word':'до','start':19.4,'end':19.8},{'word':'граница','start':19.8,'end':20.2},{'word':'после','start':20.3,'end':20.8}]}
  first=central_segment(row,0,20);second=central_segment(row,20,40)
  self.assertEqual(first['text'],'до');self.assertEqual(second['text'],'граница после')
  self.assertEqual(second['start'],20)
  self.assertEqual(audio_window(320000,320000,656000),(288000,656000))
 def test_audio_change_invalidates_and_preserves_old_cache(self):
  old=identity(self.audio,ENGINE);self.cache.write_text(json.dumps(checkpoint(old,[],41,656000,True)))
  with self.audio.open('r+b') as stream:stream.seek(44);stream.write(b'\x00\x00')
  fresh=identity(self.audio,ENGINE);self.assertNotEqual(old,fresh)
  self.assertFalse(prepare(self.cache,fresh,656000,320000)['complete'])
  self.assertEqual(json.loads(next(self.root.glob('*before-quality*')).read_text())['identity'],old)
 def test_changed_terms_in_merged_source_invalidate_cache(self):
  merged=self.root/'study/lecture-2026-10-12-10-00-00.notes.json'
  merged.write_text(json.dumps({'parts':[{'file':'source.wav','start':0,'duration':41}]}))
  source=self.root/'study/source.notes.json';source.write_text(json.dumps({'asr_terms':'Коши'}))
  first=identity(self.audio,ENGINE);source.write_text(json.dumps({'asr_terms':'Вейерштрасс'}))
  self.assertNotEqual(first,identity(self.audio,ENGINE))
 def test_invalid_cache_is_archived(self):
  expected=identity(self.audio,ENGINE)
  for frames in (-1,1,656001):
   self.cache.write_text(json.dumps(checkpoint(expected,[],41,frames)))
   self.assertEqual(prepare(self.cache,expected,656000,320000)['completed_frames'],0)
  self.cache.write_text('{broken')
  self.assertFalse(prepare(self.cache,expected,656000,320000)['complete'])
  self.assertEqual(len(list(self.root.glob('*before-quality*'))),4)
 def test_engine_switch_cannot_reuse_previous_transcript(self):
  expected=identity(self.audio,ENGINE);self.cache.write_text(json.dumps(checkpoint(expected,[],41,656000,True)))
  fresh=prepare(self.cache,identity(self.audio,WHISPER_ENGINE),656000,480000)
  self.assertFalse(fresh['complete']);self.assertEqual(fresh['engine'],WHISPER_ENGINE)
 def test_quality_resume_uses_context_and_does_not_repeat_completed_chunk(self):
  expected=identity(self.audio,ENGINE)
  self.cache.write_text(json.dumps(checkpoint(expected,[{'id':0,'start':0,'end':20,'text':'Первая часть.'}],41,320000)))
  with patch('speech_gate.speech_profile',side_effect=voiced_profile),patch.object(Decoder,'transcribe',return_value='Продолжение лекции.') as decode,patch('power_budget.Budget.checkpoint'):
   qwen_transcribe.run(self.audio,self.root/'result.json',self.root/'progress.json')
  self.assertEqual([len(c.args[0]) for c in decode.call_args_list],[23*16000,3*16000])
  self.assertEqual([c.kwargs['emit_start'] for c in decode.call_args_list],[2,2])
  rows=json.loads(self.cache.read_text())['segments'];self.assertEqual([r['start'] for r in rows],[0,20,40])
 def test_whisper_pipeline_uses_context_and_reuses_matching_cache(self):
  mx=types.ModuleType('mlx.core');mx.gpu='gpu';mx.synchronize=lambda *_:None
  mlx=types.ModuleType('mlx');mlx.core=mx;whisper=types.ModuleType('mlx_whisper')
  import numpy as np
  calls=[]
  def decode(samples,**kwargs):
   calls.append(len(samples))
   words=([{'word':'До','start':29.4,'end':29.8},{'word':'граница','start':29.8,'end':30.2},{'word':'после','start':30.3,'end':30.8}] if len(calls)==1 else [{'word':'граница','start':1.8,'end':2.2},{'word':'после','start':2.3,'end':2.8}])
   return {'segments':[{'text':'До граница после','words':words}]}
  whisper.transcribe=decode
  with patch.dict(sys.modules,{'mlx':mlx,'mlx.core':mx,'mlx_whisper':whisper}),patch.object(ai_worker,'speech_ranges',side_effect=lambda x:[(0,len(x)/16000)]),patch.object(ai_worker,'strict_speech_ranges',side_effect=lambda x:[(0,len(x)/16000)]),patch.object(ai_worker,'supported_words',return_value=True),patch.object(ai_worker,'usable',return_value=True),patch('power_budget.Budget.checkpoint'):
   ai_worker.run(self.audio,self.root/'result.json',self.root/'progress.json',True)
   ai_worker.run(self.audio,self.root/'result.json',self.root/'progress.json',True)
  self.assertEqual(calls,[32*16000,13*16000])
  rows=json.loads(self.cache.read_text())['segments'];self.assertEqual([r['text'] for r in rows],['До','граница после'])
  self.assertEqual([r['start'] for r in rows],[29.4,30])


if __name__=='__main__':unittest.main()
