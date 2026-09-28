import { NumericInput } from "./NumericInput";
import { NATIONAL_REGIONS } from "./regions";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Community } from "./types";
import { downloadFile } from "./api";

type Row = Record<string, unknown>;
const AGES = ["0-3岁", "4-6岁", "7-12岁", "13-17岁", "18-59岁", "60-69岁", "70-79岁", "80岁以上"];
const FACILITIES: Record<string, string[]> = {
  "助餐设施": ["社区食堂建筑面积（平方米）"],
  "养老设施": ["老年服务站容纳量（人）", "老年服务站建筑面积（平方米）"],
  "托育设施": ["现有托儿所建筑面积（平方米）", "现有托儿所托育人数（人）", "现有幼儿园建筑面积（平方米）", "现有幼儿园用地面积（平方米）", "现有幼儿园托育人数（人）"],
  "停车充电设施": ["停车位数量（个）", "机动车充电桩数量（个）"],
  "公共活动场地": ["公共活动场地面积（平方米）", "多功能运动场地面积（平方米）"],
};
const SPACE_FIELDS = ["闲置空间编号", "待分配建筑面积（平方米）", "待分配用地面积（平方米）", "经度", "纬度"];
const CHARGER_FIELDS = ["机动车充电桩编号", "建设年份", "经度", "纬度"];

