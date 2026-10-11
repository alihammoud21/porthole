/*
 * porthole_runtime.h — the one interface every runtime is adapted to.
 *
 * The shell drives engines through this ABI and never knows whether it is talking
 * to a SNES core, DOSBox, or OpenMW. libretro cores get a thin shim (libretro is
 * already approximately this shape); native engines get a per-engine adapter, which
 * is where most of the per-runtime work lives.
 *
 * Design rules, learned from libretro's mistakes and kept deliberately strict:
 *
 *   1. The HOST owns all memory and the main loop. A runtime never calls malloc for
 *      anything the host must free, never spawns its own window, and never blocks.
 *   2. ph_frame() is called once per display refresh and must return promptly. A
 *      runtime that needs its own thread manages it internally and presents the
 *      most recent complete frame.
 *   3. Everything is C. No C++ types cross this boundary, so Swift can import it
 *      directly and any engine language can implement it.
 *   4. Versioned. ph_abi_version() is checked before anything else is called.
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef PORTHOLE_RUNTIME_H
#define PORTHOLE_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PH_ABI_VERSION 1

/* ───────────────────────────────── diagnostics ───────────────────────────────── */

typedef enum {
    PH_LOG_DEBUG = 0,
    PH_LOG_INFO  = 1,
    PH_LOG_WARN  = 2,
    PH_LOG_ERROR = 3,
} ph_log_level;

/* Host-provided logger. Runtimes must not write to stdout/stderr directly: on iOS
 * nobody will ever see it. */
typedef void (*ph_log_fn)(ph_log_level level, const char *msg, void *userdata);

/* ───────────────────────────────── configuration ───────────────────────────────── */

typedef struct {
    const char *key;
    const char *value;
} ph_option;

typedef struct {
    /* Absolute path to the game's asset root, inside the app container. Read-only
     * by convention; a runtime that needs scratch space uses save_dir. */
    const char *asset_root;

    /* Absolute path to a writable directory for saves and configuration. Survives
     * app re-signing, which is why it is separate from the bundle. */
    const char *save_dir;

    /* Recipe-declared options, as parsed from the recipe's [runtime_options]. */
    const ph_option *options;
    size_t           option_count;

    /* Display the host will present into. A runtime may render smaller and let the
     * host scale; it must not render larger. */
    uint32_t max_width;
    uint32_t max_height;

    /* Audio format the host will consume. Fixed for the session. */
    uint32_t sample_rate;     /* typically 48000 */
    uint8_t  channels;        /* 1 or 2 */

    ph_log_fn log;
    void     *log_userdata;
} ph_config;

/* ───────────────────────────────── input ───────────────────────────────── */

/* Abstract buttons. The shell maps touch overlays, MFi controllers, and hardware
 * keyboards onto these, so a runtime never sees a layout or an input device.
 * Engines that want scancodes get them through ph_input.keys instead. */
typedef enum {
    PH_BTN_UP = 0, PH_BTN_DOWN, PH_BTN_LEFT, PH_BTN_RIGHT,
    PH_BTN_A, PH_BTN_B, PH_BTN_X, PH_BTN_Y,
    PH_BTN_L1, PH_BTN_R1, PH_BTN_L2, PH_BTN_R2,
    PH_BTN_START, PH_BTN_SELECT,
    PH_BTN_COUNT
} ph_button;

typedef enum {
    PH_AXIS_LEFT_X = 0, PH_AXIS_LEFT_Y,
    PH_AXIS_RIGHT_X,    PH_AXIS_RIGHT_Y,
    PH_AXIS_COUNT
} ph_axis;

typedef struct {
    /* Bitmask over ph_button. */
    uint32_t buttons;

    /* -1.0 .. 1.0, already deadzoned and normalised by the host. */
    float axes[PH_AXIS_COUNT];

    /* Pointer state, in the runtime's own framebuffer coordinates. For absolute
     * (direct-touch) layouts this is where the finger is; for relative (trackpad)
     * layouts the host integrates movement and reports a virtual cursor. Either way
     * the runtime just sees a mouse. */
    bool    pointer_active;
    int32_t pointer_x;
    int32_t pointer_y;
    int32_t pointer_dx;      /* delta since last frame, for mouse-look */
    int32_t pointer_dy;
    uint8_t pointer_buttons; /* bit 0 left, 1 right, 2 middle */

    /* Raw keyboard, for engines that want scancodes. USB HID usage codes, which is
     * what both iOS and SDL ultimately speak. NULL when nothing is pressed. */
    const uint16_t *keys;
    size_t          key_count;

    /* Monotonic microseconds since ph_open(). Runtimes must use this rather than
     * calling into the clock themselves, so that pausing and frame-stepping work. */
    uint64_t time_us;
} ph_input;

