import CoreGraphics
import UIKit

/// Draws a layout's controls and turns touches into router input.
///
/// This is UIKit rather than SwiftUI on purpose. Games need many simultaneous
/// touches tracked individually and identified across frames, and
/// `touchesBegan/Moved/Ended` with `UITouch` identity is the only API that does that
/// cleanly. SwiftUI's gesture system actively fights it.
final class TouchOverlayView: UIView {

    private let router: InputRouter
    private var layout: Layout
    private var mode = "world"

    /// Which control each live touch is driving, by `UITouch` identity.
    private var assignments: [ObjectIdentifier: Assignment] = [:]

    private struct Assignment {
        let control: Control
        let index: Int
        /// For sticks: where the centre is. With `recenter`, that's where the finger
        /// first landed rather than the control's drawn centre — which is what makes
        /// a virtual stick feel acceptable instead of merely present.
        var origin: CGPoint
        /// For relative pointers: the previous position, to compute a delta.
        var lastPoint: CGPoint
        /// Live visual state, 0...1 for buttons, a vector for sticks.
        var value: CGPoint = .zero
        var pressed = false
    }

    private let lightHaptic = UIImpactFeedbackGenerator(style: .light)
    private let mediumHaptic = UIImpactFeedbackGenerator(style: .medium)

    /// Set by the session so touches in the game area can be mapped to framebuffer
    /// coordinates.
    var contentRect: CGRect = .zero

    init(layout: Layout, router: InputRouter) {
        self.layout = layout
        self.router = router
        super.init(frame: .zero)
        backgroundColor = .clear
        isMultipleTouchEnabled = true
        isOpaque = false
        lightHaptic.prepare()
        mediumHaptic.prepare()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    // MARK: - Layout changes

    func setLayout(_ new: Layout) {
        layout = new
        releaseAll()
        setNeedsDisplay()
    }

    func setMode(_ new: String) {
        guard layout.modal, new != mode else { return }
        mode = new
        releaseAll()
        setNeedsDisplay()
    }

    func toggleMode() {
        setMode(mode == "world" ? "cursor" : "world")
    }

    /// Hide the overlay when a controller is connected, if the layout asks for it.
    func controllerConnectionChanged() {
        let hide = layout.autohideOnController && InputRouter.isControllerConnected
        isHidden = hide
        if hide { releaseAll() }
    }

    private func releaseAll() {
        for (_, a) in assignments {
            router.apply(bind: a.control.bind, value: 0, pressed: false)
        }
        assignments.removeAll()
        router.reset()
    }

    // MARK: - Geometry

    private var activeControls: [(offset: Int, element: Control)] {
        Array(layout.controls(inMode: mode).enumerated())
    }

    private var contentBounds: CGRect {
        layout.safeArea ? bounds.inset(by: safeAreaInsets) : bounds
    }

    /// Hit test in reverse draw order, so a control drawn on top wins.
    private func control(at point: CGPoint) -> (Control, Int)? {
        let b = contentBounds
        for (i, c) in activeControls.reversed() {
            guard c.isVisible else { continue }
            // Generous: touch targets extend past the drawn shape, because a finger
            // that lands 4 points outside a button meant to press it.
            if c.frame(in: b).insetBy(dx: -8, dy: -8).contains(point) {
                return (c, i)
            }
        }
        return nil
    }

    /// The pointer control covering a point, if any. Pointer regions are the
    /// background: they only claim a touch no other control wanted.
    private func pointerControl(at point: CGPoint) -> (Control, Int)? {
        let b = contentBounds
        for (i, c) in activeControls where c.kind == .pointer {
            let region: CGRect
            switch c.region {
            case "right-half":
                region = CGRect(x: b.midX, y: b.minY, width: b.width / 2, height: b.height)
            case "left-half":
                region = CGRect(x: b.minX, y: b.minY, width: b.width / 2, height: b.height)
            case "upper-two-thirds":
                region = CGRect(x: b.minX, y: b.minY, width: b.width, height: b.height * 2 / 3)
            default:
                region = b
            }
            if region.contains(point) { return (c, i) }
        }
        return nil
    }

    // MARK: - Touch handling

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            let p = touch.location(in: self)
            let key = ObjectIdentifier(touch)

            if let (c, i) = control(at: p) {
                var a = Assignment(
                    control: c, index: i,
                    origin: c.recenter == true ? p : c.frame(in: contentBounds).center,
                    lastPoint: p)
                a.pressed = true

                switch c.kind {
                case .button, .buttonCluster:
                    router.apply(bind: c.bind, value: 1, pressed: true)
                    fire(haptic: c.haptic)
                case .stick, .dpad:
                    update(assignment: &a, to: p)
                case .slider:
                    router.apply(bind: c.bind, value: 1, pressed: true)
                    fire(haptic: c.haptic)
                default:
                    break
                }
                assignments[key] = a
                setNeedsDisplay()
                continue
            }

            // Nothing claimed it, so it belongs to a pointer region or to the game.
            if let (c, i) = pointerControl(at: p) {
                var a = Assignment(control: c, index: i, origin: p, lastPoint: p)
                a.pressed = true
                if c.mode == "absolute" {
                    router.setPointer(viewPoint: p, active: true)
                }
                assignments[key] = a
            }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            let key = ObjectIdentifier(touch)
            guard var a = assignments[key] else { continue }
            let p = touch.location(in: self)

            switch a.control.kind {
            case .stick, .dpad:
                update(assignment: &a, to: p)
                setNeedsDisplay()

            case .pointer:
                if a.control.mode == "absolute" {
                    router.setPointer(viewPoint: p, active: true)
                } else {
                    let delta = CGPoint(x: p.x - a.lastPoint.x, y: p.y - a.lastPoint.y)
                    router.movePointer(
                        by: delta,
                        sensitivity: CGFloat(a.control.sensitivity ?? 1.0))
                }

            case .button, .buttonCluster:
                // Sticky: a finger that slides off a button keeps it held. Releasing
                // on slide-off makes action games miserable.
                break

            case .slider:
                break

            default:
                break
            }

            a.lastPoint = p
            assignments[key] = a
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        endTouches(touches)
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        endTouches(touches)
    }

