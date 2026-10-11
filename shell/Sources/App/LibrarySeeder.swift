import Foundation
import os

/// Copies the games baked into the app bundle out into Documents on first launch.
///
/// `porthole build` writes each game's manifest and compiled layout into
/// `Seed/<id>/` inside the bundle. They cannot stay there: the bundle is read-only and
/// is replaced wholesale every time the app is re-signed, which for a free Apple
/// developer certificate is every seven days.
///
/// Documents, by contrast, survives re-signing — so that is where a game's manifest,
/// imported assets, and saves live. This is the mechanism behind the claim that
/// re-signing never costs you your saves.
enum LibrarySeeder {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "seed")

    /// Install any bundled game that is not already present.
    ///
    /// Idempotent and safe to call on every launch. An existing game is updated —
    /// its layout is refreshed from the new build — but its `assets_imported` state
    /// and save directory are left strictly alone.
    @discardableResult
    static func seed(bundle: Bundle = .main) -> [String] {
        guard let seedRoot = bundle.url(forResource: "Seed", withExtension: nil) else {
            return []
        }
        return seed(from: seedRoot, into: InstalledGame.libraryRoot)
    }

    /// Roots are parameters so this is testable without a real app bundle. The
    /// manifest merge below protects a user's import state across re-signs, which is
    /// exactly the kind of logic that should not be verified by hand.
    @discardableResult
    static func seed(from seedRoot: URL, into libraryRoot: URL) -> [String] {
        let fm = FileManager.default

        guard let entries = try? fm.contentsOfDirectory(
            at: seedRoot, includingPropertiesForKeys: [.isDirectoryKey])
        else {
            return []
        }

        var installed: [String] = []

        for src in entries {
            guard (try? src.resourceValues(forKeys: [.isDirectoryKey]))?
                .isDirectory == true else { continue }

            let id = src.lastPathComponent
            let dest = libraryRoot.appendingPathComponent(id, isDirectory: true)

            do {
                try fm.createDirectory(at: dest, withIntermediateDirectories: true)
                try fm.createDirectory(
                    at: dest.appendingPathComponent("assets"),
                    withIntermediateDirectories: true)
                try fm.createDirectory(
                    at: dest.appendingPathComponent("saves"),
                    withIntermediateDirectories: true)

                // The layout is build output and always takes the newer copy: a
                // rebuilt app should deliver a retuned control layout.
                try replace(
                    src.appendingPathComponent("layout.json"),
                    with: dest.appendingPathComponent("layout.json"))

                // The manifest carries runtime state (`assets_imported`,
                // `asset_bytes`) that the bundle cannot know about, so merge rather
                // than overwrite.
                try mergeManifest(
                    from: src.appendingPathComponent("manifest.json"),
                    into: dest.appendingPathComponent("manifest.json"))

                installed.append(id)
            } catch {
                // One bad game should not stop the rest from installing.
                log.error("""
                    could not seed \(id, privacy: .public): \
                    \(error.localizedDescription, privacy: .public)
                    """)
            }
        }

        if !installed.isEmpty {
            log.info("seeded \(installed.joined(separator: ", "), privacy: .public)")
        }
        return installed
    }

    private static func replace(_ src: URL, with dest: URL) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: src.path) else { return }
        if fm.fileExists(atPath: dest.path) {
            try fm.removeItem(at: dest)
        }
        try fm.copyItem(at: src, to: dest)
    }

    /// Take build-time fields from the bundle, keep runtime fields from disk.
    private static func mergeManifest(from src: URL, into dest: URL) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: src.path) else { return }

        guard var incoming = try JSONSerialization.jsonObject(
            with: Data(contentsOf: src)) as? [String: Any] else { return }

        if fm.fileExists(atPath: dest.path),
           let existing = try? JSONSerialization.jsonObject(
            with: Data(contentsOf: dest)) as? [String: Any] {
            // These describe what the user has done, not what the build produced.
            for key in ["assets_imported", "asset_bytes"] {
                if let value = existing[key] {
                    incoming[key] = value
                }
            }
        }

        let data = try JSONSerialization.data(
            withJSONObject: incoming, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: dest, options: .atomic)
    }
}
