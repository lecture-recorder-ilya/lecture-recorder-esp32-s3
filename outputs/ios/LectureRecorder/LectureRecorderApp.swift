import SwiftUI
import UniformTypeIdentifiers

@main struct LectureRecorderApp: App {
    @StateObject private var model = PhoneModel()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            FieldNotesHome(model: model)
                .onChange(of: phase) { value in
                    if value == .active { model.applicationDidBecomeActive() }
                    else { model.playback.checkpoint() }
                }
        }
    }
}

struct FieldNotesHome: View {
    @ObservedObject var model: PhoneModel
    @State private var tab = HomeTab.record
    @State private var requestedFile: String?

    var body: some View {
        TabView(selection: $tab) {
            RecordScreen(model: model) { file in
                requestedFile = file
                tab = .library
            }
            .tabItem { Label("Запись", systemImage: "mic") }.tag(HomeTab.record)

            LibraryScreen(model: model, requestedFile: $requestedFile)
                .tabItem { Label("Библиотека", systemImage: "books.vertical") }.tag(HomeTab.library)
        }
        .onChange(of: model.savedFile) { file in
            if file != nil { UIAccessibility.post(notification: .announcement, argument: "Запись сохранена в библиотеке") }
        }
        .onChange(of: model.captureNotice) { notice in
            if !notice.isEmpty { UIAccessibility.post(notification: .announcement, argument: notice) }
        }
        .tint(Studio.accent)
    }
}

private enum HomeTab { case record, library }

struct ScreenEntry: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var entered = false

    func body(content: Content) -> some View {
        content
            .opacity(entered || reduceMotion ? 1 : 0.86)
            .offset(y: entered || reduceMotion ? 0 : 5)
            .onAppear {
                guard !entered else { return }
                withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0.72, 0.27, 1, duration: 0.18)) {
                    entered = true
                }
            }
    }
}

extension View {
    func studioScreen() -> some View {
        self
            .background(Studio.background.ignoresSafeArea())
            .toolbarBackground(Studio.background, for: .navigationBar, .tabBar)
            .toolbarBackground(.visible, for: .navigationBar, .tabBar)
    }
}

func clock(_ value: Double) -> String {
    guard value.isFinite, value < Double(Int.max) else { return "—" }
    let seconds = Int(max(0, value))
    return String(format: "%02d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
}

struct RecordScreen: View {
    @ObservedObject var model: PhoneModel
    let openMaterial: (String) -> Void
    @Environment(\.openURL) private var openURL
    @State private var importing = false
    @State private var settings = false

    private var phase: CapturePhase {
        if model.recording { return .recording }
        if model.starting { return .starting }
        if model.importingFile { return .importing }
        return model.busy ? .saving : .ready
    }

    var body: some View {
        ScrollView {
            CaptureDesk(
                phase: phase, source: model.sourceLabel, elapsed: phase == .recording || phase == .saving ? model.seconds : 0,
                signal: model.meterLevel, notice: model.captureNotice,
                permissionSettings: model.needsMicrophoneAccess ? openMicrophoneSettings : nil,
                savedTitle: model.savedItem?.title,
                capture: capture, importAudio: { importing = true }, settings: { settings = true },
                openSaved: { if let file = model.savedFile { openMaterial(file) } }
            )
        }
        .studioScreen()
        .fileImporter(isPresented: $importing, allowedContentTypes: [.audio, .movie], onCompletion: model.selectImport)
        .sheet(isPresented: $settings) { SettingsScreen(model: model) }
    }

    private func openMicrophoneSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
    }

    private func capture() {
        switch phase {
        case .ready: model.startRecording()
        case .starting: model.cancelStart()
        case .recording: model.stopRecording()
        case .saving, .importing: break
        }
    }
}

struct SettingsScreen: View {
    @ObservedObject var model: PhoneModel
    @Environment(\.dismiss) private var dismiss
    @State private var host = ""
    @State private var code = ""
    @State private var disconnect = false
    var body: some View {
        NavigationStack {
            Form {
                Section("Диктофон ClipMic") {
                    if let id = model.boardID {
                        Label("Сохранённый ClipMic · " + String(id.uuidString.suffix(4)), systemImage: "checkmark.circle")
                        Button("Забыть диктофон", role: .destructive) { model.forgetBoard() }
                            .disabled(model.recording || model.busy || model.findingBoard)
                    } else {
                        Text("Удержи REC на ClipMic P1 или BOOT на плате около секунды, затем выбери его здесь. В следующий раз достаточно нажать «Начать запись».")
                            .font(.footnote)
                        if model.findingBoard {
                            ForEach(model.boards) { board in
                                Button(board.label) { model.chooseBoard(board.id) }
                            }
                            Button("Отменить поиск") { model.cancelBoardSearch() }
                        } else {
                            Button("Найти ClipMic по Bluetooth") { model.findBoard() }
                                .disabled(model.recording || model.busy)
                        }
                    }
                    if !model.boardStatus.isEmpty { Text(model.boardStatus).font(.footnote).foregroundStyle(.secondary) }
                }
                Section("Телефон и Mac") {
                    Text(model.macName)
                    Text("Открой на Mac «Настройки → Телефон и Mac → Подключить телефон». Оба устройства должны быть в одной Wi-Fi сети.").font(.footnote)
                    TextField("Адрес Mac с его экрана", text: $host).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    TextField("Код Mac · 12 символов", text: $code).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    if !model.verification.isEmpty { Text(model.verification).font(.largeTitle.monospacedDigit()); Text("Сравни цифры и подтверди подключение на Mac") }
                    Button(model.pairing ? "Ожидаю подтверждения…" : "Подключить Mac") { model.connect(host: host, code: code) }.disabled(model.pairing || model.recording)
                    if model.pairing { Button("Отмена") { model.cancelPairing() } }
                    if !model.macStatus.isEmpty { Text(model.macStatus).font(.footnote).foregroundStyle(.secondary) }
                    Button("Отключить Mac", role: .destructive) { disconnect = true }.disabled(model.recording || model.pairing)
                }
                Section("Перенос и обновления") {
                    Text("Открой приложение рядом с Mac. Новые записи и расшифровки переносятся по Wi-Fi автоматически. После подтверждения Mac аудиокопия остаётся в библиотеке телефона.")
                    Text("В фоне iOS может приостановить перенос. Продолжающаяся запись сохраняется локально.")
                    Text("Обновления для iPhone устанавливаются через TestFlight или App Store.")
                    let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
                    Text("Версия \(version) · iOS / iPadOS 16+").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden)
            .modifier(ScreenEntry())
            .navigationTitle("Настройки")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Готово") { dismiss() } } }
            .studioScreen()
            .confirmationDialog("Отключить Mac? Записи и тексты останутся на телефоне.", isPresented: $disconnect) { Button("Отключить Mac", role: .destructive) { model.disconnect() } }
        }
    }
}
