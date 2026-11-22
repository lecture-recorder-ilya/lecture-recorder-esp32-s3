"""След CTC и проверка двух правил в копии Java. Приложение не переписывается."""
import argparse
import hashlib
import json
from pathlib import Path

import profile_android_asr as profile

EXTRA=r'''
class AcousticProbe {
 static JSONArray decodes;
 static final java.util.regex.Pattern CONTENT=java.util.regex.Pattern.compile("[\\p{L}\\p{N}]");
 static boolean letters(JSONArray words)throws Exception {
  for(int i=0;i<words.length();i++)if(CONTENT.matcher(words.getJSONObject(i).getString("word")).find())return true;
  return false;
 }
 static boolean nearby(float[] wave,int frame) {
  int begin=Math.max(0,frame*640-10240),end=Math.min(wave.length,(frame+1)*640+10240);
  for(int i=begin;i<end;i++)if(wave[i]!=0f)return true;return false;
 }
 static JSONArray inspect(JSONArray beam,JSONArray greedy,float[][] logits,int steps,String[] tokens,
                            int[] alignment,float[] wave,double left,double start,double end)throws Exception {
  int first=0,last=wave.length,blankFrames=0,letterFrames=0,previous=256;double square=0;
  while(first<last && wave[first]==0f)first++;while(last>first && wave[last-1]==0f)last--;
  for(float sample:wave)square+=sample*sample;
  JSONArray events=new JSONArray();
  for(int t=0;t<steps;t++) {
   int best=0;for(int k=1;k<logits[t].length;k++)if(logits[t][k]>logits[t][best])best=k;
   if(best==256)blankFrames++;else if(CONTENT.matcher(tokens[best]).find())letterFrames++;
   int id=alignment==null?best:alignment[t];boolean emit=id!=previous && id!=256 && id!=0;previous=id;
   if(!emit)continue;
   events.put(new JSONObject().put("frame",t).put("seconds",left+t*.04).put("token",tokens[id])
    .put("probability",Math.exp(logits[t][id])).put("blank_probability",Math.exp(logits[t][256]))
    .put("greedy_token",tokens[best]).put("nonzero_within_640ms",nearby(wave,t)));
  }
  boolean drop=POLICY.equals("greedy-blank") && beam.length()==1 && letters(beam) && !letters(greedy);
  decodes.put(new JSONObject().put("beam",new JSONArray(beam.toString())).put("greedy",new JSONArray(greedy.toString()))
   .put("events",events).put("steps",steps).put("blank_argmax_frames",blankFrames)
   .put("letter_argmax_frames",letterFrames).put("first_nonzero",first==wave.length?-1:left+first/16000.0)
   .put("last_nonzero",last==0?-1:left+last/16000.0).put("rms",Math.sqrt(square/wave.length))
   .put("emit_start",start).put("emit_end",end).put("dropped_by_experiment",drop));
  return drop?new JSONArray():beam;
 }
 static final String POLICY=__POLICY__;
}
'''


def configure(policy):
    harness=profile.HARNESS
    harness=profile.replace_once(harness,'public final class Harness {',EXTRA.replace('__POLICY__',json.dumps(policy))+'\npublic final class Harness {')
    harness=profile.replace_once(harness,'static void reset() { started=', 'static void reset() { AcousticProbe.decodes=new JSONArray();started=')
    harness=profile.replace_once(harness,'.put("windows",Probe.windows)', '.put("decodes",AcousticProbe.decodes).put("windows",Probe.windows)')
    profile.HARNESS=harness
    original=profile.prepare_sources

    def prepare(source,folder,instrument=True):
        shas=original(source,folder,instrument)
        if instrument:
            path=folder/'PhoneGigaAm.java';text=path.read_text()
            before='                    return words(logits, steps, tokens, left, start, end, left + wave.length / (double) RATE, alignment);'
            after='''                    JSONArray measured=words(logits,steps,tokens,left,start,end,left+wave.length/(double)RATE,alignment);
                    JSONArray greedy=words(logits,steps,tokens,left,start,end,left+wave.length/(double)RATE,null);
                    return AcousticProbe.inspect(measured,greedy,logits,steps,tokens,alignment,wave,left,start,end);'''
            text=profile.replace_once(text,before,after)
            if policy=='onset-single':
                before='if (words.length() == 1 && words.getJSONObject(0).optBoolean("verify_onset"))'
                after='''if (words.length() == 1 && (words.getJSONObject(0).optBoolean("verify_onset") ||
                            wave.length >= RATE && words.getJSONObject(0).getDouble("end")-offset <= .64 &&
                            words.getJSONObject(0).getDouble("conf") < .8 && CONTENT.matcher(words.getJSONObject(0).getString("word")).find()))'''
                text=profile.replace_once(text,before,after)
            path.write_text(text)
        return shas
    profile.prepare_sources=prepare


def run(args):
    configure(args.policy);profile.run(args)
    report=json.loads(args.output.read_text())
    generated=args.output.parent/(args.output.stem+'-jvm')
    report.update(experiment_policy=args.policy,production_code_changed=False,
                  diagnostic_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  generated_java_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in generated.glob('*.java')})
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    for name in ('source-root','deps','jdk','model','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--repeats',type=int,default=1,choices=(1,2,3))
    p.add_argument('--policy',choices=['observe','greedy-blank','onset-single'],default='observe')
    run(p.parse_args())
