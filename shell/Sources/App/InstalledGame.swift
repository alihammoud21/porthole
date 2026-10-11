import Foundation

/// A game installed into the app container.
///
/// Written by `porthole build` as `manifest.json` inside the game's own directory.
/// The shell discovers games by scanning for these rather than keeping a central
/// index, so a half-finished import or a manually deleted folder can never leave the
/// library pointing at something that isn't there.
struct InstalledGame: Codable, Identifiable, Hashable {
    /// Recipe id — `morrowind`, `diablo`, `doom2`.
    let id: String
    let title: String
    let year: Int?

    /// Runtime framework to `dlopen`, matching `Frameworks/<id>.framework`.
    let runtimeID: String
    let runtimeName: String
    let runtimeLicense: String

    /// Touch layout id; the compiled JSON lives next to the manifest.
    let layoutID: String

    let tier: Int
    let runtimeOptions: [String: String]

    /// Set once assets have been imported and verified. A game can exist in the
    /// library before its files arrive — that's the normal state right after install,
    /// and the library shows it as "needs files" rather than hiding it.
    var assetsImported: Bool

    /// Bytes of imported assets, for the library listing.
    var assetBytes: Int64?

    enum CodingKeys: String, CodingKey {
        case id, title, year, tier
        case runtimeID = "runtime_id"
        case runtimeName = "runtime_name"
        case runtimeLicense = "runtime_license"
        case layoutID = "layout_id"
        case runtimeOptions = "runtime_options"
        case assetsImported = "assets_imported"
        case assetBytes = "asset_bytes"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        year = try c.decodeIfPresent(Int.self, forKey: .year)
        tier = try c.decodeIfPresent(Int.self, forKey: .tier) ?? 0
        runtimeID = try c.decode(String.self, forKey: .runtimeID)
        runtimeName = try c.decodeIfPresent(String.self, forKey: .runtimeName) ?? runtimeID
        runtimeLicense = try c.decodeIfPresent(String.self, forKey: .runtimeLicense) ?? "?"
        layoutID = try c.decodeIfPresent(String.self, forKey: .layoutID) ?? "gamepad"
        runtimeOptions = try c.decodeIfPresent([String: String].self,
                                               forKey: .runtimeOptions) ?? [:]
        assetsImported = try c.decodeIfPresent(Bool.self, forKey: .assetsImported) ?? false
        assetBytes = try c.decodeIfPresent(Int64.self, forKey: .assetBytes)
    }

    // MARK: - Paths

    /// Games live in Documents so they survive re-signing and are reachable from the
    /// Files app, which is how most people will get their assets in.
    static var libraryRoot: URL {
        let docs = FileManager.default.urls(
            for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("Games", isDirectory: true)
    }

    var root: URL { Self.libraryRoot.appendingPathComponent(id, isDirectory: true) }
    var assetRoot: URL { root.appendingPathComponent("assets", isDirectory: true) }
    var saveDirectory: URL { root.appendingPathComponent("saves", isDirectory: true) }
    var manifestURL: URL { root.appendingPathComponent("manifest.json") }
    var layoutURL: URL { root.appendingPathComponent("layout.json") }

    func saveStateURL(slot: Int) -> URL {
        saveDirectory.appendingPathComponent("state\(slot).phst")
    }

    // MARK: - Discovery

    /// Scan the library directory for manifests. Unreadable entries are skipped with
    /// a note rather than failing the whole scan — one corrupt manifest should not
    /// hide the rest of someone's library.
    static func discover() -> [InstalledGame] {
        let fm = FileManager.default
        guard let entries = try? fm.contentsOfDirectory(
            at: libraryRoot, includingPropertiesForKeys: nil) else { return [] }

        var games: [InstalledGame] = []
        for dir in entries where (try? dir.resourceValues(forKeys: [.isDirectoryKey]))?
            .isDirectory == true {
            let manifest = dir.appendingPathComponent("manifest.json")
            guard let data = try? Data(contentsOf: manifest),
                  var game = try? JSONDecoder().decode(InstalledGame.self, from: data)
            else { continue }

            // Trust the filesystem over the manifest: a manifest can say assets are
            // imported while the user has since deleted them from the Files app.
            game.assetsImported = Self.hasAssets(at: dir.appendingPathComponent("assets"))
            games.append(game)
        }
        return games.sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
    }

    private static func hasAssets(at url: URL) -> Bool {
        guard let entries = try? FileManager.default.contentsOfDirectory(
            atPath: url.path) else { return false }
        return !entries.isEmpty
    }

    func loadLayout() throws -> Layout {
        try Layout.load(from: layoutURL)
    }
}
