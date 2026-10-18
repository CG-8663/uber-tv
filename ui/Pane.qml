import QtQuick

// A pane of the table layout: a box (the pane element) with its name set
// into the top border, like tmux and terminal apps draw them. What's put
// inside goes in its padding, under the name.
Box {
  id: pane

  required property var guide
  property string title: ""
  property string note: ""          // quieter words after the name: a count, a channel
  default property alias content: inner.data
  readonly property real titleHeight: titleBox.height

  s: guide.look.pane
  unit: guide.u

  Box {
    id: titleBox
    x: guide.u * 1.2
    y: -height / 2
    z: 2
    width: titleRow.implicitWidth + titleBox.padding * 2
    height: titleRow.implicitHeight + Math.min(titleBox.padding, guide.u * 0.2) * 2
    s: guide.look.paneTitle
    unit: guide.u

    Row {
      id: titleRow
      anchors.centerIn: parent
      spacing: guide.u * 0.5
      Label {
        text: pane.title
        s: guide.look.paneTitle
        unit: guide.u
      }
      Label {
        visible: pane.note !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: pane.note
        s: guide.look.barLabel
        unit: guide.u
      }
    }
  }

  Item {
    id: inner
    anchors.fill: parent
    anchors.margins: pane.padding
    anchors.topMargin: Math.max(pane.padding, titleBox.height / 2 + guide.u * 0.3)
    clip: true
  }
}