function EditableRows({ title, rows, columns, onChange, baseYear, readOnly = false }: {title: string; rows: Row[]; columns: string[]; onChange: (rows: Row[]) => void; baseYear?: number; readOnly?: boolean}) {
  const [selected, setSelected] = useState<number[]>([]);
  const [page, setPage] = useState(0);
  const [newRow, setNewRow] = useState<Row>({});
  const pages = Math.max(1, Math.ceil(rows.length / 30));
  const activePage = Math.min(page, pages - 1);
  const indices = rows.slice(activePage * 30, activePage * 30 + 30).map((_, i) => activePage * 30 + i);
  const cell = (column: string, row: Row, change: (next: Row) => void, id: string) => {
    if (column === "性别") return <select disabled={readOnly} aria-label={`${id}性别`} value={String(row[column] || "未知")} onChange={e => change({...row, [column]:e.target.value})}><option>未知</option><option>男</option><option>女</option></select>;
    if (column === "年龄" && baseYear) return <span>{row["出生年份"] !== undefined && row["出生年份"] !== "" ? baseYear - Number(row["出生年份"]) : String(row["年龄"] ?? "—")}</span>;
    const text = column.includes("编号") || column === "序号" || column === "姓名";
    return <input readOnly={readOnly} aria-label={`${id}${column}`} type={text ? "text" : "number"} step={column.includes("年份") ? 1 : "any"} value={String(row[column] ?? "")} onChange={e => change({...row, [column]:text || e.target.value === "" ? e.target.value : Number(e.target.value)})} />;
  };
  return <section className="editor-rows"><div className="section-header"><div><h3>{title}</h3><p>共 {rows.length} 条；当前选中 {selected.length} 条。{readOnly ? "内置案例，仅供查看。" : "编辑后需点击“保存社区”。"}</p></div><button type="button" className="danger-button" disabled={readOnly || !selected.length} onClick={() => {onChange(rows.filter((_, i) => !selected.includes(i))); setSelected([]);}}>删除选中</button></div>
    <div className="editable-table-scroll"><table className="parameter-table"><thead><tr><th><input disabled={readOnly} type="checkbox" aria-label={`${title}选中本页`} checked={indices.length > 0 && indices.every(i => selected.includes(i))} onChange={e => setSelected(e.target.checked ? [...new Set([...selected,...indices])] : selected.filter(i => !indices.includes(i)))} /></th>{columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>
      {!readOnly && <tr className="new-record"><td><button type="button" className="secondary-button" onClick={() => {onChange([...rows, { ...(columns.includes("序号") ? {"序号":rows.reduce((max,r)=>Math.max(max,Number(r["序号"]) || 0),0) + 1, "性别":"未知"} : {}), ...newRow}]); setNewRow({}); setPage(Math.floor(rows.length / 30));}}>添加</button></td>{columns.map(c => <td key={c}>{cell(c,newRow,setNewRow,"新增")}</td>)}</tr>}
      {indices.map(i => <tr key={i}><td><input disabled={readOnly} type="checkbox" aria-label={`${title}选择第${i+1}条`} checked={selected.includes(i)} onChange={e => setSelected(e.target.checked ? [...selected,i] : selected.filter(x => x !== i))} /></td>{columns.map(c => <td key={c}>{cell(c,rows[i],row => onChange(rows.map((r,j) => j===i ? row:r)),`第${i+1}条`)}</td>)}</tr>)}
    </tbody></table></div><div className="editor-pagination"><button type="button" disabled={activePage===0} onClick={()=>setPage(activePage-1)}>上一页</button><span>{activePage+1} / {pages} 页（每页30条）</span><button type="button" disabled={activePage>=pages-1} onClick={()=>setPage(activePage+1)}>下一页</button></div>
    {rows.some(row => row["原始性别"] !== undefined) && <p className="inline-error">部分导入记录原始性别无效，已保留原值并暂记未知；请核实修正。</p>}
  </section>;
}

export function CommunityEditor({community, regions, baseYear, onSave, onCancel, hasResults = false, results, onDirtyChange, readOnly = false, initialTab = "社区基础信息", exportHref}: {exportHref?:string; readOnly?:boolean; initialTab?:string; community?: Community; regions: string[]; baseYear:number; onSave:(data:Partial<Community>)=>Promise<boolean>; onCancel:()=>void; hasResults?:boolean; results?:ReactNode; onDirtyChange?:(dirty:boolean)=>void}) {
  const [draft,setDraft] = useState<Partial<Community>>(() => community ? structuredClone(community) : {code:"",name:"",region:regions.includes("全国") ? "全国" : regions[0],households:0,average_household_size:2.5, migration_rates:Object.fromEntries(AGES.map(a=>[a,0])),age_counts:{},facilities:{},idle_spaces:[],population_records:[],population_base_year:baseYear});
  const [tab,setTab] = useState(initialTab);
  const [dirty,setDirty] = useState(false);
  useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>()=>onDirtyChange?.(false),[onDirtyChange]);
  const [saving,setSaving] = useState(false);
  const [error,setError] = useState("");
  const update = (data:Partial<Community>) => {setDraft(current=>({...current,...data}));setDirty(true);};
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[dirty]);
  const records=draft.population_records || [];
  const existingSummary = community && !(community.population_records || []).length && Object.values(community.age_counts).some(v=>v>0);
  const total=records.length || Object.values(draft.age_counts || {}).reduce((a,b)=>a+b,0);
  const setRecords=(rows:Row[])=>update({population_records:rows,age_counts:{},population_base_year:draft.population_base_year || baseYear});
  const [useSummary,setUseSummary]=useState(Boolean(existingSummary));
  const changeTab=(next:string)=>{if(next==="预测结果" && !hasResults){setError("该社区尚未执行成功的预测，请先完成人口或设施预测。");return;}setError("");setTab(next);};
  return <div className="community-editor content-card"><div className="section-header"><div><h2>{community ? `${community.code} · ${community.name}` : "新建社区"}</h2>{dirty && <span className="unsaved-badge">有未保存修改</span>}</div><button type="button" className="secondary-button" onClick={()=>{if(!dirty || window.confirm("放弃尚未保存的社区修改？"))onCancel();}}>返回</button></div>
    {exportHref && <p>{dirty ? "请先保存社区，导出仅包含已保存数据。" : <button type="button" className="secondary-button" onClick={() => void downloadFile(exportHref).catch(err => setError(err instanceof Error ? err.message : "下载失败"))}>下载本社区完整数据</button>}</p>}
    <div className="parameter-tabs">{["社区基础信息","社区设施信息","社区闲置空间信息","社区人口列表",...(community ? ["预测结果"]:[])].map(t=><button type="button" key={t} className={tab===t ? "active":""} title={t==="预测结果" && !hasResults ? "尚未预测，点击查看提示" : t} onClick={()=>changeTab(t)}>{t}</button>)}</div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {tab==="预测结果" ? results : <form onSubmit={async e=>{e.preventDefault();if(saving || readOnly)return;setSaving(true);setError("");try{const data={...draft,households:draft.households ?? Math.round(total/Number(draft.average_household_size || 2.5))};if(await onSave(data)){setDirty(false);if(!community)onCancel();}else setError("保存未完成，请检查页面错误提示。");}catch(err){setError(err instanceof Error?err.message:"保存失败");}finally{setSaving(false);}}}><fieldset disabled={saving} className="editor-fieldset">
      {tab==="社区基础信息" && <><div className="community-field-grid">
        <label>社区编号<input readOnly={readOnly} required maxLength={80} value={draft.code || ""} onChange={e=>update({code:e.target.value})}/></label>
        <label>社区名称<input readOnly={readOnly} required maxLength={160} value={draft.name || ""} onChange={e=>update({name:e.target.value})}/></label>
        <label>预测参数参考地区<select disabled={readOnly} value={draft.region || ""} onChange={e=>update({region:e.target.value})}>{[...new Set([...NATIONAL_REGIONS,...regions,...(draft.region ? [draft.region]:[])])].map(r=><option key={r}>{r}</option>)}</select></label>
        <label>总户数（户）<NumericInput readOnly={readOnly} min={0} step={1} value={draft.households} onNumberChange={value=>update({households:value})}/></label>
        <label>预测户均人数（人/户）<NumericInput readOnly={readOnly} required min={0.1} step="any" value={draft.average_household_size} onNumberChange={value=>update({average_household_size:value})}/></label>
        <label>人口数据基准年<NumericInput readOnly={readOnly} required min={1900} max={9900} value={draft.population_base_year} onNumberChange={value=>update({population_base_year:value})}/></label>
      </div><h3>各年龄段年均净迁入率（‰）</h3><div className="community-age-grid">{AGES.map(a=><label key={a}>{a}<NumericInput readOnly={readOnly} aria-label={`${a}净迁入率`} min={-1000} max={1000} step="any" value={draft.migration_rates?.[a]} onNumberChange={value=>{const rates={...draft.migration_rates}; if(value===undefined)delete rates[a];else rates[a]=value;update({migration_rates:rates});}}/></label>)}</div></>}
      {tab==="社区设施信息" && <>{Object.entries(FACILITIES).map(([category,fields])=><section className="community-form-section" key={category}><h3>{category}{category==="公共活动场地" ? "（预测扩展项）":""}</h3><div className="community-field-grid">{fields.map(field=><label key={field}>{field}<input readOnly={readOnly} type="number" min={0} step="any" value={String((draft.facilities?.[category] as Row)?.[field] ?? "")} onChange={e=>update({facilities:{...draft.facilities,[category]:{...(draft.facilities?.[category] as Row || {}),[field]:e.target.value==="" ? null:Number(e.target.value)}}})}/></label>)}</div></section>)}<EditableRows readOnly={readOnly} key={tab} title="机动车充电桩列表" rows={(draft.facilities?.["机动车充电桩列表"] as Row[]) || []} columns={CHARGER_FIELDS} onChange={rows=>update({facilities:{...draft.facilities,"机动车充电桩列表":rows}})}/></>}
      {tab==="社区闲置空间信息" && <EditableRows readOnly={readOnly} key={tab} title="社区闲置空间" rows={draft.idle_spaces || []} columns={SPACE_FIELDS} onChange={rows=>update({idle_spaces:rows})}/>}
      {tab==="社区人口列表" && <>{useSummary ? <><p>旧版本只保存了年龄汇总，不能还原真实性别或出生年份。可重新导入原 Excel 恢复原始人口列表，或确认替换后手动录入。</p><div className="community-age-grid">{Object.keys(community?.age_counts || draft.age_counts || {}).map(age=><label key={age}>{age}{/^\d+$/.test(age)?"岁":""}<NumericInput readOnly={readOnly} min={0} step={1} value={draft.age_counts?.[age]} onNumberChange={value=>{const counts={...draft.age_counts};if(value===undefined)delete counts[age];else counts[age]=value;update({age_counts:counts});}}/></label>)}</div><button type="button" disabled={readOnly} className="secondary-button" onClick={()=>{if(window.confirm("将清空旧人口汇总，改为逐人录入；保存前可返回放弃。")){setUseSummary(false);setRecords([]);}}}>改为逐人录入</button></> : <EditableRows readOnly={readOnly} key={tab} title="社区人口列表" rows={records} columns={["序号","性别","出生年份","年龄"]} baseYear={draft.population_base_year || baseYear} onChange={setRecords}/>}</>}
      <div className="community-form-actions"><span>预测结果只读；保存修改不会覆盖历史预测，需重新预测生成新批次。</span><button className="primary-button" type="submit" hidden={readOnly} disabled={saving}>{saving?"保存中…":community?"保存社区":"确认创建"}</button></div>
    </fieldset></form>}
  </div>;
}
