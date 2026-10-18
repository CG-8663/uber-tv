import QtQuick
import "../AppLooks.js" as Looks

// Who an app's screen belongs to, always: a band across the top with the
// app's icon in a frame (so a see-through icon still shows where it is),
// an APP cue, its name, a small badge for an app installed from a file
// or a file (ui/OriginBadge.qml: no words), and the time. It's the guide's own, not a styled part: no theme, style or
// agent changes whether it shows, where, how big or how see-through. Its
// fill follows the theme only while the theme's text reads on it (4.5:1);
// otherwise the guide's own colors. Sizes are fixed in units, the font is
// the shell's. Drawn over every picture, shade and theme picture on the
// screen; only the guide's own boxes go over it.
Rectangle {
  id: strip

  required property var guide
  property var app: null              // the app's record
  readonly property real u: guide.u
  readonly property var pair: Looks.stripColors(String(guide.colors.bgTop), String(guide.colors.text))
  readonly property string ink: pair.text

  objectName: "identityStrip"
  height: Math.max(Math.round(u * 3.6), Math.ceil(u * 3.2))
  color: pair.fill
  opacity: 1

  Row {
    id: who
    x: strip.u * 3
    anchors.verticalCenter: parent.verticalCenter
    spacing: strip.u * 0.9

    // its icon, in a frame of its own
    Rectangle {
      objectName: "stripIconFrame"
      anchors.verticalCenter: parent.verticalCenter
      width: Math.round(strip.u * 2.6)
      height: width
      radius: strip.u * 0.4
      color: "transparent"
      border.width: Math.max(1, Math.round(strip.u * 0.1))
      border.color: strip.ink
      Image {
        anchors.fill: parent
        anchors.margins: parent.border.width + Math.round(strip.u * 0.2)
        visible: status === Image.Ready
        source: strip.app && strip.app.icon ? strip.guide.fileUrl(strip.app.icon) : ""
        sourceSize.width: 128
        fillMode: Image.PreserveAspectFit
        asynchronous: true
      }
    }
    // the APP cue
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: cue.implicitWidth + strip.u * 0.9
      height: cue.implicitHeight + strip.u * 0.3
      radius: strip.u * 0.3
      color: "transparent"
      border.width: Math.max(1, Math.round(strip.u * 0.1))
      border.color: strip.ink
      Text {
        id: cue
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: "APP"
        color: strip.ink
        font.family: strip.guide.fontFamily
        font.pixelSize: Math.round(strip.u * 0.85)
        font.bold: true
        font.letterSpacing: strip.u * 0.12
      }
    }
    Text {
      objectName: "stripName"
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: strip.app ? strip.app.name : ""
      color: strip.ink
      font.family: strip.guide.fontFamily
      font.pixelSize: Math.round(strip.u * 1.5)
      font.bold: true
      elide: Text.ElideRight
      width: Math.min(implicitWidth, strip.width - strip.u * 30)
    }
    // from a signed or Developer-mode file: not Uber TV's own
    OriginBadge {
      anchors.verticalCenter: parent.verticalCenter
      guide: strip.guide
      u: strip.u
      from: strip.app ? strip.app.from || "" : ""
    }
  }
  Text {
    anchors.right: parent.right
    anchors.rightMargin: strip.u * 3
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: strip.guide.clock(strip.guide.now)
    color: strip.ink
    font.family: strip.guide.fontFamily
    font.pixelSize: Math.round(strip.u * 1.4)
    font.bold: true
  }
}
