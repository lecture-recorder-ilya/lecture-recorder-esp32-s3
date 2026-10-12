import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var process: Process?
    var timer: Timer?
    var view: WKWebView!
    var attempts = 0
    var finishRecordingOnExit = false
    var reloading = false
    let root = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        let reloadItem = NSMenuItem(title: "Обновить приложение", action: #selector(reloadApplication), keyEquivalent: "r")
        reloadItem.target = self; appMenu.addItem(reloadItem)
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Выйти — запись продолжится", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        let finishItem = NSMenuItem(title: "Завершить запись и выйти", action: #selector(finishAndQuit), keyEquivalent: "")
        finishItem.target = self; appMenu.addItem(finishItem)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x:0, y:0, width:880, height:840), styleMask:[.titled,.closable,.miniaturizable,.resizable], backing:.buffered, defer:false)
        window.title = "Запись лекций"
        window.center(); window.delegate = self
        view = WKWebView(frame: window.contentView!.bounds)
        view.autoresizingMask = [.width,.height]
        window.contentView!.addSubview(view)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
        probe(startIfMissing: true)
    }
    func probe(startIfMissing: Bool) {
        let url = URL(string:"http://127.0.0.1:8767/app-info")!
        var request = URLRequest(url:url); request.timeoutInterval = 1
        URLSession.shared.dataTask(with:request) { data, response, error in
            DispatchQueue.main.async {
                let diagnostic = "status=\((response as? HTTPURLResponse)?.statusCode ?? 0) error=\(error?.localizedDescription ?? "none") attempt=\(self.attempts)"
                try? diagnostic.write(to: self.root.appendingPathComponent("work/app-probe.txt"), atomically: true, encoding: .utf8)
                if let response = response as? HTTPURLResponse, response.statusCode == 200 {
                    self.timer?.invalidate()
                    self.view.load(URLRequest(url:URL(string:"http://127.0.0.1:8767/")!))
                } else if startIfMissing {
                    if let error = error {
                        try? error.localizedDescription.write(to: self.root.appendingPathComponent("work/app-startup-error.txt"), atomically: true, encoding: .utf8)
                    }
                    self.launchBackend()
                }
            }
        }.resume()
    }
    func launchBackend() {
        let child = Process()
        child.executableURL = root.appendingPathComponent("work/esp-check-env/bin/python")
        child.arguments = [root.appendingPathComponent("outputs/recorder/app_server.py").path]
        child.currentDirectoryURL = root
        child.standardOutput = FileHandle.nullDevice
        let logURL = root.appendingPathComponent("work/app-server.log")
        if !FileManager.default.fileExists(atPath:logURL.path) { FileManager.default.createFile(atPath:logURL.path, contents:nil) }
        let log = try? FileHandle(forWritingTo:logURL)
        log?.seekToEndOfFile(); child.standardError = log ?? FileHandle.nullDevice
        do { try child.run(); process = child }
        catch {
            let alert = NSAlert(); alert.messageText = "Не удалось запустить приложение"; alert.informativeText = "Оставь приложение в папке проекта: ему нужна установленная среда записи."; alert.runModal(); NSApp.terminate(nil); return
        }
        timer = Timer.scheduledTimer(withTimeInterval:0.5, repeats:true) { _ in
            self.attempts += 1
            if self.attempts > 100 {
                self.timer?.invalidate()
                let alert = NSAlert(); alert.messageText = "Сервис записи не отвечает"; alert.informativeText = "Проверь, что папка проекта не перемещена."; alert.runModal()
            } else { self.probe(startIfMissing:false) }
        }
    }
    @objc func reloadApplication() {
        guard !reloading else { return }
        reloading = true
        var request = URLRequest(url:URL(string:"http://127.0.0.1:8767/reload-app")!)
        request.httpMethod = "POST"; request.timeoutInterval = 5
        URLSession.shared.dataTask(with:request) { data, response, error in
            let result = data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
            guard error == nil, (response as? HTTPURLResponse)?.statusCode == 200, let previous = result?["generation"] as? String else {
                DispatchQueue.main.async {
                    self.reloading = false
                    let alert = NSAlert(); alert.messageText = "Не удалось обновить приложение"
                    alert.informativeText = result?["error"] as? String ?? "Проверь журнал work/app-server.log. Запись продолжает работать отдельно."; alert.runModal()
                }
                return
            }
            DispatchQueue.main.async { self.waitForReload(previous:previous, remaining:120) }
        }.resume()
    }
    func waitForReload(previous:String?, remaining:Int) {
        guard remaining > 0 else {
            reloading = false
            let alert = NSAlert(); alert.messageText = "Приложение пока не обновилось"
            alert.informativeText = "Запись продолжает работать отдельно. Открой приложение снова."; alert.runModal()
            return
        }
        var request = URLRequest(url:URL(string:"http://127.0.0.1:8767/app-info")!)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with:request) { data, response, error in
            let info = data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
            DispatchQueue.main.async {
                if let generation = info?["generation"] as? String, generation != previous {
                    self.reloading = false
                    self.view.load(URLRequest(url:URL(string:"http://127.0.0.1:8767/")!))
                } else {
                    DispatchQueue.main.asyncAfter(deadline:.now()+0.5) { self.waitForReload(previous:previous, remaining:remaining-1) }
                }
            }
        }.resume()
    }
    @objc func finishAndQuit() { finishRecordingOnExit = true; NSApp.terminate(nil) }
    func windowShouldClose(_ sender:NSWindow) -> Bool { NSApp.terminate(nil); return true }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        if !finishRecordingOnExit { return .terminateNow }
        var request = URLRequest(url:URL(string:"http://127.0.0.1:8765/stop")!)
        request.httpMethod = "POST"; request.timeoutInterval = 7
        URLSession.shared.dataTask(with:request) { _,_,_ in
            DispatchQueue.main.async {
                NSApp.reply(toApplicationShouldTerminate:true)
            }
        }.resume()
        return .terminateLater
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
