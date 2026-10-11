//
// Fullscreen blit of a runtime's framebuffer, with integer-aware scaling and
// palette expansion done on the GPU.
//
// Palette expansion matters more than it looks: many of the engines Porthole targets
// are 8-bit indexed (Doom, Blood, Duke, X-COM, the whole BUILD family), and
// converting 640x480 indices to RGBA on the CPU every frame would waste a chunk of a
// frame budget for something a texture lookup does for free.
//
// SPDX-License-Identifier: GPL-3.0-or-later
//

#include <metal_stdlib>
using namespace metal;

struct VertexOut {
    float4 position [[position]];
    float2 uv;
};

// A fullscreen triangle strip generated from the vertex id, so there is no vertex
// buffer to manage.
vertex VertexOut ph_vertex(uint vid [[vertex_id]],
                           constant float4 &rect [[buffer(0)]]) {
    // rect = (x, y, width, height) in normalised device coordinates, precomputed on
    // the CPU so aspect ratio and letterboxing are not recalculated per vertex.
    const float2 corners[4] = {
        float2(0.0, 0.0), float2(1.0, 0.0),
        float2(0.0, 1.0), float2(1.0, 1.0)
    };
    const float2 c = corners[vid];

    VertexOut out;
    out.position = float4(rect.x + c.x * rect.z,
                          rect.y + c.y * rect.w,
                          0.0, 1.0);
    // Flip V: framebuffers from these engines are top-row-first.
    out.uv = float2(c.x, 1.0 - c.y);
    return out;
}

// Direct sample, for RGBA8888 / BGRA8888 / RGB565. Metal's pixel formats handle the
// channel order and bit depth, so one shader covers all three.
fragment float4 ph_fragment_direct(VertexOut in [[stage_in]],
                                   texture2d<float> tex [[texture(0)]],
                                   sampler smp [[sampler(0)]]) {
    return float4(tex.sample(smp, in.uv).rgb, 1.0);
}

// Palettised: the framebuffer is 8-bit indices in an r8Unorm texture, and the
// palette is 256x1 RGBA.
fragment float4 ph_fragment_palette(VertexOut in [[stage_in]],
                                    texture2d<float> indices [[texture(0)]],
                                    texture2d<float> palette [[texture(1)]],
                                    sampler smp [[sampler(0)]],
                                    sampler pal_smp [[sampler(1)]]) {
    // r8Unorm gives 0..1; scale back to an index and land on the texel centre.
    const float index = indices.sample(smp, in.uv).r * 255.0;
    const float u = (index + 0.5) / 256.0;
    return float4(palette.sample(pal_smp, float2(u, 0.5)).rgb, 1.0);
}
