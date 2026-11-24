import Foundation
import AVFoundation

enum ClipMicPrefix {
    static func read(_ url: URL, trimmingTail seconds: Double) throws -> Data {
        let input = try AVAudioFile(forReading: url, commonFormat: .pcmFormatInt16, interleaved: true)
        let format = input.processingFormat
        guard format.sampleRate == 16000, format.channelCount == 1, input.length <= 12 * 16000 else {
            throw RecorderFailure.message("Не удалось соединить запись телефона и ClipMic")
        }
        let frames = AVAudioFrameCount(max(0, input.length - Int64((seconds * format.sampleRate).rounded())))
        guard frames > 0 else { return Data() }
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else {
            throw RecorderFailure.message("Не удалось прочитать начало записи")
        }
        try input.read(into: buffer, frameCount: frames)
        guard buffer.frameLength == frames, let pcm = buffer.int16ChannelData?[0] else {
            throw RecorderFailure.message("Не удалось прочитать начало записи")
        }
        return Data(bytes: pcm, count: Int(frames) * 2)
    }
}

struct ClipMicPacket {
    let sequence: UInt32
    let offset: Int
    let pcm: Data

    init(_ bytes: Data) throws {
        guard bytes.count >= 10, bytes.count <= 508, bytes.count.isMultiple(of: 2) else {
            throw RecorderFailure.message("Повреждён пакет ClipMic")
        }
        func littleEndian(_ start: Int) -> UInt32 {
            (0..<4).reduce(0) { $0 | UInt32(bytes[bytes.startIndex + start + $1]) << (8 * $1) }
        }
        sequence = littleEndian(0)
        offset = Int(littleEndian(4))
        pcm = Data(bytes.dropFirst(8))
    }
}

final class ClipMicTape {
    private let files: PhoneFiles
    private let temporary: URL
    private let writer: WaveWriter
    private var started: Int64
    private var nextSequence: UInt32 = 0
    private var buffer = Data()
    private var gaps: [[String: Double]] = []
    private var routes: [[String: Any]] = []
    private var prefixFrames = 0
    private var coveredLeading = 0
    private var latestPCM = Data()
    private var lastPacketTime = 0.0
    var recordingName: String { temporary.deletingPathExtension().lastPathComponent }
    var meterLevel: Double {
        guard ProcessInfo.processInfo.systemUptime - lastPacketTime < 0.4 else { return 0 }
        let peak = latestPCM.withUnsafeBytes { raw -> Int in
            var peak = 0
            for index in stride(from: 0, to: raw.count, by: 2) {
                let sample = Int16(littleEndian: raw.loadUnaligned(fromByteOffset: index, as: Int16.self))
                peak = max(peak, abs(Int(sample)))
            }
            return peak
        }
        guard peak > 0 else { return 0 }
        return max(0, min(1, (20 * log10(Double(peak) / 32768) + 60) / 60))
    }
    private(set) var boardFrames = 0
    var frames: Int { prefixFrames + max(0, boardFrames - coveredLeading) }

    init(files: PhoneFiles) throws {
        self.files = files
        started = Int64(Date().timeIntervalSince1970 * 1000)
        temporary = files.folder("drafts").appendingPathComponent(files.name()).appendingPathExtension("clipmic")
        writer = try WaveWriter(temporary)
        try saveMetadata()
    }

    private func saveMetadata(_ interruption: String? = nil) throws {
        var value: [String: Any] = ["source": "ios", "input": "clipmic_ble", "started_ms": started, "gaps": gaps]
        if !routes.isEmpty { value["input_routes"] = routes; value["input"] = "mixed" }
        if let interruption { value["interruption"] = interruption }
        try JSONSerialization.data(withJSONObject: value).write(to: temporary.appendingPathExtension("json"), options: .atomic)
    }

