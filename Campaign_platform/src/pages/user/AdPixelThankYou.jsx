import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { buildApiUrl } from "../../config";
import { firePixel } from "../../utils/adPixels";
import "./AdPixelThankYou.css";

// Thank-you page for respondents who came from ads (Meta now; Google/TikTok later).
// Same message for everyone; the backend decides, once per respondent, whether a pixel fires.
export default function AdPixelThankYou() {
  const [searchParams] = useSearchParams();
  const rid = searchParams.get("rid") || "";
  const requestedRef = useRef(false); // StrictMode runs effects twice in dev

  useEffect(() => {
    document.title = "Thank you | Cogentix Research";
    if (!rid || requestedRef.current) return;
    requestedRef.current = true;

    fetch(buildApiUrl(`/api/adpixel?rid=${encodeURIComponent(rid)}`), { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => firePixel(data?.pixel))
      .catch(() => {}); // the respondent never sees a pixel failure
  }, [rid]);

  return (
    <main className="adpx-page">
      <section className="adpx-card">
        <div className="adpx-brand">Cogentix Research</div>
        <div className="adpx-tick" aria-hidden="true">&#10003;</div>
        <h1 className="adpx-title">Thank you! Your response has been recorded.</h1>
        <p className="adpx-text">You can now close this page.</p>
      </section>
    </main>
  );
}
