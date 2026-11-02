"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useState } from "react";
import { coverage, num, pct, pkr, ratio } from "@/lib/format";
import { SimpleBars } from "./charts";
import { FilterBar } from "./filters";
import { exportHref, useAnalytics } from "./overview";
import { LoadingPage, NeedDataset, Notice, PageHead, Panel, PlatformLabel, Segmented } from "./ui";
import { useWorkspace } from "./workspace";

const GROUPS = [
  { value: "campaign", label: "Campaign" },
  { value: "platform", label: "Platform" },
  { value: "date", label: "Date" },
  { value: "city", label: "City" },
  { value: "age", label: "Age" },
  { value: "gender", label: "Gender" },
  { value: "device", label: "Device" },
] as const;

const COLS = [
  { key: "rows", label: "Rows", fmt: (v: number | null) => num(v) },
  { key: "spend", label: "Spend", fmt: (v: number | null) => pkr(v) },
  { key: "impressions", label: "Impr.", fmt: (v: number | null) => num(v) },
  { key: "clicks", label: "Clicks", fmt: (v: number | null) => num(v) },
  { key: "conversions", label: "Conv.", fmt: (v: number | null) => num(v, 2) },
  { key: "revenue", label: "Revenue", fmt: (v: number | null) => pkr(v) },
  { key: "ctr", label: "CTR", fmt: (v: number | null) => pct(v) },
  { key: "cpc", label: "CPC", fmt: (v: number | null) => pkr(v) },
  { key: "cpa", label: "CPA", fmt: (v: number | null) => pkr(v) },
  { key: "cvr", label: "CVR", fmt: (v: number | null) => pct(v) },
  { key: "roas", label: "ROAS", fmt: (v: number | null) => ratio(v) },
] as const;

type SortKey = "name" | (typeof COLS)[number]["key"];

export function Campaigns() {
  const { dataset, filters, loading: wsLoading } = useWorkspace();
  const [group, setGroup] = useState<string>("campaign");
  const [sort, setSort] = useState<SortKey>("revenue");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [filterKey, setFilterKey] = useState(JSON.stringify(filters));
  if (filterKey !== JSON.stringify(filters)) {
    setFilterKey(JSON.stringify(filters));
    setPage(1);
  }
  const { data, error, loading } = useAnalytics(dataset, filters, {
    group_by: group,
    sort,
    direction,
    page: String(page),
    page_size: String(pageSize),
  });
  if (wsLoading) return <LoadingPage label="Loading workspace" />;
  if (!dataset)
    return (
      <>
        <PageHead eyebrow="Campaign explorer" title="Drill into campaigns" />
        <NeedDataset />
      </>
    );
  const pages = data ? Math.max(1, Math.ceil(data.table_total / data.page_size)) : 1;
  const toggleSort = (key: SortKey) => {
    if (sort === key) setDirection(direction === "desc" ? "asc" : "desc");
    else {
      setSort(key);
      setDirection(key === "name" ? "asc" : "desc");
    }
    setPage(1);
  };
  const sortIcon = (key: SortKey) => (sort === key ? direction === "desc" ? <ArrowDown size={12} /> : <ArrowUp size={12} /> : null);
  const ariaSort = (key: SortKey) => (sort === key ? (direction === "desc" ? "descending" : "ascending") : "none");
  const sortLabel = COLS.find((c) => c.key === sort);
  return (
    <>
      <PageHead
        eyebrow="Campaign explorer"
        title="Campaign & audience drill-down"
        actions={
          <a className="btn sm" href={exportHref(dataset, filters)} download>
            <Download size={15} /> Export current selection (CSV)
          </a>
        }
      >
        Grouping, sorting and paging run on the backend; the browser only receives one page of aggregated rows.
      </PageHead>
      <FilterBar dataset={dataset} />
      <Panel
        title="Group results by"
        actions={
          <Segmented
            label="Group by"
            value={group}
            options={GROUPS.map((g) => ({ value: g.value, label: g.label }))}
            onChange={(g) => {
              setGroup(g);
              setPage(1);
            }}
          />
        }
      >
        {error && <Notice tone="error">{error}</Notice>}
        {!data && loading && <LoadingPage label="Loading table" />}
        {data && (
          <div className="grid" aria-busy={loading} style={{ opacity: loading ? 0.6 : 1 }}>
            {data.table.length === 0 ? (
              <Notice>No groups match the current filters.</Notice>
            ) : (
              <>
                {sortLabel && sort !== "rows" && (
                  <SimpleBars
                    label={`${sortLabel.label} for this page`}
                    data={data.table.filter((r) => r[sort as keyof typeof r] != null).map((r) => ({ name: r.name, value: r[sort as keyof typeof r] as number }))}
                    fmt={(v) => sortLabel.fmt(v)}
                    color="var(--peri)"
                  />
                )}
                <div className="table-wrap">
                  <table className="data">
                    <caption className="sr-only">
                      {data.table_total} groups by {group}, sorted by {sort} {direction}
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col" aria-sort={ariaSort("name")}>
                          <button className="sort-btn" type="button" onClick={() => toggleSort("name")}>
                            {GROUPS.find((g) => g.value === group)?.label} {sortIcon("name")}
                          </button>
                        </th>
                        {COLS.map((c) => (
                          <th key={c.key} scope="col" className="r" aria-sort={ariaSort(c.key)}>
                            <button className="sort-btn" type="button" onClick={() => toggleSort(c.key)}>
                              {c.label} {sortIcon(c.key)}
                            </button>
                          </th>
                        ))}
                        <th scope="col" className="r">
                          Revenue coverage
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.table.map((row) => (
                        <tr key={row.name}>
                          <th scope="row" style={{ fontWeight: 650 }}>
                            {group === "platform" ? <PlatformLabel name={row.name} /> : row.name}
                          </th>
                          {COLS.map((c) => (
                            <td key={c.key} className="r" style={row[c.key] == null ? { color: "var(--text-3)" } : undefined}>
                              {c.fmt(row[c.key])}
                            </td>
                          ))}
                          <td className="r">{coverage(row.coverage.revenue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="btn-row" style={{ justifyContent: "space-between" }}>
                  <span className="faint num">
                    {num(data.table_total)} groups · page {data.page} of {pages}
                  </span>
                  <div className="btn-row">
                    <label className="field" style={{ gridAutoFlow: "column", alignItems: "center" }}>
                      Rows
                      <select
                        className="select"
                        style={{ minHeight: 34, width: 80 }}
                        value={pageSize}
                        onChange={(e) => {
                          setPageSize(Number(e.target.value));
                          setPage(1);
                        }}
                      >
                        {[10, 25, 50, 100].map((n) => (
                          <option key={n}>{n}</option>
                        ))}
                      </select>
                    </label>
                    <button className="btn sm" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">
                      <ChevronLeft size={15} />
                    </button>
                    <button className="btn sm" type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">
                      <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </Panel>
    </>
  );
}
