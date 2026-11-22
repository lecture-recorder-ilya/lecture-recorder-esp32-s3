package ru.ilya.lecturerecorder;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.json.*;

final class SummarySources {
    static final String NOTICE="Источник нужно сверить.";
    private static final String WARNING="Источники конспекта:";
    private static final String[] ACTIVE={"start","end","segment_id","source_fingerprint"};

    private static String norm(String text) { return text.replaceAll("(?U)\\s+"," ").trim().toLowerCase(Locale.ROOT); }
    private static final class Span { final int first,last; Span(int a,int b){first=a;last=b;} }

    private static String fingerprint(JSONArray rows,Span span)throws Exception {
        StringBuilder text=new StringBuilder();
        for(int i=span.first;i<=span.last;i++) {
            JSONObject row=rows.getJSONObject(i);
            if(i>span.first)text.append('\n');
            text.append(row.optInt("id",i)).append('|').append(Math.round(row.getDouble("start")*1000)).append('|')
                .append(Math.round(row.getDouble("end")*1000)).append('|').append(norm(row.getString("text")));
        }
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(text.toString().getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder();for(byte value:bytes)hex.append(String.format(Locale.ROOT,"%02x",value&255));
        return hex.toString();
    }

    private static List<Span> matches(String quote,JSONArray rows)throws JSONException {
        List<Span> spans=new ArrayList<>();String target=norm(quote);
        if(target.isEmpty())return spans;
        for(int first=0;first<rows.length();first++) {
            String text="";double previous=Double.NaN;
            for(int last=first;last<rows.length();last++) {
                JSONObject row=rows.optJSONObject(last);if(row==null)break;
                double start=row.optDouble("start"),end=row.optDouble("end");
                if(!Double.isFinite(start)||!Double.isFinite(end)||start<0||end<=start
                    || last>first&&(start-previous<-.25||start-previous>2))break;
                text=norm(text+" "+row.optString("text"));previous=end;
                if(!target.startsWith(text))break;
                if(target.equals(text)){spans.add(new Span(first,last));break;}
            }
        }
        return spans;
    }

    private static boolean trusted(JSONArray rows,Span span)throws JSONException {
        for(int i=span.first;i<=span.last;i++) {
            JSONObject row=rows.getJSONObject(i);
            if(row.optBoolean("needs_review")&&!row.optBoolean("reviewed"))return false;
        }
        return true;
    }

    private static void remember(JSONObject anchor)throws JSONException {
        if(anchor.has("original_source"))return;
        JSONObject old=new JSONObject();if(anchor.has("quote"))old.put("quote",anchor.get("quote"));
        for(String key:ACTIVE)if(anchor.has(key))old.put(key,anchor.get(key));
        anchor.put("original_source",old);
    }

    private static void bind(JSONObject anchor,JSONArray rows,boolean local,boolean fresh)throws Exception {
        List<Span> candidates=matches(anchor.optString("quote"),rows),supported=new ArrayList<>(),precise=new ArrayList<>();
        String priorHash=anchor.optString("source_fingerprint");
        if(priorHash.isEmpty()&&anchor.optJSONObject("original_source")!=null)priorHash=anchor.getJSONObject("original_source").optString("source_fingerprint");
        for(Span span:candidates)if(trusted(rows,span)) {
            supported.add(span);
            JSONObject first=rows.getJSONObject(span.first),last=rows.getJSONObject(span.last);
            int id=anchor.optInt("segment_id",-1);
            if(priorHash.equals(fingerprint(rows,span))
                ||fresh&&anchor.optDouble("start")==first.getDouble("start")&&anchor.optDouble("end")==last.getDouble("end")
                  &&(id==span.first||id==first.optInt("id",span.first)))precise.add(span);
        }
        Span selected=precise.size()==1?precise.get(0):candidates.size()==1&&supported.size()==1?supported.get(0):null;
        if(selected!=null) {
            JSONObject first=rows.getJSONObject(selected.first),last=rows.getJSONObject(selected.last);
            int id=local?selected.first:first.optInt("id",selected.first),oldId=anchor.optInt("segment_id",-1);
            boolean sameTime=anchor.optDouble("start")==first.getDouble("start")&&anchor.optDouble("end")==last.getDouble("end");
            if(sameTime&&(oldId==selected.first||oldId==first.optInt("id",selected.first)))id=oldId;
            if(!sameTime||oldId!=id){remember(anchor);anchor.put("source_rebound",true);}
            anchor.put("start",first.getDouble("start")).put("end",last.getDouble("end")).put("segment_id",id)
                .put("source_fingerprint",fingerprint(rows,selected)).put("source_status","confirmed");
            anchor.remove("source_note");anchor.remove("source_reason");
        } else {
            remember(anchor);for(String key:ACTIVE)anchor.remove(key);
            anchor.put("source_status","needs_review").put("source_note",NOTICE)
                .put("source_reason",candidates.size()>1?"ambiguous":candidates.isEmpty()?"not_found":"uncertain");
        }
    }

    static void reconcile(JSONObject report,boolean local,boolean fresh)throws Exception {
        JSONArray rows=report.optJSONArray("segments");if(rows==null)rows=new JSONArray();
        JSONArray points=report.optJSONArray("summary"),sources=report.optJSONArray("summary_evidence");
        boolean overviewDerived=points!=null&&report.optString("overview").equals(TranscriptEdits.summaryOverview(points));
        int pending=0;
        if(points!=null) {
            JSONArray updated=new JSONArray();
            for(int i=0;i<points.length();i++) {
                JSONObject anchor=sources==null?null:sources.optJSONObject(i);
                if(anchor==null)anchor=new JSONObject().put("quote",points.optString(i));
                String original=anchor.optString("source_point",points.optString(i));
                bind(anchor,rows,local,fresh);
                if(anchor.optString("source_status").equals("needs_review")) {
                    anchor.put("source_point",original);points.put(i,original+"\n"+NOTICE);pending++;
                }else {points.put(i,original);anchor.remove("source_point");}
                updated.put(anchor);
            }
            report.put("summary_evidence",updated);
            if(overviewDerived&&report.has("overview"))report.put("overview",TranscriptEdits.summaryOverview(points));
        }
        for(String field:new String[]{"homework","formulas","highlights"}) {
            JSONArray items=report.optJSONArray(field);if(items==null)continue;
            for(int i=0;i<items.length();i++) {
                JSONObject anchor=items.optJSONObject(i);if(anchor==null)continue;
                bind(anchor,rows,local,fresh);
                if(anchor.optString("source_status").equals("needs_review")) {
                    pending++;
                    if(field.equals("homework")) {
                        String original=anchor.optString("source_point",anchor.optString("task",anchor.optString("quote")));
                        anchor.put("source_point",original).put("task",original+"\n"+NOTICE);anchor.remove("deadline");
                    }
                } else if(field.equals("homework")&&anchor.has("source_point")) {
                    anchor.put("task",anchor.getString("source_point"));anchor.remove("source_point");
                }
            }
        }
        JSONArray warnings=report.optJSONArray("warnings"),updated=new JSONArray();
        if(warnings!=null)for(int i=0;i<warnings.length();i++)if(!warnings.optString(i).startsWith(WARNING))updated.put(warnings.get(i));
        if(pending>0)updated.put(WARNING+" нужно сверить — "+pending+".");
        if(warnings!=null||pending>0)report.put("warnings",updated);
    }
}
