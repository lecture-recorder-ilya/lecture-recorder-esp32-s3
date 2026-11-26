import SwiftUI

enum Studio {
    static let background = rgb(0x111110)
    static let panel = rgb(0x242421)
    static let hero = rgb(0x34342e)
    static let line = rgb(0x474740)
    static let ink = rgb(0xF0EEE6)
    static let muted = rgb(0xC0BDB1)
    static let accent = rgb(0xECE8D9)
    static let card = rgb(0x171715)
    static let cardInk = rgb(0xF3F1EA)
    static let cardMuted = rgb(0xC8C6BA)
    static let live = rgb(0xFF9C83)
    static let paper = rgb(0xF0EEE6)
    static let paperInk = rgb(0x1E2829)
    static let paperAccent = rgb(0x80501F)
    static let paperSelection = rgb(0xF4DFC1)
    static let paperWarning = rgb(0x79521B)

    private static func rgb(_ hex: Int) -> Color {
        Color(.sRGB, red: Double(hex >> 16) / 255, green: Double((hex >> 8) & 255) / 255,
              blue: Double(hex & 255) / 255)
    }
}

struct DeskGlass: ViewModifier {
    let radius: CGFloat
    var tint: Color?
    var interactive = false
    @Environment(\.accessibilityReduceTransparency) private var opaque
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @ViewBuilder func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        if opaque {
            content.background(tint ?? Studio.panel, in: shape)
                .overlay { shape.strokeBorder(Studio.line).allowsHitTesting(false) }
        } else {
            #if compiler(>=6.2)
            if #available(iOS 26.0, *) {
                let glass = tint.map { Glass.regular.tint($0) } ?? .regular
                content.glassEffect(glass.interactive(interactive && !reduceMotion), in: shape)
            } else {
                frosted(content, in: shape)
            }
            #else
            frosted(content, in: shape)
            #endif
        }
    }

    private func frosted(_ content: Content, in shape: RoundedRectangle) -> some View {
        content
            .background((tint ?? Studio.panel).opacity(tint == nil ? 0.56 : 0.92), in: shape)
            .background(.thinMaterial, in: shape)
            .overlay {
                shape.strokeBorder(LinearGradient(colors: [.white.opacity(0.36), .white.opacity(0.07), .white.opacity(0.16)],
                                                  startPoint: .topLeading, endPoint: .bottomTrailing))
                    .allowsHitTesting(false)
            }
    }
}
