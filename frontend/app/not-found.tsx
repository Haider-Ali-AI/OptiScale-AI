import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <h2>That page is not part of SignalSpend.</h2>
      <p>The link may be from an older version. Every current screen is in the navigation.</p>
      <Link className="btn primary" href="/">
        Go to welcome
      </Link>
    </div>
  );
}
