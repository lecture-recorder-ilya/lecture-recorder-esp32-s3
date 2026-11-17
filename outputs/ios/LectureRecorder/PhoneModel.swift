import Foundation
import AVFoundation
import Combine
import CoreMedia

struct LectureNote: Decodable, Identifiable {
    let file: String
    let report: Report
    var id: String { file }
    struct Report: Decodable {
        var subject: String?
        var topic: String?
        var overview: String?
        var summary: [String]?
        var segments: [Segment]?
    }
    struct Segment: Decodable {
        var start: Double?
        var end: Double?
        var text: String
        var needs_review: Bool?
    }
}

@MainActor final class PhoneModel: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published var recordings: [URL] = []
    @Published var notes: [LectureNote] = []
    @Published var drafts: [URL] = []
    @Published var recording = false
    @Published var busy = false
    @Published var seconds = 0.0
    @Published var message = "Готово к записи"
    @Published var macName = SavedMac.load()?.name ?? "Mac не подключён"
    @Published var pairing = false
    @Published var verification = ""
    let files: PhoneFiles
    private var recorder: AVAudioRecorder?
    private var draft: URL?
    private var player: AVAudioPlayer?
    private var sync: PhoneSyncServer?
    private var timer: Timer?
    private var pairingTask: Task<Void, Never>?
    private var notesRevision = ""

    override init() {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Lectures", isDirectory: true)
        do { files = try PhoneFiles(root: root) } catch { fatalError("Не удалось открыть хранилище приложения") }
        super.init(); refresh(); startSync()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in Task { @MainActor in
            guard let self = self else { return }; self.seconds = self.recorder?.currentTime ?? 0; self.refresh()
        } }
        NotificationCenter.default.addObserver(self, selector: #selector(interrupted), name: AVAudioSession.interruptionNotification, object: nil)
    }
    func refresh() {
        let current = files.recordings(); if current != recordings { recordings = current }
        let noteFiles = (try? FileManager.default.contentsOfDirectory(at: files.folder("notes"), includingPropertiesForKeys: nil)) ?? []
        let revision = noteFiles.sorted { $0.path < $1.path }.map { url -> String in let value = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]); return url.lastPathComponent + String(value?.contentModificationDate?.timeIntervalSince1970 ?? 0) + String(value?.fileSize ?? 0) }.joined(separator: "|")
        if revision != notesRevision { notesRevision = revision; notes = noteFiles.sorted { $0.lastPathComponent > $1.lastPathComponent }.compactMap { url in (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode(LectureNote.self, from: $0) } } }
        drafts = ((try? FileManager.default.contentsOfDirectory(at: files.folder("drafts"), includingPropertiesForKeys: nil)) ?? []).filter { $0.pathExtension == "caf" && $0 != draft }
    }
    func startRecording() {
        guard !recording, !busy else { return }; busy = true
        AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in Task { @MainActor in
            guard let self = self else { return }; self.busy = false
            guard allowed else { self.message = "Разреши микрофон в настройках iPhone"; return }
            do {
                self.stopPlayback()
                let session = AVAudioSession.sharedInstance(); try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth]); try session.setActive(true)
                let url = self.files.folder("drafts").appendingPathComponent(UUID().uuidString + ".caf")
                let recorder = try AVAudioRecorder(url: url, settings: [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
                recorder.delegate = self; guard recorder.record(forDuration: 8 * 3600) else { throw RecorderFailure.message("Не удалось включить микрофон") }
                self.recorder = recorder; self.draft = url; self.recording = true; self.message = "Идёт запись · экран можно заблокировать"
            } catch { self.message = error.localizedDescription }
        } }
    }
    func stopRecording() {
        guard let url = draft else { return }; draft = nil; recorder?.stop(); recorder = nil; recording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        importAudio(url, removeDraft: true)
    }
    @objc private func interrupted(_ notification: Notification) {
        if let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt, type == AVAudioSession.InterruptionType.began.rawValue { stopRecording() }
    }
    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) { Task { @MainActor in if self.draft != nil { self.stopRecording() } } }
    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) { Task { @MainActor in self.stopRecording() } }
    func importAudio(_ source: URL, removeDraft: Bool = false) {
        guard !busy, !recording else { return }; busy = true; message = "Сохраняю запись…"
        let target = files.folder("recordings").appendingPathComponent(files.name()), temporary = files.folder("drafts").appendingPathComponent(UUID().uuidString + ".wav")
        Task {
            do {
                try await Task.detached(priority: .utility) {
                    let permitted = source.startAccessingSecurityScopedResource(); defer { if permitted { source.stopAccessingSecurityScopedResource() } }
                    let asset = AVURLAsset(url: source)
                    guard let track = asset.tracks(withMediaType: .audio).first else { throw RecorderFailure.message("В файле нет аудиодорожки") }
                    let reader = try AVAssetReader(asset: asset)
                    let output = AVAssetReaderTrackOutput(track: track, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false])
                    output.alwaysCopiesSampleData = false; guard reader.canAdd(output) else { throw RecorderFailure.message("Этот формат не открылся") }; reader.add(output)
                    let writer = try WaveWriter(temporary)
                    guard reader.startReading() else { throw RecorderFailure.message("Не удалось открыть аудиозапись") }
                    while let sample = output.copyNextSampleBuffer() {
                        if let buffer = CMSampleBufferGetDataBuffer(sample) {
                            let length = CMBlockBufferGetDataLength(buffer); var data = Data(count: length)
                            let status = data.withUnsafeMutableBytes { CMBlockBufferCopyDataBytes(buffer, atOffset: 0, dataLength: length, destination: $0.baseAddress!) }
                            guard status == noErr else { throw RecorderFailure.message("Аудиофайл повреждён") }; try writer.write(data)
                        }
                    }
                    guard reader.status == .completed else { throw reader.error ?? RecorderFailure.message("Чтение аудио прервалось") }
                    try writer.finish()
                    guard (try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) > 44 else { throw RecorderFailure.message("Аудиозапись пустая") }
                    let meta: [String: Any] = ["source": "ios", "started_ms": Int64(Date().timeIntervalSince1970 * 1000), "imported": !removeDraft, "original_name": source.lastPathComponent, "gaps": []]
                    try JSONSerialization.data(withJSONObject: meta).write(to: target.appendingPathExtension("json"), options: .atomic)
                    try FileManager.default.moveItem(at: temporary, to: target)
                    if removeDraft { try? FileManager.default.removeItem(at: source) }
                }.value
                message = "Запись сохранена · открой приложение рядом с Mac для переноса"
            } catch { try? FileManager.default.removeItem(at: temporary); message = error.localizedDescription }
            busy = false; refresh()
        }
    }
    func play(_ url: URL, at seconds: Double = 0) {
        guard !recording else { return }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback); try AVAudioSession.sharedInstance().setActive(true)
            player = try AVAudioPlayer(contentsOf: url); player?.currentTime = max(0, seconds); player?.play()
        } catch { message = "Не удалось воспроизвести запись" }
    }
    func stopPlayback() { player?.stop(); player = nil }
    func startSync() {
        guard let mac = SavedMac.load() else { return }; sync?.stop(); sync = PhoneSyncServer(files: files, key: mac.token)
        do { try sync?.start(); macName = mac.name } catch { message = "Не удалось включить перенос. Закрой и открой приложение." }
    }
    func disconnect() { guard !recording else { return }; pairingTask?.cancel(); sync?.stop(); sync = nil; SavedMac.forget(); macName = "Mac не подключён" }
    func connect(host: String, code: String) {
        guard !recording, !pairing else { return }
        let host = host.trimmingCharacters(in: .whitespacesAndNewlines), code = code.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        guard host.range(of: "^[A-Za-z0-9.-]{1,253}$", options: .regularExpression) != nil, code.range(of: "^[A-Z2-7]{12}$", options: .regularExpression) != nil else { message = "Введи адрес Mac и 12 символов его кода"; return }
        pairing = true; verification = ""; message = "Подключаюсь к Mac…"
        pairingTask = Task {
            defer { pairing = false }
            do {
                let client = PinnedMac(host: host, code: code)
                let request = try await client.post("/pair/request", ["name": "iPhone / iPad", "device_id": UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(), "nonce": UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()])
                guard let id = request["request_id"] as? String else { throw RecorderFailure.message("Запрос не создан") }
                verification = request["verification"] as? String ?? ""; message = "Сравни цифры с Mac и подтверди подключение на компьютере"
                for _ in 0..<300 {
                    try Task.checkCancellation()
                    let reply = try await client.post("/pair/status", ["request_id": id])
                    if ["approved", "complete"].contains(reply["status"] as? String ?? ""), let token = reply["sync_token"] as? String, token.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil {
                        try Task.checkCancellation(); try SavedMac(host: host, name: reply["mac_name"] as? String ?? "Mac", token: token).save()
                        _ = try? await client.post("/pair/ack", ["request_id": id]); startSync(); verification = ""; message = "Mac подключён · записи и тексты переносятся автоматически"; return
                    }
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                }
                throw RecorderFailure.message("Код истёк. Открой подключение на Mac заново")
            } catch is CancellationError { message = "Подключение отменено" }
            catch { message = "Не удалось подключиться. Проверь код, дату и общую Wi-Fi сеть. " + error.localizedDescription }
        }
    }
    func cancelPairing() { pairingTask?.cancel(); pairing = false; verification = "" }
}
