import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWIFT = ROOT / "outputs/ios/LectureRecorder"


class ClipMicCaptureTests(unittest.TestCase):
    def test_packets_handoff_disconnect_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            harness = folder / "Capture.swift"
            harness.write_text(r'''
import Foundation
import AVFoundation

@main struct CaptureTest {
    static func packet(_ index: UInt32, _ offset: UInt32, _ samples: [UInt16]) -> Data {
        var data = Data()
        for number in [index, offset] {
            for n in 0..<4 { data.append(UInt8(truncatingIfNeeded: number >> (n * 8))) }
        }
        for sample in samples {
            data.append(UInt8(truncatingIfNeeded: sample))
            data.append(UInt8(truncatingIfNeeded: sample >> 8))
        }
        return data
    }

    static func invalid(_ block: () throws -> Void) {
        do { try block(); fatalError("Повреждённый пакет принят") } catch {}
    }

    static func main() throws {
        let files = try PhoneFiles(root: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true))
        let tape = try ClipMicTape(files: files)
        let route: [[String: Any]] = [["at": 0.0, "name": "Гарнитура", "type": "HeadsetMic"]]
        try tape.prependLocal(Data([91, 0, 92, 0]), startedMs: 1000, inputs: route)
        try tape.append(packet(0, 0, [21, 22]))
        try tape.append(packet(2, 5, [24]))
        precondition(tape.frames == 8)
        invalid { try tape.append(packet(2, 5, [24])) }
        invalid { try tape.append(packet(3, 7, [25])) }
        invalid { try tape.append(packet(5, 6, [26])) }
        invalid { try tape.append(packet(4, 160007, [27])) }
        invalid { try tape.append(packet(UInt32.max, 8, [28])) }
        invalid { try tape.append(Data([1, 2, 3])) }
        try tape.finish(interruption: "Связь прервалась")
        let entry = try files.list().first!
        let file = files.localAudio(entry["name"] as! String)!
        let wave = try Data(contentsOf: file)
        precondition(Array(wave.dropFirst(44)) == [91, 0, 92, 0, 21, 0, 22, 0, 0, 0, 0, 0, 0, 0, 24, 0])
        precondition(entry["input"] as? String == "mixed" && entry["started_ms"] as? Int == 1000)
        let routes = entry["input_routes"] as! [[String: Any]]
        precondition(routes.count == 2 && routes[0]["name"] as? String == "Гарнитура")
        precondition(routes[1]["at"] as? Double == 2.0 / 16000)
        let gap = (entry["gaps"] as! [[String: Double]])[0]
        precondition(gap["start"] == 4.0 / 16000 && gap["seconds"] == 3.0 / 16000)
        precondition(entry["interruption"] as? String == "Связь прервалась")
        let prefixRoot = try PhoneFiles(root: files.root.appendingPathComponent("prefix"))
        let caf = files.root.appendingPathComponent("input.caf")
        let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
        do {
            let writer = try AVAudioFile(forWriting: caf, settings: format.settings, commonFormat: .pcmFormatInt16, interleaved: true)
            let samples = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 5)!
            samples.frameLength = 5
            for n in 0..<5 { samples.int16ChannelData![0][n] = Int16(n + 1) }
            try writer.write(from: samples)
        }
        let prefix = try ClipMicPrefix.read(caf, trimmingTail: 2.0 / 16000)
        precondition(Array(prefix) == [1, 0, 2, 0, 3, 0])
        let trimmed = try ClipMicPrefix.read(caf, trimmingTail: 1)
        precondition(trimmed.isEmpty)
        let leadingLoss = try ClipMicTape(files: prefixRoot)
        try leadingLoss.prependLocal(prefix, startedMs: 1000, inputs: route, leadingMissing: 2)
        try leadingLoss.append(packet(1, 2, [4, 5]))
        try leadingLoss.append(packet(2, 4, [6]))
        precondition(leadingLoss.frames == 6)
        try leadingLoss.finish(interruption: nil)
        let combined = try Data(contentsOf: prefixRoot.recordings()[0])
        precondition(Array(combined.dropFirst(44)) == [1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0])
        let prefixMeta = try prefixRoot.list()[0]
        precondition((prefixMeta["gaps"] as! [[String: Any]]).isEmpty)
        let empty = try ClipMicTape(files: files)
        try empty.finish(interruption: nil)
        precondition(files.recordings().count == 1)
        do {
            let torn = try ClipMicTape(files: files)
            try torn.append(packet(0, 0, [49]))
        }
        try ClipMicTape.recover(in: files)
        try ClipMicTape.recover(in: files)
        let recovered = files.recordings().first { $0.lastPathComponent != file.lastPathComponent }!
        let recoveredAudio = try Data(contentsOf: recovered)
        precondition(Array(recoveredAudio.suffix(2)) == [49, 0] && recoveredAudio.count == 46)
        precondition(String(decoding: recoveredAudio.prefix(4), as: UTF8.self) == "RIFF")
        let rows = try files.list()
        precondition(rows.count == 2)
        let record = rows.first { $0["name"] as? String == recovered.lastPathComponent }!
        precondition(record["input"] as? String == "clipmic_ble" && record["interruption"] != nil)
    }
}
''', encoding="utf-8")
            program = folder / "capture"
            subprocess.run(["xcrun", "swiftc", str(SWIFT / "RecorderCore.swift"), str(SWIFT / "ClipMicAudio.swift"),
                            str(harness), "-o", str(program)], check=True)
            subprocess.run([str(program), str(folder / "library")], check=True)


if __name__ == "__main__":
    unittest.main()
