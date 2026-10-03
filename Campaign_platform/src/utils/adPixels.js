// Ad-platform pixel loaders.
//  - Landing page (/takesurvey) for an ad click: base pixel + PageView (GET /api/adpixel/landing)
//  - Thank-you page (/adpixel): + SurveyComplete, only when GET /api/adpixel says so
// The backend decides; these only load what it returns.
// Adding a platform = enable it in backend/services/ad_tracking.py + add a loader here.

function initMetaPixel(pixelId) {
  if (!/^\d{5,20}$/.test(String(pixelId))) return false;

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
  window.fbq("init", String(pixelId));
  window.fbq("track", "PageView");
  return true;
}

const PIXEL_LOADERS = {
  meta: {
    landing: ({ pixel_id }) => initMetaPixel(pixel_id),
    complete: ({ pixel_id, survey_id, event_id }) => {
      if (!initMetaPixel(pixel_id)) return;
      window.fbq("trackCustom", "SurveyComplete", { survey_id: String(survey_id) }, { eventID: String(event_id) });
    },
  },
  // google_ads: { landing: ..., complete: ... },
  // tiktok: { landing: ..., complete: ... },
};

// Thank-you page: SurveyComplete (backend already checked + stamped the fire).
export function firePixel(pixel) {
  const loader = pixel && PIXEL_LOADERS[pixel.platform];
  if (loader) loader.complete(pixel);
}

// Landing page: PageView for ad clicks only.
export function fireLandingPixel(pixel) {
  const loader = pixel && PIXEL_LOADERS[pixel.platform];
  if (loader) loader.landing(pixel);
}
