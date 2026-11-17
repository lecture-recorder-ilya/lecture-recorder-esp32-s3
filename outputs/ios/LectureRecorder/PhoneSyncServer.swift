import Foundation
import Network
import CryptoKit

final class PhoneSyncServer {
    private var listener: NWListener?
    private var discovery: NWListener?
    private let queue = DispatchQueue(label: "ru.ilya.lecturerecorder.sync")
    private let files: PhoneFiles
    private let key: String
    private let auth = SyncAuth()
    private var clients: [ObjectIdentifier: NWConnection] = [:]
    private let port: UInt16
    private let discoveryPort: UInt16
    var onReady: ((UInt16) -> Void)?
    init(files: PhoneFiles, key: String, port: UInt16 = 8780, discoveryPort: UInt16 = 8783) { self.files = files; self.key = key; self.port = port; self.discoveryPort = discoveryPort }
    func start() throws {
        guard listener == nil, !key.isEmpty else { return }
        let server = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: port)!)
        server.newConnectionHandler = { [weak self] connection in self?.accept(connection) }
        server.stateUpdateHandler = { [weak self, weak server] state in if case .ready = state, let port = server?.port?.rawValue { self?.onReady?(port) } }
        server.start(queue: queue); listener = server
        let udp = try NWListener(using: .udp, on: NWEndpoint.Port(rawValue: discoveryPort)!)
        udp.newConnectionHandler = { [weak self] connection in
            guard let self = self else { connection.cancel(); return }
            connection.start(queue: self.queue)
            connection.receiveMessage { data, _, _, _ in
                guard let data = data, let query = String(data: data, encoding: .utf8), query.range(of: "^LECTURES1 [a-f0-9]{32}$", options: .regularExpression) != nil else { connection.cancel(); return }
                let nonce = String(query.dropFirst(10)), canonical = "DISCOVER\n" + String(query.dropFirst(10)) + "\n8780"
                let hash = HMAC<SHA256>.authenticationCode(for: Data(canonical.utf8), using: SymmetricKey(data: Data(self.key.utf8))).map { String(format: "%02x", $0) }.joined()
                connection.send(content: Data("LECTURES1 \(nonce) 8780 \(hash)".utf8), completion: .contentProcessed { _ in connection.cancel() })
            }
        }
        udp.start(queue: queue); discovery = udp
    }
    func stop() {
        queue.async { self.listener?.cancel(); self.discovery?.cancel(); self.listener = nil; self.discovery = nil; for connection in self.clients.values { connection.cancel() }; self.clients.removeAll() }
    }
    private func accept(_ connection: NWConnection) {
        guard clients.count < 12 else { connection.cancel(); return }
        let id = ObjectIdentifier(connection); clients[id] = connection
        connection.stateUpdateHandler = { [weak self] state in if case .cancelled = state { self?.clients.removeValue(forKey: id) } }
        connection.start(queue: queue)
        let timeout = DispatchWorkItem { connection.cancel() }; queue.asyncAfter(deadline: .now() + 30, execute: timeout)
        receive(connection, data: Data(), timeout: timeout)
    }
    private func receive(_ connection: NWConnection, data: Data, timeout: DispatchWorkItem) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] chunk, _, complete, error in
            guard let self = self, error == nil else { connection.cancel(); return }
            var accumulated = data; accumulated.append(chunk ?? Data())
            guard accumulated.count <= 2 * 1024 * 1024 + 16384 else { self.reply(connection, 413, [:]); return }
            if let split = accumulated.range(of: Data("\r\n\r\n".utf8)) {
                guard split.lowerBound <= 16384, let header = String(data: accumulated[..<split.lowerBound], encoding: .utf8) else { self.reply(connection, 400, [:]); return }
                let lines = header.components(separatedBy: "\r\n"), first = lines[0].components(separatedBy: " ")
                guard first.count == 3, ["GET", "POST"].contains(first[0]), first[1].hasPrefix("/") else { self.reply(connection, 400, [:]); return }
                var headers: [String: String] = [:]
                for line in lines.dropFirst() {
                    guard let colon = line.firstIndex(of: ":") else { self.reply(connection, 400, [:]); return }
                    let name = line[..<colon].lowercased()
                    guard headers[name] == nil else { self.reply(connection, 400, [:]); return }
                    headers[name] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
                }
                let limit = first[1] == "/notes" ? 2 * 1024 * 1024 : 2048
                guard headers["transfer-encoding"] == nil, let length = Int(headers["content-length"] ?? "0"), length >= 0, length <= limit else { self.reply(connection, 413, [:]); return }
                let body = Data(accumulated[split.upperBound...])
                if body.count < length && !complete { self.receive(connection, data: accumulated, timeout: timeout); return }
                guard body.count == length else { self.reply(connection, 400, [:]); return }
                timeout.cancel()
                guard self.auth.authorize(method: first[0], route: first[1], headers: headers, body: body, key: self.key) else { self.reply(connection, 403, [:]); return }
                self.handle(connection, method: first[0], route: first[1], headers: headers, body: body); return
            }
            guard accumulated.count <= 16384, !complete else { self.reply(connection, 400, [:]); return }
            self.receive(connection, data: accumulated, timeout: timeout)
        }
    }
    private func handle(_ connection: NWConnection, method: String, route: String, headers: [String: String], body: Data) {
        do {
            if method == "GET" && route == "/list" { reply(connection, 200, try files.list()); return }
            if method == "GET" && route == "/notes-index" { reply(connection, 200, try files.notesIndex()); return }
            if method == "POST" && route == "/notes" { reply(connection, 200, ["ok": true, "sha256": try files.saveNote(body)]); return }
            if method == "POST" && route == "/ack" {
                guard let value = try JSONSerialization.jsonObject(with: body) as? [String: String], let name = value["name"], let digest = value["sha256"] else { reply(connection, 400, [:]); return }
                try files.acknowledge(name, digest: digest); reply(connection, 200, ["ok": true]); return
            }
            if method == "GET" && route.hasPrefix("/file/") {
                let name = String(route.dropFirst(6)); guard validRecording(name) else { reply(connection, 400, [:]); return }
                let url = files.folder("recordings").appendingPathComponent(name)
                let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                var offset = 0
                if let range = headers["range"] {
                    guard range.range(of: "^bytes=[0-9]+-$", options: .regularExpression) != nil, let value = Int(range.dropFirst(6).dropLast()), value < size else { reply(connection, 416, [:]); return }
                    offset = value
                }
                let source = try FileHandle(forReadingFrom: url); try source.seek(toOffset: UInt64(offset))
                let status = headers["range"] == nil ? 200 : 206
                let contentRange = status == 206 ? "Content-Range: bytes \(offset)-\(size-1)/\(size)\r\n" : ""
                let header = Data("HTTP/1.1 \(status) Response\r\nContent-Type: audio/wav\r\nContent-Length: \(size-offset)\r\nAccept-Ranges: bytes\r\n\(contentRange)Connection: close\r\n\r\n".utf8)
                connection.send(content: header, completion: .contentProcessed { error in if error != nil { try? source.close(); connection.cancel() } else { self.stream(source, connection: connection) } }); return
            }
            reply(connection, 404, [:])
        } catch { reply(connection, 422, ["error": "Не удалось сохранить или передать файл. Оригинал остаётся на телефоне."]) }
    }
    private func stream(_ file: FileHandle, connection: NWConnection) {
        do {
            guard let data = try file.read(upToCount: 65536), !data.isEmpty else { try? file.close(); connection.cancel(); return }
            connection.send(content: data, completion: .contentProcessed { error in if error != nil { try? file.close(); connection.cancel() } else { self.stream(file, connection: connection) } })
        } catch { try? file.close(); connection.cancel() }
    }
    private func reply(_ connection: NWConnection, _ status: Int, _ value: Any) {
        let data = (try? JSONSerialization.data(withJSONObject: value)) ?? Data("{}".utf8)
        var response = Data("HTTP/1.1 \(status) Response\r\nContent-Type: application/json\r\nContent-Length: \(data.count)\r\nConnection: close\r\n\r\n".utf8); response.append(data)
        connection.send(content: response, completion: .contentProcessed { _ in connection.cancel() })
    }
}
