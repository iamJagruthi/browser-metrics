export function UrlField({ tag, tagStyle, value, onChange, placeholder }) {
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm font-semibold ml-1">
        <span className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded" style={tagStyle}>
          {tag}
        </span>
        Dashboard URL
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="dv-input w-full px-4 py-3 rounded-xl text-sm transition-all duration-200"
      />
    </div>
  );
}
