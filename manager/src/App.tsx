import { useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import {
  ClashConfig, CreateRequest, DataOverview, EditRequest, ExtensionItem, ExtensionSearchResult, HistoryItem, Identity, ProxyNode, ProxySource,
  cancelRuntime, installRuntime, runtimeStatus, selectPython, type RuntimeStatus,
  clashConfigs, cloneIdentity, createIdentity, dataOverview, deleteIdentity, editIdentity, environmentCheck,
  exportAllData, exportCookies, exportPack, extImport, extInstall, extList, extRemove, extSearch, importAllData, importPack, launchHistory, launchIdentity, listIdentities, openDataDir,
  proxyDelete, proxyImport, proxyNodes, proxyRename, proxySetCore, proxySources, rebuildIdentity, reorderIdentities, stopIdentity, type EnvironmentCheck,
} from "./api";
import Flag from "./Flag";

const APP_ICON = new URL("../app-icon.png", import.meta.url).href;

const OS_OPTIONS = [
  { value: "", label: "自动匹配" },
  { value: "windows", label: "Windows" },
  { value: "macos", label: "macOS" },
  { value: "linux", label: "Linux" },
];
const COUNTRY_OPTIONS = [
  ["", "自动选择"], ["US", "美国"], ["CA", "加拿大"], ["GB", "英国"],
  ["FR", "法国"], ["DE", "德国"], ["ES", "西班牙"], ["IT", "意大利"],
  ["NL", "荷兰"], ["SE", "瑞典"], ["CH", "瑞士"], ["AU", "澳大利亚"],
  ["JP", "日本"], ["KR", "韩国"], ["SG", "新加坡"], ["IN", "印度"],
  ["BR", "巴西"], ["CN", "中国"], ["TW", "中国台湾"], ["HK", "中国香港"],
] as const;
const OS_LABELS: Record<string, string> = { windows: "Windows", macos: "macOS", linux: "Linux" };
const OS_ICONS: Record<string, string> = { windows: "▣", macos: "●", linux: "◆" };

type View = "overview" | "environments" | "proxy" | "extensions" | "history";
const VIEW_LABEL: Record<View, string> = {
  overview: "总览", environments: "浏览器环境", proxy: "代理管理", extensions: "扩展中心", history: "启动记录",
};
const EVENT_LABEL: Record<string, string> = { launch: "启动", stop: "停止", closed: "关闭窗口" };
const EXT_SOURCE_LABEL: Record<string, string> = { engine: "引擎内置", amo: "官方商店", local: "本地导入" };

function formatUsers(count: number): string {
  if (count >= 10000) return `${(count / 10000).toFixed(count >= 100000 ? 0 : 1)} 万`;
  return String(count);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatStamp(seconds: number): string {
  if (!seconds) return "—";
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function emptyForm(): CreateRequest { return { name: "", note: "", os: "", country: "", network: "direct", ui_locale: "zh-CN", memory_cache: true }; }

/// Notes written before the multiline input existed may contain escaped line
/// breaks ("\n") or the "/n" users typed as a workaround; render both as
/// real breaks so the bubble matches what was intended.
function noteForTooltip(note: string): string {
  return note.replace(/\\n|\/n/g, "\n");
}

/// The table row is a single line: strip any breaks so notes never introduce
/// blank space or wrap oddly there.
function inlineNote(note: string): string {
  return noteForTooltip(note).replace(/\s*\n+\s*/g, " ").trim();
}

function Modal(props: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="overlay" onClick={props.onClose}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">CACER</div><h2>{props.title}</h2></div><button className="icon-button" onClick={props.onClose} aria-label="关闭">×</button></div>
      {props.children}
    </div>
  </div>;
}

function Icon({ children }: { children: ReactNode }) { return <span className="nav-icon">{children}</span>; }

export default function App() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [environment, setEnvironment] = useState<EnvironmentCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const busyRef = useRef(new Set<string>());
  const nodeRequests = useRef({ create: 0, edit: 0 });
  const refreshRequest = useRef<Promise<void> | null>(null);
  const refreshQueued = useRef(false);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [form, setForm] = useState<CreateRequest>(emptyForm());
  const [editTarget, setEditTarget] = useState<Identity | null>(null);
  const [editForm, setEditForm] = useState<EditRequest>({});
  const [netChoice, setNetChoice] = useState<"direct" | "sub" | "custom">("direct");
  const [editNetChoice, setEditNetChoice] = useState<"direct" | "sub" | "custom">("direct");
  const [guide, setGuide] = useState<"python" | "engine" | "fonts" | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const runtimeBusyRef = useRef(false);
  const [downloadState, setDownloadState] = useState<RuntimeStatus | null>(null);
  const [downloadProxy, setDownloadProxy] = useState("");
  const [pythonPath, setPythonPath] = useState("");
  const environmentRef = useRef<EnvironmentCheck | null>(null);
  const [copied, setCopied] = useState(false);
  const [proxySourceList, setProxySourceList] = useState<ProxySource[]>([]);
  const [proxyCore, setProxyCore] = useState<{ found: boolean; path: string | null } | null>(null);
  const [subNodes, setSubNodes] = useState<ProxyNode[]>([]);
  const [editSubNodes, setEditSubNodes] = useState<ProxyNode[]>([]);
  const [localClashConfigs, setLocalClashConfigs] = useState<ClashConfig[]>([]);
  const [showClash, setShowClash] = useState(false);
  const [clashLabels, setClashLabels] = useState<Record<string, string>>({});
  const [subBusy, setSubBusy] = useState<string | null>(null);
  const [view, setView] = useState<View>("environments");
  const [notice, setNotice] = useState<string | null>(null);
  const [dataInfo, setDataInfo] = useState<DataOverview | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [noteTip, setNoteTip] = useState<{ x: number; y: number; above: boolean; text: string } | null>(null);
  const [extItems, setExtItems] = useState<ExtensionItem[]>([]);
  const [extResults, setExtResults] = useState<ExtensionSearchResult[]>([]);
  const [extQuery, setExtQuery] = useState("");
  const [extBusy, setExtBusy] = useState<string | null>(null);
  const [extSearched, setExtSearched] = useState(false);

  // Poll fast only while something is actually transitioning; an idle window
  // does not need a Python process every 3 seconds.
  const hasActive = identities.some((it) => it.running || it.status === "starting");

  useEffect(() => {
    checkEnvironment();
  }, []);
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, hasActive ? 3000 : 10000);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [hasActive]);
  useEffect(() => {
    if (view === "proxy") { loadProxy(); }
    if (view === "extensions") { loadExtensions(); }
    if (view === "history") loadHistory();
    if (view === "overview" || view === "proxy") loadData();
  }, [view]);
  // The webview's native context menu (reload / inspect / print) has no place
  // in an app window; keep it off until a real right-click action exists.
  useEffect(() => {
    const block = (event: MouseEvent) => event.preventDefault();
    document.addEventListener("contextmenu", block);
    return () => document.removeEventListener("contextmenu", block);
  }, []);
  function refresh(afterMutation = false): Promise<void> {
    if (!environmentRef.current?.ready) return Promise.resolve();
    // Polls share a pending read; completed mutations request one fresh read.
    if (refreshRequest.current) {
      if (afterMutation) refreshQueued.current = true;
      return refreshRequest.current;
    }
    refreshQueued.current = true;
    refreshRequest.current = (async () => {
      while (refreshQueued.current) {
        refreshQueued.current = false;
        try { setIdentities(await listIdentities()); }
        catch (e) { setError(String(e)); }
      }
    })().finally(() => { refreshRequest.current = null; });
    return refreshRequest.current;
  }
  async function checkEnvironment() {
    try {
      const result = await environmentCheck();
      environmentRef.current = result;
      setEnvironment(result);
      if (result.ready) { setError(null); await refresh(true); await loadExtensions(); }
      return result;
    } catch (e) { setError(String(e)); return null; }
  }
  async function setupRuntime(kind: "python" | "fonts"): Promise<boolean> {
    if (runtimeBusyRef.current) return false;
    runtimeBusyRef.current = true;
    setRuntimeBusy(true);
    setError(null);
    setDownloadState({ busy: true, message: "正在准备", downloaded: 0, total: 0 });
    const timer = window.setInterval(() => runtimeStatus().then(setDownloadState).catch(() => {}), 500);
    try {
      await installRuntime(kind, downloadProxy);
      await checkEnvironment();
      setNotice(kind === "python" ? "Python 与依赖已准备完成" : "浏览器字体已准备完成，后续可离线使用");
      return true;
    } catch (e) { setError(String(e)); return false; }
    finally {
      window.clearInterval(timer);
      runtimeBusyRef.current = false;
      setRuntimeBusy(false);
      setDownloadState(null);
    }
  }
  async function applyPython() {
    if (runtimeBusyRef.current) return;
    runtimeBusyRef.current = true;
    setRuntimeBusy(true);
    try { await selectPython(pythonPath); await checkEnvironment(); }
    catch (e) { setError(String(e)); }
    finally { runtimeBusyRef.current = false; setRuntimeBusy(false); }
  }
  async function launchPrepared(id: string) {
    if (!environmentRef.current?.ready) { setGuide("python"); return; }
    if (!environmentRef.current.fonts_ready) {
      setGuide("fonts");
      if (!(await setupRuntime("fonts"))) return;
      setGuide(null);
    }
    await launchIdentity(id);
  }
  const failedKeys = environment?.checks.filter((check) => !check.ok).map((check) => check.key) ?? [];
  const pythonMissing = failedKeys.includes("python");
  const engineMissing = failedKeys.includes("engine");
  const guideText = environment?.manual_commands ?? "正在读取安装命令…";
  function openGuide(kind: "python" | "engine" | "fonts") { setCopied(false); setGuide(kind); }
  async function copyGuide() {
    try {
      await navigator.clipboard.writeText(guideText);
    } catch {
      const area = document.createElement("textarea");
      area.value = guideText;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }
  async function withBusy<T>(key: string, op: () => Promise<T>) {
    // The ref also blocks double clicks before React commits the next render.
    if (busyRef.current.has(key)) return;
    busyRef.current.add(key);
    setBusy(new Set(busyRef.current));
    try { await op(); await refresh(true); }
    catch (e) { setError(String(e)); await refresh(true); }
    finally {
      busyRef.current.delete(key);
      setBusy(new Set(busyRef.current));
    }
  }
  async function loadProxy() {
    if (!environmentRef.current?.ready) return [];
    try {
      const overview = await proxySources();
      setProxySourceList(overview.sources);
      setProxyCore(overview.core);
      return overview.sources;
    } catch (e) { setError(String(e)); return []; }
  }
  async function loadNodes(source: string, forEdit: boolean) {
    const slot = forEdit ? "edit" : "create";
    const request = ++nodeRequests.current[slot];
    const update = forEdit ? setEditSubNodes : setSubNodes;
    update([]);
    if (!source) return;
    try {
      const result = await proxyNodes(source);
      if (request === nodeRequests.current[slot]) update(result.nodes);
    } catch (e) {
      if (request === nodeRequests.current[slot]) setError(String(e));
    }
  }
  async function scanClash() {
    setError(null);
    setSubBusy("正在扫描 Clash 配置…");
    try {
      const configs = (await clashConfigs()).configs;
      setLocalClashConfigs(configs);
      setClashLabels(Object.fromEntries(configs.map((c) => [c.path, c.name])));
      setShowClash(true);
      if (!configs.length) flash("没有扫描到包含节点的 Clash 配置");
    } catch (e) { setError(String(e)); }
    finally { setSubBusy(null); }
  }
  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 4000);
  }
  async function loadData() {
    try { setDataInfo(await dataOverview()); } catch (e) { setError(String(e)); }
  }
  async function loadHistory() {
    if (!environmentRef.current?.ready) return;
    try { setHistory((await launchHistory(80)).items); } catch (e) { setError(String(e)); }
  }
  async function loadExtensions() {
    if (!environmentRef.current?.ready) return;
    try { setExtItems((await extList()).extensions); } catch (e) { setError(String(e)); }
  }
  function searchExtensions() {
    const query = extQuery.trim();
    if (!query || extBusy) return;
    setError(null);
    setExtBusy("search");
    extSearch(query, 20)
      .then((data) => { setExtResults(data.results); setExtSearched(true); })
      .catch((e) => setError(String(e)))
      .finally(() => setExtBusy(null));
  }
  function installExtension(slug: string) {
    setError(null);
    setExtBusy(`install-${slug}`);
    extInstall(slug)
      .then(async (item) => {
        await loadExtensions();
        setExtResults((results) => results.map((result) => result.slug === slug ? { ...result, installed: true } : result));
        flash(`已安装 ${item.name}，所有环境默认启用`);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setExtBusy(null));
  }
  function importExtension() {
    const path = window.prompt("导入扩展：填写 .xpi / .zip 安装包的完整路径，或已解压扩展文件夹的路径。", "");
    if (!path?.trim()) return;
    setError(null);
    setExtBusy("import");
    extImport(path.trim())
      .then(async (item) => { await loadExtensions(); flash(`已导入 ${item.name}，所有环境默认启用`); })
      .catch((e) => setError(String(e)))
      .finally(() => setExtBusy(null));
  }
  function removeExtension(item: ExtensionItem) {
    if (!window.confirm(`确定卸载“${item.name}”吗？\n\n卸载后所有环境都不再加载它。`)) return;
    setError(null);
    setExtBusy(`remove-${item.slug}`);
    extRemove(item.slug)
      .then(async () => {
        await loadExtensions();
        setExtResults((results) => results.map((result) => result.slug === item.slug ? { ...result, installed: false } : result));
        flash(`已卸载 ${item.name}`);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setExtBusy(null));
  }
  function toggleEditExtension(slug: string, enabled: boolean) {
    const disabled = editForm.disabled_extensions ?? [];
    setEditForm({
      ...editForm,
      disabled_extensions: enabled
        ? disabled.filter((value) => value !== slug)
        : Array.from(new Set([...disabled, slug])),
    });
  }
  function openDataFolder() { openDataDir().catch((e) => setError(String(e))); }
  function openSettings() { setError(null); setShowSettings(true); loadData(); }
  function openCreate() { if (busyRef.current.has("create")) return; loadNodes("", false); setError(null); setForm(emptyForm()); setNetChoice("direct"); setSubNodes([]); setShowCreate(true); loadProxy(); }
  function chooseSubSource(source: string, forEdit: boolean) {
    if (forEdit) setEditForm({ ...editForm, proxy_source: source, proxy_node: "" });
    else setForm({ ...form, proxy_source: source || null, proxy_node: null });
    loadNodes(source, forEdit);
  }
  async function doImport(kind: "file" | "url", value: string, label = "") {
    setError(null);
    setSubBusy("正在导入订阅…");
    try {
      const result = await proxyImport(kind, value, "", label);
      await loadProxy();
      setSubBusy(`已导入 ${result.label}（${result.count} 个节点）`);
      window.setTimeout(() => setSubBusy(null), 2500);
    } catch (e) { setError(String(e)); setSubBusy(null); }
  }
  function importBy(kind: "file" | "url") {
    const value = window.prompt(kind === "file" ? "Clash 配置文件完整路径" : "Clash 订阅链接（http/https）");
    if (!value?.trim()) return;
    const label = window.prompt("订阅备注名（留空自动命名）", "");
    doImport(kind, value.trim(), (label ?? "").trim());
  }
  function importFromClash(config: ClashConfig) {
    doImport("file", config.path, (clashLabels[config.path] ?? config.name).trim());
  }
  async function importAllClash() {
    if (!localClashConfigs.length) return;
    setError(null);
    try {
      const total = localClashConfigs.length;
      for (let index = 0; index < total; index += 1) {
        const config = localClashConfigs[index];
        setSubBusy(`正在导入 ${index + 1}/${total}：${config.name}`);
        await proxyImport("file", config.path, "", (clashLabels[config.path] ?? config.name).trim());
      }
      await loadProxy();
      setShowClash(false);
      flash(`已导入 ${total} 个 Clash 配置`);
    } catch (e) { setError(String(e)); }
    finally { setSubBusy(null); }
  }
  function renameSource(source: ProxySource) {
    const next = window.prompt(`为「${source.label}」设置备注名（留空恢复默认）`, source.label);
    if (next === null) return;
    setSubBusy("正在保存备注名…");
    proxyRename(source.name, next.trim())
      .then(loadProxy)
      .catch((e) => setError(String(e)))
      .finally(() => setSubBusy(null));
  }
  function removeSource(source: ProxySource) {
    if (!window.confirm(`删除订阅“${source.label}”？使用该订阅节点的环境需要重新选择节点。`)) return;
    setSubBusy("正在删除…");
    proxyDelete(source.name)
      .then(loadProxy)
      .catch((e) => setError(String(e)))
      .finally(() => setSubBusy(null));
  }
  function pickCore() {
    const path = window.prompt("mihomo 内核路径（mihomo.exe）");
    if (!path?.trim()) return;
    setSubBusy("正在检测内核…");
    proxySetCore(path.trim())
      .then(setProxyCore)
      .catch((e) => setError(String(e)))
      .finally(() => setSubBusy(null));
  }

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return identities;
    return identities.filter((it) => [it.name, it.note, it.country, it.os, it.proxy_server ?? "", it.proxy_node ?? ""].join(" ").toLowerCase().includes(q));
  }, [identities, search]);
  const running = identities.filter((it) => it.running || it.status === "starting").length;
  const proxyCount = identities.filter((it) => it.network_mode !== "direct").length;
  const canDrag = !search.trim() && identities.length > 1;

  function startDrag(event: DragEvent<HTMLTableRowElement>, id: string) {
    if (!canDrag) return;
    hideNoteTip();
    setDragId(id);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", id);
  }
  function overRow(event: DragEvent<HTMLTableRowElement>, id: string) {
    // Fall back to the drag payload: the first dragover can arrive before
    // React commits the dragId state set in dragstart.
    if (!dragId && !event.dataTransfer.types.includes("text/plain")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (dragOverId !== id) setDragOverId(id);
  }
  function dropRow(event: DragEvent<HTMLTableRowElement>, targetId: string) {
    event.preventDefault();
    const sourceId = dragId ?? event.dataTransfer.getData("text/plain");
    setDragId(null);
    setDragOverId(null);
    if (!sourceId || sourceId === targetId) return;
    const ids = identities.map((it) => it.id);
    const from = ids.indexOf(sourceId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    const next = [...ids];
    next.splice(from, 1);
    next.splice(to, 0, sourceId);
    const byId = new Map(identities.map((it) => [it.id, it]));
    setIdentities(next.map((id) => byId.get(id)).filter((it): it is Identity => !!it));
    reorderIdentities(next).then(() => refresh(true)).catch((e) => { setError(String(e)); refresh(true); });
  }
  function endDrag() {
    setDragId(null);
    setDragOverId(null);
  }
  function showNoteTip(event: ReactMouseEvent<HTMLSpanElement>, note: string) {
    // Show for every environment that has a note: relying on "is it clipped"
    // made borderline notes (and therefore most rows) silently skip the
    // bubble. An empty note has nothing to show.
    if (!note || dragId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const above = rect.bottom + 150 > window.innerHeight;
    setNoteTip({
      x: Math.max(12, Math.min(rect.left, window.innerWidth - 380)),
      y: above ? rect.top : rect.bottom + 8,
      above,
      text: noteForTooltip(note),
    });
  }
  function hideNoteTip() {
    setNoteTip(null);
  }

  const create = () => {
    setError(null);
    return withBusy("create", async () => {
    const payload: CreateRequest = {
      ...form,
      network: netChoice === "direct" ? "direct" : "proxy",
      proxy_server: netChoice === "custom" ? form.proxy_server : null,
      proxy_source: netChoice === "sub" ? form.proxy_source : null,
      proxy_node: netChoice === "sub" ? form.proxy_node : null,
    };
    await createIdentity(payload); setForm(emptyForm()); setNetChoice("direct"); setShowCreate(false);
    });
  };
  function openEdit(it: Identity) {
    const subscription = it.network_mode !== "direct" && !!it.proxy_source && !!it.proxy_node;
    setEditTarget(it);
    setEditForm({
      name: it.name, note: it.note, os: it.os, country: it.country,
      network: it.network_mode === "direct" ? "direct" : "proxy",
      proxy_server: it.proxy_server ?? "",
      proxy_source: it.proxy_source ?? "",
      proxy_node: it.proxy_node ?? "",
      ui_locale: it.ui_locale ?? "",
      memory_cache: it.memory_cache ?? true,
      disabled_extensions: it.disabled_extensions ?? [],
    });
    setEditNetChoice(it.network_mode === "direct" ? "direct" : subscription ? "sub" : "custom");
    loadNodes(subscription ? it.proxy_source ?? "" : "", true);
    loadProxy();
    loadExtensions();
  }
  const exportCurrent = () => {
    if (!editTarget) return;
    withBusy(`export-${editTarget.id}`, async () => {
      const result = await exportPack(editTarget.id, editTarget.name);
      await loadData();
      flash(`已导出到 ${result.file}`);
    });
  };
  const exportCookiesCurrent = () => {
    if (!editTarget) return;
    const file = window.prompt("导出 Cookie 文件路径", `${editTarget.name || editTarget.id}-cookies.json`);
    if (!file?.trim()) return;
    withBusy(`cookies-${editTarget.id}`, () => exportCookies(editTarget.id, file.trim()));
  };
  const importArchive = (file: string) => withBusy(`import-${file}`, async () => {
    await importPack(file);
    await loadData();
    flash(`已导入身份包 ${file}`);
  });
  const exportAll = () => {
    const stamp = new Date().toISOString().slice(0, 10);
    const file = window.prompt("导出全部数据：所有环境（含账号密码）、订阅、设置与启动记录。\n只填文件名会保存到系统「下载」文件夹。", `cacer-data-${stamp}.zip`);
    if (!file?.trim()) return;
    withBusy("export-all", async () => {
      const result = await exportAllData(file.trim());
      await loadData();
      flash(`已导出 ${result.files} 个文件到 ${result.archive}`);
    });
  };
  const importAll = () => {
    const file = window.prompt("导入数据包（.zip）：可填完整路径，或「下载」文件夹里的文件名。同名文件会被覆盖。", "");
    if (!file?.trim()) return;
    withBusy("import-all", async () => {
      const result = await importAllData(file.trim());
      await loadData();
      flash(`已恢复 ${result.files} 个文件到 ${result.data}`);
    });
  };
  const cloneEnvironment = () => {
    if (!editTarget) return;
    const name = window.prompt("新环境名称", `${editTarget.name}-副本`);
    if (!name?.trim()) return;
    withBusy(`clone-${editTarget.id}`, async () => {
      await cloneIdentity(editTarget.id, name.trim());
      setEditTarget(null);
    });
  };
  const saveEdit = () => withBusy(`edit-${editTarget!.id}`, async () => {
    const live = !!editTarget!.running || editTarget!.status === "starting";
    const fingerprintChanged = editForm.os !== editTarget!.os || editForm.country !== editTarget!.country;
    if (!live && fingerprintChanged && !window.confirm("修改国家或系统将生成新的设备指纹，并清空当前浏览器缓存。原有 Cookie 和登录状态可能失效。是否继续？")) return;
    // A running helper keeps its routing; only metadata that lives in
    // identity.json is safe to change. The next launch picks up language/cache.
    const req: EditRequest = live
      ? { name: editForm.name, note: editForm.note, ui_locale: editForm.ui_locale, memory_cache: editForm.memory_cache, disabled_extensions: editForm.disabled_extensions ?? [] }
      : {
        ...editForm,
        network: editNetChoice === "direct" ? "direct" : "proxy",
        proxy_server: editNetChoice === "custom" ? editForm.proxy_server : "",
        proxy_source: editNetChoice === "sub" ? editForm.proxy_source : "",
        proxy_node: editNetChoice === "sub" ? editForm.proxy_node : "",
        clear_proxy: editNetChoice === "direct",
      };
    await editIdentity(editTarget!.id, req);
    if (!live && fingerprintChanged) await rebuildIdentity(editTarget!.id, editForm.os ?? "", editForm.country ?? "");
    setEditTarget(null);
  });
  const remove = (it: Identity) => { if (window.confirm(`确定删除“${it.name}”吗？\n\n默认只删除身份配置，不删除浏览器数据。`)) withBusy(`del-${it.id}`, () => deleteIdentity(it.id, false)); };
  const valid = form.name.trim().length > 0 && (netChoice === "direct" || (netChoice === "sub" ? !!form.proxy_source && !!form.proxy_node : !!form.proxy_server?.trim()));
  const editLive = !!editTarget?.running || editTarget?.status === "starting";
  const editValid = (editForm.name ?? "").trim().length > 0 && (editLive || editNetChoice === "direct" || (editNetChoice === "sub" ? !!editForm.proxy_source && !!editForm.proxy_node : !!(editForm.proxy_server ?? "").trim()));

  const runningList = identities.filter((it) => it.running || it.status === "starting");
  const proxyEnvs = identities.filter((it) => it.network_mode === "proxy");

  const coreBlock = <>
    <h4>代理内核（mihomo）</h4>
    <div className="proxy-core"><span className={`proxy-dot ${proxyCore?.found ? "ok" : "warn"}`} /><span>{proxyCore === null ? "正在检测…" : proxyCore.found ? <>已检测到 <code>{proxyCore.path}</code></> : "未检测到 mihomo 内核"}</span></div>
    <p className="hint">订阅节点依赖 mihomo 内核。可将 mihomo.exe 放入软件目录的 tools 文件夹，或手动指定路径；Clash Verge 自带的 mihomo 也会被自动识别。</p>
    <div className="settings-actions"><button className="secondary" onClick={loadProxy} disabled={!!subBusy}>重新检测</button><button className="secondary" onClick={pickCore} disabled={!!subBusy}>指定内核路径</button></div>
    {subBusy && <div className="form-progress">{subBusy}</div>}
  </>;

  const subBlock = <>
    <h4>代理订阅</h4>
    {proxySourceList.length === 0
      ? <p className="hint">暂无订阅。可导入本地 Clash 配置、订阅链接，或直接使用 Clash 客户端里的配置。</p>
      : <div className="sub-list">{proxySourceList.map((s) => <div className="sub-row" key={s.name}><div className="sub-info"><strong>{s.label}</strong><span>{s.nodes} 个节点 · {s.updated_at}</span></div><div className="row-actions"><button className="secondary" onClick={() => renameSource(s)} disabled={!!subBusy}>备注</button><button className="more-action danger-text" onClick={() => removeSource(s)} disabled={!!subBusy}>删除</button></div></div>)}</div>}
    <div className="settings-actions"><button className="secondary" onClick={() => importBy("file")} disabled={!!subBusy}>导入本地文件</button><button className="secondary" onClick={() => importBy("url")} disabled={!!subBusy}>订阅链接</button><button className="secondary" onClick={scanClash} disabled={!!subBusy}>扫描 Clash 配置</button></div>
  </>;

  const dataBlock = <>
    <h4>身份数据</h4>
    <p className="hint">身份包、订阅与代理配置都保存在同一个数据目录，迁移时整个复制即可。</p>
    <div className="data-line"><code>{dataInfo?.dir ?? "正在读取…"}</code></div>
    <div className="settings-actions"><button className="secondary" onClick={openDataFolder}>打开数据文件夹</button><button className="secondary" onClick={loadData}>刷新列表</button></div>
    <h4>备份与迁移</h4>
    <p className="hint">导出会打包全部环境（含保存的账号密码）、订阅、设置与启动记录；导入会覆盖同名文件，建议先停止所有浏览器。</p>
    <div className="settings-actions">
      <button className="secondary" onClick={exportAll} disabled={busy.size > 0}>导出全部数据</button>
      <button className="secondary" onClick={importAll} disabled={busy.size > 0}>导入全部数据</button>
    </div>
    {dataInfo && dataInfo.packs.length > 0
      ? <div className="sub-list">{dataInfo.packs.map((p) => <div className="sub-row" key={p.name}><div className="sub-info"><strong>{p.name}</strong><span>{formatSize(p.size)} · {formatStamp(p.modified)}</span></div><button className="secondary" onClick={() => importArchive(p.name)} disabled={busy.size > 0}>导入</button></div>)}</div>
      : <p className="hint">还没有身份包。在环境编辑窗口点「导出身份」即可保存到此处。</p>}
  </>;

  const runtimeControls = <section className="edit-section">
    <h4>运行环境</h4>
    <p className="hint">Python 可快捷下载到应用专用目录，也可手动安装后指定解释器。浏览器字体首次启动时下载，所有环境共用缓存。</p>
    <label className="edit-field"><span>下载代理（可选）</span><input value={downloadProxy} onChange={(e) => setDownloadProxy(e.target.value)} placeholder="http://127.0.0.1:7890" disabled={runtimeBusy} /></label>
    <div className="settings-actions">
      <button className="primary" disabled={runtimeBusy} onClick={() => setupRuntime("python")}>快捷安装 Python 与依赖{environment?.python_size ? `（${formatSize(environment.python_size)}）` : ""}</button>
      <button className="secondary" disabled={runtimeBusy || environment?.fonts_ready} onClick={() => setupRuntime("fonts")}>{environment?.fonts_ready ? "字体已就绪" : `下载字体${environment?.fonts_size ? `（${formatSize(environment.fonts_size)}）` : ""}`}</button>
      <button className="secondary" disabled={runtimeBusy} onClick={checkEnvironment}>重新检查</button>
    </div>
    {downloadState && <div className="form-progress" role="status">{downloadState.message}{downloadState.total > 0 && <> · {formatSize(downloadState.downloaded)} / {formatSize(downloadState.total)}<progress max={downloadState.total} value={downloadState.downloaded} /></>}<button className="secondary" onClick={() => cancelRuntime().catch((e) => setError(String(e)))}>取消</button></div>}
    <details><summary>手动安装 Python / 使用已有 Python</summary>
      <p className="hint">将以下命令复制到 PowerShell 执行。已有 Python 时可以跳过安装步骤，再填入已安装依赖的解释器路径。</p>
      <pre className="cmd-block">{guideText}</pre>
      <button className="secondary" onClick={copyGuide}>{copied ? "已复制" : "复制安装命令"}</button>
      <label className="edit-field"><span>Python 解释器路径</span><input value={pythonPath} onChange={(e) => setPythonPath(e.target.value)} placeholder="C:\\…\\Scripts\\python.exe" disabled={runtimeBusy} /></label>
      <button className="secondary" onClick={applyPython} disabled={runtimeBusy || !pythonPath.trim()}>检查并使用此 Python</button>
    </details>
  </section>;

  return <main className="app-shell">
    <aside className="sidebar">
      <div className="brand"><img className="brand-mark" src={APP_ICON} alt="" /><div><strong>Cacer</strong><span>隐私浏览工作台</span></div></div>
      <nav className="nav"><div className="nav-group-title">工作台</div><a className={`nav-item ${view === "overview" ? "active" : ""}`} onClick={() => setView("overview")}><Icon>⌂</Icon>总览</a><a className={`nav-item ${view === "environments" ? "active" : ""}`} onClick={() => setView("environments")}><Icon>▦</Icon>浏览器环境<span className="nav-count">{identities.length}</span></a><a className={`nav-item ${view === "proxy" ? "active" : ""}`} onClick={() => setView("proxy")}><Icon>⌁</Icon>代理管理</a><a className={`nav-item ${view === "extensions" ? "active" : ""}`} onClick={() => setView("extensions")}><Icon>⧩</Icon>扩展中心<span className="nav-count">{extItems.length}</span></a><a className={`nav-item ${view === "history" ? "active" : ""}`} onClick={() => setView("history")}><Icon>◷</Icon>启动记录</a><div className="nav-group-title second">系统</div><a className="nav-item" onClick={openSettings}><Icon>⚙</Icon>设置</a></nav>
      <div className={`sidebar-bottom ${environment && !environment.ready ? "service-warning" : ""}`} onClick={checkEnvironment} title="点击重新检查运行环境"><div className="health-dot"/><div><strong>{environment ? (environment.ready ? "本地服务正常" : "需要检查环境") : "正在检查环境"}</strong><span>Cacer 0.1.0 · 点击检测</span></div></div>
    </aside>
    <section className="workspace">
      <header className="topbar"><div className="breadcrumb"><span>工作台</span><b>/</b><strong>{VIEW_LABEL[view]}</strong></div><div className="top-actions"><button className="icon-button" title="刷新" onClick={() => refresh(true)}>↻</button><button className="icon-button" title="设置" onClick={openSettings}>⚙</button></div></header>
      <div className="content">
        {environment && !environment.ready && <div className="banner warning"><span>!</span><div><strong>运行环境未就绪</strong><p>{environment.checks.filter((check) => !check.ok).map((check) => `${check.label}：${check.detail}`).join("；")}</p></div><div className="banner-actions">{pythonMissing && <button onClick={() => openGuide("python")}>安装 Python</button>}{engineMissing && <button onClick={() => openGuide("engine")}>安装 Camoufox 引擎</button>}<button onClick={checkEnvironment}>重新检查</button></div></div>}
        {error && <div className="banner error"><span>!</span><span>{error}</span><button onClick={() => setError(null)}>×</button></div>}
        {notice && <div className="banner success"><span>✓</span><span>{notice}</span></div>}
        {view === "overview" && <>
          <div className="page-heading"><div><div className="eyebrow">DASHBOARD</div><h1>总览</h1><p>查看运行状态与环境分布。</p></div><button className="primary large" onClick={openCreate}>＋ 新建环境</button></div>
          <section className="stats"><div className="stat-card"><span className="stat-icon purple">▦</span><div><span>全部环境</span><strong>{identities.length}</strong></div></div><div className="stat-card"><span className="stat-icon green">●</span><div><span>正在运行</span><strong>{running}</strong></div></div><div className="stat-card"><span className="stat-icon blue">⌁</span><div><span>已配置代理</span><strong>{proxyCount}</strong></div></div><div className="stat-card"><span className="stat-icon orange">✓</span><div><span>服务状态</span><strong className="status-text">{environment?.ready ? "正常" : "待检查"}</strong></div></div></section>
          <section className="panel panel-pad">
            <h3 className="block-title">正在运行的浏览器</h3>
            {runningList.length === 0
              ? <div className="empty-mini">当前没有运行中的浏览器环境。</div>
              : <div className="sub-list">{runningList.map((it) => <div className="sub-row" key={it.id}><div className="sub-info"><strong>{it.name || it.id}</strong><span>{it.network_mode === "direct" ? "直连" : it.proxy_node ?? it.proxy_server ?? "代理"}</span></div><span className={`status ${it.status === "starting" ? "starting" : "online"}`}><i />{it.status === "starting" ? "启动中" : "运行中"}</span></div>)}</div>}
          </section>
          <section className="panel panel-pad">
            <h3 className="block-title">快速开始</h3>
            <div className="settings-actions"><button className="secondary" onClick={openCreate}>新建环境</button><button className="secondary" onClick={() => setView("proxy")}>管理代理订阅</button><button className="secondary" onClick={() => setView("history")}>查看启动记录</button></div>
          </section>
        </>}
        {view === "environments" && <>
          <div className="page-heading"><div><div className="eyebrow">ENVIRONMENT MANAGER</div><h1>浏览器环境</h1><p>管理独立身份、网络配置与浏览器运行状态。</p></div><button className="primary large" onClick={openCreate}>＋ 新建环境</button></div>
        <section className="panel"><div className="toolbar"><div className="search-box"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索环境名称、国家或代理" /></div><div className="toolbar-right"><span className="result-count">共 {visible.length} 个环境</span>{!search.trim() && identities.length > 1 && <span className="drag-hint">拖动环境行可调整顺序</span>}</div></div>
          {visible.length === 0 ? <div className="empty"><img className="empty-mark" src={APP_ICON} alt="" /><h3>{identities.length ? "没有匹配的环境" : "开始创建第一个环境"}</h3><p>{identities.length ? "尝试更换搜索关键词。" : "为不同的浏览任务创建隔离的浏览器身份。"}</p>{!identities.length && <button className="primary" onClick={openCreate}>＋ 新建环境</button>}</div> : <div className="table-wrap"><table><thead><tr><th>环境</th><th>状态</th><th>设备</th><th>网络</th><th>地区 / 语言</th><th className="actions-head">操作</th></tr></thead><tbody>{visible.map((it) => <tr key={it.id} draggable={canDrag} className={dragId === it.id ? "row-dragging" : dragOverId === it.id && dragId !== it.id ? "row-drop-target" : undefined} onDragStart={(e) => startDrag(e, it.id)} onDragOver={(e) => overRow(e, it.id)} onDrop={(e) => dropRow(e, it.id)} onDragEnd={endDrag}><td><div className="profile-cell"><div className="country-avatar"><Flag country={it.country} size={26} /></div><div><strong>{it.name || it.id}</strong><span onMouseEnter={(e) => showNoteTip(e, it.note)} onMouseLeave={hideNoteTip}>{inlineNote(it.note) || `创建于 ${it.created_at?.slice(0, 10) ?? "—"}`}</span></div></div></td><td><span className={`status ${it.status === "starting" ? "starting" : it.running ? "online" : "offline"}`}><i />{it.status === "starting" ? "启动中" : it.running ? "运行中" : "已停止"}</span></td><td><span className="device"><b>{OS_ICONS[it.os] ?? "◈"}</b>{OS_LABELS[it.os] ?? it.os}</span></td><td><span className="network" title={it.proxy_node ?? it.proxy_server ?? undefined}><i className={it.network_mode === "direct" ? "direct" : "proxy"} />{it.network_mode === "direct" ? "直连" : it.proxy_node ?? "代理"}</span></td><td><span className="locale"><Flag country={it.country} size={17} /> {it.country || "自动"}<small>{it.languages?.[0] ?? it.locale}</small></span></td><td><div className="table-actions">{it.running || it.status === "starting" ? <button className="action stop-action" disabled={busy.has(`stop-${it.id}`)} onClick={() => withBusy(`stop-${it.id}`, () => stopIdentity(it.id))}>{it.status === "starting" ? "取消" : "停止"}</button> : <button className="action launch-action" disabled={busy.has(`launch-${it.id}`)} onClick={() => withBusy(`launch-${it.id}`, () => launchPrepared(it.id))}>启动</button>}<button className="more-action" onClick={() => openEdit(it)}>编辑</button><button className="more-action danger-text" disabled={it.running} onClick={() => remove(it)}>删除</button></div></td></tr>)}</tbody></table></div>}
        </section>
        </>}
        {view === "proxy" && <>
          <div className="page-heading"><div><div className="eyebrow">PROXY MANAGER</div><h1>代理管理</h1><p>管理 mihomo 内核与 Clash 订阅，为每个环境分配独立出口。</p></div></div>
          <section className="panel panel-pad">{coreBlock}</section>
          <section className="panel panel-pad">{subBlock}</section>
          <section className="panel panel-pad">
            <h3 className="block-title">环境代理分配</h3>
            {proxyEnvs.length === 0
              ? <div className="empty-mini">还没有环境使用代理。编辑环境时可在「网络方式」中选择订阅节点。</div>
              : <div className="sub-list">{proxyEnvs.map((it) => <div className="sub-row" key={it.id}><div className="sub-info"><strong>{it.name || it.id}</strong><span>{it.proxy_node ?? it.proxy_server ?? "代理"}{it.proxy_source ? ` · ${it.proxy_source}` : ""}</span></div><span className={`status ${it.running ? "online" : "offline"}`}><i />{it.running ? "运行中" : "已停止"}</span></div>)}</div>}
          </section>
        </>}
        {view === "extensions" && <>
          <div className="page-heading">
            <div><div className="eyebrow">EXTENSION CENTER</div><h1>扩展中心</h1><p>从 Firefox 官方商店安装扩展；安装后所有环境默认启用，可在环境编辑中按需关闭。</p></div>
            <button className="secondary" onClick={importExtension} disabled={!!extBusy}>导入本地 XPI</button>
          </div>
          <section className="panel panel-pad">
            <h3 className="block-title">搜索 Firefox 扩展</h3>
            <div className="ext-search">
              <input value={extQuery} onChange={(e) => setExtQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") searchExtensions(); }} placeholder="例如：ublock、沉浸式翻译、LastPass…" />
              <button className="primary" onClick={searchExtensions} disabled={!!extBusy || !extQuery.trim()}>{extBusy === "search" ? "搜索中…" : "搜索"}</button>
            </div>
            <p className="hint">数据来自 addons.mozilla.org（Firefox 官方扩展商店）。本内核是 Camoufox（Firefox），Chrome / Edge 商店的插件无法安装。</p>
            {extSearched && (extResults.length === 0
              ? <div className="empty-mini">没有找到匹配的扩展。</div>
              : <div className="ext-grid">{extResults.map((item) => <div className="ext-card" key={item.slug}>
                {item.icon ? <img className="ext-icon" src={item.icon} alt="" /> : <span className="ext-icon ext-fallback">{item.name.slice(0, 1)}</span>}
                <div className="ext-body">
                  <strong className="ext-name">{item.name}</strong>
                  <span className="ext-summary">{item.summary || "暂无简介"}</span>
                  <span className="ext-meta">v{item.version}{item.rating ? ` · ${item.rating} 分` : ""}{item.users ? ` · ${formatUsers(item.users)} 用户` : ""}</span>
                </div>
                <div className="ext-foot">{item.installed ? <span className="ext-badge">已安装</span> : <button className="primary" disabled={!!extBusy} onClick={() => installExtension(item.slug)}>{extBusy === `install-${item.slug}` ? "安装中…" : "安装"}</button>}</div>
              </div>)}</div>)}
          </section>
          <section className="panel panel-pad">
            <h3 className="block-title">已安装扩展</h3>
            <p className="hint">安装后默认在所有环境启用。每个环境的开关在「浏览器环境 → 编辑 → 浏览器扩展」里，只影响下一次启动，不会重建环境指纹。</p>
            {extItems.length === 0
              ? <div className="empty-mini">还没有安装扩展。</div>
              : <div className="ext-grid">{extItems.map((item) => <div className="ext-card" key={item.slug}>
                {item.icon ? <img className="ext-icon" src={item.icon} alt="" /> : <span className="ext-icon ext-fallback">{item.name.slice(0, 1)}</span>}
                <div className="ext-body">
                  <strong className="ext-name">{item.name}</strong>
                  <span className="ext-summary">{item.summary || "暂无简介"}</span>
                  <span className="ext-meta">v{item.version} · {EXT_SOURCE_LABEL[item.source] ?? item.source}</span>
                </div>
                <div className="ext-foot">{item.removable ? <button className="more-action danger-text" disabled={!!extBusy} onClick={() => removeExtension(item)}>{extBusy === `remove-${item.slug}` ? "卸载中…" : "卸载"}</button> : <span className="ext-badge">内置</span>}</div>
              </div>)}</div>}
          </section>
        </>}
        {view === "history" && <>
          <div className="page-heading"><div><div className="eyebrow">LAUNCH LOG</div><h1>启动记录</h1><p>记录每次环境启动、停止与窗口关闭事件。</p></div><button className="secondary" onClick={loadHistory}>刷新</button></div>
          <section className="panel">
            {history.length === 0
              ? <div className="empty"><div className="empty-mark">◷</div><h3>暂无启动记录</h3><p>启动任意环境后，这里会显示时间、网络方式与事件。</p></div>
              : <div className="table-wrap"><table><thead><tr><th>时间</th><th>环境</th><th>事件</th><th>网络</th></tr></thead><tbody>{history.map((item, index) => <tr key={`${item.at}-${item.id}-${index}`}><td>{item.at}</td><td><div className="profile-cell"><div><strong>{item.name || item.id}</strong><span>{item.id}</span></div></div></td><td><span className={`status ${item.event === "launch" ? "online" : "offline"}`}><i />{EVENT_LABEL[item.event] ?? item.event}</span></td><td>{item.network ?? "—"}</td></tr>)}</tbody></table></div>}
          </section>
        </>}
      </div>
    </section>

    {showCreate && <Modal title="新建浏览器环境" onClose={() => { if (!busyRef.current.has("create")) setShowCreate(false); }}><div className="form-intro">创建后将生成一套稳定、隔离的浏览器身份配置。</div>{error && <div className="form-error">{error}</div>}{busy.has("create") && <div className="form-progress">正在生成隔离指纹，请稍候，完成后自动关闭…</div>}<div className="grid"><label><span>环境名称 <em>*</em></span><input value={form.name} placeholder="例如：法国小店-A" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label><span>备注</span><textarea rows={3} value={form.note} placeholder="例如：电商账号专用（支持换行）" onChange={(e) => setForm({ ...form, note: e.target.value })} /></label><label><span>设备系统</span><select value={form.os ?? ""} onChange={(e) => setForm({ ...form, os: e.target.value || null })}>{OS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label><label><span>国家 / 地区</span><select value={form.country ?? ""} onChange={(e) => setForm({ ...form, country: e.target.value || null })}>{COUNTRY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><small className="field-hint">语言、时区与设备指纹将自动跟随国家。</small></label><label className="wide"><span>浏览器界面语言</span><select value={form.ui_locale ?? "zh-CN"} onChange={(e) => setForm({ ...form, ui_locale: e.target.value })}><option value="zh-CN">中文（菜单显示中文）</option><option value="">跟随环境语言（一致性最高）</option></select><small className="field-hint">仅影响浏览器菜单与对话框的显示，不会改变网站识别到的语言和地区。选择「跟随环境语言」时，日期与数字格式也会与当地完全一致。</small></label><label className="wide"><span>内存缓存</span><div className="seg">{([["on", "开启（推荐）"], ["off", "关闭"]] as const).map(([value, label]) => <button type="button" key={value} className={(form.memory_cache === false) === (value === "off") ? "seg-on" : "seg-off"} onClick={() => setForm({ ...form, memory_cache: value === "on" })}>{label}</button>)}</div><small className="field-hint">开启后页面回访与前进/后退直接读内存缓存，不再重新下载，代理环境下明显更流畅；关闭则保持引擎默认的「仅磁盘缓存」。</small></label><label className="wide"><span>网络方式</span><div className="seg">{([["direct", "直连"], ["sub", "订阅节点"], ["custom", "手动代理"]] as const).map(([value, label]) => <button type="button" key={value} className={netChoice === value ? "seg-on" : "seg-off"} onClick={() => setNetChoice(value)}>{label}</button>)}</div></label>
      {netChoice === "sub" && <>
        <label className="wide"><span>代理订阅</span><select value={form.proxy_source ?? ""} onChange={(e) => chooseSubSource(e.target.value, false)}><option value="">选择订阅…</option>{proxySourceList.map((s) => <option key={s.name} value={s.name}>{s.label}（{s.nodes} 个节点）</option>)}</select>{!proxySourceList.length && <small className="field-hint">还没有订阅，请先在「代理管理」中导入。</small>}</label>
        <label className="wide"><span>节点</span><select value={form.proxy_node ?? ""} onChange={(e) => setForm({ ...form, proxy_node: e.target.value || null })} disabled={!form.proxy_source}><option value="">{form.proxy_source ? "选择节点…" : "请先选择订阅"}</option>{subNodes.map((n) => <option key={n.name} value={n.name}>{n.name}{n.type ? ` · ${n.type}` : ""}</option>)}</select></label>
      </>}
      {netChoice === "custom" && <label className="wide"><span>代理服务器</span><input value={form.proxy_server ?? ""} placeholder="127.0.0.1:8080（默认 HTTP）" onChange={(e) => setForm({ ...form, proxy_server: e.target.value })} /></label>}</div><div className="modal-footer"><button className="secondary" disabled={busy.has("create")} onClick={() => setShowCreate(false)}>取消</button><button className="primary" disabled={!valid || busy.has("create")} onClick={create}>{busy.has("create") ? "生成中…" : "生成环境"}</button></div></Modal>}
    {showSettings && <Modal title="设置" onClose={() => setShowSettings(false)}>
      {error && <div className="form-error">{error}</div>}
      {runtimeControls}
      <section className="edit-section">{dataBlock}</section>
    </Modal>}
    {showClash && <Modal title="扫描到的 Clash 配置" onClose={() => setShowClash(false)}>
      {error && <div className="form-error">{error}</div>}
      {localClashConfigs.length === 0
        ? <p className="hint">没有扫描到包含节点的 Clash 配置。</p>
        : <>
          <p className="hint">共 {localClashConfigs.length} 个配置，可修改备注名后逐个导入，或一次全部导入。</p>
          <div className="sub-list clash-list">{localClashConfigs.map((c) => <div className="sub-row" key={c.path}>
            <input className="clash-name" value={clashLabels[c.path] ?? ""} placeholder={c.name} onChange={(e) => setClashLabels({ ...clashLabels, [c.path]: e.target.value })} disabled={!!subBusy} />
            <span className="clash-meta">{c.nodes} 个节点</span>
            <button className="secondary" onClick={() => importFromClash(c)} disabled={!!subBusy}>导入</button>
          </div>)}</div>
          {subBusy && <div className="form-progress">{subBusy}</div>}
        </>}
      <div className="modal-footer"><button className="secondary" onClick={() => setShowClash(false)} disabled={!!subBusy}>关闭</button><button className="primary" onClick={importAllClash} disabled={!!subBusy || localClashConfigs.length === 0}>全部导入</button></div>
    </Modal>}
    {guide && <Modal title={guide === "fonts" ? "准备浏览器字体" : "运行环境设置"} onClose={() => { if (!runtimeBusy) setGuide(null); }}>
      {error && <div className="form-error">{error}</div>}
      {guide === "engine" && <p className="hint">安装包已包含浏览器核心。若文件缺失，请重新安装当前版本。</p>}
      {runtimeControls}
      <div className="modal-footer"><button className="secondary" disabled={runtimeBusy} onClick={() => setGuide(null)}>关闭</button></div>
    </Modal>}
    {editTarget && <Modal title="编辑环境" onClose={() => setEditTarget(null)}><section className="edit-section"><h4>身份指纹</h4><div className="fpinfo"><span><Flag country={editTarget.country} size={16} /> {editTarget.country || "自动地区"}</span><span>{OS_ICONS[editTarget.os]} {OS_LABELS[editTarget.os] ?? editTarget.os}</span><span>◷ {editTarget.timezone}</span><span>文 {editTarget.languages?.[0] ?? editTarget.locale}</span></div><p className="hint">设备指纹保持不变，以维持 Cookie 和登录状态的一致性。</p></section><section className="edit-section"><h4>基本信息</h4><div className="grid"><label><span>环境名称</span><input value={editForm.name ?? ""} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></label><label><span>备注</span><textarea rows={3} value={editForm.note ?? ""} onChange={(e) => setEditForm({ ...editForm, note: e.target.value })} /></label><label><span>设备系统</span><select value={editForm.os ?? ""} disabled={editLive} onChange={(e) => setEditForm({ ...editForm, os: e.target.value || null })}>{OS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label><label><span>国家 / 地区</span><select value={editForm.country ?? ""} disabled={editLive} onChange={(e) => setEditForm({ ...editForm, country: e.target.value || null })}>{COUNTRY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="wide"><span>浏览器界面语言</span><select value={editForm.ui_locale ?? ""} onChange={(e) => setEditForm({ ...editForm, ui_locale: e.target.value })}><option value="zh-CN">中文（菜单显示中文）</option><option value="">跟随环境语言（一致性最高）</option>{editForm.ui_locale && editForm.ui_locale !== "zh-CN" && <option value={editForm.ui_locale}>当前：{editForm.ui_locale}</option>}</select><small className="field-hint">仅影响浏览器菜单与对话框的显示，不会改变网站识别到的语言和地区。修改后下次启动生效。</small></label><label className="wide"><span>内存缓存</span><div className="seg">{([["on", "开启（推荐）"], ["off", "关闭"]] as const).map(([value, label]) => <button type="button" key={value} className={(editForm.memory_cache === false) === (value === "off") ? "seg-on" : "seg-off"} onClick={() => setEditForm({ ...editForm, memory_cache: value === "on" })}>{label}</button>)}</div><small className="field-hint">开启后页面回访与前进/后退直接读内存缓存，代理环境下更流畅。修改后下次启动生效。</small></label></div></section><section className="edit-section"><h4>网络方式</h4><div className="seg">{([["direct", "直连"], ["sub", "订阅节点"], ["custom", "手动代理"]] as const).map(([value, label]) => <button type="button" disabled={editLive} key={value} className={editNetChoice === value ? "seg-on" : "seg-off"} onClick={() => setEditNetChoice(value)}>{label}</button>)}</div>
      {editNetChoice === "sub" && <div className="grid">
        <label><span>代理订阅</span><select value={editForm.proxy_source ?? ""} disabled={editLive} onChange={(e) => chooseSubSource(e.target.value, true)}><option value="">选择订阅…</option>{proxySourceList.map((s) => <option key={s.name} value={s.name}>{s.label}（{s.nodes} 个节点）</option>)}</select>{!proxySourceList.length && <small className="field-hint">还没有订阅，请先在「代理管理」中导入。</small>}</label>
        <label><span>节点</span><select value={editForm.proxy_node ?? ""} onChange={(e) => setEditForm({ ...editForm, proxy_node: e.target.value })} disabled={editLive || !editForm.proxy_source}><option value="">{editForm.proxy_source ? "选择节点…" : "请先选择订阅"}</option>{editSubNodes.map((n) => <option key={n.name} value={n.name}>{n.name}{n.type ? ` · ${n.type}` : ""}</option>)}</select></label>
      </div>}
      {editNetChoice === "custom" && <label className="edit-field"><span>代理服务器</span><input value={editForm.proxy_server ?? ""} disabled={editLive} placeholder="127.0.0.1:8080（默认 HTTP）" onChange={(e) => setEditForm({ ...editForm, proxy_server: e.target.value })} /></label>}<p className="hint">{editLive ? "浏览器运行中：名称、备注、界面语言、内存缓存和扩展开关会立即保存（语言、缓存与扩展下次启动生效）；设备指纹、国家与网络设置需先停止浏览器。" : "代理修改会在下次启动时生效，未写协议时按 HTTP 处理。"}</p></section><section className="edit-section"><h4>浏览器扩展</h4>{extItems.length === 0 ? <p className="hint">还没有安装扩展。可到左侧「扩展中心」从 Firefox 官方商店安装，安装后所有环境默认启用。</p> : <div className="ext-toggles">{extItems.map((item) => { const on = !(editForm.disabled_extensions ?? []).includes(item.slug); return <label className={`ext-toggle ${on ? "" : "off"}`} key={item.slug}><input type="checkbox" checked={on} onChange={(e) => toggleEditExtension(item.slug, e.target.checked)} /><span><strong>{item.name}</strong><small>v{item.version}{item.engine ? " · 引擎内置" : ""}</small></span></label>; })}</div>}<p className="hint">开关只在下一次启动时决定是否加载该扩展，不重建环境指纹，也不影响 Cookie、缓存与登录状态。</p></section><section className="edit-section"><h4>账号密码</h4><p className="hint">在浏览器内登录网站后，Firefox 会提示保存账号密码。凭据保存在本环境的配置文件中，「导出身份」时会一并打包，导入后可直接继续使用；地址栏打开 about:logins 可查看和管理。</p></section><div className="modal-footer"><button className="secondary" onClick={exportCookiesCurrent} disabled={busy.has(`cookies-${editTarget.id}`)}>导出 Cookie</button><button className="secondary" onClick={exportCurrent} disabled={!!editTarget.running || busy.has(`export-${editTarget.id}`)}>导出身份</button><button className="secondary" onClick={cloneEnvironment} disabled={!!editTarget.running || busy.has(`clone-${editTarget.id}`)}>复制为新环境</button><span className="footer-spacer"/><button className="secondary" onClick={() => setEditTarget(null)}>取消</button><button className="primary" disabled={busy.has(`edit-${editTarget.id}`) || !editValid} onClick={saveEdit}>保存修改</button></div></Modal>}
    {noteTip && <div className="note-tip" role="tooltip" style={{ left: noteTip.x, top: noteTip.y, transform: noteTip.above ? "translateY(calc(-100% - 8px))" : "none" }}>{noteTip.text}</div>}
  </main>;
}
