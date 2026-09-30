import { CalculationPanel } from "./CalculationPanel";
import { BrandMark } from "./BrandMark";
import { populationParameterIssues } from "./forecastParameters";
import { useId, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, CommunityApi, downloadFile } from "./api";
import { emitHostEvent } from "./hostBridge";
import { FacilityParameterForm, PopulationParameterForm } from "./ParameterForms";
import type { Community, CommunityImportReport, Dashboard, ModuleEvent, ParameterSet, PredictionResultRow, PredictionRun, Project, QualityReport } from "./types";
import "./styles.css";
import { CommunityEditor } from "./CommunityEditor";
import { formatTime } from "./dateTime";

type Page = "dashboard" | "projects" | "population" | "facility" | "communities" | "results";
export type Theme = "dark" | "light";

export type CommunityPredictionModuleProps = {
  mode?: "standalone" | "embedded";
  apiBase?: string;
  token?: string;
  projectId?: number;
  hostContext?: Record<string, unknown>;
  hostOrigin?: string;
  defaultTheme?: Theme;
  onEvent?: (event: ModuleEvent) => void;
};

const EMPTY_DASHBOARD: Dashboard = {
  community_count: 0,
  total_households: 0,
  total_population: 0,
  regions: {},
};
function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const nextThemeLabel = theme === "dark" ? "浅色" : "深色";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-label={`切换为${nextThemeLabel}主题`}
      title={`切换为${nextThemeLabel}主题`}
    >
      <span className="theme-glyph" aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      <span>{nextThemeLabel}</span>
    </button>
  );
}

function LoadingBlock({ label = "正在加载" }: { label?: string }) {
  return <div className="loading-block"><span className="spinner" />{label}</div>;
}

function PredictionRunPanel({
  kind,
  busy,
  communityCount,
  runCount,
  populationReady = false,
  onRun,
  quality,
  onFix,
  readOnly = false,
}: {
  kind: "population" | "facility";
  busy: string;
  communityCount: number;
  runCount: number;
  populationReady?: boolean;
  onRun: () => void;
  quality?: QualityReport | null;
  onFix?: (page:Page,communityId?:number)=>void;
  readOnly?: boolean;
}) {
  const isPopulation = kind === "population";
  const running = busy === kind;
  const unavailable = communityCount === 0 || (!isPopulation && !populationReady);
  return (
    <section className="content-card prediction-run-card">
      <div className="prediction-run-copy">
        <h2>{isPopulation ? "执行人口预测" : "执行设施预测"}</h2>
      </div>
      <div className="prediction-readiness" aria-label="预测准备状态">
        <span>社区数据<strong>{communityCount}</strong><small>个</small></span>
        <span>历史批次<strong>{runCount}</strong><small>次</small></span>
      </div>
      <button className="primary-button prediction-run-button" disabled={readOnly || Boolean(busy) || unavailable} onClick={onRun}>
        {running ? "正在计算…" : communityCount === 0 ? "请先录入社区" : !isPopulation && !populationReady ? "请先完成人口预测" : `开始${isPopulation ? "人口" : "设施"}预测`}
      </button>
      {quality && <div className={`quality-panel ${quality.ready ? "ready" : "blocked"}`}>
        <strong>{quality.ready ? `检查通过${quality.warningCount ? `，有 ${quality.warningCount} 项提醒` : ""}` : `预测前检查未通过：${quality.errorCount} 项必须修正`}</strong>
        {quality.forecastYears.length > 0 && <span>预测年度：{quality.forecastYears[0]}—{quality.forecastYears.at(-1)}年</span>}
        {quality.issues.length > 0 && <ul>{quality.issues.map((issue,index)=><li className={issue.level} key={`${issue.code}-${index}`}><span>{issue.level==="error"?"必须修正":"提醒"}：{issue.message}</span><button type="button" onClick={()=>onFix?.(issue.page,issue.communityId)}>前往修正</button></li>)}</ul>}
      </div>}
    </section>
  );
}

