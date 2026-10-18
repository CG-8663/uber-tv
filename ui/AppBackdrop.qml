import QtQuick
import QtQuick.Effects
import "../AppLooks.js" as Looks
import "../AppNav.js" as Nav

// What's behind an app's screen (§4.5), as the presentation model says:
//   focus: the selected item's backdrop (or its wide picture), blurred and
//     darkened, once the cursor has rested on it 300 ms; a new view, look
//     or start of the app calls a waiting change off; with neither
//     picture, the theme's colors, never the last item's picture;
//   details: on a details page, its backdrop (elsewhere the guide's own);
//   guide: the guide's own background; wallpaper: your Omarchy wallpaper;
//   image: a picture you picked; none: the theme's colors.
// A Cinematic details page lays its backdrop across the screen over that.
// Any picture an app or a theme sent is under at least 30% shade; only
// your wallpaper or your own picture may go lighter. The blur draws from
// one frozen picture of at most 480×270, made only while it's shown.
Item {
  id: back

  required property var guide
  required property var view
  required property var host           // the app screen it's on

  readonly property real u: guide.u
  readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
  readonly property var screen: host.model && host.model.screen ? host.model.screen : null
  readonly property var bg: screen ? screen.background : ({ mode: "details", image: "", dim: Looks.DIM })
  readonly property string mode: bg.mode
  readonly property bool detail: !!host.cur && host.cur.kind === "detail" && !!host.cur.value
  readonly property bool cinematic: detail && host.model.detailStyle === "cinematic"
  readonly property color shadeColor: guide.look.appShade && guide.look.appShade.color ? guide.look.appShade.color : guide.colors.bgBottom
  // the shade is always drawn opaque at its darkness: a see-through shade
  // color can't take the floor away
  readonly property color shadeSolid: Qt.rgba(shadeColor.r, shadeColor.g, shadeColor.b, 1)
  readonly property string shadeHex: "#" + [shadeSolid.r, shadeSolid.g, shadeSolid.b].map(function(v) { return ("0" + Math.round(v * 255).toString(16)).slice(-2) }).join("")
  // The guide's own background (guide and details modes), drawn here as the
  // guide draws it: its fill, its picture under its shade (bgBottom at its
  // darkness: a see-through bgBottom counts at its own alpha). A picture
  // that isn't surely yours (a theme's, or one saved before where it came
  // from was kept) is under the floor too (only yours, or your wallpaper,
  // may go lighter): what's added over it here (in the app shade's color)
  // to make that so, from what the guide's shade really darkens.
  readonly property real guideDim: guide.bgDim || 0
  readonly property bool guidePicture: guide.backgroundSource !== "" && guide.backgroundSource !== undefined
  readonly property bool guideFloored: !!guide.bgFloored && guidePicture
  readonly property real guideDark: Looks.stackShades(String(guide.colors.bgBottom), guideDim, "#00000000", 0).alpha
  readonly property real guideTopUp: guideFloored ? Looks.topUp(guideDark, Looks.SHADE_FLOOR) : 0
  readonly property var guideShade: Looks.stackShades(String(guide.colors.bgBottom), guideDim, shadeHex, guideTopUp)
  readonly property bool guideBack: mode === "guide" || (mode === "details" && !detailPic.visible)
  // your wallpaper, or a picture you picked, may go lighter than the floor
  readonly property bool yours: mode === "wallpaper" || (mode === "image" && !!screen && screen.from.background !== "theme")
  readonly property real dim: yours ? bg.dim : Math.max(Looks.SHADE_FLOOR, bg.dim)
  // the shade across a Cinematic details page: darkest behind the title and
  // text on the left, never under the floor
  readonly property real cineLight: Math.max(Looks.SHADE_FLOOR + 0.1, back.dim * 0.6)

  // What's directly behind the cards and titles, for the focus ring's and
  // the selected title's colors (AppLooks.behindColors)
  // (a picture only when one is drawn: before, without and after one, the
  // theme's colors are what's there)
  readonly property bool focusDrawn: !!blurred.item && blurred.item.painted
  readonly property var behind: {
    var fill = guide.look.background ? guide.look.background.fill : ""
    var base = String(guide.colors.bgBottom)
    var shade = back.shadeHex
    if (back.cinematic && cine.visible) return { fill: fill, base: base, picture: true, dim: back.cineLight, dimColor: shade }
    if (detailPic.visible || own.visible || (back.mode === "focus" && back.focusDrawn)) return { fill: fill, base: base, picture: true, dim: back.dim, dimColor: shade }
    if (back.guideBack)
      return { fill: fill, base: base, picture: back.guidePicture && guideImage.visible, dim: back.guideShade.alpha, dimColor: back.guideShade.color }
    return { fill: fill, base: base }
  }

  // the theme's colors, over the guide's own picture: every mode but the
  // guide's own and a details page's (which keep today's)
  // an opaque base: the window's own color over black (as the colors behind
  // are worked out), so nothing under the screen ever shows
  Rectangle { objectName: "opaqueBase"; anchors.fill: parent; color: "black" }
  Rectangle { anchors.fill: parent; color: guide.colors.bgBottom }
  // the theme's colors (every mode but a details page's backdrop drawn over them)
  Box {
    id: themeColors
    objectName: "themeColors"
    anchors.fill: parent
    s: guide.look.background
    unit: back.u
  }
  // the guide's own picture, its shade, and the floor over a theme's
  Image {
    id: guideImage
    objectName: "guidePicture"
    anchors.fill: parent
    visible: back.guideBack && back.guidePicture && status === Image.Ready
    source: back.guideBack && back.guidePicture ? guide.backgroundSource : ""
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    sourceSize.width: back.width
    sourceSize.height: back.height
  }
  Rectangle {
    anchors.fill: parent
    visible: guideImage.visible
    color: guide.colors.bgBottom
    opacity: back.guideDim
  }
  Rectangle {
    objectName: "guideTopUp"
    anchors.fill: parent
    visible: guideImage.visible && back.guideTopUp > 0
    color: back.shadeSolid
    opacity: back.guideTopUp
  }

  // ---- focus: the selected item's picture, after a rest ----
  readonly property var focusTarget: {
    if (back.mode !== "focus") return null
    if (back.detail) return Looks.backdropOf(host.cur.value)
    if (!host.model || !host.model.lines.length) return null
    var c = Nav.current(host.model, view.sel)
    return c && c.line.kind === "row" ? Looks.backdropOf(c.thing) : null
  }
  readonly property string targetKey: focusTarget ? String(focusTarget.token || focusTarget.path || "") : ""
  property var shownImg: null                  // the picture drawn: the one rested on
  property var wantedImg: null                 // the one asked for (wanted only while it's the target)
  readonly property string focusUrl: shownImg ? view.imageUrl(shownImg) : ""
  function keyOf(img) { return img ? String(img.token || img.path || "") : "" }
  function want(img) {
    if (back.wantedImg && back.wantedImg.token) view.unwant(back.wantedImg, "focus")
    back.wantedImg = img
    if (img && img.token) view.want(img, "focus")
  }
  function show(img) {
    back.want(img)
    back.shownImg = img
  }
  function retarget() {
    if (!back.targetKey) { rest.stop(); back.show(null); return }   // neither picture: the theme's colors
    if (back.keyOf(back.shownImg) === back.targetKey) { rest.stop(); back.want(back.shownImg); return }
    // moved on: the last one is no longer asked for (a new demand mustn't
    // ask for it again), and stays drawn only if it's already drawn
    back.want(null)
    if (!back.focusDrawn) back.shownImg = null
    rest.restart()
  }
  onTargetKeyChanged: back.retarget()
  Timer {
    id: rest
    objectName: "focusRest"
    interval: 300
    onTriggered: back.show(back.focusTarget)
  }
  // a new view, look or start: the waiting change is called off, and nothing
  // of the screen before stays
  function restart() { rest.stop(); back.show(null); back.retarget() }
  readonly property var viewNow: host.cur
  readonly property string lookNow: screen ? screen.look : ""
  onViewNowChanged: back.restart()
  onLookNowChanged: back.restart()
  Connections {
    target: back.view
    function onEpochChanged() { back.restart() }
  }
  Component.onCompleted: back.retarget()
  Component.onDestruction: back.want(null)

  // made again for every picture: a new picture (or one that can't be
  // drawn) never shows the last one's frozen frame
  property string blurUrl: ""
  onFocusUrlChanged: { back.blurUrl = ""; Qt.callLater(function() { back.blurUrl = back.focusUrl }) }
  Loader {
    id: blurred
    objectName: "focusBlur"
    anchors.fill: parent
    active: back.mode === "focus" && !back.cinematic && back.blurUrl !== "" && back.blurUrl === back.focusUrl
    sourceComponent: Item {
      id: blurItem
      property bool painted: false
      // the picture, small: decoded at most 480×270
      Image {
        id: src
        width: 480
        height: 270
        source: back.blurUrl
        sourceSize: Qt.size(480, 270)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        onStatusChanged: {
          if (status === Image.Ready) { frozen.scheduleUpdate(); blurItem.painted = true; back.view.pictureDrawn(back.shownImg) }
          else {
            blurItem.painted = false
            if (status === Image.Error && source != "") back.view.brokenPicture(back.shownImg, "focus")
          }
        }
      }
      // taken once (and again when the picture changes), not every frame
      ShaderEffectSource {
        id: frozen
        sourceItem: src
        hideSource: true
        live: false
        visible: false
        width: 480
        height: 270
        textureSize: Qt.size(480, 270)
      }
      MultiEffect {
        anchors.fill: parent
        source: frozen
        visible: blurItem.painted
        blurEnabled: true
        blur: 1
        blurMax: 32
        autoPaddingEnabled: false
        saturation: 0.1
      }
      Rectangle {
        anchors.fill: parent
        visible: blurItem.painted
        color: back.shadeSolid
        opacity: back.dim
      }
    }
  }

  // ---- details: the details page's backdrop ----
  Image {
    id: detailPic
    objectName: "detailBackdrop"
    anchors.fill: parent
    readonly property bool wanted: back.mode === "details" && back.detail && !back.cinematic
    visible: wanted && status === Image.Ready
    source: wanted ? view.imageUrl(host.cur.value.backdrop) : ""
    sourceSize: Qt.size(Math.min(960, Math.ceil(back.width * back.dpr)), Math.min(960, Math.ceil(back.height * back.dpr)))
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    onStatusChanged: {
      if (!back.detail) return
      if (status === Image.Error && source != "") view.brokenPicture(host.cur.value.backdrop, "focus")
      else if (status === Image.Ready) view.pictureDrawn(host.cur.value.backdrop)
    }
  }
  Rectangle {
    anchors.fill: parent
    visible: detailPic.visible
    color: back.shadeSolid
    opacity: back.dim
  }

  // ---- your wallpaper, or a picture ----
  Image {
    id: own
    objectName: "ownBackground"
    anchors.fill: parent
    readonly property string url: back.mode === "wallpaper" ? (guide.wallpaperUrl || "")
                                : back.mode === "image" && back.bg.image ? guide.fileUrl(back.bg.image) : ""
    visible: url !== "" && status === Image.Ready
    source: url
    sourceSize: Qt.size(Math.min(1920, Math.ceil(back.width * back.dpr)), Math.min(1920, Math.ceil(back.height * back.dpr)))
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
  }
  Rectangle {
    anchors.fill: parent
    visible: own.visible
    color: back.shadeSolid
    opacity: back.dim
  }

  // ---- a Cinematic details page: its backdrop across the screen ----
  Image {
    id: cine
    objectName: "cinematicBackdrop"
    anchors.fill: parent
    visible: back.cinematic && status === Image.Ready
    source: back.cinematic ? view.imageUrl(host.cur.value.backdrop) : ""
    sourceSize: Qt.size(Math.min(960, Math.ceil(back.width * back.dpr)), Math.min(960, Math.ceil(back.height * back.dpr)))
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    onStatusChanged: {
      if (!back.cinematic) return
      if (status === Image.Error && source != "") view.brokenPicture(host.cur.value.backdrop, "focus")
      else if (status === Image.Ready) view.pictureDrawn(host.cur.value.backdrop)
    }
  }
  Rectangle {
    objectName: "cinematicShade"
    anchors.fill: parent
    visible: cine.visible
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0; color: Qt.rgba(back.shadeColor.r, back.shadeColor.g, back.shadeColor.b, Math.max(0.88, back.dim)) }
      GradientStop { position: 0.6; color: Qt.rgba(back.shadeColor.r, back.shadeColor.g, back.shadeColor.b, Math.max(0.6, back.dim * 0.8)) }
      GradientStop { position: 1; color: Qt.rgba(back.shadeColor.r, back.shadeColor.g, back.shadeColor.b, back.cineLight) }
    }
  }
  Rectangle {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    height: parent.height * 0.55
    visible: cine.visible
    gradient: Gradient {
      GradientStop { position: 0; color: "transparent" }
      GradientStop { position: 0.7; color: Qt.rgba(back.shadeColor.r, back.shadeColor.g, back.shadeColor.b, 0.6) }
    }
  }
}
