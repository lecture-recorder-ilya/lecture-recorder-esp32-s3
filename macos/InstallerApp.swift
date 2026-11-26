import Cocoa

final class InstallerDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let fm = FileManager.default
    let resources = Bundle.main.resourceURL!.appendingPathComponent("Setup")
    let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Lecture Recorder")
    var window: NSWindow!
    var stage: NSTextField!
    var detail: NSTextField!
    var percent: NSTextField!
    var progress: NSProgressIndicator!
    var primary: NSButton!
    var secondary: NSButton!
    var repair: NSButton!
    var child: Process?
    var busy = false
    var complete = false
    var quitting = false
    var closedApplication = false
    var buffer = Data()
    var pipe: Pipe?
    var application: URL { support.appendingPathComponent("project/outputs/Запись лекций.app") }

    func label(_ text: String, size: CGFloat, color: NSColor = .labelColor) -> NSTextField {
        let view = NSTextField(wrappingLabelWithString: text)
        view.font = .systemFont(ofSize: size)
        view.textColor = color
        view.maximumNumberOfLines = 0
        return view
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(NSMenuItem(title: "Выйти", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 610), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Установить зу"
        window.delegate = self
        window.center()
        let content = window.contentView!
        let stack = NSStackView()
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 32), stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -32), stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 28)])
        let header = NSStackView(); header.orientation = .horizontal; header.spacing = 18
        let icon = NSImageView(image: NSImage(named: NSImage.applicationIconName) ?? NSImage())
        icon.translatesAutoresizingMaskIntoConstraints = false
        icon.widthAnchor.constraint(equalToConstant: 72).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 72).isActive = true
        header.addArrangedSubview(icon)
        let titles = NSStackView(); titles.orientation = .vertical; titles.alignment = .leading; titles.spacing = 7
        let title = label("зу", size: 27)
        title.font = .systemFont(ofSize: 27, weight: .semibold)
        titles.addArrangedSubview(title)
        titles.addArrangedSubview(label("Записи, расшифровки и конспекты в одном месте", size: 14, color: .secondaryLabelColor))
        header.addArrangedSubview(titles); stack.addArrangedSubview(header)
        let introduction = label("Установщик подготовит всё сам и добавит приложение в твою папку «Приложения». Пароль администратора и терминал не нужны.", size: 15)
        stack.addArrangedSubview(introduction)
        let requirements = label("Mac с Apple Silicon · macOS 14 или новее\nОколо 12 ГБ моделей · 22 ГБ свободного места · интернет для установки\nДля обработки больших лекций рекомендуется 16 ГБ памяти.", size: 13, color: .secondaryLabelColor)
        stack.addArrangedSubview(requirements)
        let divider = NSBox(); divider.boxType = .separator; stack.addArrangedSubview(divider)
        stage = label("Готово к установке", size: 17)
        stage.font = .systemFont(ofSize: 17, weight: .medium)
        detail = label("Можно приостановить установку и продолжить позже. Сохранённые записи и тексты останутся на месте.", size: 14, color: .secondaryLabelColor)
        stack.addArrangedSubview(stage); stack.addArrangedSubview(detail)
        progress = NSProgressIndicator(); progress.style = .bar; progress.isIndeterminate = false; progress.minValue = 0; progress.maxValue = 100
        progress.translatesAutoresizingMaskIntoConstraints = false
        stack.addArrangedSubview(progress)
        progress.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        percent = label("", size: 12, color: .secondaryLabelColor); stack.addArrangedSubview(percent)
        let buttons = NSStackView(); buttons.orientation = .horizontal; buttons.spacing = 12
        primary = NSButton(title: "Установить и открыть", target: self, action: #selector(primaryAction))
        primary.bezelStyle = .rounded; primary.controlSize = .large; primary.keyEquivalent = "\r"
        secondary = NSButton(title: "Журнал установки", target: self, action: #selector(secondaryAction)); secondary.bezelStyle = .rounded
        repair = NSButton(title: "Восстановить", target: self, action: #selector(startInstall)); repair.bezelStyle = .rounded; repair.isHidden = true
        buttons.addArrangedSubview(primary); buttons.addArrangedSubview(secondary); buttons.addArrangedSubview(repair)
        stack.addArrangedSubview(buttons)
        for view in [introduction, requirements, divider, stage!, detail!] {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let metadata = (try? Data(contentsOf: resources.appendingPathComponent("manifest.json"))).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        if let data = try? Data(contentsOf: support.appendingPathComponent("install-state.json")),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], value["status"] as? String == "complete",
           (value["code"] as? Int ?? 0) >= (metadata?["code"] as? Int ?? 1),
           fm.isExecutableFile(atPath: support.appendingPathComponent("project/work/ai-env/bin/python").path),
           fm.fileExists(atPath: application.path) {
            finished()
        }
    }

    @objc func primaryAction() {
        if complete {
            let configuration = NSWorkspace.OpenConfiguration()
            NSWorkspace.shared.openApplication(at: application, configuration: configuration) { _, error in
                DispatchQueue.main.async {
                    if let error = error { self.detail.stringValue = "Не удалось открыть приложение: " + error.localizedDescription }
                    else { NSApp.terminate(nil) }
                }
            }
        } else { startInstall() }
    }

    @objc func startInstall() {
        guard !busy else { return }
        complete = false; busy = true; buffer = Data(); closedApplication = false
        primary.isEnabled = false; repair.isHidden = true; secondary.title = "Приостановить"
        stage.stringValue = "Подготовка"
        detail.stringValue = "Подготавливаю приложение. Это займёт несколько минут."
        progress.doubleValue = 0; progress.isIndeterminate = true; progress.startAnimation(nil); percent.stringValue = ""
        let process = Process()
        process.executableURL = resources.appendingPathComponent("python/bin/python3.12")
        process.arguments = ["-I", "-B", resources.appendingPathComponent("install.py").path, "--resources", resources.path, "--support", support.path,
                             "--applications", fm.homeDirectoryForCurrentUser.appendingPathComponent("Applications").path, "--installer-app", Bundle.main.bundleURL.path]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONNOUSERSITE"] = "1"; environment["PYTHONUNBUFFERED"] = "1"
        environment.removeValue(forKey: "PYTHONHOME"); environment.removeValue(forKey: "PYTHONPATH")
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        let output = Pipe(); pipe = output; process.standardOutput = output; process.standardError = output
        output.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self.consume(data) }
        }
        process.terminationHandler = { result in
            DispatchQueue.main.async {
                self.busy = false; self.child = nil
                self.progress.stopAnimation(nil); self.progress.isIndeterminate = false
                self.primary.isEnabled = true; self.secondary.title = "Журнал установки"
                if self.quitting { NSApp.reply(toApplicationShouldTerminate: true); return }
                if result.terminationStatus == 0 { self.finished(); self.primaryAction() }
                else if !self.complete {
                    self.primary.title = "Продолжить"
                    if self.stage.stringValue == "Подготовка" {
                        self.stage.stringValue = "Не удалось начать установку"
                        self.detail.stringValue = "Скачай установщик заново и повтори. Сохранённые записи останутся на месте."
                    }
                }
            }
        }
        do { try process.run(); child = process }
        catch {
            busy = false; primary.isEnabled = true; primary.title = "Продолжить"; secondary.title = "Журнал установки"
            progress.stopAnimation(nil); progress.isIndeterminate = false
            stage.stringValue = "Не удалось начать установку"
            detail.stringValue = "Пакет не удалось открыть. Скачай установщик заново."
        }
    }

    func consume(_ data: Data) {
        buffer.append(data)
        while let range = buffer.range(of: Data([10])) {
            let line = buffer.subdata(in: 0..<range.lowerBound)
            buffer.removeSubrange(0..<range.upperBound)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            if let text = value["stage"] as? String { stage.stringValue = text }
            if !closedApplication, value["stage"] as? String == "Компоненты приложения" {
                closedApplication = true
                for running in NSRunningApplication.runningApplications(withBundleIdentifier: "local.esp.recorder") {
                    if running.bundleURL?.resolvingSymlinksInPath() == application.resolvingSymlinksInPath() { running.terminate() }
                }
            }
            if let text = value["detail"] as? String { detail.stringValue = text }
            if let number = value["progress"] as? Double {
                progress.stopAnimation(nil); progress.isIndeterminate = false
                progress.doubleValue = max(0, min(100, number)); percent.stringValue = "\(Int(progress.doubleValue)) %"
            }
        }
    }

    func finished() {
        complete = true; progress.isIndeterminate = false; progress.doubleValue = 100; percent.stringValue = "100 %"
        stage.stringValue = "Всё готово"
        let applications = fm.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
        let shortcut = ["зу.app", "зу — локальная.app", "Коса.app", "Коса — локальная.app", "Диктофон.app", "Диктофон — локальная.app", "На полях.app", "На полях — локальная.app", "Запись лекций.app"]
            .map { applications.appendingPathComponent($0) }
            .first { $0.resolvingSymlinksInPath().path == application.resolvingSymlinksInPath().path }
        if let shortcut {
            let name = shortcut.deletingPathExtension().lastPathComponent
            detail.stringValue = "Открой приложение и выбери запись. Для следующего запуска найди «\(name)» в папке «Приложения» своего профиля."
        } else {
            detail.stringValue = "Открой приложение кнопкой ниже и выбери запись."
        }
        primary.title = "Открыть приложение"; primary.isEnabled = true; repair.isHidden = false
    }

    @objc func secondaryAction() {
        if busy {
            child?.terminate(); secondary.isEnabled = false
            detail.stringValue = "Приостанавливаю установку. Загруженные файлы останутся для продолжения."
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.secondary.isEnabled = true }
        } else {
            let log = support.appendingPathComponent("install.log")
            if fm.fileExists(atPath: log.path) { NSWorkspace.shared.open(log) }
            else { detail.stringValue = "Журнал появится после начала установки." }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if busy { quitting = true; child?.terminate(); return .terminateLater }
        return .terminateNow
    }
}

let app = NSApplication.shared
let delegate = InstallerDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
