/*
 * selftest — the reference RuntimeHost implementation.
 *
 * Not a game. This exists so the pipeline (cross-compile → bundle → sign → install
 * → run) can be verified end to end without first building a real engine's
 * dependency tree, and so anyone writing a new adapter has a known-good example of
 * every part of the ABI in about 200 lines.
 *
 * It draws a test pattern, visualises live input, emits an audio tone whose pitch
 * tracks the left stick, and implements save states. If this runs on your phone,
 * the shell and the ABI work, and any failure after this point is the engine
 * adapter's fault rather than the plumbing's.
 *
 * SPDX-License-Identifier: MIT
 */

#include "porthole_runtime.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define FB_W 640
#define FB_H 360
#define TAU 6.283185307179586f

struct ph_runtime {
    uint32_t  framebuffer[FB_W * FB_H];
    uint64_t  frames;
    float     phase;          /* audio oscillator phase */
    int32_t   cursor_x;
    int32_t   cursor_y;
    uint32_t  last_buttons;
    uint32_t  sample_rate;
    uint8_t   channels;
    ph_config cfg;
};

/* Save-state payload. Deliberately versioned and fixed-layout: a real runtime that
 * changes this must bump the version and refuse older blobs rather than
 * misinterpreting them. */
#define STATE_MAGIC   0x50485354u   /* "PHST" */
#define STATE_VERSION 1

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint64_t frames;
    float    phase;
    int32_t  cursor_x;
    int32_t  cursor_y;
} selftest_state;

/* ───────────────────────────── static description ───────────────────────────── */

static const ph_info INFO = {
    .id             = "selftest",
    .name           = "Porthole self-test",
    .version        = "1.0.0",
    .license        = "MIT",
    .wants_pointer  = true,
    .wants_keyboard = false,
    .supports_state = true,
};

uint32_t ph_abi_version(void) { return PH_ABI_VERSION; }
const ph_info *ph_get_info(void) { return &INFO; }

/* ───────────────────────────────── lifecycle ───────────────────────────────── */

ph_runtime *ph_open(const ph_config *cfg) {
    if (!cfg) return NULL;

    ph_runtime *rt = calloc(1, sizeof(*rt));
    if (!rt) {
        ph_log(cfg, PH_LOG_ERROR, "selftest: out of memory");
        return NULL;
    }

    rt->cfg         = *cfg;
    rt->sample_rate = cfg->sample_rate ? cfg->sample_rate : 48000;
    rt->channels    = cfg->channels ? cfg->channels : 2;
    rt->cursor_x    = FB_W / 2;
    rt->cursor_y    = FB_H / 2;

    ph_log(cfg, PH_LOG_INFO, "selftest: opened");
    return rt;
}

void ph_close(ph_runtime *rt) {
    if (!rt) return;
    ph_log(&rt->cfg, PH_LOG_INFO, "selftest: closed");
    free(rt);
}

/* ───────────────────────────────── drawing ───────────────────────────────── */

static inline uint32_t rgba(uint8_t r, uint8_t g, uint8_t b) {
    return 0xFF000000u | ((uint32_t)b << 16) | ((uint32_t)g << 8) | r;
}

static void fill_rect(ph_runtime *rt, int x, int y, int w, int h, uint32_t c) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > FB_W) w = FB_W - x;
    if (y + h > FB_H) h = FB_H - y;
    for (int row = 0; row < h; row++) {
        uint32_t *p = &rt->framebuffer[(size_t)(y + row) * FB_W + x];
        for (int col = 0; col < w; col++) p[col] = c;
    }
}

static void draw_pattern(ph_runtime *rt) {
    /* A gradient that shifts with time, so a frozen frame is obvious at a glance. */
    const float t = (float)rt->frames * 0.01f;
    for (int y = 0; y < FB_H; y++) {
        const uint8_t g = (uint8_t)(y * 255 / FB_H);
        for (int x = 0; x < FB_W; x++) {
            const uint8_t r = (uint8_t)(x * 255 / FB_W);
            const uint8_t b = (uint8_t)(127.5f + 127.5f * sinf(t + (float)x * 0.01f));
            rt->framebuffer[(size_t)y * FB_W + x] = rgba(r, g, b);
        }
    }

    /* Corner markers, to confirm nothing is cropped or letterboxed wrongly. */
    const uint32_t white = rgba(255, 255, 255);
    fill_rect(rt, 0, 0, 24, 8, white);
    fill_rect(rt, 0, 0, 8, 24, white);
    fill_rect(rt, FB_W - 24, 0, 24, 8, white);
    fill_rect(rt, FB_W - 8, 0, 8, 24, white);
    fill_rect(rt, 0, FB_H - 8, 24, 8, white);
    fill_rect(rt, 0, FB_H - 24, 8, 24, white);
    fill_rect(rt, FB_W - 24, FB_H - 8, 24, 8, white);
    fill_rect(rt, FB_W - 8, FB_H - 24, 8, 24, white);
}

