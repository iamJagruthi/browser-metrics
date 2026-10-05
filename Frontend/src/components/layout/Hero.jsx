export function Hero() {
  return (
    <header className="text-center mt-14 mb-12 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-700">
      <h1
        className="dv-font-display text-5xl sm:text-7xl font-extrabold tracking-tight mb-5"
        style={{ color: 'var(--text)' }}
      >
        Wiz Match
      </h1>

      <p
        className="text-base sm:text-lg max-w-xl mx-auto leading-relaxed"
        style={{ color: 'var(--text-muted)' }}
      >
        Automated dashboard comparison and validation.
      </p>
    </header>
  );
}