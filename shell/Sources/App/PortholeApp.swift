import SwiftUI
import UniformTypeIdentifiers

@main
struct PortholeApp: App {
    var body: some Scene {
        WindowGroup {
            LibraryView()
        }
    }
}

/// The library: every game installed into this app.
///
/// Library mode is the default because a free Apple developer certificate allows only
/// three app IDs at a time. One app holding twenty games costs one of them.
struct LibraryView: View {
    @State private var games: [InstalledGame] = []
    @State private var playing: InstalledGame?
    @State private var importing: InstalledGame?

    var body: some View {
        NavigationView {
            Group {
                if games.isEmpty {
                    EmptyLibrary()
                } else {
                    List(games) { game in
                        Button {
                            if game.assetsImported {
                                playing = game
                            } else {
                                importing = game
                            }
                        } label: {
                            GameRow(game: game)
                        }
                        .buttonStyle(.plain)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Porthole")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        games = InstalledGame.discover()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Rescan library")
                }
            }
        }
        .onAppear { games = InstalledGame.discover() }
        .fullScreenCover(item: $playing) { game in
            GameView(game: game) {
                playing = nil
                games = InstalledGame.discover()
            }
            .ignoresSafeArea()
        }
        .sheet(item: $importing) { game in
            ImportSheet(game: game) {
                importing = nil
                games = InstalledGame.discover()
            }
        }
    }
}

private struct GameRow: View {
    let game: InstalledGame

    var body: some View {
        HStack(spacing: 14) {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(.quaternary)
                .frame(width: 52, height: 52)
                .overlay {
                    Image(systemName: game.assetsImported
                          ? "gamecontroller.fill" : "tray.and.arrow.down")
                        .foregroundStyle(.secondary)
                }

            VStack(alignment: .leading, spacing: 3) {
                Text(game.title)
                    .font(.body.weight(.medium))

                HStack(spacing: 6) {
                    if let year = game.year {
                        Text(String(year))
                    }
                    Text(game.runtimeName)
                    if let bytes = game.assetBytes, game.assetsImported {
                        Text(ByteCountFormatter.string(
                            fromByteCount: bytes, countStyle: .file))
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                if !game.assetsImported {
                    Text("Needs game files")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.orange)
                }
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 4)
    }
}

private struct EmptyLibrary: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "shippingbox")
                .font(.system(size: 44))
                .foregroundStyle(.tertiary)
            Text("No games yet")
                .font(.title3.weight(.semibold))
            Text("""
                Build one on your computer with `porthole build`, install it, then \
                bring your own game files in here.
                """)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 36)
        }
    }
}

/// Assets arrive after installation, never inside the signed bundle — that is what
/// keeps re-signing fast and saves intact.
private struct ImportSheet: View {
    let game: InstalledGame
    var onDone: () -> Void

    @State private var showPicker = false
    @State private var status: String?

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 18) {
                Text(game.title)
                    .font(.title2.weight(.semibold))

                Text("""
                    This app ships without game data. Bring the files from your own \
                    copy and they stay on this device.
                    """)
                    .foregroundStyle(.secondary)

                VStack(alignment: .leading, spacing: 10) {
                    Label("Files app — drag the folder into On My iPhone → Porthole",
                          systemImage: "folder")
                    Label("AirDrop an archive from your computer", systemImage: "wifi")
                    Label("`porthole serve <dir>` for a LAN handoff with a QR code",
                          systemImage: "qrcode")
                }
                .font(.callout)

                if let status {
                    Text(status)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button {
                    showPicker = true
                } label: {
                    Text("Choose a folder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .padding(22)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { onDone() }
                }
            }
            .fileImporter(
                isPresented: $showPicker,
                allowedContentTypes: [.folder, .archive],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case .success(let urls):
                    guard let src = urls.first else { return }
                    status = AssetImporter.importAssets(from: src, into: game)
                case .failure(let error):
                    status = error.localizedDescription
                }
            }
        }
    }
}
