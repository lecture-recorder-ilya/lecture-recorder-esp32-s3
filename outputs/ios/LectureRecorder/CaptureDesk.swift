import SwiftUI

enum CapturePhase {
    case ready, starting, recording, saving, importing

    var title: String {
        switch self {
        case .ready: return "Новая запись"
        case .starting: return "Подготовка"
        case .recording: return "Идёт запись"
        case .saving: return "Сохранение"
        case .importing: return "Импорт записи"
        }
    }

    var action: String {
        switch self {
        case .ready: return "Начать запись"
        case .starting: return "Отменить запуск"
        case .recording: return "Завершить и сохранить"
        case .saving: return "Сохраняем…"
        case .importing: return "Импортируем…"
        }
    }
}

struct CaptureDesk: View {
    let phase: CapturePhase
    let source: String
    let elapsed: Double
    let signal: () -> Double
    let notice: String
    let permissionSettings: (() -> Void)?
    let savedTitle: String?
    let capture: () -> Void
    let importAudio: () -> Void
    let settings: () -> Void
    let openSaved: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @ScaledMetric(relativeTo: .largeTitle) private var timerSize = 76.0

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                FieldMark().frame(width: 40, height: 40).accessibilityHidden(true)
                Text("Коса")
                    .font(.largeTitle.weight(.bold)).tracking(-1.4)
                    .foregroundStyle(Studio.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                Button(action: settings) {
                    Image(systemName: "gearshape").font(.title3)
                        .frame(width: 44, height: 44)
                        .foregroundStyle(Studio.ink)
                        .modifier(DeskGlass(radius: 22, interactive: true))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Настройки")
            }

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Label(phase.title, systemImage: phase == .recording ? "record.circle.fill" : "mic")
                        .font(.headline)
                        .foregroundStyle(phase == .recording ? Studio.live : Studio.cardInk)
                    Spacer(minLength: 8)
                    if phase == .recording { InputMeter(signal: signal) }
                }

                if phase == .importing {
                    Text(source).font(.title2.weight(.medium)).foregroundStyle(Studio.cardInk)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Файл " + source)
                } else {
                    Text(displayTime)
                        .font(.system(size: timerSize, weight: .light).monospacedDigit())
                        .foregroundStyle(Studio.cardInk)
                        .lineLimit(1).minimumScaleFactor(0.35)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityLabel("Длительность записи")
                        .accessibilityValue(spokenTime)
                        .accessibilityAddTraits(.updatesFrequently)

                    HStack(alignment: .center, spacing: 12) {
                        Image(systemName: "mic.fill")
                            .foregroundStyle(Studio.accent).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(phase == .ready ? "Источник при старте" : "Источник").font(.caption).foregroundStyle(Studio.cardMuted)
                            Text(source).font(.body.weight(.medium)).foregroundStyle(Studio.cardInk)
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .padding(.vertical, 5)
                }

                Button(action: capture) {
                    HStack(spacing: 9) {
                        if phase == .saving || phase == .importing {
                            ProgressView().tint(Studio.card)
                        } else {
                            Image(systemName: phase == .ready ? "record.circle" : (phase == .starting ? "xmark" : "stop.fill"))
                                .accessibilityHidden(true)
                        }
                        Text(phase.action)
                            .font(.headline)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 14)
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .foregroundStyle(Studio.card)
                    .modifier(DeskGlass(radius: 15, tint: phase == .recording ? Studio.live : Studio.accent, interactive: true))
                }
                .buttonStyle(DeskButtonStyle())
                .disabled(phase == .saving || phase == .importing)
            }
            .padding(typeSize.isAccessibilitySize ? 18 : 22)
            .background {
                CaptureArtwork(live: phase == .recording, signal: signal)
            }
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Studio.line).allowsHitTesting(false) }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: phase)

            if !notice.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Label(notice, systemImage: "info.circle")
                        .font(.subheadline).foregroundStyle(Studio.ink)
                    if let permissionSettings {
                        Button("Открыть настройки микрофона", action: permissionSettings)
                            .font(.headline).frame(minHeight: 44)
                    }
                }
            }
            if let savedTitle {
                Button(action: openSaved) { SavedRecordingRow(title: savedTitle) }
                    .buttonStyle(DeskButtonStyle())
                    .transition(reduceMotion ? .identity : .opacity)
            }

            Button(action: importAudio) {
                HStack(spacing: 12) {
                    Image(systemName: "square.and.arrow.down")
                        .font(.title3.weight(.medium))
                        .frame(width: 42, height: 46)
                        .foregroundStyle(Studio.accent)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Импорт из Файлов").font(.headline).foregroundStyle(Studio.ink)
                        Text("M4A, MP3, WAV или видео").font(.subheadline).foregroundStyle(Studio.muted)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                        .foregroundStyle(Studio.muted).accessibilityHidden(true)
                }
                .multilineTextAlignment(.leading)
                .padding(.vertical, 13).padding(.horizontal, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .modifier(DeskGlass(radius: 17, interactive: true))
            }
            .buttonStyle(DeskButtonStyle())
            .disabled(phase != .ready)
            .accessibilityElement(children: .combine)
        }
        .padding(.horizontal, 20).padding(.vertical, 16)
        .frame(maxWidth: 580)
        .frame(maxWidth: .infinity)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: savedTitle)
    }

    private var seconds: Int {
        guard elapsed.isFinite, elapsed > 0 else { return 0 }
        return Int(min(8 * 3600, elapsed))
    }

    private var displayTime: String {
        seconds < 3600 ? String(format: "%02d:%02d", seconds / 60, seconds % 60)
            : String(format: "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
    }

    private var spokenTime: String {
        Duration.seconds(seconds).formatted(.units(allowed: [.hours, .minutes, .seconds], width: .wide)
            .locale(Locale(identifier: "ru")))
    }
}