    func prependLocal(_ pcm: Data, startedMs: Int64, inputs: [[String: Any]], leadingMissing: Int = 0) throws {
        guard frames == 0, pcm.count.isMultiple(of: 2) else { throw RecorderFailure.message("Не удалось сохранить начало записи") }
        guard !pcm.isEmpty else { return }
        try writer.write(pcm)
        prefixFrames = pcm.count / 2
        coveredLeading = min(prefixFrames, leadingMissing)
        started = startedMs
        let boundary = Double(prefixFrames) / 16000
        routes = inputs.filter { ($0["at"] as? Double ?? 0) < boundary }
        routes.append(["at": boundary, "name": "ClipMic", "type": "clipmic_ble"])
        try saveMetadata()
    }

    func append(_ data: Data) throws {
        let packet = try ClipMicPacket(data)
        guard packet.offset >= boardFrames, packet.offset - boardFrames <= 160_000, packet.sequence >= nextSequence,
              UInt64(packet.sequence) - UInt64(nextSequence) <= UInt64(packet.offset - boardFrames),
              (packet.sequence == nextSequence) == (packet.offset == boardFrames) else {
            throw RecorderFailure.message("Нарушен порядок аудиопакетов ClipMic")
        }
        let missing = packet.offset - boardFrames - (boardFrames == 0 ? coveredLeading : 0)
        guard missing >= 0 else { throw RecorderFailure.message("Некорректное начало потока ClipMic") }
        let end = packet.offset + packet.pcm.count / 2
        guard end + prefixFrames - coveredLeading <= 8 * 3600 * 16000 else { throw RecorderFailure.message("Достигнут предел длительности записи") }
        if missing > 0 {
            gaps.append(["start": Double(frames) / 16000, "seconds": Double(missing) / 16000])
            buffer.append(Data(repeating: 0, count: missing * 2))
        }
        buffer.append(packet.pcm)
        latestPCM = packet.pcm
        lastPacketTime = ProcessInfo.processInfo.systemUptime
        if boardFrames == 0 || buffer.count >= 32000 || missing > 0 { try flush() }
        boardFrames = end
        nextSequence = packet.sequence + 1
        if missing > 0 { try saveMetadata() }
    }

    private func flush() throws {
        guard !buffer.isEmpty else { return }
        try writer.write(buffer)
        buffer.removeAll(keepingCapacity: true)
    }

    func finish(interruption: String?) throws {
        try flush()
        try saveMetadata(interruption)
        try writer.finish()
        try Self.publish(temporary, files: files)
    }

    static func recover(in files: PhoneFiles) throws {
        let folder = files.folder("drafts")
        let drafts = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
        for draft in drafts where draft.pathExtension == "clipmic" && validRecording(draft.deletingPathExtension().lastPathComponent) {
            try publish(draft, files: files, repairing: true)
        }
    }

    private static func publish(_ temporary: URL, files: PhoneFiles, repairing: Bool = false) throws {
        files.lock.lock()
        defer { files.lock.unlock() }
        let manager = FileManager.default
        let sidecar = temporary.appendingPathExtension("json")
        let length = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard length >= 46 else {
            try manager.removeItem(at: temporary)
            try? manager.removeItem(at: sidecar)
            return
        }
        let target = files.folder("recordings").appendingPathComponent(temporary.deletingPathExtension().lastPathComponent)
        guard !manager.fileExists(atPath: target.path) else {
            throw RecorderFailure.message("В библиотеке уже есть запись с тем же именем")
        }
        if repairing {
            try WaveWriter.repair(temporary)
            var meta = ((try? Data(contentsOf: sidecar)).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]) ?? [:]
            meta["source"] = "ios"
            if meta["input"] == nil { meta["input"] = "clipmic_ble" }
            meta["interruption"] = "Запись восстановлена после закрытия приложения"
            try JSONSerialization.data(withJSONObject: meta).write(to: sidecar, options: .atomic)
        }
        let meta = try Data(contentsOf: sidecar)
        try meta.write(to: target.appendingPathExtension("json"), options: .atomic)
        try manager.moveItem(at: temporary, to: target)
        try? manager.removeItem(at: sidecar)
    }
}
