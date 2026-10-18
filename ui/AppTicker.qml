import QtQuick
import "../AppLooks.js" as Looks

// A ticker row an app sent (api 4): its items' text and badges in one line,
// moving across slowly, over and over; it stops while it's selected, while
// the screen saver is up and while a video plays full screen (moving: what
// AppScreen says), and holds where it stopped.
Box {
  id: ticker

  required property var guide
  required property var line
  property bool moving: true
  readonly property real u: guide.u

  s: guide.look.appTicker
  unit: u
  clip: true

  Row {
    id: strip
    objectName: "tickerStrip"
    anchors.verticalCenter: parent.verticalCenter
    spacing: ticker.u * 2.4
    Repeater {
      model: ticker.line ? ticker.line.items : []
      delegate: Row {
        required property var modelData
        spacing: ticker.u * 0.6
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        Label {
          anchors.verticalCenter: parent.verticalCenter
          text: parent.modelData.title
          s: ticker.guide.look.appTicker
          unit: ticker.u
        }
        Label {
          anchors.verticalCenter: parent.verticalCenter
          visible: text !== ""
          text: parent.modelData.badge || ""
          s: Looks.floored(ticker.guide.look.appBadge, Looks.CARD_TEXT, ticker.u, 1)
          unit: ticker.u
        }
      }
    }
  }

  // across from its right edge until it's gone at the left, about 3 units a second
  NumberAnimation {
    id: run
    target: strip
    property: "x"
    from: ticker.width
    to: -strip.width
    duration: Math.max(4000, Math.round((ticker.width + strip.width) / (ticker.u * 3) * 1000))
    loops: Animation.Infinite
    running: ticker.visible && ticker.width > 0 && strip.width > 0
    paused: running && !ticker.moving
  }
  onWidthChanged: if (run.running) run.restart()
}
