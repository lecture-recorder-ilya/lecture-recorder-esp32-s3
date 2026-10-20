import Foundation
import Security

let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                           kSecAttrService as String: "ru.ilya.lecturerecorder.updates",
                           kSecAttrAccount as String: "lecture-recorder-ilya/lecture-recorder-esp32-s3"]
let action = CommandLine.arguments.dropFirst().first ?? ""
var status: OSStatus = errSecParam
switch action {
case "read":
    var request = query
    request[kSecReturnData as String] = true
    request[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    status = SecItemCopyMatching(request as CFDictionary, &result)
    if status == errSecSuccess, let data = result as? Data {
        FileHandle.standardOutput.write(data)
    } else if status == errSecItemNotFound {
        FileHandle.standardOutput.write(Data("{}".utf8))
        status = errSecSuccess
    }
case "write":
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 16384, (try? JSONSerialization.jsonObject(with: data)) is [String: Any] else { exit(2) }
    let attributes = [kSecValueData as String: data]
    status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
        var entry = query
        entry[kSecValueData as String] = data
        entry[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        status = SecItemAdd(entry as CFDictionary, nil)
    }
case "delete":
    status = SecItemDelete(query as CFDictionary)
    if status == errSecItemNotFound { status = errSecSuccess }
default: break
}
if status != errSecSuccess {
    FileHandle.standardError.write(Data("Связка ключей недоступна (\(status))".utf8))
    exit(1)
}
