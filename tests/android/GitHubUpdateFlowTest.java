package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.SystemClock;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

public class GitHubUpdateFlowTest {
    private static final byte[] APK = "APK fixture for the public stable channel".getBytes(StandardCharsets.UTF_8);
    private static final List<String> requests = new CopyOnWriteArrayList<>();
    private static final String STABLE = "/api.github.com/repos/org/repo/releases/latest";
    private static final String PREVIEW = "/api.github.com/repos/org/repo/releases";
    private static final String ASSET = PREVIEW + "/assets/12";
    private static final String DEVICE = "/github.com/login/device/code";
    private static final String TOKEN = "/github.com/login/oauth/access_token";
    private static final String CDN = "/release-assets.githubusercontent.com/payload";
    private static String checksum;
    private static int metadataError, assetError, cdnError;
    private static boolean rejectSavedToken;
    private static File directory;

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message + " requests=" + requests + " status=" + GitHubUpdates.status());
    }

    private static void send(HttpExchange exchange, int status, byte[] body) throws IOException {
        exchange.sendResponseHeaders(status, body.length);
        try (java.io.OutputStream out = exchange.getResponseBody()) { out.write(body); }
    }

    private static void json(HttpExchange exchange, int status, String body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        send(exchange, status, body.getBytes(StandardCharsets.UTF_8));
    }

    private static void respond(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        requests.add(path + " " + (auth == null ? "anonymous" : auth));
        if (path.equals(DEVICE)) {
            json(exchange, 200, "{\"user_code\":\"TEST-CODE\",\"device_code\":\"test-device\",\"expires_in\":30,\"interval\":5}");
        } else if (path.equals(TOKEN)) {
            String form = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            json(exchange, 200, form.contains("device_code=test-device") ? "{\"access_token\":\"new-token\"}"
                    : "{\"error\":\"invalid_grant\"}");
        } else if (path.equals(STABLE) || path.equals(PREVIEW)) {
            if (auth == null && metadataError != 0) { json(exchange, metadataError, "{}"); return; }
            if (rejectSavedToken && "Bearer saved-token".equals(auth)) { json(exchange, 401, "{}"); return; }
            String name = path.equals(STABLE) ? "lecture-recorder.apk" : "lecture-recorder-android.apk";
            String release = "{\"tag_name\":\"v0.5.19\",\"assets\":[{\"name\":\"" + name
                    + "\",\"state\":\"uploaded\",\"id\":12,\"size\":" + APK.length
                    + ",\"digest\":\"sha256:" + checksum + "\"}]}";
            json(exchange, 200, path.equals(STABLE) ? release : "[" + release + "]");
        } else if (path.equals(ASSET)) {
            if (auth == null && assetError != 0) { json(exchange, assetError, "{}"); return; }
            exchange.getResponseHeaders().set("Location", "https://release-assets.githubusercontent.com/payload");
            exchange.sendResponseHeaders(302, -1);
            exchange.close();
        } else if (path.equals(CDN)) {
            if (cdnError != 0) json(exchange, cdnError, "{}");
            else send(exchange, 200, APK);
        } else json(exchange, 500, "{}");
    }

    private static Activity reset(String test) {
        requests.clear();
        metadataError = assetError = cdnError = 0;
        rejectSavedToken = false;
        GitHubUpdateCredentials.stored = null;
        AlertDialog.dialogs = 0;
        AppUpdates.active = false;
        AppUpdates.staged = 0;
        AppUpdates.target = new File(directory, test + "/update.apk");
        SystemClock.advance += 60000;
        return new Activity();
    }

    private static void idle() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
        while (GitHubUpdates.busy() && System.nanoTime() < deadline) Thread.sleep(5);
        require(!GitHubUpdates.busy(), "Update worker did not finish");
    }

    private static long count(String endpoint) {
        return requests.stream().filter(item -> item.startsWith(endpoint + " ")).count();
    }

    private static void publicStable() throws Exception {
        Activity activity = reset("public");
        GitHubUpdates.whenOpen(activity);
        idle();
        require(AppUpdates.staged == 1 && java.util.Arrays.equals(APK, Files.readAllBytes(AppUpdates.target.toPath())),
                "Fresh install did not stage the public stable APK in the foreground");
        require(requests.equals(List.of(STABLE + " anonymous", ASSET + " anonymous", CDN + " anonymous")),
                "Anonymous public route or redirect changed");
        require(AlertDialog.dialogs == 0 && !GitHubUpdates.signedIn(activity), "Public check requested a login");
        SystemClock.advance += 60000;
        GitHubUpdates.whenOpen(activity);
        idle();
        require(count(STABLE) == 1, "Six-hour success interval ignored");
        GitHubUpdates.start(activity, true);
        idle();
        require(count(STABLE) == 2 && count(ASSET) == 1 && AppUpdates.staged == 1, "Cached APK was downloaded again");
    }

    private static void privatePreview() throws Exception {
        Activity activity = reset("preview");
        activity.packageName += ".preview";
        metadataError = 404;
        GitHubUpdates.whenOpen(activity);
        idle();
        require(requests.equals(List.of(PREVIEW + " anonymous")) && AlertDialog.dialogs == 0,
                "Background access to a private preview opened OAuth");
        GitHubUpdates.start(activity, true);
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (!GitHubUpdates.authorizing() && System.nanoTime() < end) Thread.sleep(5);
        require(GitHubUpdates.authorizing(), "Manual private check did not start device authorization");
        GitHubUpdates.start(activity, true);
        idle();
        require(AppUpdates.staged == 1 && count(DEVICE) == 1 && count(TOKEN) == 1,
                "Manual OAuth started more than once or failed to stage");
        require(requests.contains(PREVIEW + " Bearer new-token") && requests.contains(ASSET + " Bearer new-token")
                && requests.contains(CDN + " anonymous") && AlertDialog.dialogs > 0, "Private preview used the wrong credentials");
        GitHubUpdates.start(activity, true);
        idle();
        require(count(DEVICE) == 1 && count(TOKEN) == 1, "Saved credential was requested again");
    }

    private static void existingTokens() throws Exception {
        Activity activity = reset("saved");
        metadataError = 401;
        GitHubUpdateCredentials.stored = new JSONObject("{\"access_token\":\"saved-token\",\"expires_at\":" + Long.MAX_VALUE + "}");
        GitHubUpdates.whenOpen(activity);
        idle();
        require(AppUpdates.staged == 1 && requests.contains(STABLE + " Bearer saved-token") && count(DEVICE) == 0
                && AlertDialog.dialogs == 0, "A saved account stopped working in the background");
        activity = reset("revoked");
        metadataError = 401;
        rejectSavedToken = true;
        GitHubUpdateCredentials.stored = new JSONObject("{\"access_token\":\"saved-token\",\"expires_at\":" + Long.MAX_VALUE + "}");
        GitHubUpdates.whenOpen(activity);
        idle();
        require(!GitHubUpdates.signedIn(activity) && count(DEVICE) == 0 && AppUpdates.staged == 0,
                "Invalid token did not wait for an explicit user action");
    }

    private static void interruptions() throws Exception {
        Activity activity = reset("offline");
        activity.connectivity.online = false;
        GitHubUpdates.whenOpen(activity);
        idle();
        activity.connectivity.online = true;
        AppUpdates.active = true;
        SystemClock.advance += 60000;
        GitHubUpdates.whenOpen(activity);
        idle();
        require(requests.isEmpty(), "Offline or active capture made a request");
        for (int code : new int[]{403, 429, 503}) {
            activity = reset("retry-" + code);
            metadataError = code;
            GitHubUpdates.whenOpen(activity);
            idle();
            long retry = activity.getSharedPreferences("updates", 0).getLong("github_after", 0) - System.currentTimeMillis();
            require(retry > TimeUnit.MINUTES.toMillis(14) && retry <= TimeUnit.MINUTES.toMillis(15),
                    "Transient HTTP error got the wrong backoff");
            SystemClock.advance += 60000;
            GitHubUpdates.whenOpen(activity);
            idle();
            require(count(STABLE) == 1 && count(DEVICE) == 0, "Automatic retry ignored the scheduled delay");
            GitHubUpdates.start(activity, true);
            idle();
            require(count(STABLE) == 2 && count(DEVICE) == 0, "Transient HTTP error requested OAuth");
        }
        for (int code : new int[]{403, 429}) {
            activity = reset("signed-limit-" + code);
            metadataError = code;
            GitHubUpdateCredentials.stored = new JSONObject("{\"access_token\":\"saved-token\",\"expires_at\":" + Long.MAX_VALUE + "}");
            GitHubUpdates.whenOpen(activity);
            idle();
            require(AppUpdates.staged == 1 && count(STABLE) == 2 && requests.contains(STABLE + " Bearer saved-token")
                    && count(DEVICE) == 0 && AlertDialog.dialogs == 0, "Anonymous rate limit stopped a saved account");
        }
        activity = reset("invalid-signed-limit");
        metadataError = 403;
        rejectSavedToken = true;
        GitHubUpdateCredentials.stored = new JSONObject("{\"access_token\":\"saved-token\",\"expires_at\":" + Long.MAX_VALUE + "}");
        GitHubUpdates.start(activity, true);
        idle();
        require(count(STABLE) == 2 && !GitHubUpdates.signedIn(activity) && count(DEVICE) == 0,
                "Anonymous rate limit initiated OAuth for a rejected saved token");
        activity = reset("cdn");
        cdnError = 401;
        GitHubUpdates.start(activity, true);
        idle();
        require(count(CDN) == 1 && count(DEVICE) == 0 && AppUpdates.staged == 0, "CDN failure triggered OAuth");
        activity = reset("asset");
        assetError = 404;
        GitHubUpdateCredentials.stored = new JSONObject("{\"access_token\":\"saved-token\",\"expires_at\":" + Long.MAX_VALUE + "}");
        GitHubUpdates.whenOpen(activity);
        idle();
        require(AppUpdates.staged == 1 && requests.contains(ASSET + " Bearer saved-token") && count(DEVICE) == 0,
                "Private asset did not use the saved account");
    }

    public static void main(String[] args) throws Exception {
        directory = new File(args[0]);
        checksum = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(APK));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", GitHubUpdateFlowTest::respond);
        server.start();
        try {
            int port = server.getAddress().getPort();
            URL.setURLStreamHandlerFactory(protocol -> !"https".equals(protocol) ? null : new URLStreamHandler() {
                protected URLConnection openConnection(URL url) throws IOException {
                    return new URL("http", "127.0.0.1", port, "/" + url.getHost() + url.getFile()).openConnection();
                }
            });
            publicStable();
            privatePreview();
            existingTokens();
            interruptions();
        } finally {
            server.stop(0);
        }
    }
}
