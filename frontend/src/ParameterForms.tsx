import { useEffect, useState } from "react";
import { forecastYears, orderedYears, validRate, fillMissingPopulationYears, mortalityGroups } from "./forecastParameters";
import type { ParameterSet } from "./types";
import { downloadFile } from "./api";

type Data = Record<string, unknown>;
type ParameterFormProps = {
  value: ParameterSet | null;
  onDraftChange: (data: Data) => void;
  templateHref: string;
  onSave: (data: Data) => Promise<void>;
  onImport: (file: File) => Promise<void>;
  readOnly?: boolean;
};

function useParameterDraft(value: ParameterSet | null, onDraftChange: (data: Data) => void) {
  const [draft, replaceDraft] = useState<Data>({});
  useEffect(() => { if (value) replaceDraft(clone(value.data)); }, [value]);
  const setDraft = (data: Data) => { replaceDraft(data); onDraftChange(data); };
  return [draft, setDraft] as const;
}


type FacilityGroup = { id: string; label: string; fields: ReadonlyArray<readonly [string, string]> };

const FACILITY_GROUPS: readonly FacilityGroup[] = [
  { id: "meal", label: "助餐设施", fields: [
    ["老年人助餐服务需求率（%）", "meal.demandRate"],
    ["堂食模式下社区食堂人均配置建筑面积（平方米）", "meal.diningAreaPerPerson"],
    ["堂食模式下社区食堂厨房人均配置建筑面积（平方米）", "meal.kitchenAreaPerPerson"],
    ["堂食模式下社区食堂配餐空间人均配置建筑面积（平方米）", "meal.preparationAreaPerPerson"],
    ["堂食模式下社区食堂用餐空间人均配置建筑面积（平方米）", "meal.diningSpaceAreaPerPerson"],
    ["送餐模式下社区食堂人均配置建筑面积（平方米）", "meal.deliveryAreaPerPerson"],
  ] },
  { id: "elderly", label: "养老设施", fields: [
    ["生活不能完全自理的60-69岁老年人比例（%）", "elderly.disabilityRates.60-69岁"],
    ["生活不能完全自理的70-79岁老年人比例（%）", "elderly.disabilityRates.70-79岁"],
    ["生活不能完全自理的80岁以上老年人比例（%）", "elderly.disabilityRates.80岁以上"],
    ["老年服务站需求率（%）", "elderly.stationDemandRate"],
    ["老年服务站人均配置建筑面积（平方米）", "elderly.stationAreaPerPerson"],
    ["60-69岁老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.60-69岁"],
    ["70-79岁老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.70-79岁"],
    ["80岁以上老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.80岁以上"],
    ["60-69岁老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.60-69岁"],
    ["70-79岁老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.70-79岁"],
    ["80岁以上老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.80岁以上"],
    ["60-69岁老年人交通接送服务需求率（%）", "elderly.transportRates.60-69岁"],
    ["70-79岁老年人交通接送服务需求率（%）", "elderly.transportRates.70-79岁"],
    ["80岁以上老年人交通接送服务需求率（%）", "elderly.transportRates.80岁以上"],
  ] },
  { id: "childcare", label: "托育设施", fields: [
    ["托儿所人均配置建筑面积（平方米）", "childcare.nurseryAreaPerPerson"],
    ["托儿所入托需求率（%）", "childcare.nurseryDemandRate"],
    ["幼儿园人均配置建筑面积（平方米）", "childcare.kindergartenBuildingAreaPerPerson"],
    ["幼儿园人均配置用地面积（平方米）", "childcare.kindergartenLandAreaPerPerson"],
    ["幼儿园人均配置室外活动场地面积（平方米）", "childcare.outdoorAreaPerPerson"],
    ["幼儿园人均配置全园共用活动场地面积（平方米）", "childcare.sharedAreaPerPerson"],
    ["幼儿园入园需求率（%）", "childcare.kindergartenDemandRate"],
    ["幼儿园人均活动室与寝室使用面积（合并建设）（平方米）", "childcare.combinedRoomAreaPerPerson"],
    ["幼儿园人均活动室使用面积（分开设置）（平方米）", "childcare.activityRoomAreaPerPerson"],
    ["幼儿园人均寝室使用面积（分开设置）（平方米）", "childcare.bedroomAreaPerPerson"],
  ] },
  { id: "parking", label: "停车充电设施", fields: [
    ["充电桩寿命（年）", "parking.chargerLifetime"],
    ["充电桩配比（个/户）", "parking.chargersPerHousehold"],
    ["停车位配比（个/户）", "parking.parkingSpacesPerHousehold"],
  ] },
  { id: "activity", label: "公共活动场地", fields: [
    ["人均公共活动场地面积（平方米）", "activity.publicAreaPerCapita"],
    ["人均多功能运动场地面积（平方米）", "activity.sportsAreaPerCapita"],
  ] },
];

