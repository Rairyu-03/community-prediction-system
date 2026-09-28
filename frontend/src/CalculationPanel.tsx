import { useEffect, useState } from "react";
import type { CommunityApi } from "./api";

export type Calculation = {
  runId:number; communityId:number; year:number; kind:string; seed:number; algorithmVersion:string;
  hasAudit:boolean; warning:string; notes:string[]; inputs:Record<string,unknown>[]; rows:Record<string,unknown>[];
  audit:Record<string,unknown>|null; siteAnalysis:Record<string,unknown>; parameters:Record<string,unknown>;
};
function AuditTable({rows}: {rows:Record<string,unknown>[]}) {
  if (!rows.length) return null;
  const keys=[...new Set(rows.flatMap(row=>Object.keys(row)))];
  return <div className="editable-table-scroll"><table className="parameter-table"><thead><tr>{keys.map(key=><th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{keys.map(key=><td key={key}>{row[key]==null ? "—" : typeof row[key]==="object" ? JSON.stringify(row[key]) : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}
export function CalculationPanel({api,runId,communityId,years,onClose}: {api:CommunityApi;runId:number;communityId:number;years:number[];onClose:()=>void}) {
  const [year,setYear]=useState(years[0]);
  const [data,setData]=useState<Calculation|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    let disposed=false;
    if (!year) return;
    void api.getCalculation(runId,communityId,year).then(value=>{if(!disposed){setData(value);setError("");}}).catch(e=>{if(!disposed)setError(String(e.message));});
    return()=>{disposed=true;};
  },[api,runId,communityId,year]);
  const current=data?.year===year ? data : null;
  return <section className="calculation-panel" aria-label="说明">
    <div className="section-header"><div><h2>说明</h2><p>批次 #{runId} · 展示本次预测使用的数据、计算设定与结果。</p></div><button className="secondary-button" onClick={onClose}>收起计算逻辑及说明</button></div>
    <label>预测年份<select value={year} onChange={e=>{setError("");setYear(Number(e.target.value));}}>{years.map(y=><option key={y}>{y}</option>)}</select></label>
    {error ? <p role="alert">{error}</p> : !current ? <p>正在加载计算依据…</p> : <>
      <p>{current.warning}</p><p>算法版本：{current.algorithmVersion}；随机种子：{current.seed}。</p>
      <details open><summary>计算设定与适用范围</summary><ol className="calculation-notes">{current.notes.map((note,i)=><li key={i}>{note}</li>)}</ol></details>
      <h3>公式与本年度结果</h3><AuditTable rows={current.rows}/>
      <details><summary>本批次实际参数及人口输入</summary><AuditTable rows={current.inputs}/></details>
      {current.kind==="population" && current.audit && <><details><summary>分年龄段死亡计算</summary><AuditTable rows={current.audit.deaths as Record<string,unknown>[]}/></details><details><summary>分年龄段迁入迁出计算</summary><AuditTable rows={current.audit.migration as Record<string,unknown>[]}/></details></>}
      {current.kind==="facility" && current.audit && <details><summary>现状设施与闲置空间快照</summary><pre>{JSON.stringify({设施:current.audit.facilities,闲置空间:current.audit.idleSpaces},null,2)}</pre></details>}
      {Object.keys(current.siteAnalysis).length>0 && <details><summary>实际选址分析过程</summary><pre>{JSON.stringify(current.siteAnalysis,null,2)}</pre></details>}
    </>}
  </section>;
}
