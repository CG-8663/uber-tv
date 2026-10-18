import QtQuick
import "../Look.js" as Look
import "../AppLooks.js" as Looks

// One card on an app's screen, drawn as its line in the presentation model
// (AppLooks.js) says: its box takes the row's picture shape (poster, wide,
// square, logo, circle), and its picture (from the package, or fetched and
// checked by the helper) is the box's own picture, so it's cut to the box's
// corners and shape: filled edge to edge, a logo or a learned square shown
// whole. No picture: its title. Its badge, a ✓ when it's watched, how far
// in, a play mark for something that plays. Its title and line go under it
// on every card, only the selected one, or none (when the top of the
// screen shows the selected title), as its line says. Styled by the APPS
// parts (appCard, which grows when selected, appCardTitle, appCardSub,
// appBadge, appProgress), with their text never under the floor. The
// selected card always carries the guide's focus ring (a theme can style
// the card, but can't take the ring away), and its title stays readable.
// Its picture is the item's for the row's shape (AppLooks.cardImage),
// wanted first while it's selected, then while it's on the screen, then
// the rest; it says when it stops wanting it. While its row is still
// working out its shape, it tells the view how its picture came out (its
// size from the helper, else as it's drawn). Plain text only.
Item {
  id: card

  required property var modelData
  required property int index
  required property var guide
  required property var view
  property var line: ({})                         // its line in the model: cardW, cardH, captionH, fit, round, shape, from
  property bool current: false
  property bool onScreen: true                    // inside its row's and the screen's viewports
  property string ringColor: "#ffffff"           // the focus ring's color (AppLooks.ringColor)
  property string ringHalo: ""                   // its halo, where its color doesn't read (AppLooks.ringHalo)
  property var selectedTitle: ({ color: "", plate: "" })   // the selected title's (AppLooks.titleColor)
  property real u: guide.u
  readonly property real cardW: line.cardW || Math.round(u * 15.5)
  readonly property real cardH: line.cardH || Math.round(cardW * 9 / 16)
  readonly property real captionH: line.captionH || Math.round(u * 3.6)
  readonly property real ringW: Math.max(2, Math.ceil(u * 0.15))
  readonly property var bar: guide.look.appProgress
  // its title and line: under every card, only the selected one, or none
  readonly property bool titled: (line.titles || "below") === "below" || (line.titles === "selected" && current)
  readonly property var titleStyle: Looks.floored(guide.look.appCardTitle, Looks.CARD_TEXT, u, 1)
  readonly property var subStyle: Looks.floored(guide.look.appCardSub, Looks.CARD_TEXT, u, 1)
  readonly property var badgeStyle: Looks.floored(guide.look.appBadge, Looks.CARD_TEXT, u, 1)
  readonly property var liveStyle: Looks.floored(guide.look.liveBadge, Looks.CARD_TEXT, u, 1)
  readonly property bool live: modelData.badge === "LIVE"
  readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
  readonly property var img: Looks.cardImage(modelData, line)
  readonly property string prio: current ? "focus" : onScreen ? "visible" : "rest"
  readonly property string url: view.imageUrl(img)
  // its style, and for a circle, a round box whatever the theme's shape
  readonly property var style: {
    var st = card.current ? guide.look["appCard:current"] : guide.look.appCard
    if (!card.line.round) return st
    var o = {}
    for (var k in st) o[k] = st[k]
    o.shape = "pill"
    delete o.path
    return o
  }

  width: cardW
  height: cardH + captionH
  // the selected card over its neighbours, so nothing beside it covers its ring
  z: current ? 2 : 0
  // the app and view it's made for, taken once: when it's made, or at its
  // first report (a picture already loaded can report while it's made)
  function own() { if (card.ownerEpoch < 0) { card.owner = view.shapeKey; card.ownerEpoch = view.epoch } }
  // what it wants of the view: its picture, at its priority (each change
  // lets go of the one before)
  property var wantedImg: null
  property string wantedPrio: ""
  function rewant() {
    if (card.img === card.wantedImg && card.prio === card.wantedPrio) return
    if (card.wantedImg) view.unwant(card.wantedImg, card.wantedPrio)
    card.wantedImg = card.img
    card.wantedPrio = card.prio
    if (card.img) view.want(card.img, card.prio)
  }
  onImgChanged: rewant()
  onPrioChanged: rewant()
  Component.onCompleted: {
    card.own()
    card.rewant()
    if (!card.img || view.imageFailed(card.img)) report(0)
    else if (view.imageRatio(card.img) > 0 && card.url !== "") report(view.imageRatio(card.img))
  }
  Component.onDestruction: if (card.wantedImg) view.unwant(card.wantedImg, card.wantedPrio)

  // how its picture came out, once, for a row still learning its shape; the
  // app and view it was made for go with it, so a late answer from a card
  // being taken away is never counted for another app or screen
  property string owner: ""
  property int ownerEpoch: -1
  property bool reported: false
  function report(ratio) {
    if (card.reported || !card.line.id || card.line.from !== "auto") return
    card.reported = true
    card.own()
    view.pictureSettled(card.line.id, card.index, ratio, card.line.items ? card.line.items.length : 0, card.owner, card.ownerEpoch)
  }
  Connections {
    target: card.view
    function onImagePathsChanged() {
      if (!card.img) return
      if (card.view.imageFailed(card.img)) card.report(0)
      else if (card.view.imageRatio(card.img) > 0 && card.url !== "") card.report(card.view.imageRatio(card.img))
    }
  }

  Box {
    id: frame
    width: parent.width
    height: card.cardH
    s: card.style
    unit: card.u
    image: card.url !== "" && card.cardW > 0 && card.cardH > 0
           ? { url: card.url, fit: card.line.fit || "fill", opacity: 1,
               decodeW: Math.min(960, Math.ceil(card.cardW * card.dpr)), decodeH: Math.min(960, Math.ceil(card.cardH * card.dpr)) }
           : null
    onImageStatusChanged: {
      if (imageStatus === Image.Ready) { card.report(imageRatio); card.view.pictureDrawn(card.img) }
      else if (imageStatus === Image.Error) { card.report(0); card.view.brokenPicture(card.img, card.prio) }   // fetched again, once
    }
    scale: card.current ? 1 + Looks.growOf(card.style) : 1          // only the selected one grows (at most 15%)
    Behavior on scale { NumberAnimation { duration: 140 } }
    z: card.current ? 2 : 0

    // no picture: its title, large
    Label {
      anchors.fill: parent
      anchors.margins: card.u * 0.8
      visible: frame.imageStatus !== Image.Ready
      text: card.modelData.title
      s: card.titleStyle
      unit: card.u
      sizeFactor: 1.25
      wrapMode: Text.Wrap
      maximumLineCount: 4
      elide: Text.ElideRight
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
    // how far in
    Rectangle {
      visible: card.modelData.progress !== null && card.modelData.progress > 0.01
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.margins: frame.borderWidth
      height: Math.max(3, Look.px(card.bar.height, card.u))
      color: card.bar.track || "transparent"
      Rectangle {
        height: parent.height
        width: parent.width * (card.modelData.progress || 0)
        color: card.bar.fill && typeof card.bar.fill === "object" ? card.bar.fill.from : (card.bar.fill || "transparent")
      }
    }
    Box {
      id: badge
      visible: card.modelData.badge !== ""
      anchors.top: parent.top
      anchors.right: parent.right
      anchors.margins: card.u * 0.4
      width: badgeText.implicitWidth + badge.padding * 2
      height: badgeText.implicitHeight + badge.padding * 0.6
      s: card.live ? card.liveStyle : card.badgeStyle
      unit: card.u
      Label {
        id: badgeText
        anchors.centerIn: parent
        text: card.live ? "● Live" : card.modelData.badge
        s: card.live ? card.liveStyle : card.badgeStyle
        unit: card.u
      }
    }
    // watched
    Box {
      id: watched
      objectName: "watchedMark"
      visible: card.modelData.watched === true
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.margins: card.u * 0.4
      width: Math.max(height, tick.implicitWidth + watched.padding * 2)
      height: tick.implicitHeight + watched.padding * 0.6
      s: card.badgeStyle
      unit: card.u
      Label {
        id: tick
        anchors.centerIn: parent
        text: "✓"
        s: card.badgeStyle
        unit: card.u
      }
    }
    Icon {
      visible: card.modelData.kind === "play"
      anchors.left: parent.left
      anchors.bottom: parent.bottom
      anchors.margins: card.u * 0.6
      name: "play"
      size: Math.round(card.u * 1.6)
      stroke: 2
      color: "white"
    }
    // the guide's focus ring: always on the selected card, just outside it,
    // with a black or white halo where its color doesn't read
    Rectangle {
      objectName: "focusHalo"
      visible: card.current && card.ringHalo !== ""
      anchors.fill: parent
      anchors.margins: -card.ringW * 2
      color: "transparent"
      border.width: card.ringW
      border.color: card.ringHalo || "transparent"
      radius: card.line.round ? width / 2 : frame.rounded ? frame.corners[0] + card.ringW * 2 : 0
      z: 10
    }
    Rectangle {
      objectName: "focusRing"
      visible: card.current
      anchors.fill: parent
      anchors.margins: -card.ringW
      color: "transparent"
      border.width: card.ringW
      border.color: card.ringColor
      radius: card.line.round ? width / 2 : frame.rounded ? frame.corners[0] + card.ringW : 0
      z: 10
    }
  }
  Column {
    y: card.cardH + card.u * 0.6
    width: parent.width
    spacing: card.u * 0.15
    visible: card.titled
    Item {
      width: parent.width
      height: title.implicitHeight
      // where nothing else reads, the selected title gets a backing plate
      Rectangle {
        visible: card.current && card.selectedTitle.plate !== ""
        x: -card.u * 0.25
        y: -card.u * 0.1
        width: Math.min(parent.width, title.implicitWidth) + card.u * 0.5
        height: title.implicitHeight + card.u * 0.2
        radius: card.u * 0.2
        color: card.selectedTitle.plate || "transparent"
      }
      Label {
        id: title
        objectName: "cardTitle"
        width: parent.width
        text: card.modelData.title
        s: card.titleStyle
        unit: card.u
        elide: Text.ElideRight
        color: card.current && card.selectedTitle.color ? card.selectedTitle.color : (s && s.text && s.text.color ? s.text.color : "white")
        opacity: 1
      }
    }
    Label {
      objectName: "cardLine"
      width: parent.width
      visible: text !== ""
      text: card.modelData.meta || card.modelData.subtitle || ""
      s: card.subStyle
      unit: card.u
      elide: Text.ElideRight
    }
  }
}
