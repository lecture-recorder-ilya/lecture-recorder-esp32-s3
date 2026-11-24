import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var process: Process?
    var timer: Timer?
    var view: WKWebView!
    var attempts = 0
    var finishRecordingOnExit = false
    var reloading = false
    var downloads: [ObjectIdentifier: (temporary: URL, destination: URL)] = [:]
    let root = Bundle.main.bundleURL.resolvingSymlinksInPath().deletingLastPathComponent().deletingLastPathComponent()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let state = root.deletingLastPathComponent().appendingPathComponent("install-state.json")
        if let data = try? Data(contentsOf: state),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], value["status"] as? String == "installing" {
            repairInstallation(); NSApp.terminate(nil); return
        }
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        let reloadItem = NSMenuItem(title: "Обновить приложение", action: #selector(reloadApplication), keyEquivalent: "r")
        reloadItem.target = self; appMenu.addItem(reloadItem)
        let repairItem = NSMenuItem(title: "Восстановить компоненты…", action: #selector(repairInstallation), keyEquivalent: "")
        repairItem.target = self; appMenu.addItem(repairItem)
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Выйти — запись продолжится", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        let finishItem = NSMenuItem(title: "Завершить запись и выйти", action: #selector(finishAndQuit), keyEquivalent: "")
        finishItem.target = self; appMenu.addItem(finishItem)
        let shutdownItem = NSMenuItem(title: "Завершить работу", action: #selector(shutdownApplication), keyEquivalent: "")
        shutdownItem.target = self; appMenu.addItem(shutdownItem)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x:0, y:0, width:880, height:840), styleMask:[.titled,.closable,.miniaturizable,.resizable], backing:.buffered, defer:false)
        window.title = "Коса"
        window.appearance = NSAppearance(named: .darkAqua)
        let background = NSColor(srgbRed: 12 / 255, green: 18 / 255, blue: 22 / 255, alpha: 1)
        window.backgroundColor = background
        window.center(); window.delegate = self
        view = WKWebView(frame: window.contentView!.bounds)
        view.underPageBackgroundColor = background
        view.uiDelegate = self
        view.navigationDelegate = self
        view.autoresizingMask = [.width,.height]
        window.contentView!.addSubview(view)
        view.loadHTMLString("""
            <!doctype html><html lang="ru"><meta charset="utf-8">
            <style>
            html{color-scheme:light;background:#0c1216;color:#eef2f0}
            body{margin:0;min-height:100vh;display:grid;place-items:center;font:15px system-ui}
            </style>
            <body><p role="status">Открываю приложение «Коса»…</p></body></html>
            """, baseURL: nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
        probe(startIfMissing: true)
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.title = "Выбрать файл"
        panel.prompt = "Открыть"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { result in
            completionHandler(result == .OK ? panel.urls : nil)
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.title = "Сохранить материалы занятия"
        panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
        if let url = response.url, url.path.hasPrefix("/transcript-export/") {
            panel.nameFieldStringValue = url.deletingPathExtension().lastPathComponent + ".txt"
        } else if let url = response.url, url.path.hasPrefix("/export/") {
            panel.nameFieldStringValue = url.deletingPathExtension().lastPathComponent + ".md"
        }
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let destination = panel.url else { completionHandler(nil); return }
            let temporary = destination.deletingLastPathComponent().appendingPathComponent(".lecture-" + UUID().uuidString + ".download")
            if let url = response.url, ["http", "https"].contains(url.scheme ?? "") {
                completionHandler(nil)
                self.fetchExport(url, temporary: temporary, destination: destination)
                return
            }
            self.downloads[ObjectIdentifier(download)] = (temporary, destination)
            completionHandler(temporary)
        }
    }
    func downloadDidFinish(_ download: WKDownload) {
        guard let files = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        commitExport(temporary: files.temporary, destination: files.destination)
    }
    func fetchExport(_ url: URL, temporary: URL, destination: URL) {
        var request = URLRequest(url: url)
        request.timeoutInterval = 600
        URLSession.shared.downloadTask(with: request) { location, response, error in
            guard error == nil, let location = location, let response = response as? HTTPURLResponse, response.statusCode == 200 else {
                DispatchQueue.main.async { self.exportError("Не удалось скачать файл. Попробуй сохранить его ещё раз.") }
                return
            }
            do {
                let size = try location.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard response.expectedContentLength < 0 || Int64(size) == response.expectedContentLength else {
                    throw NSError(domain: "LectureExport", code: 1)
                }
                try FileManager.default.moveItem(at: location, to: temporary)
                DispatchQueue.main.async { self.commitExport(temporary: temporary, destination: destination) }
            } catch {
                DispatchQueue.main.async { self.exportError("Файл сохранился не полностью. Повтори скачивание.") }
            }
        }.resume()
    }
    func commitExport(temporary: URL, destination: URL) {
        do {
            if FileManager.default.fileExists(atPath: destination.path) {
                _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
            } else {
                try FileManager.default.moveItem(at: temporary, to: destination)
            }
        } catch { exportError("Не удалось сохранить файл. Подготовленная копия находится здесь: " + temporary.path) }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let files = downloads.removeValue(forKey: ObjectIdentifier(download)) { try? FileManager.default.removeItem(at: files.temporary) }
        if (error as NSError).code != NSURLErrorCancelled { exportError("Не удалось скачать файл. Попробуй сохранить его ещё раз.") }
    }
    func exportError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Сохранение материалов"
        alert.informativeText = message
        alert.beginSheetModal(for: window)
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
                    let info = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                    guard info?["project"] as? String == self.root.path else {
                        let alert = NSAlert(); alert.messageText = "Уже запущена другая копия приложения"
                        alert.informativeText = "Заверши её работу через меню приложения и открой эту копию снова. Её записи останутся на месте."
                        alert.runModal(); return
                    }
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
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONNOUSERSITE"] = "1"
        if FileManager.default.fileExists(atPath: "/etc/ssl/cert.pem") { environment["SSL_CERT_FILE"] = "/etc/ssl/cert.pem" }
        environment.removeValue(forKey: "PYTHONHOME"); environment.removeValue(forKey: "PYTHONPATH")
        child.environment = environment
        child.standardOutput = FileHandle.nullDevice
        let logURL = root.appendingPathComponent("work/app-server.log")
        if !FileManager.default.fileExists(atPath:logURL.path) { FileManager.default.createFile(atPath:logURL.path, contents:nil) }
        let log = try? FileHandle(forWritingTo:logURL)
        log?.seekToEndOfFile(); child.standardError = log ?? FileHandle.nullDevice
        do { try child.run(); process = child }
        catch {
            let alert = NSAlert(); alert.messageText = "Нужно подготовить компоненты приложения"
            alert.informativeText = "Открой «Установить Косу». Установщик подготовит компоненты и сохранит библиотеку."
            alert.addButton(withTitle: "Восстановить"); alert.addButton(withTitle: "Закрыть")
            if alert.runModal() == .alertFirstButtonReturn { self.repairInstallation() }
            NSApp.terminate(nil); return
        }
        timer = Timer.scheduledTimer(withTimeInterval:0.5, repeats:true) { _ in
            self.attempts += 1
            if self.attempts > 100 {
                self.timer?.invalidate()
                let alert = NSAlert(); alert.messageText = "Приложение пока не запустилось"; alert.informativeText = "Можно восстановить компоненты через меню приложения. Записи сохранятся."; alert.runModal()
            } else { self.probe(startIfMissing:false) }
        }
    }
    @objc func repairInstallation() {
        let installers = ["Установить Косу.app", "Установить Диктофон.app", "Установить На полях.app", "Установить Запись лекций.app"].map {
            root.deletingLastPathComponent().appendingPathComponent($0)
        }
        if let installer = installers.first(where: { Bundle(url: $0)?.bundleIdentifier == "local.esp.recorder.installer" }) {
            NSWorkspace.shared.open(installer)
        }
        else {
            let alert = NSAlert(); alert.messageText = "Открой «Установить Косу»"
            alert.informativeText = "Он подготовит компоненты без терминала. Библиотека этой копии останется на месте."; alert.runModal()
        }
    }
    @objc func shutdownApplication() {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8767/quit-for-install")!)
        request.httpMethod = "POST"; request.timeoutInterval = 20
        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 { NSApp.terminate(nil) }
                else {
                    let value = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                    let alert = NSAlert(); alert.messageText = "Приложение ещё работает"
                    alert.informativeText = value?["error"] as? String ?? "Дождись завершения записи и разбора, затем повтори."; alert.runModal()
                }
            }
        }.resume()
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
