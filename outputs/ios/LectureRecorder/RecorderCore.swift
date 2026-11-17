import Foundation
import CryptoKit

enum RecorderFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
func fileSHA(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var digest = SHA256()
    while let data = try handle.read(upToCount: 65536), !data.isEmpty { digest.update(data: data) }
    return digest.finalize().map { String(format: "%02x", $0) }.joined()
}

func validRecording(_ name: String) -> Bool { name.range(of: "^lecture-[0-9-]+\\.wav$", options: .regularExpression) != nil }

final class PhoneFiles {
    let root: URL
    let lock = NSRecursiveLock()
    init(root: URL) throws {
        self.root = root
        for folder in ["recordings", "library", "notes", "drafts"] {
            try FileManager.default.createDirectory(at: root.appendingPathComponent(folder), withIntermediateDirectories: true)
        }
    }
    func folder(_ name: String) -> URL { root.appendingPathComponent(name, isDirectory: true) }
    func name() -> String {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Europe/Moscow"); formatter.dateFormat = "yyyy-MM-dd-HH-mm-ss"
        return "lecture-" + formatter.string(from: Date()) + "-" + String(Int.random(in: 100000...999999)) + ".wav"
    }
    func recordings() -> [URL] {
        lock.lock(); defer { lock.unlock() }
        let pending = (try? FileManager.default.contentsOfDirectory(at: folder("recordings"), includingPropertiesForKeys: nil)) ?? []
        let library = (try? FileManager.default.contentsOfDirectory(at: folder("library"), includingPropertiesForKeys: nil)) ?? []
        return (pending + library).filter { validRecording($0.lastPathComponent) }.sorted { $0.lastPathComponent > $1.lastPathComponent }
    }
    func localAudio(_ name: String) -> URL? {
        guard validRecording(name) else { return nil }
        for directory in ["library", "recordings"] {
            let path = folder(directory).appendingPathComponent(name)
            if FileManager.default.fileExists(atPath: path.path) { return path }
        }
        return nil
    }
    func list() throws -> [[String: Any]] {
        lock.lock(); defer { lock.unlock() }
        return try recordings().filter { $0.deletingLastPathComponent() == folder("recordings") }.map { url in
            var meta = (try? JSONSerialization.jsonObject(with: Data(contentsOf: url.appendingPathExtension("json")))) as? [String: Any] ?? [:]
            let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            meta["name"] = url.lastPathComponent; meta["bytes"] = size; meta["sha256"] = try fileSHA(url)
            meta["seconds"] = Double(max(0, size - 44)) / 32000; meta["source"] = "ios"
            return meta
        }
    }
    func acknowledge(_ name: String, digest: String) throws {
        lock.lock(); defer { lock.unlock() }
        guard validRecording(name) else { throw RecorderFailure.message("Некорректное имя записи") }
        let source = folder("recordings").appendingPathComponent(name), target = folder("library").appendingPathComponent(name)
        if !FileManager.default.fileExists(atPath: source.path) { return }
        guard try fileSHA(source) == digest else { throw RecorderFailure.message("Контрольная сумма записи отличается") }
        if FileManager.default.fileExists(atPath: target.path) {
            guard try fileSHA(target) == digest else { throw RecorderFailure.message("Другая запись с таким именем уже сохранена") }
            try FileManager.default.removeItem(at: source)
        } else { try FileManager.default.moveItem(at: source, to: target) }
    }
    func saveNote(_ data: Data) throws -> String {
        lock.lock(); defer { lock.unlock() }
        guard data.count <= 2 * 1024 * 1024,
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let name = value["file"] as? String, validRecording(name), value["report"] is [String: Any]
        else { throw RecorderFailure.message("Некорректная расшифровка") }
        try data.write(to: folder("notes").appendingPathComponent(name + ".json"), options: .atomic)
        return sha256(data)
    }
    func notesIndex() throws -> [String: String] {
        lock.lock(); defer { lock.unlock() }
        var index: [String: String] = [:]
        for path in try FileManager.default.contentsOfDirectory(at: folder("notes"), includingPropertiesForKeys: nil) {
            let name = path.deletingPathExtension().lastPathComponent
            if validRecording(name) { index[name] = try fileSHA(path) }
        }
        return index
    }
}

final class SyncAuth {
    private var used: [String: TimeInterval] = [:]
    func authorize(method: String, route: String, headers: [String: String], body: Data, key: String, now: TimeInterval = Date().timeIntervalSince1970) -> Bool {
        let stamp = headers["x-lecture-time"] ?? "", nonce = headers["x-lecture-nonce"] ?? ""
        guard !key.isEmpty, let time = Double(stamp), abs(now - time) <= 300,
              stamp.range(of: "^[0-9]{10,13}$", options: .regularExpression) != nil,
              nonce.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return false }
        used = used.filter { now - $0.value <= 300 }; guard used[nonce] == nil else { return false }
        let canonical = [method, route, stamp, nonce, headers["range"] ?? "", sha256(body)].joined(separator: "\n")
        guard let signature = headers["x-lecture-signature"], signature.count == 64 else { return false }
        let supplied = stride(from: 0, to: 64, by: 2).compactMap { offset -> UInt8? in
            let start = signature.index(signature.startIndex, offsetBy: offset), end = signature.index(start, offsetBy: 2)
            return UInt8(signature[start..<end], radix: 16)
        }
        guard supplied.count == 32, HMAC<SHA256>.isValidAuthenticationCode(supplied, authenticating: Data(canonical.utf8), using: SymmetricKey(data: Data(key.utf8))) else { return false }
        used[nonce] = now; return true
    }
}

final class WaveWriter {
    private let handle: FileHandle
    private var count: UInt32 = 0
    init(_ url: URL) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: Data(repeating: 0, count: 44)) else { throw RecorderFailure.message("Не удалось создать аудиофайл") }
        handle = try FileHandle(forWritingTo: url); try handle.seek(toOffset: 44)
    }
    func write(_ data: Data) throws {
        guard data.count % 2 == 0, UInt64(count) + UInt64(data.count) <= 8 * 3600 * 32000 else { throw RecorderFailure.message("Поддерживаются записи до 8 часов") }
        try handle.write(contentsOf: data); count += UInt32(data.count)
    }
    func finish() throws {
        var header = Data("RIFF".utf8)
        func number(_ value: UInt32, _ bytes: Int) { for i in 0..<bytes { header.append(UInt8((value >> (i * 8)) & 255)) } }
        number(count + 36, 4); header.append(Data("WAVEfmt ".utf8)); number(16, 4); number(1, 2); number(1, 2)
        number(16000, 4); number(32000, 4); number(2, 2); number(16, 2); header.append(Data("data".utf8)); number(count, 4)
        try handle.seek(toOffset: 0); try handle.write(contentsOf: header); try handle.synchronize(); try handle.close()
    }
    deinit { try? handle.close() }
}
