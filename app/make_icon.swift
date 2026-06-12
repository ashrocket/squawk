// Renders the Squawk app icon (dark squircle + parrot) into an .iconset.
// Run: swift make_icon.swift && iconutil -c icns Squawk.iconset -o Icon.icns
import AppKit

let sizes = [16, 32, 64, 128, 256, 512, 1024]
let dir = URL(fileURLWithPath: "Squawk.iconset")
try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

func render(_ px: Int) -> NSImage {
    let s = CGFloat(px)
    let img = NSImage(size: NSSize(width: s, height: s))
    img.lockFocus()
    let inset = s * 0.05                       // macOS icons float inside the canvas
    let rect = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    let squircle = NSBezierPath(roundedRect: rect, xRadius: s * 0.21, yRadius: s * 0.21)
    NSColor(calibratedRed: 0.078, green: 0.086, blue: 0.102, alpha: 1).setFill()  // #14161a
    squircle.fill()
    NSColor(calibratedRed: 0.498, green: 0.690, blue: 0.412, alpha: 1).setStroke() // #7fb069
    squircle.lineWidth = max(1, s * 0.018)
    squircle.stroke()
    let emoji = "🦜" as NSString
    let font = NSFont.systemFont(ofSize: s * 0.62)
    let attrs: [NSAttributedString.Key: Any] = [.font: font]
    let size = emoji.size(withAttributes: attrs)
    emoji.draw(at: NSPoint(x: (s - size.width) / 2, y: (s - size.height) / 2), withAttributes: attrs)
    img.unlockFocus()
    return img
}

for px in sizes {
    let img = render(px)
    guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { continue }
    if px <= 512 {
        try? png.write(to: dir.appendingPathComponent("icon_\(px)x\(px).png"))
    }
    if px >= 32 {
        try? png.write(to: dir.appendingPathComponent("icon_\(px / 2)x\(px / 2)@2x.png"))
    }
}
print("wrote Squawk.iconset")
