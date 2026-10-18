# Violin Prince — Enhanced Preview

Reviewable candidate at `/upgraded-preview/`. The official root homepage is intentionally unchanged.

## Included
- The corner YouTube dock remains and can collapse to a small music-note button.
- A separate fixed horizontal player bar works on desktop and phones. Both views control the same YouTube player, sharing play/pause, seek and volume.
- YouTube's iframe and API only load after a visitor presses Play; autoplay is not forced.
- WhatsApp/social metadata points to a custom forest-green/champagne-gold share card, with a YouTube thumbnail as a compatibility fallback.
- The artist section uses a narrow, right-aligned crop of the existing Say You Won't Let Go cover artwork.
- Song requests are submitted directly through an AJAX web form rather than opening the visitor's mail app.
- Font preconnect, lazy/async images, reduced-motion support, keyboard focus styles and selected contrast improvements.

## Action needed for the song-request form
The form uses FormSubmit's AJAX endpoint for `baidyaprince69@gmail.com`. The site owner must confirm FormSubmit's first activation email before delivery works. I cannot access that inbox from this workflow, so test submission after activation. The page reports failure if the service does not accept a request.

The receiving address remains visible in the static page's client-side endpoint. No private API key is included. A server-side endpoint or form service with a dashboard offers stronger spam controls and delivery tracking.

## SEO rollout
The preview remains `noindex,follow` and canonical points to the official root. Keep this protection until the official homepage is selected. Then update canonical/share URLs for the chosen official version, submit the sitemap in Google Search Console, and monitor impressions, clicks, CTR and queries.

Preview URL: https://baidyaprince69-web.github.io/violin-prince-website/upgraded-preview/
