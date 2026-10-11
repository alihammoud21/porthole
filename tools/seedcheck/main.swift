import Foundation

// Verifies LibrarySeeder against a fake bundle and library root.
//
// The property that matters: re-signing the app replaces the bundle wholesale, and
// the seeder runs again. It must refresh build output (the layout) while never
// touching what the user has done (imported assets, save state). If this regresses,
// people silently lose their games on a Tuesday.

let tmp = URL(fileURLWithPath: NSTemporaryDirectory())
    .appendingPathComponent("porthole-seedcheck-\(UUID().uuidString)")
let seedRoot = tmp.appendingPathComponent("bundle/Seed")
let library = tmp.appendingPathComponent("Documents/Games")
let fm = FileManager.default
defer { try? fm.removeItem(at: tmp) }

func write(_ dict: [String: Any], to url: URL) throws {
    try fm.createDirectory(at: url.deletingLastPathComponent(),
                           withIntermediateDirectories: true)
    let data = try JSONSerialization.data(withJSONObject: dict,
                                          options: [.prettyPrinted, .sortedKeys])
    try data.write(to: url)
}

func read(_ url: URL) throws -> [String: Any] {
    try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
}

var failures = 0
func check(_ label: String, _ condition: Bool) {
    print("  \(condition ? "ok " : "FAIL") \(label)")
    if !condition { failures += 1 }
}

do {
    let game = seedRoot.appendingPathComponent("selftest")
    try write([
        "id": "selftest", "title": "Porthole self-test", "tier": 3,
        "runtime_id": "selftest", "runtime_name": "Porthole self-test",
        "runtime_license": "MIT", "layout_id": "selftest",
        "runtime_options": [String: String](), "assets_imported": false,
    ], to: game.appendingPathComponent("manifest.json"))
    try write(["id": "selftest", "name": "Self-test", "controls": [],
               "revision": 1], to: game.appendingPathComponent("layout.json"))

    // ── first launch ──
    let first = LibrarySeeder.seed(from: seedRoot, into: library)
    check("first launch seeds the game", first == ["selftest"])

    let dest = library.appendingPathComponent("selftest")
    check("assets directory created",
          fm.fileExists(atPath: dest.appendingPathComponent("assets").path))
    check("saves directory created",
          fm.fileExists(atPath: dest.appendingPathComponent("saves").path))
    check("manifest copied",
          fm.fileExists(atPath: dest.appendingPathComponent("manifest.json").path))

    // ── the user imports assets and plays ──
    var manifest = try read(dest.appendingPathComponent("manifest.json"))
    manifest["assets_imported"] = true
    manifest["asset_bytes"] = 1_234_567
    try write(manifest, to: dest.appendingPathComponent("manifest.json"))
    let save = dest.appendingPathComponent("saves/state0.phst")
    try Data([1, 2, 3, 4]).write(to: save)

    // ── the certificate expires; the app is rebuilt and re-signed ──
    try write(["id": "selftest", "name": "Self-test", "controls": [],
               "revision": 2], to: game.appendingPathComponent("layout.json"))
    let second = LibrarySeeder.seed(from: seedRoot, into: library)
    check("re-seed is idempotent", second == ["selftest"])

    let after = try read(dest.appendingPathComponent("manifest.json"))
    check("import state survives a re-sign",
          after["assets_imported"] as? Bool == true)
    check("asset size survives a re-sign",
          after["asset_bytes"] as? Int == 1_234_567)
    check("save file survives a re-sign", fm.fileExists(atPath: save.path))

    let layout = try read(dest.appendingPathComponent("layout.json"))
    check("layout is refreshed from the new build",
          layout["revision"] as? Int == 2)

    // ── a corrupt seed must not take down the rest ──
    let broken = seedRoot.appendingPathComponent("broken")
    try fm.createDirectory(at: broken, withIntermediateDirectories: true)
    try "not json".write(to: broken.appendingPathComponent("manifest.json"),
                         atomically: true, encoding: .utf8)
    let third = LibrarySeeder.seed(from: seedRoot, into: library)
    check("a malformed game does not block the good one",
          third.contains("selftest"))

} catch {
    print("  FAIL unexpected error: \(error)")
    failures += 1
}

print(failures == 0
      ? "\nSeeder behaves correctly across a re-sign."
      : "\n\(failures) check(s) failed.")
exit(failures == 0 ? 0 : 1)
