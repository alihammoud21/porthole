import Foundation

// Decodes every compiled layout with the production model, then checks each visible
// control lands on screen.
//
// Driven by tools/verify-layouts.py, which compiles the TOML, writes the JSON into a
// temporary directory, and runs this from there. The point is to exercise the real
// TOML -> JSON -> Codable path rather than assume it works.
let dir = URL(fileURLWithPath: "layouts")
let files = (try! FileManager.default.contentsOfDirectory(at: dir,
    includingPropertiesForKeys: nil)).filter { $0.pathExtension == "json" }.sorted {
        $0.lastPathComponent < $1.lastPathComponent }

var failures = 0
for file in files {
    do {
        let layout = try Layout.load(from: file)
        let visible = layout.controls.filter { $0.isVisible }.count
        let gestures = layout.controls.filter { $0.kind == .gesture }.count
        let bounds = CGRect(x: 0, y: 0, width: 844, height: 390)   // iPhone 14, landscape

        // Every visible control must land inside the screen.
        var offscreen: [String] = []
        for c in layout.controls where c.isVisible {
            let f = c.frame(in: bounds)
            if !bounds.insetBy(dx: -1, dy: -1).contains(f) {
                offscreen.append(c.id ?? c.kind.rawValue)
            }
        }

        let flag = offscreen.isEmpty ? "ok " : "OFF"
        print(String(format: "  %@ %-22@ %2d visible, %d gestures%@",
                     flag, layout.id as NSString, visible, gestures,
                     offscreen.isEmpty ? "" : "  offscreen: \(offscreen.joined(separator: ", "))"))
        if !offscreen.isEmpty { failures += 1 }
    } catch {
        print("  ERR \(file.lastPathComponent): \(error)")
        failures += 1
    }
}
print(failures == 0
      ? "\nAll \(files.count) layouts decode and fit on screen."
      : "\n\(failures) layout(s) have problems.")
exit(failures == 0 ? 0 : 1)
