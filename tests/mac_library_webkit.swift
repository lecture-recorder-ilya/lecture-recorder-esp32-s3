import AppKit
import WebKit

let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
let config = WKWebViewConfiguration()
config.websiteDataStore = .nonPersistent()
config.mediaTypesRequiringUserActionForPlayback = []
let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 720), styleMask: .borderless, backing: .buffered, defer: false)
window.alphaValue = 0
window.orderBack(nil)
for phase in ["entry", "initial", "restore"] {
    window.setContentSize(NSSize(width: phase == "initial" ? 1000 : 420, height: 720))
    let web = WKWebView(frame: window.contentView!.bounds, configuration: config)
    window.contentView = web
    web.load(URLRequest(url: URL(string: CommandLine.arguments[1] + "/?phase=" + phase)!))
    var result = ""
    let deadline = Date().addingTimeInterval(17)
    while result.isEmpty && Date() < deadline {
        var returned = false
        web.evaluateJavaScript("document.getElementById('library-test')?.textContent || ''") { value, _ in
            result = value as? String ?? ""
            returned = true
        }
        while !returned && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.025)) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
    }
    guard result == "ok" else {
        FileHandle.standardError.write(Data("\(phase) · \(result.isEmpty ? "время проверки истекло" : result)\n".utf8))
        exit(1)
    }
}
