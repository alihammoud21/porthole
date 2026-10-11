import Foundation
import Metal
import MetalKit
import os
import simd

/// Presents a runtime's framebuffer with Metal.
///
/// Two deliberate choices here:
///
/// - **Triple-buffered uploads.** A runtime hands over a pointer into its own
///   framebuffer and expects the host to be finished before the next `ph_frame`.
///   Writing into a texture the GPU is still reading would tear, so uploads rotate
///   through three textures.
/// - **Shaders compiled at runtime by default.** Recent Xcode moved the Metal
///   compiler into a separately downloaded component, and requiring a multi-gigabyte
///   toolchain to build a 50-line shader is a bad trade for contributors. The shader
///   source is embedded; a precompiled `default.metallib` is used instead when
///   `porthole build` found a toolchain to make one with.
final class MetalRenderer {

    private static let log = Logger(subsystem: "app.porthole.shell", category: "render")

    private let device: MTLDevice
    private let queue: MTLCommandQueue
    private var directPipeline: MTLRenderPipelineState?
    private var palettePipeline: MTLRenderPipelineState?
    private let sampler: MTLSamplerState
    private let paletteSampler: MTLSamplerState

    /// Rotating upload targets, so we never write a texture the GPU may still be
    /// reading from.
    private var frameTextures: [MTLTexture?] = [nil, nil, nil]
    private var paletteTexture: MTLTexture?
    private var slot = 0

    /// Cached so a format or size change can rebuild the textures.
    private var textureWidth = 0
    private var textureHeight = 0
    private var texturePixelFormat: MTLPixelFormat = .invalid

    enum RenderError: LocalizedError {
        case noDevice
        case noQueue
        case shaderCompilation(String)

        var errorDescription: String? {
            switch self {
            case .noDevice: return "This device has no Metal support."
            case .noQueue: return "Could not create a Metal command queue."
            case .shaderCompilation(let m): return "Shader compilation failed: \(m)"
            }
        }
    }

    init(device: MTLDevice? = MTLCreateSystemDefaultDevice()) throws {
        guard let device else { throw RenderError.noDevice }
        guard let queue = device.makeCommandQueue() else { throw RenderError.noQueue }
        self.device = device
        self.queue = queue

        let desc = MTLSamplerDescriptor()
        // Nearest by default: these are pixel-art era framebuffers and bilinear
        // smearing is almost never what someone wants. Switchable per game later.
        desc.minFilter = .nearest
        desc.magFilter = .nearest
        desc.sAddressMode = .clampToEdge
        desc.tAddressMode = .clampToEdge
        guard let s = device.makeSamplerState(descriptor: desc) else {
            throw RenderError.noDevice
        }
        sampler = s

        // The palette must always be sampled nearest — interpolating between two
        // unrelated palette entries produces colours that exist in neither.
        let palDesc = MTLSamplerDescriptor()
        palDesc.minFilter = .nearest
        palDesc.magFilter = .nearest
        palDesc.sAddressMode = .clampToEdge
        palDesc.tAddressMode = .clampToEdge
        guard let ps = device.makeSamplerState(descriptor: palDesc) else {
            throw RenderError.noDevice
        }
        paletteSampler = ps

        try buildPipelines()
    }

    // MARK: - Pipelines

    private func buildPipelines() throws {
        let library: MTLLibrary
        if let precompiled = try? device.makeDefaultLibrary(bundle: .main) {
            library = precompiled
            Self.log.info("using precompiled default.metallib")
        } else {
            do {
                library = try device.makeLibrary(source: Self.shaderSource, options: nil)
                Self.log.info("compiled shaders at runtime")
            } catch {
                throw RenderError.shaderCompilation(error.localizedDescription)
            }
        }

        func pipeline(fragment: String) throws -> MTLRenderPipelineState {
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = library.makeFunction(name: "ph_vertex")
            d.fragmentFunction = library.makeFunction(name: fragment)
            d.colorAttachments[0].pixelFormat = .bgra8Unorm
            return try device.makeRenderPipelineState(descriptor: d)
        }

        directPipeline = try pipeline(fragment: "ph_fragment_direct")
        palettePipeline = try pipeline(fragment: "ph_fragment_palette")
    }

    // MARK: - Format mapping

    /// Map an ABI pixel format onto Metal. PAL8 becomes a single-channel texture and
    /// the palette lookup happens in the fragment shader.
    private static func metalFormat(_ f: ph_pixel_format) -> (MTLPixelFormat, Int) {
        switch f {
        case PH_PIX_RGBA8888: return (.rgba8Unorm, 4)
        case PH_PIX_BGRA8888: return (.bgra8Unorm, 4)
        case PH_PIX_RGB565: return (.b5g6r5Unorm, 2)
        case PH_PIX_PAL8: return (.r8Unorm, 1)
        default: return (.rgba8Unorm, 4)
        }
    }

    // MARK: - Drawing

