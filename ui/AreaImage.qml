import QtQuick

// A picture for one area of the guide (the lower third, the cells, a box…),
// over the area's color and under its text. spec is { url, fit, opacity },
// or null for none. Fits: fill (cover, cropped), fit (whole, letterboxed),
// stretch, tile, center (actual size), and frame: the picture's edges keep
// their size and only the middle stretches, for borders and banner graphics.
// An app's picture also gives decodeW and decodeH: it's decoded no bigger
// than that (the box's size on screen), and status and ratio (its width
// over height) say how it came out. shade ({ color, stops: [[position,
// how dark], ...] }, left to right) darkens it under words, inside the
// box's shape.
Item {
  id: area

  property var spec: null

  readonly property string url: spec && spec.url ? spec.url : ""
  readonly property string fit: spec && spec.fit ? spec.fit : "fill"
  readonly property bool sized: !!spec && spec.decodeW > 0 && spec.decodeH > 0
  readonly property int status: fit === "frame" ? frame.status : picture.status
  readonly property real ratio: picture.implicitHeight > 0 ? picture.implicitWidth / picture.implicitHeight : 0

  visible: url !== ""
  opacity: spec && spec.opacity !== undefined ? spec.opacity : 1
  clip: true

  Image {
    id: picture
    anchors.fill: parent
    visible: area.fit !== "frame"
    source: area.fit !== "frame" ? area.url : ""
    sourceSize: area.sized ? Qt.size(area.spec.decodeW, area.spec.decodeH) : undefined
    fillMode: area.fit === "fit" ? Image.PreserveAspectFit
            : area.fit === "stretch" ? Image.Stretch
            : area.fit === "tile" ? Image.Tile
            : area.fit === "center" ? Image.Pad
            : Image.PreserveAspectCrop
    horizontalAlignment: Image.AlignHCenter
    verticalAlignment: Image.AlignVCenter
    asynchronous: true
    smooth: true
    mipmap: area.fit === "fill" || area.fit === "fit"
  }

  // the shade over it, once it's in: never on its own
  Rectangle {
    id: shade
    anchors.fill: parent
    readonly property var spec: area.spec && area.spec.shade ? area.spec.shade : null
    readonly property color tone: spec ? spec.color : "black"
    readonly property var stops: spec && spec.stops && spec.stops.length >= 2 ? spec.stops : [[0, 0], [1, 0]]
    visible: !!spec && area.status === Image.Ready
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: shade.stops[0][0]; color: Qt.rgba(shade.tone.r, shade.tone.g, shade.tone.b, shade.stops[0][1]) }
      GradientStop { position: shade.stops[1][0]; color: Qt.rgba(shade.tone.r, shade.tone.g, shade.tone.b, shade.stops[1][1]) }
      GradientStop { position: shade.stops[shade.stops.length - 1][0]; color: Qt.rgba(shade.tone.r, shade.tone.g, shade.tone.b, shade.stops[shade.stops.length - 1][1]) }
    }
  }

  BorderImage {
    id: frame
    anchors.fill: parent
    visible: area.fit === "frame"
    source: area.fit === "frame" ? area.url : ""
    // a third of the picture, but never more than a third of the area
    readonly property int edge: Math.round(Math.min(sourceSize.width, sourceSize.height, area.width, area.height) / 3)
    border.left: edge
    border.right: edge
    border.top: edge
    border.bottom: edge
    horizontalTileMode: BorderImage.Stretch
    verticalTileMode: BorderImage.Stretch
    asynchronous: true
    smooth: true
  }
}
