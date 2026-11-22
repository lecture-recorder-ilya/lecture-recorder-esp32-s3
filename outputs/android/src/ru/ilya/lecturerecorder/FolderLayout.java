package ru.ilya.lecturerecorder;

import java.util.LinkedHashMap;
import java.util.Map;

final class FolderLayout {
    static final int COLUMNS = 4;
    static final int MIN_WIDTH = 2;
    static final int MAX_HEIGHT = 3;

    private FolderLayout() {}

    static final class Tile {
        final int column, row, width, height;

        Tile(int column, int row, int width, int height) {
            this.width = Math.max(MIN_WIDTH, Math.min(COLUMNS, width));
            this.height = Math.max(1, Math.min(MAX_HEIGHT, height));
            this.column = Math.max(0, Math.min(COLUMNS - this.width, column));
            this.row = Math.max(0, row);
        }

        boolean overlaps(Tile other) {
            return column < other.column + other.width && other.column < column + width
                    && row < other.row + other.height && other.row < row + height;
        }
    }

    static int rows(Map<String, Tile> layout) {
        int rows = 0;
        for (Tile tile : layout.values()) rows = Math.max(rows, tile.row + tile.height);
        return rows;
    }

    static boolean fits(Map<String, Tile> layout, Tile tile) {
        for (Tile other : layout.values()) if (tile.overlaps(other)) return false;
        return true;
    }

    static Tile firstFree(Map<String, Tile> layout, int start, int width, int height) {
        for (int row = start; ; row++) {
            for (int column = 0; column <= COLUMNS - width; column++) {
                Tile tile = new Tile(column, row, width, height);
                if (fits(layout, tile)) return tile;
            }
        }
    }

    static Map<String, Tile> change(Map<String, Tile> layout, String recording, Tile target) {
        Map<String, Tile> placed = new LinkedHashMap<>();
        Map<String, Tile> displaced = new LinkedHashMap<>();
        placed.put(recording, target);
        for (Map.Entry<String, Tile> entry : layout.entrySet()) {
            if (recording.equals(entry.getKey())) continue;
            if (entry.getValue().overlaps(target)) displaced.put(entry.getKey(), entry.getValue());
            else placed.put(entry.getKey(), entry.getValue());
        }
        Tile previous = layout.get(recording);
        for (Map.Entry<String, Tile> entry : displaced.entrySet()) {
            Tile other = entry.getValue();
            Tile replacement = new Tile(previous.column, previous.row, other.width, other.height);
            placed.put(entry.getKey(), fits(placed, replacement) ? replacement
                    : firstFree(placed, target.row + target.height, other.width, other.height));
        }
        return placed;
    }
}
