package ru.ilya.lecturerecorder;

import android.content.Context;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

final class GitHubUpdateClient {
    static final String DEVICE_URL = "https://github.com/login/device";
    private static final String API = "https://api.github.com";
    private static final long MAX_APK = 256L * 1024 * 1024;
    private final String clientId;
    private final String releases;

    GitHubUpdateClient(Context context) throws Exception {
        try (InputStream input = context.getAssets().open("update-config.json")) {
            JSONObject config = new JSONObject(read(input, 4096));
            clientId = config.getString("client_id");
            releases = API + "/repos/" + config.getString("repository") + "/releases";
        }
    }

    static final class AuthorizationRequired extends IOException {
        AuthorizationRequired() { super("Войди в GitHub для проверки обновлений."); }
    }

    static final class DeviceCode {
        final String userCode;
        final String deviceCode;
        final long expiresAt;
        long interval;

        DeviceCode(JSONObject value) throws Exception {
            userCode = value.getString("user_code");
            deviceCode = value.getString("device_code");
            expiresAt = SystemClock.elapsedRealtime() + 1000L * value.getInt("expires_in");
            interval = 1000L * Math.max(5, value.optInt("interval", 5));
        }
    }

    DeviceCode startAuthorization() throws Exception {
        return new DeviceCode(post("/login/device/code", "client_id", clientId));
    }

    JSONObject awaitAuthorization(DeviceCode code) throws Exception {
        while (SystemClock.elapsedRealtime() + code.interval < code.expiresAt) {
            Thread.sleep(code.interval);
            JSONObject response = post("/login/oauth/access_token", "client_id", clientId,
                    "grant_type", "urn:ietf:params:oauth:grant-type:device_code", "device_code", code.deviceCode);
            if (Thread.interrupted()) throw new InterruptedException();
            switch (response.optString("error")) {
                case "": return response;
                case "authorization_pending": break;
                case "slow_down": code.interval += 5000; break;
                case "access_denied": throw new GitHubUpdates.Failure("Вход в GitHub отменён.");
                default: throw new GitHubUpdates.Failure("Код GitHub истёк. Начни вход заново.");
            }
        }
        throw new GitHubUpdates.Failure("Код GitHub истёк. Начни вход заново.");
    }

    JSONObject refresh(String refreshToken) throws Exception {
        JSONObject result = post("/login/oauth/access_token", "client_id", clientId,
                "grant_type", "refresh_token", "refresh_token", refreshToken);
        String error = result.optString("error");
        if (error.equals("bad_refresh_token") || error.equals("invalid_grant")
                || error.equals("expired_token")) throw new AuthorizationRequired();
        if (!error.isEmpty()) throw new GitHubUpdates.Failure("GitHub временно не обновил вход. Повтори проверку.");
        return result;
    }

    static final class Asset {
        final String version;
        final long id;
        final long bytes;
        final String sha256;

        Asset(String version, JSONObject item) throws Exception {
            this.version = version;
            id = item.getLong("id");
            bytes = item.getLong("size");
            String digest = item.getString("digest");
            if (id <= 0 || bytes <= 0 || bytes > MAX_APK || !digest.matches("sha256:[a-f0-9]{64}"))
                throw new GitHubUpdates.Failure("GitHub не предоставил допустимый размер или контрольную сумму APK.");
            sha256 = digest.substring("sha256:".length());
        }
    }

    Asset latest(String token, String installed, String assetName) throws Exception {
        boolean stable = "lecture-recorder.apk".equals(assetName);
        String endpoint = stable ? releases + "/latest" : releases + "?per_page=30";
        Asset best = null;
        while (endpoint != null) {
            HttpURLConnection http = connect(endpoint, "application/vnd.github+json", token);
            try {
                checkStatus(http.getResponseCode());
                String body = read(http.getInputStream(), 8 * 1024 * 1024);
                if (stable) return compatible(new JSONObject(body), installed, assetName, true);
                JSONArray page = new JSONArray(body);
                for (int i = 0; i < page.length(); i++) {
                    Asset asset = compatible(page.getJSONObject(i), best == null ? installed : best.version, assetName, false);
                    if (asset != null) best = asset;
                }
                String next = nextPage(http.getHeaderField("Link"));
                endpoint = endpoint.equals(next) ? null : next;
            } finally {
                http.disconnect();
            }
        }
        return best;
    }

