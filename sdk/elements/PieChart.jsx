// Inline styles throughout, deliberately: Chainlit serves a prebuilt CSS
// bundle, so utility classes this file used would silently do nothing.
//
// A pie draws parts of a whole, and a whole leaks: a withheld slice could be
// read straight off the gap it leaves. So the slices are shares of the
// RELEASED values only, and the caption says how many levels are withheld.
export default function PieChart() {
  const groups = props.groups || [];
  const fills = ["#0d6459", "#6fb8a8", "#a8cfc6", "#cfe3dd", "#e3ded4",
                 "#8a7f6e"];

  const card = {
    border: "1px solid rgba(128,128,128,0.25)",
    borderRadius: "9px",
    padding: "18px 20px",
    fontFamily: "system-ui, -apple-system, sans-serif",
  };
  const head = {
    display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "16px",
  };
  const title = { fontSize: "13.5px", fontWeight: 600 };
  const caption = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px", opacity: 0.6,
  };
  const groupLabel = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "11.5px", opacity: 0.75, marginBottom: "8px",
  };
  const legendRow = {
    display: "flex", alignItems: "center", gap: "7px", marginBottom: "3px",
  };
  const legendText = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "11px", opacity: 0.85,
  };

  // One circle per group: slice paths computed from the released values.
  function slices(bars) {
    const total = bars.reduce((s, b) => s + (b.value || 0), 0);
    if (!total) return { paths: [], total: 0 };
    const R = 56, C = 60;
    let angle = -Math.PI / 2;
    const paths = bars.map((b, i) => {
      const share = (b.value || 0) / total;
      const start = angle;
      angle += share * 2 * Math.PI;
      const large = share > 0.5 ? 1 : 0;
      const x1 = C + R * Math.cos(start), y1 = C + R * Math.sin(start);
      const x2 = C + R * Math.cos(angle), y2 = C + R * Math.sin(angle);
      const d = share >= 0.999
        ? "M " + C + " " + (C - R) +
          " A " + R + " " + R + " 0 1 1 " + (C - 0.01) + " " + (C - R) + " Z"
        : "M " + C + " " + C + " L " + x1 + " " + y1 +
          " A " + R + " " + R + " 0 " + large + " 1 " + x2 + " " + y2 + " Z";
      return { d: d, fill: fills[i % fills.length], share: share };
    });
    return { paths: paths, total: total };
  }

  return (
    <div style={card}>
      <div style={head}>
        <span style={title}>{props.title}</span>
        <span style={caption}>{props.caption}</span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "22px" }}>
        {groups.map((g, gi) => {
          const pie = slices(g.bars || []);
          return (
            <div key={gi} style={{ display: "flex", gap: "14px",
                                   alignItems: "center" }}>
              <svg width="120" height="120" viewBox="0 0 120 120">
                {pie.paths.map((s, i) => (
                  <path key={i} d={s.d} fill={s.fill} />
                ))}
              </svg>
              <div>
                {g.label ? <div style={groupLabel}>{g.label}</div> : null}
                {(g.bars || []).map((b, i) => {
                  const pct = pie.total
                    ? Math.round((1000 * (b.value || 0)) / pie.total) / 10
                    : 0;
                  return (
                    <div key={i} style={legendRow}>
                      <span style={{ width: "10px", height: "10px",
                                     borderRadius: "2px", flex: "none",
                                     background: fills[i % fills.length] }} />
                      <span style={legendText}>
                        {b.who} — {b.label} ({pct}%)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ ...caption, marginTop: "14px", display: "block" }}>
        shares of released values only
        {props.held
          ? " — " + props.held + " level(s) below the suppression threshold, withheld"
          : ""}
      </div>
    </div>
  );
}
