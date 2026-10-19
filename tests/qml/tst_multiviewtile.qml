import QtQuick
import QtTest
import "../../ui"

// A Multiview tile (ui/MultiviewTile.qml) against a stand-in guide: it asks
// the streamer for its quality (?h=, none at 1080), follows a new quality,
// plays IPTV streams as they are, waits for the streamer when it isn't up
// yet, refuses a locked channel, and stop() stops it for good: no reload or
// retry after. Only the tile with the sound has an audio output.
Item {
  id: top
  width: 640
  height: 360

  Component {
    id: guideKind
    QtObject {
      property var channels: [
        { url: "https://www.youtube.com/@sky", name: "Sky News", state: "ready", items: [{ id: "aaaaaaaaaaa" }], live: { id: "skylive0001", title: "Sky News Live" } },
        { url: "https://iptv.example/one.m3u8", name: "One", kind: "iptv", state: "ready", items: [], live: { id: "", title: "One" } },
        { url: "https://www.youtube.com/@kurz", name: "Kurz", state: "ready", items: [{ id: "bbbbbbbbbbb", duration: 600 }] }
      ]
      property string streamBase: "http://127.0.0.1:9/secret"
      property bool muted: false
      property var locked: ({})
      property int streamerAsked: 0
      property var channelLock: QtObject {
        function blocks(ch) { return !!ch && !!top.lockedUrls[ch.url] }
      }
      function indexOf(url) { for (var i = 0; i < channels.length; i++) if (channels[i].url === url) return i; return -1 }
      function airs(ch) { return !!ch && (ch.state === "ready" || !!ch.live) }
      function rollDay() { return "same day" }
      function airing(ch, t) {
        if (ch.kind === "iptv") return { id: "", stream: ch.url, title: ch.live.title, start: t, end: t + 21600, live: true, iptv: true }
        if (ch.live) return { id: ch.live.id, title: ch.live.title, start: t, end: t + 21600, live: true }
        return { id: ch.items[0].id, title: "a video", start: t - 120, end: t + 480 }
      }
      function startStreamer() { streamerAsked++ }
      function liveEnded(r) {}
    }
  }

  property var lockedUrls: ({})

  Component {
    id: tileKind
    MultiviewTile {}
  }

  TestCase {
    name: "MultiviewTile"
    when: windowShown

    function make(url, quality) {
      var g = createTemporaryObject(guideKind, top)
      var t = createTemporaryObject(tileKind, top, { guide: g, url: url, quality: quality, width: 320, height: 180 })
      return { g: g, t: t }
    }

    function init() { top.lockedUrls = ({}) }

    function test_asks_the_streamer_for_its_quality() {
      var x = make("https://www.youtube.com/@sky", 480)
      compare(x.t.tune(), "ok")
      compare(x.t.reception, "tuning")
      compare(x.t.player.source.toString(), "http://127.0.0.1:9/secret/play/skylive0001.m3u8?h=480")
    }

    function test_1080_asks_for_no_height() {
      var x = make("https://www.youtube.com/@kurz", 1080)
      x.t.tune()
      compare(x.t.player.source.toString(), "http://127.0.0.1:9/secret/play/bbbbbbbbbbb.m3u8")
    }

    function test_a_new_quality_tunes_again() {
      var x = make("https://www.youtube.com/@sky", 720)
      x.t.tune()
      x.t.quality = 360
      compare(x.t.player.source.toString(), "http://127.0.0.1:9/secret/play/skylive0001.m3u8?h=360")
    }

    function test_iptv_plays_its_stream() {
      var x = make("https://iptv.example/one.m3u8", 480)
      x.t.tune()
      compare(x.t.player.source.toString(), "https://iptv.example/one.m3u8")
    }

    function test_waits_for_the_streamer() {
      var x = make("https://www.youtube.com/@sky", 720)
      x.g.streamBase = ""
      compare(x.t.tune(), "ok")
      compare(x.g.streamerAsked, 1, "the streamer is asked for")
      compare(x.t.player.source.toString(), "", "nothing to load yet")
      x.g.streamBase = "http://127.0.0.1:9/later"
      compare(x.t.player.source.toString(), "http://127.0.0.1:9/later/play/skylive0001.m3u8?h=720", "it loads once the streamer says where it is")
    }

    function test_a_locked_channel_doesnt_play() {
      top.lockedUrls = { "https://www.youtube.com/@sky": true }
      var x = make("https://www.youtube.com/@sky", 720)
      compare(x.t.tune(), "locked")
      compare(x.t.reception, "locked")
      compare(x.t.player.source.toString(), "")
    }

    function test_an_unknown_channel_is_lost() {
      var x = make("https://www.youtube.com/@nobody", 720)
      compare(x.t.tune(), "no such channel")
      compare(x.t.reception, "lost")
    }

    function test_stop_is_for_good() {
      var x = make("https://www.youtube.com/@sky", 720)
      x.t.tune()
      x.t.stop()
      compare(x.t.reception, "off")
      compare(x.t.player.source.toString(), "")
      x.g.streamBase = "http://127.0.0.1:9/again"
      x.t.quality = 360
      wait(200)
      compare(x.t.player.source.toString(), "", "a new streamer address or quality doesn't start a stopped tile")
      compare(x.t.reception, "off")
    }

    function test_only_the_sound_tile_has_audio() {
      var x = make("https://www.youtube.com/@sky", 720)
      verify(x.t.player.audioOutput === null, "no audio output without the sound")
      x.t.sound = true
      verify(x.t.player.audioOutput !== null, "the sound tile has one")
      x.t.sound = false
      verify(x.t.player.audioOutput === null, "and gives it up")
    }
  }
}
