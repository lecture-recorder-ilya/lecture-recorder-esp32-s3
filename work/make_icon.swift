import Cocoa

let iconset = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)

let ink = NSColor(srgbRed: 15 / 255, green: 23 / 255, blue: 26 / 255, alpha: 1)
let signal = NSColor(srgbRed: 255 / 255, green: 190 / 255, blue: 117 / 255, alpha: 1)

func drawIcon(size: Int, fullBleed: Bool) -> Data {
    let alpha: CGImageAlphaInfo = fullBleed ? .noneSkipLast : .premultipliedLast
    let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                            bytesPerRow: size * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: alpha.rawValue)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
    let scale = CGFloat(size) / 1024
    NSGraphicsContext.current!.cgContext.scaleBy(x: scale, y: scale)
    ink.setFill()
    if fullBleed {
        NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1024, height: 1024)).fill()
    } else {
        NSBezierPath(roundedRect: NSRect(x: 50, y: 50, width: 924, height: 924),
                     xRadius: 210, yRadius: 210).fill()
    }
    context.translateBy(x: -80, y: 0)
    context.concatenate(CGAffineTransform(a: 1, b: 0, c: 0.156, d: 1, tx: 0, ty: 0))
    signal.setFill()
    for (index, height) in [200, 356, 520, 398, 238].enumerated() {
        let bar = NSRect(x: 231 + index * 126, y: (1024 - height) / 2, width: 74, height: height)
        NSBezierPath(roundedRect: bar, xRadius: 37, yRadius: 37).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return NSBitmapImageRep(cgImage: context.makeImage()!).representation(using: .png, properties: [:])!
}

for size in [16, 32, 64, 128, 256, 512, 1024] {
    let png = drawIcon(size: size, fullBleed: false)
    if [16, 32, 128, 256, 512].contains(size) {
        try png.write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    }
    let half = size / 2
    if [16, 32, 128, 256, 512].contains(half) {
        try png.write(to: iconset.appendingPathComponent("icon_\(half)x\(half)@2x.png"))
    }
    if size == 1024 {
        try png.write(to: URL(fileURLWithPath: "outputs/recorder-icon.png"))
    }
}
if CommandLine.arguments.count > 2 {
    try drawIcon(size: 1024, fullBleed: true).write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
}
