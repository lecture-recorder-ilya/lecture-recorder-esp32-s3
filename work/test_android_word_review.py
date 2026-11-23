import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/android/src/ru/ilya/lecturerecorder'
HARNESS = r'''package ru.ilya.lecturerecorder;
import java.util.*;
import org.json.*;
public final class WordReviewTest {
 static JSONObject row(String text) throws Exception {
  return new JSONObject().put("text",text).put("start",10).put("end",14).put("needs_review",true);
 }
 static JSONObject word(String text,double conf) throws Exception {
  return new JSONObject().put("word",text).put("start",10).put("end",11).put("conf",conf);
 }
 public static void main(String[] args) throws Exception {
  JSONObject row; List<TranscriptReview.Item> words;
  switch(args[0]) {
   case "critical":
    for(String value:new String[]{"3","−1,25","трёх","пятидесяти","миллионов"})
     assert TranscriptReview.kind(value).equals("number"):value;
    for(String value:new String[]{"НЕ","ни","нет","без"})
     assert TranscriptReview.kind(value).equals("negation"):value;
    for(String value:new String[]{"сантиметров","килограммах","рублей","рублём","секунд","мл","%","₽"})
     assert TranscriptReview.kind(value).equals("unit"):value;
    words=TranscriptReview.words(row("−1,25 кг"));
    assert words.size()==2 && words.get(0).text.equals("−1,25") && words.get(1).kind.equals("unit");
    break;
   case "boundaries":
    for(String value:new String[]{"небо","трибуна","семья","стоимость","метрика","неверно","единица","с"})
     assert TranscriptReview.kind(value).equals("word"):value;
    assert TranscriptReview.words(row("С миром в семье")).isEmpty();
    words=TranscriptReview.words(row("Три м с краю"));
    assert words.size()==2 && words.get(1).kind.equals("unit");
    break;
   case "direct":
    PhonePhrases phrases=new PhonePhrases();
    phrases.accept(new JSONArray().put(word("Не",.99).put("speech_conf",.4))
      .put(word("пример",.99).put("needs_review",true)).put(word("три.",.99)));
    row=phrases.finish().getJSONObject(0);words=TranscriptReview.words(row);
    assert row.getJSONArray("word_reviews").length()==2 && words.size()==3;
    assert words.get(0).direct && words.get(1).direct && !words.get(2).direct;
    assert words.get(2).kind.equals("number") && words.get(2).first==10;
    break;
   case "average":
    PhonePhrases phrases2=new PhonePhrases();
    phrases2.accept(new JSONArray().put(word("Три",.7)).put(word("метра.",.8)));
    row=phrases2.finish().getJSONObject(0);
    assert row.getBoolean("needs_review") && row.getJSONArray("word_reviews").length()==0;
    words=TranscriptReview.words(row);
    assert words.size()==2 && !words.get(0).direct && !words.get(1).direct;
    row.put("needs_review",false);assert TranscriptReview.words(row).isEmpty();
    break;
   case "seek":
    row=row("😀 Не три.").put("word_times",new JSONArray().put(new JSONArray("[3,5,11240]"))
       .put(new JSONArray("[6,10,12000]")));
    words=TranscriptReview.words(row);
    assert words.size()==2 && words.get(0).first==3 && words.get(0).millis==11240;
    assert words.get(0).timedWord && words.get(1).millis==12000;
    assert row.getString("text").substring(words.get(0).first,words.get(0).last).equals("Не");
    break;
   case "legacy":
    words=TranscriptReview.words(row("Не три метра"));
    assert words.size()==3;
    for(TranscriptReview.Item item:words)assert !item.direct && !item.timedWord && item.millis==10000;
    assert TranscriptReview.words(new JSONObject().put("text","Три").put("needs_review",true)).get(0).millis==-1;
    break;
   case "invalid":
    row=row("Не три").put("word_times",new JSONArray("[[-1,2,11000],[0,99,11000],[0,2,9998],[3,6,14002]]"))
       .put("word_reviews",new JSONArray("[[-1,2],[0,99]]"));
    for(TranscriptReview.Item item:TranscriptReview.words(row))assert !item.direct && !item.timedWord && item.millis==10000;
    row.put("start",-1);
    for(TranscriptReview.Item item:TranscriptReview.words(row))assert item.millis==-1;
    break;
   case "flush":
    List<JSONObject> preview=new ArrayList<>();PhonePhrases live=new PhonePhrases(preview::add);
    live.accept(new JSONArray().put(word("Не.",.4)).put(word("Три.",.99).put("start",12).put("end",13)));
    JSONArray result=live.finish();
    assert result.length()==2 && preview.size()==2;
    assert preview.get(0).getJSONArray("word_reviews").getJSONArray(0).getInt(0)==0;
    assert preview.get(1).getJSONArray("word_reviews").length()==0;
    assert !preview.get(1).getBoolean("needs_review");
    assert live.finish().length()==2 && preview.size()==2;
    break;
   default: throw new IllegalArgumentException(args[0]);
  }
 }
}'''


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        main = common.parent
        cls.jdk = Path(os.environ['CLIPMIC_ASR_JDK']) if os.environ.get('CLIPMIC_ASR_JDK') else next((main.parent / '.build-tools/jdk').glob('*/Contents/Home'))
        jar = Path(os.environ.get('ANDROID_JSON_JAR', main / 'work/lecture-profile-local-asr/asr-check/android-json.jar'))
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        folder = Path(temp.name)
        harness = folder / 'WordReviewTest.java'
        harness.write_text(HARNESS)
        cls.cp = os.pathsep.join(map(str, [jar, folder]))
        subprocess.run([cls.jdk / 'bin/javac', '--release', '8', '-encoding', 'UTF-8', '-cp', cls.cp, '-d', folder,
                        SOURCE / 'PhonePhrases.java', SOURCE / 'TranscriptReview.java', harness], check=True)

    def run_case(self, name):
        subprocess.run([self.jdk / 'bin/java', '-ea', '-cp', self.cp, 'ru.ilya.lecturerecorder.WordReviewTest', name], check=True)

    def test_critical_categories(self): self.run_case('critical')
    def test_ordinary_words_and_prepositions(self): self.run_case('boundaries')
    def test_preserve_existing_word_doubts(self): self.run_case('direct')
    def test_phrase_doubt_is_not_word_doubt(self): self.run_case('average')
    def test_exact_word_seek_and_utf16_spans(self): self.run_case('seek')
    def test_old_reports_and_missing_timestamps(self): self.run_case('legacy')
    def test_invalid_metadata_falls_back_to_phrase(self): self.run_case('invalid')
    def test_live_and_final_metadata_and_reset(self): self.run_case('flush')


if __name__ == '__main__':
    unittest.main()
