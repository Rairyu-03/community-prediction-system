export type ParameterData = Record<string, unknown>;
export const MORTALITY_GROUPS = ["0-4岁", "5-9岁", "10-14岁", "15-19岁", "20-24岁", "25-29岁", "30-34岁", "35-39岁", "40-44岁", "45-49岁", "50-54岁", "55-59岁", "60-64岁", "65-69岁", "70-74岁", "75-79岁", "80-84岁", "85-89岁", "90-94岁", "95-99岁", "100岁及以上"];

export function populationParameterIssues(data: ParameterData): string[] {
  if (data._pendingUniformDeath) return ["统一死亡率尚未应用，请先确认应用或取消统一编辑"];
  const years = forecastYears(data.startYear, data.duration);
  if (!years.length) return ["请设置有效的人口预测基准年和时长"];
  const birth = (data.birthRates || {}) as Record<string, Record<string, unknown>>;
  const death = (data.deathRates || {}) as Record<string, Record<string, unknown>>;
  if (!Object.keys(birth).length) return ["请配置出生率参考地区"];
  const missing = years.filter(year=>Object.values(birth).some(row=>!validRate(row[year])) || MORTALITY_GROUPS.some(group=>!validRate(death[year]?.[group])));
  return missing.length ? [`${missing.join("、")}年人口参数不完整，请在人口参数页填写或确认补齐后再预测`] : [];
}

export function forecastYears(start: unknown, duration: unknown): string[] {
  const first = Number(start), count = Number(duration);
  if (!Number.isInteger(first) || first < 1900 || first > 9900 || !Number.isInteger(count) || count < 1 || count > 100 || first + count > 9999) return [];
  return Array.from({ length: count }, (_, i) => String(first + i + 1));
}

export function orderedYears(target: string[], existing: string[], showOther: boolean): string[] {
  return [...target, ...(showOther ? [...new Set(existing)].filter(y => !target.includes(y)).sort((a,b)=>Number(a)-Number(b)) : [])];
}

export function validRate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1000;
}

/** Copy assumptions only when the caller has obtained confirmation. Preserve real zeroes. */
export function fillMissingPopulationYears(data: ParameterData, years: string[], groups: readonly string[]): ParameterData {
  const result = structuredClone(data);
  const birth = (result.birthRates || {}) as Record<string, Record<string, unknown>>;
  const death = (result.deathRates || {}) as Record<string, Record<string, unknown>>;
  const nearest = (series: Record<string, unknown>, year: string) => Object.keys(series)
    .filter(y => /^\d+$/.test(y) && validRate(series[y]))
    .sort((a,b)=>Math.abs(Number(a)-Number(year))-Math.abs(Number(b)-Number(year)) || Number(a)-Number(b))[0];
  for (const series of Object.values(birth)) {
    const original = { ...series };
    for (const year of years) if (!validRate(series[year])) {
      const source = nearest(original, year);
      if (source) series[year] = original[source];
    }
  }
  for (const group of groups) {
    const original = Object.fromEntries(Object.entries(death).map(([year, row])=>[year,row[group]]));
    for (const year of years) if (!validRate(death[year]?.[group])) {
      const source = nearest(original, year);
      if (source) (death[year] ||= {})[group] = original[source];
    }
  }
  result.birthRates = birth;
  result.deathRates = death;
  const notes = { ...((result.sourceNotes || {}) as ParameterData) };
  const note = `用户确认的沿用假设：${years[0]}—${years.at(-1)}年缺失值取同地区或同年龄段最近已填年度值，不是新增实测数据。`;
  for (const kind of ["birth", "death"]) if (!String(notes[kind] || "").includes(note)) notes[kind] = [notes[kind], note].filter(Boolean).join("\n");
  result.sourceNotes = notes;
  return result;
}
