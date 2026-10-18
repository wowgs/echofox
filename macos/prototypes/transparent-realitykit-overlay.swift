// Run: swiftc -O macos/prototypes/transparent-realitykit-overlay.swift -o /tmp/overlay && /tmp/overlay (quits after 40 s).
// Prototype: a RealityKit scene drawn with a transparent background in a click-through panel over the front window.
import AppKit
import ApplicationServices
import Metal
import QuartzCore
import RealityKit

@MainActor final class Proto {
    let device = MTLCreateSystemDefaultDevice()!
    lazy var queue = device.makeCommandQueue()!
    let layer = CAMetalLayer()
    var renderer: RealityRenderer!
    var panel: NSPanel!
    var model = ModelEntity()
    var t = 0.0
    var timer: Timer?

    func start() throws {
        let frame = Self.targetFrame()
        panel = NSPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let scale = NSScreen.main?.backingScaleFactor ?? 2
        layer.device = device
        layer.pixelFormat = .bgra8Unorm
        layer.isOpaque = false
        layer.framebufferOnly = false
        layer.contentsScale = scale
        layer.drawableSize = CGSize(width: frame.width * scale, height: frame.height * scale)
        let view = NSView(frame: NSRect(origin: .zero, size: frame.size))
        view.layer = layer
        view.wantsLayer = true
        panel.contentView = view
        panel.orderFrontRegardless()

        renderer = try RealityRenderer()
        model = ModelEntity(mesh: .generateBox(size: 0.22, cornerRadius: 0.04),
                            materials: [SimpleMaterial(color: .systemPink, roughness: 0.25, isMetallic: false)])
        let ball = ModelEntity(mesh: .generateSphere(radius: 0.07),
                               materials: [SimpleMaterial(color: .systemTeal, roughness: 0.1, isMetallic: true)])
        ball.position = [0.17, 0.13, 0.05]
        model.addChild(ball)
        let light = DirectionalLight()
        light.light.intensity = 4000
        light.look(at: .zero, from: [0.6, 1.0, 1.2], relativeTo: nil)
        let camera = PerspectiveCamera()
        camera.look(at: .zero, from: [0, 0, 0.75], relativeTo: nil)
        renderer.entities.append(model)
        renderer.entities.append(light)
        renderer.entities.append(camera)
        renderer.activeCamera = camera
        renderer.cameraSettings.colorBackground = .outputTexture()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60, repeats: true) { [weak self] _ in MainActor.assumeIsolated { self?.frame() } }
    }

    func frame() {
        t += 1.0 / 60
        model.transform.rotation = simd_quatf(angle: Float(t), axis: simd_normalize(SIMD3<Float>(0.3, 1, 0.2)))
        model.position = [Float(sin(t * 0.7)) * 0.08, Float(sin(t * 2)) * 0.05, 0]
        guard let drawable = layer.nextDrawable() else { return }
        // Clear to fully transparent ourselves; RealityKit then draws on top (.outputTexture()).
        let pass = MTLRenderPassDescriptor()
        pass.colorAttachments[0].texture = drawable.texture
        pass.colorAttachments[0].loadAction = .clear
        pass.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
        pass.colorAttachments[0].storeAction = .store
        let cb = queue.makeCommandBuffer()!
        cb.makeRenderCommandEncoder(descriptor: pass)!.endEncoding()
        cb.commit()
        cb.waitUntilCompleted()
        do {
            let output = try RealityRenderer.CameraOutput(.singleProjection(colorTexture: drawable.texture))
            nonisolated(unsafe) let d = drawable
            try renderer.updateAndRender(deltaTime: 1.0 / 60, cameraOutput: output, onComplete: { _ in d.present() })
        } catch {
            print("render: \(error)")
        }
    }

    /// The lower right 360 x 360 of the front app's window (Accessibility), else of the main screen.
    static func targetFrame() -> NSRect {
        let size: CGFloat = 360, inset: CGFloat = 12
        let primary = NSScreen.screens.first?.frame.height ?? 900
        if let app = NSWorkspace.shared.frontmostApplication {
            let ax = AXUIElementCreateApplication(app.processIdentifier)
            var w: AnyObject?, p: AnyObject?, s: AnyObject?
            if AXUIElementCopyAttributeValue(ax, "AXFocusedWindow" as CFString, &w) == .success, let win = w,
               AXUIElementCopyAttributeValue(win as! AXUIElement, "AXPosition" as CFString, &p) == .success,
               AXUIElementCopyAttributeValue(win as! AXUIElement, "AXSize" as CFString, &s) == .success {
                var pt = CGPoint.zero, sz = CGSize.zero
                AXValueGetValue(p as! AXValue, .cgPoint, &pt)
                AXValueGetValue(s as! AXValue, .cgSize, &sz)
                let bottom = primary - (pt.y + sz.height)  // Accessibility's y runs down from the top
                print("front window: \(app.localizedName ?? "?") \(Int(sz.width))x\(Int(sz.height))")
                return NSRect(x: pt.x + sz.width - size - inset, y: bottom + inset, width: size, height: size)
            }
        }
        let v = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        return NSRect(x: v.maxX - size - inset, y: v.minY + inset, width: size, height: size)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let proto = MainActor.assumeIsolated { Proto() }
MainActor.assumeIsolated { do { try proto.start() } catch { print("start: \(error)"); exit(1) } }
DispatchQueue.main.asyncAfter(deadline: .now() + 40) { exit(0) }
app.run()
