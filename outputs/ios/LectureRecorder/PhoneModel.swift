import Foundation
import AVFoundation
import Combine
import UIKit
import CoreBluetooth

@MainActor final class PhoneModel: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published var recordings: [URL] = []
    @Published var notes: [LectureNote] = []
    @Published private(set) var libraryItems: [LibraryItem] = []
    let listening = ListeningLibrary()
    private(set) lazy var playback = LecturePlayback(library: listening)
    @Published var drafts: [URL] = []
    @Published var recording = false
    @Published var busy = false
    @Published var seconds = 0.0
    @Published var message = ""
    @Published var captureNotice = ""
    @Published private(set) var savedFile: String?
    @Published private(set) var importingFile = false
    @Published private(set) var needsMicrophoneAccess = false
    @Published private(set) var macStatus = ""
    @Published var macName = "Mac не подключён"
    @Published var pairing = false
    @Published var verification = ""
    @Published private(set) var inputLabel = ""
    private var deviceName: String { UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone" }
    var savedItem: LibraryItem? { savedFile.flatMap { id in libraryItems.first { $0.id == id } } }
    var sourceLabel: String {
        if recording || busy { return inputLabel }
        if boardID != nil && CBCentralManager.authorization == .allowedAlways { return "ClipMic, если рядом" }
        let session = AVAudioSession.sharedInstance()
        if let input = preferredExternalInput(session) ?? session.currentRoute.inputs.first { return name(of: input) }
        if let output = session.currentRoute.outputs.first, [.builtInSpeaker, .builtInReceiver].contains(output.portType) {
            return "Микрофон " + deviceName
        }
        return deviceName + " или гарнитура"
    }

    func meterLevel() -> Double {
        if let tape { return tape.meterLevel }
        guard let recorder else { return 0 }
        recorder.updateMeters()
        return max(0, min(1, (Double(recorder.peakPower(forChannel: 0)) + 60) / 60))
    }
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
    private var sync: PhoneSyncServer?
    private var timer: Timer?
    private var pairingTask: Task<Void, Never>?
    private var noteVersions: [URL: String] = [:]
    private var documents: [URL: LectureNote] = [:]

    override convenience init() {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Lectures", isDirectory: true)
        do { self.init(files: try PhoneFiles(root: root)) }
        catch { fatalError("Не удалось открыть хранилище приложения") }
        startSync()
    }

    init(files: PhoneFiles) {
        self.files = files
        super.init()
        do { try ClipMicTape.recover(in: files) } catch { captureNotice = "Не удалось восстановить запись ClipMic" }
        refresh()
        let tick = Timer(timeInterval: 1, repeats: true) { [weak self] _ in Task { @MainActor in
            guard let self = self else { return }
            if let tape = self.tape { self.seconds = Double(tape.frames) / 16000 }
            else if let recorder = self.recorder { self.seconds = recorder.currentTime; self.updateInput() }
            self.playback.tick()
            self.refresh()
        } }
        timer = tick
        RunLoop.main.add(tick, forMode: .common)
        NotificationCenter.default.addObserver(self, selector: #selector(routeChanged), name: AVAudioSession.routeChangeNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(interrupted), name: AVAudioSession.interruptionNotification, object: nil)
    }
    func applicationDidBecomeActive() {
        if needsMicrophoneAccess && AVAudioSession.sharedInstance().recordPermission == .granted {
            needsMicrophoneAccess = false
            captureNotice = ""
        }
        refresh()
    }

    func refresh() {
        let current = files.recordings()
        let audioChanged = current != recordings
        if audioChanged { recordings = current }
        var changedNotes = Set<String>()
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey]
        if let noteFiles = try? FileManager.default.contentsOfDirectory(at: files.folder("notes"), includingPropertiesForKeys: Array(keys)) {
            let present = Set(noteFiles)
            for path in Set(noteVersions.keys).subtracting(present) {
                if let removed = documents.removeValue(forKey: path) { changedNotes.insert(removed.file) }
                noteVersions.removeValue(forKey: path)
            }
            for path in noteFiles where path.pathExtension == "json" {
                guard let values = try? path.resourceValues(forKeys: keys) else { continue }
                let stamp = String(values.contentModificationDate?.timeIntervalSince1970 ?? 0) + "|" + String(values.fileSize ?? 0)
                guard noteVersions[path] != stamp, let data = try? Data(contentsOf: path) else { continue }
                noteVersions[path] = stamp
                if let previous = documents[path] { changedNotes.insert(previous.file) }
                documents[path] = try? JSONDecoder().decode(LectureNote.self, from: data)
                if let updated = documents[path] { changedNotes.insert(updated.file) }
            }
        }
        if !changedNotes.isEmpty { notes = documents.values.sorted { $0.file > $1.file } }
        if audioChanged || !changedNotes.isEmpty {
            libraryItems = LibraryItem.list(current, notes: notes, previous: libraryItems, changedNotes: changedNotes) { [files] name in
                for directory in ["library", "recordings"] {
                    let meta = files.folder(directory).appendingPathComponent(name + ".json")
                    if let data = try? Data(contentsOf: meta),
                       let values = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       values["imported"] as? Bool != false, let original = values["original_name"] as? String {
                        return original
                    }
                }
                return nil
            }
        }
        let nextDrafts = ((try? FileManager.default.contentsOfDirectory(at: files.folder("drafts"), includingPropertiesForKeys: nil)) ?? []).filter { $0.pathExtension == "caf" && $0.lastPathComponent != draft?.lastPathComponent }
        if drafts != nextDrafts { drafts = nextDrafts }
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
        savedFile = nil; captureNotice = ""; needsMicrophoneAccess = false
        guard let boardID, CBCentralManager.authorization == .allowedAlways else {
            startLocal(id)
            return
        }
        inputLabel = "Подключаем ClipMic…"
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
                        self.captureNotice = "Начало записи доступно в черновиках библиотеки"
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
                self.captureNotice = ""
            } else { try self.tape?.append(data) }
        }
        connection.onEnd = { [weak self] reason in
            guard let self, self.captureID == id else { return }
            self.bluetooth = nil
            let captured = self.tape
            self.tape = nil
            if captured == nil, self.recorder != nil {
                self.captureID = nil
                self.captureNotice = (reason ?? "ClipMic недоступен") + ". Продолжаем с другого микрофона."
                return
            }
            do { try captured?.finish(interruption: reason) } catch {
                self.captureID = nil; self.busy = false; self.recording = false
                self.inputLabel = ""; self.captureNotice = "Не удалось сохранить запись ClipMic. " + error.localizedDescription
                return
            }
            if let captured, captured.frames > 0 {
                self.seconds = Double(captured.frames) / 16000
                self.captureID = nil; self.busy = false; self.recording = false
                self.inputLabel = ""
                self.captureNotice = reason.map { $0 + ". Полученный звук сохранён." } ?? ""
                self.didSave(captured.recordingName)
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
        inputLabel = ""; captureNotice = ""
    }

    private func preferredExternalInput(_ session: AVAudioSession) -> AVAudioSessionPortDescription? {
        let external = (session.availableInputs ?? []).filter {
            [.headsetMic, .bluetoothHFP, .bluetoothLE, .usbAudio, .lineIn].contains($0.portType)
        }
        let active = session.currentRoute.inputs.first
        return external.first { $0.uid == active?.uid } ?? external.first
    }

    private func chooseLocalInput(_ session: AVAudioSession) {
        let preferred = preferredExternalInput(session)
        if session.preferredInput?.uid != preferred?.uid { try? session.setPreferredInput(preferred) }
    }

    private func startLocal(_ id: UUID, fallback: String? = nil) {
        inputLabel = deviceName + " или гарнитура"
        captureNotice = fallback ?? ""
        AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in Task { @MainActor in
            guard let self, self.captureID == id else { return }
            self.captureID = nil; self.busy = false
            guard allowed else {
                self.inputLabel = ""; self.needsMicrophoneAccess = true
                self.captureNotice = "Разреши доступ к микрофону, чтобы начать запись."
                return
            }
            do {
                try self.beginLocalRecorder()
            } catch {
                self.inputLabel = ""; self.captureNotice = error.localizedDescription
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
            mic.isMeteringEnabled = true
            guard mic.record(forDuration: 8 * 3600) else { throw RecorderFailure.message("Не удалось включить микрофон") }
            recorder = mic; draft = url; recording = true; busy = false
            inputChanges = []; localStarted = Int64(Date().timeIntervalSince1970 * 1000)
            updateInput()
        } catch {
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            throw error
        }
    }

    @objc private func routeChanged(_ notification: Notification) {
        Task { @MainActor in
            guard self.recorder != nil else {
                if !self.recording && !self.busy { self.objectWillChange.send() }
                return
            }
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
        let name = input.map(name(of:)) ?? "Аудиовход недоступен"
        guard name != inputLabel || inputChanges.isEmpty else { return }
        inputLabel = name
        inputChanges.append(["at": inputChanges.isEmpty ? 0 : recorder.currentTime, "name": name,
                             "type": input?.portType.rawValue ?? "unavailable"])
        let meta: [String: Any] = ["started_ms": localStarted, "input_routes": inputChanges]
        do { try JSONSerialization.data(withJSONObject: meta).write(to: draft.appendingPathExtension("json"), options: .atomic) }
        catch { captureNotice = "Идёт запись. Не удалось сохранить сведения о микрофоне." }
    }

    private func name(of port: AVAudioSessionPortDescription) -> String {
        port.portType == .builtInMic ? "Микрофон " + deviceName : port.portName
    }

    func stopRecording() {
        if tape != nil { bluetooth?.finish(); return }
        guard let url = draft else { return }
        captureID = nil; bluetooth?.finish(); bluetooth = nil
        draft = nil; let active = recorder; recorder = nil
        if let active { seconds = max(seconds, active.currentTime); active.stop() }
        recording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        importAudio(url, removeDraft: true, microphone: inputLabel)
    }

    @objc private func interrupted(_ notification: Notification) {
        guard let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              type == AVAudioSession.InterruptionType.began.rawValue else { return }
        if recorder != nil { stopRecording() }
        playback.pause()
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

    func importAudio(_ source: URL, removeDraft: Bool = false, microphone: String? = nil) {
        guard !busy, !recording else { return }
        busy = true; savedFile = nil; captureNotice = ""; needsMicrophoneAccess = false
        importingFile = !removeDraft
        inputLabel = microphone ?? (removeDraft ? "Черновик записи" : source.lastPathComponent)
        if microphone == nil { seconds = 0 }
        Task {
            do {
                let file = try await RecordingImport.save(source, in: files, recoveringDraft: removeDraft)
                didSave(file)
            } catch {
                captureNotice = removeDraft
                    ? "Не удалось сохранить запись. Черновик доступен в библиотеке. " + error.localizedDescription
                    : "Не удалось импортировать файл. " + error.localizedDescription
                refresh()
            }
            busy = false; importingFile = false; inputLabel = ""
        }
    }

    private func didSave(_ file: String) {
        refresh()
        savedFile = file
    }

    func selectImport(_ result: Result<URL, Error>) {
        switch result {
        case .success(let file):
            importAudio(file)
        case .failure(let error):
            guard (error as NSError).code != NSUserCancelledError else { return }
            savedFile = nil
            captureNotice = "Не удалось выбрать файл. " + error.localizedDescription
        }
    }

    func play(_ url: URL, at seconds: Double? = nil) {
        guard !recording, !busy else { return }
        let source = files.localAudio(url.lastPathComponent) ?? url
        do { try playback.play(source, at: seconds) }
        catch { message = "Не удалось воспроизвести запись" }
    }
    func stopPlayback() { playback.stop() }
    func startSync() {
        guard let mac = SavedMac.load() else { return }
        macName = mac.name
        sync?.stop(); sync = PhoneSyncServer(files: files, key: mac.token)
        do { try sync?.start() } catch { macStatus = "Не удалось включить перенос. Закрой и открой приложение." }
    }
    func disconnect() { guard !recording else { return }; pairingTask?.cancel(); sync?.stop(); sync = nil; SavedMac.forget(); macName = "Mac не подключён" }
    func connect(host: String, code: String) {
        guard !recording, !pairing else { return }
        let host = host.trimmingCharacters(in: .whitespacesAndNewlines), code = code.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        guard host.range(of: "^[A-Za-z0-9.-]{1,253}$", options: .regularExpression) != nil, code.range(of: "^[A-Z2-7]{12}$", options: .regularExpression) != nil else { macStatus = "Введи адрес Mac и 12 символов его кода"; return }
        pairing = true; verification = ""; macStatus = "Подключаюсь к Mac…"
        pairingTask = Task {
            defer { pairing = false }
            do {
                let client = PinnedMac(host: host, code: code)
                let request = try await client.post("/pair/request", ["name": "iPhone / iPad", "device_id": UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(), "nonce": UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()])
                guard let id = request["request_id"] as? String else { throw RecorderFailure.message("Запрос не создан") }
                verification = request["verification"] as? String ?? ""; macStatus = "Сравни цифры с Mac и подтверди подключение на компьютере"
                for _ in 0..<300 {
                    try Task.checkCancellation()
                    let reply = try await client.post("/pair/status", ["request_id": id])
                    if ["approved", "complete"].contains(reply["status"] as? String ?? ""), let token = reply["sync_token"] as? String, token.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil {
                        try Task.checkCancellation(); try SavedMac(host: host, name: reply["mac_name"] as? String ?? "Mac", token: token).save()
                        _ = try? await client.post("/pair/ack", ["request_id": id]); startSync(); verification = ""; macStatus = "Mac подключён · записи и тексты переносятся автоматически"; return
                    }
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                }
                throw RecorderFailure.message("Код истёк. Открой подключение на Mac заново")
            } catch is CancellationError { macStatus = "Подключение отменено" }
            catch { macStatus = "Не удалось подключиться. Проверь код, дату и общую Wi-Fi сеть. " + error.localizedDescription }
        }
    }
    func cancelPairing() { pairingTask?.cancel(); pairing = false; verification = "" }
}
