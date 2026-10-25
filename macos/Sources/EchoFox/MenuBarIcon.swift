// The fox of the menu bar: its face alone when idle, and with a large white headset, outlined in dark, while it
// records (an earpiece with a red center), records Ultra Private (a shield with a keyhole) or waits for the text (an
// open ring turning on the earpiece). The drawing is the approved one (macos/art/README.md): 26 × 24 pt, the
// geometry in points of that box, the origin at its bottom left. AppKit only, so that a check can compile it alone.
import AppKit

enum MenuBarIcon {
    enum Kind { case idle, recording, ultraPrivate, processing }

    static let size = NSSize(width: 26, height: 24)

    /// The image for the menu bar: idle is a template (the system tints it); the others carry their own white and red,
    /// so the face is black on a light menu bar and white on a dark one. `phase`: the processing ring's start, degrees.
    static func image(_ kind: Kind, dark: Bool, phase: CGFloat = 0) -> NSImage {
        let image = NSImage(size: size)
        // Bitmaps of each scale, not a drawing handler: the face's cutouts would cut the menu bar itself
        for scale in 1...3 {
            let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width) * scale,
                                       pixelsHigh: Int(size.height) * scale, bitsPerSample: 8, samplesPerPixel: 4,
                                       hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0,
                                       bitsPerPixel: 0)!
            rep.size = size
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
            draw(kind, in: NSRect(x: 0, y: 1, width: 25, height: 23),
                 face: kind == .idle || !dark ? .black : .white, phase: phase)
            NSGraphicsContext.restoreGraphicsState()
            image.addRepresentation(rep)
        }
        image.isTemplate = kind == .idle
        return image
    }

    private static func path(_ points: [NSPoint], close: Bool = true) -> NSBezierPath {
        let p = NSBezierPath()
        p.move(to: points[0])
        for point in points.dropFirst() { p.line(to: point) }
        if close { p.close() }
        return p
    }

    private static func draw(_ kind: Kind, in rect: NSRect, face: NSColor, phase: CGFloat) {
        let context = NSGraphicsContext.current!
        NSGraphicsContext.saveGraphicsState()
        let t = NSAffineTransform(transform: AffineTransform(translationByX: rect.minX, byY: rect.minY))
        t.scaleX(by: rect.width / 26, yBy: rect.height / 24)
        t.concat()

        // The face, then its ears, eyes and muzzle cut out of it, then the pupils and the nose
        face.setFill()
        path([NSPoint(x: 4, y: 9), NSPoint(x: 3, y: 22), NSPoint(x: 10, y: 18), NSPoint(x: 16, y: 18),
              NSPoint(x: 23, y: 22), NSPoint(x: 22, y: 9), NSPoint(x: 25, y: 6), NSPoint(x: 18, y: 3),
              NSPoint(x: 13, y: 1), NSPoint(x: 8, y: 3), NSPoint(x: 2, y: 6)]).fill()
        context.compositingOperation = .destinationOut
        NSColor.black.setFill()
        path([NSPoint(x: 5, y: 19), NSPoint(x: 6, y: 13), NSPoint(x: 9, y: 17)]).fill()
        path([NSPoint(x: 21, y: 19), NSPoint(x: 20, y: 13), NSPoint(x: 17, y: 17)]).fill()
        NSBezierPath(ovalIn: NSRect(x: 6, y: 5, width: 6, height: 7)).fill()
        NSBezierPath(ovalIn: NSRect(x: 14, y: 5, width: 6, height: 7)).fill()
        path([NSPoint(x: 5, y: 5), NSPoint(x: 13, y: 0), NSPoint(x: 21, y: 5), NSPoint(x: 17, y: 7),
              NSPoint(x: 9, y: 7)]).fill()
        context.compositingOperation = .sourceOver
        face.setFill()
        NSBezierPath(ovalIn: NSRect(x: 8, y: 6, width: 3, height: 4)).fill()
        NSBezierPath(ovalIn: NSRect(x: 15, y: 6, width: 3, height: 4)).fill()
        NSBezierPath(ovalIn: NSRect(x: 11.5, y: 3, width: 3, height: 2)).fill()

        if kind != .idle {
            let outline = NSColor(calibratedWhite: 0.12, alpha: 1)
            func outlinedLine(_ shape: NSBezierPath, width: CGFloat) {
                shape.lineCapStyle = .round
                shape.lineJoinStyle = .round
                outline.setStroke()
                shape.lineWidth = width + 1.5
                shape.stroke()
                NSColor.white.setStroke()
                shape.lineWidth = width
                shape.stroke()
            }
            func outlinedFill(_ shape: NSBezierPath) {
                NSColor.white.setFill()
                shape.fill()
                outline.setStroke()
                shape.lineWidth = 0.85
                shape.lineJoinStyle = .round
                shape.stroke()
            }
            // The microphone's boom and the headband, then the earpiece: a shield for Ultra Private
            outlinedLine(path([NSPoint(x: 4.2, y: 8), NSPoint(x: 5, y: 4.5), NSPoint(x: 8, y: 2.7),
                               NSPoint(x: 11, y: 2.7)], close: false), width: 2.5)
            outlinedLine(path([NSPoint(x: 4.2, y: 12), NSPoint(x: 5, y: 15.5), NSPoint(x: 7, y: 17.5)], close: false),
                         width: 2.6)
            if kind == .ultraPrivate {
                outlinedFill(path([NSPoint(x: 0.7, y: 15), NSPoint(x: 7.8, y: 15), NSPoint(x: 7.8, y: 9),
                                   NSPoint(x: 6.2, y: 6.8), NSPoint(x: 4.2, y: 5.3), NSPoint(x: 2.2, y: 6.8),
                                   NSPoint(x: 0.7, y: 9)]))
            } else {
                outlinedFill(NSBezierPath(ovalIn: NSRect(x: 0.7, y: 6, width: 7.1, height: 10)))
            }
            outlinedFill(NSBezierPath(roundedRect: NSRect(x: 9, y: 1, width: 4.5, height: 3.4), xRadius: 1.5, yRadius: 1.5))

            // What is on the earpiece
            outline.setStroke()
            outline.setFill()
            switch kind {
            case .ultraPrivate:
                NSBezierPath(ovalIn: NSRect(x: 2.7, y: 10.2, width: 3, height: 3)).fill()
                NSBezierPath(rect: NSRect(x: 3.4, y: 7.8, width: 1.6, height: 3)).fill()
            case .processing:
                let ring = NSBezierPath()
                ring.appendArc(withCenter: NSPoint(x: 4.25, y: 11), radius: 2.1, startAngle: phase,
                               endAngle: phase + 260, clockwise: false)
                ring.lineWidth = 1.5
                ring.lineCapStyle = .round
                ring.stroke()
            default:
                NSColor.systemRed.setFill()
                NSBezierPath(ovalIn: NSRect(x: 2.3, y: 8.5, width: 3.9, height: 5)).fill()
            }
        }
        NSGraphicsContext.restoreGraphicsState()
    }
}
