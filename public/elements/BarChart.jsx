export default function BarChart() {
  const groups = props.groups || [];
  const palette = ["#0d6459", "#6fb8a8", "#a8cfc6", "#cfe3dd"];

  let top = 0;
  for (const g of groups) for (const b of g.bars) top = Math.max(top, b.value);

  return (
    <div className="rounded-lg border p-5 bg-background">
      <div className="flex items-baseline gap-3 mb-4">
        <span className="text-sm font-semibold">{props.title}</span>
        <span className="text-xs font-mono text-muted-foreground">
          {props.caption}
        </span>
      </div>

      <div className="flex flex-col gap-4">
        {groups.map((g, gi) => (
          <div key={gi}>
            {g.label ? (
              <div className="text-xs font-mono text-muted-foreground mb-1.5">
                {g.label}
              </div>
            ) : null}
            <div className="flex flex-col gap-1">
              {g.bars.map((b, i) => (
                <div key={i} className="flex items-center gap-2.5">
                  <span className="text-xs font-mono text-muted-foreground w-28 shrink-0 truncate">
                    {b.who}
                  </span>
                  <div className="flex-1 h-4 rounded-sm bg-muted relative">
                    <div
                      className="absolute inset-y-0 left-0 rounded-sm"
                      style={{
                        width: top ? Math.max(2, (100 * b.value) / top) + "%" : 0,
                        background: palette[i % palette.length],
                      }}
                    />
                  </div>
                  <span className="text-xs font-mono w-20 text-right shrink-0">
                    {b.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {props.held ? (
        <div className="text-xs text-muted-foreground mt-4">
          {props.held} level(s) below the suppression threshold — withheld
        </div>
      ) : null}
    </div>
  );
}
