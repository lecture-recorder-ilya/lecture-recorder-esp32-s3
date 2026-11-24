import AVFoundation
import Foundation

enum RecordingImport {
    static func save(_ source: URL, in files: PhoneFiles, recoveringDraft: Bool) async throws -> String {
        let access = source.startAccessingSecurityScopedResource()
        defer { if access { source.stopAccessingSecurityScopedResource() } }

        let temporary = files.folder("drafts").appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let asset = AVURLAsset(url: source)
        guard let track = try await asset.loadTracks(withMediaType: .audio).first else {
            throw RecorderFailure.message("В файле нет аудиодорожки")
        }
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false
        ])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw RecorderFailure.message("Этот формат не открылся") }
        reader.add(output)
        let writer = try WaveWriter(temporary)
        guard reader.startReading() else { throw reader.error ?? RecorderFailure.message("Не удалось открыть аудиозапись") }
        while let sample = output.copyNextSampleBuffer() {
            guard let buffer = CMSampleBufferGetDataBuffer(sample) else { continue }
            let count = CMBlockBufferGetDataLength(buffer)
            guard count > 0 else { continue }
            var data = Data(count: count)
            let status = data.withUnsafeMutableBytes {
                CMBlockBufferCopyDataBytes(buffer, atOffset: 0, dataLength: count, destination: $0.baseAddress!)
            }
            guard status == noErr else { throw RecorderFailure.message("Аудиофайл повреждён") }
            try writer.write(data)
        }
        guard reader.status == .completed else { throw reader.error ?? RecorderFailure.message("Чтение аудио прервалось") }
        try writer.finish()
        guard (try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) > 44 else {
            throw RecorderFailure.message("Аудиозапись пустая")
        }

        var metadata: [String: Any] = [
            "source": "ios", "started_ms": Int64(Date().timeIntervalSince1970 * 1000),
            "imported": !recoveringDraft, "original_name": source.lastPathComponent, "gaps": []
        ]
        let sidecar = source.appendingPathExtension("json")
        if recoveringDraft, let data = try? Data(contentsOf: sidecar),
           let values = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            for key in ["started_ms", "input_routes"] where values[key] != nil { metadata[key] = values[key] }
        }
        let name = try publish(temporary, metadata: metadata, in: files)
        if recoveringDraft {
            try? FileManager.default.removeItem(at: source)
            try? FileManager.default.removeItem(at: sidecar)
        }
        return name
    }

    private static func publish(_ temporary: URL, metadata: [String: Any], in files: PhoneFiles) throws -> String {
        files.lock.lock()
        defer { files.lock.unlock() }
        var target = files.folder("recordings").appendingPathComponent(files.name())
        while files.localAudio(target.lastPathComponent) != nil {
            target = files.folder("recordings").appendingPathComponent(files.name())
        }
        let sidecar = target.appendingPathExtension("json")
        try JSONSerialization.data(withJSONObject: metadata).write(to: sidecar, options: .atomic)
        do { try FileManager.default.moveItem(at: temporary, to: target) }
        catch {
            try? FileManager.default.removeItem(at: sidecar)
            throw error
        }
        return target.lastPathComponent
    }
}
