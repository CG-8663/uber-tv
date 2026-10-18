import QtQuick
import "../Look.js" as Look

// Text on split flaps, like a departures board: a row of tiles with a
// letter on each, and the letters that change flip over when the text does.
// Kept light (a tile, a letter and a scale each, one animation for the lot)
// since a board shows a thousand or so at once.
Item {
  id: flaps

  property string text: ""
  property int count: 8              // flaps; longer text is cut
  property var s: ({})               // the flap element's style, resolved
  property var textColor: undefined  // over the style's, where the board wants another (live)
  property real tileHeight: 32
  property real unit: 16
  property bool alignRight: false

  readonly property real tileWidth: Math.round(tileHeight * (s.aspect || 0.66))
  readonly property real gap: Math.max(1, Math.round(Look.px(s.gap, unit)))
  readonly property color fill: s.fill && typeof s.fill === "object" ? s.fill.from : (s.fill || "#1a1a1a")
  readonly property real radius: Look.px(s.radius, tileHeight / 2.4)
  readonly property real letterSize: Math.min((s.text ? s.text.size : 1.2) * unit, tileHeight * 0.74)

  // the text as exactly count letters, padded with blanks
  function fitted(t) {
    var str = String(t || "")
    if (str.length > count) str = str.slice(0, count)
    var pad = new Array(count - str.length + 1).join(" ")
    return alignRight ? pad + str : str + pad
  }

  property string fromText: ""
  property string toText: ""
  property real phase: 1

  onTextChanged: turn()
  onCountChanged: { fromText = fitted(text); toText = fromText }
  Component.onCompleted: { fromText = new Array(count + 1).join(" "); toText = fitted(text); flip.restart() }

  function turn() {
    var shown = phase < 0.5 ? fromText : toText
    var next = fitted(text)
    if (next === shown) return
    fromText = shown
    toText = next
    flip.restart()
  }

  NumberAnimation { id: flip; target: flaps; property: "phase"; from: 0; to: 1; duration: 300; easing.type: Easing.InOutQuad }

  implicitWidth: count * tileWidth + Math.max(0, count - 1) * gap
  implicitHeight: tileHeight

  Row {
    spacing: flaps.gap
    Repeater {
      model: flaps.count
      delegate: Rectangle {
        id: tile
        required property int index
        readonly property string from: flaps.fromText.charAt(index)
        readonly property string to: flaps.toText.charAt(index)
        width: flaps.tileWidth
        height: flaps.tileHeight
        radius: flaps.radius
        color: flaps.fill
        border.color: flaps.s.border ? flaps.s.border.color : "transparent"
        border.width: flaps.s.border && flaps.s.border.width ? Math.max(1, Look.px(flaps.s.border.width, flaps.unit)) : 0

        Text {
          id: letter
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: flaps.phase < 0.5 ? tile.from : tile.to
          color: flaps.textColor !== undefined ? flaps.textColor : (flaps.s.text ? flaps.s.text.color : "white")
          font.family: flaps.s.text ? flaps.s.text.font : ""
          font.pixelSize: Math.max(1, flaps.letterSize)
          font.weight: flaps.s.text ? flaps.s.text.weight : Font.Bold
          font.capitalization: flaps.s.text && flaps.s.text.case === "lower" ? Font.AllLowercase
                             : flaps.s.text && flaps.s.text.case === "none" ? Font.MixedCase : Font.AllUppercase
          transform: Scale {
            origin.y: letter.height / 2
            yScale: tile.from !== tile.to && flaps.phase < 1 ? Math.abs(1 - 2 * flaps.phase) : 1
          }
        }
      }
    }
  }

  // The split across every flap
  Rectangle {
    y: Math.round(flaps.tileHeight / 2 - height / 2)
    width: flaps.implicitWidth
    height: Math.max(1, Math.round(flaps.tileHeight * 0.04))
    color: flaps.s.seam || "black"
  }
}
