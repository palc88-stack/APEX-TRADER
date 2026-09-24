</footer>
    </main>
  );
}

function ServiceRow({ title, value }) {
  const known = typeof value === "boolean";
  const label = value ? "متصل" : known ? "غير متصل" : "غير معروف";

  return (
    <div className="service-row">
      <i className={`dot ${value ? "ok" : known ? "bad" : "unknown"}`} />
      <span>{title}</span>
      <b>{label}</b>
    </div>
  );
}
