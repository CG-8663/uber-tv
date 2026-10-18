import QtQuick

// Full-screen TV: black behind the picture, and the channel banner (the
// lower third). The picture itself (Guide.qml's video) moves in here.
Rectangle {
  id: tvScreen

  required property var guide

  visible: guide.watching
  color: "black"

  // The mouse, as on a TV player: moving it shows the banner (or the player
  // bar), a click pauses (or shows the banner), a double-click goes back.
  // Nothing stays on the picture: still for a moment, the pointer hides too.
  property bool pointerIdle: false
  property real bannerAt: 0

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: tvScreen.pointerIdle ? Qt.BlankCursor : Qt.ArrowCursor
    onPositionChanged: {
      tvScreen.pointerIdle = false
      idle.restart()
      if (Date.now() - tvScreen.bannerAt > 1500) {
        tvScreen.bannerAt = Date.now()
        guide.vod ? guide.showVodBar() : guide.showBanner()
      }
    }
    onClicked: guide.vod ? guide.togglePause() : guide.showBanner()
    onDoubleClicked: guide.vod ? guide.stopVod() : guide.showGuide()
  }

  Timer {
    id: idle
    interval: 2500
    running: tvScreen.visible
    onTriggered: tvScreen.pointerIdle = true
  }

  // On demand: the player bar
  VodBar {
    z: 2
    visible: guide.vod !== null && (guide.vodBarShown || guide.vodPaused || guide.reception !== "on")
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: guide.u * 2
    guide: tvScreen.guide
  }

  // The channel banner (the lower third)
  LowerThird {
    z: 2
    visible: guide.bannerShown && guide.vod === null
    anchors.fill: parent
    look: guide.look
    image: guide.areaImages.lt
    unit: guide.u
    logo: guide.logoFor(guide.channels[guide.tunedRow])
    number: guide.numbers[guide.tunedRow] || ""
    channel: guide.channels[guide.tunedRow] ? guide.channels[guide.tunedRow].name : ""
    title: guide.onAir ? guide.onAir.title : ""
    progress: guide.onAir && (!guide.onAir.live || guide.onAir.epg) ? Math.max(0, (guide.now - guide.onAir.start) / (guide.onAir.end - guide.onAir.start)) : -1
    clock: guide.clock(guide.now)
    times: !guide.onAir ? "" : guide.onAir.live && !guide.onAir.epg ? "● LIVE" : guide.clock(guide.onAir.start) + " – " + guide.clock(guide.onAir.end)
  }
}
