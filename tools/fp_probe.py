"""Phase 0a acceptance probe: verify Camoufox engine + deterministic fingerprints.

Commands:
  draw   [--os macos|windows|linux] [--out identity.json]
         Draw a fingerprint via fpgen and persist it (identity source of truth).
  probe  <identity.json> [--headed] [--out report.json]
         Launch Camoufox with the persisted fingerprint, collect in-page
         fingerprint values, dump a report.
  verify <report1.json> <report2.json>
         Compare two probe reports field-by-field; assert determinism, native
         descriptors, and no automation residue.
  acceptance [--out docs/phase0a-report.md]
         Draw identity A (macos); probe A twice HEADED in separate processes
         (the product always runs headed -- determinism must hold there);
         draw identity B (windows) and assert it differs from A; verify.

Launcher notes (findings baked in):
  * fpgen.yml maps only navigator/screen/window/headers. locale/timezone must
    be provided via `locale=`/`geoip=` (Phase 1 launcher's job), and GPU is
    drawn by camoufox coherent with the screen -- both are by design.
  * navigator.maxTouchPoints is dropped by _cast_to_properties when falsy
    (0 skipped), so a Mac identity on a touchscreen host leaks the real
    digitizer count. The launcher pattern below sets it explicitly.
  * navigator.hardwareConcurrency: we replicate camoufox's no-pin behaviour
    (host count snapped down into PLAUSIBLE_CORE_COUNTS) because setting any
    navigator.* key ourselves disables its internal fix.

Exit code 0 = acceptance passed, 1 = failed.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE_JS = """
async () => {
    const out = {};

    // --- navigator / environment ---
    out.userAgent = navigator.userAgent;
    out.platform = navigator.platform;
    out.oscpu = navigator.oscpu;
    out.hardwareConcurrency = navigator.hardwareConcurrency;
    out.language = navigator.language;
    out.languages = [...navigator.languages];
    out.maxTouchPoints = navigator.maxTouchPoints;
    out.webdriver = navigator.webdriver;
    out.deviceMemory = navigator.deviceMemory !== undefined ? navigator.deviceMemory : null;
    out.doNotTrack = navigator.doNotTrack;
    out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    out.locale = Intl.DateTimeFormat().resolvedOptions().locale;

    // --- screen / window ---
    out.screen = {
        width: screen.width, height: screen.height,
        availWidth: screen.availWidth, availHeight: screen.availHeight,
        colorDepth: screen.colorDepth, pixelDepth: screen.pixelDepth,
    };
    out.window = {
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
        outerWidth: window.outerWidth, outerHeight: window.outerHeight,
        devicePixelRatio: window.devicePixelRatio,
    };

    // --- canvas 2d (raw pixels come back; Python hashes them) ---
    const cv = document.createElement('canvas');
    cv.width = 280; cv.height = 70;
    const ctx = cv.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 280, 0);
    grad.addColorStop(0, '#f13');
    grad.addColorStop(0.5, '#3f9');
    grad.addColorStop(1, '#13f');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 280, 70);
    ctx.font = '17px "Arial"';
    ctx.fillStyle = '#0a2';
    ctx.fillText('ShadowFox probe 你好 Ω≈ç√∫˜µ≤≥', 4, 22);
    ctx.font = '22px "Times New Roman"';
    ctx.fillStyle = '#f30';
    ctx.fillText('Cwm fjordbank glyphs vext quiz', 4, 55);
    out.canvasDataUrl = cv.toDataURL();

    // --- webgl ---
    const glc = document.createElement('canvas').getContext('webgl');
    const dbg = glc && glc.getExtension('WEBGL_debug_renderer_info');
    out.webgl = {
        vendor: glc ? glc.getParameter(glc.VENDOR) : null,
        renderer: glc ? glc.getParameter(glc.RENDERER) : null,
        unmaskedVendor: dbg ? glc.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
        unmaskedRenderer: dbg ? glc.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
        maxTextureSize: glc ? glc.getParameter(glc.MAX_TEXTURE_SIZE) : null,
        glVersion: glc ? glc.getParameter(glc.VERSION) : null,
    };

    // --- audio fingerprint (OfflineAudioContext; runs in the MAIN world,
    //     otherwise TypedArray access trips over Xray wrappers) ---
    try {
        const actx = new OfflineAudioContext(1, 44100, 44100);
        const osc = actx.createOscillator();
        osc.type = 'triangle';
        osc.frequency.value = 10000;
        const comp = actx.createDynamicsCompressor();
        osc.connect(comp); comp.connect(actx.destination);
        osc.start(0);
        const buf = await actx.startRendering();
        const data = buf.getChannelData(0);
        let sum = 0;
        for (let i = 4500; i < 5000; i++) sum += Math.abs(data[i]);
        out.audioSum = sum;
    } catch (e) { out.audioSum = 'ERR:' + e.message; }

    // --- font presence probe (width comparison vs monospace fallback) ---
    const probes = ['Arial', 'Calibri', 'Cambria', 'Courier New', 'Georgia',
        'Helvetica', 'Impact', 'Lucida Grande', 'Palatino', 'Segoe UI',
        'Tahoma', 'Times New Roman', 'Trebuchet MS', 'Verdana', 'Menlo',
        'Geneva', 'San Francisco', 'Consolas', 'Candara', 'Franklin Gothic'];
    const fc = document.createElement('canvas').getContext('2d');
    const fontSig = [];
    for (const f of probes) {
        fc.font = '72px monospace';
        const base = fc.measureText('mmmmmmmmmmlli').width;
        fc.font = `72px "${f}", monospace`;
        fontSig.push([f, Math.round(fc.measureText('mmmmmmmmmmlli').width - base)]);
    }
    out.fontWidths = fontSig;

    // --- native descriptor checks (anti JS-injection) ---
    const nativeGet = (obj, prop) => {
        let o = obj;
        while (o) {
            const d = Object.getOwnPropertyDescriptor(o, prop);
            if (d) {
                if (!d.get) return 'NOT_A_GETTER';
                return d.get.toString().includes('[native code]') ? 'native' : 'PATCHED';
            }
            o = Object.getPrototypeOf(o);
        }
        return 'MISSING';
    };
    out.descriptors = {
        userAgent: nativeGet(navigator, 'userAgent'),
        platform: nativeGet(navigator, 'platform'),
        oscpu: nativeGet(navigator, 'oscpu'),
        hardwareConcurrency: nativeGet(navigator, 'hardwareConcurrency'),
        language: nativeGet(navigator, 'language'),
        webdriver: nativeGet(navigator, 'webdriver'),
    };

    // --- automation residue globals ---
    const residue = [];
    for (const k of ['__playwright', '__playwright__', '__pw_manual',
        '__nightmare', '_selenium', 'calledSelenium', '_phantom', '__phantomas',
        'domAutomation', 'domAutomationController', '__webdriver_evaluate',
        '__fxdriver_evaluate', '__driver_evaluate']) {
        if (window[k] !== undefined) residue.push(k);
    }
    out.automationResidue = residue;

    return out;
}
"""

# Window placement legitimately varies between launches.
VOLATILE_FIELDS = {"screenX", "screenY"}

# camoufox.fingerprints.PLAUSIBLE_CORE_COUNTS (copied: launcher replicates the
# no-pin host-snap behaviour because we set navigator.* keys ourselves)
PLAUSIBLE_CORE_COUNTS = (4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32)


def _host_snapped_cores() -> int:
    try:
        n = len(__import__("os").sched_getaffinity(0))
    except AttributeError:
        n = __import__("os").cpu_count() or 8
    allowed = [c for c in PLAUSIBLE_CORE_COUNTS if c <= n]
    return allowed[-1] if allowed else PLAUSIBLE_CORE_COUNTS[0]


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def cmd_draw(args):
    from camoufox.fingerprints import generate_fingerprint

    fp = generate_fingerprint(os=args.os)
    fp_dict = fp if isinstance(fp, dict) else fp.__dict__
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fp_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    nav = fp_dict.get("navigator", {})
    print(f"[draw] identity saved -> {out}")
    print(f"[draw]   UA: {nav.get('userAgent')}")
    print(f"[draw]   platform: {nav.get('platform')} | maxTouchPoints: {nav.get('maxTouchPoints')}")
    return 0


def _postprocess(report: dict) -> dict:
    data = report["data"]
    if data.get("canvasDataUrl"):
        data["canvasHash"] = _sha256(data.pop("canvasDataUrl"))
    return report


def collect_report(identity_path, headed, out_path):
    from camoufox.sync_api import Camoufox

    fp_dict = json.loads(Path(identity_path).read_text(encoding="utf-8"))
    nav = fp_dict.get("navigator", {})

    # Launcher pattern: the identity's own touch count, and the host's
    # snapped core count (setting navigator.* disables camoufox's internal
    # fixes, so we replicate fix_hardware_concurrency's no-pin branch).
    explicit_config = {
        "navigator.maxTouchPoints": int(nav.get("maxTouchPoints") or 0),
        "navigator.hardwareConcurrency": _host_snapped_cores(),
    }

    with Camoufox(
        fingerprint=fp_dict,
        config=explicit_config,
        i_know_what_im_doing=True,
        main_world_eval=True,
        headless=not headed,
        humanize=True,
        enable_cache=False,
    ) as browser:
        page = browser.new_page()
        page.goto("about:blank")
        data = page.evaluate("mw:" + PROBE_JS)
        shot = None
        if headed:
            shot_path = Path(out_path).with_suffix(".png")
            page.screenshot(path=str(shot_path))
            shot = str(shot_path)

    report = _postprocess({
        "identity_file": str(identity_path),
        "headed": headed,
        "explicit_config": explicit_config,
        "data": data,
    })
    Path(out_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[probe] report -> {out_path}" + (f" (screenshot {shot})" if shot else ""))
    return report


def cmd_probe(args):
    collect_report(args.identity, args.headed, args.out)
    return 0


def fp_hash(data):
    stable = {k: v for k, v in data.items() if k not in VOLATILE_FIELDS}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return _sha256(blob)


def cmd_verify(args):
    r1 = json.loads(Path(args.report1).read_text(encoding="utf-8"))
    r2 = json.loads(Path(args.report2).read_text(encoding="utf-8"))
    d1, d2 = r1["data"], r2["data"]

    failures = []

    keys = sorted(set(d1) | set(d2))
    for k in keys:
        if k in VOLATILE_FIELDS:
            continue
        if d1.get(k) != d2.get(k):
            failures.append(f"nondeterministic field: {k}: {d1.get(k)!r} != {d2.get(k)!r}")

    h1, h2 = fp_hash(d1), fp_hash(d2)
    print(f"[verify] fingerprint hash run1: {h1[:16]}...")
    print(f"[verify] fingerprint hash run2: {h2[:16]}...")
    if h1 != h2:
        failures.append(f"fingerprint hash mismatch: {h1} != {h2}")

    for field, verdict in (d1.get("descriptors") or {}).items():
        if verdict not in ("native", "NOT_A_GETTER"):
            failures.append(f"descriptor not native: {field} -> {verdict}")

    if d1.get("automationResidue"):
        failures.append(f"automation residue globals: {d1['automationResidue']}")
    if d1.get("webdriver"):
        failures.append("navigator.webdriver is true")

    print(f"[verify] UA: {d1.get('userAgent')}")
    print(f"[verify] platform: {d1.get('platform')} | cores: {d1.get('hardwareConcurrency')}")
    print(f"[verify] maxTouchPoints: {d1.get('maxTouchPoints')}")
    print(f"[verify] screen: {d1.get('screen')}")
    print(f"[verify] webgl: {d1.get('webgl', {}).get('unmaskedRenderer')}")
    print(f"[verify] timezone: {d1.get('timezone')} | locale: {d1.get('locale')}")
    print(f"[verify] audioSum: {d1.get('audioSum')}")
    fonts = [f for f, w in (d1.get("fontWidths") or []) if w != 0]
    print(f"[verify] fonts present: {', '.join(fonts[:12])}")

    if failures:
        print("\n[verify] FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n[verify] PASS: deterministic + native + residue-free")
    return 0


def cmd_acceptance(args):
    tmp = Path(tempfile.mkdtemp(prefix="shadowfox-p0a-"))
    here = Path(__file__).resolve()

    def probe_subprocess(identity, headed, out):
        rc = subprocess.run(
            [sys.executable, str(here), "probe", str(identity),
             "--out", str(out)] + (["--headed"] if headed else []),
            cwd=str(tmp), check=False,
        ).returncode
        if rc != 0:
            print(f"[acceptance] probe subprocess failed rc={rc}")
            sys.exit(1)

    print("=== [1/4] draw identity A (macos) ===")
    ident_a = tmp / "identity-a.json"
    cmd_draw(argparse.Namespace(os="macos", out=str(ident_a)))

    print("=== [2/4] probe A twice, HEADED, in separate processes ===")
    probe_subprocess(ident_a, headed=True, out=tmp / "a1.json")
    probe_subprocess(ident_a, headed=True, out=tmp / "a2.json")

    rc = cmd_verify(argparse.Namespace(
        report1=str(tmp / "a1.json"), report2=str(tmp / "a2.json")))

    print("=== [3/4] draw identity B (windows), assert it differs from A ===")
    ident_b = tmp / "identity-b.json"
    cmd_draw(argparse.Namespace(os="windows", out=str(ident_b)))
    probe_subprocess(ident_b, headed=False, out=tmp / "b1.json")

    a1 = json.loads((tmp / "a1.json").read_text(encoding="utf-8"))
    a2 = json.loads((tmp / "a2.json").read_text(encoding="utf-8"))
    b1 = json.loads((tmp / "b1.json").read_text(encoding="utf-8"))
    da = a1["data"]

    extra = []
    if "Mac" not in (da.get("platform") or ""):
        extra.append(f"identity A platform is not Mac-like: {da.get('platform')}")
    if "Macintosh" not in (da.get("userAgent") or ""):
        extra.append("identity A UA does not claim Macintosh")
    # The launcher sets this explicitly; a non-zero value here means the
    # digitizer leaked despite the explicit config (or the draw was odd).
    if da.get("maxTouchPoints") != 0:
        extra.append(f"macOS identity with maxTouchPoints {da.get('maxTouchPoints')} (expected 0)")
    if da.get("hardwareConcurrency") != _host_snapped_cores():
        extra.append(f"cores {da.get('hardwareConcurrency')} != host snapped {_host_snapped_cores()}")
    if fp_hash(b1["data"]) == fp_hash(da):
        extra.append("identity B (windows) presents the same fingerprint as A")
    if "Windows" not in (b1["data"].get("userAgent") or ""):
        extra.append(f"identity B UA is not Windows: {b1['data'].get('userAgent')}")
    if b1["data"].get("webgl", {}).get("unmaskedRenderer", "").startswith("ANGLE") is False:
        extra.append(f"identity B WebGL not ANGLE-style: {b1['data'].get('webgl', {}).get('unmaskedRenderer')}")
    if da.get("audioSum") in (None, "") or str(da.get("audioSum", "")).startswith("ERR"):
        extra.append(f"audio fingerprint failed: {da.get('audioSum')}")

    descriptors_ok = all(
        v in ("native", "NOT_A_GETTER") for v in da.get("descriptors", {}).values()
    )
    screenshot_ok = (tmp / "a1.png").exists()

    lines = [
        "# Phase 0a 验收报告 — Camoufox 引擎验证",
        "",
        f"- 身份文件: A={ident_a} | B={ident_b}",
        f"- 报告目录: {tmp}",
        "",
        "## 采集的指纹（A, headed run1）",
        "",
        f"- UA: `{da.get('userAgent')}`",
        f"- platform/oscpu: `{da.get('platform')}` / `{da.get('oscpu')}`",
        f"- cores: {da.get('hardwareConcurrency')} | languages: {da.get('languages')}",
        f"- maxTouchPoints: {da.get('maxTouchPoints')}（launcher 显式设置，防触摸屏宿主泄漏）",
        f"- screen: `{da.get('screen')}` | window: `{da.get('window')}`",
        f"- timezone: {da.get('timezone')} | Intl locale: {da.get('locale')}",
        f"- WebGL unmasked: `{da.get('webgl', {}).get('unmaskedRenderer')}`",
        f"- canvasHash: `{da.get('canvasHash')}` | audioSum: {da.get('audioSum')}",
        f"- descriptors: `{da.get('descriptors')}`",
        f"- automationResidue: {da.get('automationResidue')}",
        "",
        "## 结论",
        "",
        f"- 跨重启一致性（headed 双进程）: {'PASS' if rc == 0 else 'FAIL'} (hash `{fp_hash(da)[:16]}…`)",
        f"- 引擎原生注入（无 JS patch 痕迹）: {'PASS' if descriptors_ok else 'FAIL'}",
        f"- 无自动化残留/webdriver: {'PASS' if not da.get('automationResidue') and not da.get('webdriver') else 'FAIL'}",
        f"- headed 窗口打开+截图: {'PASS' if screenshot_ok else 'FAIL'}",
        f"- 身份 B(windows) 与 A 互异: {'PASS' if fp_hash(b1['data']) != fp_hash(da) else 'FAIL'}",
        f"- audio 指纹（主世界采集）: {'PASS' if not str(da.get('audioSum', 'ERR')).startswith('ERR') else 'FAIL'}",
    ]
    for e in extra:
        lines.append(f"- 额外检查: FAIL — {e}")
    if not extra:
        lines.append("- 额外检查: PASS（Mac 身份零触摸点、核心数=宿主快照、B 身份独立、B 的 WebGL 为 ANGLE 风格）")
    rc_final = rc + (1 if extra else 0)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[acceptance] report -> {out}")
    print(f"[acceptance] RESULT: {'PASS' if rc_final == 0 else 'FAIL'}")
    return rc_final


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("draw")
    p.add_argument("--os", default="macos", choices=["macos", "windows", "linux"])
    p.add_argument("--out", default="identity.json")

    p = sub.add_parser("probe")
    p.add_argument("identity")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--out", default="report.json")

    p = sub.add_parser("verify")
    p.add_argument("report1")
    p.add_argument("report2")

    p = sub.add_parser("acceptance")
    p.add_argument("--out", default="docs/phase0a-report.md")

    args = ap.parse_args()
    return {
        "draw": cmd_draw,
        "probe": cmd_probe,
        "verify": cmd_verify,
        "acceptance": cmd_acceptance,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
