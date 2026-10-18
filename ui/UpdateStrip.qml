import QtQuick

// The strip about Uber TV's updates, across the bottom of Home and the
// guide, just above the key hints. The first time: update notifications are
// off, and Y (or a click) turns them on, N puts the strip away for good.
// After Turn on, what the first look found, for a few seconds. Never over a
// box, nor while you watch.
Box {
  id: strip

  required property var guide

  readonly property var updates: guide.updates
  readonly property real u: guide.u
  readonly property bool asking: !updates.asked
  readonly property string message: asking ? "Updates are off. To get the latest updates, turn on update notifications." : updates.strip

  visible: message !== "" && guide.opened && !guide.watching && guide.dialog === ""
           && (guide.screen === "home" || guide.screen === "guide") && !guide.managing && !guide.homeEditing && !guide.railEditing
  height: Math.round(u * 3)
  s: guide.look.box
  unit: u

  // a click on the strip stays on it
  MouseArea { anchors.fill: parent }

  Icon {
    id: mark
    anchors.left: parent.left
    anchors.leftMargin: strip.u
    anchors.verticalCenter: parent.verticalCenter
    name: "info"
    size: Math.round(strip.u * 1.3)
    stroke: 2
    color: strip.guide.colors.accent
  }
  Label {
    anchors.left: mark.right
    anchors.leftMargin: strip.u * 0.8
    anchors.right: actions.visible ? actions.left : parent.right
    anchors.rightMargin: strip.u
    anchors.verticalCenter: parent.verticalCenter
    text: strip.message
    s: strip.guide.look.menuRow
    unit: strip.u
    sizeFactor: 0.78
    color: strip.guide.ink
    elide: Text.ElideRight
  }

  Row {
    id: actions
    visible: strip.asking
    anchors.right: parent.right
    anchors.rightMargin: strip.u
    anchors.verticalCenter: parent.verticalCenter
    spacing: strip.u * 1.2
    Repeater {
      model: [{ keys: ["Y"], label: "Turn on", act: "on" }, { keys: ["N"], label: "Dismiss", act: "dismiss" }]
      delegate: Item {
        id: action
        required property var modelData
        width: hint.implicitWidth
        height: hint.implicitHeight
        KeyHints {
          id: hint
          model: [{ keys: action.modelData.keys, label: action.modelData.label }]
          size: strip.u * 1.55
          capStyle: strip.guide.look.keycap
          labelStyle: strip.guide.look.keyLabel
        }
        MouseArea {
          anchors.fill: parent
          anchors.margins: -strip.u * 0.3
          cursorShape: Qt.PointingHandCursor
          onClicked: action.modelData.act === "on" ? strip.updates.turnOn() : strip.updates.dismiss()
        }
      }
    }
  }
}
