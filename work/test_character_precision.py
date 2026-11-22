import hashlib
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
import character_weights
import quality_asr
from quality_asr import Decoder
from speech_gate import SpeechProfile


def result(tokens, times=None, confidence=.99):
    if times is None:
        times = [.48 + .28 * index for index in range(len(tokens))]
    return SimpleNamespace(tokens=tokens, timestamps=times, logprobs=[math.log(confidence)] * len(tokens))


class CharacterPrecisionTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        data = b'compact character model'
        self.compact = folder / character_weights.FILENAME
        self.compact.write_bytes(data)
        self.enterContext(patch.object(quality_asr, 'CHAR', folder))
        self.enterContext(patch.multiple(character_weights, SIZE=len(data), SHA256=hashlib.sha256(data).hexdigest()))
        self.audio = np.ones(32000, dtype=np.float32) * .02
        self.profile = SpeechProfile([(0, 2)], [(0, 2)], [(0, 2)])
        self.decoder = Decoder()
        self.models = {}
        self.outputs(['Смотрим', ' записи.'])

    def outputs(self, words, confidence=.76):
        for kind, output in [
            ('ctc', result(words)),
            ('rnnt', result(words, confidence=confidence)),
            ('char', result(words)),
            ('char_fast', result(words)),
        ]:
            self.models[kind] = Mock(recognize=Mock(return_value=output))

    def decode(self, *, terms=None):
        with patch.object(self.decoder, '_load', side_effect=self.models.__getitem__) as load:
            text = self.decoder.transcribe(self.audio, speech=self.profile, terms=terms)
        return text, [call.args[0] for call in load.call_args_list]

    def test_ordinary_speech_uses_optional_fast_pass(self):
        self.assertEqual(self.decode(), ('Смотрим записи.', ['ctc', 'rnnt', 'char_fast']))

    def test_older_installation_uses_full_precision(self):
        self.compact.unlink()
        self.decoder = Decoder()
        self.assertEqual(self.decode(), ('Смотрим записи.', ['ctc', 'rnnt', 'char']))

    def test_refresh_respects_explicit_full_precision(self):
        self.decoder = Decoder(allow_fast_character=False)
        self.decoder.refresh_character_model()
        self.assertEqual(self.decoder.engine, quality_asr.BASE_ENGINE)
        self.assertEqual(self.decode(), ('Смотрим записи.', ['ctc', 'rnnt', 'char']))

    def test_user_terms_use_full_precision(self):
        self.assertEqual(self.decode(terms=['записи']), ('Смотрим записи.', ['ctc', 'rnnt', 'char']))

    def test_digits_and_spoken_currency_use_full_precision(self):
        for words in (['Было', ' —15.'], ['Курс', ' доллара.'], ['Вычитаем', ' проценты.']):
            with self.subTest(words=words):
                self.outputs(words)
                self.assertEqual(self.decode()[1], ['ctc', 'rnnt', 'char'])

    def test_spoken_numbers_use_full_precision_without_digits_or_units(self):
        for numeral in ('пять', 'семьдесят', 'полтора', 'полутора', 'семидесяти', 'четыреста'):
            with self.subTest(numeral=numeral):
                self.outputs(['Получается', f' {numeral}.'])
                self.assertEqual(self.decode()[1], ['ctc', 'rnnt', 'char'])

    def test_similar_conversational_words_leave_fast_pass_enabled(self):
        self.outputs(['Вот', ' семинар', ' в', ' пятницу.'])
        self.assertEqual(self.decode()[1], ['ctc', 'rnnt', 'char_fast'])

    def test_currency_in_other_pass_or_shared_sign_uses_full_precision(self):
        for accepted, other in (
            (['Читаем', ' строку.'], ['Читаем', ' доллары.']),
            (['Читаем', ' строку', ' ₽.'], ['Читаем', ' строку', ' ₽.']),
        ):
            with self.subTest(other=other):
                self.outputs(accepted)
                self.models['ctc'].recognize.return_value = result(other)
                self.assertEqual(self.decode()[1], ['ctc', 'rnnt', 'char'])

    def test_currency_heard_only_in_fast_pass_is_rechecked(self):
        self.models['char_fast'].recognize.return_value = result(['Смотрим', ' доллары.'])
        self.assertEqual(self.decode(), ('Смотрим записи.', ['ctc', 'rnnt', 'char_fast', 'char']))
        self.assertFalse(self.decoder.last['refinements'])

    def test_quiet_and_brief_consensus_use_full_precision(self):
        self.profile = SpeechProfile([], [], [], quiet=((.20, 1.70),))
        self.outputs(['Смотрим', ' записи.'])
        self.assertEqual(self.decode(), ('Смотрим записи.', ['ctc', 'rnnt', 'char']))

        self.profile = SpeechProfile([], [(.20, .80)], [], brief=((.40, .60),))
        self.models['rnnt'].recognize.return_value = result(['Начали.'], [.63])
        self.models['char'].recognize.return_value = result(['начали'], [.63])
        self.assertEqual(self.decode(), ('Начали.', ['rnnt', 'char']))


if __name__ == '__main__':
    unittest.main()