    private func endTouches(_ touches: Set<UITouch>) {
        for touch in touches {
            let key = ObjectIdentifier(touch)
            guard let a = assignments.removeValue(forKey: key) else { continue }

            switch a.control.kind {
            case .stick, .dpad:
                router.apply(vector: .zero, bind: a.control.bind)
            case .pointer:
                if a.control.mode == "absolute" {
                    router.setPointer(viewPoint: a.lastPoint, active: false)
                }
            default:
                router.apply(bind: a.control.bind, value: 0, pressed: false)
            }
            setNeedsDisplay()
        }
    }

    private func update(assignment a: inout Assignment, to point: CGPoint) {
        let radius = CGFloat(a.control.size ?? 140) / 2
        guard radius > 0 else { return }

        var v = CGPoint(
            x: (point.x - a.origin.x) / radius,
            y: (point.y - a.origin.y) / radius)

        if a.control.kind == .dpad {
            // Snap to 8 or 4 directions.
            let allowDiagonals = a.control.diagonals ?? true
            v = Self.snap(v, diagonals: allowDiagonals)
        }

        a.value = v
        router.apply(
            vector: v,
            bind: a.control.bind,
            deadzone: Float(a.control.deadzone ?? 0.12))
    }

    /// Snap a vector to the nearest d-pad direction.
    static func snap(_ v: CGPoint, diagonals: Bool) -> CGPoint {
        let magnitude = (v.x * v.x + v.y * v.y).squareRoot()
        guard magnitude > 0.25 else { return .zero }

        let step = diagonals ? CGFloat.pi / 4 : CGFloat.pi / 2
        let angle = atan2(v.y, v.x)
        let snapped = (angle / step).rounded() * step
        return CGPoint(x: cos(snapped), y: sin(snapped))
    }

    private func fire(haptic: String?) {
        switch haptic {
        case "medium": mediumHaptic.impactOccurred()
        case "light": lightHaptic.impactOccurred()
        default: break
        }
    }

    // MARK: - Drawing

    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        let b = contentBounds

        // Live values keyed by control index, so a pressed button draws differently.
        var live: [Int: Assignment] = [:]
        for (_, a) in assignments { live[a.index] = a }

