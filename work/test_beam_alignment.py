import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'outputs/android/src/ru/ilya/lecturerecorder'
JAVA = Path(os.environ['JAVA_HOME'])/'bin' if 'JAVA_HOME' in os.environ else Path()

HARNESS = '''package ru.ilya.lecturerecorder;
import java.util.Arrays;

public class AlignmentCheck {
    public static void main(String[] args) {
        if (args[0].equals("onset")) {
            System.out.println(PhoneCtc.weakOpeningLetter(args[1], args[2], Math.log(Double.parseDouble(args[3])),
                    Double.parseDouble(args[4])));
            return;
        }
        if (args[0].equals("window")) {
            float[] nextPhrase = {0f, 0f, 0f, 1f/32768f};
            assert PhoneSpeechWindow.constant(nextPhrase, 3);
            assert !PhoneSpeechWindow.constant(nextPhrase, 4);
            return;
        }
        int blank = 3;
        float[][] logits = new float[args.length-1][4];
        for (int t = 0; t < logits.length; t++) {
            Arrays.fill(logits[t], -16f);
            logits[t][blank] = -4f;
            logits[t][Integer.parseInt(args[t+1])] = -.01f;
        }
        System.out.println(Arrays.toString(PhoneCtc.alignment(logits, logits.length, blank)));
    }
}
'''


class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.build = Path(temp.name)
        harness = cls.build/'AlignmentCheck.java'
        harness.write_text(HARNESS)
        subprocess.run([JAVA/'javac', '-d', cls.build, SRC/'PhoneCtc.java',
                        SRC/'PhoneSpeechWindow.java', harness], check=True)

    def decode(self, *args):
        return subprocess.check_output([JAVA/'java', '-ea', '-cp', self.build,
                                       'ru.ilya.lecturerecorder.AlignmentCheck', *map(str, args)], text=True).strip()

    def test_repeated_letters_keep_two_frame_positions_only_with_a_blank(self):
        self.assertEqual(self.decode('ctc', 3,1,3,1,3,2,3,3), '[3, 1, 3, 1, 3, 2, 3, 3]')
        self.assertEqual(self.decode('ctc', 1,1), '[1, 3]')

    def test_one_frame_only_emits_one_label(self):
        self.assertEqual(self.decode('ctc', 1), '[1]')

    def test_unknown_label_does_not_emit_a_word(self):
        self.assertEqual(self.decode('ctc', 0), '[3]')

    def test_empty_window_returns_no_frames(self):
        self.assertEqual(self.decode('ctc'), '[]')

    def test_only_weak_isolated_opening_letter_requests_a_retry(self):
        self.assertEqual(self.decode('onset', 'Д.', '▁Д', .3, 5), 'true')
        for text, token, score, length in [('Д.', '▁Д', .8, 5), ('Д.', '▁Д', .3, .2),
                                           ('Д.', '▁Г', .3, 5), ('9.', '▁9', .2, 3),
                                           ('Да.', '▁Да', .3, 5), ('не', 'не', .2, 2), ('три.', 'три', .3, 2)]:
            self.assertEqual(self.decode('onset', text, token, score, length), 'false')

    def test_silence_check_stops_at_model_input_and_keeps_quiet_speech(self):
        self.assertEqual(self.decode('window'), '')


if __name__ == '__main__':
    unittest.main()