struct SavedRecordingRow: View {
    let title: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.title3).foregroundStyle(Studio.accent).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Сохранено в библиотеке").font(.subheadline.weight(.semibold)).foregroundStyle(Studio.accent)
                Text(title).font(.headline).foregroundStyle(Studio.ink)
            }
            Spacer(minLength: 4)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                .foregroundStyle(Studio.accent).accessibilityHidden(true)
        }
        .multilineTextAlignment(.leading)
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .modifier(DeskGlass(radius: 17, interactive: true))
        .accessibilityElement(children: .combine)
        .accessibilityHint("Открывает материал в библиотеке")
    }
}

private struct FieldMark: View {
    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 64, y: size.height / 64)
            context.concatenate(CGAffineTransform(a: 1, b: 0, c: -0.156, d: 1, tx: 5, ty: 0))
            for (index, height) in [16, 30, 44, 34, 20].enumerated() {
                let bar = CGRect(x: 9 + index * 10, y: (64 - height) / 2, width: 6, height: height)
                context.fill(Path(roundedRect: bar, cornerRadius: 3), with: .color(Studio.accent))
            }
        }
    }
}

private struct CaptureArtwork: View {
    let live: Bool
    let signal: () -> Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scene

    var body: some View {
        let still = reduceMotion || scene != .active
        TimelineView(.animation(minimumInterval: 1.0 / 24, paused: still)) { frame in
            let angle = still ? 0 : frame.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 16) * .pi / 8
            GeometryReader { area in
                Image("CaptureWave").resizable().scaledToFill().saturation(0.06)
                    .frame(width: area.size.width, height: area.size.height)
                    .scaleEffect(1.10 + (live && !still ? 0.04 * signal() : 0))
                    .offset(x: sin(angle) * area.size.width * 0.035, y: cos(angle) * area.size.height * 0.025)
                    .clipped()
                    .overlay {
                        LinearGradient(stops: [
                            .init(color: Studio.card, location: 0),
                            .init(color: Studio.card.opacity(0.91), location: 0.42),
                            .init(color: Studio.card.opacity(0.30), location: 1)
                        ], startPoint: .leading, endPoint: .trailing)
                    }
            }
        }.accessibilityHidden(true)
    }
}

struct PlayingBars: View {
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scene

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: !active || reduceMotion || scene != .active)) { frame in
            let phase = active && !reduceMotion ? frame.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 2) * .pi : 0
            HStack(spacing: 2) {
                ForEach(0..<5, id: \.self) { index in
                    Capsule().frame(width: 2, height: 4 + 11 * abs(sin(phase + Double(index) * 0.83)))
                }
            }
        }.frame(width: 20, height: 18).accessibilityHidden(true)
    }
}

private struct InputMeter: View {
    let signal: () -> Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.periodic(from: .now, by: reduceMotion ? 1 : 0.2)) { _ in
            let lit = Int((max(0, min(1, signal())) * 10).rounded())
            HStack(alignment: .bottom, spacing: 2) {
                ForEach(0..<10, id: \.self) { index in
                    Capsule().fill(index < lit ? Studio.accent : Studio.cardMuted.opacity(0.3))
                        .frame(width: 3, height: CGFloat(4 + index * 2))
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Уровень сигнала")
            .accessibilityValue("\(lit) из 10")
            .accessibilityAddTraits(.updatesFrequently)
        }
    }
}

private struct DeskButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(enabled ? (configuration.isPressed ? 0.83 : 1) : 0.62)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.985 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
