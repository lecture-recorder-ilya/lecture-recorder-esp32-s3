import AVFoundation
import Foundation
import Speech

struct OfflineSpeechWindow {
    let start: Double
    let duration: Double
    let buffer: AVAudioPCMBuffer

    static func read(from file: AVAudioFile) throws -> OfflineSpeechWindow {
        let rate = file.processingFormat.sampleRate
        let start = file.framePosition
        let remaining = file.length - start
        guard remaining > 0, rate > 0 else { throw RecorderFailure.message("Аудиозапись пуста") }
        let frames = AVAudioFrameCount(min(remaining, Int64(rate * 50)))
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames)
        else { throw RecorderFailure.message("Не удалось прочитать запись") }
        try file.read(into: buffer, frameCount: frames)
        while buffer.frameLength < frames {
            let filled = Int(buffer.frameLength)
            let missing = frames - buffer.frameLength
            guard let tail = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: missing)
            else { throw RecorderFailure.message("Не удалось прочитать конец фрагмента") }
            try file.read(into: tail, frameCount: missing)
            guard tail.frameLength > 0, let target = buffer.floatChannelData, let source = tail.floatChannelData
            else { throw RecorderFailure.message("Запись оборвалась при чтении") }
            for channel in 0..<Int(file.processingFormat.channelCount) {
                target[channel].advanced(by: filled).update(from: source[channel], count: Int(tail.frameLength))
            }
            buffer.frameLength += tail.frameLength
        }
        guard buffer.frameLength > 0, let samples = buffer.floatChannelData?[0]
        else { throw RecorderFailure.message("Не удалось прочитать фрагмент записи") }

        if remaining > Int64(frames) {
            let step = max(1, Int(rate * 0.04))
            let end = Int(buffer.frameLength)
            let begin = max(0, end - Int(rate * 3))
            var lowest = Float.infinity
            var cut = end
            for offset in stride(from: end - step, through: begin, by: -step) {
                var energy: Float = 0
                for i in offset..<(offset + step) { energy += samples[i] * samples[i] }
                if energy < lowest {
                    lowest = energy
                    cut = offset + step / 2
                }
            }
            if cut > 0 {
                buffer.frameLength = AVAudioFrameCount(cut)
                file.framePosition = start + Int64(cut)
            }
        }
        return OfflineSpeechWindow(start: Double(start) / rate,
                                   duration: Double(buffer.frameLength) / rate, buffer: buffer)
    }

    var silent: Bool {
        guard let samples = buffer.floatChannelData?[0] else { return false }
        return !UnsafeBufferPointer(start: samples, count: Int(buffer.frameLength)).contains { $0 != 0 }
    }
}

struct OfflineSpeechWord {
    let text: String
    let start: Double
    let duration: Double
    let confidence: Float

    static func phrases(_ words: [OfflineSpeechWord], offset: Double, length: Double) -> [[String: Any]] {
        var rows: [[String: Any]] = []
        var text = ""
        var times: [[Int]] = []
        var start = 0.0, end = 0.0
        var uncertain = false
        func flush() {
            guard !times.isEmpty else { return }
            rows.append(["start": start, "end": end, "text": text, "needs_review": uncertain, "word_times": times])
            times = []; text = ""; uncertain = false
        }
        for word in words {
            let token = word.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !token.isEmpty, word.start.isFinite, word.duration.isFinite else { continue }
            let from = offset + min(length, max(0, word.start))
            let to = offset + min(length, max(0, word.start + max(0, word.duration)))
            if !times.isEmpty && (from - end >= 0.65 || to - start > 8 || times.count >= 22) { flush() }
            if times.isEmpty { start = from } else { text += " " }
            let first = text.utf16.count
            text += token
            times.append([first, text.utf16.count, Int((from * 1000).rounded())])
            end = max(from, to)
            uncertain = uncertain || word.confidence < 0.55
            if let last = token.last, ".?!…".contains(last) { flush() }
        }
        flush()
        return rows
    }
}

@MainActor final class OnDeviceTranscript {
    private static let language = Locale(identifier: "ru-RU")
    private var runID: UUID?
    private var cancelled = false
    private var activeTask: SFSpeechRecognitionTask?
    private var windowID: UUID?
    private var continuation: CheckedContinuation<[OfflineSpeechWord], Error>?
    private var timeout: Task<Void, Never>?

    static var supported: Bool {
        SFSpeechRecognizer(locale: language)?.supportsOnDeviceRecognition == true
    }

    func cancel() {
        guard runID != nil else { return }
        cancelled = true
        if let window = windowID { finish(window, .failure(CancellationError())) }
    }

