import SwiftUI

@main struct LectureRecorderApp: App {
    @StateObject private var model = PhoneModel()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            TabView {
                RecordScreen(model: model).tabItem { Label("Запись", systemImage: "mic") }
                LibraryScreen(model: model).tabItem { Label("Библиотека", systemImage: "books.vertical") }
                SettingsScreen(model: model).tabItem { Label("Настройки", systemImage: "gearshape") }
            }
            .onChange(of: phase) { value in if value != .active { model.playback.checkpoint() } }
            .tint(Studio.accent)
            .preferredColorScheme(.dark)
        }
    }
}

enum Studio {
    static let background = Color(red: 18 / 255, green: 22 / 255, blue: 24 / 255)
    static let panel = Color(red: 29 / 255, green: 35 / 255, blue: 37 / 255)
    static let hero = Color(red: 32 / 255, green: 59 / 255, blue: 57 / 255)
    static let line = Color(red: 59 / 255, green: 73 / 255, blue: 73 / 255)
    static let ink = Color(red: 13 / 255, green: 37 / 255, blue: 34 / 255)
    static let muted = Color(red: 165 / 255, green: 180 / 255, blue: 195 / 255)
    static let accent = Color(red: 124 / 255, green: 218 / 255, blue: 196 / 255)
    static let recording = Color(red: 1, green: 192 / 255, blue: 177 / 255)
    static let warning = Color(red: 243 / 255, green: 194 / 255, blue: 135 / 255)
}

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

private struct RecordButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isEnabled) private var enabled
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity, minHeight: 48)
            .padding(.horizontal, 12)
            .foregroundStyle(Studio.ink)
            .background(color, in: RoundedRectangle(cornerRadius: 14))
            .opacity(enabled ? (configuration.isPressed ? 0.84 : 1) : 0.45)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.985 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
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
    @ScaledMetric(relativeTo: .largeTitle) private var timerSize = 52.0

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 16) {
                        Label(model.inputLabel,
                              systemImage: model.recording ? "record.circle.fill" : "mic.fill")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(model.recording ? Studio.recording : Studio.accent)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Длительность записи").font(.caption).foregroundStyle(Studio.muted)
                            Text(clock(model.seconds))
                                .font(.system(size: timerSize, weight: .medium, design: .monospaced))
                                .minimumScaleFactor(0.55)
                                .lineLimit(1)
                                .accessibilityLabel("Длительность записи")
                                .accessibilityValue(clock(model.seconds))
                        }
                        Button(model.recording ? "Завершить и сохранить" : (model.starting ? "Отменить" : "Начать запись")) {
                            if model.recording { model.stopRecording() }
                            else if model.starting { model.cancelStart() }
                            else { model.startRecording() }
                        }
                        .buttonStyle(RecordButtonStyle(color: model.recording ? Studio.recording : Studio.accent))
                        .disabled(model.busy && !model.starting)
                        Text("Запись сохраняется на телефоне. Wi-Fi и кабель не нужны.").font(.footnote).foregroundStyle(Studio.muted)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(24)
                    .background(
                        LinearGradient(colors: [Studio.hero, Studio.panel, Studio.panel],
                                       startPoint: .topLeading, endPoint: .bottomTrailing),
                        in: RoundedRectangle(cornerRadius: 22)
                    )
                    .overlay {
                        RoundedRectangle(cornerRadius: 22).strokeBorder(Studio.line)
                            .allowsHitTesting(false)
                    }
                    Text(model.message).font(.callout).accessibilityAddTraits(.updatesFrequently)
                    if model.recording {
                        Text("Экран можно заблокировать.")
                            .font(.footnote).foregroundStyle(Studio.muted)
                    }
                    Text("Выбор микрофона автоматический. Свой ClipMic можно подключить в настройках приложения.")
                        .font(.footnote).foregroundStyle(Studio.muted)
                }
                .frame(maxWidth: 620)
                .padding(20)
                .frame(maxWidth: .infinity)
                .modifier(ScreenEntry())
            }
            .navigationTitle("Новая запись")
            .studioScreen()
        }
    }
}

struct SettingsScreen: View {
    @ObservedObject var model: PhoneModel
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
                    Text(model.message).font(.footnote).foregroundStyle(.secondary)
                    Button("Отключить Mac", role: .destructive) { disconnect = true }.disabled(model.recording || model.pairing)
                }
                Section("Перенос и обновления") {
                    Text("Открой приложение рядом с Mac. Новые записи и расшифровки переносятся по Wi-Fi автоматически. После подтверждения Mac аудиокопия остаётся в библиотеке телефона.")
                    Text("В фоне iOS может приостановить перенос. Продолжающаяся запись сохраняется локально.")
                    Text("Версии приложения для iPhone устанавливаются через TestFlight или App Store. APK для Android сюда не подходит.")
                    let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
                    Text("Версия \(version) · iOS / iPadOS 16+").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden)
            .modifier(ScreenEntry())
            .navigationTitle("Настройки")
            .studioScreen()
            .confirmationDialog("Отключить Mac? Записи и тексты останутся на телефоне.", isPresented: $disconnect) { Button("Отключить Mac", role: .destructive) { model.disconnect() } }
        }
    }
}
