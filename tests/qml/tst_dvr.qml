import QtQuick
import QtTest
import "../../ui"
import "../../Look.js" as Look
import "../../Dvr.js" as Dvr

// Recordings drawn for real (offscreen) over a pretend guide in Retro's
// colors: the banner's REC badge over the clock; a recording's choices on
// the banner drawn as the record choice element, the note under one (what
// to know before Record is pressed), and dimmed when it can't start, the
// other choices as before; a recording's card with its state word (none
// for Done) and, while it records, how far it is to its stop time; a
// recording's details with its state, why it stopped, and its choices as
// rows in the record choice element, the one under the cursor focused.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root
  width: 1280
  height: 720

  readonly property var retro: ({ text: "#f2f4ff", textDim: "#9fb0f0", accent: "#ffd23f", timeline: "#ff4d4d", cell: "#1b3591", cellBorder: "#3b5bd1", channelCell: "#0f2470", selected: "#ffd23f", selectedText: "#141414", header: "#ffd23f", headerText: "#141414", band: "#030a2b", bandText: "#ffd23f", infoPanel: "#40000000", preview: "#000000", alert: "#ff4d4d", bgTop: "#071447", bgBottom: "#030a2b", ltBg: "#eb081447", ltBorder: "#3b5bd1", ltNumber: "#ffd23f", ltChannel: "#9fb0f0", ltTitle: "#f2f4ff", ltProgress: "#ffd23f", ltTrack: "#1b3591", ltClock: "#f2f4ff", ltTime: "#ffd23f", cardBackdrop: "#d1000000", cardName: "#ffd23f", cardStatus: "#9fb0f0", cardFrame: "#3b5bd1", boxBg: "#071447", boxBorder: "#ffd23f", scrim: "#bf030a2b", keyFace: "#e4e9ff", keyText: "#0b1550", keyEdge: "#46559a", miniBar: "#eb030a2b" })
  readonly property var look: Look.resolve({}, {}, root.retro, { body: "Sans", display: "Sans", mono: "Monospace" }, {})

  function card(id, state, extra) {
    var c = { id: "rec:" + id, kind: "recording", title: "Show " + id, sub: "News 24", poster: "", shape: "wide", recState: state, recProgress: 0, rec: { id: id } }
    for (var k in extra || {}) c[k] = extra[k]
    return c
  }

  QtObject {
    id: guide
    property real u: 16
    readonly property var colors: root.retro
    readonly property var look: root.look
    readonly property var layout: Look.effectiveLayout({}, {})
    readonly property color ink: colors.text
    readonly property color dimInk: colors.textDim
    property var areaImages: ({})
    property real now: 0
    property bool watching: false
    property string screen: "library"
    property var libDetail: null
    property var libDetailRec: null
    property var libDetailRecCard: null
    property var recActions: []
    property int libEpisode: 0
    property var acted: []
    function clock(t) { return "9:00" }
    function showTitle(t) { return t }
    function dayTime(t) { return "Tomorrow, 9:00" }
    // as DVR.qml's reasonOf: a conflict's others (ids) named as the lock is now
    function recReason(rec) { return Dvr.reasonOf(rec, rec.state === "conflict" ? (rec.others || []).map(function(id) { return { q: "Quiz", f: "Film" }[id] || "a recording" }) : null) }
    function posterFor(entry) { return "" }
    function libProgress(id) { return 0.4 }
    function libFinished(id) { return false }
    function inLibraryList(id) { return false }
    function libResumeAt(id) { return 0 }
    function recAct(i) { guide.acted.push(i) }
  }

  LowerThird {
    id: banner
    width: 1280
    height: 720
    look: root.look
    unit: 16
    channel: "News 24"
    title: "Evening News"
    clock: "8:42 PM"
    recording: "● REC until 9:00"
    options: [{ key: "multiview", label: "Multiview", icon: "apps" },
              { key: "record", label: "Record", rec: true, note: "Uses a 2nd stream from this provider" },
              { key: "mini", label: "Mini player", icon: "window" }]
    optionFocus: 1
  }

  CardRows {
    id: rows
    guide: guide
    width: 1280
    height: 400
    rows: [{ key: "rec-now", title: "Recording now", shape: "thumb",
             cards: [root.card("a", "Recording", { recProgress: 0.5 }), root.card("b", "Failed"), root.card("c", "Done")] }]
  }

  CardRows {
    id: upcoming
    guide: guide
    y: 400
    width: 1280
    height: 300
    rows: [{ key: "rec-upcoming", title: "Upcoming", shape: "thumb", cards: [root.card("s", "Scheduled"), root.card("k", "Conflict"), root.card("m", "Missed")] }]
  }

  DetailBox { id: details; guide: guide; width: 1280; height: 720 }

  // pause and rewind's words on the tuning card
  ChannelIdent { id: ident; width: 640; height: 360; up: true; name: "News 24"; look: root.look; unit: 16 }

  // a choice's row, too narrow for its note in half of it
  MenuRow { id: recordRow; guide: guide; y: 700; width: 700; element: "recordChoice"; icon: "record"; label: "Record"; value: "Conflict: too many recordings at this time" }
  MenuRow { id: plainRow; guide: guide; y: 700; width: 700; label: "Save recordings to"; value: "Conflict: too many recordings at this time" }

  TestCase {
    name: "Dvr"
    when: windowShown

    function under(item, test, out) {
      out = out || []
      if (test(item)) out.push(item)
      var kids = item.children || []
      for (var i = 0; i < kids.length; i++) under(kids[i], test, out)
      return out
    }
    function shownText(item, text) {
      return under(item, function(it) { return it.text === text && it.visible && (function() { for (var p = it; p; p = p.parent) if (!p.visible) return false; return true })() })
    }
    function boxOf(label) {
      for (var p = label.parent; p; p = p.parent) if (p.s !== undefined && p.opacity !== undefined && p.modelData) return p
      return null
    }

    function test_the_pause_chip() {
      banner.timeshift = "Live"
      banner.behindLive = false
      wait(0)
      var chip = shownText(banner, "Live")[0]
      verify(chip, "Live, on the banner")
      compare(chip.s, root.look.liveChip, "as the chip element")
      banner.timeshift = "2:15 behind live"
      banner.behindLive = true
      wait(0)
      chip = shownText(banner, "2:15 behind live")[0]
      verify(chip, "how far behind, as approved")
      compare(chip.s, root.look["liveChip:behind"], "in its behind state")
      verify(root.look["liveChip:behind"].fill !== root.look.liveChip.fill, "which looks different from Live")
      banner.timeshift = ""
      wait(0)
      compare(shownText(banner, "2:15 behind live").length, 0, "none while it's off")
    }

    function test_the_tuning_card_while_it_fills_or_stalls() {
      ident.status = "filling"
      wait(0)
      compare(shownText(ident, "Starting pause and rewind…").length, 1)
      ident.status = "stalled"
      wait(0)
      compare(shownText(ident, "Waiting for the channel…").length, 1)
      ident.status = "tuning"
      wait(0)
      compare(shownText(ident, "Tuning…").length, 1, "tuning as before")
    }

    function test_the_banner_says_its_recording() {
      compare(shownText(banner, "● REC until 9:00").length, 1, "the REC badge, over the clock")
      banner.recording = ""
      compare(shownText(banner, "● REC until 9:00").length, 0, "none while nothing records")
      banner.recording = "● REC until 9:00"
    }

    function test_the_record_choice_and_its_note() {
      var label = shownText(banner, "Record")[0]
      verify(label, "Record among the choices")
      var box = boxOf(label)
      compare(box.el, "recordChoice", "drawn as the record choice element")
      compare(box.st, root.look["recordChoice:focused"], "focused, as that element's focused state")
      compare(shownText(banner, "Uses a 2nd stream from this provider").length, 1, "the note under it, before it's pressed")
      var note = shownText(banner, "Uses a 2nd stream from this provider")[0]
      compare(String(note.color), String(root.look["recordChoice:focused"].text.color), "on the picked choice, in its own text color (reads on its fill)")
      verify(note.opacity < 1, "a little dimmer than its label")
      banner.optionFocus = 0
      wait(0)
      compare(String(note.color), String(root.look.recordNote.text.color), "on a choice not picked, the note's own color")
      compare(note.opacity, 1)
      banner.optionFocus = 1
      compare(boxOf(shownText(banner, "Mini player")[0]).el, "menuRow", "the other choices as before")
      compare(box.opacity, 1)
      banner.options = [{ key: "record", label: "Record", rec: true, note: "Too many recordings right now", unavailable: true }]
      wait(0)
      compare(boxOf(shownText(banner, "Record")[0]).opacity, 0.55, "one that can't start, dimmed")
    }

    function test_a_long_note_wraps_on_the_banner() {
      var long = "Can't save to " + "A Very Long Drive Name ".repeat(16)
      banner.options = [{ key: "record", label: "Record", rec: true, note: long, unavailable: true },
                        { key: "mini", label: "Mini player", icon: "window" }]
      wait(0)
      var note = shownText(banner, long)[0]
      verify(note, "the note, under its choice")
      var box = boxOf(note)
      verify(box.width <= banner.noteMax + banner.unit * 2.2 + 0.5, "the choice no wider than a note may be")
      verify(note.lineCount > 1, "the note wrapped onto more lines, not cut")
      var top = note.mapToItem(box, 0, 0).y, bottom = note.mapToItem(box, 0, note.height).y
      verify(top >= 0 && bottom <= box.height + 0.5, "inside its choice: the row as tall as it needs")
      var mini = boxOf(shownText(banner, "Mini player")[0])
      compare(mini.height, box.height, "the choices all one height")
      banner.options = [{ key: "multiview", label: "Multiview", icon: "apps" },
                        { key: "record", label: "Record", rec: true, note: "Uses a 2nd stream from this provider" },
                        { key: "mini", label: "Mini player", icon: "window" }]
    }

    function test_the_two_stream_warning() {
      banner.options = []
      banner.note = "Watching and recording from this provider: 2 streams"
      wait(0)
      var label = shownText(banner, banner.note)[0]
      verify(label, "above the banner while its choices aren't up")
      compare(label.s, root.look.recordWarning, "as the warning element")
      banner.options = [{ key: "multiview", label: "Multiview" }]
      wait(0)
      compare(shownText(banner, banner.note).length, 0, "the choices take its place")
      banner.note = ""
    }

    function test_a_recordings_card() {
      wait(50)
      compare(shownText(rows, "● Recording").length, 1, "recording: its state word, with a dot")
      compare(shownText(rows, "Failed").length, 1, "failed: said on its card")
      compare(shownText(rows, "Done").length, 0, "done: no word")
      var bars = under(rows, function(it) { return it.rb !== undefined && it.visible })
      compare(bars.length, 1, "how far to its stop, on the one recording")
      var frames = under(rows, function(it) { return it.s === root.look["recordingCard:current"] })
      compare(frames.length, 1, "the card under the cursor, as the recording card element's current state")
    }

    function test_upcoming_cards() {
      wait(50)
      var word = shownText(upcoming, "Scheduled")[0]
      verify(word, "a scheduled one says so")
      compare(word.s, root.look["recordingState:scheduled"], "in the state element's scheduled look")
      compare(shownText(upcoming, "Conflict")[0].s, root.look["recordingState:attention"], "a conflict needs you")
      compare(shownText(upcoming, "Missed")[0].s, root.look["recordingState:attention"], "missed too")
      var frames = under(upcoming, function(it) { return it.s === root.look["upcomingRecording:current"] })
      compare(frames.length, 1, "the card under the cursor, as the upcoming card element's current state")
    }

    function test_a_conflicts_details() {
      guide.libDetailRec = { id: "k", kind: "iptv", state: "conflict", reason: "conflict", others: ["q", "f"], start: 100, end: 2000,
                             show: { start: 160, end: 1880 }, channel: { name: "News 24" } }
      guide.recActions = [{ key: "cancel", label: "Cancel recording" }]
      guide.libEpisode = 0
      guide.libDetail = root.card("k", "Conflict")
      wait(50)
      compare(shownText(details, "Conflict · Tomorrow, 9:00 – 9:00").length, 1, "its state and when")
      compare(shownText(details, "Already scheduled: Quiz, Film").length, 1, "who's in the way")
      verify(shownText(details, "Cancel recording")[0], "its choice")
      guide.libDetail = null
    }

    function test_the_details_follow_the_recording() {
      guide.libDetailRec = { id: "a", kind: "iptv", state: "done", present: true, path: "/r/a.ts", channel: { name: "News 24" } }
      guide.recActions = [{ key: "play", label: "Play" }]
      guide.libEpisode = 0
      guide.libDetail = root.card("a", "Recording", { sub: "News 24 · until 9:00" })
      wait(50)
      compare(shownText(details, "News 24 · until 9:00").length, 1, "as it was opened, with nothing newer")
      guide.libDetailRecCard = root.card("a", "Done", { sub: "News 24 · 8 min" })
      wait(50)
      compare(shownText(details, "News 24 · 8 min").length, 1, "stopped while it's open: as it is now")
      compare(shownText(details, "News 24 · until 9:00").length, 0, "not its stop time from before")
      guide.libDetailRecCard = null
      guide.libDetail = null
    }

    function test_a_long_reason_stays_in_the_box() {
      guide.libDetailRec = { id: "m", kind: "iptv", state: "missed", reason: "notRunning", show: { start: 160, end: 1880 }, channel: { name: "News 24" } }
      guide.recActions = [{ key: "delete", label: "Take it off the list…", danger: true }]
      guide.libEpisode = 0
      guide.libDetail = root.card("m", "Missed")
      wait(50)
      var why = shownText(details, Dvr.reasonOf(guide.libDetailRec))[0]
      verify(why, "why it was missed")
      var info = why.parent.parent
      verify(why.mapToItem(info, why.width, 0).x <= info.width + 0.5, "inside the box, beside its state")
      verify(why.lineCount > 1, "wrapped, not run past the box's edge")
      guide.libDetail = null
    }

    function test_a_record_choices_note_uses_the_row() {
      var note = under(recordRow, function(it) { return it.text === recordRow.value })[0]
      verify(note, "the note")
      compare(note.truncated, false, "whole: the room its short name leaves, not half the row")
      verify(note.width > recordRow.width * 0.5, "past half the row")
      var value = under(plainRow, function(it) { return it.text === plainRow.value })[0]
      compare(value.truncated, true, "a setting's value still keeps to half")
    }

    function test_a_recordings_details() {
      guide.libDetailRec = { id: "a", kind: "iptv", state: "incomplete", present: true, path: "/r/a.ts", reason: "space", channel: { name: "News 24" } }
      guide.recActions = [{ key: "play", label: "Play" }, { key: "delete", label: "Delete recording…", danger: true }]
      guide.libEpisode = 1
      guide.libDetail = root.card("a", "Incomplete")
      wait(50)
      compare(shownText(details, "Incomplete").length, 1, "its state")
      compare(shownText(details, "The disk got too full.").length, 1, "and why it stopped")
      var del = shownText(details, "Delete recording…")[0]
      verify(del, "its choices as rows")
      for (var p = del.parent; p && p.element === undefined; p = p.parent) {}
      compare(p.element, "recordChoice", "in the record choice element")
      compare(p.focused, true, "the one under the cursor focused")
      compare(shownText(details, "Play").length, 1)
      guide.libDetail = null
    }
  }
}
