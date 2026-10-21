import QtQuick
import QtMultimedia

// One Multiview tile: a channel on a player of its own, at the quality its
// size needs (the streamer's ?h=, or an IPTV stream's track at or under it),
// joining a live stream at its edge and a scheduled channel mid-show, as the
// TV does (guide.airing). Only the tile with the sound has an audio output;
// the others have none. stop() stops it for good: nothing it started (a
// retry, a reload, the next show) runs after.
Item {
  id: tile

  required property var guide
  property string url: ""            // the channel, by its address in the list
  property int quality: 720          // 1080, 720, 480 or 360
  property bool sound: false
  property var onAir: null           // what it plays: guide.airing()'s answer
  property string reception: "off"   // off, locked, tuning, on, lost
  property bool started: false
  property bool retried: false       // an IPTV stream that dropped is tried once more
  property bool paused: false        // held paused: loading again (a new quality) doesn't play it
  readonly property alias player: player
  // Really playing (for keep-awake and the screen saver): on, moving, not stalled
  readonly property bool playing: reception === "on" && player.playbackState === MediaPlayer.PlayingState
                                  && player.mediaStatus !== MediaPlayer.StalledMedia

  function channelRow() { return tile.guide.indexOf(tile.url) }

  function streamUrl() {
    if (!tile.onAir) return ""
    if (tile.onAir.iptv) return tile.onAir.stream
    if (!tile.guide.streamBase || !tile.onAir.id) return ""
    return tile.guide.streamBase + "/play/" + tile.onAir.id + ".m3u8" + (tile.quality < 1080 ? "?h=" + tile.quality : "")
  }

  // Plays the channel's show at `at` (now, if not given)
  function tune(at, retrying) {
    var r = tile.channelRow()
    var ch = tile.guide.channels[r]
    if (!retrying) tile.retried = false
    if (r < 0 || !ch) { tile.halt("lost"); return "no such channel" }
    if (tile.guide.channelLock.blocks(ch)) { tile.halt("locked"); return "locked" }
    if (!tile.guide.airs(ch)) { tile.halt("lost"); return "not ready" }
    var t = at || Date.now() / 1000
    if (ch.kind !== "iptv" && !ch.live) {
      tile.guide.rollDay()
      ch = tile.guide.channels[r]
    }
    tile.onAir = tile.guide.airing(ch, t)
    tile.reception = "tuning"
    tile.started = false
    watchdog.restart()
    tile.load()
    return "ok"
  }

  // The stream for what's on: once the streamer is up (it's asked for, and
  // its address coming calls this again)
  function load() {
    if (tile.reception !== "tuning") return
    var s = tile.streamUrl()
    if (!s) { tile.guide.startStreamer(); return }
    if (player.source.toString() === s) {
      player.source = ""
      reload.restart()
    } else {
      player.source = s
    }
  }

  function halt(why) {
    watchdog.stop()
    reload.stop()
    player.stop()
    player.source = ""
    tile.started = false
    tile.reception = why
  }

  function stop() { tile.halt("off") }

  // An IPTV stream with several sizes: the biggest at or under the tile's
  // quality, else the smallest
  function pickTrack() {
    var best = -1, bestHeight = -1, small = -1, smallHeight = 1e9
    for (var i = 0; i < player.videoTracks.length; i++) {
      var size = player.videoTracks[i].value(MediaMetaData.Resolution)
      var h = size ? size.height : 0
      if (h <= tile.quality && h > bestHeight) { bestHeight = h; best = i }
      if (h > 0 && h < smallHeight) { smallHeight = h; small = i }
    }
    if (best < 0) best = small
    if (best >= 0 && best !== player.activeVideoTrack) player.activeVideoTrack = best
  }

  onPausedChanged: {
    if (tile.reception !== "tuning" && tile.reception !== "on") return
    if (tile.paused) player.pause()
    else if (tile.started) player.play()
  }

  // A new size: an IPTV stream changes track; a YouTube one tunes again at
  // the new quality, where it is now
  onQualityChanged: {
    if (tile.reception !== "tuning" && tile.reception !== "on") return
    if (tile.onAir && tile.onAir.iptv) tile.pickTrack()
    else tile.tune()
  }

  VideoOutput {
    id: video
    anchors.fill: parent
  }

  // the system's sound output now, followed as the TV's sound does
  MediaDevices { id: audioDevices }

  AudioOutput {
    id: audio
    device: audioDevices.defaultAudioOutput
    muted: !!tile.guide.muted
  }

  MediaPlayer {
    id: player
    videoOutput: video
    audioOutput: tile.sound ? audio : null
    onMediaStatusChanged: {
      if (tile.reception !== "tuning" && tile.reception !== "on") return
      if (mediaStatus === MediaPlayer.LoadedMedia && tile.reception === "tuning") {
        // join it where it is now, not where it was when tuning began
        var into = Date.now() / 1000 - tile.onAir.start
        if (!tile.onAir.live && into > 3) player.position = Math.floor(into * 1000)
        if (tile.onAir.iptv) tile.pickTrack()
        tile.started = true
        if (tile.paused) { tile.reception = "on"; watchdog.stop() }   // loaded and held: paused, not a failed tune
        else player.play()
      } else if (mediaStatus === MediaPlayer.BufferedMedia && tile.reception === "tuning" && tile.started) {
        tile.reception = "on"
        watchdog.stop()
      } else if (mediaStatus === MediaPlayer.EndOfMedia && tile.reception === "on") {
        if (tile.onAir.iptv) {
          if (tile.retried) tile.halt("lost")
          else { tile.retried = true; tile.tune(0, true) }
        } else if (tile.onAir.live) {
          var r = tile.channelRow()
          if (r >= 0) tile.guide.liveEnded(r)
          if (tile.tune() !== "ok" && tile.reception === "tuning") tile.halt("lost")
        } else {
          tile.tune(Math.max(Date.now() / 1000, tile.onAir.end + 1))
        }
      } else if (mediaStatus === MediaPlayer.InvalidMedia) {
        tile.halt("lost")
      }
    }
    // buffered can lag well behind the picture: playback moving counts too
    onPositionChanged: {
      if (tile.reception === "tuning" && tile.started && playbackState === MediaPlayer.PlayingState
          && (mediaStatus === MediaPlayer.BufferingMedia || mediaStatus === MediaPlayer.BufferedMedia)) {
        tile.reception = "on"
        watchdog.stop()
      }
    }
  }

  // The streamer's address came: a tile waiting for it loads now
  Connections {
    target: tile.guide
    ignoreUnknownSignals: true
    function onStreamBaseChanged() { if (tile.reception === "tuning" && !player.source.toString()) tile.load() }
  }

  // Swapping in the same stream again needs a moment between
  Timer {
    id: reload
    interval: 50
    onTriggered: if (tile.reception === "tuning") player.source = tile.streamUrl()
  }

  // A channel that hasn't started in this long isn't going to
  Timer {
    id: watchdog
    interval: 20000
    onTriggered: if (tile.reception === "tuning") tile.halt("lost")
  }
}
