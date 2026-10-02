// Ad-platform pixel loaders for the /adpixel thank-you page.
// The backend (GET /api/adpixel) decides whether a pixel fires; these only load it.
// Adding a platform = enable it in backend/services/ad_tracking.py + add a loader here.

function loadMetaPixel({ pixel_id, survey_id, event_id }) {
  if (!/^\d{5,20}$/.test(String(pixel_id))) return;

  /* Meta Pixel base code */
  !function(f,b,e,v,n,t,s)
  {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
  n.callMethod.apply(n,arguments):n.queue.push(arguments)};
  if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
  n.queue=[];t=b.createElement(e);t.async=!0;
  t.src=v;s=b.getElementsByTagName(e)[0];
  s.parentNode.insertBefore(t,s)}(window, document,'script',
  'https://connect.facebook.net/en_US/fbevents.js');

  // Values go in as function arguments, never into script text, so no injection.
  window.fbq("init", String(pixel_id));
  window.fbq("track", "PageView");
  window.fbq("trackCustom", "SurveyComplete", { survey_id: String(survey_id) }, { eventID: String(event_id) });
}

const PIXEL_LOADERS = {
  meta: loadMetaPixel,
  // google_ads: loadGoogleAdsTag,
  // tiktok: loadTikTokPixel,
};

export function firePixel(pixel) {
  const loader = pixel && PIXEL_LOADERS[pixel.platform];
  if (loader) loader(pixel);
}