function clone(data: Data): Data {
  return JSON.parse(JSON.stringify(data)) as Data;
}

function readPath(data: Data, path: string): unknown {
  let current: unknown = data;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Data)[part];
  }
  return current;
}

function writePath(data: Data, path: string, value: unknown): Data {
  const next = clone(data);
  const parts = path.split(".");
  let current = next;
  for (const part of parts.slice(0, -1)) {
    const child = current[part];
    if (!child || typeof child !== "object" || Array.isArray(child)) current[part] = {};
    current = current[part] as Data;
  }
  current[parts.at(-1) as string] = value;
  return next;
}

function numberValue(value: unknown): string | number {
  return typeof value === "number" || typeof value === "string" ? value : "";
}

function NumberInput({ value, onChange, label }: { value: unknown; onChange: (value: number | null) => void; label: string }) {
  return <input aria-label={label} type="number" step="any" value={numberValue(value)} onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} />;
}

function ParameterHeader({ templateHref, onImport, onSave, readOnly = false }: { templateHref: string; onImport: (file: File) => Promise<void>; onSave: () => void; readOnly?: boolean }) {
  return <div className="parameter-actions"><button type="button" className="secondary-button" onClick={() => void downloadFile(templateHref).catch(error => window.alert(error instanceof Error ? error.message : "下载失败"))}>下载参数模板</button><label className={`secondary-button file-button${readOnly ? " disabled" : ""}`} aria-disabled={readOnly}>导入 Excel<input disabled={readOnly} type="file" accept=".xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void onImport(file); event.currentTarget.value = ""; }} /></label><button className="primary-button" disabled={readOnly} onClick={onSave}>保存参数</button></div>;
}

function cleanSourceNote(value: unknown): string {
  return String(value || "")
    .replace(/(?:根据|初始化自)附件\s*[一二三四五六七八九十\d]+[；，、。]?/g, "")
    .replace(/正式项目应由业务方确认并导入[。]?/g, "")
    .trim();
}