static void draw_input(ph_runtime *rt, const ph_input *in) {
    /* One lamp per abstract button, lit while held. Confirms the whole input path:
     * touch overlay or controller → InputRouter → layout binding → ph_button. */
    const int size = 20, gap = 6, x0 = 20, y0 = 20;
    for (int i = 0; i < PH_BTN_COUNT; i++) {
        const bool held = ph_held(in, (ph_button)i);
        const int x = x0 + (i % 7) * (size + gap);
        const int y = y0 + (i / 7) * (size + gap);
        fill_rect(rt, x, y, size, size,
                  held ? rgba(80, 255, 120) : rgba(30, 30, 40));
    }

    /* Analog sticks as two dots in two boxes. */
    for (int s = 0; s < 2; s++) {
        const int bx = x0 + s * 90, by = y0 + 70, half = 34;
        fill_rect(rt, bx, by, half * 2, half * 2, rgba(24, 24, 32));
        const float ax = in->axes[s == 0 ? PH_AXIS_LEFT_X : PH_AXIS_RIGHT_X];
        const float ay = in->axes[s == 0 ? PH_AXIS_LEFT_Y : PH_AXIS_RIGHT_Y];
        const int dx = (int)(ax * (float)(half - 6));
        const int dy = (int)(ay * (float)(half - 6));
        fill_rect(rt, bx + half + dx - 4, by + half + dy - 4, 8, 8,
                  rgba(255, 200, 60));
    }

    /* Pointer crosshair. Absolute layouts place it; relative layouts integrate. */
    if (in->pointer_active) {
        rt->cursor_x = in->pointer_x;
        rt->cursor_y = in->pointer_y;
    } else {
        rt->cursor_x += in->pointer_dx;
        rt->cursor_y += in->pointer_dy;
    }
    if (rt->cursor_x < 0) rt->cursor_x = 0;
    if (rt->cursor_y < 0) rt->cursor_y = 0;
    if (rt->cursor_x >= FB_W) rt->cursor_x = FB_W - 1;
    if (rt->cursor_y >= FB_H) rt->cursor_y = FB_H - 1;

    const uint32_t c = in->pointer_buttons ? rgba(255, 80, 80) : rgba(255, 255, 255);
    fill_rect(rt, rt->cursor_x - 10, rt->cursor_y - 1, 21, 3, c);
    fill_rect(rt, rt->cursor_x - 1, rt->cursor_y - 10, 3, 21, c);
}

/* ───────────────────────────────── per-frame ───────────────────────────────── */

void ph_frame(ph_runtime *rt, const ph_input *in,
              ph_video *out_video, ph_audio *out_audio) {
    if (!rt || !in) return;

    rt->frames++;
    draw_pattern(rt);
    draw_input(rt, in);
    rt->last_buttons = in->buttons;

    if (out_video) {
        out_video->pixels  = rt->framebuffer;
        out_video->width   = FB_W;
        out_video->height  = FB_H;
        out_video->pitch   = FB_W * sizeof(uint32_t);
        out_video->format  = PH_PIX_RGBA8888;
        out_video->palette = NULL;
        out_video->skipped = false;
        out_video->aspect  = 0.0f;
    }

    /* A tone whose pitch follows the left stick, so audio and input can be checked
     * together. Silent unless a button is held — nobody wants a test tone on loop. */
    if (out_audio && out_audio->samples && out_audio->frames_capacity) {
        const bool audible = in->buttons != 0;
        const float base = 220.0f;
        const float bend = in->axes[PH_AXIS_LEFT_Y] * -0.5f;
        const float freq = base * powf(2.0f, bend);
        const float step = TAU * freq / (float)rt->sample_rate;

        for (size_t f = 0; f < out_audio->frames_capacity; f++) {
            const int16_t v = audible
                ? (int16_t)(sinf(rt->phase) * 6000.0f)
                : 0;
            for (uint8_t ch = 0; ch < rt->channels; ch++)
                out_audio->samples[f * rt->channels + ch] = v;
            rt->phase += step;
            if (rt->phase > TAU) rt->phase -= TAU;
        }
        out_audio->frames_written = out_audio->frames_capacity;
    }
}

/* ───────────────────────────────── save states ───────────────────────────────── */

bool ph_save_state(ph_runtime *rt, ph_blob *out) {
    if (!rt || !out) return false;

    if (out->size < sizeof(selftest_state)) {
        out->size = sizeof(selftest_state);   /* tell the host how much we need */
        return false;
    }

    selftest_state s = {
        .magic    = STATE_MAGIC,
        .version  = STATE_VERSION,
        .frames   = rt->frames,
        .phase    = rt->phase,
        .cursor_x = rt->cursor_x,
        .cursor_y = rt->cursor_y,
    };
    memcpy(out->data, &s, sizeof(s));
    out->size = sizeof(s);
    return true;
}

bool ph_load_state(ph_runtime *rt, const ph_blob *in) {
    if (!rt || !in || !in->data || in->size < sizeof(selftest_state)) return false;

    selftest_state s;
    memcpy(&s, in->data, sizeof(s));

    if (s.magic != STATE_MAGIC) {
        ph_log(&rt->cfg, PH_LOG_ERROR, "selftest: save state magic mismatch");
        return false;
    }
    if (s.version != STATE_VERSION) {
        ph_log(&rt->cfg, PH_LOG_WARN, "selftest: refusing save state from another version");
        return false;
    }

    rt->frames   = s.frames;
    rt->phase    = s.phase;
    rt->cursor_x = s.cursor_x;
    rt->cursor_y = s.cursor_y;
    return true;
}
