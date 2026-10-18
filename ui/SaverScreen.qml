import QtQuick
import QtQuick.Effects
import "../Saver.js" as SaverRules

// One screen of the screen saver (ScreenSaver.qml): its pictures crossfading,
// each drifting and zooming slowly, scaled to the screen when it's read, and
// the clock, which moves a little every minute so nothing burns in. Each
// picture is shown from the copy take() makes (never from its own name).
Item {
  id: scr

  required property var guide
  property var order: []              // the pictures, shuffled once for every screen
  property int place: 0               // this screen among the screens
  property int screens: 1
  property int every: 20              // seconds a picture stays
  property string clockAt: "bottomRight"
  property real dpr: 1
  property var take: null             // take(path, done(copy)): ScreenSaver.qml

  property int step: 0
  property bool frontA: true          // which layer is in front
  readonly property real u: Math.max(10, height / 60)

  // A picture's copy into a layer; one that can't be shown is passed over
  // for the next (a few times at most)
  function load(layer, tries) {
    var p = SaverRules.pictureAt(scr.order, scr.step, scr.place, scr.screens)
    if (!p || !scr.take) return
    scr.take(p, function(copy) {
      if (!copy) { if (tries < 3 && scr.order.length > 1) { scr.step += 1; scr.load(layer, tries + 1) } return }
      layer.source = scr.guide.fileUrl(copy)
    })
  }

  // The next picture goes in the layer behind; once it's read, it fades in
  function advance() {
    scr.step += 1
    scr.load(scr.frontA ? layerB : layerA, 0)
  }
  function swap() {
    scr.frontA = !scr.frontA
    var front = scr.frontA ? layerA : layerB
    front.drift()
  }

  Rectangle { anchors.fill: parent; color: "black" }

  SaverPicture { id: layerA; shown: scr.frontA; every: scr.every; dpr: scr.dpr; onLoaded: if (!scr.frontA) scr.swap() }
  SaverPicture { id: layerB; shown: !scr.frontA; every: scr.every; dpr: scr.dpr; onLoaded: if (scr.frontA) scr.swap() }

  Timer {
    interval: scr.every * 1000
    repeat: true
    running: scr.order.length > 1
    onTriggered: scr.advance()
  }

  Component.onCompleted: {
    scr.load(layerA, 0)
    layerA.drift()
  }

  // ---- the clock ----
  property real nudgeX: 0
  property real nudgeY: 0
  Timer {
    interval: 60000
    repeat: true
    running: scr.clockAt !== "off"
    onTriggered: { scr.nudgeX = (Math.random() - 0.5) * scr.u * 3; scr.nudgeY = (Math.random() - 0.5) * scr.u * 2 }
  }
  Behavior on nudgeX { NumberAnimation { duration: 4000; easing.type: Easing.InOutSine } }
  Behavior on nudgeY { NumberAnimation { duration: 4000; easing.type: Easing.InOutSine } }

  // a soft shade under it, so it reads on any picture
  Rectangle {
    visible: scr.clockAt !== "off"
    width: clockBox.width + scr.u * 10
    height: clockBox.height + scr.u * 8
    x: clockBox.x + (clockBox.width - width) / 2
    y: clockBox.y + (clockBox.height - height) / 2
    radius: height / 2
    color: "black"
    opacity: 0.28
    layer.enabled: true
    layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 64 }
  }

  Column {
    id: clockBox
    visible: scr.clockAt !== "off"
    readonly property real margin: scr.u * 4
    spacing: scr.u * 0.2
    x: (scr.clockAt === "topLeft" || scr.clockAt === "bottomLeft" ? margin
        : scr.clockAt === "middle" ? (scr.width - width) / 2 : scr.width - width - margin) + scr.nudgeX
    y: (scr.clockAt === "topLeft" || scr.clockAt === "topRight" ? margin
        : scr.clockAt === "middle" ? (scr.height - height) / 2 : scr.height - height - margin) + scr.nudgeY
    layer.enabled: true
    layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "#c0000000"; shadowBlur: 0.8; shadowVerticalOffset: 2 }

    Text {
      anchors.right: scr.clockAt === "topRight" || scr.clockAt === "bottomRight" ? parent.right : undefined
      anchors.horizontalCenter: scr.clockAt === "middle" ? parent.horizontalCenter : undefined
      text: scr.guide.clock(scr.guide.now)
      color: "white"
      font.family: scr.guide.look.clock.text.font || ""
      font.pixelSize: scr.u * (scr.clockAt === "middle" ? 7 : 5)
      font.weight: Font.Light
    }
    Text {
      anchors.right: scr.clockAt === "topRight" || scr.clockAt === "bottomRight" ? parent.right : undefined
      anchors.horizontalCenter: scr.clockAt === "middle" ? parent.horizontalCenter : undefined
      text: Qt.formatDate(new Date(scr.guide.now * 1000), "dddd, d MMMM")
      color: "white"
      opacity: 0.9
      font.family: scr.guide.look.clock.text.font || ""
      font.pixelSize: scr.u * 1.6
    }
  }
}
