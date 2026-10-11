import Foundation
import os

/// Loads a runtime framework from the app bundle and drives it through the
/// RuntimeHost C ABI.
///
/// Runtimes are `dlopen`ed rather than statically linked, because in library mode one
/// app hosts many games and every runtime exports the same seven symbols. The upside
/// beyond avoiding collisions: a broken runtime fails to load instead of preventing
/// the app from launching at all.
final class RuntimeHost {

    enum LoadError: LocalizedError {
        case notFound(String)
        case dlopenFailed(String, String)
        case missingSymbol(String)
        case abiMismatch(found: UInt32, expected: UInt32)
        case openFailed

        var errorDescription: String? {
            switch self {
            case .notFound(let id):
                return "No runtime named '\(id)' in the app bundle."
            case .dlopenFailed(let id, let err):
                return "Could not load runtime '\(id)': \(err)"
            case .missingSymbol(let sym):
                return "Runtime is missing the required symbol '\(sym)'."
            case .abiMismatch(let found, let expected):
                return """
                    Runtime was built against ABI version \(found), but this shell \
                    speaks version \(expected). Rebuild it with `porthole build`.
                    """
            case .openFailed:
                return "The runtime refused to open. Check the log for why."
            }
        }
    }

    // MARK: - Resolved entry points

    private let handle: UnsafeMutableRawPointer
    private let fnGetInfo: ph_get_info_fn
    private let fnOpen: ph_open_fn
    private let fnFrame: ph_frame_fn
    private let fnSaveState: ph_save_state_fn?
    private let fnLoadState: ph_load_state_fn?
    private let fnClose: ph_close_fn

    // ph_runtime is an opaque forward-declared struct, so Swift imports it as
    // OpaquePointer rather than a typed pointer.
    private var instance: OpaquePointer?

    /// Static description, available before `open()`.
    let info: RuntimeInfo

    struct RuntimeInfo {
        let id: String
        let name: String
        let version: String
        let license: String
        let wantsPointer: Bool
        let wantsKeyboard: Bool
        let supportsState: Bool
    }

    // MARK: - Loading

    /// `id` matches a framework in `Frameworks/<id>.framework` inside the bundle,
    /// which is where `porthole build` puts it.
    init(id: String, bundle: Bundle = .main) throws {
        guard let frameworks = bundle.privateFrameworksURL else {
            throw LoadError.notFound(id)
        }
        let binary = frameworks
            .appendingPathComponent("\(id).framework")
            .appendingPathComponent(id)

        guard FileManager.default.fileExists(atPath: binary.path) else {
            throw LoadError.notFound(id)
        }

        // RTLD_LOCAL keeps each runtime's symbols out of the global namespace, which
        // is the entire point of loading them this way.
        guard let h = dlopen(binary.path, RTLD_NOW | RTLD_LOCAL) else {
            throw LoadError.dlopenFailed(id, String(cString: dlerror()))
        }
        handle = h

        func sym<T>(_ name: String, as _: T.Type) throws -> T {
            guard let raw = dlsym(h, name) else {
                dlclose(h)
                throw LoadError.missingSymbol(name)
            }
            return unsafeBitCast(raw, to: T.self)
        }

        // Check the ABI before calling anything else, so a stale runtime produces a
        // clear message rather than a crash in a struct layout mismatch.
        let version = try sym("ph_abi_version", as: ph_abi_version_fn.self)
        let found = version()
        guard found == UInt32(PH_ABI_VERSION) else {
            dlclose(h)
            throw LoadError.abiMismatch(found: found, expected: UInt32(PH_ABI_VERSION))
        }

        fnGetInfo = try sym("ph_get_info", as: ph_get_info_fn.self)
        fnOpen = try sym("ph_open", as: ph_open_fn.self)
        fnFrame = try sym("ph_frame", as: ph_frame_fn.self)
        fnClose = try sym("ph_close", as: ph_close_fn.self)

        guard let raw = fnGetInfo() else {
            dlclose(h)
            throw LoadError.missingSymbol("ph_get_info returned NULL")
        }
        let i = raw.pointee
        info = RuntimeInfo(
            id: i.id.map { String(cString: $0) } ?? id,
            name: i.name.map { String(cString: $0) } ?? id,
            version: i.version.map { String(cString: $0) } ?? "?",
            license: i.license.map { String(cString: $0) } ?? "?",
            wantsPointer: i.wants_pointer,
            wantsKeyboard: i.wants_keyboard,
            supportsState: i.supports_state
        )

        // Save states are optional; resolve them only if the runtime claims them.
        if info.supportsState {
            fnSaveState = try? sym("ph_save_state", as: ph_save_state_fn.self)
            fnLoadState = try? sym("ph_load_state", as: ph_load_state_fn.self)
        } else {
            fnSaveState = nil
            fnLoadState = nil
        }
    }

