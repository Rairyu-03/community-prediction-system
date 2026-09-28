// SQLite stores UTC timestamps without retaining the offset. Older API responses
// may still lack it; never interpret those UTC values as local wall-clock time.
export function formatTime(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "时间无效" : date.toLocaleString("zh-CN", { hour12: false });
}
