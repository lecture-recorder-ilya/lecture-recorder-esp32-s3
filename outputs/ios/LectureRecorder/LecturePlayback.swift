import AVFoundation
import Combine
import Foundation

@MainActor final class LecturePlayback: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var file: String?
    @Published private(set) var elapsed = 0.0
    @Published private(set) var duration = 0.0
    @Published private(set) var playing = false
    private let library: ListeningLibrary
    private var audio: AVAudioPlayer?
    private var lastSaved = 0.0

    init(library: ListeningLibrary) { self.library = library }

    func position(for id: String) -> Double {
        if id == file { return audio?.currentTime ?? elapsed }
        return library.position(id)
    }

    func play(_ url: URL, at target: Double? = nil) throws {
        let id = url.lastPathComponent
        if id != file || audio == nil {
            stop()
            let next = try AVAudioPlayer(contentsOf: url)
            guard next.duration.isFinite, next.duration > 0 else { throw RecorderFailure.message("В записи нет звука") }
            next.delegate = self
            next.enableRate = true
            audio = next; file = id; duration = next.duration
            elapsed = min(library.position(id), duration)
            next.currentTime = elapsed < duration ? elapsed : 0
        }
        guard let audio else { return }
        if let target, target.isFinite { audio.currentTime = min(duration, max(0, target)) }
        if audio.currentTime >= duration { audio.currentTime = 0 }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback)
            try AVAudioSession.sharedInstance().setActive(true)
            audio.rate = library.rate
            guard audio.play() else { throw RecorderFailure.message("Не удалось начать воспроизведение") }
            playing = true; elapsed = audio.currentTime
            checkpoint()
        } catch { stop(); throw error }
    }

    func seek(_ id: String, to time: Double, duration length: Double) {
        guard time.isFinite, length.isFinite, length > 0 else { return }
        let position = min(length, max(0, time))
        if id == file { audio?.currentTime = position; elapsed = position }
        library.savePosition(position, for: id)
    }

    func setRate(_ value: Float) {
        library.setRate(value)
        audio?.rate = library.rate
    }

    func tick() {
        guard playing, let audio else { return }
        elapsed = audio.currentTime
        if ProcessInfo.processInfo.systemUptime - lastSaved >= 5 { checkpoint() }
    }

    func checkpoint() {
        if let file, let audio { library.savePosition(audio.currentTime, for: file) }
        lastSaved = ProcessInfo.processInfo.systemUptime
    }

    func pause() {
        guard let audio, playing else { return }
        audio.pause()
        playing = false; elapsed = audio.currentTime; checkpoint()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func stop() {
        guard let audio else { return }
        checkpoint()
        audio.delegate = nil; audio.stop()
        self.audio = nil; file = nil; elapsed = 0; duration = 0; playing = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            guard player === self.audio, let id = self.file else { return }
            self.stop()
            if flag { self.library.savePosition(0, for: id) }
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in if player === self.audio { self.stop() } }
    }
}
