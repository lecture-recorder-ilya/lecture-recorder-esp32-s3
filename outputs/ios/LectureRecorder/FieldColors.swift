import SwiftUI

enum Studio {
    static let background = rgb(0x0C1216)
    static let panel = rgb(0x182126)
    static let hero = rgb(0x28383a)
    static let line = rgb(0x354449)
    static let ink = rgb(0xEEF2F0)
    static let muted = rgb(0xAEBEBD)
    static let accent = rgb(0xFFBE75)
    static let card = rgb(0x10191c)
    static let cardInk = rgb(0xF3F5F2)
    static let cardMuted = rgb(0xBFD1D0)
    static let live = rgb(0xFF9E83)
    static let paper = rgb(0xEEF2F0)
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
