from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from asr_qa import validate_lecture_splits
from compare_lecture_asr import attach_speakers, average, report_rows, sensitivity
from evaluate_asr import audio_sha256
from prepare_long_asr import caption_coverage, continuous_window, parse_vtt
from prepare_lecture_review import verify_manual


class LectureControlTests(unittest.TestCase):
    def test_webvtt_timing_tags_and_overlap(self):
        vtt = ('WEBVTT\n\n00:00:01.100 --> 00:00:03.000\n<i>Не 15, а 50.</i>\n\n'
               '00:00:02.800 --> 00:00:04.100\nДальше.\n')
        cues = parse_vtt(vtt)
        self.assertEqual(cues[0], dict(start=1.1, end=3, text='Не 15, а 50.'))
        self.assertAlmostEqual(caption_coverage(cues, 1.1), 3)

    def test_window_stays_contiguous_and_keeps_complete_cues(self):
        cues = [dict(start=i, end=i+4, text='Фраза.') for i in range(0, 180, 5)]
        group, start, end = continuous_window(cues)
        self.assertEqual(start, group[0]['start'])
        self.assertEqual(end, group[-1]['end'])
        self.assertEqual(start, 15)
        self.assertTrue(120 <= end-start <= 150)

    def test_cannot_split_one_lecture_or_known_speaker(self):
        a = dict(id='a', lecture_id='x', speaker_id='one', subset='lecture_tune', reference_type='subtitles')
        b = dict(a, id='b', lecture_id='y', subset='lecture_holdout')
        with self.assertRaisesRegex(ValueError, 'speaker_id'):
            validate_lecture_splits([a, b])
        with self.assertRaisesRegex(ValueError, 'lecture_id'):
            validate_lecture_splits([a, dict(b, lecture_id='x', speaker_id='two')])
        validate_lecture_splits([a, dict(b, speaker_id='two')])

    def test_machine_text_is_not_a_reference(self):
        with self.assertRaisesRegex(ValueError, 'немашинный эталон'):
            validate_lecture_splits([dict(id='a', lecture_id='x', subset='lecture_tune', reference_type='machine')])

    def test_manual_review_requires_label_same_audio_and_reviewer(self):
        row = dict(id='a', audio_sha256='same', manual_review=None)
        self.assertFalse(verify_manual(row))
        entry = dict(reference_type='machine', audio_sha256='same', text='Не 15.',
                     reviewer='R1', checked_at='2026-11-22')
        row['manual_review'] = entry
        with self.assertRaisesRegex(ValueError, 'ручная сверка'):
            verify_manual(row)
        entry['reference_type'] = 'manual_verified'
        self.assertTrue(verify_manual(row))
        entry['audio_sha256'] = 'other'
        with self.assertRaisesRegex(ValueError, 'совпадающего WAV'):
            verify_manual(row)

    def test_weighted_and_per_lecture_means_and_speaker_removal(self):
        def row(lecture, speaker, words, errors):
            return dict(lecture_id=lecture, speaker_id=speaker, reference_words=words,
                        word_error_breakdown=dict(substitutions=errors, deletions=0, insertions=0))
        rows = [row('A', 'speaker1', 60, 6), row('B', 'speaker1', 40, 4), row('C', 'speaker2', 20, 10)]
        self.assertAlmostEqual(average(rows)['micro'], 20/120)
        self.assertAlmostEqual(average(rows)['macro'], (.1+.1+.5)/3)
        self.assertEqual(sensitivity(rows)['speaker:speaker1'], dict(micro=.5, macro=.5))
        self.assertEqual(sensitivity(rows)['speaker:speaker2'], dict(micro=.1, macro=.1))


    def test_speaker_sources_must_match_and_stay_in_one_split(self):
        a = dict(id='a', lecture_id='A', source_video='one', subset='lecture_tune', reference_type='subtitles')
        b = dict(a, id='b', lecture_id='B', source_video='two', subset='lecture_holdout')
        cases = dict(a=a, b=b)
        speakers = dict(A=dict(speaker='First', source_video='one'), B=dict(speaker='Second', source_video='two'))
        self.assertEqual(attach_speakers(cases, speakers)['b']['speaker_id'], 'Second')
        speakers['B']['speaker'] = 'First'
        with self.assertRaisesRegex(ValueError, 'speaker_id'):
            attach_speakers(cases, speakers)
        speakers['B']['source_video'] = 'one'
        with self.assertRaisesRegex(ValueError, 'исходным видео'):
            attach_speakers(cases, speakers)

    def test_comparison_rejects_changed_wav_or_reference_count(self):
        with TemporaryDirectory() as directory:
            lock = Path(directory) / 'lock.json'
            lock.write_text('{}')
            cases = dict(x=dict(audio_sha256='wav-sha', subset='lecture_holdout',
                                lecture_id='clip', reference='Не пятнадцать.'))
            score = dict(id='x', audio_sha256='wav-sha', subset='lecture_holdout', reference_words=2)
            report = dict(platform='mac', lock_sha256=audio_sha256(lock), manifest_sha256='manifest-sha',
                          revision='base', cases=[score])
            manifest = dict(manifest_sha256='manifest-sha')
            self.assertEqual(report_rows(report, cases, lock, manifest)[0]['lecture_id'], 'clip')
            score['audio_sha256'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'метаданные или WAV'):
                report_rows(report, cases, lock, manifest)
            score.update(audio_sha256='wav-sha', reference_words=1)
            with self.assertRaisesRegex(ValueError, 'метаданные или WAV'):
                report_rows(report, cases, lock, manifest)


if __name__ == '__main__':
    unittest.main()
