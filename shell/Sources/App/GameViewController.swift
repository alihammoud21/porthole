import MetalKit
import os
import SwiftUI
import UIKit

/// Hosts a running game: an `MTKView` for the picture with a `TouchOverlayView` on
/// top for the controls.
final class GameViewController: UIViewController {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "game")

    private let game: InstalledGame
    private var session: GameSession?
    private var metalView: MTKView!
    private var overlay: TouchOverlayView!

    var onExit: (() -> Void)?

    init(game: InstalledGame) {
        self.game = game
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    // Games run full-bleed; the layout's `safe_area` decides where controls sit.
    override var prefersHomeIndicatorAutoHidden: Bool { true }
    override var prefersStatusBarHidden: Bool { true }
    override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
        .landscape
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black

        metalView = MTKView(frame: view.bounds)
        metalView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(metalView)

        do {
            let layout = try game.loadLayout()
            let s = try GameSession(game: game)
            overlay = TouchOverlayView(layout: layout, router: s.inputRouter)
            overlay.frame = view.bounds
            overlay.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            view.addSubview(overlay)

            s.attach(view: metalView, overlay: overlay)
            s.onShellMenu = { [weak self] in self?.presentShellMenu() }
            try s.start()
            session = s
            overlay.controllerConnectionChanged()
        } catch {
            presentFailure(error)
        }

        NotificationCenter.default.addObserver(
            self, selector: #selector(willResignActive),
            name: UIApplication.willResignActiveNotification, object: nil)
        NotificationCenter.default.addObserver(
            self, selector: #selector(didBecomeActive),
            name: UIApplication.didBecomeActiveNotification, object: nil)
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
        session?.stop()
    }

    // MARK: - Lifecycle

    /// iOS will kill the app for memory while backgrounded, and engines from 2002 do
    /// not expect to be suspended mid-frame. Pausing on resign is the minimum; proper
    /// state snapshotting is tracked as an open question in shell/README.md.
    @objc private func willResignActive() {
        session?.pause()
        if session?.supportsSaveStates == true {
            try? session?.saveState(slot: 9)   // slot 9 is the autosave
        }
    }

    @objc private func didBecomeActive() {
        session?.resume()
    }

    // MARK: - UI

    private func presentShellMenu() {
        session?.pause()
        let sheet = UIAlertController(
            title: game.title, message: nil, preferredStyle: .actionSheet)

        if session?.supportsSaveStates == true {
            sheet.addAction(UIAlertAction(title: "Save state", style: .default) { _ in
                do {
                    try self.session?.saveState()
                } catch {
                    self.presentFailure(error)
                }
                self.session?.resume()
            })
            sheet.addAction(UIAlertAction(title: "Load state", style: .default) { _ in
                do {
                    try self.session?.loadState()
                } catch {
                    self.presentFailure(error)
                }
                self.session?.resume()
            })
        }

        if let s = session {
            let ms = String(format: "%.1f", s.averageFrameMs)
            sheet.addAction(UIAlertAction(
                title: "\(s.game.runtimeName) · \(ms) ms/frame", style: .default) { _ in
                    s.resume()
                })
        }

        sheet.addAction(UIAlertAction(title: "Quit to library", style: .destructive) { _ in
            self.session?.stop()
            self.onExit?()
        })
        sheet.addAction(UIAlertAction(title: "Resume", style: .cancel) { _ in
            self.session?.resume()
        })
        present(sheet, animated: true)
    }

    private func presentFailure(_ error: Error) {
        Self.log.error("\(error.localizedDescription, privacy: .public)")
        let alert = UIAlertController(
            title: "Could not start \(game.title)",
            message: error.localizedDescription,
            preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Back", style: .default) { _ in
            self.onExit?()
        })
        present(alert, animated: true)
    }
}

/// SwiftUI wrapper, so the library can push a game like any other destination.
struct GameView: UIViewControllerRepresentable {
    let game: InstalledGame
    var onExit: () -> Void

    func makeUIViewController(context: Context) -> GameViewController {
        let vc = GameViewController(game: game)
        vc.onExit = onExit
        return vc
    }

    func updateUIViewController(_ controller: GameViewController, context: Context) {}
}
