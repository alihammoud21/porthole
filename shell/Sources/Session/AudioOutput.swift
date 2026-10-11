import AVFoundation
import Foundation
import os

/// Audio output for a running runtime.
///
/// The runtime produces samples on the frame loop; CoreAudio consumes them on its own
/// real-time thread. A lock-free ring buffer sits between the two, because taking a
/// lock on the audio thread is how you get glitches.
///
/// iOS is markedly less forgiving about underruns than any desktop, so the buffer is
/// sized for roughly four frames of audio and underruns fill with silence rather than
/// repeating stale samples — a click is less objectionable than a buzz.
final class AudioOutput {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "audio")

    let sampleRate: Double
    let channels: UInt32

    private let engine = AVAudioEngine()
    private var sourceNode: AVAudioSourceNode?

    /// Ring buffer of interleaved Int16 frames.
    private let capacityFrames: Int
    private var ring: UnsafeMutableBufferPointer<Int16>
    private var writeIndex = 0           // frame index, producer only
    private var readIndex = 0            // frame index, consumer only
    private let indexLock = NSLock()     // guards only the two Ints, never the audio copy

    private(set) var underruns = 0

    init(sampleRate: Double = 48000, channels: UInt32 = 2, bufferFrames: Int = 4096) {
        self.sampleRate = sampleRate
        self.channels = channels
        self.capacityFrames = bufferFrames
        self.ring = .allocate(capacity: bufferFrames * Int(channels))
        ring.initialize(repeating: 0)
    }

    deinit {
        stop()
        ring.deallocate()
    }

    // MARK: - Lifecycle

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        // .ambient so a game does not stop the user's music unless it wants to, and
        // mixWithOthers because being the app that kills someone's podcast is rude.
        try session.setCategory(.ambient, mode: .default, options: [.mixWithOthers])
        try session.setPreferredSampleRate(sampleRate)
        try session.setActive(true)

        guard let format = AVAudioFormat(
            standardFormatWithSampleRate: sampleRate,
            channels: AVAudioChannelCount(channels))
        else {
            throw NSError(domain: "app.porthole.audio", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Could not create an audio format."
            ])
        }

        let node = AVAudioSourceNode(format: format) { [weak self] _, _, frameCount, buffers in
            guard let self else { return noErr }
            self.render(frameCount: Int(frameCount), into: buffers)
            return noErr
        }
        sourceNode = node

        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        try engine.start()
        Self.log.info("audio started at \(self.sampleRate, privacy: .public) Hz")
    }

    func stop() {
        if engine.isRunning { engine.stop() }
        if let node = sourceNode {
            engine.detach(node)
            sourceNode = nil
        }
    }

    // MARK: - Producer side (frame loop)

    /// Frames the runtime should produce this call: enough to keep the buffer around
    /// half full, so neither starved nor latent.
    var framesWanted: Int {
        indexLock.lock()
        let queued = writeIndex - readIndex
        indexLock.unlock()
        let target = capacityFrames / 2
        return max(0, min(capacityFrames - queued, target))
    }

    /// Copy `frames` of interleaved Int16 from the runtime's output into the ring.
    func submit(_ samples: UnsafePointer<Int16>, frames: Int) {
        guard frames > 0 else { return }

        indexLock.lock()
        let queued = writeIndex - readIndex
        let room = capacityFrames - queued
        let toWrite = min(frames, room)
        var w = writeIndex
        indexLock.unlock()

        let ch = Int(channels)
        for f in 0..<toWrite {
            let dst = (w % capacityFrames) * ch
            for c in 0..<ch {
                ring[dst + c] = samples[f * ch + c]
            }
            w += 1
        }

        indexLock.lock()
        writeIndex = w
        indexLock.unlock()
    }

    // MARK: - Consumer side (audio thread)

    private func render(frameCount: Int, into buffers: UnsafeMutablePointer<AudioBufferList>) {
        let abl = UnsafeMutableAudioBufferListPointer(buffers)
        let ch = Int(channels)

        indexLock.lock()
        var r = readIndex
        let available = writeIndex - r
        indexLock.unlock()

        let toRead = min(frameCount, max(0, available))
        if toRead < frameCount {
            underruns += 1
        }

        // AVAudioSourceNode with a standard format gives deinterleaved Float32
        // buffers, one per channel.
        for (channel, buffer) in abl.enumerated() {
            guard channel < ch,
                  let out = buffer.mData?.assumingMemoryBound(to: Float.self)
            else { continue }

            for f in 0..<frameCount {
                if f < toRead {
                    let src = ((r + f) % capacityFrames) * ch + channel
                    out[f] = Float(ring[src]) / 32768.0
                } else {
                    out[f] = 0     // underrun: silence, not stale samples
                }
            }
        }

        r += toRead
        indexLock.lock()
        readIndex = r
        indexLock.unlock()
    }
}
