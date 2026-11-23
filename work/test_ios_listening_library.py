import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/ios/LectureRecorder"


class ListeningLibraryTests(unittest.TestCase):
    def test_search_legacy_records_and_saved_listening_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            harness = folder / "Check.swift"
            harness.write_text(r'''import Foundation

@main struct Check {
    @MainActor static func main() throws {
        let first = "lecture-2026-11-24-10-00-00-100001.wav"
        let second = "lecture-2026-11-23-13-50-00-100002.wav"
        let third = "lecture-2026-11-20-09-00-00-100003.wav"
        let data: [String: Any] = ["file": first, "lesson": ["subject": "Физика", "teacher": "Иван Петров"],
            "report": ["topic": "Электричество", "summary": ["Цепи переменного тока"],
                       "segments": [["text": "Проводник нагрелся.", "start": 2.5, "end": 4],
                                    ["text": "Ёмкость конденсатора.", "start": 6.0, "end": 7]],
                       "homework": [["task": "Решите задачу о поле"]]]]
        let old: [String: Any] = ["file": second, "lesson": "Старый формат", "report": ["subject": "Алгебра", "segments": [["text": "Базис пространства"]]]]
        let notes = try [data, old].map { try JSONDecoder().decode(LectureNote.self, from: JSONSerialization.data(withJSONObject: $0)) }
        let directory = URL(fileURLWithPath: "/audio")
        let audio = [first, first, third].map { directory.appendingPathComponent($0) }
        let rows = LibraryItem.list(audio, notes: notes) { $0 == third ? "Эскиз.m4a" : nil }
        precondition(rows.count == 3 && rows.map(\.id) == [first, second, third])
        precondition(rows[0].audio != nil && rows[0].note != nil && rows[0].title == "Электричество")
        precondition(rows[1].audio == nil && rows[1].title == "Алгебра")
        precondition(rows[2].note == nil && rows[2].title == "Эскиз")
        precondition(rows[0].result(for: LibraryItem.terms("  ЕМКОСТЬ  "))?.match?.location == .segment(1))
        precondition(rows[0].result(for: LibraryItem.terms("физика конденсатора"))?.match?.location == .segment(1))
        precondition(rows[0].result(for: LibraryItem.terms("Переменного тока"))?.match?.location == .summary(0))
        precondition(rows[0].result(for: LibraryItem.terms("задачу о поле"))?.match?.location == .homework(0))
        precondition(rows[0].result(for: LibraryItem.terms("Петров"))?.match == nil)
        precondition(rows[0].result(for: LibraryItem.terms("Петров")) != nil)
        precondition(rows[1].result(for: LibraryItem.terms("несуществующая фраза")) == nil)
        precondition(rows[2].result(for: LibraryItem.terms("Эскиз")) != nil)
        var metadataReads = 0
        let reused = LibraryItem.list(audio, notes: notes, previous: rows, changedNotes: [second]) { _ in metadataReads += 1; return nil }
        precondition(metadataReads == 1 && reused.map(\.title) == rows.map(\.title))
        let suite = "ClipMic.LibraryTest." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let prefs = ListeningLibrary(defaults: defaults)
        precondition(prefs.rate == 1 && prefs.bookmarks(first).isEmpty && prefs.position(first) == 0)
        prefs.toggleFavorite(first); prefs.toggleFavorite(second); prefs.toggleFavorite(second)
        prefs.addBookmark(first, name: "  Итог  ", at: 17.5)
        prefs.addBookmark(first, name: "Начало", at: 2.75)
        prefs.addBookmark(first, name: " ", at: 3)
        prefs.addBookmark(second, name: "Другая запись", at: 5)
        prefs.savePosition(24.5, for: first); prefs.savePosition(.nan, for: first)
        prefs.setRate(1.5); prefs.setRate(9)
        let returned = ListeningLibrary(defaults: UserDefaults(suiteName: suite)!)
        precondition(returned.favorites == [first] && returned.position(first) == 24.5 && returned.rate == 1.5)
        let marks = returned.bookmarks(first)
        precondition(marks.map(\.name) == ["Начало", "Итог"] && marks.map(\.time) == [2.75, 17.5])
        returned.removeBookmark(marks[0].id, from: first)
        let again = ListeningLibrary(defaults: UserDefaults(suiteName: suite)!)
        precondition(again.bookmarks(first).map(\.id) == [marks[1].id] && again.bookmarks(second).count == 1)
    }
}
''', encoding="utf8")
            binary = folder / "check"
            subprocess.run(["xcrun", "swiftc", "-target", "arm64-apple-macos14.0",
                            str(SOURCE / "LibraryCatalog.swift"), str(SOURCE / "ListeningLibrary.swift"),
                            str(harness), "-o", str(binary)], check=True, timeout=90)
            subprocess.run([str(binary)], check=True, timeout=30)


    def test_playback_actions_resume_the_correct_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            harness = folder / "PlaybackCheck.swift"
            harness.write_text(r'''import AVFoundation
import Foundation

protocol AVAudioPlayerDelegate: AnyObject {}
final class AVAudioPlayer {
    static var last: AVAudioPlayer?
    weak var delegate: AVAudioPlayerDelegate?
    var currentTime = 0.0, duration = 90.0, enableRate = false
    var rate: Float = 1
    init(contentsOf _: URL) throws { Self.last = self }
    func play() -> Bool { true }
    func pause() {}
    func stop() { currentTime = 0 }
}
final class AVAudioSession {
    enum Category { case playback }
    enum Options { case notifyOthersOnDeactivation }
    static let session = AVAudioSession()
    static func sharedInstance() -> AVAudioSession { session }
    func setCategory(_ category: Category) throws {}
    func setActive(_ active: Bool, options: Options? = nil) throws {}
}
@main struct Check {
    @MainActor static func main() async throws {
        let suite = "ClipMic.PlaybackTest." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let library = ListeningLibrary(defaults: defaults)
        let first = URL(fileURLWithPath: "/recordings/a.wav"), second = URL(fileURLWithPath: "/library/b.wav")
        library.savePosition(13.25, for: first.lastPathComponent)
        let playback = LecturePlayback(library: library)
        try playback.play(first)
        precondition(playback.playing && playback.elapsed == 13.25 && playback.file == "a.wav")
        playback.setRate(1.5)
        let old = AVAudioPlayer.last!
        precondition(old.enableRate && old.rate == 1.5)
        old.currentTime = 18.75
        playback.tick()
        precondition(playback.elapsed == 18.75)
        playback.pause()
        precondition(!playback.playing && library.position("a.wav") == 18.75)
        try playback.play(first, at: 42)
        precondition(AVAudioPlayer.last === old && playback.elapsed == 42)
        playback.seek("b.wav", to: 6.25, duration: 90)
        try playback.play(second)
        let next = AVAudioPlayer.last!
        precondition(next !== old && playback.elapsed == 6.25 && next.rate == 1.5)
        precondition(library.position("a.wav") == 42)
        next.currentTime = 21
        playback.checkpoint()
        playback.stop()
        precondition(playback.file == nil && library.position("b.wav") == 21)
        try playback.play(second)
        precondition(playback.elapsed == 21)
        playback.audioPlayerDidFinishPlaying(old, successfully: true)
        await Task.yield()
        precondition(playback.file == "b.wav")
        playback.audioPlayerDidFinishPlaying(AVAudioPlayer.last!, successfully: true)
        for _ in 0..<3 { await Task.yield() }
        precondition(playback.file == nil && library.position("b.wav") == 0 && library.position("a.wav") == 42)
    }
}
''', encoding="utf8")
            binary = folder / "playback"
            subprocess.run(["xcrun", "swiftc", "-target", "arm64-apple-macos14.0",
                            str(SOURCE / "ListeningLibrary.swift"), str(SOURCE / "LecturePlayback.swift"),
                            str(SOURCE / "RecorderCore.swift"), str(harness), "-o", str(binary)], check=True, timeout=90)
            subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