function CommunityDataInputPage({
  communities, exportHref,
  dashboard,
  regions,
  baseYear,
  onDirtyChange,
  readOnly = false,
  onCreate,
  onImport,
}: {
  communities: Community[];
  exportHref: (communityId:number)=>string;
  dashboard: Dashboard;
  readOnly?: boolean;
  regions: string[];
  baseYear: number;
  onDirtyChange: (dirty: boolean) => void;
  onCreate: (payload: Partial<Community>) => Promise<boolean>;
  onImport: (file: File) => Promise<CommunityImportReport>;
}) {
  const [exportId,setExportId]=useState(communities[0]?.id || 0);
  const selectedExportId=communities.some(c=>c.id===exportId)?exportId:communities[0]?.id;
  const [showCreate, setShowCreate] = useState(false);
  const [localDirty, setLocalDirty] = useState(false);
  const draftChanged = useCallback((dirty: boolean) => { setLocalDirty(dirty); onDirtyChange(dirty); }, [onDirtyChange]);
  const [importing, setImporting] = useState(false);
  const [importReport, setImportReport] = useState<CommunityImportReport | null>(null);
  const maxRegion = Math.max(1, ...Object.values(dashboard.regions));
  return (
    <div className="page-stack">
      <section className="community-input-card">
        <div className="section-header community-toolbar">
          <div className="actions">
            {communities.length > 1 && <label>选择社区<select aria-label="下载社区现状数据的社区" value={selectedExportId} onChange={e=>setExportId(Number(e.target.value))}>{communities.map(c=><option value={c.id} key={c.id}>{c.code} · {c.name}</option>)}</select></label>}
            {selectedExportId ? <button type="button" className="secondary-button" onClick={() => void downloadFile(exportHref(selectedExportId)).catch(error => window.alert(error instanceof Error ? error.message : "下载失败"))}>下载社区现状数据</button> : <button className="secondary-button" disabled title="请先新建或导入社区并保存数据">下载社区现状数据</button>}
            <label className={`secondary-button file-button ${importing ? "disabled" : ""}`}>{importing ? "正在校验…" : "导入社区 Excel"}<input type="file" accept=".xlsx" disabled={importing || readOnly} onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                setImporting(true);
                void onImport(file).then(setImportReport).finally(() => setImporting(false));
              }
              event.currentTarget.value = "";
            }} /></label>
            <button disabled={readOnly} className="primary-button" onClick={() => { if (!showCreate || !localDirty || window.confirm("放弃尚未保存的新社区？")) setShowCreate((value) => !value); }}>{showCreate ? "取消新建" : "新建社区"}</button>
          </div>
        </div>
        {showCreate && <CommunityEditor onDirtyChange={draftChanged} regions={regions} baseYear={baseYear} onSave={onCreate} onCancel={() => setShowCreate(false)} />}

      </section>
      {importReport && <section className="content-card import-report-card" aria-live="polite">
        <div className="section-header import-report-header">
          <div><h2>社区导入报告</h2><p>文件：{importReport.filename}</p></div>
          <button className="report-close" aria-label="关闭导入报告" onClick={() => setImportReport(null)}>×</button>
        </div>
        <div className="import-summary">
          <article className="success"><span>成功</span><strong>{importReport.success_count}</strong><small>个文件</small></article>
          <article className="updated"><span>更新</span><strong>{importReport.updated_count}</strong><small>个社区</small></article>
          <article className="failed"><span>失败</span><strong>{importReport.failed_count}</strong><small>个文件</small></article>
          <article className="issues"><span>异常字段</span><strong>{importReport.issues.length}</strong><small>处</small></article>
        </div>
        {importReport.warnings?.map((warning, index) => <p key={index} className="inline-error">{warning}</p>)}
        {importReport.issues.length === 0 ? <div className="import-report-success">校验通过，{importReport.created_count ? "已新建社区" : "已更新同编号社区"}。</div> : <div className="import-issues-table">
          <div className="import-issues-head"><span>工作表</span><span>行号</span><span>字段</span><span>异常值</span><span>原因</span></div>
          {importReport.issues.map((issue, index) => <div className="import-issues-row" key={`${issue.sheet}-${issue.row}-${issue.field}-${index}`}>
            <span>{issue.sheet || "—"}</span><span>{issue.row || "—"}</span><strong>{issue.field}</strong><code>{issue.value === undefined || issue.value === null || issue.value === "" ? "空值" : String(issue.value)}</code><span>{issue.message}</span>
          </div>)}
        </div>}
      </section>}
      <section className="metric-grid">
        <article><span>社区总数</span><strong>{dashboard.community_count}</strong><small>个社区</small></article>
        <article><span>社区总户数</span><strong>{dashboard.total_households.toLocaleString()}</strong><small>户</small></article>
        <article><span>社区总人口</span><strong>{dashboard.total_population.toLocaleString()}</strong><small>人</small></article>
        <article><span>覆盖地区</span><strong>{Object.keys(dashboard.regions).length}</strong><small>个参考地区</small></article>
      </section>
      <section className="content-card region-card">
        <div className="section-header"><div><h2>社区参考地区分布</h2></div></div>
        {Object.keys(dashboard.regions).length === 0 ? <div className="empty-state">导入社区后显示真实统计数据</div> : (
          <div className="region-bars">
            {Object.entries(dashboard.regions).map(([name, count]) => (
              <div className="region-row" key={name}>
                <span>{name}</span><div><i style={{ width: `${(count / maxRegion) * 100}%` }} /></div><strong>{count}</strong>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function CommunitiesPage({
  communities,
  onOpen,
}: {
  communities: Community[];
  onOpen: (community: Community, tab?: string) => void;
}) {
  return (
    <div className="page-stack">
      <section className="content-card">
        <div className="community-list">
          {communities.length === 0 ? <div className="empty-state">没有找到符合条件的社区，请调整搜索条件或前往“社区数据输入”录入数据。</div> : communities.map((community) => {
            const population = Object.values(community.age_counts).reduce((sum, count) => sum + Number(count), 0);
            return (
              <article className="community-item" key={community.id}>
                <div className="community-card-heading">
                  <div className="community-main"><button className="chart-action" onClick={() => onOpen(community)}>{community.name}</button><span>{community.region} · {community.households.toLocaleString()} 户 · {population.toLocaleString()} 人</span></div>
                  <span className="community-code">{community.code}</span>
                </div>
                <div className="community-quick-actions">{["社区基础信息","社区设施信息","社区闲置空间信息","社区人口列表","预测结果"].map((tab,index)=><button className="secondary-button" key={tab} onClick={()=>onOpen(community,tab)}><span className="community-action-icon" aria-hidden="true">{["档","设","空","人","图"][index]}</span>{tab.replace("社区","")}<span aria-hidden="true">→</span></button>)}</div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function CreateProjectDialog({ open, onClose, onCreate }: { open: boolean; onClose: () => void; onCreate: (name: string) => Promise<boolean> }) {
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => { if (open) { setName(""); setWorking(false); } }, [open]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !working) onClose(); }}>
      <section className="create-project-dialog" role="dialog" aria-modal="true" aria-labelledby="create-project-title">
        <button className="dialog-close" type="button" aria-label="关闭" disabled={working} onClick={onClose}>×</button>
        <p className="eyebrow">新建工程</p><h2 id="create-project-title">创建独立预测工程</h2><p>新工程将拥有独立的社区、参数、预测批次和报告。</p>
        <form onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim() || working) return;
          setWorking(true);
          const created = await onCreate(name.trim());
          if (created) onClose(); else setWorking(false);
        }}>
          <label>工程名称<input autoFocus autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：和平区完整社区预测" /></label>
          <div><button className="secondary-button" type="button" disabled={working} onClick={onClose}>取消</button><button className="primary-button" type="submit" disabled={working || !name.trim()}>{working ? "创建中…" : "创建并进入"}</button></div>
        </form>
      </section>
    </div>
  );
}

function ProjectsPage({
  projects,
  activeProjectId,
  onCreate,
  onSelect,
  onRename,
  onDelete,
  exportUrl,
  systemBackupUrl,
  onImport,
  onRestore,
}: {
  projects: Project[];
  activeProjectId: number;
  onCreate: (name: string) => Promise<boolean>;
  onSelect: (id: number) => Promise<boolean>;
  onRename: (id: number, name: string) => Promise<boolean>;
  onDelete: (id: number) => Promise<void>;
  exportUrl:(id:number)=>string;
  systemBackupUrl:string;
  onImport:(file:File)=>Promise<void>;
  onRestore:(file:File)=>Promise<void>;
}) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [working, setWorking] = useState(false);

  return (
    <div className="page-stack">
      <section className="content-card project-management-card">
        <div className="project-create-row">
          <h2>新建预测工程</h2>
          <form onSubmit={async (event) => {
            event.preventDefault();
            if (!newName.trim()) return;
            setWorking(true);
            const created = await onCreate(newName.trim());
            if (created) setNewName("");
            setWorking(false);
          }}>
            <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="输入工程名称，例如：和平区完整社区预测" aria-label="新工程名称" />
            <button className="primary-button" type="submit" disabled={working || !newName.trim()}>{working ? "创建中…" : "＋ 新建工程"}</button>
          </form>
        </div>
        <div className="project-data-row">
          <h3>工程数据</h3>
          <div className="actions"><label className="secondary-button file-button">导入工程 ZIP<input type="file" accept=".zip" onChange={e=>{const f=e.target.files?.[0];if(f)void onImport(f);e.currentTarget.value=""}}/></label><button type="button" className="secondary-button" onClick={() => void downloadFile(systemBackupUrl).catch(error => window.alert(error instanceof Error ? error.message : "下载失败"))}>备份全部工程</button><label className="secondary-button file-button">恢复系统备份<input type="file" accept=".zip" onChange={e=>{const f=e.target.files?.[0];if(f)void onRestore(f);e.currentTarget.value=""}}/></label></div>
        </div>
      </section>

      <section className="content-card">
        <div className="project-grid">
          {projects.map((project) => {
            const isActive = project.id === activeProjectId;
            const isEditing = project.id === editingId;
            return (
              <article className={`project-card ${isActive ? "active" : ""}`} key={project.id}>
                <div className="project-card-top"><span className="project-monogram">{project.name.slice(0, 1).toUpperCase()}</span><div className="project-badges">{isActive && <span className="current-badge">当前工程</span>}</div></div>
                {isEditing ? (
                  <form className="rename-form" onSubmit={async (event) => {
                    event.preventDefault();
                    if (!editingName.trim()) return;
                    const renamed = await onRename(project.id, editingName.trim());
                    if (renamed) setEditingId(null);
                  }}>
                    <input autoFocus value={editingName} onChange={(event) => setEditingName(event.target.value)} aria-label="工程新名称" />
                    <button className="primary-button" type="submit">保存</button>
                    <button className="secondary-button" type="button" onClick={() => setEditingId(null)}>取消</button>
                  </form>
                ) : <h3>{project.name}</h3>}
                <div className="project-meta"><span>创建于 {formatTime(project.created_at)}</span><span>更新于 {formatTime(project.updated_at)}</span></div>
                {!isEditing && <div className="project-card-actions">
                  <button className={isActive ? "secondary-button" : "primary-button"} disabled={isActive} onClick={() => void onSelect(project.id)}>{isActive ? "正在使用" : "打开工程"}</button>
                  <button className="secondary-button" title="重命名工程" onClick={() => { setEditingId(project.id); setEditingName(project.name); }}>重命名</button>
                  <button type="button" className="secondary-button" onClick={() => void downloadFile(exportUrl(project.id)).catch(error => window.alert(error instanceof Error ? error.message : "下载失败"))}>导出工程</button>
                  <button className="danger-button" disabled={projects.length === 1} title={projects.length === 1 ? "系统至少需要保留一个工程" : "删除工程"} onClick={() => {
                    if (window.confirm(`确定删除工程“${project.name}”吗？数据库记录会删除，工程文件将移入回收目录。`)) void onDelete(project.id);
                  }}>{projects.length === 1 ? "至少保留一个" : "删除"}</button>
                </div>}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function metricUnit(key: string) { return /占比|比例|率/.test(key) ? "%" : key.includes("面积") ? "㎡" : key.includes("人数") || key.includes("容纳量") ? "人" : "个"; }

function runLabel(run: PredictionRun) {
  const years = run.forecast_years || [];
  return `#${run.id} · ${run.project_name || "当前工程"} · ${run.community_names?.join("、") || "未产生社区结果"} · ${run.kind === "population" ? "人口" : "设施"} · ${years.length ? `${years[0]}—${years.at(-1)}年` : "—"} · 执行 ${formatTime(run.started_at)}`;
}

function CombinationCharts({run, results}: {run:PredictionRun;results:PredictionResultRow[]}) {
  const [groupIndex,setGroupIndex] = useState(0);
  const filtered = results;
  const preferredFacilityGroups = ["助餐设施","养老服务设施","托育服务设施","停车充电设施","公共活动场地"];
  const resultFacilityGroups = [...new Set(filtered.flatMap(row=>Object.keys(row.data.metrics || {}).map(key=>key.split("/",1)[0])))];
  const allGroups = run.kind === "population" ? ["人口规模与年龄结构"] : [...preferredFacilityGroups.filter(group=>resultFacilityGroups.includes(group)), ...resultFacilityGroups.filter(group=>!preferredFacilityGroups.includes(group))];
  const groups = [allGroups[groupIndex] || allGroups[0]];
  return <div className="combination-charts">{run.kind === "facility" && <div className="facility-chart-filter"><label>设施类别<select value={groupIndex} onChange={e=>setGroupIndex(Number(e.target.value))}>{allGroups.map((g,i)=><option key={g} value={i}>{g}</option>)}</select></label></div>}{groups.map(group=>{
    const ageKeys = [...new Set(filtered.flatMap(row=>Object.keys(row.data.ageGroups || {})))];
    const keys = run.kind === "population"
      ? ["总人口", "总户数", ...ageKeys]
      : [...new Set(filtered.flatMap(row=>Object.keys(row.data.metrics || {}).filter(key=>key.startsWith(`${group}/`))))];
    const unitOf=(key:string)=>run.kind==="population" ? (key === "总户数" ? "户" : "人") : metricUnit(key);
    const availableUnits:string[]=run.kind === "population" ? ["人 / 户"] : [...new Set(keys.map(unitOf))].sort((a,b)=>keys.filter(k=>unitOf(k)===b).length-keys.filter(k=>unitOf(k)===a).length);
    const unitLabel=(unit:string)=>unit==="㎡"?"面积（㎡）":unit==="人"?"人数（人）":unit==="%"?"比例（%）":unit==="户"?"户数（户）":unit==="人 / 户"?"人口与户数":"数量（个）";
    const chartGroups=availableUnits.map(unit=>{
      const unitKeys=keys.filter(key=>run.kind === "population" || unitOf(key)===unit);
      const series=unitKeys.flatMap(key=>{
        if (unit === "%") return [...new Set(filtered.map(row=>row.communityId))].map(id=>({name:`${filtered.find(row=>row.communityId===id)?.communityName} · ${key.split("/")[1]}`,unit,isGap:false,values:filtered.filter(row=>row.communityId===id).sort((a,b)=>a.year-b.year).map(row=>({year:row.year,value:row.data.metrics?.[key] || 0}))}));
        const values=new Map<number,number>();
        filtered.forEach(row=>{const value=run.kind === "population" ? (key === "总人口" ? row.data.totalPopulation : key === "总户数" ? row.data.households : row.data.ageGroups?.[key]) : row.data.metrics?.[key];if(value!==undefined)values.set(row.year,(values.get(row.year)||0)+value);});
        const isGap=run.kind === "facility" && key.includes("缺口");
        return {name:key.includes("/")?key.split("/")[1]:key,unit:unitOf(key),isGap,values:[...values.entries()].sort((a,b)=>a[0]-b[0]).map(([year,value])=>({year,value}))};
      });
      return {unit,unitKeys,series};
    });
    return <section className="combination-card" key={group}><div className="section-header facility-result-header"><h3>{group}</h3>{run.kind === "facility" && <span>共 {keys.length} 项</span>}</div>{chartGroups.map(({unit,unitKeys,series})=>{
      return <div className="facility-unit-chart" key={`${group}-${unit}`}><div className="facility-unit-heading"><h4>{unitLabel(unit)}</h4>{run.kind === "facility" && <span>{unitKeys.length} 项</span>}</div><TrendBarChart series={series} unit={unit || ""}/></div>;
    })}</section>;
  })}</div>;
}

type ChartSeries = { name: string; unit?: string; isGap?: boolean; values: Array<{ year: number; value: number }> };
type HoveredChartPoint = { seriesName: string; unit?: string; isGap?: boolean; year: number; value: number; x: number; y: number; color: string };
const CHART_COLORS = ["#078583", "#276cc3", "#8b5cf6", "#ca641b", "#d13769", "#24824c", "#ac8020", "#657591", "#965038", "#cc499b", "#6264d7", "#42849a", "#657021", "#943ab8", "#254778", "#983737"];

function formatChartNumber(value: number) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}

function TrendBarChart({ series: allSeries, unit }: { series: ChartSeries[]; unit: string }) {
  const gradientId = useId();
  const [hidden, setHidden] = useState<string[]>([]);
  const [scale, setScale] = useState(() => {
    const positive = allSeries.flatMap(item => item.values.map(point => point.value)).filter(value => value > 0);
    return positive.length && Math.max(...positive) / Math.min(...positive) > 10 ? "log" : "linear";
  });
  const series = allSeries.filter(item=>!hidden.includes(item.name));
  const transform = (value:number) => scale === "log" ? Math.sign(value)*Math.log10(1+Math.abs(value)) : value;
  const inverse = (value:number) => scale === "log" ? Math.sign(value)*(10**Math.abs(value)-1) : value;
  const [hoveredPoint, setHoveredPoint] = useState<HoveredChartPoint | null>(null);
  const width = 1080;
  const height = 390;
  const margin = { top: 30, right: 30, bottom: 58, left: 84 };
  const years = Array.from(new Set(series.flatMap((item) => item.values.map((point) => point.year)))).sort();
  const values = series.flatMap((item) => item.values.map((point) => point.value));
  if (!years.length || !values.length) return <div className="empty-state">该批次没有可绘制的数据</div>;

  const rawMin = transform(Math.min(...values));
  const rawMax = transform(Math.max(...values));
  const rawRange = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.2, 1);
  const domainMin = rawMin < 0 ? rawMin - rawRange * 0.1 : 0;
  const domainMax = rawMax > 0 ? rawMax + rawRange * 0.12 : 0;
  const domainRange = domainMax - domainMin || 1;
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const yearSlot = chartWidth / years.length;
  const groupWidth = Math.min(yearSlot * 0.78, 156);
  const barGap = series.length > 8 ? 1.5 : 3;
  const barWidth = Math.max(3, (groupWidth - barGap * Math.max(0, series.length - 1)) / Math.max(series.length, 1));
  const yearCenter = (year: number) => margin.left + (years.indexOf(year) + 0.5) * yearSlot;
  const barX = (year: number, seriesIndex: number) => yearCenter(year) - groupWidth / 2 + seriesIndex * (barWidth + barGap);
  const axisY = (value: number) => margin.top + ((domainMax - value) / domainRange) * chartHeight;
  const y = (value:number) => axisY(transform(value));
  const zeroY = axisY(0);
  const ticks = Array.from({ length: 5 }, (_, index) => domainMax - (domainRange * index) / 4);

  return (
    <div className="trend-chart-wrap bar-chart-wrap"><div className="chart-scale-toolbar"><label>纵轴尺度<select value={scale} onChange={e=>{setScale(e.target.value);setHoveredPoint(null);}}><option value="linear">真实数值 · 自动范围</option><option value="log">对数尺度 · 展开小数值</option></select></label></div>
      <svg className="trend-chart bar-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="预测年度分组柱状图">
        <defs>
          {series.map((item, index) => <linearGradient id={`${gradientId}-bar-${index}`} x1="0" y1="0" x2="0" y2="1" key={item.name}><stop offset="0%" stopColor={CHART_COLORS[allSeries.findIndex(s=>s.name===item.name) % CHART_COLORS.length]} stopOpacity="1" /><stop offset="100%" stopColor={CHART_COLORS[allSeries.findIndex(s=>s.name===item.name) % CHART_COLORS.length]} stopOpacity="0.68" /></linearGradient>)}
          <linearGradient id={`${gradientId}-surplus`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38b27b" /><stop offset="100%" stopColor="#78d4a8" /></linearGradient>
          <filter id={`${gradientId}-shadow`} x="-30%" y="-20%" width="160%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="5" floodColor="#092c3f" floodOpacity="0.18" /></filter>
        </defs>
        {ticks.map((tick) => <g key={tick}><line className="chart-grid-line" x1={margin.left} x2={width - margin.right} y1={axisY(tick)} y2={axisY(tick)} /><text className="chart-axis-label" x={margin.left - 13} y={axisY(tick) + 4} textAnchor="end">{formatChartNumber(inverse(tick))}</text></g>)}
        <line className="chart-zero-line" x1={margin.left} x2={width - margin.right} y1={zeroY} y2={zeroY} />
        {years.map((year) => <g key={year}><rect className="chart-year-band" x={margin.left + years.indexOf(year) * yearSlot + yearSlot * 0.05} y={margin.top} width={yearSlot * 0.9} height={chartHeight} rx="8" /><text className="chart-axis-label chart-year-label" x={yearCenter(year)} y={height - 22} textAnchor="middle">{year}</text></g>)}
        <text className="chart-unit" x={margin.left} y={14}>{unit}</text>
        {series.map((item, index) => {
          const color = CHART_COLORS[allSeries.findIndex(s=>s.name===item.name) % CHART_COLORS.length];
          return <g key={item.name}>{item.values.map((point) => {
            const valueY = y(point.value);
            const rectY = Math.min(valueY, zeroY);
            const rectHeight = Math.max(2, Math.abs(zeroY - valueY));
            const x = barX(point.year, index);
            const surplus = Boolean(item.isGap && point.value < 0);
            return <rect className={`chart-bar${surplus ? " surplus-bar" : ""}`} data-testid={`chart-bar-${index}-${point.year}`} key={`${item.name}-${point.year}`} x={x} y={rectY} width={barWidth} height={rectHeight} rx={Math.min(5, barWidth / 2)} fill={`url(#${surplus ? `${gradientId}-surplus` : `${gradientId}-bar-${index}`})`} filter={`url(#${gradientId}-shadow)`} onPointerEnter={() => setHoveredPoint({ seriesName: item.name, unit: item.unit, isGap:item.isGap, year: point.year, value: point.value, x: x + barWidth / 2, y: rectY, color:surplus ? "#38b27b" : color })} onPointerLeave={() => setHoveredPoint(null)} />;
          })}</g>;
        })}
        {hoveredPoint && <g className="chart-tooltip" pointerEvents="none" transform={`translate(${Math.min(Math.max(hoveredPoint.x, 122), width - 122)} ${Math.max(hoveredPoint.y - 12, 58)})`}>
          <line className="chart-tooltip-guide" x1="0" x2="0" y1={12} y2={height - margin.bottom - Math.max(hoveredPoint.y - 12, 58)} />
          <rect x="-112" y="-44" width="224" height="48" rx="8" />
          <circle cx="-98" cy="-28" r="4" fill={hoveredPoint.color} />
          <text className="chart-tooltip-title" x="-88" y="-25">{hoveredPoint.seriesName}</text>
          <text className="chart-tooltip-value" x="-98" y="-8">{hoveredPoint.year}年 · {formatChartNumber(hoveredPoint.value)}{hoveredPoint.unit || unit}</text>
        </g>}
      </svg>
      <div className="chart-legend">{allSeries.map((item) => <button type="button" aria-pressed={!hidden.includes(item.name)} style={{opacity:hidden.includes(item.name)?0.35:1}} onClick={()=>{setHoveredPoint(null);setHidden(hidden.includes(item.name)?hidden.filter(n=>n!==item.name):hidden.length<allSeries.length-1?[...hidden,item.name]:hidden);}} key={item.name}><i className="bar-legend-swatch" style={{ background: CHART_COLORS[allSeries.findIndex(s=>s.name===item.name) % CHART_COLORS.length] }} />{item.name}</button>)}</div>
    </div>
  );
}

function ResultsPage({ runs, api, onDeleteRun, onClear, onReportGenerated, communityFilterId, readOnly = false, communities = [] }: { runs: PredictionRun[]; api: CommunityApi; onDeleteRun: (run: PredictionRun) => Promise<void>; onClear?: () => Promise<void>; onReportGenerated?: () => Promise<void>; communityFilterId?: number; readOnly?:boolean; communities?:Community[] }) {
  const [selectedCommunityId,setSelectedCommunityId] = useState(communityFilterId || communities[0]?.id || runs.flatMap(r=>r.community_ids || [])[0] || 0);
  const [kind,setKind] = useState("population");
  const communityOptions=[...new Map([...runs.flatMap(r=>(r.community_ids || []).map((id,i)=>[id,r.community_names?.[i] || ("社区 "+id)] as const)),...communities.map(c=>[c.id,`${c.code} · ${c.name}`] as const)]).entries()];
  const effectiveCommunityId=communityFilterId || selectedCommunityId;
  const successfulRuns = runs.filter(run=>run.status==="success" && run.kind===kind && run.community_ids?.includes(effectiveCommunityId));
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [chartResults, setChartResults] = useState<PredictionResultRow[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState("");
  const [deletingRunId, setDeletingRunId] = useState<number | null>(null);
  const chartCardRef = useRef<HTMLElement>(null);
  const [clearing, setClearing] = useState(false);
  const [showCalculation,setShowCalculation]=useState(false);
  const populationReady = runs.some((run) => run.kind === "population" && run.status === "success");
  const facilityRuns = runs.filter((run) => run.kind === "facility" && run.status === "success");
  const [reportMode, setReportMode] = useState<"community" | "overall">(communityFilterId ? "community" : "overall");
  const [reportCommunityId, setReportCommunityId] = useState(communityFilterId || selectedCommunityId || communityOptions[0]?.[0] || 0);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState("");
  const [generatedReportId, setGeneratedReportId] = useState<number | null>(null);

  const reportRun = facilityRuns.find((run) => reportMode === "overall" || run.community_ids?.includes(reportCommunityId));
  useEffect(() => {
    if (communityFilterId) setReportCommunityId(communityFilterId);
  }, [communityFilterId]);
  const showRunChart = (runId: number) => {
    const run = runs.find(item => item.id === runId);
    if (run) {
      setKind(run.kind);
      if (!communityFilterId && !run.community_ids?.includes(effectiveCommunityId)) setSelectedCommunityId(run.community_ids?.[0] || 0);
    }
    setSelectedRunId(runId);
    window.requestAnimationFrame(() => chartCardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const confirmDeleteRun = async (run: PredictionRun) => {
    if (!window.confirm(`确定删除预测批次 #${run.id} 吗？系统会先在回收目录保留内部备份。`)) return;
    setDeletingRunId(run.id);
    try {
      await onDeleteRun(run);
    } catch (error) { setChartError(error instanceof Error ? error.message : "删除失败"); } finally {
      setDeletingRunId(null);
    }
  };

  useEffect(() => {
    if (!successfulRuns.some((run) => run.id === selectedRunId)) setSelectedRunId(successfulRuns[0]?.id || null);
  }, [selectedRunId, successfulRuns]);

  useEffect(() => {
    if (!selectedRunId) { setChartResults([]); return; }
    let cancelled = false;
    setChartLoading(true);
    setChartError("");
    void api.getRunResults(selectedRunId).then((rows) => { if (!cancelled) setChartResults(rows.filter(row => row.communityId === effectiveCommunityId)); }).catch((error) => { if (!cancelled) setChartError(error instanceof Error ? error.message : "结果加载失败"); }).finally(() => { if (!cancelled) setChartLoading(false); });
    return () => { cancelled = true; };
  }, [api, selectedRunId, effectiveCommunityId]);

  const selectedRun = successfulRuns.find((run) => run.id === selectedRunId);
  const generateReport = async () => {
    if (!reportRun) return;
    setReportBusy(true);
    setReportError("");
    try {
      await api.generateReport(reportRun.id, reportMode, reportMode === "community" ? reportCommunityId : undefined);
      setGeneratedReportId(reportRun.id);
      await onReportGenerated?.();
    } catch (error) {
      setReportError(error instanceof Error ? error.message : "报告生成失败");
    } finally {
      setReportBusy(false);
    }
  };
  return (
    <div className="page-stack">
      {!communityFilterId && <section className="content-card report-generation-card">
        <div className="report-generation-heading"><span aria-hidden="true">DOC</span><h2>生成 Word 报告</h2></div>
        {readOnly ? <p className="report-generation-note">只读工程不能重新生成报告。</p> : populationReady && facilityRuns.length ? <div className="report-generation-controls">
          <label><span>报告范围</span><select value={reportMode} onChange={(event) => { setReportMode(event.target.value as "community" | "overall"); setGeneratedReportId(null); setReportError(""); }}><option value="overall">整体报告</option><option value="community">分社区报告</option></select></label>
          {reportMode === "community" && <label><span>选择社区</span><select value={reportCommunityId || ""} onChange={(event) => { setReportCommunityId(Number(event.target.value)); setGeneratedReportId(null); setReportError(""); }}>{communityOptions.map(([id,name]) => <option value={id} key={id}>{name}</option>)}</select></label>}
          <button className="primary-button" disabled={reportBusy || !reportRun} onClick={() => void generateReport()}>{reportBusy ? "正在生成…" : "生成 Word 报告"}</button>
          {generatedReportId && <button type="button" className="secondary-button generated-report-download" onClick={() => void downloadFile(api.reportUrl(generatedReportId)).catch(error => setReportError(error instanceof Error ? error.message : "报告下载失败"))}>下载报告</button>}
        </div> : <p className="report-generation-note">请先完成人口预测和设施预测。</p>}
        {reportError && <p role="alert" className="inline-error report-generation-error">{reportError}</p>}
      </section>}
      <section className="content-card chart-card" ref={chartCardRef}><div className="result-selectors">{!communityFilterId && <label>选择社区<select value={selectedCommunityId} onChange={e=>setSelectedCommunityId(Number(e.target.value))}>{communityOptions.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}<label>预测类型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="population">人口预测</option><option value="facility">设施预测</option></select></label></div>
        <div className="result-chart-toolbar"><button className="secondary-button" disabled={!selectedRun} onClick={()=>setShowCalculation(value=>!value)}>{showCalculation ? "收起计算逻辑及说明" : "查看计算逻辑及说明"}</button>{successfulRuns.length > 0 && <label>预测批次<select value={selectedRunId || ""} onChange={(event) => setSelectedRunId(Number(event.target.value))}>{successfulRuns.map((run) => <option value={run.id} key={run.id}>{runLabel(run)}</option>)}</select></label>}</div>
        {showCalculation && selectedRun && <CalculationPanel key={`${selectedRun.id}-${effectiveCommunityId}`} api={api} runId={selectedRun.id} communityId={effectiveCommunityId} years={selectedRun.forecast_years || []} onClose={()=>setShowCalculation(false)}/>}
        {chartLoading ? <LoadingBlock label="正在加载预测趋势" /> : chartError ? <div className="inline-error">{chartError}</div> : selectedRun ? <><CombinationCharts key={`${selectedRun.id}-${effectiveCommunityId}`} run={selectedRun} results={chartResults} /></> : <div className="empty-state">所选社区暂无该类型的成功预测，请切换类型、社区或先执行预测。</div>}
      </section>
      <section className="content-card">
        <div className="section-header"><div><h2>预测批次</h2></div>{onClear && !readOnly && <button className="danger-button" disabled={clearing || !runs.length || runs.some(run => run.status === "running")} onClick={async () => {if(!window.confirm("清除当前工程全部预测历史及结果文件？社区和参数保留，清除前自动备份。"))return;setClearing(true);try{await onClear();}catch(error){setChartError(error instanceof Error ? error.message : "清除失败");}finally{setClearing(false);}}}>{clearing ? "清除中…" : "一键清除历史"}</button>}</div>
        <div className="runs-table">
          <div className="runs-head"><span>批次</span><span>类型</span><span>状态</span><span>开始时间</span><span>输出</span></div>
          {runs.length === 0 ? <div className="empty-state">尚未运行预测</div> : runs.map((run) => (
            <div className={`runs-row ${selectedRunId === run.id ? "selected" : ""}`} key={run.id}>
              <span title={runLabel(run)}>#{run.id}<small className="run-context">{run.project_name}<br/>{run.community_names?.join("、") || "无社区结果"}<br/>{run.forecast_years?.length ? `${run.forecast_years[0]}—${run.forecast_years.at(-1)}年` : "尚无预测年度"}</small></span><span>{run.kind === "population" ? "人口预测" : "设施预测"}</span>
              <span className={`status ${run.status}`}>{run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "运行中"}</span>
              <span>{formatTime(run.started_at)}</span>
              <span className="result-links">
                {run.status === "success" ? <><button className="chart-action" onClick={() => showRunChart(run.id)}>查看图表</button><button type="button" onClick={() => void downloadFile(api.downloadUrl(run.id)).catch(error => setChartError(error instanceof Error ? error.message : "下载失败"))}>下载结果</button>{run.kind === "facility" && run.report_available && <button type="button" onClick={() => void downloadFile(api.reportUrl(run.id)).catch(error => setChartError(error instanceof Error ? error.message : "报告下载失败"))}>下载报告</button>}</> : <span className="run-error-message">{run.error_message || "—"}</span>}
                {run.status !== "running" && <><button type="button" onClick={() => void downloadFile(api.backupUrl(run.id)).catch(error => setChartError(error instanceof Error ? error.message : "备份下载失败"))}>备份</button><button hidden={readOnly} className="run-delete-action" disabled={deletingRunId === run.id} onClick={() => void confirmDeleteRun(run)}>{deletingRunId === run.id ? "删除中" : "删除"}</button></>}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function CommunityPredictionModule({
  mode = "standalone",
  apiBase,
  token,
  projectId,
  hostContext,
  hostOrigin = "*",
  defaultTheme,
  onEvent,
}: CommunityPredictionModuleProps) {
  const api = useMemo(() => new CommunityApi({ baseUrl: apiBase, token, hostContext }), [apiBase, token, hostContext]);
  const [page, setPage] = useState<Page>("dashboard");
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(projectId || null);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [allCommunities, setAllCommunities] = useState<Community[]>([]);
  const [communitySearchQuery, setCommunitySearchQuery] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard>(EMPTY_DASHBOARD);
  const [parameters, setParameters] = useState<Record<string, ParameterSet | null>>({ population: null, facility: null });
  const [runs, setRuns] = useState<PredictionRun[]>([]);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const navigatePage = (next: Page) => { if (next !== page && editorDirty && !window.confirm("放弃尚未保存的社区修改？")) return; setPage(next); };
  const [selectedCommunityTab,setSelectedCommunityTab] = useState("社区基础信息");
  const [selectedCommunity, setSelectedCommunity] = useState<Community | null>(null);
  const [communityRegions, setCommunityRegions] = useState<string[]>(["全国"]);
  const [populationBaseYear, setPopulationBaseYear] = useState(new Date().getFullYear());
  const [populationRange, setPopulationRange] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [startupError, setStartupError] = useState("");
  const [initializationVersion, setInitializationVersion] = useState(0);
  const [busy, setBusy] = useState("");
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [theme, setTheme] = useState<Theme>(defaultTheme || "light");
  const toastTimerRef = useRef<number | null>(null);
  const projectDataRequestRef = useRef(0);
  const communitySearchRequestRef = useRef(0);
  const activeProjectIdRef = useRef<number | null>(activeProjectId);
  const drafts = useRef<Record<number, Record<string, Record<string, unknown>>>>({});
  const [, refreshDirty] = useState(0);
  const changeDraft = (kind: string, data: Record<string, unknown>) => {
    if (!activeProjectId) return;
    (drafts.current[activeProjectId] ||= {})[kind] = data;
    refreshDirty((value) => value + 1);
  };
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (Object.values(drafts.current).some((entry) => Object.keys(entry).length)) {
        event.preventDefault(); event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  useEffect(() => {
    activeProjectIdRef.current = activeProjectId;
  }, [activeProjectId]);

  const notify = useCallback((event: ModuleEvent) => {
    onEvent?.(event);
    emitHostEvent(event, hostOrigin);
  }, [hostOrigin, onEvent]);

  const showToast = useCallback((message: string, error = false) => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    setToast({ message, error });
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null);
      toastTimerRef.current = null;
    }, 3500);
  }, []);

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  useEffect(() => {
    setQuality(null);
  }, [activeProjectId]);

  const toggleTheme = useCallback(() => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    notify({ type: "theme-changed", payload: { theme: nextTheme } });
  }, [notify, theme]);

  const refreshProjectData = useCallback(async (id: number, query = "") => {
    const requestId = ++projectDataRequestRef.current;
    const [communityData, dashboardData, runData] = await Promise.all([
      api.listCommunities(id, query), api.dashboard(id), api.listRuns(id),
    ]);
    if (requestId !== projectDataRequestRef.current) return false;
    setCommunities(communityData);
    setCommunitySearchQuery(query);
    if (!query) setAllCommunities(communityData);
    setDashboard(dashboardData);
    setRuns(runData);
    return true;
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setStartupError("");
      try {
        await api.health();
        if (cancelled) return;
        let data = await api.listProjects();
        if (cancelled) return;
        if (data.length === 0) {
          try {
            const defaultProject = await api.createProject("我的预测工程");
            data = [defaultProject];
            notify({ type: "project-created", payload: defaultProject });
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 409) throw error;
            data = await api.listProjects();
          }
        }
        if (cancelled) return;
        setProjects(data);
        const selected = projectId && data.some((item) => item.id === projectId) ? projectId : data[0].id;
        activeProjectIdRef.current = selected;
        setActiveProjectId(selected);
        await refreshProjectData(selected);
        notify({ type: "module-ready", payload: { projectId: selected } });
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "后端服务不可用";
        setStartupError(message);
        notify({ type: "module-error", payload: { message } });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [api, initializationVersion, notify, projectId, refreshProjectData]);

  useEffect(() => {
    if (!activeProjectId || !["population", "facility"].includes(page)) return;
    const kind = page as "population" | "facility";
    let cancelled = false;
    setParameters((current) => ({ ...current, [kind]: null }));
    void api.getParameters(activeProjectId, kind).then((value) => {
      if (!cancelled) setParameters((current) => ({ ...current, [kind]: { ...value, data: drafts.current[activeProjectId]?.[kind] || value.data } }));
    }).catch((error) => {
      if (!cancelled) showToast(error instanceof Error ? error.message : "参数加载失败", true);
    });
    return () => { cancelled = true; };
  }, [activeProjectId, api, page, showToast]);

  useEffect(() => { setSelectedCommunity(null); }, [activeProjectId]);
  useEffect(() => {
    if (!activeProjectId) return;
    let cancelled = false;
    void api.getParameters(activeProjectId, "population").then(parameter => {
      if (!cancelled) {
        setCommunityRegions(Object.keys((parameter.data.birthRates || {}) as Record<string, unknown>));
        setPopulationBaseYear(Number(parameter.data.startYear));
        setPopulationRange(parameter.data);
      }
    }).catch(error => showToast(String(error), true));
    return () => { cancelled = true; };
  }, [activeProjectId, api, parameters.population, showToast]);

  const create = async (name: string) => {
    try {
      const project = await api.createProject(name);
      setProjects((current) => [project, ...current]);
      activeProjectIdRef.current = project.id;
      setActiveProjectId(project.id);
      setParameters({ population: null, facility: null });
      await refreshProjectData(project.id);
      setPage("dashboard");
      notify({ type: "project-created", payload: project });
      showToast("工程创建成功");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "工程创建失败", true);
      return false;
    }
  };

  const selectProject = async (id: number): Promise<boolean> => {
    if (id === activeProjectId) return true;
    if (editorDirty && !window.confirm("切换工程将放弃尚未保存的社区修改，是否继续？")) return false;
    try {
      const loaded = await refreshProjectData(id);
      if (!loaded) return false;
      activeProjectIdRef.current = id;
      setActiveProjectId(id);
      setParameters({ population: null, facility: null });
      communitySearchRequestRef.current += 1;
      notify({ type: "project-changed", payload: { projectId: id } });
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "工程切换失败", true);
      return false;
    }
  };

  const renameProject = async (id: number, name: string) => {
    try {
      const saved = await api.renameProject(id, name);
      setProjects((current) => current.map((item) => item.id === id ? saved : item));
      notify({ type: "project-renamed", payload: saved });
      showToast("工程名称已更新");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "工程重命名失败", true);
      return false;
    }
  };

  const deleteProject = async (id: number) => {
    if (projects.length <= 1) {
      showToast("系统至少需要保留一个工程，请先新建工程后再删除", true);
      return;
    }
    try {
      await api.deleteProject(id);
      const remaining = projects.filter((item) => item.id !== id);
      setProjects(remaining);
      if (activeProjectId === id) {
        const nextProject = remaining[0];
        await refreshProjectData(nextProject.id);
        activeProjectIdRef.current = nextProject.id;
        setActiveProjectId(nextProject.id);
        setParameters({ population: null, facility: null });
      }
      notify({ type: "project-deleted", payload: { projectId: id } });
      showToast("工程已删除，文件已转入回收目录");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "工程删除失败", true);
    }
  };

  const importProjectArchive = async (file:File) => {
    try { const imported=await api.importProjectArchive(file);const list=await api.listProjects();setProjects(list);await selectProject(imported.id);setPage("dashboard");showToast(`工程“${imported.name}”已导入，路径已重建`); }
    catch(error){showToast(error instanceof Error?error.message:"工程导入失败",true);}
  };
  const restoreSystemBackup = async (file:File) => {
    try { const result=await api.restoreSystem(file);setProjects(await api.listProjects());showToast(`已从备份恢复 ${result.restoredCount} 个工程副本`); }
    catch(error){showToast(error instanceof Error?error.message:"系统备份恢复失败",true);}
  };

  const fixQualityIssue = (target:Page,communityId?:number) => {
    if(target==="communities" && communityId){const item=allCommunities.find(c=>c.id===communityId);if(item){setSelectedCommunityTab("社区基础信息");setSelectedCommunity(item);}}
    setPage(target);
  };

  const runPrediction = async (kind: "population" | "facility") => {
    if (!activeProjectId) return;
    const targetProjectId = activeProjectId;
    setBusy(kind);
    try {
      if (kind === "population") {
        const data = drafts.current[targetProjectId]?.population || (await api.getParameters(targetProjectId, "population")).data;
        const issues = populationParameterIssues(data);
        if (issues.length) throw new Error(issues.join("；"));
      }
      for (const [draftKind, data] of Object.entries(drafts.current[targetProjectId] || {})) {
        await api.saveParameters(targetProjectId, draftKind as "population" | "facility", data);
        if (drafts.current[targetProjectId]?.[draftKind] === data) delete drafts.current[targetProjectId][draftKind];
      }
      refreshDirty((value) => value + 1);
      const report=await api.quality(targetProjectId,kind);
      setQuality(report);
      if(!report.ready){showToast(`预测前检查未通过：请修正 ${report.errorCount} 项问题`,true);return;}
      const run = kind === "population" ? await api.runPopulation(targetProjectId) : await api.runFacility(targetProjectId);
      if (activeProjectIdRef.current !== targetProjectId) return;
      await refreshProjectData(targetProjectId);
      showToast(`${kind === "population" ? "人口" : "设施"}预测成功`);
      notify({ type: "prediction-completed", payload: run });
      setPage("results");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "预测失败", true);
      notify({ type: "prediction-failed", payload: { kind, message: String(error) } });
    } finally {
      setBusy("");
    }
  };

  const saveParameters = async (kind: "population" | "facility", data: Record<string, unknown>) => {
    if (!activeProjectId) return;
    const targetProjectId = activeProjectId;
    try {
      const saved = await api.saveParameters(targetProjectId, kind, data);
      if (JSON.stringify(drafts.current[targetProjectId]?.[kind]) === JSON.stringify(data)) delete drafts.current[targetProjectId][kind];
      refreshDirty((value) => value + 1);
      if (activeProjectIdRef.current !== targetProjectId) return;
      setParameters((current) => ({ ...current, [kind]: { ...saved, data: drafts.current[targetProjectId]?.[kind] || saved.data } }));
      showToast(`${kind === "population" ? "人口" : "设施"}参数已保存`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "参数保存失败", true);
    }
  };

  const importParameters = async (kind: "population" | "facility", file: File) => {
    if (!activeProjectId) return;
    const targetProjectId = activeProjectId;
    try {
      const saved = await api.importParameters(targetProjectId, kind, file);
      if (drafts.current[targetProjectId]) delete drafts.current[targetProjectId][kind];
      refreshDirty((value) => value + 1);
      if (activeProjectIdRef.current !== targetProjectId) return;
      setParameters((current) => ({ ...current, [kind]: saved }));
      showToast(`${kind === "population" ? "人口" : "设施"}参数导入成功`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "参数导入失败", true);
    }
  };

  const createCommunity = async (payload: Partial<Community>) => {
    if (!activeProjectId) return false;
    const targetProjectId = activeProjectId;
    try {
      await api.createCommunity(targetProjectId, payload);
      if (activeProjectIdRef.current !== targetProjectId) return true;
      await refreshProjectData(targetProjectId);
      showToast("社区创建成功");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "社区创建失败", true);
      return false;
    }
  };

  const importCommunity = async (file: File): Promise<CommunityImportReport> => {
    if (!activeProjectId) {
      return { filename: file.name, total_count: 1, success_count: 0, created_count: 0, updated_count: 0, failed_count: 1, issues: [{ field: "工程", message: "当前没有可用工程" }] };
    }
    const targetProjectId = activeProjectId;
    try {
      const report = await api.importCommunity(targetProjectId, file);
      if (activeProjectIdRef.current !== targetProjectId) return report;
      if (report.success_count) {
        await refreshProjectData(targetProjectId);
        showToast(report.updated_count ? "社区数据更新成功" : "社区导入成功");
      } else {
        showToast(`导入失败，发现 ${report.issues.length} 处异常字段`, true);
      }
      return report;
    } catch (error) {
      const message = error instanceof Error ? error.message : "社区导入失败";
      showToast(message, true);
      return { filename: file.name, total_count: 1, success_count: 0, created_count: 0, updated_count: 0, failed_count: 1, issues: [{ field: "文件", message }] };
    }
  };

  const searchCommunities = (query: string) => {
    setCommunitySearchQuery(query);
    if (!activeProjectId) return;
    const targetProjectId = activeProjectId;
    const requestId = ++communitySearchRequestRef.current;
    void api.listCommunities(targetProjectId, query).then((items) => {
      if (requestId === communitySearchRequestRef.current && activeProjectIdRef.current === targetProjectId) setCommunities(items);
    }).catch((error) => showToast(error instanceof Error ? error.message : "社区搜索失败", true));
  };

  const deletePredictionRun = async (run: PredictionRun) => {
    if (!activeProjectId) return;
    try {
      await api.deleteRun(run.id);
      await refreshProjectData(activeProjectId);
      showToast(`预测批次 #${run.id} 已删除，内部备份已保留在回收目录`);
      notify({ type: "prediction-run-deleted", payload: { runId: run.id, projectId: activeProjectId } });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "预测批次删除失败", true);
      throw error;
    }
  };

  const updateCommunity = async (payload: Partial<Community>) => {
    if (!activeProjectId || !selectedCommunity) return false;
    const id = activeProjectId;
    try {
      const saved = await api.updateCommunity(id, selectedCommunity.id, payload);
      if (activeProjectIdRef.current !== id) return true;
      setSelectedCommunity(saved);
      await refreshProjectData(id);
      showToast("社区资料已保存；历史结果不变，请重新预测更新结果");
      return true;
    } catch (error) { showToast(error instanceof Error ? error.message : "保存失败", true); return false; }
  };
  const clearHistory = async () => {
    if (!activeProjectId) return;
    const id = activeProjectId;
    const result = await api.clearRuns(id, runs.map(run => run.id));
    if (activeProjectIdRef.current === id) await refreshProjectData(id);
    showToast(`已清除 ${result.deleted_count} 个批次，内部备份保留在回收目录`);
  };

  const shellClassName = `module-shell ${mode} theme-${theme} single-workspace`;
  if (loading) return <div className={shellClassName}><div className="floating-theme"><ThemeToggle theme={theme} onToggle={toggleTheme} /></div><LoadingBlock label="正在连接预测服务" /></div>;
  if (startupError) return <div className={shellClassName}><div className="floating-theme"><ThemeToggle theme={theme} onToggle={toggleTheme} /></div><main className="service-error"><div className="service-error-mark">!</div><h1>无法连接预测服务</h1><p>{startupError}</p><button className="primary-button" onClick={() => setInitializationVersion((value) => value + 1)}>重新连接</button></main></div>;
  if (projects.length === 0) return <div className={shellClassName}><div className="floating-theme"><ThemeToggle theme={theme} onToggle={toggleTheme} /></div><LoadingBlock label="正在初始化默认工程" /></div>;

  const activeProject = projects.find((item) => item.id === activeProjectId) || projects[0];
  return (
    <div className={shellClassName}>
      {toast && <div className={`toast ${toast.error ? "error" : "success"}`}>{toast.message}</div>}
      <CreateProjectDialog open={showCreateProject} onClose={() => setShowCreateProject(false)} onCreate={create} />
      <header className="topbar">
        <div className="brand"><BrandMark /><div><strong>完整社区预测</strong></div></div>
        <div className="project-context">
          <span>当前工程</span>
          <select value={activeProject.id} onChange={(event) => void selectProject(Number(event.target.value))}>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>
          <small>{editorDirty ? "社区资料未保存" : Object.keys(drafts.current[activeProject.id] || {}).length ? "参数未保存（预测前自动保存）" : "已保存"}</small>
        </div>
        <div className="run-actions">
          <button className="accent" type="button" onClick={() => { if (!editorDirty || window.confirm("新建工程将离开当前社区编辑，是否继续？")) setShowCreateProject(true); }}>＋ 新建工程</button>
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </div>
      </header>
      <div className="app-body">
        <main className="main-content">
          <nav className="workspace-nav" aria-label="完整社区预测功能">{([ 
            ["dashboard","社区数据",dashboard.community_count ? `${dashboard.community_count} 个社区` : "待录入"],
            ["population","人口预测",runs.some(r=>r.kind==="population" && r.status==="success") ? "已有结果" : "待执行"],
            ["facility","设施预测",runs.some(r=>r.kind==="facility" && r.status==="success") ? "已有结果" : "待执行"],
            ["results","结果报告",runs.some(r=>r.report_available) ? "报告可下载" : "预测后查看"],
            ["communities","社区管理",`${dashboard.community_count} 个社区`],
            ["projects","工程管理",`${projects.length} 个工程`],
          ] as Array<[Page,string,string]>).map(([target,title,status],i)=><button className={page===target?"active":""} key={target} onClick={()=>navigatePage(target)}><b>{i+1}</b><span><strong>{title}</strong></span><em>{status}</em></button>)}</nav>

          {page === "communities" && !selectedCommunity && <div className="page-tools"><input className="search-input page-search" aria-label="搜索社区" placeholder="搜索社区编号、名称或地区" value={communitySearchQuery} onChange={(event) => searchCommunities(event.target.value)} /></div>}
          {page === "dashboard" && <CommunityDataInputPage communities={allCommunities} exportHref={id=>api.communityTemplateUrl(activeProject.id,id)} readOnly={false} onDirtyChange={setEditorDirty} key={activeProject.id} regions={communityRegions} baseYear={populationBaseYear} dashboard={dashboard} onCreate={createCommunity} onImport={importCommunity} />}
          {page === "projects" && <ProjectsPage projects={projects} activeProjectId={activeProject.id} onCreate={create} onSelect={selectProject} onRename={renameProject} onDelete={deleteProject} exportUrl={id=>api.projectExportUrl(id)} systemBackupUrl={api.systemBackupUrl()} onImport={importProjectArchive} onRestore={restoreSystemBackup} />}
          {page === "population" && <div className="page-stack"><PopulationParameterForm readOnly={false} onDraftChange={(data) => changeDraft("population", data)} value={parameters.population} templateHref={api.parameterTemplateUrl(activeProject.id, "population")} onSave={(data) => saveParameters("population", data)} onImport={(file) => importParameters("population", file)} /><PredictionRunPanel readOnly={false} kind="population" busy={busy} communityCount={dashboard.community_count} runCount={runs.filter((run) => run.kind === "population").length} quality={quality?.kind==="population"?quality:null} onFix={fixQualityIssue} onRun={() => void runPrediction("population")} /></div>}
          {page === "facility" && <div className="page-stack"><FacilityParameterForm readOnly={false} key={activeProject.id} populationParameters={drafts.current[activeProject.id]?.population || parameters.population?.data || populationRange} onDraftChange={(data) => changeDraft("facility", data)} value={parameters.facility} templateHref={api.parameterTemplateUrl(activeProject.id, "facility")} onSave={(data) => saveParameters("facility", data)} onImport={(file) => importParameters("facility", file)} /><PredictionRunPanel readOnly={false} kind="facility" busy={busy} communityCount={dashboard.community_count} runCount={runs.filter((run) => run.kind === "facility").length} populationReady={runs.some((run) => run.kind === "population" && run.status === "success")} quality={quality?.kind==="facility"?quality:null} onFix={fixQualityIssue} onRun={() => void runPrediction("facility")} /></div>}
          {page === "communities" && (selectedCommunity ? <CommunityEditor exportHref={api.communityTemplateUrl(activeProject.id,selectedCommunity.id)} readOnly={false} initialTab={selectedCommunityTab} onDirtyChange={setEditorDirty} key={selectedCommunity.id} community={selectedCommunity} regions={communityRegions} baseYear={populationBaseYear} onSave={updateCommunity} onCancel={() => setSelectedCommunity(null)} hasResults={runs.some(run => run.status === "success" && run.community_ids?.includes(selectedCommunity.id))} results={<ResultsPage communities={communities} readOnly={false} runs={runs.filter(run => run.community_ids?.includes(selectedCommunity.id))} api={api} onDeleteRun={deletePredictionRun} communityFilterId={selectedCommunity.id} onReportGenerated={async()=>{await refreshProjectData(activeProject.id);}} />} /> : <CommunitiesPage communities={communities} onOpen={(community,tab)=>{if(tab==="预测结果" && !runs.some(r=>r.status==="success" && r.community_ids?.includes(community.id))){showToast("该社区尚无成功预测，请先执行预测。",true);return;}setSelectedCommunityTab(tab || "社区基础信息");setSelectedCommunity(community);}} />)}
          {page === "results" && <ResultsPage communities={allCommunities} readOnly={false} key={activeProject.id} runs={runs} api={api} onDeleteRun={deletePredictionRun} onClear={clearHistory} onReportGenerated={async()=>{await refreshProjectData(activeProject.id);}} />}
        </main>
      </div>
    </div>
  );
}

export default CommunityPredictionModule;