/* ───────────────────────────────── output ───────────────────────────────── */

typedef enum {
    PH_PIX_RGBA8888 = 0,
    PH_PIX_BGRA8888,
    PH_PIX_RGB565,
    PH_PIX_PAL8,        /* 8-bit indexed; palette must be supplied */
} ph_pixel_format;

typedef struct {
    /* Set by the runtime each frame. The host does not take ownership and will have
     * finished with the pixels before the next ph_frame() call, so a runtime may
     * hand over a pointer into its own framebuffer. */
    const void     *pixels;
    uint32_t        width;
    uint32_t        height;
    size_t          pitch;          /* bytes per row */
    ph_pixel_format format;

    /* 256 entries of 0xAARRGGBB, required for PH_PIX_PAL8 and ignored otherwise.
     * Many of the engines Porthole targets are palettised, and converting on the
     * CPU every frame would be wasteful when the GPU can do it in a shader. */
    const uint32_t *palette;

    /* Set to true when the runtime rendered nothing new; the host reuses the
     * previous frame and skips a texture upload. */
    bool skipped;

    /* Display aspect ratio, when it differs from width/height (CRT pixel aspect,
     * anamorphic PSX modes). 0 means "use width/height". */
    float aspect;
} ph_video;

typedef struct {
    /* Interleaved signed 16-bit PCM at ph_config.sample_rate. The runtime writes
     * into host-owned storage; capacity is frames_capacity * channels samples. */
    int16_t *samples;
    size_t   frames_capacity;
    size_t   frames_written;     /* set by the runtime */
} ph_audio;

/* ───────────────────────────────── lifecycle ───────────────────────────────── */

typedef struct ph_runtime ph_runtime;

typedef struct {
    uint8_t *data;
    size_t   size;
} ph_blob;

/* Static description of a runtime, available before anything is opened. */
typedef struct {
    const char *id;              /* matches runtimes/registry.toml */
    const char *name;
    const char *version;
    const char *license;         /* SPDX expression */
    bool        wants_pointer;   /* true for mouse-driven engines */
    bool        wants_keyboard;
    bool        supports_state;  /* ph_save_state / ph_load_state are implemented */
} ph_info;

/* Every runtime exports exactly these seven symbols.
 *
 * In library mode one app hosts many games, and therefore potentially many runtimes
 * -- all of which export these same names. So runtimes are built as frameworks
 * inside the app bundle and loaded with dlopen/dlsym rather than statically linked.
 * That avoids symbol collision, and means one broken runtime fails to load instead
 * of refusing to launch the whole app.
 *
 * The declarations below are what a runtime implements; the typedefs after them are
 * what the host resolves. */

uint32_t        ph_abi_version(void);
const ph_info  *ph_get_info(void);

/* Returns NULL on failure, after logging why through cfg->log. */
ph_runtime     *ph_open(const ph_config *cfg);

void            ph_frame(ph_runtime *rt, const ph_input *in,
                         ph_video *out_video, ph_audio *out_audio);

/* Save states. Optional — ph_info.supports_state says whether these do anything.
 * ph_save_state writes into host-owned storage; if out->size is too small the
 * runtime sets out->size to what it needs and returns false. */
bool            ph_save_state(ph_runtime *rt, ph_blob *out);
bool            ph_load_state(ph_runtime *rt, const ph_blob *in);

void            ph_close(ph_runtime *rt);

/* Resolved by the host via dlsym(). Keep in sync with the declarations above. */
typedef uint32_t       (*ph_abi_version_fn)(void);
typedef const ph_info *(*ph_get_info_fn)(void);
typedef ph_runtime    *(*ph_open_fn)(const ph_config *cfg);
typedef void           (*ph_frame_fn)(ph_runtime *rt, const ph_input *in,
                                      ph_video *out_video, ph_audio *out_audio);
typedef bool           (*ph_save_state_fn)(ph_runtime *rt, ph_blob *out);
typedef bool           (*ph_load_state_fn)(ph_runtime *rt, const ph_blob *in);
typedef void           (*ph_close_fn)(ph_runtime *rt);

/* ───────────────────────────────── helpers ───────────────────────────────── */

static inline bool ph_held(const ph_input *in, ph_button b) {
    return (in->buttons & (1u << (uint32_t)b)) != 0;
}

static inline void ph_log(const ph_config *cfg, ph_log_level lv, const char *msg) {
    if (cfg && cfg->log) cfg->log(lv, msg, cfg->log_userdata);
}

#ifdef __cplusplus
}
#endif

#endif /* PORTHOLE_RUNTIME_H */
