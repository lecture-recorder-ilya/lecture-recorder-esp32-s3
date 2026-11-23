"""Настоящая сборка CTC-слов: пунктуация, стык и защита слабой начальной буквы."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from profile_android_asr import prepare_sources

HARNESS='''package ru.ilya.lecturerecorder;
import java.lang.reflect.*;
import java.util.*;
import org.json.*;
public class TokenTimeTests {
 static final int BLANK=256;
 static JSONArray words(int steps,int[] frames,int[] labels,double left,double start,double end,double probability)throws Exception {
  float[][] scores=new float[steps][257];int[] aligned=new int[steps];Arrays.fill(aligned,BLANK);
  for(float[] row:scores)Arrays.fill(row,-20);
  for(int i=0;i<frames.length;i++){aligned[frames[i]]=labels[i];scores[frames[i]][labels[i]]=(float)Math.log(labels[i]==2?Math.min(1,probability+.1):probability);}
  String[] tokens=new String[257];Arrays.fill(tokens,"");
  tokens[1]="▁Три";tokens[2]=".";tokens[3]="«";tokens[4]="три";tokens[5]="»";
  tokens[6]="▁Д";tokens[7]="▁Да";tokens[8]="▁15";tokens[9]="▁три.";
  tokens[10]="▁т";tokens[11]="ри";
  Method method=PhoneGigaAm.class.getDeclaredMethod("words",float[][].class,int.class,String[].class,
    double.class,double.class,double.class,double.class,int[].class);method.setAccessible(true);
  return (JSONArray)method.invoke(null,scores,steps,tokens,left,start,end,left+steps*.04,aligned);
 }
 static void same(double actual,double expected){assert Math.abs(actual-expected)<1e-7:actual+" != "+expected;}
 public static void main(String[] args)throws Exception {
  JSONArray result;
  switch(args[0]) {
   case "live_phrases":
    List<JSONObject> published=new ArrayList<>();
    PhonePhrases live=new PhonePhrases(published::add);
    live.accept(new JSONArray().put(w("Первая.",1.25,2,true)));
    assert published.isEmpty();
    live.accept(new JSONArray().put(w("Вторая.",3,4,true)));
    assert published.size()==1;
    same(published.get(0).getDouble("start"),1.25);
    assert published.get(0).getString("text").equals("Первая.");
    JSONArray complete=live.finish();
    assert published.size()==2 && complete.length()==2;
    assert published.get(0).toString().equals(complete.getJSONObject(0).toString());
    assert live.finish().length()==2 && published.size()==2;
    break;
   case "silence_trim":
    float[] pcm=new float[32000];
    pcm[24000]=1f/32768;
    same(PhoneSpeechWindow.trimSilentStart(pcm,10,10,12),11.46);
    same(PhoneSpeechWindow.trimSilentStart(pcm,10,11.42,12),11.42);
    same(PhoneSpeechWindow.trimSilentStart(pcm,10,10,11),10);
    pcm[0]=1f/32768;
    same(PhoneSpeechWindow.trimSilentStart(pcm,10,10,12),10);
    break;
   case "punctuation":
    result=words(125,new int[]{10,124},new int[]{1,2},0,0,5,.8);
    assert result.length()==1;JSONObject w=result.getJSONObject(0);
    assert w.getString("word").equals("Три.");same(w.getDouble("start"),.4);same(w.getDouble("end"),.44);same(w.getDouble("conf"),.85);
    result=words(125,new int[]{0,10,100,124},new int[]{3,4,2,5},0,0,5,.8);
    w=result.getJSONObject(0);assert w.getString("word").equals("«три.»");same(w.getDouble("start"),.4);same(w.getDouble("end"),.44);
    break;
   case "numbers":
    for(int token:new int[]{8,9}) {
     result=words(125,new int[]{10,124},new int[]{token,2},0,0,5,.8);
     same(result.getJSONObject(0).getDouble("end"),.44);
    }
    break;
   case "seam":
    // Одна и та же речь до стыка, точка после стыка. Только первое окно владеет словом.
    PhonePhrases phrases=new PhonePhrases();PhoneWordTimeline timeline=new PhoneWordTimeline(phrases,2);
    result=words(525,new int[]{440,520},new int[]{1,2},0,0,18,.8);assert result.length()==1;
    assert !result.getJSONObject(0).getBoolean("_legacy_core");timeline.accept(result,18);
    result=words(225,new int[]{40,200},new int[]{1,2},16,18,25,.8);assert result.length()==1;
    assert result.getJSONObject(0).getBoolean("_legacy_core");timeline.accept(result,25);timeline.finish();
    result=phrases.finish();assert result.length()==1;assert result.getJSONObject(0).getString("text").equals("Три.");
    // Речь после стыка принадлежит только второму окну.
    result=words(525,new int[]{450,520},new int[]{1,2},0,0,18,.8);assert result.length()==0;
    result=words(225,new int[]{50,200},new int[]{1,2},16,18,25,.8);assert result.length()==1;
    // Слово пересекает стык: последний речевой кадр принадлежит второму окну.
    result=words(525,new int[]{448,451,520},new int[]{10,11,2},0,0,18,.8);assert result.length()==0;
    result=words(225,new int[]{48,51,200},new int[]{10,11,2},16,18,25,.8);assert result.length()==1;
    same(result.getJSONObject(0).getDouble("start"),17.92);same(result.getJSONObject(0).getDouble("end"),18.08);
    break;
   case "repeat":
    PhonePhrases repeated=new PhonePhrases();PhoneWordTimeline joined=new PhoneWordTimeline(repeated,2);
    JSONArray first=new JSONArray().put(w("не",17.60,17.68,true)).put(w("не",17.76,17.84,true));
    JSONArray second=new JSONArray().put(w("не",17.60,17.68,true)).put(w("не",17.76,17.84,true));
    joined.accept(first,18);joined.accept(second,25);joined.finish();result=repeated.finish();
    assert result.getJSONObject(0).getString("text").equals("не не");
    assert !result.getJSONObject(0).getBoolean("needs_review");
    // Ровно два кадра между настоящими словами; ранний первый токен второго окна.
    repeated=new PhonePhrases();joined=new PhoneWordTimeline(repeated,2);
    joined.accept(new JSONArray().put(w("не",17.60,17.64,true)),18);
    joined.accept(new JSONArray().put(w("не",16.5,17.72,true)),25);joined.finish();
    result=repeated.finish();assert result.getJSONObject(0).getString("text").equals("не не");
    break;
   case "fallback":
    PhonePhrases recovered=new PhonePhrases();PhoneWordTimeline tail=new PhoneWordTimeline(recovered,2);
    tail.accept(new JSONArray().put(w("место.",6.5,6.8,true)),18.5);
    tail.accept(new JSONArray().put(w("Три.",16.5,17.92,true)),25);tail.finish();
    result=recovered.finish();assert result.length()==2;assert result.getJSONObject(1).getString("text").equals("Три.");
    PhonePhrases alternate=new PhonePhrases();tail=new PhoneWordTimeline(alternate,2);
    tail.accept(new JSONArray().put(w("мне",17.7,17.9,false)),18);
    tail.accept(new JSONArray().put(w("не",17.7,17.9,true)),25);tail.finish();
    result=alternate.finish();assert result.getJSONObject(0).getString("text").equals("не");
    assert result.getJSONObject(0).getBoolean("needs_review");
    // Кандидат и исходный ответ того же слова расходятся ровно на два кадра.
    PhonePhrases duplicated=new PhonePhrases();tail=new PhoneWordTimeline(duplicated,2);
    tail.accept(new JSONArray().put(w("место.",52.32,52.56,false)),54);
    tail.accept(new JSONArray().put(w("Место.",52,52.64,true)),70);tail.finish();
    result=duplicated.finish();assert result.length()==1;
    assert result.getJSONObject(0).getString("text").equals("Место.");
    break;
   case "signs":
    for(String[] pair:new String[][]{{"-5","5"},{"15,0","150"}}) {
     PhonePhrases critical=new PhonePhrases();PhoneWordTimeline numbers=new PhoneWordTimeline(critical,2);
     numbers.accept(new JSONArray().put(w(pair[0],17.6,17.8,true)),18);
     numbers.accept(new JSONArray().put(w(pair[1],17.6,17.8,true)),25);numbers.finish();
     result=critical.finish();assert result.getJSONObject(0).getString("text").equals(pair[0]+" "+pair[1]);
     assert result.getJSONObject(0).getBoolean("needs_review");
    }
    break;
   case "legacy_order":
    PhonePhrases order=new PhonePhrases();PhoneWordTimeline ordered=new PhoneWordTimeline(order,2);
    ordered.accept(new JSONArray().put(w("Небо",0,18.16,true)),18.5);
    ordered.accept(new JSONArray().put(w("Нибо",16.5,18.15,true)),25);ordered.finish();
    result=order.finish();assert result.length()==2;
    assert result.getJSONObject(0).getString("text").equals("Небо");
    assert result.getJSONObject(1).getString("text").equals("Нибо");
    assert result.getJSONObject(0).getBoolean("needs_review") && result.getJSONObject(1).getBoolean("needs_review");
    break;
   case "onset":
    result=words(125,new int[]{0,124},new int[]{6,2},0,0,5,.3);
    assert result.length()==1;assert result.getJSONObject(0).getBoolean("verify_onset");same(result.getJSONObject(0).getDouble("end"),.04);
    for(int token:new int[]{6,7}) {
     result=words(125,new int[]{0,124},new int[]{token,2},0,0,5,token==6?.8:.3);
     assert !result.getJSONObject(0).optBoolean("verify_onset");
    }
    break;
   default:throw new IllegalArgumentException(args[0]);
  }
 }
 static JSONObject w(String text,double start,double end,boolean core)throws Exception {
  return new JSONObject().put("word",text).put("start",start).put("end",end).put("conf",.99).put("_legacy_core",core);
 }
}'''


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute():common=(ROOT/common).resolve()
        main=common.parent
        cls.jdk=Path(os.environ['CLIPMIC_ASR_JDK']) if os.environ.get('CLIPMIC_ASR_JDK') else next((main.parent/'.build-tools/jdk').glob('*/Contents/Home'))
        deps=main/'work/lecture-profile-local-asr/asr-check'
        temp=tempfile.TemporaryDirectory();cls.addClassCleanup(temp.cleanup)
        folder=Path(temp.name)/'java';prepare_sources(ROOT,folder,False)
        (folder/'TokenTimeTests.java').write_text(HARNESS)
        cls.cp=os.pathsep.join(map(str,[deps/'ort.jar',deps/'android-json.jar',folder]))
        subprocess.run([cls.jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cls.cp,'-d',folder,*folder.glob('*.java')],check=True)

    def run_case(self,name):
        subprocess.run([self.jdk/'bin/java','-ea','-cp',self.cp,'ru.ilya.lecturerecorder.TokenTimeTests',name],check=True)

    def test_live_callback_emits_each_completed_phrase_once(self):self.run_case('live_phrases')
    def test_punctuation_cannot_move_speech(self):self.run_case('punctuation')
    def test_only_digital_silence_can_move_start(self):self.run_case('silence_trim')
    def test_number_and_mixed_token_keep_speech_boundary(self):self.run_case('numbers')
    def test_neighboring_windows_keep_one_copy(self):self.run_case('seam')
    def test_short_speech_span_keeps_weak_onset_retry(self):self.run_case('onset')
    def test_real_repeated_negative_keeps_two_words(self):self.run_case('repeat')
    def test_overlap_recovers_word_and_preserves_original_choice(self):self.run_case('fallback')
    def test_signs_and_decimal_separator_are_not_duplicate_punctuation(self):self.run_case('signs')
    def test_ambiguous_overlap_keeps_original_word_order(self):self.run_case('legacy_order')


if __name__=='__main__':unittest.main()
