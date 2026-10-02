import { Link, useLocation } from "react-router-dom"

// Unknown /admin/* addresses land here, inside the app's layout. They used
// to fall through to the catch-all, which sent people to the login page --
// a dead sidebar link looked like being logged out.
const NOT_BUILT = []

export default function NotFound() {
  const { pathname } = useLocation()
  const notBuilt = NOT_BUILT.some((p) => pathname.startsWith(p))
  return (
    <div className="mx-auto max-w-xl px-6 py-20 text-left">
      <p className="text-sm font-semibold uppercase tracking-wide text-cogentix-orange-700">
        {notBuilt ? "Not built yet" : "Page not found"}
      </p>
      <h1 className="mt-2 text-3xl font-bold text-cogentix-navy">
        {notBuilt ? "This section is on the way" : "We couldn't find that page"}
      </h1>
      <p className="mt-4 text-base text-cogentix-navy-700">
        {notBuilt
          ? "This part of the platform has not been built yet."
          : <>There is no page at <code className="font-mono text-sm">{pathname}</code>. It may have moved.</>}
      </p>
      <div className="mt-8 flex gap-3">
        <Link to="/admin/dashboard"
              className="rounded-lg bg-cogentix-orange px-5 py-2.5 text-[0.95rem] font-semibold text-white no-underline hover:bg-cogentix-orange-600">
          Go to the dashboard
        </Link>
        <button type="button" onClick={() => window.history.back()}
                className="rounded-lg border-2 border-cogentix-orange bg-transparent px-5 py-2 text-[0.95rem] font-semibold text-cogentix-orange-700 hover:bg-cogentix-orange-50">
          Go back
        </button>
      </div>
    </div>
  )
}
