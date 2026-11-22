import SwiftUI
import UniformTypeIdentifiers

@main struct LectureRecorderApp: App {
    @StateObject private var model = PhoneModel()
    var body: some Scene {
        WindowGroup {
            TabView {
                RecordScreen(model: model).tabItem { Label("Запись", systemImage: "mic") }
                LibraryScreen(model: model).tabItem { Label("Библиотека", systemImage: "books.vertical") }
                SettingsScreen(model: model).tabItem { Label("Настройки", systemImage: "gearshape") }
            }
            .tint(Studio.accent)
            .preferredColorScheme(.dark)
        }
    }
}

private enum Studio {
    static let background = Color(red: 14 / 255, green: 18 / 255, blue: 23 / 255)
    static let panel = Color(red: 23 / 255, green: 30 / 255, blue: 39 / 255)
    static let hero = Color(red: 32 / 255, green: 46 / 255, blue: 64 / 255)
    static let line = Color(red: 51 / 255, green: 66 / 255, blue: 82 / 255)
    static let ink = Color(red: 16 / 255, green: 33 / 255, blue: 53 / 255)
    static let muted = Color(red: 165 / 255, green: 180 / 255, blue: 195 / 255)
    static let accent = Color(red: 168 / 255, green: 215 / 255, blue: 250 / 255)
    static let recording = Color(red: 1, green: 192 / 255, blue: 177 / 255)
    static let warning = Color(red: 243 / 255, green: 194 / 255, blue: 135 / 255)
}

private struct ScreenEntry: ViewModifier {
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

private extension View {
    func studioScreen() -> some View {
        self
            .background(Studio.background.ignoresSafeArea())
            .toolbarBackground(Studio.background, for: .navigationBar, .tabBar)
            .toolbarBackground(.visible, for: .navigationBar, .tabBar)
    }
}

func clock(_ value: Double) -> String {
    let seconds = max(0, Int(value))
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
                        Label(model.recording ? "Идёт запись" : "Микрофон телефона",
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
                        Button(model.recording ? "Завершить и сохранить" : "Начать запись") {
                            if model.recording { model.stopRecording() } else { model.startRecording() }
                        }
                        .buttonStyle(RecordButtonStyle(color: model.recording ? Studio.recording : Studio.accent))
                        .disabled(model.busy)
                        Text("Запись сохраняется на телефоне.").font(.footnote).foregroundStyle(Studio.muted)
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
                        Text("Экран можно заблокировать. Звонок или системное прерывание завершит запись и сохранит доступный звук.")
                            .font(.footnote).foregroundStyle(Studio.muted)
                    }
                    Text("Очистка, расшифровка с таймкодами и конспект готовятся на Mac после переноса.")
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

struct LibraryScreen: View {
    @ObservedObject var model: PhoneModel
    @State private var importing = false
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { importing = true } label: { Label("Загрузить аудио или видео", systemImage: "square.and.arrow.down") }.disabled(model.busy || model.recording)
                    Text(model.message).font(.footnote).foregroundStyle(.secondary)
                        .listRowBackground(Studio.panel)
                }
                if !model.drafts.isEmpty {
                    Section("Незавершённые записи") {
                        ForEach(model.drafts, id: \.path) { file in
                            Button("Восстановить запись") { model.importAudio(file, removeDraft: true) }
                                .disabled(model.busy || model.recording)
                                .listRowBackground(Studio.panel)
                        }
                    }
                }
                Section("Расшифровки и конспекты") {
                    if model.notes.isEmpty {
                        Text("Появятся после обработки на Mac").foregroundStyle(Studio.muted)
                            .listRowBackground(Studio.panel)
                    }
                    ForEach(model.notes) { note in
                        NavigationLink(note.report.topic ?? note.report.subject ?? "Занятие") {
                            ReaderScreen(model: model, note: note)
                        }.listRowBackground(Studio.panel)
                    }
                }
                Section("Аудиозаписи") {
                    if model.recordings.isEmpty {
                        Text("Пока нет записей").foregroundStyle(Studio.muted).listRowBackground(Studio.panel)
                    }
                    ForEach(model.recordings, id: \.path) { file in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(file.lastPathComponent.replacingOccurrences(of: "lecture-", with: "").replacingOccurrences(of: ".wav", with: "")).font(.subheadline)
                            HStack { Button { model.play(file) } label: { Label("Слушать", systemImage: "play.fill") }.buttonStyle(.bordered); ShareLink(item: file) { Image(systemName: "square.and.arrow.up").accessibilityLabel("Поделиться записью") }.buttonStyle(.bordered) }
                        }.padding(.vertical, 6).listRowBackground(Studio.panel)
                    }
                    Button("Остановить воспроизведение") { model.stopPlayback() }.listRowBackground(Studio.panel)
                }
            }
            .scrollContentBackground(.hidden)
            .modifier(ScreenEntry())
            .navigationTitle("Библиотека")
            .studioScreen()
            .fileImporter(isPresented: $importing, allowedContentTypes: [.audio, .movie], allowsMultipleSelection: false) { result in
                switch result { case .success(let files): if let file = files.first { model.importAudio(file) }; case .failure(let error): model.message = error.localizedDescription }
            }
        }
    }
}

struct ReaderScreen: View {
    @ObservedObject var model: PhoneModel
    let note: LectureNote
    @State private var selected = 0
    var current: LectureNote { model.notes.first { $0.id == note.id } ?? note }
    var body: some View {
        List {
            Picker("Материалы", selection: $selected) { Text("Текст").tag(0); Text("Конспект").tag(1) }.pickerStyle(.segmented)
            if selected == 0 {
                if model.files.localAudio(note.file) == nil { Text("Аудиокопии на этом телефоне нет. Полная запись доступна на Mac.").font(.footnote).foregroundStyle(.secondary) }
                ForEach(Array((current.report.segments ?? []).enumerated()), id: \.offset) { _, segment in
                    Button {
                        if let file = model.files.localAudio(note.file) { model.play(file, at: segment.start ?? 0) }
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            if let start = segment.start { Text(clock(start)).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
                            Text(segment.text).foregroundStyle(.primary).multilineTextAlignment(.leading)
                            if segment.needs_review == true { Label("Проверь по записи", systemImage: "ear.badge.exclamationmark").font(.caption).foregroundStyle(Studio.warning) }
                        }.padding(.vertical, 6)
                    }.buttonStyle(.plain).disabled(model.files.localAudio(note.file) == nil || model.recording)
                        .listRowBackground(Studio.panel)
                }
            } else {
                if let overview = current.report.overview, !overview.isEmpty { Text(overview).listRowBackground(Studio.panel) }
                ForEach(Array((current.report.summary ?? []).enumerated()), id: \.offset) { _, point in
                    Text(point).listRowBackground(Studio.panel)
                }
            }
            Button("Остановить звук") { model.stopPlayback() }
        }
        .scrollContentBackground(.hidden)
        .modifier(ScreenEntry())
        .navigationTitle(current.report.topic ?? current.report.subject ?? "Занятие")
        .navigationBarTitleDisplayMode(.inline)
        .studioScreen()
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
