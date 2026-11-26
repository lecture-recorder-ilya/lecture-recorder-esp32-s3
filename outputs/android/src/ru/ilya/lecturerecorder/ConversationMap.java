package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.view.ViewGroup;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.HashSet;
import java.util.Set;

final class ConversationMap {
    interface Player { void seek(int millis, String place); }

    static void show(LectureReaderActivity owner, String file, String title, JSONObject report, boolean canPlay, String place, Player player) {
        SharedPreferences store = owner.getSharedPreferences("conversation_map", Context.MODE_PRIVATE);
        Set<String> pins = new HashSet<>(store.getStringSet(file, java.util.Collections.emptySet()));
        JSONArray times = new JSONArray();
        for (String pin : pins) {
            try { times.put(Integer.parseInt(pin) / 1000.0); }
            catch (NumberFormatException | JSONException ignored) {}
        }
        JSONObject data = new JSONObject();
        try {
            JSONArray segments = report.optJSONArray("segments");
            data.put("evidence", report.optJSONArray("summary_evidence"));
            data.put("title", title).put("key", file).put("segments", segments == null ? new JSONArray() : segments);
            data.put("canPlay", canPlay).put("pins", times).put("place", place);
        } catch (JSONException invalid) { throw new IllegalArgumentException(invalid); }

        WebView web = new WebView(owner);
        web.setBackgroundColor(0xff191a18);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setBlockNetworkLoads(true);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setAllowFileAccess(false);
        AlertDialog dialog = new AlertDialog.Builder(owner).setTitle("Карта разговора").setView(web)
                .setNegativeButton("Закрыть", null).create();
        String entry = "file:///android_asset/conversation/conversation-mobile.html";
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) {
                if (url.equals(entry)) view.evaluateJavascript("renderNativeMap(" + data + ")", null);
            }
            private boolean handle(Uri uri) {
                if (!"zumap".equals(uri.getScheme())) return true;
                int ms;
                try { ms = Integer.parseInt(uri.getLastPathSegment()); } catch (NumberFormatException ignored) { return true; }
                if (ms < 0) return true;
                String action = uri.getHost();
                if ("export".equals(action)) {
                    web.evaluateJavascript("JSON.stringify(globalThis.zuFile)", value -> {
                        try {
                            String document = new org.json.JSONTokener(value).nextValue().toString();
                            owner.saveMap(new JSONObject(document));
                        } catch (Exception failure) {
                            android.widget.Toast.makeText(owner, "Не удалось сохранить карту", android.widget.Toast.LENGTH_LONG).show();
                        }
                    });
                }
                if ("play".equals(action) && canPlay) {
                    String nextPlace = uri.getQueryParameter("place");
                    dialog.dismiss();
                    player.seek(ms, nextPlace);
                }
                if ("pin".equals(action) || "unpin".equals(action)) {
                    if ("pin".equals(action)) pins.add(Integer.toString(ms)); else pins.remove(Integer.toString(ms));
                    store.edit().putStringSet(file, new HashSet<>(pins)).apply();
                }
                return true;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return handle(request.getUrl()); }
            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) { return handle(Uri.parse(url)); }
        });
        dialog.setOnDismissListener(d -> {
            if (web.getParent() instanceof ViewGroup) ((ViewGroup) web.getParent()).removeView(web);
            web.destroy();
        });
        dialog.show();
        if (dialog.getWindow() != null) dialog.getWindow().setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        web.loadUrl(entry);
    }
}
