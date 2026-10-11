import Foundation
import GameController
import MetalKit
import os
import UIKit

/// One running game: runtime, renderer, input, audio, and the frame loop that drives
/// them.
///
/// The loop is `CADisplayLink`, so frames are produced in step with the display
/// rather than on a timer that drifts against it. A runtime that needs its own thread
/// manages that internally and presents its most recent complete frame — the ABI
/// requires `ph_frame` to return promptly either way.
final class GameSession: NSObject {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "session")

    let game: InstalledGame

    private let runtime: RuntimeHost
    private let renderer: MetalRenderer
    /// The overlay must feed the *same* router this session samples from, so it is
    /// owned here and handed out rather than constructed in two places.
    let inputRouter = InputRouter()
    private let audio: AudioOutput

    private weak var view: MTKView?
    private weak var overlay: TouchOverlayView?
    private var displayLink: CADisplayLink?

    /// Host-owned output buffers, reused every frame. The ABI specifies the runtime
    /// writes into these and the host owns them, which keeps allocation out of the
    /// frame loop entirely.
    private var video = ph_video()
    private var audioBuffer: UnsafeMutableBufferPointer<Int16>
    private let audioCapacityFrames = 2048

    private(set) var isPaused = false
    private(set) var frameCount: UInt64 = 0

    /// Rolling frame-time average, for the debug overlay and for honest `[expect]`
    /// numbers in recipes.
    private(set) var averageFrameMs: Double = 0

    init(game: InstalledGame) throws {
        self.game = game
        self.runtime = try RuntimeHost(id: game.runtimeID)
        self.renderer = try MetalRenderer()
        self.audio = AudioOutput(sampleRate: 48000, channels: 2)
        self.audioBuffer = .allocate(capacity: audioCapacityFrames * 2)
        audioBuffer.initialize(repeating: 0)
        super.init()

        Self.log.info("""
            opening \(game.title, privacy: .public) on \
            \(self.runtime.info.name, privacy: .public) \
            \(self.runtime.info.version, privacy: .public) \
            (\(self.runtime.info.license, privacy: .public))
            """)
    }

    deinit {
        stop()
        audioBuffer.deallocate()
    }

    // MARK: - Attaching to a view

    func attach(view: MTKView, overlay: TouchOverlayView) {
        self.view = view
        self.overlay = overlay
        view.device = MTLCreateSystemDefaultDevice()
        view.colorPixelFormat = .bgra8Unorm
        view.framebufferOnly = true
        // We drive frames ourselves, so the view must not also drive them.
        view.isPaused = true
        view.enableSetNeedsDisplay = false
    }

    // MARK: - Lifecycle

    func start() throws {
        guard displayLink == nil else { return }

        try FileManager.default.createDirectory(
            at: game.saveDirectory, withIntermediateDirectories: true)

        let scale = UIScreen.main.nativeScale
        let size = UIScreen.main.bounds.size
        try runtime.open(
            assetRoot: game.assetRoot,
            saveDir: game.saveDirectory,
            maxSize: (UInt32(size.width * scale), UInt32(size.height * scale)),
            sampleRate: UInt32(audio.sampleRate),
            channels: UInt8(audio.channels),
            options: game.runtimeOptions)

        do {
            try audio.start()
        } catch {
            // A game without sound still beats no game at all.
            Self.log.error("audio unavailable: \(error.localizedDescription, privacy: .public)")
        }

        let link = CADisplayLink(target: self, selector: #selector(tick))
        link.preferredFrameRateRange = CAFrameRateRange(
            minimum: 30, maximum: 120, preferred: 60)
        link.add(to: .main, forMode: .common)
        displayLink = link

        NotificationCenter.default.addObserver(
            self, selector: #selector(controllerChanged),
            name: .GCControllerDidConnect, object: nil)
        NotificationCenter.default.addObserver(
            self, selector: #selector(controllerChanged),
            name: .GCControllerDidDisconnect, object: nil)
    }

    func stop() {
        displayLink?.invalidate()
        displayLink = nil
        audio.stop()
        runtime.close()
        NotificationCenter.default.removeObserver(self)
    }

    func pause() {
        isPaused = true
        displayLink?.isPaused = true
    }

    func resume() {
        isPaused = false
        displayLink?.isPaused = false
    }

    @objc private func controllerChanged() {
        overlay?.controllerConnectionChanged()
    }

    // MARK: - Frame loop

    @objc private func tick(_ link: CADisplayLink) {
        guard let view, !isPaused else { return }
        let began = CACurrentMediaTime()

        // Tell the router where the game is on screen, so a touch in the game area
        // maps to the right framebuffer pixel.
        if video.width > 0, video.height > 0 {
            let aspect = video.aspect > 0
                ? CGFloat(video.aspect)
                : CGFloat(video.width) / CGFloat(video.height)
            inputRouter.contentSize = CGSize(width: CGFloat(video.width),
                                        height: CGFloat(video.height))
            inputRouter.contentRect = Self.fittedRect(aspect: aspect, in: view.bounds)
            overlay?.contentRect = inputRouter.contentRect
        }

        inputRouter.pollController()
        var input = inputRouter.snapshot()

        var audioOut = ph_audio(
            samples: audioBuffer.baseAddress,
            frames_capacity: min(audio.framesWanted, audioCapacityFrames),
            frames_written: 0)

        runtime.frame(input: &input, video: &video, audio: &audioOut)

        if audioOut.frames_written > 0, let samples = audioBuffer.baseAddress {
            audio.submit(samples, frames: audioOut.frames_written)
        }

        renderer.draw(video: video, in: view)

        // Shell-level actions the runtime never sees.
        for action in inputRouter.shellActions {
            handle(action)
        }
        inputRouter.clearTransient()

        frameCount += 1
        let elapsed = (CACurrentMediaTime() - began) * 1000
        averageFrameMs = averageFrameMs * 0.95 + elapsed * 0.05
    }

    private func handle(_ action: InputRouter.ShellAction) {
        switch action {
        case .modeToggle:
            overlay?.toggleMode()
        case .mode(let m):
            overlay?.setMode(m)
        case .toggleKeyboard:
            onToggleKeyboard?()
        case .shellMenu:
            onShellMenu?()
        }
    }

    var onToggleKeyboard: (() -> Void)?
    var onShellMenu: (() -> Void)?

    /// Where the game's picture sits inside the view, preserving aspect ratio. Mirrors
    /// `MetalRenderer.fitRect` but in view coordinates rather than NDC.
    static func fittedRect(aspect: CGFloat, in bounds: CGRect) -> CGRect {
        guard aspect > 0, bounds.height > 0 else { return bounds }
        let viewAspect = bounds.width / bounds.height
        if aspect > viewAspect {
            let h = bounds.width / aspect
            return CGRect(x: bounds.minX, y: bounds.midY - h / 2,
                          width: bounds.width, height: h)
        } else {
            let w = bounds.height * aspect
            return CGRect(x: bounds.midX - w / 2, y: bounds.minY,
                          width: w, height: bounds.height)
        }
    }

    // MARK: - Save states

    var supportsSaveStates: Bool { runtime.info.supportsState }

    func saveState(slot: Int = 0) throws {
        guard let data = runtime.saveState() else {
            throw NSError(domain: "app.porthole.session", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "This runtime did not produce a save state."
            ])
        }
        try data.write(to: game.saveStateURL(slot: slot), options: .atomic)
        Self.log.info("saved state to slot \(slot)")
    }

    func loadState(slot: Int = 0) throws {
        let url = game.saveStateURL(slot: slot)
        let data = try Data(contentsOf: url)
        guard runtime.loadState(data) else {
            throw NSError(domain: "app.porthole.session", code: 3, userInfo: [
                NSLocalizedDescriptionKey:
                    "The runtime refused this save state. It may be from another version."
            ])
        }
        Self.log.info("loaded state from slot \(slot)")
    }
}