    /// Upload one frame and present it, letterboxed to preserve aspect ratio.
    func draw(video: ph_video, in view: MTKView) {
        guard !video.skipped || frameTextures[slot] != nil,
              let pixels = video.pixels,
              video.width > 0, video.height > 0,
              let drawable = view.currentDrawable,
              let pass = view.currentRenderPassDescriptor
        else { return }

        let (format, bytesPerPixel) = Self.metalFormat(video.format)
        let w = Int(video.width)
        let h = Int(video.height)

        // Rebuild the texture ring if geometry or format changed. Engines do this
        // mid-session more often than you would expect — DOS games switch video
        // modes, PSX games switch resolution per scene.
        if w != textureWidth || h != textureHeight || format != texturePixelFormat {
            let desc = MTLTextureDescriptor.texture2DDescriptor(
                pixelFormat: format, width: w, height: h, mipmapped: false)
            desc.usage = .shaderRead
            desc.storageMode = .shared
            frameTextures = (0..<3).map { _ in device.makeTexture(descriptor: desc) }
            textureWidth = w
            textureHeight = h
            texturePixelFormat = format
            Self.log.info("framebuffer is now \(w)x\(h), format \(format.rawValue)")
        }

        slot = (slot + 1) % frameTextures.count
        guard let texture = frameTextures[slot] else { return }

        if !video.skipped {
            let pitch = video.pitch > 0 ? video.pitch : w * bytesPerPixel
            texture.replace(
                region: MTLRegionMake2D(0, 0, w, h),
                mipmapLevel: 0,
                withBytes: pixels,
                bytesPerRow: pitch)
        }

        let isPalettised = video.format == PH_PIX_PAL8
        if isPalettised, let palette = video.palette {
            uploadPalette(palette)
        }

        guard let pipeline = isPalettised ? palettePipeline : directPipeline,
              let buffer = queue.makeCommandBuffer(),
              let encoder = buffer.makeRenderCommandEncoder(descriptor: pass)
        else { return }

        // Aspect-correct destination rect in normalised device coordinates.
        let aspect = video.aspect > 0 ? video.aspect : Float(w) / Float(h)
        var rect = Self.fitRect(
            contentAspect: aspect,
            into: Float(view.drawableSize.width / max(view.drawableSize.height, 1)))

        encoder.setRenderPipelineState(pipeline)
        encoder.setVertexBytes(&rect, length: MemoryLayout<SIMD4<Float>>.size, index: 0)
        encoder.setFragmentTexture(texture, index: 0)
        encoder.setFragmentSamplerState(sampler, index: 0)
        if isPalettised {
            encoder.setFragmentTexture(paletteTexture, index: 1)
            encoder.setFragmentSamplerState(paletteSampler, index: 1)
        }
        encoder.drawPrimitives(type: .triangleStrip, vertexStart: 0, vertexCount: 4)
        encoder.endEncoding()

        buffer.present(drawable)
        buffer.commit()
    }

    private func uploadPalette(_ palette: UnsafePointer<UInt32>) {
        if paletteTexture == nil {
            let desc = MTLTextureDescriptor.texture2DDescriptor(
                pixelFormat: .bgra8Unorm, width: 256, height: 1, mipmapped: false)
            desc.usage = .shaderRead
            desc.storageMode = .shared
            paletteTexture = device.makeTexture(descriptor: desc)
        }
        // The ABI specifies 0xAARRGGBB, which is exactly bgra8Unorm's byte order on
        // a little-endian device, so this is a straight copy.
        paletteTexture?.replace(
            region: MTLRegionMake2D(0, 0, 256, 1),
            mipmapLevel: 0,
            withBytes: palette,
            bytesPerRow: 256 * 4)
    }

    /// Letterbox or pillarbox `contentAspect` inside a viewport of `viewAspect`,
    /// returning (x, y, width, height) in NDC.
    static func fitRect(contentAspect: Float, into viewAspect: Float) -> SIMD4<Float> {
        guard contentAspect > 0, viewAspect > 0 else {
            return SIMD4<Float>(-1, -1, 2, 2)
        }
        if contentAspect > viewAspect {
            // Content is wider: full width, bars top and bottom.
            let height = 2 * (viewAspect / contentAspect)
            return SIMD4<Float>(-1, -height / 2, 2, height)
        } else {
            let width = 2 * (contentAspect / viewAspect)
            return SIMD4<Float>(-width / 2, -1, width, 2)
        }
    }

    // MARK: - Embedded shader source

    /// Kept byte-identical to `Shaders.metal`; that file is the canonical copy and
    /// the one a precompiled metallib is built from. `tools/sync-shaders.py` checks
    /// the two have not drifted, and CI runs it.
    private static let shaderSource = """
    #include <metal_stdlib>
    using namespace metal;

    struct VertexOut {
        float4 position [[position]];
        float2 uv;
    };

    vertex VertexOut ph_vertex(uint vid [[vertex_id]],
                               constant float4 &rect [[buffer(0)]]) {
        const float2 corners[4] = {
            float2(0.0, 0.0), float2(1.0, 0.0),
            float2(0.0, 1.0), float2(1.0, 1.0)
        };
        const float2 c = corners[vid];

        VertexOut out;
        out.position = float4(rect.x + c.x * rect.z,
                              rect.y + c.y * rect.w,
                              0.0, 1.0);
        out.uv = float2(c.x, 1.0 - c.y);
        return out;
    }

    fragment float4 ph_fragment_direct(VertexOut in [[stage_in]],
                                       texture2d<float> tex [[texture(0)]],
                                       sampler smp [[sampler(0)]]) {
        return float4(tex.sample(smp, in.uv).rgb, 1.0);
    }

    fragment float4 ph_fragment_palette(VertexOut in [[stage_in]],
                                        texture2d<float> indices [[texture(0)]],
                                        texture2d<float> palette [[texture(1)]],
                                        sampler smp [[sampler(0)]],
                                        sampler pal_smp [[sampler(1)]]) {
        const float index = indices.sample(smp, in.uv).r * 255.0;
        const float u = (index + 0.5) / 256.0;
        return float4(palette.sample(pal_smp, float2(u, 0.5)).rgb, 1.0);
    }
    """
}
