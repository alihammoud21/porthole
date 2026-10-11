import CoreGraphics
import Foundation

/// A touch control layout.
///
/// Layouts are authored as TOML in `layouts/` and compiled to JSON by
/// `porthole build`. The shell reads the JSON, which is why there is no TOML parser
/// here — the shell commits to zero third-party dependencies, and Codable is free.
struct Layout: Codable {
    var schema: Int
    var id: String
    var name: String
    var description: String?
    var safeArea: Bool
    var autohideOnController: Bool
    var modal: Bool
    var controls: [Control]
    var tuning: [String: String]

    enum CodingKeys: String, CodingKey {
        case schema, id, name, description, controls, tuning, modal
        case safeArea = "safe_area"
        case autohideOnController = "autohide_on_controller"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schema = try c.decodeIfPresent(Int.self, forKey: .schema) ?? 1
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        description = try c.decodeIfPresent(String.self, forKey: .description)
        safeArea = try c.decodeIfPresent(Bool.self, forKey: .safeArea) ?? true
        autohideOnController =
            try c.decodeIfPresent(Bool.self, forKey: .autohideOnController) ?? true
        modal = try c.decodeIfPresent(Bool.self, forKey: .modal) ?? false
        controls = try c.decodeIfPresent([Control].self, forKey: .controls) ?? []
        tuning = try c.decodeIfPresent([String: String].self, forKey: .tuning) ?? [:]
    }

    /// Controls active in a given mode. Non-modal layouts return everything.
    func controls(inMode mode: String) -> [Control] {
        guard modal else { return controls }
        return controls.filter { $0.activeIn == nil || $0.activeIn == mode }
    }

    static func load(from url: URL) throws -> Layout {
        try JSONDecoder().decode(Layout.self, from: Data(contentsOf: url))
    }
}

enum ControlKind: String, Codable {
    case stick, dpad, button, pointer, slider, gesture, gyro, keystrip
    case buttonCluster = "button-cluster"
}

enum Anchor: String, Codable {
    case topLeft = "top-left"
    case topCenter = "top-center"
    case topRight = "top-right"
    case leftCenter = "left-center"
    case rightCenter = "right-center"
    case bottomLeft = "bottom-left"
    case bottomCenter = "bottom-center"
    case bottomRight = "bottom-right"

    /// Resolve an anchored offset to a rect inside `bounds`.
    ///
    /// Offsets always measure *inward* from the anchor, so one layout survives every
    /// screen size and both orientations without absolute coordinates.
    func frame(offset: CGPoint, size: CGSize, in bounds: CGRect) -> CGRect {
        let x: CGFloat
        let y: CGFloat

        switch self {
        case .topLeft, .leftCenter, .bottomLeft:
            x = bounds.minX + offset.x
        case .topCenter, .bottomCenter:
            x = bounds.midX - size.width / 2 + offset.x
        case .topRight, .rightCenter, .bottomRight:
            x = bounds.maxX - offset.x - size.width
        }

        switch self {
        case .topLeft, .topCenter, .topRight:
            y = bounds.minY + offset.y
        case .leftCenter, .rightCenter:
            y = bounds.midY - size.height / 2 + offset.y
        case .bottomLeft, .bottomCenter, .bottomRight:
            y = bounds.maxY - offset.y - size.height
        }

        return CGRect(x: x, y: y, width: size.width, height: size.height)
    }
}

/// One control. Deliberately a single struct rather than a class hierarchy: layouts
/// are data, the fields are sparse, and `kind` drives a switch in exactly two places
/// (hit testing and drawing).
struct Control: Codable {
    var kind: ControlKind
    var id: String?
    var anchor: Anchor?
    var offset: [Double]?
    var size: Double?
    var length: Double?
    var opacity: Double?
    var deadzone: Double?
    var sensitivity: Double?
    var enabled: Bool?
    var recenter: Bool?
    var haptic: String?
    var style: String?
    var icon: String?
    var mode: String?
    var region: String?
    var showCursor: Bool?
    var diagonals: Bool?
    var arrangement: String?
    var orientation: String?
    var trigger: String?
    var axis: String?
    var activeIn: String?
    var invertY: Bool?
    var keys: [[String]]?

    /// `bind` is either a single action (`bind = "attack"`) or a direction map
    /// (`bind = { up = "forward", ... }`). Both spellings appear across the shipped
    /// layouts, so both decode into the same place.
    var bind: Bind?

    enum CodingKeys: String, CodingKey {
        case kind, id, anchor, offset, size, length, opacity, deadzone, sensitivity
        case enabled, recenter, haptic, style, icon, mode, region, diagonals
        case arrangement, orientation, trigger, axis, bind, keys
        case showCursor = "show_cursor"
        case activeIn = "active_in"
        case invertY = "invert_y"
    }

    var offsetPoint: CGPoint {
        guard let o = offset, o.count >= 2 else { return .zero }
        return CGPoint(x: o[0], y: o[1])
    }

    /// Gestures and gyro have no on-screen presence; neither do disabled controls.
    var isVisible: Bool {
        if enabled == false { return false }
        if kind == .gesture || kind == .gyro { return false }
        return (opacity ?? 1) > 0.01
    }

    func frame(in bounds: CGRect) -> CGRect {
        let side = size ?? 64
        let dimension: CGSize
        switch kind {
        case .slider:
            let len = length ?? 200
            dimension = orientation == "vertical"
                ? CGSize(width: 40, height: len)
                : CGSize(width: len, height: 40)
        default:
            dimension = CGSize(width: side, height: side)
        }
        return (anchor ?? .bottomLeft).frame(
            offset: offsetPoint, size: dimension, in: bounds)
    }
}

/// A binding: one action, or a direction-keyed map of actions.
enum Bind: Codable {
    case action(String)
    case directions([String: String])

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) {
            self = .action(s)
        } else {
            self = .directions(try c.decode([String: String].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .action(let s): try c.encode(s)
        case .directions(let m): try c.encode(m)
        }
    }

    var single: String? {
        if case .action(let s) = self { return s }
        return nil
    }

    func direction(_ key: String) -> String? {
        if case .directions(let m) = self { return m[key] }
        return nil
    }
}