export function PopulationParameterForm({ value, templateHref, onSave, onImport, onDraftChange, readOnly = false }: ParameterFormProps) {
  const [draft, setDraft] = useParameterDraft(value, onDraftChange);
  const [tab, setTab] = useState<"base" | "birth" | "death">("base");
  const [deathYear, setDeathYear] = useState("");
  const [deathMode, setDeathMode] = useState<"yearly" | "uniform">("yearly");
  const [showOther, setShowOther] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmation, setConfirmation] = useState<{ message: string; apply: () => void } | null>(null);
  const birthRates = (draft.birthRates || {}) as Record<string, Data>;
  const regions = Object.keys(birthRates);
  const targetYears = forecastYears(draft.startYear, draft.duration);
  const birthYears = orderedYears(targetYears, regions.flatMap(region=>Object.keys(birthRates[region])), showOther);
  const deathRates = (draft.deathRates || {}) as Record<string, Data>;
  const deathGroups = mortalityGroups(deathRates);
  const deathYears = orderedYears(targetYears, Object.keys(deathRates), showOther);
  const pendingUniform = draft._pendingUniformDeath as Data | undefined;
  const uniformValues = pendingUniform || deathRates[deathYear] || {};
  useEffect(() => { if (pendingUniform) setDeathMode("uniform"); }, [pendingUniform]);
  useEffect(() => { if (!deathYears.includes(deathYear)) setDeathYear(deathYears[0] || ""); }, [deathYear, deathYears]);
  if (!value) return <div className="loading-block"><span className="spinner" />正在加载人口预测参数</div>;
  const notes = (draft.sourceNotes || {}) as Data;
  const missingBirth = targetYears.reduce((n, year)=>n+regions.filter(region=>!validRate(birthRates[region]?.[year])).length, 0);
  const missingDeath = targetYears.reduce((n, year)=>n+deathGroups.filter(group=>!validRate(deathRates[year]?.[group])).length, 0);
  const applyUniform = () => {
    if (!targetYears.length || deathGroups.some(group=>!validRate(uniformValues[group]))) {
      setMessage(`请填写完整的${deathGroups.length}组死亡率（0—1000‰），并设置有效预测范围。`); return;
    }
    setConfirmation({message:`将当前这组死亡率应用到 ${targetYears[0]}—${targetYears.at(-1)} 年？会覆盖这些年度原有的分龄死亡率，其他年度保留。应用后还需保存参数。`, apply:()=>{
    const next = clone(draft);
    const rates = (next.deathRates || {}) as Record<string, Data>;
    for (const year of targetYears) rates[year] = Object.fromEntries(deathGroups.map(group=>[group,uniformValues[group]]));
    next.deathRates = rates;
    delete next._pendingUniformDeath;
    const note = `用户确认统一死亡率：${targetYears[0]}—${targetYears.at(-1)}年使用同一组分龄死亡率。`;
    next.sourceNotes = {...notes, death:[notes.death, note].filter(Boolean).join("\n")};
    setDraft(next);
    setMessage("已应用到全部预测年度，请点击“保存参数”。");
    }});
  };
  const save = () => {
    if (pendingUniform) { setMessage("统一死亡率尚未应用，请先确认应用或取消统一编辑。"); return; }
    if (!targetYears.length || !regions.length || missingBirth || missingDeath) {
      setMessage("当前预测年度的出生率或死亡率尚未完整，请填写空白单元格，或确认沿用最近已填年度值后再保存。"); return;
    }
    setMessage("");
    void onSave({
      ...draft,
      sourceNotes: { ...notes, birth: cleanSourceNote(notes.birth), death: cleanSourceNote(notes.death) },
    });
  };
  return <section className="content-card parameter-editor structured-parameters">
    <div className="parameter-toolbar">
      <div className="parameter-tabs"><button className={tab === "base" ? "active" : ""} onClick={() => setTab("base")}>基础参数</button><button className={tab === "birth" ? "active" : ""} onClick={() => setTab("birth")}>出生率</button><button className={tab === "death" ? "active" : ""} onClick={() => setTab("death")}>死亡率</button></div>
      <ParameterHeader templateHref={templateHref} onImport={onImport} onSave={save} readOnly={readOnly} />
    </div>
    <fieldset className="parameter-readonly-body" disabled={readOnly}>
    <div className="parameter-range-bar">
      <span>{targetYears.length ? `本次预测：${targetYears[0]}—${targetYears.at(-1)} 年，共 ${targetYears.length} 年` : "请填写有效的基准年与预测时长"}</span>
      <label><input type="checkbox" checked={showOther} onChange={e=>setShowOther(e.target.checked)}/>显示其他已保存年度</label>
    </div>
    {(missingBirth > 0 || missingDeath > 0 || !regions.length) && <div className="warning-banner">
      预测范围内待补充：出生率 {missingBirth} 项、死亡率 {missingDeath} 项。{!regions.length && "暂无地区出生率，请导入参数。"}
      <button className="secondary-button" disabled={!targetYears.length || Boolean(pendingUniform)} onClick={()=>{
        setConfirmation({message:"仅补充当前预测年度的缺失项：出生率沿用同地区、死亡率沿用同年龄段最近已填年份的数值。现有有效值（含0）不变；这是一项假设，不是自动获取的真实数据。确认补齐？",apply:()=>{
        setDraft(fillMissingPopulationYears(draft,targetYears,deathGroups));
        setMessage("已按最近年度补齐可用项并记录来源；无参考值的项目仍需手动填写。请核对后保存。");
        }});
      }}>沿用最近年度补齐缺失项</button>
    </div>}
    {message && <p className="parameter-feedback" role="status">{message}</p>}
    {pendingUniform && <p className="warning-banner">有尚未应用的统一死亡率，保存和预测前请先应用，或返回死亡率页取消统一编辑。</p>}
    {tab === "base" && <div className="base-parameter-grid">
      <label><span>人口预测基准年</span><NumberInput label="人口预测基准年" value={draft.startYear} onChange={(next) => setDraft(writePath(draft, "startYear", next))} /></label>
      <label><span>预测时长（年）</span><NumberInput label="预测时长" value={draft.duration} onChange={(next) => setDraft(writePath(draft, "duration", next))} /></label>
      <label className="wide"><span>出生率数据来源</span><textarea value={cleanSourceNote(notes.birth)} onChange={(event) => setDraft(writePath(draft, "sourceNotes.birth", event.target.value))} /></label>
      <label className="wide"><span>死亡率数据来源</span><textarea value={cleanSourceNote(notes.death)} onChange={(event) => setDraft(writePath(draft, "sourceNotes.death", event.target.value))} /></label>
    </div>}
    {tab === "birth" && <><p>单位：‰（每千人）。优先显示本次预测年度；空白表示待填写，不等于0。</p><div className="parameter-table-wrap"><table className="parameter-table matrix"><thead><tr><th>年份</th>{regions.map((region) => <th key={region}>{region}（‰）</th>)}</tr></thead><tbody>{birthYears.map((year) => <tr key={year}><td>{year}{!targetYears.includes(year) && "（参考）"}</td>{regions.map((region) => <td key={region}><NumberInput label={`${region}${year}年出生率`} value={readPath(draft, `birthRates.${region}.${year}`)} onChange={(next) => setDraft(writePath(draft, `birthRates.${region}.${year}`, next))} /></td>)}</tr>)}</tbody></table></div></>}
    {tab === "death" && <>
      <div className="parameter-mode-bar"><label>设置方式<select value={deathMode} onChange={e=>{
        const mode=e.target.value as "yearly" | "uniform";
        const switchMode=()=>{ if (pendingUniform) { const next=clone(draft); delete next._pendingUniformDeath; setDraft(next); } setDeathMode(mode); setMessage(""); };
        if (pendingUniform) setConfirmation({message:"取消尚未应用的统一编辑？原有各年度死亡率不变。",apply:switchMode});
        else switchMode();
      }}><option value="yearly">逐年设置参数</option><option value="uniform">各年使用同一组参数</option></select></label>
      {deathMode==="yearly" ? <label>当前参数年份<select value={deathYear} onChange={e=>setDeathYear(e.target.value)}>{deathYears.map(year=><option key={year} value={year}>{year}年{!targetYears.includes(year) ? "（参考）" : ""}</option>)}</select></label>
        : <><span>以 {deathYear || "当前"} 年为初始参考，填写一组后确认应用。</span><button className="secondary-button" onClick={applyUniform}>确认应用到预测年度</button></>}
      <span>单位：‰</span></div>
      <div className="parameter-table-wrap"><table className="parameter-table"><thead><tr><th>年龄段</th><th>死亡率（‰）</th></tr></thead><tbody>{deathGroups.map(group=><tr key={group}><td>{group}</td><td><NumberInput label={deathMode==="uniform" ? `统一${group}死亡率` : `${deathYear}${group}死亡率`} value={deathMode==="uniform" ? uniformValues[group] : deathRates[deathYear]?.[group]} onChange={next=>{
        if (deathMode==="uniform") setDraft({...draft,_pendingUniformDeath:{...uniformValues,[group]:next}});
        else setDraft(writePath(draft,`deathRates.${deathYear}.${group}`,next));
      }}/></td></tr>)}</tbody></table></div>
    </>}
    {confirmation && <div className="dialog-backdrop"><section className="create-project-dialog" role="alertdialog" aria-modal="true" aria-label="确认参数变更" onKeyDown={e=>{
      if(e.key==="Escape") setConfirmation(null);
      if(e.key==="Tab") { const buttons=e.currentTarget.querySelectorAll<HTMLButtonElement>("button"); const first=buttons[0],last=buttons[buttons.length-1]; if(e.shiftKey && document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first.focus();} }
    }}><h2>确认参数变更</h2><p>{confirmation.message}</p><div className="actions"><button autoFocus className="secondary-button" onClick={()=>setConfirmation(null)}>取消</button><button className="primary-button" onClick={()=>{confirmation.apply();setConfirmation(null);}}>确认应用</button></div></section></div>}
    </fieldset>
  </section>;
}

