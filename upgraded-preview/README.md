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
The form submits through the provided Formspree endpoint (`https://formspree.io/f/xjygzejd`) using an AJAX request. The form ID is public by design; the recipient's Gmail address is not embedded in the page. The hidden `_gotcha` field is included as a Formspree honeypot for spam filtering. No Formspree API key or password is placed in client-side JavaScript.

The website's request flow has been connected to this endpoint, but no real submission was sent from this workflow, so delivery and notification email are not independently verified. The owner should submit one harmless test request from the preview and check the Formspree dashboard and `princebaidya386@gmail.com`. If the service asks to verify the notification recipient or activate the form, complete that action in the Formspree dashboard.

## SEO rollout
The preview remains `noindex,follow` and canonical points to the official root. Keep this protection until the official homepage is selected. Then update canonical/share URLs for the chosen official version, submit the sitemap in Google Search Console, and monitor impressions, clicks, CTR and queries.

Preview URL: https://baidyaprince69-web.github.io/violin-prince-website/upgraded-preview/
