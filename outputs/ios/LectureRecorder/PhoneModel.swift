import Foundation
import AVFoundation
import Combine
import CoreMedia
import CoreBluetooth

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
        var summary_evidence: [Citation]?
        var homework: [Citation]?
        var summary_method: String?

        enum CodingKeys: String, CodingKey {
            case subject, topic, overview, summary, segments, summary_evidence, homework, summary_method
        }

        init(from decoder: Decoder) throws {
            let fields = try decoder.container(keyedBy: CodingKeys.self)
            subject = try fields.decodeIfPresent(String.self, forKey: .subject)
            topic = try fields.decodeIfPresent(String.self, forKey: .topic)
            overview = try fields.decodeIfPresent(String.self, forKey: .overview)
            summary = try fields.decodeIfPresent([String].self, forKey: .summary)
            segments = try fields.decodeIfPresent([Segment].self, forKey: .segments)
            summary_evidence = try? fields.decode([Citation].self, forKey: .summary_evidence)
            homework = try? fields.decode([Citation].self, forKey: .homework)
            summary_method = try? fields.decode(String.self, forKey: .summary_method)
        }

        func sourceTime(_ citation: Citation?) -> Double? {
            guard let citation, citation.source_status == "confirmed", let quote = citation.quote,
                  let id = citation.segment_id, let segments, segments.indices.contains(id) else { return nil }
            let source = segments[id]
            guard source.start == citation.start, source.end == citation.end, source.text == quote,
                  source.needs_review != true else { return nil }
            return citation.start
        }
    }
    struct Citation: Decodable {
        var quote: String?
        var task: String?
        var source_status: String?
        var segment_id: Int?
        var start: Double?
        var end: Double?
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
    @Published var inputLabel = "Автовыбор микрофона"
    @Published var findingBoard = false
    @Published var boards: [ClipMicChoice] = []
    @Published var boardStatus = ""
    @Published var boardID = UserDefaults.standard.string(forKey: "clipmic.peripheral").flatMap(UUID.init(uuidString:))
    @Published var transcribingFile: String?
    @Published var transcriptionProgress = 0
    private var captureID: UUID?
    var starting: Bool { captureID != nil && busy && !recording }
    private var bluetooth: ClipMicBluetooth?
    private var tape: ClipMicTape?
    private var inputChanges: [[String: Any]] = []
    private var localStarted: Int64 = 0
    private var recognitionTask: Task<Void, Never>?
    private var recognitionID: UUID?
    private lazy var localTranscript = OnDeviceTranscript()
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
        super.init()
        do { try ClipMicTape.recover(in: files) } catch { message = "Не удалось восстановить запись ClipMic" }
        refresh(); startSync()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in Task { @MainActor in
            guard let self = self else { return }
            if let tape = self.tape { self.seconds = Double(tape.frames) / 16000 }
            else if let recorder = self.recorder { self.seconds = recorder.currentTime; self.updateInput() }
            self.refresh()
        } }
        NotificationCenter.default.addObserver(self, selector: #selector(routeChanged), name: AVAudioSession.routeChangeNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(interrupted), name: AVAudioSession.interruptionNotification, object: nil)
    }
    func refresh() {
        let current = files.recordings(); if current != recordings { recordings = current }
        let noteFiles = (try? FileManager.default.contentsOfDirectory(at: files.folder("notes"), includingPropertiesForKeys: nil)) ?? []
        let revision = noteFiles.sorted { $0.path < $1.path }.map { url -> String in let value = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]); return url.lastPathComponent + String(value?.contentModificationDate?.timeIntervalSince1970 ?? 0) + String(value?.fileSize ?? 0) }.joined(separator: "|")
        if revision != notesRevision { notesRevision = revision; notes = noteFiles.sorted { $0.lastPathComponent > $1.lastPathComponent }.compactMap { url in (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode(LectureNote.self, from: $0) } } }
        drafts = ((try? FileManager.default.contentsOfDirectory(at: files.folder("drafts"), includingPropertiesForKeys: nil)) ?? []).filter { $0.pathExtension == "caf" && $0.lastPathComponent != draft?.lastPathComponent }
    }
    func findBoard() {
        guard !findingBoard, !recording, !busy else { return }
        findingBoard = true; boards = []; boardStatus = "Ищу ClipMic рядом…"
        let connection = ClipMicBluetooth(known: nil)
        bluetooth = connection
        connection.onChoices = { [weak self] in self?.boards = $0 }
        connection.onPaired = { [weak self] id in
            self?.boardID = id
            UserDefaults.standard.set(id.uuidString, forKey: "clipmic.peripheral")
            self?.boardStatus = "ClipMic подключён"
        }
        connection.onEnd = { [weak self] reason in
            guard let self else { return }
            self.findingBoard = false; self.boards = []; self.bluetooth = nil
            if let reason { self.boardStatus = reason }
        }
        connection.begin()
    }

    func chooseBoard(_ id: UUID) {
        guard findingBoard else { return }
        boards = []; boardStatus = "Подтверди запрос Bluetooth на iPhone"
        bluetooth?.choose(id)
    }

    func cancelBoardSearch() {
        guard findingBoard else { return }
        bluetooth?.finish()
        boardStatus = ""
    }

    func forgetBoard() {
        guard !recording, !busy else { return }
        cancelBoardSearch()
        UserDefaults.standard.removeObject(forKey: "clipmic.peripheral")
        boardID = nil; boardStatus = ""
    }

    func startRecording() {
        guard !recording, !busy else { return }
        cancelBoardSearch(); cancelTranscription(); stopPlayback()
        let id = UUID()
        captureID = id; busy = true; seconds = 0
        guard let boardID, CBCentralManager.authorization == .allowedAlways else {
            startLocal(id)
            return
        }
        inputLabel = "Подключаю ClipMic…"; message = "Проверяю сохранённый диктофон"
        if AVAudioSession.sharedInstance().recordPermission == .granted {
            try? beginLocalRecorder()
        }
        let connection = ClipMicBluetooth(known: boardID)
        bluetooth = connection
        connection.onPacket = { [weak self] data, arrival in
            guard let self, self.captureID == id else { return }
            if self.tape == nil {
                let packet = try ClipMicPacket(data)
                guard packet.offset <= 160000, packet.sequence <= UInt32(packet.offset),
                      (packet.offset == 0) == (packet.sequence == 0) else {
                    throw RecorderFailure.message("Некорректное начало потока ClipMic")
                }
                if let active = self.recorder, active.currentTime > 10 {
                    throw RecorderFailure.message("ClipMic подключился слишком поздно")
                }
                let capture = try ClipMicTape(files: self.files)
                let localURL = self.draft
                if let active = self.recorder, let localURL {
                    let lag = max(0, ProcessInfo.processInfo.systemUptime - arrival)
                              + Double(packet.pcm.count / 2) / 16000
                    active.delegate = nil; active.stop()
                    self.recorder = nil; self.draft = nil
                    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
                    do {
                        let prefix = try ClipMicPrefix.read(localURL, trimmingTail: lag)
                        try capture.prependLocal(prefix, startedMs: self.localStarted, inputs: self.inputChanges, leadingMissing: packet.offset)
                    } catch {
                        self.message = "Начало записи доступно в черновиках"
                        self.refresh()
                        throw error
                    }
                }
                self.tape = capture
                try capture.append(data)
                if let localURL {
                    try? FileManager.default.removeItem(at: localURL)
                    try? FileManager.default.removeItem(at: localURL.appendingPathExtension("json"))
                }
                self.busy = false; self.recording = true; self.inputLabel = "ClipMic · Bluetooth"
                self.message = localURL == nil ? "Идёт запись с диктофона" : "Источник переключён на ClipMic"
            } else { try self.tape?.append(data) }
        }
        connection.onEnd = { [weak self] reason in
            guard let self, self.captureID == id else { return }
            self.bluetooth = nil
            let captured = self.tape
            self.tape = nil
            if captured == nil, self.recorder != nil {
                self.captureID = nil
                self.message = (reason ?? "ClipMic недоступен") + ". Идёт запись · " + self.inputLabel
                return
            }
            do { try captured?.finish(interruption: reason) } catch {
                self.captureID = nil; self.busy = false; self.recording = false
                self.inputLabel = "Автовыбор микрофона"; self.message = "Ошибка сохранения ClipMic: " + error.localizedDescription
                return
            }
            if let captured, captured.frames > 0 {
                self.seconds = Double(captured.frames) / 16000
                self.captureID = nil; self.busy = false; self.recording = false
                self.inputLabel = "Автовыбор микрофона"
                self.message = reason.map { $0 + ". Полученный звук сохранён" } ?? "Запись с ClipMic сохранена"
                self.refresh()
            } else {
                self.recording = false; self.busy = true
                self.startLocal(id, fallback: reason ?? "ClipMic недоступен")
            }
        }
        connection.begin()
    }

    func cancelStart() {
        guard starting else { return }
        captureID = nil; busy = false
        bluetooth?.finish(); bluetooth = nil
        inputLabel = "Автовыбор микрофона"; message = "Запись отменена"
    }

    private func chooseLocalInput(_ session: AVAudioSession) {
        let external = (session.availableInputs ?? []).filter {
            [.headsetMic, .bluetoothHFP, .bluetoothLE, .usbAudio, .lineIn].contains($0.portType)
        }
        let active = session.currentRoute.inputs.first
        let preferred = external.first { $0.uid == active?.uid } ?? external.first
        if session.preferredInput?.uid != preferred?.uid { try? session.setPreferredInput(preferred) }
    }

    private func startLocal(_ id: UUID, fallback: String? = nil) {
        inputLabel = "Включаю микрофон…"
        message = fallback.map { $0 + ". Включаю микрофон телефона или гарнитуры" } ?? "Включаю микрофон"
        AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in Task { @MainActor in
            guard let self, self.captureID == id else { return }
            self.captureID = nil; self.busy = false
            guard allowed else {
                self.inputLabel = "Автовыбор микрофона"; self.message = "Разреши микрофон в настройках iPhone"
                return
            }
            do {
                try self.beginLocalRecorder()
                if let fallback { self.message = fallback + ". Идёт запись · " + self.inputLabel }
            } catch {
                self.inputLabel = "Автовыбор микрофона"; self.message = error.localizedDescription
            }
        } }
    }

    private func beginLocalRecorder() throws {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
            chooseLocalInput(session)
            let url = files.folder("drafts").appendingPathComponent(UUID().uuidString + ".caf")
            let mic = try AVAudioRecorder(url: url, settings: [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000,
                  AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
            mic.delegate = self
            guard mic.record(forDuration: 8 * 3600) else { throw RecorderFailure.message("Не удалось включить микрофон") }
            recorder = mic; draft = url; recording = true; busy = false
            inputChanges = []; localStarted = Int64(Date().timeIntervalSince1970 * 1000)
            message = "Идёт запись"
            updateInput()
        } catch {
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            throw error
        }
    }

    @objc private func routeChanged(_ notification: Notification) {
        Task { @MainActor in
            guard self.recorder != nil else { return }
            if let value = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
               [.newDeviceAvailable, .oldDeviceUnavailable].contains(AVAudioSession.RouteChangeReason(rawValue: value)) {
                self.chooseLocalInput(.sharedInstance())
            }
            self.updateInput()
        }
    }

    private func updateInput() {
        guard let recorder, let draft else { return }
        let input = AVAudioSession.sharedInstance().currentRoute.inputs.first
        let name: String
        if let input {
            name = input.portType == .builtInMic ? "Микрофон телефона" : input.portName
        } else { name = "Аудиовход недоступен" }
        guard name != inputLabel || inputChanges.isEmpty else { return }
        if !inputChanges.isEmpty { message = "Источник звука изменился · " + name }
        inputLabel = name
        inputChanges.append(["at": inputChanges.isEmpty ? 0 : recorder.currentTime, "name": name,
                             "type": input?.portType.rawValue ?? "unavailable"])
        let meta: [String: Any] = ["started_ms": localStarted, "input_routes": inputChanges]
        do { try JSONSerialization.data(withJSONObject: meta).write(to: draft.appendingPathExtension("json"), options: .atomic) }
        catch { message = "Идёт запись · не удалось сохранить сведения о микрофоне" }
    }

    func stopRecording() {
        if tape != nil { bluetooth?.finish(); return }
        guard let url = draft else { return }
        captureID = nil; bluetooth?.finish(); bluetooth = nil
        draft = nil; let active = recorder; recorder = nil; active?.stop(); recording = false
        inputLabel = "Автовыбор микрофона"
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        importAudio(url, removeDraft: true)
    }

    @objc private func interrupted(_ notification: Notification) {
        if recorder != nil, let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
           type == AVAudioSession.InterruptionType.began.rawValue { stopRecording() }
    }
    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor in if self.recorder === recorder { self.stopRecording() } }
    }
    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        Task { @MainActor in if self.recorder === recorder { self.stopRecording() } }
    }

    func transcribe(_ url: URL) {
        guard !recording, !busy, recognitionTask == nil, !notes.contains(where: { $0.file == url.lastPathComponent }) else { return }
        let id = UUID()
        recognitionID = id; transcribingFile = url.lastPathComponent; transcriptionProgress = 0
        recognitionTask = Task { [self] in
            do {
                try await localTranscript.transcribe(url, files: files) { [weak self] progress in
                    if self?.recognitionID == id { self?.transcriptionProgress = Int(min(1, max(0, progress)) * 100) }
                }
                if recognitionID == id { message = "Расшифровка готова"; refresh() }
            } catch {
                if recognitionID == id { message = error.localizedDescription }
            }
            if recognitionID == id { recognitionID = nil; recognitionTask = nil; transcribingFile = nil }
        }
    }

    func cancelTranscription() {
        guard recognitionTask != nil else { return }
        recognitionID = nil; recognitionTask?.cancel(); recognitionTask = nil
        localTranscript.cancel(); transcribingFile = nil; message = "Расшифровка отменена"
    }

    func importAudio(_ source: URL, removeDraft: Bool = false) {
        guard !busy, !recording else { return }; busy = true; message = "Сохраняю запись…"
        let target = files.folder("recordings").appendingPathComponent(files.name()), temporary = files.folder("drafts").appendingPathComponent(UUID().uuidString + ".wav")
        Task {
            do {
                try await Task.detached(priority: .utility) {
                    let permitted = source.startAccessingSecurityScopedResource(); defer { if permitted { source.stopAccessingSecurityScopedResource() } }
                    let asset = AVURLAsset(url: source)
                    guard let track = try await asset.loadTracks(withMediaType: .audio).first else { throw RecorderFailure.message("В файле нет аудиодорожки") }
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
                    var meta: [String: Any] = ["source": "ios", "started_ms": Int64(Date().timeIntervalSince1970 * 1000), "imported": !removeDraft, "original_name": source.lastPathComponent, "gaps": []]
                    let draftMeta = source.appendingPathExtension("json")
                    if removeDraft, let data = try? Data(contentsOf: draftMeta),
                       let routes = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        for key in ["started_ms", "input_routes"] { meta[key] = routes[key] ?? meta[key] }
                    }
                    try JSONSerialization.data(withJSONObject: meta).write(to: target.appendingPathExtension("json"), options: .atomic)
                    try FileManager.default.moveItem(at: temporary, to: target)
                    if removeDraft { try? FileManager.default.removeItem(at: source); try? FileManager.default.removeItem(at: draftMeta) }
                }.value
                message = "Запись сохранена в библиотеке"
            } catch { try? FileManager.default.removeItem(at: temporary); message = error.localizedDescription }
            busy = false; refresh()
        }
    }
    func play(_ url: URL, at seconds: Double = 0) {
        guard !recording, !busy else { return }
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
