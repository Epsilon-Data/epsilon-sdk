// Inline styles throughout, deliberately. Chainlit serves a prebuilt CSS
// bundle, so Tailwind utilities this file uses but its own components do not
// are simply absent — the layout silently collapses to stacked text.
export default function BarChart() {
  const groups = props.groups || [];
  const fills = ["#0d6459", "#6fb8a8", "#a8cfc6", "#cfe3dd"];

  let top = 0;
  for (const g of groups) for (const b of g.bars) top = Math.max(top, b.value);

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
    fontSize: "11.5px", opacity: 0.75, marginBottom: "6px",
  };
  const row = {
    display: "flex", alignItems: "center", gap: "9px", marginBottom: "4px",
  };
  const who = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px", opacity: 0.7,
    flex: "0 0 96px", overflow: "hidden", textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  };
  const track = {
    flex: 1, height: "15px", borderRadius: "3px",
    background: "rgba(128,128,128,0.18)", position: "relative",
  };
  const value = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "11.5px", flex: "0 0 74px", textAlign: "right",
  };

  return (
    <div style={card}>
      <div style={head}>
        <span style={title}>{props.title}</span>
        <span style={caption}>{props.caption}</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
        {groups.map((g, gi) => (
          <div key={gi}>
            {g.label ? <div style={groupLabel}>{g.label}</div> : null}
            {g.bars.map((b, i) => (
              <div key={i} style={row}>
                <span style={who}>{b.who}</span>
                <div style={track}>
                  <div
                    style={{
                      position: "absolute", left: 0, top: 0, bottom: 0,
                      width: top ? Math.max(2, (100 * b.value) / top) + "%" : 0,
                      borderRadius: "3px",
                      background: fills[i % fills.length],
                    }}
                  />
                </div>
                <span style={value}>{b.label}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {props.held ? (
        <div style={{ ...caption, marginTop: "14px", display: "block" }}>
          {props.held} level(s) below the suppression threshold — withheld
        </div>
      ) : null}
    </div>
  );
}
