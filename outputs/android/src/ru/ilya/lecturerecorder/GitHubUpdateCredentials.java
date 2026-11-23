package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class GitHubUpdateCredentials {
    private static final String ALIAS = "github-release-access";
    private final SharedPreferences preferences;

    GitHubUpdateCredentials(Context context) {
        preferences = context.getSharedPreferences("github_updates", Context.MODE_PRIVATE);
    }

    boolean exists() { return preferences.contains("encrypted"); }

    JSONObject read() {
        if (!exists()) return null;
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(),
                    new GCMParameterSpec(128, Base64.decode(preferences.getString("iv", ""), Base64.NO_WRAP)));
            byte[] data = cipher.doFinal(Base64.decode(preferences.getString("encrypted", ""), Base64.NO_WRAP));
            return new JSONObject(new String(data, StandardCharsets.UTF_8));
        } catch (Exception unavailable) {
            clear();
            return null;
        }
    }

    void save(JSONObject response) throws Exception {
        long now = System.currentTimeMillis();
        JSONObject data = new JSONObject().put("access_token", response.getString("access_token"))
                .put("expires_at", now + 1000L * response.optLong("expires_in", 86400L * 365));
        if (response.has("refresh_token")) {
            data.put("refresh_token", response.getString("refresh_token"));
            data.put("refresh_expires_at", now + 1000L * response.optLong("refresh_token_expires_in", 15552000));
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] value = cipher.doFinal(data.toString().getBytes(StandardCharsets.UTF_8));
        if (!preferences.edit().putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                .putString("encrypted", Base64.encodeToString(value, Base64.NO_WRAP)).commit())
            throw new GitHubUpdates.Failure("Не удалось сохранить вход в GitHub.");
    }

    void clear() { preferences.edit().clear().apply(); }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey existing = (SecretKey) store.getKey(ALIAS, null);
        if (existing != null) return existing;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
}
