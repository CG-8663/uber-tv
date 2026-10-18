import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import "../Look.js" as Look

// One element's box, drawn from its style (Look.js): its fill (a color or a
// gradient), its border (all round or on some sides), corners and shape, a
// shadow, and a picture over the fill. What's put inside goes on top.
// Shapes other than rect and pill, sides, shadows and masks are made only
// when a style asks for them, so plain boxes (most of the grid) stay cheap.
Item {
  id: box

  property var s: ({})              // the element's style, resolved
  property real unit: 16            // what a length of 1 is, in pixels
  property var image: null          // a picture over the fill ({ url, fit, opacity }), or null

  readonly property real borderWidth: s.border && s.border.width ? Math.max(1, Look.px(s.border.width, unit)) : 0
  readonly property color borderColor: s.border ? s.border.color : "transparent"
  readonly property var sides: s.border && Array.isArray(s.border.sides) ? s.border.sides : null   // null: all round
  readonly property real padding: Look.px(s.padding, unit)
  readonly property string shape: s.shape || "rect"
  readonly property bool curved: shape !== "rect" && shape !== "pill"     // drawn as a path
  readonly property var gradient: s.fill && typeof s.fill === "object" ? s.fill : null
  readonly property color fillColor: gradient ? "transparent" : (s.fill || "transparent")
  // corners in pixels: top left, top right, bottom right, bottom left
  readonly property var corners: {
    var most = Math.min(width, height) / 2
    if (shape === "pill") return [most, most, most, most]
    var list = Array.isArray(s.radius) ? s.radius : [s.radius, s.radius, s.radius, s.radius]
    return list.map(function(r) { return Math.min(most, Math.max(0, Look.px(r, box.unit))) })
  }
  readonly property bool rounded: corners[0] > 0 || corners[1] > 0 || corners[2] > 0 || corners[3] > 0
  readonly property bool someSides: sides !== null && !rounded && !curved
  readonly property int imageStatus: picture.status   // how the picture came out (Image.Ready, Error…)
  readonly property real imageRatio: picture.ratio    // its width over height, once it's in

  // The outline of a slant, arrow or chevron, in pixels, inset by half the border
  function outline(w, h) {
    var i = borderWidth / 2
    var k = s.slant !== undefined ? Look.px(s.slant, unit) : shape === "slant" ? unit : h / 2
    var pts = shape === "slant" ? (k >= 0 ? [[k, 0], [w, 0], [w - k, h], [0, h]] : [[0, 0], [w + k, 0], [w, h], [-k, h]])
            : shape === "arrow" ? [[0, 0], [w - Math.abs(k), 0], [w, h / 2], [w - Math.abs(k), h], [0, h]]
            : [[0, 0], [w - Math.abs(k), 0], [w, h / 2], [w - Math.abs(k), h], [0, h], [Math.abs(k), h / 2]]
    if (shape !== "slant" && k < 0) pts = pts.map(function(p) { return [w - p[0], p[1]] })   // pointing left
    var sx = w > 2 * i ? (w - 2 * i) / w : 0
    var sy = h > 2 * i ? (h - 2 * i) / h : 0
    return "M " + pts.map(function(p) { return (i + p[0] * sx).toFixed(2) + " " + (i + p[1] * sy).toFixed(2) }).join(" L ") + " Z"
  }

  // The fill, border and picture: one layer, so a shadow falls from all of it
  Item {
    id: back
    anchors.fill: parent

    layer.enabled: !!box.s.shadow
    layer.effect: MultiEffect {
      shadowEnabled: true
      shadowColor: box.s.shadow ? box.s.shadow.color : "black"
      blurMax: Math.max(1, Math.round(box.s.shadow ? Look.px(box.s.shadow.blur, box.unit) : 1))
      shadowBlur: 1
      shadowHorizontalOffset: box.s.shadow ? Look.px(box.s.shadow.x, box.unit) : 0
      shadowVerticalOffset: box.s.shadow ? Look.px(box.s.shadow.y, box.unit) : 0
    }

    Rectangle {
      id: plain
      anchors.fill: parent
      visible: !box.curved
      color: box.fillColor
      gradient: box.gradient ? rectGradient : null
      topLeftRadius: box.corners[0]
      topRightRadius: box.corners[1]
      bottomRightRadius: box.corners[2]
      bottomLeftRadius: box.corners[3]
      border.color: box.borderColor
      border.width: box.someSides ? 0 : box.borderWidth

      Gradient {
        id: rectGradient
        orientation: box.gradient && (box.gradient.direction === "right" || box.gradient.direction === "left") ? Gradient.Horizontal : Gradient.Vertical
        GradientStop { position: 0; color: !box.gradient ? "transparent" : box.gradient.direction === "up" || box.gradient.direction === "left" ? box.gradient.to : box.gradient.from }
        GradientStop { position: 1; color: !box.gradient ? "transparent" : box.gradient.direction === "up" || box.gradient.direction === "left" ? box.gradient.from : box.gradient.to }
      }
    }

    // A border on some sides only
    Loader {
      anchors.fill: parent
      active: box.someSides && box.borderWidth > 0
      sourceComponent: Item {
        Rectangle { visible: box.sides.indexOf("top") >= 0; width: parent.width; height: box.borderWidth; color: box.borderColor }
        Rectangle { visible: box.sides.indexOf("bottom") >= 0; y: parent.height - height; width: parent.width; height: box.borderWidth; color: box.borderColor }
        Rectangle { visible: box.sides.indexOf("left") >= 0; width: box.borderWidth; height: parent.height; color: box.borderColor }
        Rectangle { visible: box.sides.indexOf("right") >= 0; x: parent.width - width; width: box.borderWidth; height: parent.height; color: box.borderColor }
      }
    }

    Loader {
      anchors.fill: parent
      active: box.curved
      sourceComponent: Outline { fill: box.fillColor; stroke: box.borderColor; strokeWidth: box.borderWidth; gradientFill: box.gradient }
    }

    AreaImage {
      id: picture
      anchors.fill: parent
      anchors.margins: box.borderWidth
      spec: box.image
      layer.enabled: box.image !== null && (box.rounded || box.curved)
      layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: maskLoader.item
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1
      }
    }

    // The box's shape in white, for cutting the picture to it
    Loader {
      id: maskLoader
      anchors.fill: picture
      active: picture.layer.enabled
      sourceComponent: Item {
        visible: false
        layer.enabled: true
        Rectangle {
          anchors.fill: parent
          visible: !box.curved
          color: "white"
          topLeftRadius: Math.max(0, box.corners[0] - box.borderWidth)
          topRightRadius: Math.max(0, box.corners[1] - box.borderWidth)
          bottomRightRadius: Math.max(0, box.corners[2] - box.borderWidth)
          bottomLeftRadius: Math.max(0, box.corners[3] - box.borderWidth)
        }
        Outline { anchors.fill: parent; visible: box.curved; fill: "white"; stroke: "transparent"; strokeWidth: 0 }
      }
    }
  }

  // A slant, arrow, chevron or your own path (drawn in a 100 by 100 box,
  // stretched to the box)
  component Outline: Shape {
    id: outlineShape
    property color fill: "transparent"
    property color stroke: "transparent"
    property real strokeWidth: 0
    property var gradientFill: null
    readonly property bool own: box.shape === "path"
    preferredRendererType: Shape.CurveRenderer

    transform: Scale { xScale: outlineShape.own ? outlineShape.width / 100 : 1; yScale: outlineShape.own ? outlineShape.height / 100 : 1 }

    ShapePath {
      fillColor: outlineShape.fill
      strokeColor: outlineShape.strokeWidth > 0 ? outlineShape.stroke : "transparent"
      strokeWidth: outlineShape.own ? outlineShape.strokeWidth * 200 / Math.max(1, outlineShape.width + outlineShape.height) : outlineShape.strokeWidth
      joinStyle: ShapePath.MiterJoin
      fillGradient: outlineShape.gradientFill ? shapeGradient : null
      PathSvg { path: outlineShape.own ? (box.s.path || "M0 0 L100 0 L100 100 L0 100 Z") : box.outline(outlineShape.width, outlineShape.height) }
    }

    LinearGradient {
      id: shapeGradient
      readonly property string dir: outlineShape.gradientFill ? outlineShape.gradientFill.direction : "down"
      readonly property real w: outlineShape.own ? 100 : outlineShape.width
      readonly property real h: outlineShape.own ? 100 : outlineShape.height
      x1: dir === "left" ? w : 0
      y1: dir === "up" ? h : 0
      x2: dir === "right" ? w : 0
      y2: dir === "down" ? h : 0
      GradientStop { position: 0; color: outlineShape.gradientFill ? outlineShape.gradientFill.from : "transparent" }
      GradientStop { position: 1; color: outlineShape.gradientFill ? outlineShape.gradientFill.to : "transparent" }
    }
  }
}
