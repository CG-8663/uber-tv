# Showcase

An example app with code (API 4) that shows every block Uber TV
draws, offline: it asks for no network at all, and its pictures come with it.
An app that changes things on a site says so in `app.json`'s `netWrite`
(API 4, `PROTOCOL.md`): this one changes nothing anywhere, so it asks for
none, and its review says only "It doesn't connect to anything."

- a featured row (`layout: hero`), with backdrops and title logos;
- rows of each picture shape: posters, wide pictures (with progress and a
  badge), squares, logos (a LIVE badge) and people in circles;
- a grid and a list (with `meta` and the watched mark);
- details pages in both styles: cinematic (backdrop, logo, chips, buttons,
  cast and more like this) and classic;
- search, buttons that answer with a message, and a Home row;
- API 4's richer blocks: a ticker row (news), a table (standings, each with
  a chart of its form; a team's details page has one too) and an article
  page (Reading), which the arrows scroll.

Check it, try it, pack it:

```bash
P=~/.config/omarchy/plugins/marcho78.om-pg
python3 $P/bin/om-pg-apps check $P/apps/sdk/examples/showcase
python3 $P/bin/om-pg-apps try $P/apps/sdk/examples/showcase --call home --call 'details:{"item":"title:1"}'
python3 $P/bin/om-pg-apps pack $P/apps/sdk/examples/showcase ~/showcase.tar.gz
```

To see it in the guide, install it in Developer mode (Settings → Apps →
Install an unsigned app), as any app from a file; its tile shows a small page. The
pictures are flat shapes made for it (no one's artwork).
