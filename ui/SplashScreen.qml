import QtQuick
import QtQuick.Shapes

// The splash when Uber TV turns on (Settings → General → Splash screen): an
// old set warming up, about 9 seconds, drawn on a 1920 × 1080 stage scaled to
// fit. A white line opens into a picture, snow rolls, color bars tune in to
// channel 03, the logo snaps in with a color-fringe glitch while the tagline
// types out, and the picture collapses to a dot. Any key, click or phone
// press skips it (skip()). The design is output/splash.
Item {
  id: splash

  property real t: 0                    // seconds into it
  readonly property bool running: run.running
  signal finished()

  visible: running
  enabled: running

  // the scenes, as in the design: dark 0.5, on 1.3, snow 1.2, tune 1.4,
  // logo 3.4, off 1.2
  readonly property real cOn: 0.5
  readonly property real cStatic: 1.8
  readonly property real cTune: 3.0
  readonly property real cLogo: 4.4
  readonly property real cOff: 7.8
  readonly property real total: 9.0

  readonly property color amber: "#f0b44c"
  readonly property color cream: "#e6e4da"
  readonly property color ink: "#0c0d13"
  readonly property color green: "#4fe08c"

  function start() {
    splash.t = 0
    run.restart()
  }

  function skip() {
    if (!run.running) return
    run.stop()
  }

  NumberAnimation {
    id: run
    objectName: "splashClock"
    target: splash
    property: "t"
    from: 0
    to: splash.total
    duration: splash.total * 1000
    onRunningChanged: if (!running) splash.finished()
  }

  FontLoader { id: display; source: Qt.resolvedUrl("../fonts/Orbitron.ttf") }
  FontLoader { id: mono; source: Qt.resolvedUrl("../fonts/DMMono-Medium.ttf") }

  // ---- easing, as the design's three motion helpers ----
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)) }
  function prog(T, s, e) { return clamp((T - s) / (e - s), 0, 1) }
  function enter(T, s, e) { var p = prog(T, s, e); return p >= 1 ? 1 : 1 - Math.pow(2, -10 * p) }
  function ease(T, s, e) { var p = prog(T, s, e); return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2 }
  function snap(T, s, e) { var p = prog(T, s, e); return p * p * p }
  function hash(n) { var x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x) }

  // ---- the picture's geometry: a line grows, then opens; the reverse at the end ----
  readonly property real sx: {
    var T = splash.t
    if (T < cOn) return 0
    return Math.min(enter(T, cOn, cOn + 0.3), 1 - snap(T, cOff + 0.35, cOff + 0.8))
  }
  readonly property real sy: {
    var T = splash.t
    if (T < cOn) return 0
    return Math.min(0.006 + 0.994 * ease(T, cOn + 0.3, cOn + 1.0), 0.006 + 0.994 * (1 - snap(T, cOff, cOff + 0.4)))
  }
  readonly property real flash: {
    var T = splash.t
    return enter(T, cOn + 0.15, cOn + 0.5) * (1 - ease(T, cOn + 0.5, cOn + 1.4))
           + ease(T, cOff - 0.1, cOff + 0.3) * (1 - snap(T, cOff + 0.3, cOff + 0.5)) * 0.6
  }

  Rectangle { anchors.fill: parent; color: "black" }

  MouseArea { anchors.fill: parent; onClicked: splash.skip() }

  Item {
    id: stage
    width: 1920
    height: 1080
    anchors.centerIn: parent
    scale: Math.min(splash.width / 1920, splash.height / 1080)

    // the dot: as it switches on, and the afterglow as it goes
    Item {
      x: 960; y: 540
      opacity: (splash.t >= splash.cOn && splash.t < splash.cOn + 0.05 ? 1 : 0)
               + (splash.t > splash.cOff + 0.7 ? 1 - splash.snap(splash.t, splash.cOff + 0.7, splash.cOff + 1.1) : 0)
      Rectangle { x: -40; y: -40; width: 80; height: 80; radius: 40; color: "white"; opacity: 0.25 }
      Rectangle { x: -20; y: -20; width: 40; height: 40; radius: 20; color: "white"; opacity: 0.5 }
      Rectangle { x: -6; y: -6; width: 12; height: 12; radius: 6; color: "white" }
    }

    Rectangle {
      id: picture
      width: 1920
      height: 1080
      color: "#0a0b10"
      radius: 70 * (1 - splash.sy) + 40
      clip: true
      opacity: splash.clamp(splash.sx * 40, 0, 1) * (1 - splash.snap(splash.t, splash.cOff + 0.7, splash.cOff + 1.0))
      transform: Scale { origin.x: 960; origin.y: 540; xScale: splash.sx; yScale: splash.sy }

      // snow, and the hold bar rolling through it
      Item {
        anchors.fill: parent
        opacity: splash.ease(splash.t, splash.cOn + 0.5, splash.cOn + 0.9) * 0.9 * (1 - splash.ease(splash.t, splash.cTune - 0.05, splash.cTune + 0.35))
        visible: opacity > 0
        readonly property real roll: splash.t > splash.cStatic && splash.t < splash.cTune ? -((splash.t - splash.cStatic) * 900) % 1080 : 0
        Noise { y: parent.roll; frame: Math.floor(splash.t * 24) }
        Noise { y: parent.roll + 1080; frame: Math.floor(splash.t * 24) + 1 }
        Rectangle { y: 540 + Math.sin(splash.t * 9) * 400; width: 1920; height: 36; color: Qt.rgba(1, 1, 1, 0.35) }
      }

      // color bars, channel 03
      Item {
        id: bars
        width: 1920
        height: 1080
        readonly property real roll: splash.enter(splash.t, splash.cTune, splash.cTune + 0.7) * -380 + 380
        x: Math.sin(splash.t * 40) * 6 * (1 - splash.ease(splash.t, splash.cTune, splash.cTune + 0.7))
        y: roll
        opacity: splash.enter(splash.t, splash.cTune, splash.cTune + 0.12) * (1 - splash.ease(splash.t, splash.cLogo + 0.3 - 0.35, splash.cLogo + 0.3))
        visible: opacity > 0
        Rectangle { anchors.fill: parent; color: splash.ink }
        Row {
          Repeater {
            model: ["#c8c8c8", "#c8c800", "#00c8c8", "#00c800", "#c800c8", "#c80000", "#0000c8"]
            Rectangle { width: 1920 / 7; height: 700; color: modelData }
          }
        }
        Row {
          y: 700
          Repeater {
            model: ["#0000c8", "#131313", "#c800c8", "#131313", "#00c8c8", "#131313", "#c8c8c8"]
            Rectangle { width: 1920 / 7; height: 90; color: modelData }
          }
        }
        Row {
          y: 790
          Repeater {
            model: ["#00214c", "#ffffff", "#32006a", "#131313", "#090909", "#131313", "#1d1d1d", "#131313"]
            Rectangle { width: 1920 / 8.4 * (index === 3 ? 1.4 : 1); height: 290; color: modelData }
          }
        }
        Text {
          x: 110; y: 96
          text: "CH 03"
          font.family: mono.font.family
          font.pixelSize: 56
          font.letterSpacing: 4
          color: splash.green
          opacity: Math.sin(splash.t * 5) > -0.6 ? 1 : 0
        }
        Text {
          anchors.right: parent.right
          anchors.rightMargin: 110
          y: 96
          text: splash.t - splash.cTune < 0.45 ? "TUNING" : "SIGNAL OK"
          font.family: mono.font.family
          font.pixelSize: 40
          font.letterSpacing: 4
          color: splash.green
        }
      }

      // the logo, snapping in with a color-fringe glitch, and the tagline typing out
      Item {
        id: logoShot
        anchors.fill: parent
        readonly property real settle: 1 - splash.ease(splash.t, splash.cLogo, splash.cLogo + 0.9)
        readonly property real jit: (Math.floor(splash.t * 30) % 2 ? 1 : -1) * 22 * settle * splash.hash(Math.floor(splash.t * 30))
        opacity: splash.clamp(splash.enter(splash.t, splash.cLogo, splash.cLogo + 0.5) * 3, 0, 1)
        visible: splash.t >= splash.cLogo

        Item {
          id: logoRow
          width: parent.width
          height: 210
          y: 1080 / 2 - (210 + 70 + 56) / 2
          transform: [
            Scale { origin.x: 960; origin.y: 105; yScale: 0.82 + 0.18 * splash.enter(splash.t, splash.cLogo, splash.cLogo + 0.45) },
            Translate { y: logoShot.jit * 0.3 }
          ]
          Logo { family: display.font.family; tone: "#ff2d55"; box: "#ff2d55"; inkColor: "black"; opacity: 0.6; x: (parent.width - width) / 2 - logoShot.jit - 14 * logoShot.settle }
          Logo { family: display.font.family; tone: "#00e5ff"; box: "#00e5ff"; inkColor: "black"; opacity: 0.6; x: (parent.width - width) / 2 + logoShot.jit + 14 * logoShot.settle }
          Logo {
            family: display.font.family; tone: splash.cream; box: splash.amber; inkColor: splash.ink
            x: (parent.width - width) / 2
            opacity: splash.enter(splash.t, splash.cLogo + 0.15, splash.cLogo + 0.6)
          }
        }

        Text {
          readonly property string typed: "media center for omarchy"
          readonly property int shown: Math.floor(splash.clamp((splash.t - splash.cLogo - 0.9) / 1.0, 0, 1) * typed.length)
          readonly property bool caret: Math.floor(splash.t * 2.2) % 2 === 0 || shown < typed.length
          anchors.horizontalCenter: parent.horizontalCenter
          anchors.horizontalCenterOffset: logoShot.jit
          y: logoRow.y + 210 + 70
          textFormat: Text.StyledText
          text: typed.slice(0, shown) + "<font color='" + splash.amber + "'>" + (caret ? "▌" : "&nbsp;") + "</font>"
          font.family: display.font.family
          font.pixelSize: 40
          font.letterSpacing: 10
          color: splash.cream
          opacity: 0.9
        }
      }

      // scanlines, the vignette, flicker and the flash
      Repeater {
        model: 270
        Rectangle { y: index * 4 + 3; width: 1920; height: 1; color: Qt.rgba(0, 0, 0, 0.28) }
      }
      Shape {
        anchors.fill: parent
        ShapePath {
          strokeWidth: -1
          fillGradient: RadialGradient {
            centerX: 960; centerY: 540; centerRadius: 1100
            focalX: 960; focalY: 540
            GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.75) }
          }
          startX: 0; startY: 0
          PathLine { x: 1920; y: 0 }
          PathLine { x: 1920; y: 1080 }
          PathLine { x: 0; y: 1080 }
          PathLine { x: 0; y: 0 }
        }
      }
      Rectangle { anchors.fill: parent; color: "white"; opacity: (1 - (0.94 + 0.06 * Math.sin(splash.t * 61) * Math.sin(splash.t * 17))) * 0.4 }
      Rectangle { anchors.fill: parent; color: "white"; opacity: Math.min(1, splash.flash) * 0.9 }
    }

    // the line, glowing while it's thin
    Item {
      y: 540
      width: 1920
      opacity: splash.sy < 0.05 && splash.sx > 0 ? 1 : 0
      transform: Scale { origin.x: 960; xScale: splash.sx }
      Rectangle { y: -18; width: 1920; height: 36; color: "white"; opacity: 0.2 }
      Rectangle { y: -9; width: 1920; height: 18; color: "white"; opacity: 0.4 }
      Rectangle { y: -3; width: 1920; height: 6; color: "white" }
    }
  }

  // "uber" and "tv" in its box, in one color
  component Logo: Row {
    id: logo
    property string family
    property color tone
    property color box
    property color inkColor
    spacing: 56
    height: 210
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: "uber"
      font.family: logo.family
      font.weight: Font.ExtraBold
      font.pixelSize: 190
      font.letterSpacing: -4
      font.variableAxes: { "wght": 800 }   // (Orbitron is one variable font)
      color: logo.tone
    }
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: tvText.implicitWidth + 72
      height: tvText.implicitHeight + 14
      radius: 28
      color: logo.box
      Text {
        id: tvText
        x: 36
        text: "tv"
        font.family: logo.family
        font.weight: Font.ExtraBold
        font.pixelSize: 190
        font.letterSpacing: -2
        font.variableAxes: { "wght": 800 }
        color: logo.inkColor
      }
    }
  }

  // snow: one grain picture (ui/splash-noise.png), shifted and flipped each
  // frame so it never looks still
  component Noise: Item {
    id: snow
    property int frame: 0
    width: 1920
    height: 1080
    clip: true
    function rnd(n) { var x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x) }
    Image {
      source: Qt.resolvedUrl("splash-noise.png")
      width: 600
      height: 360
      scale: 4
      transformOrigin: Item.TopLeft
      smooth: false
      mirror: snow.frame % 2 === 1
      x: -Math.floor(snow.rnd(snow.frame) * 120) * 4
      y: -Math.floor(snow.rnd(snow.frame + 7) * 90) * 4
    }
  }
}
