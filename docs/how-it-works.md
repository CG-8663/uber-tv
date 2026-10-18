# How it works

How channels become a schedule, where listings come from, and the known limits.

## How it works

- Listings come from `yt-dlp --flat-playlist -J` (the newest 40 videos per
  channel; no API key). Videos under 5 minutes or over 4 hours, and
  members-only or private ones, are left out.
- The schedule starts at a fixed moment (2026-01-01 UTC) and repeats each
  channel's lineup forever.
- Video plays in Qt's own player (QtMultimedia). YouTube's direct streams
  keep audio and video apart, which it can't play, so `bin/om-pg-streamer`
  (a small Python server on 127.0.0.1, using yt-dlp's library) hands it an
  HLS playlist instead: one H.264 variant up to 1080p plus the original audio.
  Unlike YouTube's own playlist, it is seekable, which is how tuning in joins
  a video partway through. When a video ends, the channel moves on to the
  next one.

## Listings and the daily lineup

- **Listings are saved** in `~/.cache/om-pg/listings.json`, so the guide opens
  with every channel at once, even after a restart.
- **They refresh** when you open the guide and the last refresh was more than
  3 hours ago (in the background; the guide shows what it has meanwhile),
  for any channel that has none yet, and when you press **R**. Four channels
  are fetched at a time; a channel whose refresh fails keeps its listing.
- **The lineup is daily.** Each channel's schedule is planned once per TV day,
  4 AM to 4 AM, from its listing, so new uploads don't make a channel jump
  mid-show; they join the next day's lineup. Press **R** to re-plan now.
  For lineups that follow every refresh instead, choose *Latest* in Settings →
  Live TV → Lineups.
- **Live streams** aren't part of the lineup: they're checked when the guide
  opens (unless they were in the last 15 minutes), on every refresh, and every
  15 minutes while it's open.

## Known limits

- It runs inside `omarchy-shell`, so a crash in the video decoder would take
  the bar down with it. None seen so far.
- Full screen, the guide covers everything, the bar too, and takes the
  keyboard; in a window (**W**) it's an ordinary window.
- Tuning takes a couple of seconds the first time a video is played.
- `keepLoaded` means code changes need `omarchy restart shell`.
