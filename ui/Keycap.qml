import QtQuick
import "../Look.js" as Look

// A key drawn as a keycap: its face with the label on it, over a lower edge
// for depth, styled by the keycap element (Look.js), whose lengths go by the
// key's height. Single characters sit on a square key; words (ENTER, SHIFT)
// get a wider one.
Item {
  id: cap

  property string label: ""
  property real size: 24          // the key's height
  property var s: ({})            // the keycap element's style, resolved

  readonly property real edge: (s.depth || 0) > 0 ? Math.max(2, Math.round(size * s.depth)) : 0
  // "auto": a border a little lighter than the face
  readonly property var faceStyle: {
    var face = s.fill && typeof s.fill === "object" ? s.fill.from : (s.fill || "#e4e9ff")
    var border = s.border && s.border.color === "auto" ? Qt.lighter(face, 1.15).toString() : s.border ? s.border.color : "transparent"
    return Look.merge(s, { border: { color: border } })
  }

  implicitHeight: size
  implicitWidth: Math.max(size, keyLabel.implicitWidth + size * 0.7)

  Rectangle {
    anchors.fill: parent
    anchors.topMargin: cap.edge
    visible: cap.edge > 0
    radius: cap.size * (cap.s.radius || 0)
    color: cap.s.edge || "transparent"
  }

  Box {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    height: parent.height - cap.edge
    s: cap.faceStyle
    unit: cap.size

    Label {
      id: keyLabel
      anchors.centerIn: parent
      text: cap.label
      s: cap.s
      unit: cap.size
      sizeFactor: cap.label.length > 1 ? 0.5 / 0.62 : 1
    }
  }
}