    deinit {
        if instance != nil { fnClose(instance) }
        dlclose(handle)
    }

    // MARK: - Session

    private static let log = Logger(subsystem: "app.porthole.shell", category: "runtime")

    /// Trampoline for the C log callback. Runtimes must not touch stdout — on iOS
    /// nobody would ever see it — so everything goes through unified logging.
    private static let logShim: ph_log_fn = { level, msg, _ in
        let text = msg.map { String(cString: $0) } ?? ""
        switch level {
        case PH_LOG_ERROR: RuntimeHost.log.error("\(text, privacy: .public)")
        case PH_LOG_WARN: RuntimeHost.log.warning("\(text, privacy: .public)")
        case PH_LOG_DEBUG: RuntimeHost.log.debug("\(text, privacy: .public)")
        default: RuntimeHost.log.info("\(text, privacy: .public)")
        }
    }

    func open(assetRoot: URL, saveDir: URL, maxSize: (width: UInt32, height: UInt32),
              sampleRate: UInt32, channels: UInt8,
              options: [String: String] = [:]) throws {
        precondition(instance == nil, "runtime already open")

        // Keep the C strings alive for the duration of the ph_open call. ph_config is
        // borrowed, not retained, so this scope is sufficient.
        let assetC = strdup(assetRoot.path)
        let saveC = strdup(saveDir.path)
        defer { free(assetC); free(saveC) }

        var keys: [UnsafeMutablePointer<CChar>?] = []
        var vals: [UnsafeMutablePointer<CChar>?] = []
        for (k, v) in options {
            keys.append(strdup(k))
            vals.append(strdup(v))
        }
        defer {
            keys.forEach { free($0) }
            vals.forEach { free($0) }
        }

        var opts: [ph_option] = (0..<options.count).map {
            ph_option(key: keys[$0], value: vals[$0])
        }

        try opts.withUnsafeMutableBufferPointer { buf in
            var cfg = ph_config(
                asset_root: assetC,
                save_dir: saveC,
                options: buf.baseAddress,
                option_count: buf.count,
                max_width: maxSize.width,
                max_height: maxSize.height,
                sample_rate: sampleRate,
                channels: channels,
                log: RuntimeHost.logShim,
                log_userdata: nil
            )
            guard let rt = fnOpen(&cfg) else { throw LoadError.openFailed }
            instance = rt
        }
    }

    /// Advance one frame. Buffers are owned by the caller and must outlive the call.
    func frame(input: UnsafePointer<ph_input>,
               video: UnsafeMutablePointer<ph_video>,
               audio: UnsafeMutablePointer<ph_audio>) {
        guard let rt = instance else { return }
        fnFrame(rt, input, video, audio)
    }

    func close() {
        guard let rt = instance else { return }
        fnClose(rt)
        instance = nil
    }

    // MARK: - Save states

    /// Two-pass, because the ABI lets a runtime report the size it needs by failing
    /// the first call with `size` updated.
    func saveState() -> Data? {
        guard let rt = instance, let save = fnSaveState else { return nil }

        var probe = ph_blob(data: nil, size: 0)
        _ = save(rt, &probe)
        guard probe.size > 0 else { return nil }

        var buffer = [UInt8](repeating: 0, count: probe.size)
        let ok = buffer.withUnsafeMutableBufferPointer { buf -> Bool in
            var blob = ph_blob(data: buf.baseAddress, size: buf.count)
            guard save(rt, &blob) else { return false }
            probe.size = blob.size
            return true
        }
        guard ok else { return nil }
        return Data(buffer.prefix(probe.size))
    }

    func loadState(_ data: Data) -> Bool {
        guard let rt = instance, let load = fnLoadState, !data.isEmpty else { return false }
        var bytes = [UInt8](data)
        return bytes.withUnsafeMutableBufferPointer { buf -> Bool in
            var blob = ph_blob(data: buf.baseAddress, size: buf.count)
            return load(rt, &blob)
        }
    }
}