        for (i, c) in activeControls {
            guard c.isVisible else { continue }
            let frame = c.frame(in: b)
            let alpha = CGFloat(c.opacity ?? 0.3)
            let a = live[i]

            switch c.kind {
            case .stick:
                drawStick(ctx, frame: frame, alpha: alpha, assignment: a)
            case .dpad:
                drawDpad(ctx, frame: frame, alpha: alpha, assignment: a)
            case .button, .buttonCluster:
                drawButton(ctx, frame: frame, alpha: alpha,
                           pressed: a?.pressed ?? false, label: c.id)
            case .slider:
                drawSlider(ctx, frame: frame, alpha: alpha,
                           segmented: c.style == "segmented")
            case .keystrip:
                drawKeystrip(ctx, frame: b, alpha: alpha, keys: c.keys ?? [])
            default:
                break
            }
        }
    }

    private func drawStick(_ ctx: CGContext, frame: CGRect, alpha: CGFloat,
                           assignment: Assignment?) {
        ctx.setFillColor(UIColor.white.withAlphaComponent(alpha * 0.5).cgColor)
        ctx.fillEllipse(in: frame)

        ctx.setStrokeColor(UIColor.white.withAlphaComponent(alpha * 1.4).cgColor)
        ctx.setLineWidth(2)
        ctx.strokeEllipse(in: frame.insetBy(dx: 1, dy: 1))

        // The thumb, offset by the live vector.
        let v = assignment?.value ?? .zero
        let clamped = Self.clampToUnitCircle(v)
        let thumbSize = frame.width * 0.42
        let centre = frame.center
        let thumb = CGRect(
            x: centre.x + clamped.x * (frame.width / 2 - thumbSize / 2) - thumbSize / 2,
            y: centre.y + clamped.y * (frame.height / 2 - thumbSize / 2) - thumbSize / 2,
            width: thumbSize, height: thumbSize)
        ctx.setFillColor(UIColor.white.withAlphaComponent(alpha * 2.0).cgColor)
        ctx.fillEllipse(in: thumb)
    }

    private func drawDpad(_ ctx: CGContext, frame: CGRect, alpha: CGFloat,
                          assignment: Assignment?) {
        let arm = frame.width / 3
        let v = assignment?.value ?? .zero

        func segment(_ r: CGRect, lit: Bool) {
            ctx.setFillColor(UIColor.white
                .withAlphaComponent(alpha * (lit ? 2.2 : 0.55)).cgColor)
            ctx.fill(r)
        }

        segment(CGRect(x: frame.minX + arm, y: frame.minY, width: arm, height: arm),
                lit: v.y < -0.3)
        segment(CGRect(x: frame.minX + arm, y: frame.maxY - arm, width: arm, height: arm),
                lit: v.y > 0.3)
        segment(CGRect(x: frame.minX, y: frame.minY + arm, width: arm, height: arm),
                lit: v.x < -0.3)
        segment(CGRect(x: frame.maxX - arm, y: frame.minY + arm, width: arm, height: arm),
                lit: v.x > 0.3)
        segment(CGRect(x: frame.minX + arm, y: frame.minY + arm, width: arm, height: arm),
                lit: false)
    }

    private func drawButton(_ ctx: CGContext, frame: CGRect, alpha: CGFloat,
                            pressed: Bool, label: String?) {
        ctx.setFillColor(UIColor.white
            .withAlphaComponent(alpha * (pressed ? 2.4 : 1.0)).cgColor)
        ctx.fillEllipse(in: frame)
        ctx.setStrokeColor(UIColor.white.withAlphaComponent(alpha * 1.6).cgColor)
        ctx.setLineWidth(1.5)
        ctx.strokeEllipse(in: frame.insetBy(dx: 0.75, dy: 0.75))

        guard let label, !label.isEmpty else { return }
        let text = String(label.prefix(4)).uppercased()
        let attrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: max(9, frame.width * 0.22), weight: .semibold),
            .foregroundColor: UIColor.black.withAlphaComponent(0.55),
        ]
        let size = (text as NSString).size(withAttributes: attrs)
        (text as NSString).draw(
            at: CGPoint(x: frame.midX - size.width / 2, y: frame.midY - size.height / 2),
            withAttributes: attrs)
    }

    private func drawSlider(_ ctx: CGContext, frame: CGRect, alpha: CGFloat,
                            segmented: Bool) {
        let track = frame.insetBy(dx: 0, dy: frame.height * 0.35)
        ctx.setFillColor(UIColor.white.withAlphaComponent(alpha).cgColor)

        guard segmented else {
            ctx.fill(track)
            return
        }
        let count = 8
        let gap: CGFloat = 3
        let w = (track.width - gap * CGFloat(count - 1)) / CGFloat(count)
        for i in 0..<count {
            ctx.fill(CGRect(x: track.minX + CGFloat(i) * (w + gap),
                            y: track.minY, width: w, height: track.height))
        }
    }

    private func drawKeystrip(_ ctx: CGContext, frame: CGRect, alpha: CGFloat,
                              keys: [[String]]) {
        guard !keys.isEmpty else { return }
        let rowHeight: CGFloat = 40
        let gap: CGFloat = 4
        let totalHeight = CGFloat(keys.count) * rowHeight + CGFloat(keys.count - 1) * gap
        var y = frame.maxY - totalHeight - 14

        for row in keys {
            guard !row.isEmpty else { continue }
            let w = (frame.width - 24 - gap * CGFloat(row.count - 1)) / CGFloat(row.count)
            var x = frame.minX + 12
            for key in row {
                let r = CGRect(x: x, y: y, width: w, height: rowHeight)
                ctx.setFillColor(UIColor.white.withAlphaComponent(alpha).cgColor)
                let path = UIBezierPath(roundedRect: r, cornerRadius: 6)
                ctx.addPath(path.cgPath)
                ctx.fillPath()

                let attrs: [NSAttributedString.Key: Any] = [
                    .font: UIFont.systemFont(ofSize: 11, weight: .medium),
                    .foregroundColor: UIColor.black.withAlphaComponent(0.6),
                ]
                let size = (key as NSString).size(withAttributes: attrs)
                (key as NSString).draw(
                    at: CGPoint(x: r.midX - size.width / 2, y: r.midY - size.height / 2),
                    withAttributes: attrs)
                x += w + gap
            }
            y += rowHeight + gap
        }
    }

    static func clampToUnitCircle(_ v: CGPoint) -> CGPoint {
        let m = (v.x * v.x + v.y * v.y).squareRoot()
        return m > 1 ? CGPoint(x: v.x / m, y: v.y / m) : v
    }
}

extension CGRect {
    var center: CGPoint { CGPoint(x: midX, y: midY) }
}
