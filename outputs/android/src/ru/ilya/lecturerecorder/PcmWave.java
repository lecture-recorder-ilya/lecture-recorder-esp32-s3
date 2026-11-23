package ru.ilya.lecturerecorder;

import java.io.IOException;
import java.io.InterruptedIOException;
import java.io.RandomAccessFile;
import java.util.Arrays;

final class PcmWave {
    static final int SAMPLE_RATE = 16000;
    private static final byte[] PCM_SUBFORMAT = {
        1, 0, 0, 0, 0, 0, 0x10, 0, (byte) 0x80, 0, 0, (byte) 0xaa, 0, 0x38, (byte) 0x9b, 0x71
    };

    private static int unsignedShortLE(RandomAccessFile audio) throws IOException {
        return Short.toUnsignedInt(Short.reverseBytes(audio.readShort()));
    }

    private static boolean isExtensiblePcm16(RandomAccessFile audio, long size) throws IOException {
        if (size < 40) return false;
        int extension = unsignedShortLE(audio);
        if (extension < 22 || 18L + extension > size || unsignedShortLE(audio) != 16) return false;
        audio.skipBytes(4);
        byte[] subformat = new byte[PCM_SUBFORMAT.length];
        audio.readFully(subformat);
        return Arrays.equals(subformat, PCM_SUBFORMAT);
    }

    static long seekData(RandomAccessFile audio) throws IOException {
        long length = audio.length();
        audio.seek(0);
        if (length < 44 || audio.readInt() != 0x52494646) throw new IOException("Аудио повреждено");
        audio.seek(8);
        if (audio.readInt() != 0x57415645) throw new IOException("Неподдерживаемый формат WAV");
        boolean pcm = false;
        while (audio.getFilePointer() + 8 <= length) {
            int chunk = audio.readInt();
            long size = Integer.toUnsignedLong(Integer.reverseBytes(audio.readInt()));
            long end = audio.getFilePointer() + size;
            if (end > length) throw new IOException("Аудио повреждено");
            if (chunk == 0x666d7420) {
                if (size < 16) throw new IOException("Аудио повреждено");
                int tag = unsignedShortLE(audio);
                if (unsignedShortLE(audio) != 1 || Integer.reverseBytes(audio.readInt()) != SAMPLE_RATE) {
                    throw new IOException("Нужна моно запись PCM 16 кГц");
                }
                audio.skipBytes(6);
                if (unsignedShortLE(audio) != 16 || !(tag == 1 || (tag == 0xfffe && isExtensiblePcm16(audio, size)))) {
                    throw new IOException("Нужна запись PCM16");
                }
                pcm = true;
            }
            if (chunk == 0x64617461 && pcm && size % 2 == 0) return size;
            audio.seek(end + (size % 2));
        }
        throw new IOException("Аудиоданные WAV недоступны");
    }

    static Envelope envelope(RandomAccessFile audio, int buckets) throws IOException {
        long samples = seekData(audio) / 2;
        float[] peaks = new float[(int) Math.min(buckets, samples)];
        byte[] buffer = new byte[65536];
        long read = 0;
        for (int bucket = 0; bucket < peaks.length; bucket++) {
            long end = samples * (bucket + 1) / peaks.length;
            int peak = 0;
            while (read < end) {
                if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException();
                int count = (int) Math.min(buffer.length / 2, end - read);
                audio.readFully(buffer, 0, count * 2);
                for (int i = 0; i < count * 2; i += 2) {
                    int sample = (short) ((buffer[i] & 0xff) | (buffer[i + 1] << 8));
                    peak = Math.max(peak, Math.abs(sample));
                }
                read += count;
            }
            peaks[bucket] = peak / 32768f;
        }
        return new Envelope(peaks, samples * 1000 / SAMPLE_RATE);
    }

    static final class Envelope {
        final float[] peaks;
        final long durationMillis;

        Envelope(float[] peaks, long durationMillis) {
            this.peaks = peaks;
            this.durationMillis = durationMillis;
        }
    }

    private PcmWave() {}
}
