import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/ios/LectureRecorder'


class OfflineTranscriptTests(unittest.TestCase):
    def test_windows_timestamps_and_existing_note(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            harness = folder / 'Check.swift'
            harness.write_text('''import AVFoundation
import Foundation

@main struct Check {
    @MainActor static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let files = try PhoneFiles(root: root)
        let path = root.appendingPathComponent("input.wav")
        let count = 105 * 16000
        let format = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
        do {
            let output = try AVAudioFile(forWriting: path, settings: format.settings)
            let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count))!
            pcm.frameLength = pcm.frameCapacity
            for i in 0..<count {
                pcm.floatChannelData![0][i] = (48 * 16000..<49 * 16000).contains(i) ? 0 : 0.001
            }
            try output.write(from: pcm)
        }
        let input = try AVAudioFile(forReading: path, commonFormat: .pcmFormatFloat32, interleaved: false)
        var frames = 0
        var windows = 0
        while input.framePosition < input.length {
            let window = try OfflineSpeechWindow.read(from: input)
            precondition(window.start == Double(frames) / 16000)
            precondition(!window.silent)
            frames += Int(window.buffer.frameLength)
            if windows == 0 { precondition((48 * 16000..<49 * 16000).contains(frames)) }
            windows += 1
        }
        precondition(windows == 3 && frames == count, [windows, frames, count, Int(input.length)].description)
        let words = [OfflineSpeechWord(text: "Ток", start: 0.2, duration: 0.4, confidence: 0.88),
                     OfflineSpeechWord(text: "мал", start: 0.7, duration: 0.2, confidence: 0.3),
                     OfflineSpeechWord(text: "Пауза", start: 2, duration: 0.4, confidence: 0.9)]
        let rows = OfflineSpeechWord.phrases(words, offset: 50, length: 4)
        precondition(rows.count == 2 && rows[0]["text"] as? String == "Ток мал")
        precondition(rows[0]["needs_review"] as? Bool == true && rows[1]["needs_review"] as? Bool == false)
        precondition(rows[0]["word_times"] as? [[Int]] == [[0,3,50200],[4,7,50700]])
        precondition(rows[1]["start"] as? Double == 52)
        let note = files.folder("notes").appendingPathComponent("existing.json")
        try OnDeviceTranscript.saveNew(Data([1]), at: note, files: files)
        try OnDeviceTranscript.saveNew(Data([2]), at: note, files: files)
        let saved = try Data(contentsOf: note)
        precondition(saved == Data([1]))

        func row(_ text: String, _ at: Double, uncertain: Bool = false) -> [String: Any] {
            ["text": text, "start": at, "end": at + 1, "needs_review": uncertain]
        }
        let samples = [
            row("Производная функции определяется как предел отношения приращений.", 0),
            row("Сила тока измеряется в амперах.", 4),
            row("Чему равна производная функции?", 8),
            row("Рекурсия это вызов функции из неё самой.", 12),
            row("Температура на улице равна десяти градусам.", 16),
            row("Дома решите задачи семь и восемь.", 20),
            row("Дома не нужно решать задачу номер два.", 24),
            row("К следующей паре прочитайте третью главу.", 28),
            row("Молекула воды состоит из атомов водорода и кислорода.", 32, uncertain: true),
            row("Если сопротивление постоянно, то сила тока пропорциональна напряжению.", 36),
            row("Например, эта функция называется линейной.", 40),
            row("Дома решите задачу, если захотите.", 44),
            row("Сила тока равна", 48),
            row("Сосед сказал, дома решите задачу номер восемь.", 52),
            row("Что такое функция", 56),
            row("За обедом прочитайте меню дома.", 60),
            row("Сила тока измеряется в амперах.", 64)
        ]
        let extracted = OfflineNoteSelection.report(samples)
        let evidence = extracted["summary_evidence"] as! [[String: Any]]
        let assignments = extracted["homework"] as! [[String: Any]]
        precondition(evidence.compactMap { $0["segment_id"] as? Int } == [0, 1, 3, 9], String(describing: evidence))
        precondition(assignments.compactMap { $0["segment_id"] as? Int } == [5, 7], String(describing: assignments))
        let cancelled = OfflineNoteSelection.report([
            row("Дома решите задачу номер семь.", 0), row("Задание на дом отменено.", 5),
            row("Дома прочитайте главу о графах.", 20),
            row("Равномерная скорость равна четырём метрам в секунду.", 30),
            row("Нет, эту фразу исправим.", 31)
        ])
        precondition((cancelled["summary"] as? [String])?.isEmpty == true)
        precondition((cancelled["homework"] as? [[String: Any]])?.compactMap { $0["segment_id"] as? Int } == [2])
        try JSONSerialization.data(withJSONObject: extracted).write(to: root.appendingPathComponent("summary-test.json"))
    }
}
''')
            executable = folder / 'check'
            subprocess.run([
                'xcrun', 'swiftc', '-target', 'arm64-apple-macos14.0',
                str(SOURCE / 'RecorderCore.swift'), str(SOURCE / 'OfflineNoteSelection.swift'), str(SOURCE / 'OnDeviceTranscript.swift'),
                str(harness), '-o', str(executable),
            ], check=True, timeout=90)
            subprocess.run([executable, directory], check=True, timeout=30)
            sys.path.insert(0, str(ROOT / "outputs/recorder"))
            from summary_sources import reconcile
            report = json.loads((folder / "summary-test.json").read_text())
            verified = reconcile(report)
            for item in report["summary_evidence"] + report["homework"]:
                segment = report["segments"][item["segment_id"]]
                self.assertEqual((item["quote"], item["start"], item["end"]),
                                 (segment["text"], segment["start"], segment["end"]))
            for key in ("summary_evidence", "homework"):
                self.assertEqual(verified[key], report[key])


if __name__ == '__main__':
    unittest.main()
