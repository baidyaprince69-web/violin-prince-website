# Violin Prince — Artist Website

A lightweight, responsive portfolio for **Violin Prince (Prince Baidya)**, built with plain HTML, CSS and JavaScript. No framework, build tools or server are required.

## What's included

- Cinematic forest-green, champagne-gold and ivory design
- Responsive mobile navigation
- Curated video gallery linking to verified videos from the Violin Prince YouTube channel
- Category filters for Bengali, Bollywood, Rabindra Sangeet and English covers
- Mood-based song request shortcuts
- Song-request form that prepares an email draft in the visitor's email app
- SEO title, description, Open Graph metadata and Person structured data
- `robots.txt` and an initial `sitemap.xml`
- Accessibility basics including keyboard-friendly controls, labels and reduced-motion support

## Publish with GitHub Pages

1. Open this repository on GitHub.
2. Go to **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select branch `main` and folder `/(root)`, then click **Save**.
5. Wait for GitHub Pages to publish the site. The expected project URL is:
   `https://baidyaprince69-web.github.io/violin-prince-website/`
6. Open that URL and test the navigation, video links and song request form on desktop and mobile.

The canonical URL, Open Graph URL, structured-data URL, robots sitemap line and sitemap URL currently use that expected GitHub Pages address. If you later use a custom domain, update all of those URLs to the final HTTPS domain.

## Song-request form: important note

This is a static website, so it does not store requests in a database or silently send email. On submit, it opens the visitor's default email app with a prepared message. The visitor must add your preferred email address in the **To** field, review the message, and send it. This means no email address has been guessed or exposed in the public source.

If you want one-click delivery to a fixed inbox later, choose an email form provider or a server-side form endpoint, and configure it securely. Do not place private API keys in client-side JavaScript.

## Search engine setup

After the website is published:

1. Add the exact published URL as a property in [Google Search Console](https://search.google.com/search-console/about).
2. Verify ownership using a method offered by Search Console.
3. Submit the sitemap: `https://baidyaprince69-web.github.io/violin-prince-website/sitemap.xml`.
4. Add the site in [Bing Webmaster Tools](https://www.bing.com/webmasters/about) and submit the same sitemap.
5. Check that the live homepage loads over HTTPS and that the sitemap is accessible.

These steps help search engines discover the site, but indexing and ranking are not guaranteed and can take time.

## Local preview

Double-click `index.html` to preview it in a browser. For a more realistic local preview, run a simple static server from this directory, or use a lightweight editor with a live-preview extension.

## Video and copyright note

The gallery embeds no copyrighted audio files; each thumbnail links to the corresponding YouTube video. Cover-song rights and availability are controlled by the relevant rights holders and platforms. If any video is removed or its URL changes, update its link and thumbnail in `index.html`.
