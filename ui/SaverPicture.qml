import QtQuick

// A picture of the screen saver (SaverScreen.qml): it fades in when shown,
// read at the screen's size (a little more, for the zoom), and drift() starts
// its slow zoom and pan, in or out, never far enough to show an edge.
Image {
  id: pic

  property bool shown: false
  property int every: 20
  property real dpr: 1
  signal loaded()

  width: parent ? parent.width : 0
  height: parent ? parent.height : 0
  fillMode: Image.PreserveAspectCrop
  asynchronous: true
  cache: false
  smooth: true
  sourceSize: Qt.size(Math.round(width * 1.16 * dpr), Math.round(height * 1.16 * dpr))
  opacity: shown && status === Image.Ready ? 1 : 0
  Behavior on opacity { NumberAnimation { duration: 1600; easing.type: Easing.InOutQuad } }
  onStatusChanged: if (status === Image.Ready) pic.loaded()

  // zoomed between 1.06 and 1.14, so a pan of up to 2.5% a side stays inside
  scale: 1.06
  transform: Translate { id: pan }

  function drift() {
    var inward = Math.random() < 0.5
    zoom.from = inward ? 1.06 : 1.14
    zoom.to = inward ? 1.14 : 1.06
    var sx = Math.random() < 0.5 ? -1 : 1, sy = Math.random() < 0.5 ? -1 : 1
    panX.from = sx * pic.width * 0.025
    panX.to = -panX.from * 0.6
    panY.from = sy * pic.height * 0.02
    panY.to = -panY.from * 0.6
    move.restart()
  }

  ParallelAnimation {
    id: move
    NumberAnimation { id: zoom; target: pic; property: "scale"; duration: (pic.every + 3) * 1000; easing.type: Easing.InOutSine }
    NumberAnimation { id: panX; target: pan; property: "x"; duration: (pic.every + 3) * 1000; easing.type: Easing.InOutSine }
    NumberAnimation { id: panY; target: pan; property: "y"; duration: (pic.every + 3) * 1000; easing.type: Easing.InOutSine }
  }
}
