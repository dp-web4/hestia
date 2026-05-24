interface ToolHistogramProps {
  data: [string, number][];
}

export function ToolHistogram({ data }: ToolHistogramProps) {
  if (data.length === 0) return null;

  const max = Math.max(...data.map(([, count]) => count));

  return (
    <div className="tool-histogram">
      {data.slice(0, 10).map(([tool, count]) => (
        <div key={tool} className="histogram-row">
          <span className="histogram-label">{tool}</span>
          <div className="histogram-track">
            <div
              className="histogram-fill"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
          <span className="histogram-count">{count}</span>
        </div>
      ))}
    </div>
  );
}
