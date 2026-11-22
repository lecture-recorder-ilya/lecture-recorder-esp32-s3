import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evaluate_asr import audio_sha256, compare_transcripts, score

class EvaluationTests(unittest.TestCase):
 def test_fixed_talk_selection_requires_identifiers_and_checksums(self):
  from prepare_mtedx_asr import PARQUET_SHA256, clip_selection
  row = {'id': 'abcdef01234_0001', 'audio_sha256': 'a' * 64}
  with tempfile.TemporaryDirectory() as temp:
   path = Path(temp) / 'selection.json'
   for clips in ([], [row, row], [dict(row, id='../test')], [dict(row, audio_sha256='bad')]):
    path.write_text(json.dumps({'parquet_sha256': PARQUET_SHA256, 'clips': clips}))
    with self.assertRaises(ValueError):
     clip_selection(path)
   path.write_text(json.dumps({'parquet_sha256': PARQUET_SHA256, 'clips': [row]}))
   self.assertEqual(clip_selection(path), {row['id']: row['audio_sha256']})

 def test_case_punctuation_and_yo_are_equivalent(self):
  self.assertEqual(score('Ещё одна фраза.','ЕЩЕ одна, фраза!')['wer'],0)
 def test_alignment_retains_operation_and_reference_position(self):
  result = score('один два три четыре пять шесть семь',
                 'один другой три пять шесть семь восемь')
  self.assertEqual(result['word_errors'], 3)
  self.assertEqual(result['word_error_breakdown'], {'substitutions': 1, 'deletions': 1, 'insertions': 1})
  self.assertEqual([(edit['op'], edit['reference_index'], edit['reference'], edit['hypothesis'])
                    for edit in result['word_edits']],
                   [('substitutions', 1, 'два', 'другой'), ('deletions', 3, 'четыре', None),
                    ('insertions', None, None, 'восемь')])
 def test_silence_tracks_invented_words_without_division_by_zero(self):
  result=score('','Спасибо за внимание.');self.assertIsNone(result['wer']);self.assertEqual(result['hallucinated_words'],3)
  self.assertEqual(score('','')['hallucinated_words'],0)
 def test_important_numbers_and_negations_remain_distinct(self):
  self.assertEqual(score('не равно пять','равно шесть')['word_errors'],2)
  self.assertGreater(score('пять','5')['wer'],0)
  self.assertEqual(score('до тридцати','до двадцати')['numeric_tokens'], {'missed': 1, 'extra': 1})
  self.assertEqual(score('150 копий','153й год')['numeric_tokens'], {'missed': 1, 'extra': 1})

 def test_critical_phrases_count_scope_separately_from_negation_tokens(self):
  result = score('Не применять метод Гаусса. Вектор равен пяти.',
                 'Применять метод Гаусса. Вектор не равен шести.',
                 ['не применять', 'метод Гаусса'])
  self.assertEqual(result['critical_phrases'], {'missed': 1, 'extra': 0})
  self.assertEqual(result['negations'], {'missed': 0, 'extra': 0})
  self.assertEqual(result['numeric_tokens'], {'missed': 1, 'extra': 1})
  self.assertEqual(score('в пятницу не будет пары', 'будет пары')['numeric_tokens'],
                   {'missed': 0, 'extra': 0})

 def test_rejects_critical_phrase_outside_reference(self):
  with self.assertRaisesRegex(ValueError, 'отсутствует в эталоне'):
   score('исходный текст', 'текст', ['другая фраза'])

 def test_comparison_uses_common_wav_hash_and_separate_noise_score(self):
  with tempfile.TemporaryDirectory() as temp:
   directory = Path(temp)
   speech, noise = directory / 'speech.wav', directory / 'noise.wav'
   for signal, path in [(b'\x01\x00', speech), (b'\x00\x00', noise)]:
    with wave.open(str(path), 'wb') as audio:
     audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
     audio.writeframes(signal)
   manifest = directory / 'manifest.json'
   manifest.write_text(json.dumps([
       dict(id='speech', audio=speech.name, subset='clean', reference='не больше пяти',
            critical_phrases=['не больше']),
       dict(id='noise', audio=noise.name, subset='control', reference=''),
   ]))
   clean = [
       dict(id='speech', audio_sha256=audio_sha256(speech), text='не больше пяти'),
       dict(id='noise', audio_sha256=audio_sha256(noise), text=''),
   ]
   other = [dict(clean[0], text='больше пяти'), dict(clean[1], text='лишний текст')]
   first, second = directory / 'first.json', directory / 'second.json'
   first.write_text(json.dumps({'cases': clean}))
   second.write_text(json.dumps(other))
   paths = {'ClipMic': first, 'Другой движок': second}
   reports = compare_transcripts(manifest, paths)['systems']
   self.assertEqual(reports['ClipMic']['summary']['wer'], 0)
   summary = reports['Другой движок']['summary']
   self.assertAlmostEqual(summary['wer'], 1 / 3)
   self.assertEqual(summary['hallucinated_words'], 2)
   self.assertEqual(summary['failed_noise_cases'], 1)
   subsets = reports['Другой движок']['subsets']
   self.assertEqual(subsets['clean']['clips'], 1)
   self.assertAlmostEqual(subsets['clean']['wer'], 1 / 3)
   self.assertEqual(subsets['control']['hallucinated_words'], 2)
   self.assertIsNone(subsets['control']['wer'])
   other[1]['audio_sha256'] = audio_sha256(speech)
   second.write_text(json.dumps(other))
   with self.assertRaisesRegex(ValueError, 'SHA-256'):
    compare_transcripts(manifest, paths)
   second.write_text(json.dumps(other[:1]))
   with self.assertRaisesRegex(ValueError, 'состав записей'):
    compare_transcripts(manifest, paths)

if __name__=='__main__':unittest.main()