export function FacilityParameterForm({ value, templateHref, onSave, onImport, onDraftChange, populationParameters, readOnly = false }: ParameterFormProps & { populationParameters: Data }) {
  const [draft, setDraft] = useParameterDraft(value, onDraftChange);
  const [groupId, setGroupId] = useState("meal");
  const [showOtherYears, setShowOtherYears] = useState(false);
  if (!value) return <div className="loading-block"><span className="spinner" />正在加载设施预测参数</div>;
  const group = FACILITY_GROUPS.find((item) => item.id === groupId) || FACILITY_GROUPS[0];
  const missingCount = FACILITY_GROUPS.flatMap((item) => item.fields).filter(([, path]) => readPath(draft, path) === null || readPath(draft, path) === undefined || readPath(draft, path) === "").length;
  const references = (draft.references || {}) as Data;
  const newEnergy = (readPath(draft, "parking.newEnergyVehiclesPerCapita") || {}) as Data;
  const vehicles = (readPath(draft, "parking.vehiclesPerCapita") || {}) as Data;
  const targetYears = forecastYears(populationParameters.startYear, populationParameters.duration);
  const vehicleYears = orderedYears(targetYears, [...Object.keys(newEnergy), ...Object.keys(vehicles)], showOtherYears);
  return <section className="content-card parameter-editor structured-parameters">
    <div className="parameter-toolbar">
      <div className="parameter-tabs facility-tabs">{FACILITY_GROUPS.map((item) => <button className={groupId === item.id ? "active" : ""} key={item.id} onClick={() => setGroupId(item.id)}>{item.label}</button>)}</div>
      <ParameterHeader templateHref={templateHref} onImport={onImport} onSave={() => void onSave(draft)} readOnly={readOnly} />
    </div>
    <fieldset className="parameter-readonly-body" disabled={readOnly}>
    {missingCount > 0 && <div className="warning-banner">还有 {missingCount} 个设施标准未填写；停车充电还需至少填写一个年度的两类机动车人均保有量。补齐后即可运行设施预测。</div>}
    <div className="parameter-table-wrap"><table className="parameter-table facility-parameter-table"><thead><tr><th>参数项</th><th>参数值</th><th>参考来源</th></tr></thead><tbody>{group.fields.map(([label, path]) => {
      const reference = (references[path] || {}) as Data;
      return <tr key={path}><td>{label}</td><td><NumberInput label={label} value={readPath(draft, path)} onChange={(next) => setDraft(writePath(draft, path, next))} /></td><td><input aria-label={`${label}参考来源`} value={String(reference.source || "")} placeholder="填写标准或数据来源" onChange={(event) => setDraft({ ...draft, references: { ...references, [path]: { ...reference, source: event.target.value } } })} /></td></tr>;
    })}</tbody></table></div>
    {groupId === "parking" && <div className="vehicle-section"><div className="subsection-heading"><div><h3>乘用机动车人均保有量</h3><p>年份随人口预测范围联动（含尚未保存的范围修改）。空白年度计算时按已有参考数据线性插值，范围外沿用最近年度；不代表实测数据。</p></div></div><div className="parameter-range-bar"><span>{targetYears.length ? `本次预测：${targetYears[0]}—${targetYears.at(-1)}年` : "请先设置有效的人口预测范围"}</span><label><input type="checkbox" checked={showOtherYears} onChange={e=>setShowOtherYears(e.target.checked)}/>显示其他已保存年度</label></div><div className="parameter-table-wrap"><table className="parameter-table matrix"><thead><tr><th>年份</th><th>新能源乘用机动车（辆/人）</th><th>乘用机动车总量（辆/人）</th><th>参考来源</th></tr></thead><tbody>{vehicleYears.map((year) => <tr key={year}><td>{year}{!targetYears.includes(year) && "（参考）"}</td><td><NumberInput label={`${year}年新能源车人均保有量`} value={newEnergy[year]} onChange={(next) => setDraft(writePath(draft, `parking.newEnergyVehiclesPerCapita.${year}`, next))} /></td><td><NumberInput label={`${year}年机动车人均保有量`} value={vehicles[year]} onChange={(next) => setDraft(writePath(draft, `parking.vehiclesPerCapita.${year}`, next))} /></td><td><input aria-label={`${year}年车辆数据来源`} value={String(readPath(draft, `vehicleSources.${year}`) || "")} placeholder="填写数据来源" onChange={(event) => setDraft(writePath(draft, `vehicleSources.${year}`, event.target.value))} /></td></tr>)}</tbody></table></div></div>}
    </fieldset>
  </section>;
}
