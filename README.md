# Violin Prince — Artist Website

A responsive static portfolio for **Violin Prince (Prince Baidya)**, built with plain HTML, CSS and JavaScript. No framework or build tool is required.

## Homepage

The homepage uses a warm, cinematic palette of near-black brown, ember, copper, gold and ivory, with Cormorant Garamond and DM Sans typography.

- Full-bleed cinematic hero using the artist's own performance photograph.
- Featured violin covers linking to their dedicated pages and YouTube performances.
- “Find all my music” section linking to YouTube, SoundCloud and BandLab, paired with the artist's recording-studio photograph.
- Audience snapshot with YouTube channel figures and the artist-reported 12-month SoundCloud play total, explicitly distinguished from unique listeners.
- Five music-collection links that open the dedicated Covers Library with its category filters.
- Song-request form connected to the configured Formspree endpoint.
- Lightweight hero and scroll-reveal animations, with reduced-motion support.
- Floating YouTube IFrame player with play/pause, volume and minimize controls.
- Google Analytics 4, Google Search Console verification, canonical URL, Open Graph metadata and Person structured data.

The Covers Library, production guide and existing individual cover pages remain separate pages in the repository.

## Homepage photography

The homepage images are stored in the repository:

- `assets/violin-prince-cinematic-hero.jpg` — cinematic performance photograph.
- `assets/violin-prince-studio-photo.jpg` — recording-studio photograph featuring the Maono AU-PM461TR microphone.

## Publish with GitHub Pages

1. Open this repository on GitHub.
2. Go to **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select branch `main` and folder `/(root)`.
5. The expected project URL is:
   `https://baidyaprince69-web.github.io/violin-prince-website/`
6. After deployment, test navigation, the floating player, cover links and song-request form on desktop and mobile.

The canonical URL, Open Graph URL, structured-data URL, robots sitemap line and sitemap URL use that GitHub Pages address. If a custom domain is added later, update all of those URLs.

## Song-request form

The homepage form submits to the configured Formspree endpoint from the browser. The endpoint identifier is visible in the public client-side HTML. After a deployment or form-provider change, submit a controlled test request and confirm that it reaches the intended inbox before relying on the form. Do not place private API keys or credentials in client-side files.

## Search engine setup

After the website is published:

1. Add the exact published URL as a property in [Google Search Console](https://search.google.com/search-console/about).
2. Verify ownership using the verification method already configured in the homepage.
3. Submit the sitemap: `https://baidyaprince69-web.github.io/violin-prince-website/sitemap.xml`.
4. Add the site in [Bing Webmaster Tools](https://www.bing.com/webmasters/about) and submit the same sitemap.
5. Confirm that the live homepage and sitemap load over HTTPS.

These steps help search engines discover the site, but indexing and ranking are not guaranteed.

## Local preview

Double-click `index.html` to preview the static site. For a more realistic local preview, run a simple static server from this directory.

## Video and copyright note

The site uses YouTube thumbnails and the official YouTube IFrame Player API; it does not store or redistribute copyrighted song audio files. Cover-song rights and availability are controlled by the relevant rights holders and platforms. If a video is removed or its URL changes, update the relevant page and thumbnail reference.
