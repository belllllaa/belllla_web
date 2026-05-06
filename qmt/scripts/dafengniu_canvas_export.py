from pathlib import Path
import pandas as pd


CSV_PATH = Path(r"qmt/实盘策略/dafengniu_all_combo_compare_filtered.csv")
CANVAS_PATH = Path(
    r"C:\Users\Dustin.hou\.cursor\projects\c-Users-Dustin-hou-belllla-web\canvases\dafengniu-grid-analysis.canvas.tsx"
)


def fnum(v):
    s = str(v).strip()
    return float(s) if s else 0.0


def inum(v):
    s = str(v).strip()
    return int(float(s)) if s else 0


def main():
    df = pd.read_csv(CSV_PATH).fillna("")

    rows = []
    for _, r in df.iterrows():
        rule = str(r["策略"]).replace("\\", "\\\\").replace('"', '\\"')
        rows.append(
            '  { rule: "%s", n: %d, win: %.6f, pl: %.6f, avg: %.6f, linear: %.6f, nav: %.6f, unsold: %d }'
            % (
                rule,
                inum(r["样本"]),
                fnum(r["胜率"]),
                fnum(r["盈亏比"]),
                fnum(r["单笔平均收益"]),
                fnum(r["总收益_线性"]),
                fnum(r["净值_顺序复利"]),
                inum(r["未成交数"]),
            )
        )

    arr = ",\n".join(rows)
    content = f"""import {{ Divider, Grid, H1, H2, Stack, Stat, Table, Text }} from "cursor/canvas";

type Row = {{
  rule: string;
  n: number;
  win: number;
  pl: number;
  avg: number;
  linear: number;
  nav: number;
  unsold: number;
}};

const rows: Row[] = [
{arr}
];

const pct = (v: number) => `${{(v * 100).toFixed(2)}}%`;
const num = (v: number) => v.toFixed(3);

export default function DafengniuGridAnalysis() {{
  const byAvg = [...rows].sort((a, b) => b.avg - a.avg);
  const byWin = [...rows].sort((a, b) => b.win - a.win);
  const baseline = rows.find((r) => r.rule.includes("基准_")) || rows[0];
  const tableRows = byAvg.map((r) => [r.rule, String(r.n), pct(r.win), num(r.pl), pct(r.avg), pct(r.linear), num(r.nav), String(r.unsold)]);
  return (
    <Stack gap={{20}}>
      <H1>大风牛多维卖出组合对比（可成交口径）</H1>
      <Text tone="secondary">过滤：D0一字板与低流动性样本（|D0开-D0收|≤0.10）剔除；另外剔除你指定黑名单代码；卖出日若跌停封死则顺延到下一可成交收盘。</Text>
      <Grid columns={{2}} gap={{16}}>
        <Stat value={{String(rows.length)}} label="总测试组合数（全部保留）" />
        <Stat value={{String(baseline.n)}} label={{"样本数（过滤后） | 基准=" + baseline.rule}} />
        <Stat value={{pct(byAvg[0].avg)}} label={{"最高单笔平均收益：" + byAvg[0].rule}} />
        <Stat value={{pct(byWin[0].win)}} label={{"最高胜率：" + byWin[0].rule}} />
      </Grid>
      <Divider />
      <H2>完整对比表（按单笔平均收益降序）</H2>
      <Table headers={{["组合", "样本", "胜率", "盈亏比", "单笔平均收益", "总收益(线性)", "净值(顺序复利)", "未成交数"]}} rows={{tableRows}} />
    </Stack>
  );
}}
"""
    CANVAS_PATH.write_text(content, encoding="utf-8")
    print("canvas_written", CANVAS_PATH)


if __name__ == "__main__":
    main()

