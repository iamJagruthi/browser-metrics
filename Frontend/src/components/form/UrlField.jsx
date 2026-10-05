export function UrlField({ tag, tagStyle, value, onChange, placeholder }) {
  // "SOURCE" -> "Source"
  const tagText = tag ? tag.charAt(0) + tag.slice(1).toLowerCase() : '';

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm font-semibold ml-1">
        <span className="text-xs font-bold px-2 py-0.5 rounded" style={tagStyle}>
          {tagText}
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