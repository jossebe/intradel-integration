# Refreshing the session cookie in one click

The Intradel login form is protected by a reCAPTCHA that the site verifies
server-side, so an automated login/password request is always rejected. A session
cookie captured from a browser that is already logged in is the only usable
credential.

You still log in on the Intradel website yourself, in your own browser. Only the
resulting session is handed over to Home Assistant.

## Why the browser has to do it

Home Assistant cannot fetch the cookie itself:

- the site sends `X-Frame-Options: SAMEORIGIN`, so it cannot be embedded in a
  Home Assistant page at all;
- and even if it could, the same-origin policy forbids reading another domain's
  cookies from JavaScript. That rule is what stops any website from stealing your
  sessions, so there is no way around it.

So the page hands the cookie over itself, which a bookmarklet does in one click.

## Setting it up

Call the `intradel.show_bookmarklet` service (Developer tools → Actions). A
notification appears with a ready-to-use bookmark, already pointing at your own
Home Assistant. Drag it to your bookmarks bar, or create a bookmark with it as
the URL.

Then: log in at <https://www.intradel.be/particulier/>, check that your data is
shown, and click the bookmark.

Home Assistant validates the cookie against the site before storing it, so a
stale one is refused rather than saved.

## What it does, and does not, expose

The bookmark posts to a **webhook**, not to the REST API. That means:

- **no access token** sits in your bookmarks — the earlier version of this
  document required a long-lived token, which was a password in plain text;
- **no CORS configuration**: a POST of plain text is a "simple request", so the
  browser sends it without a preflight and `configuration.yaml` needs no
  `cors_allowed_origins` entry;
- the webhook is **local-only**, so it cannot be reached from the internet;
- the only thing it can do is replace the Intradel session cookie.

## Doing it by hand instead

1. Log in at <https://www.intradel.be/particulier/>.
2. Press `F12`, open the **Network** tab, reload with `F5`.
3. Click the `data.php` request and find **Cookie** under **Request headers**.
4. Copy its value into the integration's `Session cookie` field.

**Keep the cookie's name**: paste `PHPSESSID=abc123`, not `abc123` on its own. A
cookie is a `name=value` pair, so a bare value sends no session and the site
answers as if the credentials were wrong. (The integration now repairs this for
you, but the full value is what the site actually expects.)

## How often will you need this?

Rarely. The cookie carries no expiry of its own: it dies when the server garbage
collects an inactive PHP session. The integration pings the site every 15 minutes
(`keepalive_interval`, set it to 0 to disable) precisely so the session stays
alive. You should only need this after a long Home Assistant outage, or if
Intradel invalidates the session on its side.
