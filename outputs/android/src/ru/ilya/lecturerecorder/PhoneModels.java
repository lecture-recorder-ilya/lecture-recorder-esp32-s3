package ru.ilya.lecturerecorder;

import android.content.Context;

import java.io.*;
import java.net.URL;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

final class PhoneModels {
    private static final String SPEECH = "vosk-model-small-ru-0.22";
    private static final String GIGAAM = "gigaam-v3-e2e-ctc.int8.onnx";
    private static final long GIGAAM_BYTES = 224893347L;
    private static final String TEXT = "qwen3-0.6b-int4.litertlm";
    private static final long TEXT_BYTES = 343490560L;

    static boolean ready(Context context) {
        File directory = directory(context);
        return new File(directory, GIGAAM).length() == GIGAAM_BYTES && summaryReady(context);
    }

    static boolean summaryReady(Context context) {
        return new File(directory(context), TEXT).length() == TEXT_BYTES;
    }

    static File acoustic(Context context, PhoneAnalysisService.Job job) throws Exception {
        return download(directory(context), GIGAAM,
                "https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/"
                        + "322c3b29492673eb7d0b434bfa9dfb8653e34d02/v3_e2e_ctc.int8.onnx",
                GIGAAM_BYTES, "2e3fcb7a7b66030336fd10c2fcfb033bd1dc7e1bf238fe5cfd83b1d0cfc9d28e",
                "Скачиваю модель речи", job);
    }

    static File speech(Context context, PhoneAnalysisService.Job job) throws Exception {
        File directory = directory(context);
        File model = new File(directory, SPEECH).getCanonicalFile();
        File marker = new File(model, ".ready");
        if (marker.isFile()) return model;

        File archive = download(directory, SPEECH + ".zip",
                "https://alphacephei.com/vosk/models/" + SPEECH + ".zip", 46236750L,
                "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4",
                "Скачиваю модель речи", job);
        job.update("Подготавливаю модель речи");
        String prefix = model.getCanonicalPath() + File.separator;
        long extracted = 0;
        byte[] buffer = new byte[65536];
        try (ZipInputStream zip = new ZipInputStream(new BufferedInputStream(new FileInputStream(archive)))) {
            for (ZipEntry entry; (entry = zip.getNextEntry()) != null; ) {
                job.check();
                File file = new File(directory, entry.getName()).getCanonicalFile();
                if (!file.equals(model) && !file.getPath().startsWith(prefix)) {
                    throw new IOException("Неверная структура модели речи");
                }
                File parent = entry.isDirectory() ? file : file.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new IOException("Папка модели недоступна");
                if (entry.isDirectory()) continue;
                try (OutputStream output = new FileOutputStream(file)) {
                    for (int size; (size = zip.read(buffer)) != -1; ) {
                        job.check();
                        extracted += size;
                        if (extracted > 100000000L) throw new IOException("Модель речи повреждена");
                        output.write(buffer, 0, size);
                    }
                }
            }
        }
        if (!marker.createNewFile()) throw new IOException("Не удалось сохранить модель речи");
        archive.delete();
        return model;
    }

    static File text(Context context, PhoneAnalysisService.Job job) throws Exception {
        return download(directory(context), TEXT,
                "https://huggingface.co/litert-community/Qwen3-0.6B/resolve/"
                        + "2670e142a0d16a1b685be6604e5b4f2b31a826d7/Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm",
                TEXT_BYTES, "bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0",
                "Скачиваю модель конспекта", job);
    }

    private static File directory(Context context) {
        return new File(context.getFilesDir(), "phone-models");
    }

    private static File download(File directory, String name, String url, long bytes, String sha,
                                 String status, PhoneAnalysisService.Job job) throws Exception {
        File target = new File(directory, name);
        if (target.length() == bytes) return target;
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Папка моделей недоступна");
        if (directory.getUsableSpace() < bytes + 150000000L) throw new IOException("Освободи место для моделей");
        File part = new File(directory, name + ".part");
        javax.net.ssl.HttpsURLConnection connection =
                (javax.net.ssl.HttpsURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(20000);
        job.update(status + " · 0%");
        try {
            byte[] buffer = new byte[65536];
            long written = 0;
            int progress = 0;
            if (connection.getResponseCode() != 200) throw new IOException("Сервер модели недоступен");
            try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(part)) {
                for (int size; (size = input.read(buffer)) != -1; ) {
                    job.check();
                    written += size;
                    if (written > bytes) throw new IOException("Неверный размер модели");
                    output.write(buffer, 0, size);
                    int percent = (int) (100 * written / bytes);
                    if (percent != progress) {
                        progress = percent;
                        job.update(status + " · " + percent + "%");
                    }
                }
                output.getFD().sync();
            }
            if (written != bytes || !sha.equals(Store.hash(part))) throw new IOException("Модель скачалась с ошибкой");
            job.check();
            if (!part.renameTo(target)) throw new IOException("Не удалось сохранить модель");
            return target;
        } finally {
            connection.disconnect();
            part.delete();
        }
    }

    private PhoneModels() {}
}