    func transcribe(_ audio: URL, files: PhoneFiles, progress: @escaping (Double) -> Void) async throws {
        let name = audio.lastPathComponent
        guard runID == nil else { throw RecorderFailure.message("Уже идёт расшифровка") }
        guard validRecording(name), files.localAudio(name) != nil
        else { throw RecorderFailure.message("Запись отсутствует в библиотеке") }
        let target = files.folder("notes").appendingPathComponent(name + ".json")
        guard !FileManager.default.fileExists(atPath: target.path) else { return }
        guard let recognizer = SFSpeechRecognizer(locale: Self.language), recognizer.supportsOnDeviceRecognition
        else { throw RecorderFailure.message("На этом iPhone недоступна русская модель для офлайн-расшифровки") }
        let id = UUID()
        runID = id
        cancelled = false
        defer { runID = nil }
        try await withTaskCancellationHandler {
            let status: SFSpeechRecognizerAuthorizationStatus
            if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
                status = await withCheckedContinuation { answer in
                    SFSpeechRecognizer.requestAuthorization { answer.resume(returning: $0) }
                }
            } else { status = SFSpeechRecognizer.authorizationStatus() }
            try checkCancellation()
            guard status == .authorized else { throw RecorderFailure.message("Разреши распознавание речи в настройках iPhone") }
            let file = try Self.openAudio(name, files: files)
            guard file.length > 0 else { throw RecorderFailure.message("Запись пуста") }
            var rows: [[String: Any]] = []
            progress(0)
            while file.framePosition < file.length {
                try checkCancellation()
                let window = try OfflineSpeechWindow.read(from: file)
                if !window.silent {
                    let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".caf")
                    defer { try? FileManager.default.removeItem(at: temporary) }
                    do {
                        let track = try AVAudioFile(forWriting: temporary, settings: window.buffer.format.settings)
                        try track.write(from: window.buffer)
                    }
                    let words = try await recognize(temporary, with: recognizer)
                    rows += OfflineSpeechWord.phrases(words, offset: window.start, length: window.duration)
                }
                progress(Double(file.framePosition) / Double(file.length))
                await Task.yield()
            }
            try checkCancellation()
            guard !rows.isEmpty else { throw RecorderFailure.message("В записи не удалось разобрать речь") }
            let report = OfflineNoteSelection.report(rows)
            let data = try JSONSerialization.data(withJSONObject: ["file": name, "report": report])
            try Self.saveNew(data, at: target, files: files)
        } onCancel: { [weak self] in
            Task { @MainActor in if self?.runID == id { self?.cancel() } }
        }
    }

    private static func openAudio(_ name: String, files: PhoneFiles) throws -> AVAudioFile {
        files.lock.lock()
        defer { files.lock.unlock() }
        guard let url = files.localAudio(name) else { throw RecorderFailure.message("Запись отсутствует в библиотеке") }
        return try AVAudioFile(forReading: url, commonFormat: .pcmFormatFloat32, interleaved: false)
    }

    static func saveNew(_ data: Data, at url: URL, files: PhoneFiles) throws {
        files.lock.lock()
        defer { files.lock.unlock() }
        guard !FileManager.default.fileExists(atPath: url.path) else { return }
        try data.write(to: url, options: .atomic)
    }

    private func checkCancellation() throws {
        if cancelled || Task.isCancelled { throw CancellationError() }
    }

    private func recognize(_ url: URL, with recognizer: SFSpeechRecognizer) async throws -> [OfflineSpeechWord] {
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        request.taskHint = .dictation
        request.addsPunctuation = true
        let id = UUID()
        return try await withCheckedThrowingContinuation { answer in
            continuation = answer
            windowID = id
            activeTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                if let result = result, result.isFinal {
                    let words = result.bestTranscription.segments.map {
                        OfflineSpeechWord(text: $0.substring, start: $0.timestamp, duration: $0.duration, confidence: $0.confidence)
                    }
                    Task { @MainActor in self?.finish(id, .success(words)) }
                } else if let error = error as NSError? {
                    let outcome: Result<[OfflineSpeechWord], Error>
                    if error.domain == "kAFAssistantErrorDomain" && error.code == 1110 {
                        outcome = .success([])
                    } else {
                        outcome = .failure(RecorderFailure.message("Офлайн-распознавание прервалось. " + error.localizedDescription))
                    }
                    Task { @MainActor in self?.finish(id, outcome) }
                }
            }
            timeout = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 180_000_000_000) } catch { return }
                self?.finish(id, .failure(RecorderFailure.message("iPhone не успел разобрать фрагмент. Можно повторить попытку.")))
            }
        }
    }

    private func finish(_ id: UUID, _ result: Result<[OfflineSpeechWord], Error>) {
        guard windowID == id, let answer = continuation else { return }
        windowID = nil
        continuation = nil
        timeout?.cancel(); timeout = nil
        if case .failure = result { activeTask?.cancel() }
        activeTask = nil
        answer.resume(with: result)
    }
}
