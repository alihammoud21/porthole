import CoreGraphics
import Foundation
import GameController
import os

/// Merges touch overlay, MFi controller, and hardware keyboard into the single
/// `ph_input` a runtime sees.
///
/// The indirection is what makes layouts portable: a control binds to an *action*
/// name, the router maps actions onto the abstract buttons and axes in the ABI, and
/// the runtime adapter maps those onto whatever the engine actually wants. Change
/// any one layer without touching the others.
final class InputRouter {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "input")

    /// Actions a layout can bind to. The raw values are exactly the strings that
    /// appear in `layouts/*.toml`.
    enum Action: String {
        // Movement — these resolve to axes, not buttons, so a d-pad and a stick
        // feed the same place.
        case forward, back
        case strafeLeft = "strafe_left"
        case strafeRight = "strafe_right"
        case turnLeft = "turn_left"
        case turnRight = "turn_right"
        case walk, look
        case slideLeft = "slide_left"
        case slideRight = "slide_right"
        case slideUp = "slide_up"
        case slideDown = "slide_down"
        case pitchYaw = "pitch_yaw"
        case roll, throttle

        // Buttons
        case attack, use, jump, activate, action, fire
        case firePrimary = "fire_primary"
        case fireSecondary = "fire_secondary"
        case afterburner
        case readyMagic = "ready_magic"
        case inventory, spellbook, journal, map, menu, automap, start, select
        case l1, r1, l2, r2
        case weaponCycle = "weapon_cycle"
        case cycleItem = "cycle_item"
        case belt1 = "belt_1"
        case belt2 = "belt_2"
        case strafeModifier = "strafe_modifier"
        case walkModifier = "walk_modifier"
        case lookModifier = "look_modifier"
        case toggleKeyboard = "toggle_keyboard"
        case shellMenu = "shell_menu"
        case zoom, scroll

        // Pointer
        case mouse
        case mouseLeft = "mouse_left"
        case mouseRight = "mouse_right"
        case mouseLeftHold = "mouse_left_hold"

        // Composite — resolved by the control, not bound directly
        case dpad, face

        case castSpell = "cast_spell"
    }

    /// Where an action lands in the ABI.
    private enum Target {
        case button(ph_button)
        case axis(ph_axis, Float)      // axis plus the sign this action contributes
        case pointerButton(UInt8)
        case pointerMove
        case shell(ShellAction)        // handled by the shell, never reaches the runtime
        case ignored
    }

    enum ShellAction {
        case toggleKeyboard
        case shellMenu
        case modeToggle
        case mode(String)
    }

    /// The table. Deliberately explicit rather than clever: an unmapped action should
    /// be a visible omission, not a silent fallthrough.
    private static let targets: [Action: Target] = [
        .forward: .axis(PH_AXIS_LEFT_Y, -1),
        .back: .axis(PH_AXIS_LEFT_Y, 1),
        .strafeLeft: .axis(PH_AXIS_LEFT_X, -1),
        .strafeRight: .axis(PH_AXIS_LEFT_X, 1),
        .slideLeft: .axis(PH_AXIS_LEFT_X, -1),
        .slideRight: .axis(PH_AXIS_LEFT_X, 1),
        .slideUp: .axis(PH_AXIS_LEFT_Y, -1),
        .slideDown: .axis(PH_AXIS_LEFT_Y, 1),
        .turnLeft: .axis(PH_AXIS_RIGHT_X, -1),
        .turnRight: .axis(PH_AXIS_RIGHT_X, 1),
        .look: .pointerMove,
        .pitchYaw: .pointerMove,
        .mouse: .pointerMove,

        .attack: .button(PH_BTN_A),
        .fire: .button(PH_BTN_A),
        .firePrimary: .button(PH_BTN_A),
        .action: .button(PH_BTN_A),
        .jump: .button(PH_BTN_B),
        .use: .button(PH_BTN_X),
        .activate: .button(PH_BTN_X),
        .fireSecondary: .button(PH_BTN_Y),
        .readyMagic: .button(PH_BTN_Y),
        .castSpell: .button(PH_BTN_Y),
        .afterburner: .button(PH_BTN_R2),

        .l1: .button(PH_BTN_L1),
        .r1: .button(PH_BTN_R1),
        .l2: .button(PH_BTN_L2),
        .r2: .button(PH_BTN_R2),
        .weaponCycle: .button(PH_BTN_R1),
        .cycleItem: .button(PH_BTN_R1),
        .strafeModifier: .button(PH_BTN_L1),
        .walkModifier: .button(PH_BTN_L2),
        .lookModifier: .button(PH_BTN_L1),
        .walk: .button(PH_BTN_L2),

        .start: .button(PH_BTN_START),
        .menu: .button(PH_BTN_START),
        .select: .button(PH_BTN_SELECT),
        .inventory: .button(PH_BTN_SELECT),
        .spellbook: .button(PH_BTN_Y),
        .journal: .button(PH_BTN_SELECT),
        .map: .button(PH_BTN_SELECT),
        .automap: .button(PH_BTN_SELECT),
        .belt1: .button(PH_BTN_L1),
        .belt2: .button(PH_BTN_R1),

        .mouseLeft: .pointerButton(0),
        .mouseLeftHold: .pointerButton(0),
        .mouseRight: .pointerButton(1),

        .toggleKeyboard: .shell(.toggleKeyboard),
        .shellMenu: .shell(.shellMenu),

        // Host-side concerns the runtime never needs to know about.
        .zoom: .ignored,
        .scroll: .ignored,
        .throttle: .ignored,
        .roll: .ignored,
        .dpad: .ignored,
        .face: .ignored,
    ]

    // MARK: - Accumulated state for the current frame

    private var buttons: UInt32 = 0
    private var axes = [Float](repeating: 0, count: Int(PH_AXIS_COUNT.rawValue))
    private var pointerButtons: UInt8 = 0
    private var pointerActive = false
    private var pointerPosition = CGPoint.zero
    private var pointerDelta = CGPoint.zero
    /// Stable storage for the keyboard array handed to C. An Array's buffer pointer
    /// is only valid inside `withUnsafeBufferPointer`, and `ph_input.keys` outlives
    /// that closure, so the router owns this memory outright.
    private var keyStorage = UnsafeMutableBufferPointer<UInt16>.allocate(capacity: 16)
    private var keyCount = 0

    /// Framebuffer geometry, needed to convert a touch in view space into the
    /// runtime's own pixel coordinates.
    var contentSize = CGSize(width: 640, height: 360)
    var contentRect = CGRect(x: 0, y: 0, width: 640, height: 360)

    /// Pending shell actions, drained by the session each frame.
    private(set) var shellActions: [ShellAction] = []

    private var warnedAbout = Set<String>()
    private let start = DispatchTime.now()

    // MARK: - Input from the overlay

    func clearTransient() {
        pointerDelta = .zero
        shellActions.removeAll(keepingCapacity: true)
    }

    func reset() {
        buttons = 0
        for i in axes.indices { axes[i] = 0 }
        pointerButtons = 0
        pointerActive = false
        pointerDelta = .zero
    }

    /// A control was pressed or released. `value` is 0...1 so a stick and a button
    /// can share this path.
    func apply(bind: Bind?, value: Float, pressed: Bool) {
        guard let bind else { return }
        switch bind {
        case .action(let name):
            apply(actionName: name, value: value, pressed: pressed)
        case .directions(let map):
            // A direction map is applied by `apply(stick:)` / `apply(dpad:)`; a bare
            // press on one has no meaning.
            _ = map
        }
    }

    func apply(actionName: String, value: Float, pressed: Bool) {
        // Mode switches are spelled `mode:cursor` / `mode:toggle` in layouts.
        if actionName.hasPrefix("mode:") {
            guard pressed else { return }
            let mode = String(actionName.dropFirst(5))
            shellActions.append(mode == "toggle" ? .modeToggle : .mode(mode))
            return
        }

        guard let action = Action(rawValue: actionName) else {
            warnOnce(actionName)
            return
        }
        guard let target = Self.targets[action] else {
            warnOnce(actionName)
            return
        }

        switch target {
        case .button(let b):
            if pressed { buttons |= (1 << UInt32(b.rawValue)) }
            else { buttons &= ~(1 << UInt32(b.rawValue)) }

        case .axis(let a, let sign):
            let i = Int(a.rawValue)
            // Accumulate so opposing bindings (forward + back held together) cancel
            // rather than fighting over the slot.
            axes[i] = max(-1, min(1, axes[i] + (pressed ? sign * value : 0)))

        case .pointerButton(let bit):
            if pressed { pointerButtons |= (1 << bit) }
            else { pointerButtons &= ~(1 << bit) }

        case .pointerMove, .ignored:
            break

        case .shell(let s):
            if pressed { shellActions.append(s) }
        }
    }

    /// A two-axis control (stick or 8-way d-pad) with a direction-keyed binding.
    func apply(vector: CGPoint, bind: Bind?, deadzone: Float = 0.12) {
        guard let bind else { return }

        var x = Float(vector.x)
        var y = Float(vector.y)
        let magnitude = (x * x + y * y).squareRoot()
        if magnitude < deadzone {
            x = 0
            y = 0
        } else if magnitude > 1 {
            x /= magnitude
            y /= magnitude
        }

        switch bind {
        case .action:
            // A stick bound to a single action drives the left stick.
            axes[Int(PH_AXIS_LEFT_X.rawValue)] = x
            axes[Int(PH_AXIS_LEFT_Y.rawValue)] = y

        case .directions:
            // Resolve each half-axis through its own action, so `turn_left` can land
            // on a different axis from `strafe_left`.
            applyHalfAxis(bind.direction("left"), magnitude: max(0, -x))
            applyHalfAxis(bind.direction("right"), magnitude: max(0, x))
            applyHalfAxis(bind.direction("up"), magnitude: max(0, -y))
            applyHalfAxis(bind.direction("down"), magnitude: max(0, y))
        }
    }

    private func applyHalfAxis(_ name: String?, magnitude: Float) {
        guard let name, magnitude > 0 else { return }
        guard let action = Action(rawValue: name),
              let target = Self.targets[action] else {
            warnOnce(name)
            return
        }
        switch target {
        case .axis(let a, let sign):
            let i = Int(a.rawValue)
            axes[i] = max(-1, min(1, axes[i] + sign * magnitude))
        case .button(let b):
            if magnitude > 0.5 { buttons |= (1 << UInt32(b.rawValue)) }
        default:
            break
        }
    }

    /// Absolute pointer: a direct-touch layout reporting where the finger is, in
    /// view coordinates.
    func setPointer(viewPoint: CGPoint, active: Bool) {
        pointerActive = active
        guard contentRect.width > 0, contentRect.height > 0 else { return }
        let nx = (viewPoint.x - contentRect.minX) / contentRect.width
        let ny = (viewPoint.y - contentRect.minY) / contentRect.height
        pointerPosition = CGPoint(
            x: max(0, min(contentSize.width - 1, nx * contentSize.width)),
            y: max(0, min(contentSize.height - 1, ny * contentSize.height)))
    }

    /// Relative pointer: a trackpad or mouse-look layout reporting movement.
    func movePointer(by delta: CGPoint, sensitivity: CGFloat) {
        let scale = contentRect.width > 0 ? contentSize.width / contentRect.width : 1
        let dx = delta.x * sensitivity * scale
        let dy = delta.y * sensitivity * scale
        pointerDelta.x += dx
        pointerDelta.y += dy
        pointerPosition.x = max(0, min(contentSize.width - 1, pointerPosition.x + dx))
        pointerPosition.y = max(0, min(contentSize.height - 1, pointerPosition.y + dy))
        pointerActive = false      // relative mode: the runtime integrates deltas
    }

    // MARK: - MFi controllers

    /// Poll the connected controller, if any. Called once per frame rather than using
    /// callbacks, so controller and touch state are sampled at the same instant.
    func pollController() {
        guard let pad = GCController.current?.extendedGamepad else { return }

        func set(_ b: ph_button, _ pressed: Bool) {
            if pressed { buttons |= (1 << UInt32(b.rawValue)) }
        }

        set(PH_BTN_A, pad.buttonA.isPressed)
        set(PH_BTN_B, pad.buttonB.isPressed)
        set(PH_BTN_X, pad.buttonX.isPressed)
        set(PH_BTN_Y, pad.buttonY.isPressed)
        set(PH_BTN_L1, pad.leftShoulder.isPressed)
        set(PH_BTN_R1, pad.rightShoulder.isPressed)
        set(PH_BTN_L2, pad.leftTrigger.isPressed)
        set(PH_BTN_R2, pad.rightTrigger.isPressed)
        set(PH_BTN_UP, pad.dpad.up.isPressed)
        set(PH_BTN_DOWN, pad.dpad.down.isPressed)
        set(PH_BTN_LEFT, pad.dpad.left.isPressed)
        set(PH_BTN_RIGHT, pad.dpad.right.isPressed)
        set(PH_BTN_START, pad.buttonMenu.isPressed)
        if let options = pad.buttonOptions {
            set(PH_BTN_SELECT, options.isPressed)
        }

        // Controller sticks win over touch when both move, because a physical stick
        // is always the more deliberate input.
        let lx = pad.leftThumbstick.xAxis.value
        let ly = pad.leftThumbstick.yAxis.value
        let rx = pad.rightThumbstick.xAxis.value
        let ry = pad.rightThumbstick.yAxis.value
        if abs(lx) > 0.05 { axes[Int(PH_AXIS_LEFT_X.rawValue)] = lx }
        // GameController reports Y up-positive; the ABI uses screen conventions.
        if abs(ly) > 0.05 { axes[Int(PH_AXIS_LEFT_Y.rawValue)] = -ly }
        if abs(rx) > 0.05 { axes[Int(PH_AXIS_RIGHT_X.rawValue)] = rx }
        if abs(ry) > 0.05 { axes[Int(PH_AXIS_RIGHT_Y.rawValue)] = -ry }
    }

    static var isControllerConnected: Bool {
        GCController.current?.extendedGamepad != nil
    }

    // MARK: - Snapshot

    /// Build the `ph_input` for this frame. The keys array is held by the router so
    /// the pointer handed to C stays valid for the duration of the frame call.
    func snapshot() -> ph_input {
        let elapsed = DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds
        return ph_input(
            buttons: buttons,
            axes: (axes[0], axes[1], axes[2], axes[3]),
            pointer_active: pointerActive,
            pointer_x: Int32(pointerPosition.x),
            pointer_y: Int32(pointerPosition.y),
            pointer_dx: Int32(pointerDelta.x),
            pointer_dy: Int32(pointerDelta.y),
            pointer_buttons: pointerButtons,
            keys: keyCount > 0 ? UnsafePointer(keyStorage.baseAddress) : nil,
            key_count: keyCount,
            time_us: elapsed / 1000
        )
    }

    /// Replace the pressed-key set. HID usage codes, which is what both UIKey and
    /// SDL ultimately speak.
    func setPressedKeys(_ keys: [UInt16]) {
        keyCount = min(keys.count, keyStorage.count)
        for i in 0..<keyCount { keyStorage[i] = keys[i] }
    }

    deinit {
        keyStorage.deallocate()
    }

    private func warnOnce(_ name: String) {
        guard !warnedAbout.contains(name) else { return }
        warnedAbout.insert(name)
        Self.log.warning("layout binds unknown action '\(name, privacy: .public)'")
    }
}