    private static Asset compatible(JSONObject release, String installed, String assetName, boolean stable) throws Exception {
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) return null;
        String tag = release.optString("tag_name");
        if (!tag.matches((stable ? "v" : "(?:android-)?v") + "[0-9]{1,8}\\.[0-9]{1,8}\\.[0-9]{1,8}")) return null;
        String version = tag.substring(tag.indexOf('v') + 1);
        if (compareVersions(version, installed) <= 0) return null;
        JSONArray assets = release.getJSONArray("assets");
        for (int i = 0; i < assets.length(); i++) {
            JSONObject asset = assets.getJSONObject(i);
            if (assetName.equals(asset.optString("name")) && "uploaded".equals(asset.optString("state"))) {
                return new Asset(version, asset);
            }
        }
        return null;
    }

    private String nextPage(String header) {
        if (header == null) return null;
        for (String link : header.split(",")) {
            int end = link.indexOf('>'), start = link.indexOf('<');
            if (start >= 0 && end > start && link.substring(end).contains("rel=\"next\"")) {
                String url = link.substring(start + 1, end);
                if (url.startsWith(releases + "?") && url.matches(".*[?&]page=[0-9]+(?:&[^#]*)?")) return url;
            }
        }
        return null;
    }

    static int compareVersions(String left, String right) {
        String[] a = left.split("\\.");
        String[] b = right.split("[-+]", 2)[0].split("\\.");
        for (int i = 0; i < 3; i++) {
            int order = Integer.compare(Integer.parseInt(a[i]), i < b.length ? Integer.parseInt(b[i]) : 0);
            if (order != 0) return order;
        }
        return 0;
    }

    interface Progress { void update(int percent) throws IOException; }

    void download(String token, Asset asset, File target, Progress progress) throws Exception {
        HttpURLConnection http = connect(releases + "/assets/" + asset.id, "application/octet-stream", token);
        try {
            int status = http.getResponseCode();
            if (status == 302) {
                URL location = new URL(http.getHeaderField("Location"));
                String host = location.getHost();
                if (!"https".equals(location.getProtocol()) || location.getUserInfo() != null
                        || !(host.equals("release-assets.githubusercontent.com")
                             || host.equals("objects.githubusercontent.com")))
                    throw new GitHubUpdates.Failure("GitHub вернул неизвестный адрес загрузки.");
                http.disconnect();
                http = connect(location.toExternalForm(), "application/octet-stream", null);
                status = http.getResponseCode();
            }
            checkStatus(status);
            long received = 0;
            try (InputStream input = http.getInputStream(); FileOutputStream output = new FileOutputStream(target)) {
                byte[] buffer = new byte[64 * 1024];
                for (int count; (count = input.read(buffer)) != -1;) {
                    received += count;
                    if (received > asset.bytes) throw new GitHubUpdates.Failure("Размер APK отличается от указанного на GitHub.");
                    output.write(buffer, 0, count);
                    progress.update((int)(received * 100 / asset.bytes));
                }
                output.getFD().sync();
            }
            if (received != asset.bytes || !asset.sha256.equals(Store.hash(target)))
                throw new GitHubUpdates.Failure("Загруженный APK не прошёл проверку контрольной суммы.");
        } finally {
            http.disconnect();
        }
    }

    private static void checkStatus(int status) throws IOException {
        if (status == 200) return;
        if (status == 401) throw new AuthorizationRequired();
        if (status == 403 || status == 404)
            throw new GitHubUpdates.Failure("GitHub не открыл канал обновлений. Проверь доступ аккаунта к репозиторию.");
        throw new GitHubUpdates.Failure("GitHub временно не ответил. Повтори проверку.");
    }

    private static JSONObject post(String path, String... fields) throws Exception {
        StringBuilder form = new StringBuilder();
        for (int i = 0; i < fields.length; i += 2) {
            if (i > 0) form.append('&');
            form.append(fields[i]).append('=').append(URLEncoder.encode(fields[i + 1], "UTF-8"));
        }
        byte[] body = form.toString().getBytes(StandardCharsets.UTF_8);
        HttpURLConnection http = connect("https://github.com" + path, "application/json", null);
        try {
            http.setRequestMethod("POST");
            http.setDoOutput(true);
            http.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            http.setFixedLengthStreamingMode(body.length);
            try (OutputStream out = http.getOutputStream()) { out.write(body); }
            checkStatus(http.getResponseCode());
            return new JSONObject(read(http.getInputStream(), 32 * 1024));
        } finally {
            http.disconnect();
        }
    }

    private static HttpURLConnection connect(String address, String accept, String token) throws IOException {
        HttpURLConnection http = (HttpURLConnection) new URL(address).openConnection();
        http.setInstanceFollowRedirects(false);
        http.setConnectTimeout(15000);
        http.setReadTimeout(20000);
        http.setRequestProperty("Accept", accept);
        http.setRequestProperty("User-Agent", "LectureRecorder-Android");
        if (address.startsWith(API + "/")) http.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        if (token != null) http.setRequestProperty("Authorization", "Bearer " + token);
        return http;
    }

    private static String read(InputStream input, int limit) throws IOException {
        try (InputStream source = input; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            for (int count; (count = source.read(buffer)) != -1;) {
                if (out.size() + count > limit) throw new GitHubUpdates.Failure("Ответ GitHub слишком большой.");
                out.write(buffer, 0, count);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }
}
