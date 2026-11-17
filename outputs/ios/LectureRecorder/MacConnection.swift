import Foundation
import Security
import CryptoKit

struct SavedMac: Codable {
    let host: String
    let name: String
    let token: String
    static let service = "ru.ilya.lecturerecorder.ios.mac"
    static func load() -> SavedMac? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "mac", kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(SavedMac.self, from: data)
    }
    func save() throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: Self.service, kSecAttrAccount as String: "mac"]
        let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(self), kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else { throw RecorderFailure.message("Не удалось сохранить подключение") }
        } else if status != errSecSuccess { throw RecorderFailure.message("Не удалось сохранить подключение") }
    }
    static func forget() { SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "mac"] as CFDictionary) }
}

func certificateCode(_ der: Data) -> String {
    let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    var bits: UInt32 = 0, count = 0, result = ""
    for byte in SHA256.hash(data: der) {
        bits = (bits << 8) | UInt32(byte); count += 8
        while count >= 5 { count -= 5; result.append(alphabet[Int((bits >> count) & 31)]); if result.count == 12 { return result } }
    }
    return result
}

final class PinnedMac: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    let host: String
    let code: String
    init(host: String, code: String) { self.host = host; self.code = code }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              challenge.protectionSpace.host == host, let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let certificate = chain.first,
              certificateCode(SecCertificateCopyData(certificate) as Data) == code else { completionHandler(.cancelAuthenticationChallenge, nil); return }
        SecTrustSetPolicies(trust, SecPolicyCreateBasicX509()); SecTrustSetAnchorCertificates(trust, [certificate] as CFArray); SecTrustSetAnchorCertificatesOnly(trust, true)
        guard SecTrustEvaluateWithError(trust, nil) else { completionHandler(.cancelAuthenticationChallenge, nil); return }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    func post(_ path: String, _ body: [String: String]) async throws -> [String: Any] {
        var components = URLComponents(); components.scheme = "https"; components.host = host; components.port = 8784; components.path = path
        guard let url = components.url else { throw RecorderFailure.message("Проверь адрес Mac") }
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.timeoutInterval = 15
        request.httpBody = try JSONSerialization.data(withJSONObject: body); request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let (data, response) = try await session.data(for: request)
        guard data.count <= 65536, let value = try JSONSerialization.jsonObject(with: data) as? [String: Any], let status = (response as? HTTPURLResponse)?.statusCode else { throw RecorderFailure.message("Mac вернул непонятный ответ") }
        guard status == 200 else { throw RecorderFailure.message(value["error"] as? String ?? "Mac отклонил подключение") }
        return value
    }
}
