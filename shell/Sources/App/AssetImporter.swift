import Foundation
import os

/// Copies a user's game files into a game's asset directory.
///
/// Assets live in Documents rather than inside the signed app bundle. That is the
/// single most consequential decision in the shell's design: it keeps the 7-day
/// re-signing ritual fast, keeps saves alive across re-signs, and sidesteps bundle
/// size limits entirely.
enum AssetImporter {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "import")

    /// Copy from a security-scoped URL handed over by the document picker.
    ///
    /// Returns a human-readable status string, because every caller is UI.
    static func importAssets(from source: URL, into game: InstalledGame) -> String {
        let needsScope = source.startAccessingSecurityScopedResource()
        defer { if needsScope { source.stopAccessingSecurityScopedResource() } }

        let fm = FileManager.default
        do {
            try fm.createDirectory(at: game.assetRoot, withIntermediateDirectories: true)

            var copied = 0
            var bytes: Int64 = 0

            let isDirectory = (try? source.resourceValues(forKeys: [.isDirectoryKey]))?
                .isDirectory ?? false

            if isDirectory {
                // Copy the *contents*, not the folder itself: recipes describe paths
                // relative to the asset root, and nesting them one level deeper is
                // the single most common import mistake.
                let entries = try fm.contentsOfDirectory(
                    at: source,
                    includingPropertiesForKeys: [.fileSizeKey, .isDirectoryKey])
                for entry in entries {
                    let dest = game.assetRoot.appendingPathComponent(entry.lastPathComponent)
                    if fm.fileExists(atPath: dest.path) {
                        try fm.removeItem(at: dest)
                    }
                    try fm.copyItem(at: entry, to: dest)
                    copied += 1
                    bytes += size(of: dest)
                }
            } else {
                let dest = game.assetRoot.appendingPathComponent(source.lastPathComponent)
                if fm.fileExists(atPath: dest.path) {
                    try fm.removeItem(at: dest)
                }
                try fm.copyItem(at: source, to: dest)
                copied = 1
                bytes = size(of: dest)
            }

            try markImported(game, bytes: bytes)

            let human = ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
            log.info("imported \(copied) item(s), \(human, privacy: .public)")
            return "Imported \(copied) item\(copied == 1 ? "" : "s") · \(human)"

        } catch {
            log.error("import failed: \(error.localizedDescription, privacy: .public)")
            return "Import failed: \(error.localizedDescription)"
        }
    }

    /// Recursive size. Used for the library listing, and cheap enough because it only
    /// runs once per import rather than per launch.
    static func size(of url: URL) -> Int64 {
        let fm = FileManager.default
        var total: Int64 = 0

        if (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true {
            guard let walker = fm.enumerator(
                at: url, includingPropertiesForKeys: [.fileSizeKey]) else { return 0 }
            for case let child as URL in walker {
                total += Int64((try? child.resourceValues(forKeys: [.fileSizeKey]))?
                    .fileSize ?? 0)
            }
        } else {
            total = Int64((try? url.resourceValues(forKeys: [.fileSizeKey]))?
                .fileSize ?? 0)
        }
        return total
    }

    /// Record the import in the manifest. The library still verifies against the
    /// filesystem on every scan — a manifest can claim assets the user has since
    /// deleted from the Files app.
    private static func markImported(_ game: InstalledGame, bytes: Int64) throws {
        let url = game.manifestURL
        guard var json = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)) as? [String: Any] else { return }
        json["assets_imported"] = true
        json["asset_bytes"] = bytes
        let data = try JSONSerialization.data(
            withJSONObject: json, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: url, options: .atomic)
    }
}
