package ru.ilya.lecturerecorder;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

final class StereoPcmMix {
    private boolean opposite = true;
    private long firstSignalFrame = -1;
    private long mixedFromFrame;

    void consume(ByteBuffer input, PcmResampler output) throws IOException {
        if (input.remaining() % 4 != 0) throw new IOException("Неполный стереокадр PCM");
        input.order(ByteOrder.LITTLE_ENDIAN);
        while (input.hasRemaining()) {
            int left = input.getShort();
            int sum = left + input.getShort();
            if (opposite && sum != 0) {
                opposite = false;
                if (firstSignalFrame >= 0) {
                    mixedFromFrame = output.frames();
                    output.clearSignalHistory();
                }
            }
            if (opposite && left != 0 && firstSignalFrame < 0) firstSignalFrame = output.frames();
            output.sample(opposite ? left : sum * 0.5);
        }
    }

    void finish(File wav, long dataOffset) throws IOException {
        if (opposite || firstSignalFrame < 0 || firstSignalFrame >= mixedFromFrame) return;
        long remaining = (mixedFromFrame - firstSignalFrame) * 2;
        byte[] silence = new byte[(int) Math.min(65536, remaining)];
        try (RandomAccessFile output = new RandomAccessFile(wav, "rw")) {
            output.seek(dataOffset + firstSignalFrame * 2);
            while (remaining > 0) {
                int count = (int) Math.min(remaining, silence.length);
                output.write(silence, 0, count);
                remaining -= count;
            }
        }
    }
}
